#!/usr/bin/env bash
# Instala dependencias locales del backend (Python 3.12) y del frontend (npm).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ Backend: entorno virtual Python 3.12"
cd "$ROOT/backend"
if command -v uv >/dev/null 2>&1; then
  [[ -d .venv ]] || uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r requirements-dev.txt
else
  PY="$(command -v python3.12 || true)"
  if [[ -z "$PY" ]]; then
    echo "✗ Se necesita uv (recomendado) o python3.12. Instale uv: https://docs.astral.sh/uv/" >&2; exit 1
  fi
  [[ -d .venv ]] || "$PY" -m venv .venv
  .venv/bin/pip install -r requirements-dev.txt
fi

echo "→ Frontend: dependencias npm"
cd "$ROOT/frontend"
npm ci

echo "→ (Opcional) navegador para pruebas E2E: cd frontend && npx playwright install chromium"
echo "✓ Listo. Arranque con: ./scripts/dev.sh"
