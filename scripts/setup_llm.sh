#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/backend/.env"
EXAMPLE="$ROOT/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$EXAMPLE" "$ENV_FILE"
  echo "Created $ENV_FILE from .env.example"
  echo "Edit it and set OPENROUTER_API_KEY, then re-run:"
  echo "  bash scripts/setup_llm.sh --verify"
  exit 0
fi

if ! grep -q '^OPENROUTER_API_KEY=.\+' "$ENV_FILE"; then
  echo "OPENROUTER_API_KEY is empty in $ENV_FILE"
  echo "Add your key from https://openrouter.ai/keys"
  exit 1
fi

cd "$ROOT/backend"
if [[ "${1:-}" == "--verify" ]]; then
  uv run python scripts/verify_llm.py --live --agent
else
  uv run python scripts/verify_llm.py
fi
