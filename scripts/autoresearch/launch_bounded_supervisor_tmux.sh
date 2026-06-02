#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <config.json> [session-name]" >&2
  exit 2
fi

CONFIG_PATH="$(python - <<'PY' "$1"
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
SESSION_NAME="${2:-autoresearch_supervisor}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOGDIR="${REPO_ROOT}/data/autoresearch/logs"

mkdir -p "${LOGDIR}"

if [[ -f /home/ubuntu/.tribe_worker_env.sh ]]; then
  # Discovery workers export runtime env here.
  # shellcheck disable=SC1091
  source /home/ubuntu/.tribe_worker_env.sh >/dev/null 2>&1 || true
elif [[ -f /home/ubuntu/.bashrc ]]; then
  # Legacy fallback.
  # shellcheck disable=SC1091
  source /home/ubuntu/.bashrc >/dev/null 2>&1 || true
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
supervisor_file="${LOGDIR}/bounded_supervisor_${timestamp}.sh"

cat > "${supervisor_file}" <<'EOF_SUPERVISOR'
#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="__CONFIG_PATH__"
REPO_ROOT="__REPO_ROOT__"
LOGDIR="__LOGDIR__"
MAX_RESTARTS="${AUTORESEARCH_MAX_RESTARTS:-3}"
RESTART_DELAY_SECONDS="${AUTORESEARCH_RESTART_DELAY_SECONDS:-5}"

if [[ -f /home/ubuntu/.tribe_worker_env.sh ]]; then
  # shellcheck disable=SC1091
  source /home/ubuntu/.tribe_worker_env.sh >/dev/null 2>&1 || true
elif [[ -f /home/ubuntu/.bashrc ]]; then
  # shellcheck disable=SC1091
  source /home/ubuntu/.bashrc >/dev/null 2>&1 || true
fi

export PYTHONUNBUFFERED=1

restart_count=0
while true; do
  cycle_ts="$(date +%Y%m%d_%H%M%S)"
  cycle_log="${LOGDIR}/supervisor_cycle_${cycle_ts}.log"
  set +e
  python -m brain_researcher.autoresearch.supervisor --config "${CONFIG_PATH}" | tee "${cycle_log}"
  status=$?
  set -e
  if [[ ${status} -eq 0 ]]; then
    exit 0
  fi
  restart_count=$((restart_count + 1))
  if (( restart_count >= MAX_RESTARTS )); then
    echo "bounded shell watchdog exhausted MAX_RESTARTS=${MAX_RESTARTS}" | tee -a "${cycle_log}"
    exit ${status}
  fi
  sleep "${RESTART_DELAY_SECONDS}"
done
EOF_SUPERVISOR

python - <<'PY' "${supervisor_file}" "${CONFIG_PATH}" "${REPO_ROOT}" "${LOGDIR}"
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("__CONFIG_PATH__", sys.argv[2])
text = text.replace("__REPO_ROOT__", sys.argv[3])
text = text.replace("__LOGDIR__", sys.argv[4])
path.write_text(text, encoding="utf-8")
PY

chmod +x "${supervisor_file}"

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
  echo "tmux session already exists: ${SESSION_NAME}" >&2
  echo "supervisor_file=${supervisor_file}"
  exit 1
fi

tmux new-session -d -s "${SESSION_NAME}" "bash '${supervisor_file}'"

echo "session=${SESSION_NAME}"
echo "supervisor_file=${supervisor_file}"
echo "attach=tmux attach -t ${SESSION_NAME}"
