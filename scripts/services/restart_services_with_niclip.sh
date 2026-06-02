#!/bin/bash

# Service Restart Script with NiCLIP Configuration
# Restarts all Brain Researcher services with proper environment variables

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p "$PROJECT_ROOT/logs"

WEB_UI_LOG="$PROJECT_ROOT/logs/web_ui.log"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
NEO4J_DATA_ROOT="$PROJECT_ROOT/data/neo4j"
mkdir -p "$NEO4J_DATA_ROOT/data" "$NEO4J_DATA_ROOT/logs" "$NEO4J_DATA_ROOT/plugins" "$NEO4J_DATA_ROOT/import"

echo "🔄 Restarting Brain Researcher Services with NiCLIP Configuration"
echo "=================================================================="
echo ""

# Load environment variables from main .env file
if [ -f ".env" ]; then
    echo "📋 Loading environment variables from .env..."
    set -a
    source .env
    set +a
else
    echo "⚠️  Warning: .env file not found in project root"
fi

# Export critical environment variables
export BR_KG_API_URL="http://localhost:5000"
export BR_KG_URL="http://localhost:5000"
export NICLIP_DATA_PATH="${NICLIP_DATA_PATH:-$PROJECT_ROOT/data/niclip/data}"
export GEMINI_API_KEY="${GEMINI_API_KEY:-}"
export DEFAULT_LLM_MODEL="${DEFAULT_LLM_MODEL:-gemini-2.0-flash}"
export WEB_UI_URL="${WEB_UI_URL:-http://localhost:3000}"
export NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
export NEO4J_USER="${NEO4J_USER:-neo4j}"
export NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"

echo "✅ Environment variables set:"
echo "   BR_KG_API_URL=$BR_KG_API_URL"
echo "   NICLIP_DATA_PATH=$NICLIP_DATA_PATH"
echo "   DEFAULT_LLM_MODEL=$DEFAULT_LLM_MODEL"
echo ""

# Function to kill a service by name
kill_service() {
    local service_name=$1
    local search_pattern=$2

    echo "🛑 Stopping $service_name..."
    pkill -f "$search_pattern" 2>/dev/null && echo "   ✓ Stopped $service_name" || echo "   ℹ️  $service_name not running"
}

# Kill existing services
echo "🛑 Stopping existing services..."
kill_service "Agent" "brain_researcher.services.agent"
kill_service "Orchestrator" "brain_researcher.services.orchestrator"
kill_service "BR-KG" "brain_researcher.services.br_kg"
kill_service "Web UI" "brain_researcher.cli.main.*serve web"
kill_service "Web UI (Next.js)" "next dev"

# Give services time to shut down
sleep 2

# Ensure Neo4j container is running
echo ""
echo "🧱 Ensuring Neo4j database container is running..."
ensure_neo4j() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "   ⚠️  Docker not found on PATH. Skipping Neo4j container check."
        return
    fi

    local compose_cmd=""
    if docker compose version >/dev/null 2>&1; then
        compose_cmd="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        compose_cmd="docker-compose"
    else
        echo "   ⚠️  Neither 'docker compose' nor 'docker-compose' is available. Skipping Neo4j container start."
        return
    fi

    if docker ps --format '{{.Names}}' | grep -q '^brain-researcher-neo4j$'; then
        echo "   ✓ Neo4j container already running"
    else
        echo "   ⏳ Starting Neo4j container (this may take a few seconds)..."
        if [[ ! -f "$PROJECT_ROOT/$COMPOSE_FILE" ]]; then
            echo "   ⚠️  Compose file not found at $PROJECT_ROOT/$COMPOSE_FILE"
            return
        fi
        $compose_cmd -f "$PROJECT_ROOT/$COMPOSE_FILE" up -d neo4j >> "$PROJECT_ROOT/logs/br-kg.log" 2>&1
        if docker ps --format '{{.Names}}' | grep -q '^brain-researcher-neo4j$'; then
            echo "   ✓ Neo4j container started"
        else
            echo "   ⚠️  Failed to start Neo4j container. Check Docker status."
        fi
    fi
}
ensure_neo4j

