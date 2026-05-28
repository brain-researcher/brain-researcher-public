#!/usr/bin/env bash
# Legacy stub. Gateway is no longer part of the active local service topology.
set -euo pipefail

cat >&2 <<'MSG'
scripts/services/run_gateway.sh has been retired.
Gateway is no longer part of the active local service topology.

Use one of these active entrypoints instead:
  br serve agent --host 0.0.0.0 --port 8000
  br serve orchestrator --host 0.0.0.0 --port 3001
  br serve kg --host 0.0.0.0 --port 5000
  br serve web --host 0.0.0.0 --port 3000
  bash scripts/mcp/start_http_local.sh
  ./scripts/services/start_services.sh
MSG

exit 1
