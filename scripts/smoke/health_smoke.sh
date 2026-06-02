#!/usr/bin/env bash
set -euo pipefail
BASE_AGENT=${BASE_AGENT:-http://localhost:8000}
BASE_NKG=${BASE_NKG:-http://localhost:5000}
BASE_UI=${BASE_UI:-http://localhost:3000}

fail=0

check(){
  local name=$1 url=$2
  echo "[check] ${name}: ${url}" >&2
  if ! curl -fsS --max-time 5 "$url" >/dev/null; then
    echo "[fail] ${name}" >&2
    fail=1
  else
    echo "[ok] ${name}" >&2
  fi
}

check agent "${BASE_AGENT}/api/health"
check br-kg "${BASE_NKG}/health"
check web-ui "${BASE_UI}/api/health"

exit $fail