echo ""
echo "🚀 Starting services..."
echo ""

# Start BR-KG service
echo "1️⃣  Starting BR-KG service on port 5000..."
nohup br serve kg --host 0.0.0.0 --port 5000 > logs/br-kg.log 2>&1 &
BR_KG_PID=$!
echo "   ✓ BR-KG started (PID: $BR_KG_PID)"
echo "   📄 Logs: logs/br-kg.log"

# Wait for BR-KG to be ready
sleep 3

# Start Agent service
echo ""
echo "2️⃣  Starting Agent service on port 8000..."
nohup br serve agent --host 0.0.0.0 --port 8000 > logs/agent.log 2>&1 &
AGENT_PID=$!
echo "   ✓ Agent started (PID: $AGENT_PID)"
echo "   📄 Logs: logs/agent.log"

# Wait for Agent to be ready
sleep 3

# Start Orchestrator service
echo ""
echo "3️⃣  Starting Orchestrator service on port 3001..."
nohup br serve orchestrator --host 0.0.0.0 --port 3001 > logs/orchestrator.log 2>&1 &
ORCHESTRATOR_PID=$!
echo "   ✓ Orchestrator started (PID: $ORCHESTRATOR_PID)"
echo "   📄 Logs: logs/orchestrator.log"

# Wait for Orchestrator to be ready
sleep 3

# Start Web UI
echo ""
echo "4️⃣  Starting Web UI on port 3000..."
mkdir -p "$(dirname "$WEB_UI_LOG")"
nohup br serve web --host 0.0.0.0 --port 3000 > "$WEB_UI_LOG" 2>&1 &
WEB_UI_PID=$!
echo "   ✓ Web UI started (PID: $WEB_UI_PID)"
echo "   📄 Logs: logs/web_ui.log"

# Give Web UI time to initialize
sleep 5

echo ""
echo "=================================================================="
echo "✅ All services restarted successfully!"
echo "=================================================================="
echo ""
echo "📊 Service Status:"
echo ""

# Check BR-KG health
echo "🔍 Checking BR-KG (http://localhost:5000/health)..."
if curl -s http://localhost:5000/health | grep -q "healthy"; then
    echo "   ✅ BR-KG is healthy"
else
    echo "   ⚠️  BR-KG health check failed"
fi

# Check Agent health
echo "🔍 Checking Agent (http://localhost:8000/health)..."
if curl -s http://localhost:8000/health | grep -q "healthy"; then
    echo "   ✅ Agent is healthy"
else
    echo "   ⚠️  Agent health check failed"
fi

# Check Orchestrator health
echo "🔍 Checking Orchestrator (http://localhost:3001/health)..."
if curl -s http://localhost:3001/health | grep -q "healthy"; then
    echo "   ✅ Orchestrator is healthy"
else
    echo "   ⚠️  Orchestrator health check failed"
fi

# Check Web UI health
echo "🔍 Checking Web UI (http://localhost:3000/api/health)..."
if curl -s -o /dev/null -w "%{http_code}" "http://localhost:3000/api/health" | grep -q "200"; then
    echo "   ✅ Web UI responded successfully"
else
    echo "   ⚠️  Web UI health check failed (it may still be compiling; see logs/web_ui.log)"
fi

echo ""
echo "🎯 Service URLs:"
echo "   • BR-KG:      http://localhost:5000"
echo "   • Agent:        http://localhost:8000"
echo "   • Orchestrator: http://localhost:3001"
echo "   • Web UI:       http://localhost:3000"
echo ""
echo "💡 To view logs:"
echo "   tail -f logs/br-kg.log"
echo "   tail -f logs/agent.log"
echo "   tail -f logs/orchestrator.log"
echo "   tail -f logs/web_ui.log"
echo ""
echo "🧪 To verify NiCLIP loading:"
echo "   python scripts/validation/verify_niclip_loading.py"
echo ""
