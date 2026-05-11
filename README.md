<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT">
  <img src="https://img.shields.io/badge/OpenAI-Compatible-purple" alt="OpenAI Compatible">
  <img src="https://img.shields.io/badge/OpenCode-Ready-orange" alt="OpenCode Ready">
</p>

<h1 align="center">
  <pre>
    ⚡ ╦═╗╔═╗╔═╗╔═╗ ⚡
    ╚╗ ║ ║║ ║╚═╗║║║
     ╚╝╚═╝╚═╝╚═╝╚╩╝
    🔋 ╔═╗╔═╗╔═╗ 🔋
      ║║║╠╣ ╠═╣
      ╚╩╝╚  ╩ ╩
  </pre>
</h1>

<p align="center"><b>Multi-provider AI gateway — rotate unlimited NVIDIA keys, fall back to Ollama, talk to any OpenAI client.</b></p>

<p align="center">
  <i>Drop as many NVIDIA API keys as you want. More keys = more throughput.<br>
  Built for OpenCode, works with anything.</i>
</p>

---

## Features

| | Feature | Description |
|---|---|---|
| 🔑 | **Unlimited Key Rotation** | Throw 4, 10, or 100 NVIDIA keys at it. Beep cycles round-robin. Rate-limited keys cool down, others keep serving. All hot? The coolest one gets force-picked. |
| 🌐 | **Dual Backend** | Prefix `nvidia/` or `ollama/` to choose. Default goes to NVIDIA, falls back to Ollama when offline. |
| 🛠️ | **Tool Calling** | Full OpenAI function calling in streaming + non-streaming. Auto-fixes missing IDs, null args, wrong finish reasons. |
| 🧹 | **Content Cleaning** | Strips `<thinking>`, `<reasoning>`, `<example>` tags and `||||` filler from NVIDIA outputs. |
| 🔌 | **Drop-in Replacement** | Native OpenAI protocol. Works with OpenCode, Cursor, any OpenAI SDK, curl. |
| 📦 | **Single File** | ~300 lines of Python. Deploy anywhere — bare metal, VPS, Raspberry Pi, systemd. |

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
  │              │     │   │  Tool Call Engine                     │   │
  │              │     │   │  ┌────────┐  ┌──────────┐  ┌──────┐  │   │
  │              │     │   │  │ Fix ID │  │ Fix Args │  │ Fix  │  │   │
  │              │     │   │  │ null→  │  │ null→""  │  │Model │  │   │
  │              │     │   │  │ uuid   │  │          │  │Name  │  │   │
  │              │     │   │  └────────┘  └──────────┘  └──────┘  │   │
  │              │     │   └───────────────────────────────────────┘   │
  │              │     │                                               │
  │              │     │   ┌───────────────────────────────────────┐   │
  │              │     │   │  Content Filter                       │   │
  │              │     │   │  ✗ <thinking>  ✗ <reasoning>  ✗ |||| │   │
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

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
# More keys = more throughput. No upper limit.
NVIDIA_API_KEYS=nvapi-key1,nvapi-key2,nvapi-key3,nvapi-key4,nvapi-key5
```

### 3. Run

```bash
python server.py
```

```
╔════════════════════════════════════╗
║  Beep                              ║
╚════════════════════════════════════╝
INFO:     Uvicorn running on http://0.0.0.0:8083
```

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
  "ollama_url": "http://localhost:11434"
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

Beep becomes a **polite, proactive AI butler** when you add the `AGENTS.md` instruction file:

```
~/.config/opencode/AGENTS.md
```

This transforms the agent into a digital majordomo — polished, attentive, and smooth. It will greet you with warmth, anticipate your needs, and execute tasks with elegance. Copy `AGENTS.example.md` from this repo to get started.

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
  "ollama_url": "http://localhost:11434"
}
```

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
    ⚡ ╦═╗╔═╗╔═╗╔═╗ ⚡
    ╚╗ ║ ║║ ║╚═╗║║║
     ╚╝╚═╝╚═╝╚═╝╚╩╝
    🔋 ╔═╗╔═╗╔═╗ 🔋
      ║║║╠╣ ╠═╣
      ╚╩╝╚  ╩ ╩
  </pre>
</p>

<p align="center">
  <i>More keys, more speed, no limits.</i><br>
  <a href="https://opencode.ai">OpenCode</a> •
  <a href="https://build.nvidia.com">NVIDIA NIM</a> •
  <a href="https://ollama.com">Ollama</a>
</p>
