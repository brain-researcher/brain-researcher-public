#!/usr/bin/env bash
# setup_local_runtime.sh
#
# One-time local setup: creates the brain_researcher conda env, registers
# the Jupyter kernel, and starts a local Jupyter server so the Studio UI
# can execute notebook cells against a real kernel.
#
# After running this script, add the printed vars to .env.local and restart
# the orchestrator.
#
# Usage:
#   bash scripts/setup/setup_local_runtime.sh
#   bash scripts/setup/setup_local_runtime.sh --port 8889  # custom port
#   bash scripts/setup/setup_local_runtime.sh --no-server  # env + kernel only, no server
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${BR_JUPYTER_PORT:-8888}"
START_SERVER=true

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --port) PORT="$2"; shift 2 ;;
    --no-server) START_SERVER=false; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

echo "==> Setting up Brain Researcher runtime environment"
echo "    Repo: $REPO_ROOT"
echo "    Port: $PORT"
echo ""

# Step 1: Create conda env
echo "==> Creating conda environment brain_researcher ..."
conda env create \
  -f "$REPO_ROOT/environment.brain_researcher.yml" \
  --force
echo "    Done."
echo ""

# Step 2: Register Jupyter kernel
echo "==> Registering Jupyter kernel ..."
conda run -n brain_researcher \
  python -m ipykernel install \
    --user \
    --name brain_researcher \
    --display-name "Brain Researcher"
echo "    Kernel registered."
echo ""

# Step 3: Verify core imports
echo "==> Smoke-testing Python runtime ..."
conda run -n brain_researcher python - <<'EOF'
import sys
failed = []
for pkg in ["nibabel", "nilearn", "numpy", "scipy"]:
    try:
        __import__(pkg)
    except ImportError as e:
        failed.append(f"{pkg}: {e}")
if failed:
    for f in failed: print(f"  FAIL: {f}")
    sys.exit(1)
print("  nibabel, nilearn, numpy, scipy — ok")
EOF
echo ""

if [[ "$START_SERVER" == "false" ]]; then
  echo "==> Skipping Jupyter server (--no-server)."
  echo ""
  echo "=== Manual steps ==="
  echo "Start Jupyter manually:"
  echo "  conda activate brain_researcher"
  echo "  jupyter server --no-browser --port $PORT --ip 127.0.0.1"
  exit 0
fi

# Step 4: Start Jupyter server
TOKEN="${BR_STUDIO_JUPYTER_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_hex(16))')}"
LOG_FILE="/tmp/br-jupyter-${PORT}.log"

echo "==> Starting Jupyter server on port $PORT ..."

# Kill any existing server on this port
lsof -ti tcp:"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true

nohup conda run --no-capture-output -n brain_researcher \
  jupyter server \
    --no-browser \
    --port "$PORT" \
    --ip 127.0.0.1 \
    --ServerApp.token="$TOKEN" \
    --ServerApp.root_dir="$HOME" \
    --ServerApp.allow_origin='*' \
  > "$LOG_FILE" 2>&1 &

JUPYTER_PID=$!
echo "    PID: $JUPYTER_PID  log: $LOG_FILE"
echo ""

# Wait for server to be ready
echo "==> Waiting for Jupyter to start ..."
READY=false
for i in $(seq 1 20); do
  if curl -sf "http://127.0.0.1:${PORT}/api?token=${TOKEN}" > /dev/null 2>&1; then
    echo "    Ready."
    READY=true
    break
  fi
  sleep 1
done
if [[ "$READY" == "false" ]]; then
  echo ""
  echo "ERROR: Jupyter server did not start within 20 seconds." >&2
  echo "       Check the log for details: $LOG_FILE" >&2
  echo "       Common causes: port $PORT already in use, conda env missing," >&2
  echo "       or ipykernel not installed in the brain_researcher env." >&2
  exit 1
fi
echo ""

# Step 5: Print config
echo "================================================"
echo "  Add these to your .env.local:"
echo ""
echo "  BR_STUDIO_JUPYTER_BASE_URL=http://127.0.0.1:${PORT}"
echo "  BR_STUDIO_JUPYTER_TOKEN=${TOKEN}"
echo "  BR_STUDIO_JUPYTER_KERNEL_NAME=brain_researcher"
echo "  BR_CONDA_ENV=brain_researcher"
echo "================================================"
echo ""
echo "Then restart the orchestrator:"
echo "  br serve orchestrator"
echo ""
echo "Verify kernel list:"
echo "  jupyter kernelspec list | grep brain_researcher"
