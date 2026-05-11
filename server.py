"""
Beep — Multi-provider AI gateway with automatic key rotation, tool calling,
and local fallback. Drop-in OpenAI-compatible server for OpenCode.

Features:
  • Round-robin across unlimited NVIDIA API keys — more keys = more throughput
  • Auto-detects rate limits (HTTP 429), exponential backoff, 5min cooldown
  • Full OpenAI tool/function calling — streaming & non-streaming
  • Ollama fallback for offline operation — zero config changes
  • Content sanitization — strips <thinking>/<reasoning>/||||

Run:  python server.py
"""

import os, re, json, uuid, time, itertools, asyncio, logging
from dataclasses import dataclass
from typing import Optional, AsyncIterator

import dotenv
from pydantic_settings import BaseSettings
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from openai import AsyncOpenAI
from httpx import AsyncClient

dotenv.load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("beep")


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "extra": "ignore"}
    model: str = "nvidia/llama-3.3-nemotron-super-49b-v1"
    port: int = 8083
    host: str = "0.0.0.0"
    nvidia_api_keys: str = ""
    ollama_url: str = "http://localhost:11434"
    backend: str = "nvidia"

    @property
    def api_keys(self) -> list[str]:
        return [k.strip() for k in self.nvidia_api_keys.split(",") if k.strip()]


settings = Settings()


@dataclass
class _Key:
    key: str
    blocked_until: float = 0.0
    rate_limited_until: float = 0.0
    errors: int = 0


class KeyPool:
    def __init__(self, keys: list[str]):
        if not keys:
            raise RuntimeError("No NVIDIA keys configured. Set NVIDIA_API_KEYS in .env")
        self._pool = [_Key(k) for k in keys]
        self._cycle = itertools.cycle(self._pool)
        log.info("KeyPool: %d key(s) loaded", len(self._pool))

    def pick(self) -> str:
        for _ in range(len(self._pool)):
            k = next(self._cycle)
            now = time.time()
            if now < k.blocked_until or now < k.rate_limited_until:
                continue
            return k.key
        k = next(self._cycle)
        k.blocked_until = k.rate_limited_until = 0.0
        log.warning("All keys exhausted, forcing %s...", k.key[:16])
        return k.key

    def success(self, key: str):
        for k in self._pool:
            if k.key == key:
                k.errors = 0
                break

    def rate_limit(self, key: str, wait: float = 60.0):
        for k in self._pool:
            if k.key == key:
                backoff = wait * (1.5 ** k.errors)
                k.rate_limited_until = time.time() + backoff
                k.errors += 1
                log.warning("Rate-limited key %s, cooling %.0fs (#%d)", key[:16], backoff, k.errors)
                break

    def error(self, key: str):
        for k in self._pool:
            if k.key == key:
                k.errors += 1
                if k.errors >= 3:
                    k.blocked_until = time.time() + 300.0
                    log.warning("Blocked key %s for 5min (%d errors)", k.key[:16], k.errors)
                break


if settings.api_keys:
    pool = KeyPool(settings.api_keys)
else:
    pool = None


NVIDIA_URL = "https://integrate.api.nvidia.com/v1"
_nv_client: Optional[AsyncOpenAI] = None


def _nv(key: str) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=key, base_url=NVIDIA_URL, max_retries=0, timeout=300.0)


def _rotate() -> str:
    global _nv_client
    key = pool.pick()
    _nv_client = _nv(key)
    log.info("Rotated to key %s...", key[:16])
    return key


if pool:
    _nv_client = _nv(pool.pick())


def _ollama_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="ollama",
        base_url=settings.ollama_url.rstrip("/") + "/v1",
        max_retries=0,
        timeout=300.0,
    )


