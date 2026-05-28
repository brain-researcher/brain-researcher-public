#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:3000}" # UI proxy base (Next.js)

start=$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ)
end=$(date -u +%Y-%m-%dT%H:%M:%SZ)

payload=$(cat <<JSON
{
  "start_time": "$start",
  "end_time": "$end",
  "granularity": "minute",
  "services": ["web_ui"],
  "metric_types": ["usage"]
}
JSON
)

echo "Hitting ${BASE_URL}/api/telemetry/metrics ..."
resp=$(curl -s -w "\n%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d "$payload" \
  "$BASE_URL/api/telemetry/metrics")

body="$(echo "$resp" | head -n-1)"
code="$(echo "$resp" | tail -n1)"

if [[ "$code" != "200" ]]; then
  echo "Telemetry metrics check failed (HTTP $code)" >&2
  echo "$body" >&2
  exit 1
fi

echo "Telemetry metrics OK"
echo "$body"
