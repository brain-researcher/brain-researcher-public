#!/bin/bash

# =============================================================================
# Clean Service Launcher for Brain Researcher
# =============================================================================
# This script launches Brain Researcher services without Neurodesk interference
# by temporarily cleaning the environment of Singularity variables.
# =============================================================================

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Brain Researcher Clean Service Launcher${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Get the project root directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"
ENV_FILE="$PROJECT_ROOT/.env"

load_env_file() {
    local file_path="$1"
    if [[ -f "$file_path" ]]; then
        echo -e "${GREEN}✓ Loading environment overrides from ${file_path}${NC}"
        set -a
        source "$file_path"
        set +a
    else
        echo -e "${YELLOW}No ${file_path} file detected. Using shell environment values.${NC}"
    fi
}

# Load repo-level environment overrides (only root .env)
load_env_overlays() {
    load_env_file "$PROJECT_ROOT/.env"
    load_env_file "$PROJECT_ROOT/.env.local"
}

# Function to display usage
show_usage() {
    echo "Usage: $0 [service] [options]"
    echo ""
    echo "Services:"
    echo "  kg        - Launch BR-KG service"
    echo "  agent     - Launch Gateway (Agent HTTP + Orchestrator WS on 8000)"
    echo "  gateway   - Alias for agent (preferred)"
    echo "  ui        - Launch UI Dashboard (Next dev)"
    echo "  all       - Launch kg + gateway + ui"
    echo "  check     - Playwright smoke test (login -> /en/pipeline, check WS banner)"
    echo ""
    echo "Options:"
    echo "  --port PORT    - Custom port (for single service)"
    echo "  --clean-env    - Force clean Neurodesk environment"
    echo "  --skip-mounts  - Skip OpenNeuro s3fs mounts"
    echo "  --help         - Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 kg --port 5000"
    echo "  $0 agent"
    echo "  $0 all"
}

run_openneuro_mounts() {
    if [[ "${SKIP_OPENNEURO_MOUNTS:-0}" == "1" ]]; then
        echo -e "${YELLOW}Skipping OpenNeuro mounts (SKIP_OPENNEURO_MOUNTS=1)${NC}"
        return 0
    fi

    local mount_script="${OPENNEURO_MOUNT_SCRIPT:-$PROJECT_ROOT/scripts/setup/mount_openneuro_s3fs.sh}"
    if [[ -x "$mount_script" ]]; then
        echo -e "${BLUE}Running OpenNeuro mount script: ${mount_script}${NC}"
        if ! "$mount_script"; then
            echo -e "${YELLOW}Warning: OpenNeuro mount script reported failures.${NC}"
            if [[ "${OPENNEURO_MOUNT_REQUIRED:-0}" == "1" ]]; then
                return 1
            fi
        fi
    elif [[ -f "$mount_script" ]]; then
        echo -e "${BLUE}Running OpenNeuro mount script with bash: ${mount_script}${NC}"
        if ! bash "$mount_script"; then
            echo -e "${YELLOW}Warning: OpenNeuro mount script reported failures.${NC}"
            if [[ "${OPENNEURO_MOUNT_REQUIRED:-0}" == "1" ]]; then
                return 1
            fi
        fi
    else
        echo -e "${YELLOW}OpenNeuro mount script not found: ${mount_script}${NC}"
        if [[ "${OPENNEURO_MOUNT_REQUIRED:-0}" == "1" ]]; then
            return 1
        fi
    fi
}

# Function to clean Neurodesk environment
clean_neurodesk_env() {
    echo -e "${YELLOW}Cleaning Neurodesk environment variables...${NC}"

    # Unset Singularity variables
    unset SINGULARITY_BINDPATH 2>/dev/null || true
    unset SINGULARITY_CACHEDIR 2>/dev/null || true
    unset SINGULARITY_TMPDIR 2>/dev/null || true
    unset SINGULARITY_LOCALCACHEDIR 2>/dev/null || true
    unset SINGULARITYENV_PREPEND_PATH 2>/dev/null || true

    # Unset module-related variables
    unset MODULEPATH 2>/dev/null || true
    unset LOADEDMODULES 2>/dev/null || true
    unset MODULES_CMD 2>/dev/null || true

    echo -e "${GREEN}✓ Environment cleaned${NC}"
}

# Function to check if conda environment is active
check_conda_env() {
    if [[ -z "$CONDA_DEFAULT_ENV" ]]; then
        echo -e "${YELLOW}Warning: No conda environment detected.${NC}"
        echo "Please activate the brain_researcher environment:"
        echo "  conda activate brain_researcher"
        echo ""
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo -e "${GREEN}✓ Using conda environment: $CONDA_DEFAULT_ENV${NC}"
    fi
}

# Function to check if a port is in use
check_port_available() {
    local port=$1
    local service_name=$2
    local in_use=false

    if command -v lsof >/dev/null 2>&1; then
        if timeout 3 lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
            in_use=true
        fi
    else
        if ss -ltn 2>/dev/null | grep -q ":$port "; then
            in_use=true
        fi
    fi

    if [[ "$in_use" == true ]]; then
        echo -e "${RED}Error: Port $port is already in use (needed for $service_name)${NC}"
        echo "Process using port $port:"
        if command -v lsof >/dev/null 2>&1; then
            timeout 3 lsof -Pi :$port -sTCP:LISTEN || true
        else
            ss -ltnp 2>/dev/null | grep ":$port " || true
        fi
        echo ""
        echo "Please stop the process or choose a different port."
        return 1
    fi
    return 0
}

# Function to check all required ports before launching services
check_all_ports() {
    local failed=false

    check_port_available 5000 "BR-KG" || failed=true
    check_port_available 8000 "Gateway" || failed=true
    check_port_available 3000 "UI" || failed=true

    if [[ "$failed" == true ]]; then
        echo -e "${RED}Port conflicts detected. Cannot proceed.${NC}"
        echo "Suggestion: Kill processes with: lsof -ti:PORT | xargs kill -9"
        exit 1
    fi

    echo -e "${GREEN}✓ All required ports are available${NC}"
}

# Function to launch a service
launch_service() {
    local service=$1
    local port=$2

    echo -e "${BLUE}Launching $service service...${NC}"

    # Check if CLI is available
    if command -v br &> /dev/null || command -v brain-researcher &> /dev/null; then
        CLI_CMD="br"
        if ! command -v br &> /dev/null; then
            CLI_CMD="brain-researcher"
        fi

        case $service in
            "kg"|"br-kg")
                if [[ -n "$port" ]]; then
                    $CLI_CMD serve kg --port $port
                else
                    $CLI_CMD serve kg
                fi
                ;;
            "agent"|"gateway")
                local agent_port="${port:-8000}"
                echo -e "${GREEN}Starting gateway (Agent HTTP + Orchestrator WS) on port ${agent_port}${NC}"
                BR_KG_URL=${BR_KG_URL:-http://127.0.0.1:5000} \
                BR_KG_API_URL=${BR_KG_API_URL:-http://127.0.0.1:5000} \
                BR_DEV_ORCH_COMPAT=${BR_DEV_ORCH_COMPAT:-1} \
                uvicorn brain_researcher.legacy.gateway.asgi_app:app --host 0.0.0.0 --port "$agent_port"
                ;;
            "ui"|"dashboard")
                local frontend_port="${port:-3000}"
                local frontend_host="${FRONTEND_HOST:-localhost}"
                pushd "$PROJECT_ROOT/apps/web-ui" >/dev/null
                echo -e "${GREEN}Starting Next.js frontend at http://${frontend_host}:${frontend_port}${NC}"
                WATCHPACK_POLLING=true CHOKIDAR_USEPOLLING=true \
                npm run dev -- --hostname "$frontend_host" --port "$frontend_port"
                popd >/dev/null
                ;;
            *)
                echo -e "${RED}Unknown service: $service${NC}"
                echo "Available services: kg, agent, ui"
                exit 1
                ;;
        esac
    else
        # Fallback: use Python module directly
        echo -e "${YELLOW}CLI not found. Using direct module launch...${NC}"
        echo -e "${YELLOW}Install CLI: pip install -e .${NC}"

        case $service in
            "kg"|"br-kg")
                if [[ -n "$port" ]]; then
                    PORT=$port python -c "from brain_researcher.cli.commands.services.kg_launcher import launch_kg_service; launch_kg_service(port=$port)"
                else
                    python -c "from brain_researcher.cli.commands.services.kg_launcher import launch_kg_service; launch_kg_service()"
                fi
                ;;
            "agent"|"gateway")
                local agent_port="${port:-8000}"
                echo -e "${GREEN}Starting gateway (Agent HTTP + Orchestrator WS) on port ${agent_port}${NC}"
                BR_KG_URL=${BR_KG_URL:-http://127.0.0.1:5000} \
                BR_KG_API_URL=${BR_KG_API_URL:-http://127.0.0.1:5000} \
                BR_DEV_ORCH_COMPAT=${BR_DEV_ORCH_COMPAT:-1} \
                uvicorn brain_researcher.legacy.gateway.asgi_app:app --host 0.0.0.0 --port "$agent_port"
                ;;
            "ui"|"dashboard")
                local frontend_port="${port:-3000}"
                local frontend_host="${FRONTEND_HOST:-localhost}"
                pushd "$PROJECT_ROOT/apps/web-ui" >/dev/null
                echo -e "${GREEN}Starting Next.js frontend at http://${frontend_host}:${frontend_port}${NC}"
                WATCHPACK_POLLING=true CHOKIDAR_USEPOLLING=true \
                npm run dev -- --hostname "$frontend_host" --port "$frontend_port"
                popd >/dev/null
                ;;
            *)
                echo -e "${RED}Unknown service: $service${NC}"
                echo "Available services: kg, agent, ui"
                exit 1
                ;;
        esac
    fi
}

