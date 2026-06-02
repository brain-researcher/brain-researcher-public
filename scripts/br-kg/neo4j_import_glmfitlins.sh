#!/usr/bin/env bash
# Import glmfitlins ingest CSVs into Neo4j using neo4j-admin.
# Usage: ./neo4j_import_glmfitlins.sh [csv_dir] [neo4j_home]

set -euo pipefail

CSV_DIR=${1:-$(dirname "$0")}
NEO4J_HOME=${2:-${NEO4J_HOME:-}}

if [[ -z "$NEO4J_HOME" ]]; then
  echo "Specify NEO4J_HOME or pass path as argument" >&2
  exit 1
fi

"$NEO4J_HOME"/bin/neo4j-admin database import full \
  --nodes="$CSV_DIR/datasets.csv" \
  --nodes="$CSV_DIR/contrasts.csv" \
  --relationships="$CSV_DIR/measures_edges.csv"
