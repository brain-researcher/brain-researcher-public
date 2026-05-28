#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
AGENT_URL=${AGENT_URL:-http://localhost:8000}
ORCH_URL=${ORCH_URL:-http://localhost:3001}
POLL_INTERVAL=${POLL_INTERVAL:-5}
POLL_TIMEOUT=${POLL_TIMEOUT:-600}

export BR_PLANNER_MODE=${BR_PLANNER_MODE:-autorun}
export BR_PLANNER_SOURCE=${BR_PLANNER_SOURCE:-catalog}
export AGENT_TOOL_ALLOWLIST=${AGENT_TOOL_ALLOWLIST:-*}
export BR_SANDBOX_ENABLED=${BR_SANDBOX_ENABLED:-true}
export BR_DAG_MAX_CONCURRENCY=${BR_DAG_MAX_CONCURRENCY:-2}
export BR_CACHE_ENABLED=${BR_CACHE_ENABLED:-true}
export BR_CACHE_MODE=${BR_CACHE_MODE:-fast}

read -r -d '' DEFAULT_PAYLOAD <<'JSON' || true
{
  "prompt": "compute demo connectivity",
  "pipeline": "connectivity",
  "parameters": {
    "fmri_img": "/tmp/demo_bold.nii.gz",
    "atlas_name": "Schaefer2018_200"
  }
}
JSON
PAYLOAD="${BR_AGENT_E2E_PAYLOAD:-$DEFAULT_PAYLOAD}"

for bin in curl python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "[run_agent_e2e] Missing dependency: $bin" >&2
    exit 1
  fi
done

printf "[run_agent_e2e] Using ORCH_URL=%s AGENT_URL=%s\n" "$ORCH_URL" "$AGENT_URL"

echo "[run_agent_e2e] Submitting first /run request (should execute plan)"
first_response=$(curl -sS -X POST "$ORCH_URL/run" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD")

export BR_E2E_FIRST_RESPONSE="$first_response"
job_id=$(python3 - <<'PY'
import json, os
resp = os.environ.get('BR_E2E_FIRST_RESPONSE', '')
try:
    data = json.loads(resp)
except json.JSONDecodeError:
    data = {}
print(data.get('job_id', ''))
PY
)
cache_key=$(python3 - <<'PY'
import json, os
resp = os.environ.get('BR_E2E_FIRST_RESPONSE', '')
try:
    data = json.loads(resp)
except json.JSONDecodeError:
    data = {}
value = data.get('cache_key')
print('' if value in (None, 'null') else value)
PY
)
unset BR_E2E_FIRST_RESPONSE

if [[ -z "$job_id" ]]; then
  echo "[run_agent_e2e] Failed to extract job_id from response: $first_response" >&2
  exit 1
fi

echo "[run_agent_e2e] Job $job_id created (cache_key=${cache_key:-none}). Waiting for completion..."

declare -i waited=0
while true; do
  job_payload=$(curl -sS "$ORCH_URL/jobs/$job_id")
  export BR_E2E_JOB_PAYLOAD="$job_payload"
  status=$(python3 - <<'PY'
import json, os
resp = os.environ.get('BR_E2E_JOB_PAYLOAD', '')
try:
    data = json.loads(resp)
except json.JSONDecodeError:
    data = {}
print((data.get('status') or '').upper())
PY
  )
  unset BR_E2E_JOB_PAYLOAD
  [[ -z "$status" ]] && status="UNKNOWN"
  echo "  - job status: $status"
  case "$status" in
    COMPLETED|FAILED|TIMEOUT|CANCELLED)
      break
      ;;
  esac
  if (( waited >= POLL_TIMEOUT )); then
    echo "[run_agent_e2e] Timed out waiting for job completion" >&2
    exit 1
  fi
  sleep "$POLL_INTERVAL"
  waited+=POLL_INTERVAL
done

echo "[run_agent_e2e] First run finished with status $status"

if [[ -n "$cache_key" && "$status" == "COMPLETED" ]]; then
  echo "[run_agent_e2e] Checking cache resolver for key $cache_key"
  curl -sS "$ORCH_URL/api/runs/resolve?key=$cache_key" | python3 - <<'PY'
import json, sys
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    print("Resolver did not return JSON", file=sys.stderr)
    sys.exit(0)
print(json.dumps(data, indent=2))
PY
fi

echo "[run_agent_e2e] Submitting identical /run request to verify cache fast-path"
second_response=$(curl -sS -X POST "$ORCH_URL/run" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD")

export BR_E2E_SECOND_RESPONSE="$second_response"
python3 - <<'PY'
import json, os, sys
resp = os.environ.get('BR_E2E_SECOND_RESPONSE', '')
try:
    data = json.loads(resp)
except json.JSONDecodeError:
    print("Second response not JSON", file=sys.stderr)
    sys.exit(0)
print(json.dumps(data, indent=2))
if not data.get('cached'):
    print("[run_agent_e2e] Warning: second run not served from cache", file=sys.stderr)
PY
unset BR_E2E_SECOND_RESPONSE

echo "[run_agent_e2e] Done"
