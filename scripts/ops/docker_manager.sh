#!/bin/bash
# Docker management script for Brain Researcher

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

detect_compose() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
        return
    fi
    if command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD=(docker-compose)
        return
    fi
    echo -e "${RED}Docker Compose not found. Install Docker Desktop or docker-compose.${NC}"
    exit 1
}

detect_compose

DEV_COMPOSE_FILES=(-f docker-compose.yml -f docker/compose/docker-compose.override.dev.yml)

# Functions
print_help() {
    echo "Brain Researcher Docker Manager"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start       - Start all services"
    echo "  stop        - Stop all services"
    echo "  restart     - Restart all services"
    echo "  status      - Show service status"
    echo "  logs        - Show logs (follow mode)"
    echo "  build       - Build all images"
    echo "  dev         - Start development environment"
    echo "  cli         - Run CLI in container"
    echo "  clean       - Clean up containers and images"
    echo "  test        - Run tests in container"
    echo ""
}

start_services() {
    echo -e "${BLUE}Starting Brain Researcher services...${NC}"
    "${COMPOSE_CMD[@]}" up -d
    echo -e "${GREEN}Services started!${NC}"
    echo ""
    "${COMPOSE_CMD[@]}" ps
}

stop_services() {
    echo -e "${BLUE}Stopping Brain Researcher services...${NC}"
    "${COMPOSE_CMD[@]}" down
    echo -e "${GREEN}Services stopped!${NC}"
}

restart_services() {
    stop_services
    start_services
}

show_status() {
    echo -e "${BLUE}Brain Researcher Service Status:${NC}"
    "${COMPOSE_CMD[@]}" ps
    echo ""
    echo -e "${BLUE}Service Health:${NC}"
    for service in br-kg agent web-ui; do
        if "${COMPOSE_CMD[@]}" ps | grep -q "brain-researcher-$service.*Up"; then
            echo -e "$service: ${GREEN}✓ Running${NC}"
        else
            echo -e "$service: ${RED}✗ Not running${NC}"
        fi
    done
}

show_logs() {
    echo -e "${BLUE}Following logs (Ctrl+C to exit)...${NC}"
    "${COMPOSE_CMD[@]}" logs -f
}

build_images() {
    echo -e "${BLUE}Building all images...${NC}"
    "${COMPOSE_CMD[@]}" build
    echo -e "${GREEN}Build complete!${NC}"
}

start_dev() {
    echo -e "${BLUE}Starting development environment...${NC}"
    "${COMPOSE_CMD[@]}" "${DEV_COMPOSE_FILES[@]}" up -d dev
    echo -e "${GREEN}Development container started!${NC}"
    echo ""
    echo "To enter the container:"
    echo "  docker exec -it brain-researcher-dev bash"
}

run_cli() {
    echo -e "${BLUE}Running CLI in container...${NC}"
    shift  # Remove the 'cli' command
    "${COMPOSE_CMD[@]}" "${DEV_COMPOSE_FILES[@]}" run --rm cli "$@"
}

clean_up() {
    echo -e "${RED}This will remove all Brain Researcher containers and images!${NC}"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Cleaning up...${NC}"
        "${COMPOSE_CMD[@]}" down -v
        docker images | grep brain-researcher | awk '{print $3}' | xargs -r docker rmi
        echo -e "${GREEN}Cleanup complete!${NC}"
    else
        echo "Cancelled."
    fi
}

run_tests() {
    echo -e "${BLUE}Running tests in container...${NC}"
    "${COMPOSE_CMD[@]}" "${DEV_COMPOSE_FILES[@]}" run --rm dev pytest
}

# Main script
case "$1" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    build)
        build_images
        ;;
    dev)
        start_dev
        ;;
    cli)
        run_cli "$@"
        ;;
    clean)
        clean_up
        ;;
    test)
        run_tests
        ;;
    *)
        print_help
        ;;
esac
