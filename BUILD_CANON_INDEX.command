#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h}"
cd "$ROOT"

EMBED_URL="${CANON_EMBED_URL:-http://127.0.0.1:8000/v1/embed}"
VENV="$ROOT/.venv"

printf '\nCANON — PERMANENT SCRIPTURE INDEX\n'
printf '────────────────────────────────────────────────────────\n'

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if [[ ! -f data/canon-manifest.json ]]; then
  python scripts/fetch_and_build_corpus.py
fi

printf '\nVerifying local ARBITER query embedding\n'
curl -fsS --max-time 30 \
  -H 'Content-Type: application/json' \
  -d '{"texts":["CANON index verification"],"use_freq":true}' \
  "$EMBED_URL" | python -c 'import json,sys; d=json.load(sys.stdin); v=d.get("vectors") or []; assert v and len(v[0])>0; print(f"ARBITER embed PASS · {len(v[0])}D")'

python scripts/build_index.py --embed-url "$EMBED_URL" --timeout 0 --batch-size "${CANON_BUILD_BATCH:-256}"
python scripts/verify.py --require-index

printf '\nCANON INDEX READY\n'
printf 'Runtime search now sends only one question to ARBITER.\n\n'
