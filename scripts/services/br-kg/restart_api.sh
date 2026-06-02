#!/bin/bash
# Restart the BR-KG API against the current repo checkout.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../../.." && pwd)

echo "Stopping existing API processes..."
pkill -f "brain_researcher.services.br_kg.api.graph_api|api.graph_api" || true
sleep 2

echo "Starting API with Neo4j..."
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export NEO4J_URI=${NEO4J_URI:-bolt://localhost:7687}
export NEO4J_USER=${NEO4J_USER:-neo4j}
export NEO4J_PASSWORD=${NEO4J_PASSWORD:-password}
nohup python -m brain_researcher.services.br_kg.api.graph_api > api.log 2>&1 &

echo "Waiting for API to start..."
sleep 3

# Check which port it's running on
API_PID=$!
API_PORT=$(lsof -Pan -p $API_PID -i 2>/dev/null | grep LISTEN | awk '{print $9}' | cut -d: -f2 | head -1)

if [ -z "$API_PORT" ]; then
    API_PORT=5000
fi

echo "API started on port $API_PORT (PID: $API_PID)"
echo "Dash UI has been removed. Use the Next.js UI (port 3000) or Gradio UI (port 7860)."
