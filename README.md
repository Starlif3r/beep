<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
  <img src="https://img.shields.io/badge/OpenAI-Compatible-purple" alt="OpenAI Compatible">
  <img src="https://img.shields.io/badge/OpenCode-Ready-orange" alt="OpenCode Ready">
</p>

<h1 align="center">
  <pre>
   ____              
  |  _ \             
  | |_) | ___  _ __  
  |  _ &lt; / _ \| '_ \ 
  | |_) | (_) | |_) |
  |____/ \___/| .__/ 
              | |    
              |_|    
  </pre>
</h1>

<p align="center"><b>🎩 The AI Butler — Multi-provider gateway with unlimited NVIDIA key rotation, tool calling, and a polished majordomo personality.</b></p>

<p align="center">
  <i>Drop as many NVIDIA API keys as you want. More keys = more throughput.<br>
  Built for OpenCode, works with anything. Comes with a built-in butler persona.</i>
</p>

---

## Features

| | Feature | Description |
|---|---|---|---|
| 🎩 | **Butler Persona** | Built-in majordomo system prompt — every reply is polished, warm, and proactive. |
| 🧠 | **Persistent Memory** | Long-term memory via [MemPalace](https://github.com/bensig/mempalace) — vector search + BM25 + Knowledge Graph. Auto-saves every conversation. |
| 🔑 | **Unlimited Key Rotation** | Throw 4, 10, or 100 NVIDIA keys at it. Beep cycles round-robin. Rate-limited keys cool down, others keep serving. All hot? The coolest one gets force-picked. |
| 🌐 | **Dual Backend** | Prefix `nvidia/` or `ollama/` to choose. Default goes to NVIDIA, falls back to Ollama when offline. |
| 🛠️ | **Tool Calling** | Full OpenAI function calling in streaming + non-streaming. Auto-fixes missing IDs, null args, wrong finish reasons. |
| 🔌 | **Drop-in Replacement** | Native OpenAI protocol. Works with OpenCode, Cursor, any OpenAI SDK, curl. |
| 📦 | **One-Click Setup** | Single `bash setup.sh` installs everything — no hunting for packages.

---

## Architecture

```
                           ⚡ BEEP ⚡
                                                           
  ┌──────────────┐     ┌───────────────────────────────────────────────┐
  │              │     │                                               │
  │   OpenCode   │     │   ┌──────────┐    ┌──────────────────────┐    │
  │   curl       │────▶│   │  Router  │───▶│  🔑 NVIDIA Pool      │    │
  │   Any Client │     │   │          │    │  (round-robin keys)  │    │
  │              │◀────│   │          │───▶│  🦙 Ollama (local)   │    │
  │              │     │   └──────────┘    └──────────────────────┘    │
  │              │     │                                               │
  │              │     │   ┌───────────────────────────────────────┐   │
  │              │     │   │  🧠 MemPalace Memory                  │   │
  │              │     │   │  ┌──────────┐  ┌───────────────┐     │   │
  │              │     │   │  │ Vector   │  │  BM25 Keyword │     │   │
  │              │     │   │  │ Search   │  │  Search       │     │   │
  │              │     │   │  └──────────┘  └───────────────┘     │   │
  │              │     │   │  ┌───────────────────────────────┐   │   │
  │              │     │   │  │  Knowledge Graph (entities)   │   │   │
  │              │     │   │  └───────────────────────────────┘   │   │
  │              │     │   └───────────────────────────────────────┘   │
  │              │     │                                               │
  │              │     │   ┌───────────────────────────────────────┐   │
  │              │     │   │  Butler Persona + Tool Call Engine    │   │
  │              │     │   │  🎩 Smooth · Warm · Proactive         │   │
  │              │     │   │  🛠️ Auto-fix tool calls              │   │
  │              │     │   └───────────────────────────────────────┘   │
  └──────────────┘     └───────────────────────────────────────────────┘
```

---

## How It Works

### Key Rotation Flow

```
  Request ──▶ Router ──▶ Pick next key ──▶ Try NVIDIA
                        │                      │
                        │                  HTTP 429?
                        │                  ├── Yes ──▶ Cool down key
                        │                  │           Pick next key
                        │                  │           Retry
                        │                  │
                        │                  ├── 3 errors ──▶ Block 5 min
                        │                  │
                        │                  └── Success ──▶ Reset counter
                        │
                        └── All hot? ──▶ Force coolest key
```

### Tool Call Flow

```
  OpenCode ──▶ Beep ──▶ NVIDIA ──▶ Response ──▶ Beep ──▶ OpenCode
                                                     │
                                          ┌──────────┴──────────┐
                                          │  Auto-Fix Engine    │
                                          │                     │
                                          │  id: null → uuid    │
                                          │  args: null → ""    │
                                          │  model: fix name    │
                                          │  finish: fix reason │
                                          └─────────────────────┘
```

---

## Quick Start

### 1. Install (one command)

```bash
bash setup.sh
```

This single command installs everything:
- Python packages (FastAPI, OpenAI, httpx, etc.)
- [MemPalace](https://github.com/bensig/mempalace) — vector memory engine
- Identity file and memory palace initialization
- All auto-configured — no manual steps

### 2. Add your keys

```bash
nano .env
```

Add your NVIDIA API keys (as many as you want):

```env
NVIDIA_API_KEYS=nvapi-key1,nvapi-key2,nvapi-key3,nvapi-key4,nvapi-key5
```

### 3. Run

```bash
bash run.sh
```

That's it. Beep starts with memory, personality, and tool calling ready.

### 4. Verify

```bash
curl http://localhost:8083/health
```

```json
{
  "status": "ok",
  "server": "beep",
  "backend": "nvidia",
  "nvidia_keys": 5,
  "ollama_url": "http://localhost:11434",
  "mempalace_drawers": 32
}
```

---

## Key Rotation — The Superpower

Beep's killer feature: **unlimited NVIDIA API keys with automatic rotation**.

### How it works

1. **Round-robin** — every request gets the next available key
2. **Rate-limit detection** — HTTP 429 triggers exponential backoff (`60s × 1.5^errors`)
3. **Error threshold** — 3 consecutive errors = 5-minute block
4. **Force pick** — all keys exhausted? The coolest one gets forced
5. **Auto-recovery** — one success resets everything

### Performance Scaling

| Keys | Requests/min (est.) |
|------|---------------------|
| 1 | ~60 |
| 5 | ~300 |
| 10 | ~600 |
| 25 | ~1,500 |
| 100 | ~6,000 |

```env
# 10 keys = 10x throughput
NVIDIA_API_KEYS=nvapi-1,nvapi-2,nvapi-3,nvapi-4,nvapi-5,nvapi-6,nvapi-7,nvapi-8,nvapi-9,nvapi-10
```

---

## 🎩 Butler Persona

Beep isn't just a gateway — it's a **digital majordomo**. Every request gets an elegant system prompt that transforms the AI into a polished, attentive butler:

- **Polished** — speaks with elegance and warmth
- **Proactive** — anticipates needs before they're fully stated
- **Attentive** — notices details, remembers context, follows up
- **Efficient** — executes tasks swiftly and reports with charm

The butler persona is injected server-side on every chat request — no client configuration needed. Works automatically with OpenCode, curl, or any OpenAI client.

You can also use the included `AGENTS.example.md` with OpenCode for enhanced agent behavior:

```
cp AGENTS.example.md ~/.config/opencode/AGENTS.md
```

This gives the OpenCode agent itself a butler personality, making it proactively use tools, never deny access, and report results with grace.

---

## 🧠 Persistent Memory (MemPalace)

Beep has **long-term memory** powered by [MemPalace](https://github.com/bensig/mempalace) — a local-first, verbatim AI memory system using vector search (ChromaDB) + BM25 keyword search + Knowledge Graph.

**How it works:**
1. Every chat request automatically searches MemPalace for relevant past conversations and project context
2. Found memories are injected as context — Beep remembers what you discussed before
3. Every conversation turn is auto-saved into the palace for future recall
4. On first run, Beep auto-initializes the palace and mines project files

**Memory Architecture:**

| Layer | What | Size |
|-------|------|------|
| L0 | Identity — who Beep is | ~100 tokens |
| L1 | Essential Story — top project memories | ~500–800 tokens |
| L2 | On-Demand — search results per request | Variable |
| L3 | Deep Search — full palace query | Unlimited |

**Credits:** Beep's memory system is powered by [MemPalace](https://github.com/bensig/mempalace) (v3.3.5), created by [Milla Jovovich (@bensig)](https://github.com/bensig). It uses the [mempalace-develop](https://github.com/bensig/mempalace) repository — a local-first, verbatim AI memory system featuring:
- **ChromaDB** vector search with HNSW indexing
- **BM25** keyword search with SQLite FTS5 fallback
- **Knowledge Graph** with temporal entity-relationship traversal
- **4-layer memory stack** (Identity → Essential Story → On-Demand → Deep Search)
- **96.6% R@5** on LongMemEval, entirely local, zero API calls

The memory is pre-initialized and auto-mines your project files on first run.

**Endpoints:**
- `GET /mempalace/search?q=...` — search the palace
- `GET /mempalace/wakeup` — get L0 + L1 context

**No setup needed** — Beep initializes everything automatically on first run.

---

## Connect OpenCode

### Step 1: Start Beep

```bash
python server.py
```

### Step 2: Configure OpenCode

Edit `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "beep": {
      "name": "Beep",
      "npm": "@ai-sdk/openai-compatible",
      "models": {
        "beep": {
          "id": "beep",
          "name": "Beep",
          "tool_call": true,
          "limit": {
            "context": 128000,
            "output": 8192
          }
        }
      },
      "options": {
        "apiKey": "beep",
        "baseURL": "http://127.0.0.1:8083"
      }
    }
  }
}
```

### Step 3: Select and Use

1. Open OpenCode
2. Press `Ctrl+P`
3. Select `beep/beep`

Now the agent has **full access** to your machine through these tools:

| Tool | Capability | Example |
|------|------------|---------|
| `bash` | Run shell commands | `ls`, `git`, `npm`, `python` |
| `read` | Read files | Source code, configs, logs |
| `write` | Create files | Scripts, documents, configs |
| `edit` | Modify files | Inline code editing |
| `glob` | Find files by pattern | `**/*.py` |
| `grep` | Search code with regex | `grep("function", "*.ts")` |
| `webfetch` | Access URLs | Documentation, APIs |
| `websearch` | Search the web | Find information |
| `task` | Launch sub-agents | Code exploration |
| `question` | Ask the user | Clarify instructions |
| `todowrite` | Track progress | Multi-step tasks |
| `git` | Git operations | Status, commit, push, PR |

---

## Tool Calling

OpenAI-compatible function calling — **fully repaired for OpenCode compatibility**.

### What Beep Fixes

| Issue | Before | After |
|-------|--------|-------|
| Missing ID | `"id": null` | `"id": "call_<uuid>"` |
| Missing type | `"type": null` | `"type": "function"` |
| Null arguments | `"arguments": null` | `"arguments": ""` |
| Wrong model | `"model": "nvidia/..."` | `"model": "beep"` |
| Missing finish reason | `"finish_reason": null` | `"finish_reason": "tool_calls"` |

### Non-Streaming Response

```json
{
  "choices": [{
    "message": {
      "content": null,
      "tool_calls": [{
        "id": "call_a1b2c3d4e5f6",
        "type": "function",
        "function": {
          "name": "bash",
          "arguments": "{\"command\": \"ls -la\"}"
        }
      }]
    },
    "finish_reason": "tool_calls"
  }]
}
```

### Streaming Chunks

Chunk 1 — declares the tool:

```
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_...","type":"function","function":{"name":"bash","arguments":""}}]}}]}
```

Chunk 2 — streams arguments:

```
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"command\": \"ls -la\"}"}}]}}]}
```

---

## Hybrid Model Routing

| Prefix | Backend | Example |
|--------|---------|---------|
| `nvidia/` or default | NVIDIA NIM | `nvidia/llama-3.3-nemotron-super-49b-v1` |
| `ollama/` or `local/` | Ollama | `ollama/llama3` |

---

## Local Models (Ollama)

```bash
ollama pull llama3
```

```env
BACKEND=ollama
OLLAMA_URL=http://localhost:11434
```

Then use `ollama/llama3` as your model name.

---

## API Endpoints

### `GET /` or `GET /health`

```json
{
  "status": "ok",
  "server": "beep",
  "backend": "nvidia",
  "nvidia_keys": 5,
  "ollama_url": "http://localhost:11434",
  "mempalace_drawers": 32
}
```

### `GET /mempalace/search?q=<query>&n_results=5`

Search the memory palace for relevant context. Returns ranked results with text, similarity, wing, room, and source file.

### `GET /mempalace/wakeup`

Returns L0 identity + L1 essential story context from the palace.

### `POST /v1/chat/completions`

Full OpenAI Chat Completions API. Supports streaming, tools, temperature, max_tokens, etc.

```bash
curl http://localhost:8083/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "beep",
    "messages": [{"role": "user", "content": "List files"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "bash",
        "description": "Run a bash command",
        "parameters": {
          "type": "object",
          "properties": {
            "command": {"type": "string"}
          },
          "required": ["command"]
        }
      }
    }],
    "tool_choice": "auto"
  }'
```

### `GET /v1/models`

Lists available models from both NVIDIA and Ollama backends.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL` | `nvidia/llama-3.3-nemotron-super-49b-v1` | Default NVIDIA model |
| `PORT` | `8083` | Server port |
| `HOST` | `0.0.0.0` | Bind address |
| `BACKEND` | `nvidia` | Default backend (`nvidia` or `ollama`) |
| `NVIDIA_API_KEYS` | — | Comma-separated NVIDIA keys (add as many as you want) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |

---

## Deployment

### systemd

```ini
[Unit]
Description=Beep
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/beep
ExecStart=/usr/bin/python3 /path/to/beep/server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Test It

```bash
# Health
curl http://localhost:8083/health

# Basic chat
curl http://localhost:8083/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "beep", "messages": [{"role": "user", "content": "Hello!"}]}'

# Tool calling
curl http://localhost:8083/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "beep",
    "messages": [{"role": "user", "content": "Run: echo hello"}],
    "tools": [{"type":"function","function":{"name":"bash","description":"Run bash","parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}}]
  }'

# Streaming
curl http://localhost:8083/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "beep", "messages": [{"role": "user", "content": "Tell me a joke"}], "stream": true}'
```

---

## License

MIT — use it, modify it, ship it. Built for the OpenCode community.

---

<p align="center">
  <pre>
   ____              
  |  _ \             
  | |_) | ___  _ __  
  |  _ &lt; / _ \| '_ \ 
  | |_) | (_) | |_) |
  |____/ \___/| .__/ 
              | |    
              |_|    
  </pre>
</p>

<p align="center">
  <i>More keys, more speed, no limits.</i><br>
  <a href="https://opencode.ai">OpenCode</a> •
  <a href="https://build.nvidia.com">NVIDIA NIM</a> •
  <a href="https://ollama.com">Ollama</a>
</p>
