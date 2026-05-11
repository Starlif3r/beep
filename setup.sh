#!/bin/bash
set -e

echo "╔════════════════════════════════════╗"
echo "║     Beep — One-Click Setup         ║"
echo "╚════════════════════════════════════╝"
echo ""

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 1. Install Python dependencies
echo "📦 Installing Python packages..."
pip3 install --break-system-packages -r requirements.txt 2>/dev/null || pip3 install -r requirements.txt
echo "   ✓ Done."

# 2. Create .env from example if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "📝 Created .env — next step: add your NVIDIA API keys!"
else
    echo "📝 .env already exists."
fi

# 3. Install MemPalace if missing (memory engine)
if ! pip3 show mempalace &>/dev/null; then
    echo "🧠 Installing MemPalace memory engine..."
    pip3 install --break-system-packages mempalace 2>/dev/null || pip3 install mempalace
fi
echo "   ✓ MemPalace ready (https://github.com/bensig/mempalace)"

# 4. Initialize MemPalace palace (auto-creates memory database)
if [ ! -d "$HOME/.mempalace/palace/chroma.sqlite3" ]; then
    echo "🧠 Initializing memory palace..."
    if command -v mempalace &> /dev/null; then
        mkdir -p "$HOME/.mempalace"
        mempalace init "$PROJECT_DIR" --yes --no-llm 2>/dev/null || true
        echo "Y" | mempalace mine "$PROJECT_DIR" 2>/dev/null || true
        echo "   ✓ Memory palace created with project files."
    else
        echo "   ⚠️  mempalace CLI not found — will auto-init on first server start."
    fi
else
    echo "🧠 Memory palace already exists."
fi

# 5. Create identity file
mkdir -p "$HOME/.mempalace"
if [ ! -f "$HOME/.mempalace/identity.txt" ]; then
    cat > "$HOME/.mempalace/identity.txt" << 'EOF'
Beep — AI Butler
A polished, warm AI butler with multi-provider NVIDIA key rotation,
tool calling support for OpenCode, and persistent memory via MemPalace.
Powered by MemPalace (https://github.com/bensig/mempalace).

Capabilities:
- Unlimited NVIDIA API key rotation (round-robin)
- Full tool calling (streaming + non-streaming) with auto-fix
- Ollama fallback backend
- Butler persona: smooth, talkative, proactive
- Persistent memory with MemPalace (ChromaDB + BM25 + Knowledge Graph)
EOF
    echo "   ✓ Identity created."
fi

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  ✅ Setup complete!                          ║"
echo "║                                              ║"
echo "║  Next:                                       ║"
echo "║  1. Edit .env → add your NVIDIA_API_KEYS     ║"
echo "║  2. Run:  bash run.sh                        ║"
echo "║                                              ║"
echo "║  Beep includes:                              ║"
echo "║  • NVIDIA/Ollama backends                    ║"
echo "║  • Butler persona (warm · proactive)         ║"
echo "║  • MemPalace memory (ChromaDB + BM25 + KG)   ║"
echo "║  • Tool calling (streaming + non-streaming)  ║"
echo "║                                              ║"
echo "║  Memory engine: github.com/bensig/mempalace  ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
