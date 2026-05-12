#!/usr/bin/env bash
# boot_substrate.sh — One-command Substrate boot
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "╔══════════════════════════════════════════════╗"
echo "║  Substrate — Omni Indie Hacker Control Plane ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ─── Pre-flight checks ───────────────────────────────────────────────────────

if [ ! -f .env ]; then
    echo "→ No .env found. Copying from .env.example..."
    cp .env.example .env
    echo "⚠  Edit .env with your API keys before using LLM features."
fi

# ─── Load env ────────────────────────────────────────────────────────────────
set -a
source .env
set +a

# ─── Build & boot ────────────────────────────────────────────────────────────

echo "→ Building core services..."
docker compose -f infra/docker-compose.core.yml build

echo "→ Booting substrate..."
docker compose -f infra/docker-compose.core.yml up -d

echo ""
echo "✓ Substrate is running!"
echo ""
echo "   API Gateway:   http://localhost:8000"
echo "   Workflow Eng:  http://localhost:8001"
echo "   LLM Gateway:   http://localhost:8002"
echo "   Event Bus:     http://localhost:8003"
echo "   Redis:         localhost:6379"
echo "   Nginx (omni):  http://localhost:80"
echo ""
echo "   Health check:  curl http://localhost:8000/health"
echo ""

# ─── Show status ──────────────────────────────────────────────────────────────
docker compose -f infra/docker-compose.core.yml ps
