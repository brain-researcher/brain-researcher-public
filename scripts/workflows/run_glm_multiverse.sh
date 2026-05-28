#!/bin/bash
# run_glm_multiverse.sh - Orchestrate GLM multiverse analysis using openneuro_glmfitlins workflow
#
# Usage: run_glm_multiverse.sh <dataset_id> <task> [max_models] [--skip-prep] [--skip-fitlins]
#
# This script integrates the external/openneuro_glmfitlins workflow with our multiverse
# spec generator to run multiple GLM variants (HRF basis, confound strategies, high-pass filters).
#
# Steps:
#   1. Download data and create details (1_download_data_create_details.sh)
#   2. Modify/check event files (2_modifycheck_boldeventfiles.sh)
#   3. Create seed BIDS Stats Model spec (3_create_spec_file.sh)
#   4. Generate multiverse variants (fitlins.generate_multiverse_specs)
#   5. Run FitLins for each variant (4_run_fitlins.sh)
#   6. Generate group reports (5_run_groupreport.sh)

set -euo pipefail

# -------------------- Parse Arguments --------------------
show_help() {
    echo "Usage: $0 <dataset_id> <task> [max_models] [--skip-prep] [--skip-fitlins]"
    echo ""
    echo "Arguments:"
    echo "  dataset_id     OpenNeuro dataset ID (e.g., ds000001)"
    echo "  task           Task label (e.g., balloonanalogrisktask)"
    echo "  max_models     Maximum number of multiverse variants (default: 3)"
    echo ""
    echo "Options:"
    echo "  --skip-prep    Skip steps 1-3 (data download, event check, seed spec)"
    echo "  --skip-fitlins Skip FitLins execution (only generate specs)"
    echo "  --dry-run      Print commands without executing"
    echo "  --convergence  Run multiverse convergence analysis (requires nilearn)"
    echo "  -h, --help     Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 ds000001 balloonanalogrisktask"
    echo "  $0 ds000001 balloonanalogrisktask 5"
    echo "  $0 ds000001 balloonanalogrisktask 3 --skip-prep"
}

DATASET=""
TASK=""
MAX_MODELS=3
SKIP_PREP=false
SKIP_FITLINS=false
DRY_RUN=false
RUN_CONVERGENCE=false
CONVERGENCE_THRESHOLD="${CONVERGENCE_THRESHOLD:-3.1}"
CONVERGENCE_ATLAS="${CONVERGENCE_ATLAS:-schaefer-200}"
CONVERGENCE_CONTRAST="${CONVERGENCE_CONTRAST:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-prep)
            SKIP_PREP=true
            shift
            ;;
        --skip-fitlins)
            SKIP_FITLINS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --convergence|--run-convergence)
            RUN_CONVERGENCE=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            if [[ -z "$DATASET" ]]; then
                DATASET="$1"
            elif [[ -z "$TASK" ]]; then
                TASK="$1"
            else
                MAX_MODELS="$1"
            fi
            shift
            ;;
    esac
done

# -------------------- Paths from path_config --------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GLMREPO_DIR="$PROJECT_ROOT/external/openneuro_glmfitlins"
CONFIG_FILE="$GLMREPO_DIR/path_config.json"

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Error: path_config.json not found at $CONFIG_FILE" >&2
    exit 1
fi

# jq is required for parsing JSON config
if ! command -v jq >/dev/null 2>&1; then
    echo "Error: jq not found; install jq to parse $CONFIG_FILE" >&2
    exit 1
fi

data_dir=$(jq -r '.datasets_folder' "$CONFIG_FILE")
repo_dir=$(jq -r '.openneuro_glmrepo' "$CONFIG_FILE")
tmp_folder=$(jq -r '.tmp_folder' "$CONFIG_FILE")

if [[ -z "$data_dir" || "$data_dir" == "null" ]]; then
    echo "Error: datasets_folder not set in $CONFIG_FILE" >&2
    exit 1
fi

if [[ -z "$DATASET" ]] || [[ -z "$TASK" ]]; then
    echo "Error: Missing required arguments"
    show_help
    exit 1
fi

# -------------------- Set Paths --------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GLMFITLINS_DIR="${PROJECT_ROOT}/external/openneuro_glmfitlins"
SCRIPTS_DIR="${GLMFITLINS_DIR}/scripts"
SPECS_DIR="${GLMFITLINS_DIR}/statsmodel_specs/${DATASET}"

# Verify openneuro_glmfitlins exists
if [[ ! -d "$GLMFITLINS_DIR" ]]; then
    echo "Error: openneuro_glmfitlins not found at $GLMFITLINS_DIR"
    exit 1
fi

echo "============================================================"
echo "GLM Multiverse Analysis"
echo "============================================================"
echo "Dataset:     $DATASET"
echo "Task:        $TASK"
echo "Max Models:  $MAX_MODELS"
echo "Skip Prep:   $SKIP_PREP"
echo "Skip FitLins: $SKIP_FITLINS"
echo "Dry Run:     $DRY_RUN"
echo "Convergence: $RUN_CONVERGENCE"
echo "============================================================"

