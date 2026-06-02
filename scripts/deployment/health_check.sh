#!/bin/bash

# Brain Researcher Health Check Script
# Comprehensive health monitoring for all services

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_FILE="/var/log/brain-researcher/health_check.log"
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.prod.yml}
COMPOSE_CMD=()
COMPOSE_AVAILABLE=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Health check configuration
TIMEOUT=${TIMEOUT:-10}
MAX_RETRIES=${MAX_RETRIES:-3}
CHECK_INTERVAL=${CHECK_INTERVAL:-5}

# Service definitions
declare -A SERVICES=(
    ["nginx"]="80:/health"
    ["orchestrator"]="3001:/health"
    ["agent"]="8000:/health"
    ["br-kg"]="5000:/health"
    ["web-ui"]="3000:/api/health"
    ["redis"]="6379:ping"
)

# Logging functions
log() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_info() {
    log "${BLUE}[INFO]${NC} $*"
}

log_warn() {
    log "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    log "${RED}[ERROR]${NC} $*"
}

log_success() {
    log "${GREEN}[SUCCESS]${NC} $*"
}

detect_compose() {
    if command -v docker-compose >/dev/null 2>&1; then
        if docker-compose version >/dev/null 2>&1; then
            COMPOSE_CMD=(docker-compose)
            COMPOSE_AVAILABLE=true
            return
        fi
    fi

    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
        COMPOSE_AVAILABLE=true
    else
        COMPOSE_CMD=()
        COMPOSE_AVAILABLE=false
        log_warn "Docker Compose not available; container status checks disabled"
    fi
}

run_compose() {
    if [[ "$COMPOSE_AVAILABLE" != "true" ]]; then
        return 1
    fi
    "${COMPOSE_CMD[@]}" -f "$PROJECT_ROOT/$COMPOSE_FILE" "$@"
}

# Initialize logging
init_logging() {
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
    detect_compose
}

# Show usage
show_help() {
    cat << EOF
Usage: $0 [OPTIONS] [SERVICES...]

Health check script for Brain Researcher services.

OPTIONS:
    -c, --continuous        Run continuous monitoring
    -i, --interval SEC      Check interval for continuous mode (default: 5)
    -t, --timeout SEC       Request timeout (default: 10)
    -r, --retries NUM       Max retries per service (default: 3)
    -f, --compose-file FILE Docker compose file (default: docker-compose.prod.yml)
    -j, --json              Output in JSON format
    -q, --quiet             Quiet mode (minimal output)
    -v, --verbose           Verbose output
    -h, --help              Show this help

SERVICES:
    If no services specified, checks all services.
    Available services: ${!SERVICES[@]}

EXAMPLES:
    # Check all services once
    $0

    # Check specific services
    $0 nginx br-kg

    # Continuous monitoring
    $0 --continuous --interval 30

    # JSON output for monitoring systems
    $0 --json

EOF
}

