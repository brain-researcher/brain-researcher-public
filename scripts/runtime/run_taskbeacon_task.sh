#!/usr/bin/env bash
set -euo pipefail

mode="qa"
if [[ $# -gt 0 && "${1}" != --* ]]; then
  mode="${1}"
  shift
fi

task_dir="${PWD}"
config_path=""

while [[ $# -gt 0 ]]; do
  case "${1}" in
    --task-dir)
      task_dir="${2:?--task-dir requires a value}"
      shift 2
      ;;
    --config)
      config_path="${2:?--config requires a value}"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Unknown argument: ${1}" >&2
      exit 2
      ;;
  esac
done

task_dir="$(cd "${task_dir}" && pwd)"
cd "${task_dir}"

if [[ ! -f main.py ]]; then
  echo "TaskBeacon task directory does not contain main.py: ${task_dir}" >&2
  exit 2
fi

if [[ -z "${config_path}" ]]; then
  case "${mode}" in
    qa)
      if [[ -f config/br_config_qa.yaml ]]; then
        config_path="config/br_config_qa.yaml"
      else
        config_path="config/config_qa.yaml"
      fi
      ;;
    sim)
      if [[ -f config/br_config_sim.yaml ]]; then
        config_path="config/br_config_sim.yaml"
      elif [[ -f config/config_sampler_sim.yaml ]]; then
        config_path="config/config_sampler_sim.yaml"
      else
        config_path="config/config_scripted_sim.yaml"
      fi
      ;;
    human)
      config_path="config/config.yaml"
      ;;
    *)
      echo "Unsupported TaskBeacon mode: ${mode}" >&2
      exit 2
      ;;
  esac
fi

if [[ ! -f "${config_path}" ]]; then
  echo "TaskBeacon config not found: ${config_path}" >&2
  exit 2
fi

uid_value="$(id -u)"
export MPLBACKEND="${MPLBACKEND:-Agg}"
export PYTHONPATH="/app/runtime_sitecustomize:/app/src:${PYTHONPATH:-}"
export PSYCHOPY_USERAPPDIR="${PSYCHOPY_USERAPPDIR:-${task_dir}/.psychopy}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-${uid_value}}"
mkdir -p "${PSYCHOPY_USERAPPDIR}" "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}" 2>/dev/null || true

python_bin="${BR_TASKBEACON_PYTHON:-python}"
cmd=("${python_bin}" "main.py" "${mode}" "--config" "${config_path}")

if [[ -z "${DISPLAY:-}" && "${mode}" != "human" ]] && command -v xvfb-run >/dev/null 2>&1; then
  screen_spec="${BR_TASKBEACON_XVFB_SCREEN:-1920x1080x24}"
  exec xvfb-run -a -s "-screen 0 ${screen_spec}" "${cmd[@]}"
fi

exec "${cmd[@]}"