run_cmd() {
    if $DRY_RUN; then
        echo "[DRY RUN] $*"
    else
        echo "[RUNNING] $*"
        "$@"
    fi
}

# -------------------- Steps 1-3: Data Preparation --------------------
if ! $SKIP_PREP; then
    echo ""
    echo ">>> Step 1: Download data and create details"
    run_cmd bash "${SCRIPTS_DIR}/1_download_data_create_details.sh" "$DATASET"

    echo ""
    echo ">>> Step 2: Modify/check event files"
    run_cmd bash "${SCRIPTS_DIR}/2_modifycheck_boldeventfiles.sh" "$DATASET" "$TASK"

    echo ""
    echo ">>> Step 3: Create seed BIDS Stats Model spec"
    run_cmd bash "${SCRIPTS_DIR}/3_create_spec_file.sh" "$DATASET" "$TASK"
else
    echo ""
    echo ">>> Skipping steps 1-3 (--skip-prep)"
fi

# -------------------- Step 4: Generate Multiverse Specs --------------------
echo ""
echo ">>> Step 4: Generate multiverse spec variants"

SEED_SPEC="${SPECS_DIR}/${DATASET}-${TASK}_specs.json"
if [[ ! -f "$SEED_SPEC" ]]; then
    echo "Error: Seed spec not found at $SEED_SPEC"
    echo "Run without --skip-prep or create the spec manually with 3_create_spec_file.sh"
    exit 1
fi

# Create specs directory if needed
mkdir -p "$SPECS_DIR"

# Generate multiverse specs using Python tool
if $DRY_RUN; then
    echo "[DRY RUN] Generate multiverse specs: $MAX_MODELS variants"
else
    # Step 4a: Fetch empirical priors from existing BIDS Stats Models
    echo ">>> Step 4a: Fetching empirical priors for task '${TASK}'..."
    PRIORS_JSON=$(python3 - "$TASK" "$DATASET" << 'PYEOF'
import json
import sys

task = sys.argv[1] if len(sys.argv) > 1 else None
study = sys.argv[2] if len(sys.argv) > 2 else None
try:
    from brain_researcher.services.tools.neurokg_tools import GLMPriorsTool
    tool = GLMPriorsTool()
    result = tool._run(task=task, study_id=study)
    priors = result.data.get("outputs", {}).get("priors", {})
    scanned = result.data.get("outputs", {}).get("scanned", 0)
    if priors and scanned > 0:
        print(json.dumps(priors))
    else:
        print("{}")
except Exception:
    print("{}")
PYEOF
)

    if [[ -z "$PRIORS_JSON" ]]; then
        PRIORS_JSON="{}"
        echo "  No priors found, using defaults"
    else
        echo "  Priors: ${PRIORS_JSON}"
    fi

    # Step 4b: Generate multiverse specs WITH priors
    echo ">>> Step 4b: Generating multiverse specs..."
    python3 << PYEOF
import json
from brain_researcher.services.tools.fitlins_tool import FitLinsGenerateMultiverseSpecsTool

# Parse priors from shell variable
priors_str = '''${PRIORS_JSON}'''
try:
    priors = json.loads(priors_str) if priors_str.strip() and priors_str.strip() != '{}' else None
except json.JSONDecodeError:
    priors = None

if priors:
    print(f"  Using empirical priors: HRF={list(priors.get('hrf_basis', {}).keys())}, "
          f"confounds={list(priors.get('confounds', {}).keys())}, "
          f"high_pass={list(priors.get('high_pass', {}).keys())}")
else:
    print("  Using default grid (no priors)")

tool = FitLinsGenerateMultiverseSpecsTool()
result = tool._run(
    study_id="${DATASET}",
    task="${TASK}",
    seed_spec="${SEED_SPEC}",
    output_dir="${SPECS_DIR}",
    max_models=${MAX_MODELS},
    include_seed=False,
    priors=priors  # Now uses real priors when available!
)
specs = result.data.get('outputs', {}).get('multiverse_specs', [])
print(f"Generated {len(specs)} multiverse specs")
for s in specs:
    print(f"  - {s}")
PYEOF
fi

# List generated specs
echo "Generated spec files:"
ls -la "${SPECS_DIR}/${DATASET}-${TASK}"*_specs.json 2>/dev/null || echo "  (none found)"

# -------------------- Step 6: Write multiverse manifest --------------------
# Create a simple manifest with model_id, spec, output_dir for downstream convergence analysis.
echo ""
echo ">>> Step 6: Writing multiverse manifest"
MANIFEST_PATH="${SPECS_DIR}/multiverse_manifest.csv"
python3 << PYEOF
import csv
from pathlib import Path
import sys

spec_dir = Path("${SPECS_DIR}")
dataset = "${DATASET}"
task = "${TASK}"

specs = sorted(spec_dir.glob(f"{dataset}-{task}*_specs.json"))
if not specs:
    print("No specs found to write manifest", file=sys.stderr)
    sys.exit(1)

