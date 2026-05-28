#!/bin/bash
# run_fitlins_direct.sh - Run FitLins using system fitlins (conda env)
#
# This is a simplified version of openneuro_glmfitlins/scripts/4_run_fitlins.sh
# that uses the system fitlins binary instead of uv-managed venv.
#
# Usage: run_fitlins_direct.sh [-s smoothing] [-e estimator] <dataset_id> <task> [suffix]

set -euo pipefail

# Prevent runaway thread errors
export MKL_NUM_THREADS=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

show_help() {
    echo "Usage: $0 [-s smoothing] [-e estimator] <dataset_id> <task> [suffix]"
    echo ""
    echo "Options:"
    echo "  -s <smoothing>   Smoothing FWHM:LEVEL:TYPE (default: 5:run:iso)"
    echo "  -e <estimator>   GLM estimator: nilearn or afni (default: nilearn)"
    echo "  -h               Show help"
    echo ""
    echo "Examples:"
    echo "  $0 ds000001 balloonanalogrisktask"
    echo "  $0 ds000001 balloonanalogrisktask -mv01"
    echo "  $0 -s 6:run:iso ds000001 balloonanalogrisktask -mv01"
}

# Defaults
smoothing_type="5:run:iso"
estimator="nilearn"

while getopts "s:e:h" opt; do
    case $opt in
        s) smoothing_type="$OPTARG" ;;
        e) estimator="$OPTARG" ;;
        h) show_help; exit 0 ;;
        \?) show_help; exit 1 ;;
    esac
done
shift $((OPTIND-1))

openneuro_id="${1:-}"
task_label="${2:-}"
task_suffix="${3:-}"

if [[ -z "$openneuro_id" ]] || [[ -z "$task_label" ]]; then
    echo "Error: Missing required arguments"
    show_help
    exit 1
fi

# -------------------- Paths --------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GLMFITLINS_DIR="${PROJECT_ROOT}/external/openneuro_glmfitlins"
config_file="${GLMFITLINS_DIR}/path_config.json"

if [[ ! -f "$config_file" ]]; then
    echo "Error: Config not found: $config_file"
    exit 1
fi

data_dir=$(jq -r '.datasets_folder' "$config_file")
repo_dir=$(jq -r '.openneuro_glmrepo' "$config_file")
scratch_out=$(jq -r '.tmp_folder' "$config_file")

# Build paths
if [[ -n "$task_suffix" ]]; then
    model_json="${repo_dir}/statsmodel_specs/${openneuro_id}/${openneuro_id}-${task_label}${task_suffix}_specs.json"
    task_output_label="${task_label}${task_suffix}"
else
    model_json="${repo_dir}/statsmodel_specs/${openneuro_id}/${openneuro_id}-${task_label}_specs.json"
    task_output_label="${task_label}"
fi

# Prefer local writable copy under datasets_folder/openneuro/<dsid>,
# then fall back to the OpenNeuro mount or input/ layout.
if [[ -d "${data_dir}/openneuro/${openneuro_id}" ]]; then
    bids_data_dir="${data_dir}/openneuro/${openneuro_id}"
elif [[ -d "${data_dir}/openneuro_mount/${openneuro_id}" ]]; then
    bids_data_dir="${data_dir}/openneuro_mount/${openneuro_id}"
elif [[ -d "${data_dir}/input/${openneuro_id}" ]]; then
    bids_data_dir="${data_dir}/input/${openneuro_id}"
else
    echo "Error: BIDS data not found for ${openneuro_id}"
    echo "Checked: ${data_dir}/openneuro/${openneuro_id}"
    echo "Checked: ${data_dir}/openneuro_mount/${openneuro_id}"
    echo "Checked: ${data_dir}/input/${openneuro_id}"
    exit 1
fi

# Check for fMRIPrep derivatives
if [[ -d "${data_dir}/fmriprep/${openneuro_id}/derivatives_alt" ]]; then
    fmriprep_data_dir="${data_dir}/fmriprep/${openneuro_id}/derivatives_alt"
elif [[ -d "${data_dir}/fmriprep/${openneuro_id}/derivatives" ]]; then
    fmriprep_data_dir="${data_dir}/fmriprep/${openneuro_id}/derivatives"
elif [[ -d "${data_dir}/OpenNeuroDerivatives/fmriprep/${openneuro_id}-fmriprep" ]]; then
    fmriprep_data_dir="${data_dir}/OpenNeuroDerivatives/fmriprep/${openneuro_id}-fmriprep"
else
    echo "Error: fMRIPrep derivatives not found for ${openneuro_id}"
    exit 1
fi

scratch_data_dir="${scratch_out}/fitlins/task-${task_output_label}"
output_data_dir="${data_dir}/analyses/${openneuro_id}/task-${task_output_label}"

# Create directories
mkdir -p "${scratch_data_dir}"
mkdir -p "${output_data_dir}"

# Verify model spec exists
if [[ ! -f "$model_json" ]]; then
    echo "Error: Model spec not found: $model_json"
    exit 1
fi

# -------------------- Run FitLins --------------------
echo "============================================================"
echo "Running FitLins"
echo "============================================================"
echo "Study ID:      ${openneuro_id}"
echo "Task:          ${task_label}"
echo "Suffix:        ${task_suffix:-none}"
echo "BIDS dir:      ${bids_data_dir}"
echo "fMRIPrep dir:  ${fmriprep_data_dir}"
echo "Output dir:    ${output_data_dir}"
echo "Scratch dir:   ${scratch_data_dir}"
echo "Model spec:    ${model_json}"
echo "Smoothing:     ${smoothing_type}"
echo "Estimator:     ${estimator}"
echo "============================================================"

fitlins "${bids_data_dir}" "${output_data_dir}" \
    dataset \
    -m "${model_json}" \
    -d "${fmriprep_data_dir}" \
    --ignore "sub-.*_physio\.(json|tsv\.gz)" \
    --drop-missing \
    --database-path "${scratch_data_dir}/bids_db" \
    --space MNI152NLin2009cAsym --desc-label preproc \
    --smoothing "${smoothing_type}" --estimator "${estimator}" \
    --n-cpus 6 \
    --mem-gb 32 \
    -w "${scratch_data_dir}" \
    -vvv

run_status=$?
if [[ $run_status -eq 0 ]]; then
    echo "FitLins completed successfully"
else
    echo "FitLins failed with exit code $run_status"
    exit $run_status
fi
