#!/bin/bash

# Brain Researcher - Complete System Launch Script
# This script launches the full data ingestion and all services

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🧠 Brain Researcher System Launch${NC}"
echo -e "${BLUE}========================================${NC}"

# Function to show menu
show_menu() {
    echo ""
    echo "Select launch option:"
    echo "  1) Full System (Ingestion + Services)"
    echo "  2) Data Ingestion Only"
    echo "  3) Services Only (BR-KG, Agent, UI)"
    echo "  4) Clean and Restart Everything"
    echo "  5) Check System Status"
    echo "  6) Exit"
    echo ""
    read -p "Enter choice [1-6]: " choice
}

# Function to run data ingestion
run_ingestion() {
    echo -e "${GREEN}📊 Running Data Ingestion...${NC}"
    python3 launch_ingestion.py --report
    echo -e "${GREEN}✅ Ingestion Complete!${NC}"
}

# Function to start services
start_services() {
    echo -e "${GREEN}🚀 Starting Services...${NC}"

    # Start Docker services if docker-compose exists
    if [ -f "docker-compose.yml" ]; then
        echo "Starting Docker services..."
        docker-compose up -d br-kg orchestrator redis web-ui
    else
        echo "Starting local services..."
        # Start services in background
        nohup python3 -m brain_researcher.cli serve kg > logs/br-kg.log 2>&1 &
        echo "  • BR-KG API started on port 5001"

        nohup python3 -m brain_researcher.cli serve agent > logs/agent.log 2>&1 &
        echo "  • Agent Service started on port 8000"

        # Start Next.js UI if available
        if [ -d "apps/web-ui" ]; then
            cd apps/web-ui
            npm run build && npm start > ../../../logs/web-ui.log 2>&1 &
            cd ../../..
            echo "  • Web UI started on port 3000"
        fi
    fi

    echo -e "${GREEN}✅ Services Started!${NC}"
}

# Function to check status
check_status() {
    echo -e "${BLUE}📊 System Status:${NC}"

    # Check Neo4j database
    python3 - <<'PY'
import os
try:
    from neo4j import GraphDatabase
except Exception:
    print("  • Knowledge Graph: neo4j driver not installed")
    raise SystemExit(0)

uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE")

if not password:
    print("  • Knowledge Graph: NEO4J_PASSWORD not set")
else:
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session(database=database) as session:
            nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        driver.close()
        print(f"  • Knowledge Graph (Neo4j): {nodes:,} nodes, {rels:,} relationships")
    except Exception as exc:
        print(f"  • Knowledge Graph: Neo4j unreachable ({exc})")
PY

    # Check services
    curl -s http://localhost:5001/health > /dev/null && echo "  • BR-KG API: ✅ Running" || echo "  • BR-KG API: ❌ Not running"
    curl -s http://localhost:8000/health > /dev/null && echo "  • Agent Service: ✅ Running" || echo "  • Agent Service: ❌ Not running"
    curl -s http://localhost:3000 > /dev/null && echo "  • Web UI: ✅ Running" || echo "  • Web UI: ❌ Not running"
}

# Function to clean everything
clean_all() {
    echo -e "${YELLOW}⚠️  Cleaning all data and stopping services...${NC}"

    # Stop services
    docker-compose down 2>/dev/null || true
    pkill -f "brain_researcher.cli serve" 2>/dev/null || true

    # Clean database
    rm -f data/br-kg/db/*.db

    echo -e "${GREEN}✅ Cleanup complete!${NC}"
}

# Main menu loop
while true; do
    show_menu

    case $choice in
        1)
            run_ingestion
            start_services
            check_status
            ;;
        2)
            run_ingestion
            ;;
        3)
            start_services
            ;;
        4)
            clean_all
            run_ingestion
            start_services
            check_status
            ;;
        5)
            check_status
            ;;
        6)
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${YELLOW}Invalid option, please try again${NC}"
            ;;
    esac
done
