#!/usr/bin/env bash
# Quick smoke tests for /agent/plan/export/nipype.
set -euo pipefail

AGENT_URL=${AGENT_URL:-http://localhost:8000}
WORKDIR_BASE=${WORKDIR_BASE:-/tmp/workflows}

require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1" >&2; exit 1; }; }

require_cmd curl
require_cmd python

check_health() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$AGENT_URL/health")
  if [[ "$code" != "200" ]]; then
    echo "Agent health check failed (code=$code) at $AGENT_URL/health" >&2
    exit 1
  fi
}

post_plan() {
  local payload="$1"; shift
  local expect_http="$1"; shift
  local name="$1"; shift

  local resp
  resp=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$AGENT_URL/agent/plan/export/nipype" \
    -H 'Content-Type: application/json' --data "$payload")
  local http_code
  http_code=$(echo "$resp" | awk -F: '/HTTP_CODE/ {print $2}')
  local body
  body=$(echo "$resp" | sed '/HTTP_CODE:/d')

  if [[ "$http_code" != "$expect_http" ]]; then
    echo "[$name] Unexpected HTTP code: $http_code" >&2
    echo "$body" >&2
    exit 1
  fi

  echo "$body"
}

validate_success_body() {
  local name="$1"; shift
  local body_json="$1"; shift
  CASE_NAME="$name" BODY_JSON="$body_json" python - <<'PY'
import json, sys, ast, pathlib, os
body = json.loads(os.environ["BODY_JSON"])
name = os.environ.get("CASE_NAME", "case")
if body.get("status") != "success":
    sys.stderr.write(f"[{name}] status != success: {body}\n")
    sys.exit(1)
wf = body.get("workflow_file")
if not wf:
    sys.stderr.write(f"[{name}] missing workflow_file\n")
    sys.exit(1)
path = pathlib.Path(wf)
if not path.exists():
    sys.stderr.write(f"[{name}] workflow file not found: {wf}\n")
    sys.exit(1)
try:
    ast.parse(path.read_text())
except Exception as e:
    sys.stderr.write(f"[{name}] workflow syntax error: {e}\n")
    sys.exit(1)
print(f"[{name}] OK: {wf}")
PY
}

run_case_success() {
  local name="$1"; shift
  local payload="$1"; shift
  local body
  body=$(post_plan "$payload" "200" "$name")
  validate_success_body "$name" "$body"
}

run_case_failure() {
  local name="$1"; shift
  local payload="$1"; shift
  local body
  body=$(post_plan "$payload" "400" "$name")
  echo "[$name] Expected failure OK"
  echo "$body"
}

main() {
  check_health

  run_case_success "simple-bet" "$(cat <<JSON
{
  "plan": {
    "plan_id": "smoke-bet-001",
    "domain": "neuroimaging",
    "modality": ["fmri"],
    "dag": {
      "steps": [
        {
          "id": "bet",
          "tool": "fsl.bet",
          "consumes": {"in": "volume_3d"},
          "produces": {"bet_out": "volume_3d"},
          "params": {"frac": 0.4},
          "runtime_kind": "container"
        }
      ],
      "artifacts": []
    },
    "version": 1,
    "schema_version": "1.0",
    "resolvable": true
  },
  "options": {
    "plugin": "Linear",
    "output_dir": "${WORKDIR_BASE}",
    "strict": false
  }
}
JSON
)"

  run_case_success "multi-step" "$(cat <<JSON
{
  "plan": {
    "plan_id": "smoke-fmri-preproc-001",
    "domain": "neuroimaging",
    "modality": ["fmri"],
    "dag": {
      "steps": [
        {
          "id": "bet",
          "tool": "fsl.bet",
          "consumes": {"raw": "volume_3d"},
          "produces": {"bet_out": "volume_3d"},
          "params": {"frac": 0.35},
          "runtime_kind": "container"
        },
        {
          "id": "flirt",
          "tool": "fsl.flirt",
          "consumes": {"bet_out": "volume_3d", "ref": "volume_3d"},
          "produces": {"flirt_out": "volume_3d"},
          "params": {},
          "runtime_kind": "container"
        },
        {
          "id": "smooth",
          "tool": "fsl.smooth",
          "consumes": {"flirt_out": "volume_3d"},
          "produces": {"smooth_out": "volume_3d"},
          "params": {"fwhm": 6},
          "runtime_kind": "container"
        }
      ],
      "artifacts": []
    },
    "version": 1,
    "schema_version": "1.0",
    "resolvable": true
  },
  "options": {
    "plugin": "MultiProc",
    "plugin_args": {"n_procs": 2},
    "output_dir": "${WORKDIR_BASE}",
    "strict": false
  }
}
JSON
)"

  run_case_success "mixed-runtime-skip" "$(cat <<JSON
{
  "plan": {
    "plan_id": "smoke-mixed-001",
    "domain": "neuroimaging",
    "modality": ["fmri"],
    "dag": {
      "steps": [
        {
          "id": "bet",
          "tool": "fsl.bet",
          "consumes": {"in": "volume_3d"},
          "produces": {"bet_out": "volume_3d"},
          "params": {},
          "runtime_kind": "container"
        },
        {
          "id": "api-step",
          "tool": "api.call",
          "consumes": {"bet_out": "volume_3d"},
          "produces": {"api_out": "volume_3d"},
          "params": {},
          "runtime_kind": "api"
        },
        {
          "id": "smooth",
          "tool": "fsl.smooth",
          "consumes": {"bet_out": "volume_3d"},
          "produces": {"smooth_out": "volume_3d"},
          "params": {"fwhm": 5},
          "runtime_kind": "container"
        }
      ],
      "artifacts": []
    },
    "version": 1,
    "schema_version": "1.0",
    "resolvable": true
  },
  "options": {
    "plugin": "Linear",
    "output_dir": "${WORKDIR_BASE}",
    "strict": false
  }
}
JSON
)"

  run_case_failure "mixed-runtime-strict" "$(cat <<JSON
{
  "plan": {
    "plan_id": "smoke-mixed-strict-001",
    "domain": "neuroimaging",
    "modality": ["fmri"],
    "dag": {
      "steps": [
        {
          "id": "api-step",
          "tool": "api.call",
          "consumes": {"x": "volume_3d"},
          "produces": {"y": "volume_3d"},
          "params": {},
          "runtime_kind": "api"
        }
      ],
      "artifacts": []
    },
    "version": 1,
    "schema_version": "1.0",
    "resolvable": true
  },
  "options": {
    "plugin": "Linear",
    "output_dir": "${WORKDIR_BASE}",
    "strict": true
  }
}
JSON
)"

  echo "All smoke tests passed."
}

main "$@"
