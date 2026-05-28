#!/bin/bash
# Start the BR-KG API against the current repo checkout.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../../.." && pwd)

cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# Set Neo4j connection details
export NEO4J_URI=${NEO4J_URI:-bolt://localhost:7687}
export NEO4J_USER=${NEO4J_USER:-neo4j}
export NEO4J_PASSWORD=${NEO4J_PASSWORD:-password}

echo "Starting API with Neo4j at: $NEO4J_URI"

# Start the API
python -m brain_researcher.services.neurokg.api.graph_api