# Parse arguments
parse_args() {
    SERVICES_TO_CHECK=()
    CONTINUOUS=false
    JSON_OUTPUT=false
    QUIET=false
    VERBOSE=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -c|--continuous)
                CONTINUOUS=true
                shift
                ;;
            -i|--interval)
                CHECK_INTERVAL="$2"
                shift 2
                ;;
            -t|--timeout)
                TIMEOUT="$2"
                shift 2
                ;;
            -r|--retries)
                MAX_RETRIES="$2"
                shift 2
                ;;
            -f|--compose-file)
                COMPOSE_FILE="$2"
                shift 2
                ;;
            -j|--json)
                JSON_OUTPUT=true
                shift
                ;;
            -q|--quiet)
                QUIET=true
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
                set -x
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            -*)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
            *)
                SERVICES_TO_CHECK+=("$1")
                shift
                ;;
        esac
    done

    # Default to all services if none specified
    if [[ ${#SERVICES_TO_CHECK[@]} -eq 0 ]]; then
        SERVICES_TO_CHECK=($(printf '%s\n' "${!SERVICES[@]}" | sort))
    fi
}

# Check if service is running in Docker
is_service_running() {
    local service="$1"
    if [[ "$COMPOSE_AVAILABLE" != "true" ]]; then
        return 0
    fi

    local container_id
    container_id=$(run_compose ps -q "$service" 2>/dev/null || true)
    if [[ -z "$container_id" ]]; then
        return 1
    fi

    local status_output
    status_output=$(run_compose ps "$service" 2>/dev/null || true)
    if grep -q "Up" <<<"$status_output"; then
        return 0
    fi
    return 1
}

# HTTP health check
http_health_check() {
    local service="$1"
    local port="$2"
    local path="$3"
    local url="http://localhost:${port}${path}"

    local response
    local http_code

    if [[ "$VERBOSE" == "true" ]]; then
        log_info "Checking $service at $url"
    fi

    response=$(curl -s -w "HTTPSTATUS:%{http_code}" --max-time "$TIMEOUT" "$url" 2>/dev/null) || return 1
    http_code=$(echo "$response" | sed -n 's/.*HTTPSTATUS:\([0-9]\{3\}\).*/\1/p')

    if [[ "$http_code" -ge 200 && "$http_code" -lt 400 ]]; then
        return 0
    else
        if [[ "$VERBOSE" == "true" ]]; then
            log_warn "$service returned HTTP $http_code"
        fi
        return 1
    fi
}

# Redis health check
redis_health_check() {
    local port="$1"

    if command -v redis-cli >/dev/null 2>&1; then
        redis-cli -h localhost -p "$port" ping >/dev/null 2>&1
    else
        if [[ "$COMPOSE_AVAILABLE" != "true" ]]; then
            return 0
        fi
        if run_compose exec -T redis redis-cli ping >/dev/null 2>&1; then
            return 0
        fi
        return 1
    fi
}

# Check individual service
check_service() {
    local service="$1"
    local config="${SERVICES[$service]}"
    local port="${config%:*}"
    local endpoint="${config#*:}"

    local status="healthy"
    local message=""
    local response_time=""

    # Check if container is running
    if ! is_service_running "$service"; then
        status="down"
        message="Container not running"
        return 1
    fi

    # Perform health check based on service type
    local start_time=$(date +%s%N)

    if [[ "$service" == "redis" ]]; then
        if ! redis_health_check "$port"; then
            status="unhealthy"
            message="Redis ping failed"
            return 1
        fi
    else
        if ! http_health_check "$service" "$port" "$endpoint"; then
            status="unhealthy"
            message="HTTP health check failed"
            return 1
        fi
    fi

    local end_time=$(date +%s%N)
    response_time=$((($end_time - $start_time) / 1000000))  # Convert to milliseconds

    # Store results for JSON output
    if [[ "$JSON_OUTPUT" == "true" ]]; then
        HEALTH_RESULTS["$service"]=$(cat << EOF
{
    "service": "$service",
    "status": "$status",
    "message": "$message",
    "response_time_ms": $response_time,
    "timestamp": "$(date -Iseconds)"
}
EOF
)
    fi

    return 0
}

# Check service with retries
check_service_with_retries() {
    local service="$1"
    local retry=0

    while [[ $retry -lt $MAX_RETRIES ]]; do
        if check_service "$service"; then
            if [[ "$QUIET" != "true" ]]; then
                log_success "$service is healthy"
            fi
            return 0
        fi

        retry=$((retry + 1))
        if [[ $retry -lt $MAX_RETRIES ]]; then
            if [[ "$VERBOSE" == "true" ]]; then
                log_info "Retrying $service ($retry/$MAX_RETRIES)..."
            fi
            sleep 2
        fi
    done

    log_error "$service is unhealthy (failed after $MAX_RETRIES attempts)"
    return 1
}

# Check Docker Compose status
check_compose_status() {
    if [[ "$VERBOSE" == "true" ]]; then
        log_info "Checking Docker Compose status..."
    fi

    if [[ "$COMPOSE_AVAILABLE" != "true" ]]; then
        log_warn "Skipping container status check because Docker Compose is unavailable"
        return 0
    fi

    if ! run_compose ps >/dev/null 2>&1; then
        log_error "Docker Compose is not accessible"
        return 1
    fi

    # Get service status from compose
    local compose_status
    compose_status=$(run_compose ps --format json 2>/dev/null || true)

    if [[ -n "$compose_status" ]]; then
        if [[ "$VERBOSE" == "true" ]]; then
            echo "$compose_status" | jq -r '.[] | "\(.Name): \(.State)"' 2>/dev/null || true
        fi
    fi

    return 0
}

# System resource checks
check_system_resources() {
    if [[ "$VERBOSE" == "true" ]]; then
        log_info "Checking system resources..."
    fi

    # Check disk space
    local disk_usage
    disk_usage=$(df "$PROJECT_ROOT" | awk 'NR==2 {print $5}' | sed 's/%//')

    if [[ $disk_usage -gt 90 ]]; then
        log_warn "Disk usage is high: ${disk_usage}%"
    fi

    # Check memory usage
    local mem_usage
    mem_usage=$(free | grep Mem | awk '{print int($3/$2 * 100.0)}')

    if [[ $mem_usage -gt 90 ]]; then
        log_warn "Memory usage is high: ${mem_usage}%"
    fi

    # Check load average
    local load_avg
    load_avg=$(uptime | awk '{print $(NF-2)}' | sed 's/,//')

    if [[ "$VERBOSE" == "true" ]]; then
        log_info "System resources: Disk: ${disk_usage}%, Memory: ${mem_usage}%, Load: $load_avg"
    fi
}

# Output results in JSON format
output_json() {
    local overall_status="healthy"
    local timestamp=$(date -Iseconds)

    echo "{"
    echo "  \"timestamp\": \"$timestamp\","
    echo "  \"overall_status\": \"$overall_status\","
    echo "  \"services\": ["

    local first=true
    for service in "${SERVICES_TO_CHECK[@]}"; do
        if [[ "$first" == "true" ]]; then
            first=false
        else
            echo ","
        fi

        if [[ -n "${HEALTH_RESULTS[$service]:-}" ]]; then
            echo "    ${HEALTH_RESULTS[$service]}"
        else
            echo "    {\"service\": \"$service\", \"status\": \"unknown\"}"
        fi
    done

    echo "  ]"
    echo "}"
}

# Main health check function
run_health_check() {
    local all_healthy=true

    if [[ "$JSON_OUTPUT" == "true" ]]; then
        declare -A HEALTH_RESULTS
    fi

    # Check Docker Compose
    if ! check_compose_status; then
        all_healthy=false
    fi

    # Check system resources
    check_system_resources

    # Check each service
    for service in "${SERVICES_TO_CHECK[@]}"; do
        if [[ -z "${SERVICES[$service]:-}" ]]; then
            log_error "Unknown service: $service"
            all_healthy=false
            continue
        fi

        if ! check_service_with_retries "$service"; then
            all_healthy=false
        fi
    done

    # Output results
    if [[ "$JSON_OUTPUT" == "true" ]]; then
        output_json
    elif [[ "$QUIET" != "true" ]]; then
        if [[ "$all_healthy" == "true" ]]; then
            log_success "All services are healthy ✅"
        else
            log_error "Some services are unhealthy ❌"
        fi
    fi

    return $([[ "$all_healthy" == "true" ]] && echo 0 || echo 1)
}

# Continuous monitoring mode
continuous_monitoring() {
    log_info "Starting continuous health monitoring (interval: ${CHECK_INTERVAL}s)"
    log_info "Press Ctrl+C to stop"

    local check_count=0

    while true; do
        check_count=$((check_count + 1))

        if [[ "$QUIET" != "true" ]]; then
            echo
            log_info "Health check #$check_count"
            echo "----------------------------------------"
        fi

        run_health_check

        sleep "$CHECK_INTERVAL"
    done
}

# Signal handlers for graceful shutdown
cleanup() {
    log_info "Health monitoring stopped"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Main execution
main() {
    init_logging

    if [[ "$CONTINUOUS" == "true" ]]; then
        continuous_monitoring
    else
        run_health_check
        exit $?
    fi
}

# Parse arguments and run
parse_args "$@"
main
