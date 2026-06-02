#!/usr/bin/env bash
# Run OpenNeuro GLM FitLins ingestion into Neo4j (with manifest support).

set -euo pipefail

show_help() {
    cat <<'EOF'
Usage: run_openneuro_glmfitlins_ingest_neo4j.sh [options]

Options:
  --path-config PATH     Path to path_config.local.json
  --manifest PATH        Path to openneuro_glm_statsmaps.json
  --statsmodel-dir PATH  Path to statsmodel_specs
  --limit N              Limit number of stat maps ingested
  --manifest-limit N     Limit number of maps when building manifest
  --checksum             Compute checksums when building manifest
  --mode MODE            Ingest mode: full | sample (default: full)
  --rebuild-manifest     Rebuild manifest before ingest
  --no-links             Skip cross-source link creation
  --dry-run              Print commands without executing
  -h, --help             Show this help

Environment (required for Neo4j):
  NEO4J_URI, NEO4J_PASSWORD, optional NEO4J_USER, NEO4J_DATABASE
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
TMP_DIR="$PROJECT_ROOT/tmp"

PATH_CONFIG="${PATH_CONFIG:-$PROJECT_ROOT/data/openneuro_glmfitlins/path_config.local.json}"
MANIFEST="${MANIFEST:-$PROJECT_ROOT/data/openneuro_glmfitlins/manifest/openneuro_glm_statsmaps.json}"
STATSMODEL_DIR="${STATSMODEL_DIR:-$PROJECT_ROOT/data/openneuro_glmfitlins/statsmodel_specs}"
LIMIT="${LIMIT:-}"
MANIFEST_LIMIT="${MANIFEST_LIMIT:-}"
MODE="${MODE:-full}"
CHECKSUM=false
REBUILD_MANIFEST=false
NO_LINKS=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --path-config)
            PATH_CONFIG="$2"
            shift 2
            ;;
        --manifest)
            MANIFEST="$2"
            shift 2
            ;;
        --statsmodel-dir)
            STATSMODEL_DIR="$2"
            shift 2
            ;;
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --manifest-limit)
            MANIFEST_LIMIT="$2"
            shift 2
            ;;
        --mode)
            MODE="$2"
            shift 2
            ;;
        --checksum)
            CHECKSUM=true
            shift
            ;;
        --rebuild-manifest)
            REBUILD_MANIFEST=true
            shift
            ;;
        --no-links)
            NO_LINKS=true
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

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] would create directories: $LOG_DIR $TMP_DIR"
else
    mkdir -p "$LOG_DIR" "$TMP_DIR"
fi

if [[ -z "${NEO4J_URI:-}" || -z "${NEO4J_PASSWORD:-}" ]]; then
    echo "Error: NEO4J_URI/NEO4J_PASSWORD not set. Neo4j is required." >&2
    exit 1
fi

if [[ "$REBUILD_MANIFEST" == "true" || ! -f "$MANIFEST" ]]; then
    BUILD_CMD=(python3 scripts/tools/once/build_openneuro_glm_manifest.py --config "$PATH_CONFIG" --output "$MANIFEST")
    if [[ "$CHECKSUM" == "true" ]]; then
        BUILD_CMD+=(--checksum)
    fi
    if [[ -n "$MANIFEST_LIMIT" ]]; then
        BUILD_CMD+=(--limit "$MANIFEST_LIMIT")
    fi
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY RUN] ${BUILD_CMD[*]}"
    else
        "${BUILD_CMD[@]}"
    fi
fi

CONFIG_PATH="$TMP_DIR/openneuro_glmfitlins_ingest_$(date +%Y%m%d_%H%M%S).json"
if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] would write config: $CONFIG_PATH"
else
    python3 - "$CONFIG_PATH" "$PATH_CONFIG" "$MANIFEST" "$STATSMODEL_DIR" "$MODE" "$LIMIT" "$NO_LINKS" <<'PY'
import json
import sys

config_path, path_config, manifest, statsmodel_dir, mode, limit, no_links = sys.argv[1:8]

source_cfg = {
    "path_config": path_config,
    "manifest_path": manifest,
    "statsmodel_dir": statsmodel_dir,
    "mode": mode,
}
if limit:
    try:
        source_cfg["limit"] = int(limit)
    except ValueError:
        pass

payload = {
    "sources": {"openneuro_glmfitlins": source_cfg},
}
if no_links == "true":
    payload["create_links"] = False

with open(config_path, "w", encoding="utf-8") as fp:
    json.dump(payload, fp, indent=2)
PY
fi

RUN_CMD=(python3 -m brain_researcher.services.br_kg.etl.load_all --sources openneuro_glmfitlins --config "$CONFIG_PATH")
LOG_PATH="$LOG_DIR/openneuro_glmfitlins_ingest_neo4j_$(date +%Y%m%d_%H%M%S).log"

if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY RUN] ${RUN_CMD[*]}"
    echo "[DRY RUN] log: $LOG_PATH"
else
    echo "Running ingestion (log: $LOG_PATH)"
    "${RUN_CMD[@]}" | tee "$LOG_PATH"
fi
