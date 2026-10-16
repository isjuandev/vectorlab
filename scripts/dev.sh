#!/usr/bin/env bash
# Arranca backend (127.0.0.1:8000) y frontend (localhost:3000) y los detiene juntos con Ctrl+C.
# Compatible con el bash 3.2 de macOS (no usa `wait -n`).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACK_PORT="${VECTORLAB_PORT:-8000}"
FRONT_PORT="${FRONTEND_PORT:-3000}"

if [[ ! -x "$ROOT/backend/.venv/bin/python" ]]; then
  echo "✗ Falta el entorno del backend. Ejecute primero: ./scripts/setup.sh" >&2; exit 1
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "✗ Faltan dependencias del frontend. Ejecute primero: ./scripts/setup.sh" >&2; exit 1
fi
for port in "$BACK_PORT" "$FRONT_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✗ El puerto $port ya está en uso:" >&2
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
    exit 1
  fi
done

pids=()
cleanup() {
  trap - INT TERM EXIT
  echo; echo "→ Deteniendo servicios…"
  for pid in "${pids[@]:-}"; do
    [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null || true
  done
  sleep 1
  for pid in "${pids[@]:-}"; do
    [[ -n "$pid" ]] && kill -KILL "$pid" 2>/dev/null || true
  done
  echo "✓ Detenido."
}
trap cleanup INT TERM EXIT

echo "→ Backend en http://127.0.0.1:$BACK_PORT (docs: /docs)"
(cd "$ROOT/backend" && VECTORLAB_PORT="$BACK_PORT" exec .venv/bin/python -m app) &
pids+=("$!")

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$BACK_PORT/api/v1/health" >/dev/null 2>&1; then break; fi
  if ! kill -0 "${pids[0]}" 2>/dev/null; then echo "✗ El backend terminó al arrancar." >&2; exit 1; fi
  sleep 0.5
done

echo "→ Frontend en http://localhost:$FRONT_PORT"
(cd "$ROOT/frontend" && exec ./node_modules/.bin/next dev --hostname localhost --port "$FRONT_PORT") &
pids+=("$!")

# Si cualquiera de los dos procesos termina, se detiene el otro.
while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "✗ Un servicio terminó (pid $pid); se detiene el resto." >&2
      exit 1
    fi
  done
  sleep 1
done
