#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "╔════════════════════════════════════╗"
echo "║            Beep                     ║"
echo "╚════════════════════════════════════╝"

# Auto-setup on first run
if [ ! -f .env ]; then
    cp .env.example .env
    echo "📝 Created .env — add your NVIDIA keys, then re-run."
    exit 0
fi

if ! pip show mempalace &>/dev/null; then
    pip install --break-system-packages mempalace 2>/dev/null || pip install mempalace
fi

python3 server.py