rows = []
for spec in specs:
    model_id = spec.stem.replace("_specs", "")
    # Derive output_dir consistent with run_fitlins_direct.sh
    if model_id.endswith("_" + task):
        suffix = ""
    else:
        # model_id pattern: ds000001-balloonanalogrisktask-mv01
        suffix = model_id.split(task)[-1]  # e.g., '-mv01'
    output_dir = Path("${data_dir}") / "analyses" / dataset / f"task-{task}{suffix}"
    rows.append({"model_id": model_id, "spec": str(spec), "output_dir": str(output_dir)})

with open("${MANIFEST_PATH}", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["model_id", "spec", "output_dir"])
    writer.writeheader()
    writer.writerows(rows)

print(f"Manifest written: ${MANIFEST_PATH}")
PYEOF

echo "Manifest path: ${MANIFEST_PATH}"

# Expose manifest and convergence output dir for downstream tools
export MANIFEST_PATH
export CONVERGENCE_OUTPUT_DIR="${data_dir}/analyses/${DATASET}/task-${TASK}-multiverse_summary"


# -------------------- Step 5: Run FitLins for Each Variant --------------------
if ! $SKIP_FITLINS; then
    echo ""
    echo ">>> Step 5: Run FitLins for each multiverse variant"

    # Use our direct script which works with system fitlins
    FITLINS_SCRIPT="${SCRIPT_DIR}/run_fitlins_direct.sh"

    # Run seed model first (no suffix)
    echo ""
    echo "--- Running FitLins for seed model ---"
    run_cmd bash "$FITLINS_SCRIPT" "$DATASET" "$TASK"

    # Run each mvXX variant
    for i in $(seq -f "%02g" 1 "$MAX_MODELS"); do
        SUFFIX="-mv${i}"
        SPEC_FILE="${SPECS_DIR}/${DATASET}-${TASK}${SUFFIX}_specs.json"

        if [[ -f "$SPEC_FILE" ]]; then
            echo ""
            echo "--- Running FitLins for mv${i} ---"
            run_cmd bash "$FITLINS_SCRIPT" "$DATASET" "$TASK" "$SUFFIX"
        else
            echo "Skipping mv${i}: spec file not found"
        fi
    done
else
    echo ""
    echo ">>> Skipping FitLins execution (--skip-fitlins)"
fi

# -------------------- Step 6: Generate Reports --------------------
if ! $SKIP_FITLINS; then
    echo ""
    echo ">>> Step 6: Generate group reports"

    # Report for seed model
    echo ""
    echo "--- Generating report for seed model ---"
    run_cmd bash "${SCRIPTS_DIR}/5_run_groupreport.sh" "$DATASET" "$TASK" || echo "Report generation failed (may need results first)"

    # Reports for each mvXX variant
    for i in $(seq -f "%02g" 1 "$MAX_MODELS"); do
        SUFFIX="-mv${i}"
        SPEC_FILE="${SPECS_DIR}/${DATASET}-${TASK}${SUFFIX}_specs.json"

        if [[ -f "$SPEC_FILE" ]]; then
            echo ""
            echo "--- Generating report for mv${i} ---"
            run_cmd bash "${SCRIPTS_DIR}/5_run_groupreport.sh" "$DATASET" "$TASK" "$SUFFIX" || echo "Report generation failed for mv${i}"
        fi
    done
fi

# -------------------- Step 7: Multiverse Convergence --------------------
if $RUN_CONVERGENCE; then
    echo ""
    echo ">>> Step 7: Multiverse convergence analysis"
    if [[ ! -f "$MANIFEST_PATH" ]]; then
        echo "Manifest not found at ${MANIFEST_PATH}; skipping convergence"
    else
        if $DRY_RUN; then
            echo "[DRY RUN] compute_multiverse_convergence --manifest ${MANIFEST_PATH}"
        else
            python3 << PYEOF
import os
from brain_researcher.core.analysis.multiverse_convergence import compute_multiverse_convergence

manifest_path = os.environ.get("MANIFEST_PATH", "${MANIFEST_PATH}")
output_dir = os.environ.get("CONVERGENCE_OUTPUT_DIR", "${CONVERGENCE_OUTPUT_DIR}")
threshold = float(os.environ.get("CONVERGENCE_THRESHOLD", "${CONVERGENCE_THRESHOLD}"))
atlas = os.environ.get("CONVERGENCE_ATLAS", "${CONVERGENCE_ATLAS}")
contrast = os.environ.get("CONVERGENCE_CONTRAST", "${CONVERGENCE_CONTRAST}") or None

try:
    result = compute_multiverse_convergence(
        manifest_path=manifest_path,
        output_dir=output_dir,
        threshold=threshold,
        atlas=atlas,
        contrast=contrast,
    )
    print("Convergence outputs:", result)
except Exception as exc:
    print(f"Convergence analysis failed: {exc}")
PYEOF
        fi
    fi
fi

echo ""
echo "============================================================"
echo "GLM Multiverse Analysis Complete"
echo "============================================================"
echo ""
echo "Outputs:"
echo "  Specs: ${SPECS_DIR}/"
echo "  Results: Check analyses/${DATASET}/task-${TASK}*/"
echo ""
