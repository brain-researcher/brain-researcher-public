#!/usr/bin/env bash
# Recompute Yeo17 summaries and IN_REGION edges for OpenNeuro GLM FitLins maps.

set -euo pipefail

show_help() {
    cat <<'EOF'
Usage: run_openneuro_glmfitlins_yeo17_recompute.sh [options]

Options:
  --datasets-root PATH   Root folder with analyses/stat_maps (default: data/openneuro_glmfitlins)
  --manifest PATH        Manifest JSON (default: data/openneuro_glmfitlins/manifest/openneuro_glm_statsmaps.json)
  --summaries-dir PATH   Summary output directory (default: data/openneuro_glmfitlins/summaries)
  --summary-path PATH    Explicit summary CSV path
  --neuromaps-root PATH  Yeo atlas assets directory (default: /app/data/atlases/neuromaps when available)
  --limit N              Limit number of stat maps processed
  --top-k N              Top-K regions per map (default: 17)
  --z-thr FLOAT          Z threshold (default: 2.3)
  --from-summary         Skip summary computation; ingest from existing summary CSV
  --no-resume            Do not resume from existing summary CSV
  --skip-summary         Skip summary write (edges only)
  --skip-write-edges     Skip writing IN_REGION edges
  --skip-ensure-atlas    Skip ensuring Yeo17 atlas nodes exist
  --clear-existing       Delete existing openneuro_glmfitlins Yeo17 edges first
  --dry-run              Print commands without executing
  -h, --help             Show this help

Environment:
  NEO4J_URI, NEO4J_PASSWORD, optional NEO4J_USER, NEO4J_DATABASE
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"

DATASETS_ROOT="${DATASETS_ROOT:-$PROJECT_ROOT/data/openneuro_glmfitlins}"
MANIFEST="${MANIFEST:-$PROJECT_ROOT/data/openneuro_glmfitlins/manifest/openneuro_glm_statsmaps.json}"
SUMMARIES_DIR="${SUMMARIES_DIR:-$PROJECT_ROOT/data/openneuro_glmfitlins/summaries}"
SUMMARY_PATH="${SUMMARY_PATH:-}"
if [[ -z "${NEUROMAPS_ROOT:-}" ]]; then
  if [[ -d "/app/data/atlases/neuromaps" ]]; then
    NEUROMAPS_ROOT="/app/data/atlases/neuromaps"
  else
    NEUROMAPS_ROOT="$PROJECT_ROOT/data/br-kg/raw/neuromaps"
  fi
fi
LIMIT="${LIMIT:-}"
TOP_K="${TOP_K:-17}"
Z_THR="${Z_THR:-2.3}"
FROM_SUMMARY=false
NO_RESUME=false
SKIP_SUMMARY=false
SKIP_WRITE_EDGES=false
SKIP_ENSURE_ATLAS=false
CLEAR_EXISTING=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --datasets-root)
            DATASETS_ROOT="$2"
            shift 2
            ;;
        --manifest)
            MANIFEST="$2"
            shift 2
            ;;
        --summaries-dir)
            SUMMARIES_DIR="$2"
            shift 2
            ;;
        --summary-path)
            SUMMARY_PATH="$2"
            shift 2
            ;;
        --neuromaps-root)
            NEUROMAPS_ROOT="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --top-k)
            TOP_K="$2"
            shift 2
            ;;
        --z-thr)
            Z_THR="$2"
            shift 2
            ;;
        --from-summary)
            FROM_SUMMARY=true
            shift
            ;;
        --no-resume)
            NO_RESUME=true
            shift
            ;;
        --skip-summary)
            SKIP_SUMMARY=true
            shift
            ;;
        --skip-write-edges)
            SKIP_WRITE_EDGES=true
            shift
            ;;
        --skip-ensure-atlas)
            SKIP_ENSURE_ATLAS=true
            shift
            ;;
        --clear-existing)
            CLEAR_EXISTING=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            show_help
            exit 1
            ;;
    esac
done

mkdir -p "$LOG_DIR"

if [[ -z "${NEO4J_URI:-}" || -z "${NEO4J_PASSWORD:-}" ]]; then
    echo "Error: NEO4J_URI and NEO4J_PASSWORD are required." >&2
    exit 1
fi

if [[ "$CLEAR_EXISTING" == "true" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY RUN] clear existing IN_REGION edges for openneuro_glmfitlins"
    else
        python3 - <<'PY'
from neo4j import GraphDatabase
import os

uri = os.environ["NEO4J_URI"]
user = os.environ.get("NEO4J_USER", "neo4j")
password = os.environ["NEO4J_PASSWORD"]
database = os.environ.get("NEO4J_DATABASE", "neo4j")

cypher = """
MATCH (m:StatsMap {source: 'openneuro_glmfitlins'})-[r:IN_REGION {atlas: 'yeo17', edge_source: 'openneuro_glmfitlins'}]->()
DELETE r
"""

driver = GraphDatabase.driver(uri, auth=(user, password))
try:
    with driver.session(database=database) as session:
        session.run(cypher)
finally:
    driver.close()
PY
    fi
fi

ARGS=(
    "--datasets-root" "$DATASETS_ROOT"
    "--manifest" "$MANIFEST"
    "--summaries-dir" "$SUMMARIES_DIR"
    "--neuromaps-root" "$NEUROMAPS_ROOT"
    "--neo4j-uri" "${NEO4J_URI}"
    "--neo4j-user" "${NEO4J_USER:-neo4j}"
    "--neo4j-password" "${NEO4J_PASSWORD}"
    "--neo4j-database" "${NEO4J_DATABASE:-neo4j}"
    "--top-k" "$TOP_K"
    "--z-thr" "$Z_THR"
)

if [[ -n "$SUMMARY_PATH" ]]; then
    ARGS+=(--summary-path "$SUMMARY_PATH")
fi
if [[ -n "$LIMIT" ]]; then
    ARGS+=(--limit "$LIMIT")
fi
if [[ "$FROM_SUMMARY" == "true" ]]; then
    ARGS+=(--from-summary)
fi
if [[ "$NO_RESUME" == "true" ]]; then
    ARGS+=(--no-resume)
fi
if [[ "$SKIP_SUMMARY" == "true" ]]; then
    ARGS+=(--skip-summary)
fi
if [[ "$SKIP_WRITE_EDGES" == "true" ]]; then
    ARGS+=(--skip-write-edges)
fi
if [[ "$SKIP_ENSURE_ATLAS" == "true" ]]; then
    ARGS+=(--skip-ensure-atlas)
fi

RUN_CMD=(python3 scripts/ingest/ingest_openneuro_glmfitlins_yeo17.py "${ARGS[@]}")
LOG_PATH="$LOG_DIR/openneuro_glmfitlins_yeo17_$(date +%Y%m%d_%H%M%S).log"

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] ${RUN_CMD[*]}"
    echo "[DRY RUN] log: $LOG_PATH"
else
    echo "Running Yeo17 recompute (log: $LOG_PATH)"
    "${RUN_CMD[@]}" | tee "$LOG_PATH"
fi
