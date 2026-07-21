#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h}"
cd "$ROOT"
source "$ROOT/.venv/bin/activate" 2>/dev/null || true
python3 scripts/verify.py --require-index
