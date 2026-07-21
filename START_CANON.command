#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h}"
cd "$ROOT"
VENV="$ROOT/.venv"
PORT="${CANON_PORT:-8791}"
HOST="${CANON_HOST:-127.0.0.1}"

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"
python -m pip install --quiet -r requirements.txt

if [[ ! -f data/canon-manifest.json || ! -f index/canon-index-manifest.json ]]; then
  "$ROOT/BUILD_CANON_INDEX.command"
fi

python scripts/verify.py --require-index

export CANON_EMBED_URL="${CANON_EMBED_URL:-http://127.0.0.1:8000/v1/embed}"
export CANON_PORT="$PORT"

python -m uvicorn app.canon_server:app --host "$HOST" --port "$PORT" --no-access-log &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT INT TERM

for _ in {1..80}; do
  if curl -fsS "http://$HOST:$PORT/canon/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep .25
done

open "http://$HOST:$PORT/"
printf '\nCANON LIVE · http://%s:%s/\n' "$HOST" "$PORT"
printf 'Press Control-C to stop.\n\n'
wait "$SERVER_PID"