def clean(text: str) -> str:
    text = re.sub(r'<(thinking|reasoning|example)>.*?</\1>', '', text, flags=re.DOTALL)
    text = re.sub(r'\|{2,}', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def clean_msgs(messages: list) -> list:
    for m in messages:
        if isinstance(m.get("content"), str):
            m["content"] = clean(m["content"])
    return messages


def _model_key(model: str) -> str:
    return model.split("/")[0].lower() if "/" in model else settings.backend


def _gen_id() -> str:
    return f"call_{uuid.uuid4().hex[:24]}"


def _fix_tool_calls(tc_list: list) -> bool:
    modified = False
    for t in tc_list:
        fn = t.get("function") or {}
        is_continuation = (
            t.get("id") is None
            and t.get("type") is None
            and fn.get("name") is None
            and fn.get("arguments") is not None
        )
        if is_continuation:
            if fn.get("arguments") is None:
                fn["arguments"] = ""
                modified = True
            continue
        if "id" not in t or t.get("id") is None:
            t["id"] = _gen_id()
            modified = True
        if "type" not in t or t.get("type") is None:
            t["type"] = "function"
            modified = True
        if fn.get("arguments") is None:
            fn["arguments"] = ""
            modified = True
    return modified


async def _call(client: AsyncOpenAI, body: dict, stream: bool):
    api = {k: v for k, v in body.items() if not k.startswith("_")}
    api.pop("stream", None)
    has_tools = "tools" in api and len(api.get("tools", [])) > 0
    log.info("_call model=%s tools=%s messages=%d stream=%s",
             api.get("model"), has_tools, len(api.get("messages", [])), stream)
    return await client.chat.completions.create(**api, stream=stream)


async def _nvidia_call(body: dict, stream: bool):
    global _nv_client
    key = _nv_client.api_key if _nv_client else "none"
    try:
        resp = await _call(_nv_client, body, stream)
        pool.success(key)
        return resp
    except Exception as e:
        err = str(e).lower()
        is_rate = "429" in err or "rate limit" in err or "too many" in err
        if is_rate:
            pool.rate_limit(key)
            _rotate()
            return await _nvidia_call(body, stream)
        pool.error(key)
        raise


async def _nvidia_stream(body: dict, resp_model: str, created: int) -> AsyncIterator[str]:
    key = _nv_client.api_key if _nv_client else "none"
    api = {k: v for k, v in body.items() if not k.startswith("_")}
    api["stream"] = True
    has_tools = "tools" in api and len(api.get("tools", [])) > 0

    for attempt in range(len(pool._pool) + 1):
        try:
            async with AsyncClient(timeout=300.0) as cl:
                async with cl.stream("POST", f"{NVIDIA_URL}/chat/completions",
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json"},
                                     json=api) as resp:

                    if resp.status_code == 429:
                        pool.rate_limit(key)
                        key = pool.pick()
                        continue
                    if resp.status_code != 200:
                        pool.error(key)
                        err_body = await resp.aread()
                        yield _chunk("", created, resp_model,
                                     {"content": f"NVIDIA error {resp.status_code}: {err_body.decode()}"},
                                     "stop")
                        return

                    pool.success(key)
                    had_content = False
                    had_tool_calls = False
                    chunks: list[str] = []

                    async for raw_line in resp.aiter_lines():
                        raw_line = raw_line.strip()
                        if not raw_line.startswith("data: "):
                            continue
                        payload = raw_line[6:]

                        if payload == "[DONE]":
                            log.info("Stream [DONE] had_content=%s had_tool_calls=%s has_tools=%s",
                                     had_content, had_tool_calls, has_tools)
                            if has_tools and not had_content and not had_tool_calls:
                                log.info("Empty response with tools, retrying without tools")
                                body_no_tools = {k: v for k, v in body.items()
                                                 if k not in ("tools", "tool_choice")}
                                async for sse in _nvidia_stream(body_no_tools, resp_model, created):
                                    yield sse
                                return
                            for c in chunks:
                                yield c
                            return

                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            chunks.append(raw_line + "\n\n")
                            continue

                        modified = False

                        if obj.get("model") and obj["model"] != resp_model:
                            obj["model"] = resp_model
                            modified = True

                        for ch in obj.get("choices", []):
                            delta = ch.get("delta", {})
                            cval = delta.get("content")
                            if cval is not None and cval != "":
                                had_content = True
                            tc = delta.get("tool_calls")
                            if tc:
                                had_tool_calls = True
                                if _fix_tool_calls(tc):
                                    modified = True

                        if modified:
                            chunks.append("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n")
                        else:
                            chunks.append(raw_line + "\n\n")

                    for c in chunks:
                        yield c
                    return

        except Exception as e:
            log.error("Stream HTTP error: %s", e)
            pool.error(key)
            yield _chunk("", created, resp_model,
                         {"content": f"Stream error: {e}"}, "stop")
            return


async def _ollama_stream(body: dict, resp_model: str, created: int) -> AsyncIterator[str]:
    cl = _ollama_client()
    try:
        s = await _call(cl, body, True)
        async for chunk in s:
            raw = chunk.model_dump()
            modified = False
            if raw.get("model") and raw["model"] != resp_model:
                raw["model"] = resp_model
                modified = True
            for ch in raw.get("choices", []):
                tc = ch.get("delta", {}).get("tool_calls")
                if tc:
                    if _fix_tool_calls(tc):
                        modified = True
            if modified:
                yield f"data: {json.dumps(raw, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps(raw, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        log.error("Ollama stream error: %s", e)
        yield _chunk("", created, resp_model,
                     {"content": f"Ollama error: {e}"}, "stop")
        yield "data: [DONE]\n\n"


async def _complete(body: dict) -> dict:
    backend = _model_key(body.get("model", ""))
    body["_original_model"] = body.get("model", "unknown")
    if backend in ("ollama", "local"):
        cl = _ollama_client()
        body["model"] = body["model"].split("/", 1)[1] if "/" in body["model"] else body["model"]
        resp = await _call(cl, body, False)
    else:
        if not pool:
            return {"error": "No NVIDIA keys configured"}
        body["model"] = settings.model
        resp = await _nvidia_call(body, False)

    d = resp.model_dump()
    for c in d.get("choices", []):
        msg = c.get("message", {})
        if msg.get("content"):
            msg["content"] = clean(msg["content"])
        tc = msg.get("tool_calls")
        if tc:
            _fix_tool_calls(tc)
            c["finish_reason"] = "tool_calls"
    d["model"] = body["_original_model"]
    return d


def _chunk(id: str, created: int, model: str, delta: dict,
           finish: Optional[str], usage: Optional[dict] = None) -> str:
    obj = {
        'id': id or f"chatcmpl-{uuid.uuid4().hex[:12]}",
        'object': 'chat.completion.chunk',
        'created': created,
        'model': model,
        'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]
    }
    if usage:
        obj['usage'] = usage
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def _stream(body: dict) -> AsyncIterator[str]:
    backend = _model_key(body.get("model", ""))
    body["_original_model"] = body.get("model", "unknown")
    created = int(time.time())
    try:
        if backend in ("ollama", "local"):
            body["model"] = body["model"].split("/", 1)[1] if "/" in body["model"] else body["model"]
            async for sse in _ollama_stream(body, body["_original_model"], created):
                yield sse
        else:
            if not pool:
                yield f"data: {json.dumps({'error': 'No NVIDIA keys'})}\n\n"
                yield "data: [DONE]\n\n"
                return
            body["model"] = settings.model
            resp_model = body["_original_model"]
            async for sse in _nvidia_stream(body, resp_model, created):
                yield sse
    except Exception as e:
        log.error("Stream error: %s", e)
        yield _chunk("", created, body.get("_original_model", ""),
                     {"content": f"Error: {e}"}, "stop")
        yield "data: [DONE]\n\n"


app = FastAPI(title="Beep — AI Server")


@app.get("/health")
@app.get("/")
async def root():
    return {
        "status": "ok",
        "server": "beep",
        "backend": settings.backend,
        "nvidia_keys": len(settings.api_keys) if settings.api_keys else 0,
        "ollama_url": settings.ollama_url,
    }


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat(raw: Request):
    body = await raw.json()
    log.info("Request body: %s",
             json.dumps({k: v for k, v in body.items() if k != "messages"}, default=str))
    clean_msgs(body.get("messages", []))
    if body.get("stream", False):
        return StreamingResponse(
            _stream(body),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )
    result = await _complete(body)
    return JSONResponse(result)


@app.get("/v1/models")
async def models():
    items = []
    if settings.api_keys:
        items.append({
            "id": settings.model.split("/")[-1],
            "object": "model",
            "created": int(time.time()),
            "owned_by": "nvidia",
        })
    try:
        async with AsyncClient() as cl:
            r = await cl.get(f"{settings.ollama_url}/api/tags")
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    name = m.get("name", "unknown").replace(":", "-")
                    items.append({
                        "id": f"local/{name}",
                        "object": "model",
                        "created": m.get("modified_at", int(time.time())),
                        "owned_by": "ollama",
                    })
    except Exception:
        pass
    return {"object": "list", "data": items}


if __name__ == "__main__":
    import uvicorn
    print("╔════════════════════════════════════╗")
    print("║  Beep                               ║")
    print("╚════════════════════════════════════╝")
    uvicorn.run("server:app", host=settings.host, port=settings.port, log_level="info")