# Function to launch all services
launch_all_services() {
    echo -e "${BLUE}Launching all services (Gateway + BR-KG + UI)...${NC}"

    # Check for port conflicts before launching
    check_all_ports

    # Check if CLI is available
    if command -v br &> /dev/null || command -v brain-researcher &> /dev/null; then
        CLI_CMD="br"
        if ! command -v br &> /dev/null; then
            CLI_CMD="brain-researcher"
        fi

        # Launch services in background using CLI
        echo "Starting BR-KG service on port 5000 (Neo4j backend)..."
        NEO4J_PRELOAD_CACHE=${NEO4J_PRELOAD_CACHE:-false} \
        NEO4J_URI=${NEO4J_URI:-bolt://localhost:7687} \
        NEO4J_USER=${NEO4J_USER:-neo4j} \
        NEO4J_PASSWORD=${NEO4J_PASSWORD:-password} \
        $CLI_CMD serve kg --port 5000 &
        KG_PID=$!

        # Wait for BR-KG HTTP to respond before starting dependents (max ~30s)
        echo "Waiting for BR-KG to become ready..."
        for _ in {1..30}; do
            if curl -sSf -m 1 http://127.0.0.1:5000/health >/dev/null 2>&1; then
                echo -e "${GREEN}✓ BR-KG HTTP is responding${NC}"
                break
            fi
            sleep 1
        done

        echo "Starting Gateway (Agent HTTP + Orchestrator WS) on port 8000..."
        BR_KG_URL=${BR_KG_URL:-http://127.0.0.1:5000} \
        BR_KG_API_URL=${BR_KG_API_URL:-http://127.0.0.1:5000} \
        BR_DEV_ORCH_COMPAT=${BR_DEV_ORCH_COMPAT:-1} \
        uvicorn brain_researcher.legacy.gateway.asgi_app:app --host 0.0.0.0 --port 8000 > /tmp/brain_researcher_gateway.log 2>&1 &
        GATEWAY_PID=$!

        # Wait for Gateway readiness: /tools or /orchestrator/metrics
        echo "Waiting for Gateway to become ready..."
        for _ in {1..40}; do
            if curl -sSf -m 1 http://127.0.0.1:8000/tools >/dev/null 2>&1; then
                echo -e "${GREEN}✓ Gateway /tools is responding${NC}"
                break
            fi
            if curl -sSf -m 1 http://127.0.0.1:8000/orchestrator/metrics >/dev/null 2>&1; then
                echo -e "${GREEN}✓ Orchestrator /metrics is responding${NC}"
                break
            fi
            sleep 0.5
        done

        echo "Checking WS /ws/dashboard..."
        if ! timeout 3s npx --yes wscat -c ws://127.0.0.1:8000/ws/dashboard >/dev/null 2>&1; then
            echo -e "${RED}✗ WS handshake failed: ws://127.0.0.1:8000/ws/dashboard${NC}"
            echo "See gateway log: /tmp/brain_researcher_gateway.log"
            exit 1
        fi
        echo -e "${GREEN}✓ WS handshake OK${NC}"

        echo "Starting Next.js frontend on port 3000..."
        FRONTEND_HOST="${FRONTEND_HOST:-localhost}"
        pushd "$PROJECT_ROOT/apps/web-ui" >/dev/null
        NEXT_PUBLIC_AGENT_URL=${NEXT_PUBLIC_AGENT_URL:-http://127.0.0.1:8000} \
        NEXT_PUBLIC_AGENT_API=${NEXT_PUBLIC_AGENT_API:-http://127.0.0.1:8000} \
        NEXT_PUBLIC_ORCHESTRATOR_URL=${NEXT_PUBLIC_ORCHESTRATOR_URL:-http://127.0.0.1:8000/orchestrator} \
        NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL:-ws://127.0.0.1:8000/ws} \
        NEXT_PUBLIC_USE_API_PROXY=${NEXT_PUBLIC_USE_API_PROXY:-false} \
        ENABLE_DEV_CREDENTIALS=${ENABLE_DEV_CREDENTIALS:-1} \
        DEV_CREDENTIALS_EMAIL=${DEV_CREDENTIALS_EMAIL:-demo@example.com} \
        DEV_CREDENTIALS_PASSWORD=${DEV_CREDENTIALS_PASSWORD:-DemoPass123!} \
        NEXTAUTH_SECRET=${NEXTAUTH_SECRET:-dev-secret-please-change} \
        NEXT_PUBLIC_BR_KG_API=${NEXT_PUBLIC_BR_KG_API:-http://127.0.0.1:5000} \
        NEXT_PUBLIC_BR_KG_URL=${NEXT_PUBLIC_BR_KG_URL:-$NEXT_PUBLIC_BR_KG_API} \
        WATCHPACK_POLLING=true CHOKIDAR_USEPOLLING=true \
        npm run dev -- --hostname "$FRONTEND_HOST" --port 3000 > /tmp/brain_researcher_ui.log 2>&1 &
        UI_PID=$!
        popd >/dev/null
    else
        echo -e "${RED}Error: CLI not found. Please install: pip install -e .${NC}"
        echo -e "${YELLOW}Or use the individual service launchers directly.${NC}"
        exit 1
    fi

    echo ""
    echo -e "${GREEN}All services started!${NC}"
        echo "BR-KG:      http://localhost:5000"
        echo "Gateway:      http://localhost:8000 (logs: /tmp/brain_researcher_gateway.log)"
        echo "Frontend:     http://${FRONTEND_HOST:-localhost}:3000 (logs: /tmp/brain_researcher_ui.log)"
    echo ""
    echo "Process IDs:"
    echo "  BR-KG: $KG_PID"
    echo "  Gateway: $GATEWAY_PID"
    if [[ -n "$UI_PID" ]]; then
        echo "  UI:      $UI_PID"
    fi
    echo ""
    echo "Press Ctrl+C to stop all services"

    # Wait for user to stop services
    trap 'echo -e "\n${YELLOW}Stopping all services...${NC}"; PIDS_TO_STOP=(); [[ -n "$KG_PID" ]] && PIDS_TO_STOP+=("$KG_PID"); [[ -n "$GATEWAY_PID" ]] && PIDS_TO_STOP+=("$GATEWAY_PID"); [[ -n "$UI_PID" ]] && PIDS_TO_STOP+=("$UI_PID"); if [[ ${#PIDS_TO_STOP[@]} -gt 0 ]]; then kill "${PIDS_TO_STOP[@]}" 2>/dev/null; fi; exit 0' INT
    wait $KG_PID $GATEWAY_PID $UI_PID
}

# Parse command line arguments
SERVICE=""
PORT=""
CLEAN_ENV=false
SKIP_OPENNEURO_MOUNTS=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --clean-env)
            CLEAN_ENV=true
            shift
            ;;
        --skip-mounts)
            SKIP_OPENNEURO_MOUNTS=1
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            if [[ -z "$SERVICE" ]]; then
                SERVICE="$1"
            else
                echo -e "${RED}Unknown option: $1${NC}"
                show_usage
                exit 1
            fi
            shift
            ;;
    esac
done

# Check if service is provided
if [[ -z "$SERVICE" ]]; then
    echo -e "${RED}Error: No service specified${NC}"
    show_usage
    exit 1
fi

# Change to project directory
cd "$PROJECT_ROOT"

# Load repo-level environment overrides (root .env then .env.local)
load_env_overlays

# Clean Neurodesk environment if requested or if Singularity variables are set
if [[ "$CLEAN_ENV" == true ]] || [[ -n "$SINGULARITY_BINDPATH" ]]; then
    clean_neurodesk_env
fi

# Ensure OpenNeuro mounts are available (best-effort by default)
run_openneuro_mounts

# Check conda environment
check_conda_env

# Add project to Python path
export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo ""

# Helper: playwright smoke test (login -> pipeline -> check banner)
run_playwright_check() {
  echo -e "${BLUE}Running Playwright smoke check (login -> /en/pipeline)...${NC}"
  node - <<'JS'
const { chromium } = require('./apps/web-ui/node_modules/@playwright/test');

const EMAIL = process.env.PW_EMAIL || process.env.DEV_CREDENTIALS_EMAIL || 'demo@example.com';
const PASS  = process.env.PW_PASS  || process.env.DEV_CREDENTIALS_PASSWORD || 'DemoPass123!';

(async () => {
  const b = await chromium.launch({ headless: true });
  const p = await b.newPage({ viewport: { width: 1400, height: 900 } });

  await p.goto('http://localhost:3000/auth/login?callbackUrl=%2Fen%2Fpipeline', { waitUntil: 'domcontentloaded' });
  await p.fill('input[type=email]', EMAIL);
  await p.fill('input[type=password]', PASS);
  await p.click('button:has-text("Sign in")');
  await p.waitForTimeout(1500);

  await p.goto('http://localhost:3000/en/pipeline', { waitUntil: 'domcontentloaded' });
  await p.waitForTimeout(4000);

  const bannerCount = await p.locator('text=WebSocket connection').count();
  await p.screenshot({ path: '/tmp/pipeline.png', fullPage: true });

  console.log(JSON.stringify({
    bannerCount,
    screenshot: '/tmp/pipeline.png',
    url: p.url()
  }, null, 2));

  await b.close();
  process.exit(bannerCount === 0 ? 0 : 2);
})().catch(err => { console.error(err); process.exit(2); });
JS
}

# Launch service(s) or run checks
if [[ "$SERVICE" == "all" ]]; then
    launch_all_services
elif [[ "$SERVICE" == "check" ]]; then
    run_playwright_check
else
    launch_service "$SERVICE" "$PORT"
fi
