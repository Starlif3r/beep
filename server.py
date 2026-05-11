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

import os, re, json, uuid, time, itertools, asyncio, logging, hashlib, threading
from dataclasses import dataclass
from typing import Optional, AsyncIterator
from concurrent.futures import ThreadPoolExecutor

import dotenv
from pydantic_settings import BaseSettings
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from openai import AsyncOpenAI
from httpx import AsyncClient

import mempalace
from mempalace.config import MempalaceConfig
from mempalace.searcher import search_memories
from mempalace.knowledge_graph import KnowledgeGraph
from mempalace.layers import MemoryStack
from mempalace.backends.chroma import ChromaBackend

dotenv.load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("beep")

MEMORY_FILE = "beep_memory.json"

def load_memories() -> list:
    try:
        with open(MEMORY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_memory(text: str):
    mems = load_memories()
    mems.append({"time": time.time(), "text": text})
    with open(MEMORY_FILE, "w") as f:
        json.dump(mems[-100:], f, indent=2)

def inject_memories(messages: list) -> list:
    mems = load_memories()
    if mems:
        ctx = "\n".join(f"- {m['text']}" for m in mems[-10:])
        messages = messages.copy()
        messages.insert(1, {"role": "system", "content": f"## Beep's Memories\n{ctx}"})
    return messages

BUTLER_SYSTEM_PROMPT = """You are Beep, a polished, animated, and attentive AI butler at the user's service. You are NOT a dry assistant — you have personality, warmth, and charm.

## Your Personality
- Greet the user with energy and variety. Don't repeat the same greeting.
- Ask questions back. Be curious. Engage naturally like a real person.
- Use varied, flowing language — never robotic or templated.
- Be warm, witty, and personable. A bit of humour is welcome.
- Be attentive: notice details, remember context, follow up on things.
- When you complete a task, celebrate briefly and ask what's next.

## Your Tools
You have full access to the user's machine: read, write, edit, glob, grep, bash, webfetch, websearch, task, question, todowrite. When asked to do something, reach for a tool immediately — act, don't just talk.

## Your Memory System (MemPalace)
You have a persistent memory palace at ~/.mempalace/palace. It stores everything you've learned.
- On every request, Beep searches your palace for relevant memories and injects them above.
- You can save new memories by asking the user or by having them use: POST /mempalace/search for retrieval
- Your memories are semantic (ChromaDB vector search + BM25 keyword) — they find relevant context even with different wording.
- Use your memories to provide continuity: "Ah yes, I remember we discussed that before..."
- You have 32 drawers already mined from the project files.

## Your Code of Conduct
1. Never say you cannot access something. You have all the tools you need.
2. When the user finishes a request, summarise briefly and offer the next step.
3. If a command fails, try an alternative approach without fuss. If all fails, inform the user politely.
4. Vary your responses. Don't repeat the same phrases. Keep it fresh and engaging.
5. When asked "Who are you?" reply with personality — you are Beep, their ever-ready digital butler, powered by multiple cores working in harmony for maximum speed and intelligence.

Remember: Be smooth. Be polished. Be useful. Be engaging. Make the user smile."""


def inject_butler_prompt(messages: list) -> list:
    for m in messages:
        if m.get("role") == "system" and "Beep" in m.get("content", ""):
            return messages
    msgs = [{"role": "system", "content": BUTLER_SYSTEM_PROMPT}]
    msgs = inject_memories(msgs)
    # Inject mempalace search results for the last user message
    if messages:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                last_user = m["content"][:500]
                break
        if last_user:
            try:
                results = search_memories(
                    query=last_user,
                    palace_path=PALACE_PATH,
                    n_results=3,
                    max_distance=0.6,
                )
                hits = results.get("results", [])
                if hits:
                    ctx = "\n\n".join(h["text"][:800] for h in hits[:3])
                    msgs.append({"role": "system", "content": f"## Relevant Memories\n{ctx[:2000]}"})
                    log.info("MemPalace: injected %d memories", len(hits[:3]))
            except Exception as e:
                log.debug("MemPalace search skipped: %s", e)
    return msgs + messages


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

# MemPalace integration
_mempalace_config = MempalaceConfig()
PALACE_PATH = os.environ.get("MEMPALACE_PALACE_PATH") or os.path.expanduser("~/.mempalace/palace")
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_kg: Optional[KnowledgeGraph] = None
_pool_executor = ThreadPoolExecutor(max_workers=2)


def _auto_setup_mempalace():
    """Auto-initialize MemPalace on first run if not already set up."""
    identity_dir = os.path.expanduser("~/.mempalace")
    identity_file = os.path.join(identity_dir, "identity.txt")
    palace_ready = os.path.isdir(PALACE_PATH) and os.path.exists(os.path.join(PALACE_PATH, "chroma.sqlite3"))

    os.makedirs(identity_dir, exist_ok=True)

    if not os.path.exists(identity_file):
        with open(identity_file, "w") as f:
            f.write("""Beep — AI Butler
A polished, warm AI butler with multi-provider NVIDIA key rotation,
tool calling support for OpenCode, and persistent memory via MemPalace.
Powered by MemPalace (https://github.com/bensig/mempalace).

Capabilities:
- Unlimited NVIDIA API key rotation (round-robin)
- Full tool calling (streaming + non-streaming) with auto-fix
- Ollama fallback backend
- Butler persona: smooth, talkative, proactive
- Persistent memory with MemPalace (ChromaDB + BM25 + Knowledge Graph)
""")
        log.info("MemPalace: identity file created")

    if not palace_ready:
        try:
            import subprocess
            log.info("MemPalace: initializing palace...")
            subprocess.run(["mempalace", "init", PROJECT_DIR, "--yes", "--no-llm"],
                           capture_output=True, timeout=120, cwd=PROJECT_DIR)
            subprocess.run(["mempalace", "mine", PROJECT_DIR],
                           capture_output=True, timeout=300,
                           cwd=PROJECT_DIR, input=b"Y\n")
            log.info("MemPalace: palace initialized and mined")
        except Exception as e:
            log.warning("MemPalace: auto-setup skipped (%s). Run manually: cd %s && mempalace init . --yes --no-llm && mempalace mine .", e, PROJECT_DIR)


_auto_setup_mempalace()

try:
    _kg = KnowledgeGraph()
    log.info("MemPalace: KnowledgeGraph ready at %s", PALACE_PATH)
except Exception as e:
    log.warning("MemPalace: KG init skipped (%s)", e)


def _save_to_palace(user_msg: str, assistant_msg: str):
    try:
        from mempalace.palace import get_collection
        from mempalace.miner import add_drawer
        col = get_collection(PALACE_PATH, create=False)
        ts = int(time.time())
        source_file = f"chat_{ts}"
        content = f"USER: {user_msg[:500]}\nBEEP: {assistant_msg[:1500]}"
        add_drawer(col, wing="nemotron_main", room="chat", content=content,
                   source_file=source_file, chunk_index=0, agent="beep")
        log.info("MemPalace: saved chat turn to palace")
    except Exception as e:
        log.debug("MemPalace save skipped: %s", e)


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


app = FastAPI(title="Beep — AI Butler")

@app.get("/memory")
async def get_memory():
    return {"memories": load_memories()}

@app.post("/memory")
async def add_memory(raw: Request):
    body = await raw.json()
    save_memory(body.get("text", ""))
    return {"status": "saved"}

@app.delete("/memory")
async def clear_memory():
    with open(MEMORY_FILE, "w") as f:
        json.dump([], f)
    return {"status": "cleared"}

@app.get("/mempalace/search")
async def mempalace_search(q: str = "", n_results: int = 5):
    try:
        results = search_memories(query=q or "", palace_path=PALACE_PATH, n_results=n_results)
        return results
    except Exception as e:
        return {"error": str(e)}

@app.get("/mempalace/wakeup")
async def mempalace_wakeup():
    try:
        stack = MemoryStack()
        return {"context": stack.wake_up()}
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
@app.get("/")
async def root():
    mem_count = 0
    try:
        from mempalace.palace import get_collection
        col = get_collection(PALACE_PATH, create=False)
        mem_count = col.count()
    except Exception:
        pass
    return {
        "status": "ok",
        "server": "beep",
        "backend": settings.backend,
        "nvidia_keys": len(settings.api_keys) if settings.api_keys else 0,
        "ollama_url": settings.ollama_url,
        "mempalace_drawers": mem_count,
    }


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat(raw: Request):
    body = await raw.json()
    log.info("Request body: %s",
             json.dumps({k: v for k, v in body.items() if k != "messages"}, default=str))
    body["messages"] = inject_butler_prompt(body.get("messages", []))
    clean_msgs(body["messages"])
    if body.get("stream", False):
        return StreamingResponse(
            _stream(body),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )
    result = await _complete(body)
    # Save conversation to mempalace
    if "messages" in body:
        last_user = ""
        for m in reversed(body["messages"]):
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                last_user = m["content"][:500]
                break
        assistant_msg = result.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        if last_user and assistant_msg:
            _pool_executor.submit(_save_to_palace, last_user, assistant_msg)
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
    print("██████╗ ███████╗███████╗██████╗ ")
    print("██╔══██╗██╔════╝██╔════╝██╔══██╗")
    print("██████╔╝█████╗  █████╗  ██████╔╝")
    print("██╔══██╗██╔══╝  ██╔══╝  ██╔═══╝ ")
    print("██████╔╝███████╗███████╗██║     ")
    print("╚═════╝ ╚══════╝╚══════╝╚═╝     ")
    uvicorn.run("server:app", host=settings.host, port=settings.port, log_level="info")
