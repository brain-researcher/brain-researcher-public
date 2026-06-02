#!/bin/bash

# Brain Researcher Blue-Green Deployment Script
#
# This script implements blue-green deployment strategy for the Brain Researcher platform
# supporting both Docker Swarm and Kubernetes environments.
#
# Usage:
#   ./blue_green.sh [deploy|rollback|status|cleanup] [service_name] [--platform=swarm|k8s]
#
# Features:
# - Zero-downtime deployments
# - Automatic health checks
# - Gradual traffic switching
# - Automatic rollback on failure
# - Integration with HAProxy/Ingress
# - State persistence during deployment

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
DEPLOYMENT_LOG="${SCRIPT_DIR}/deployment.log"
STATE_DIR="${SCRIPT_DIR}/state"

# Default settings
PLATFORM="swarm"  # swarm or k8s
NAMESPACE="brain-researcher-core"
HEALTH_CHECK_TIMEOUT=300  # 5 minutes
TRAFFIC_SWITCH_DELAY=30   # 30 seconds between traffic switching steps
ROLLBACK_TIMEOUT=180      # 3 minutes

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Supported services
SERVICES=("orchestrator" "br-kg" "agent" "web-ui")

# Logging function
log() {
    local level=$1
    shift
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*" | tee -a "$DEPLOYMENT_LOG"
}

log_info() {
    log "INFO" "${BLUE}$*${NC}"
}

log_success() {
    log "SUCCESS" "${GREEN}$*${NC}"
}

log_warning() {
    log "WARNING" "${YELLOW}$*${NC}"
}

log_error() {
    log "ERROR" "${RED}$*${NC}"
}

# Initialize state directory
init_state_dir() {
    mkdir -p "$STATE_DIR"
}

# Save deployment state
save_state() {
    local service=$1
    local color=$2
    local replicas=$3
    local timestamp=$(date -Iseconds)

    cat > "${STATE_DIR}/${service}_state.json" << EOF
{
    "service": "$service",
    "active_color": "$color",
    "replicas": $replicas,
    "timestamp": "$timestamp",
    "platform": "$PLATFORM"
}
EOF
}

# Load deployment state
load_state() {
    local service=$1
    local state_file="${STATE_DIR}/${service}_state.json"

    if [[ -f "$state_file" ]]; then
        cat "$state_file"
    else
        echo '{"service":"'$service'","active_color":"blue","replicas":1,"platform":"'$PLATFORM'"}'
    fi
}

# Get inactive color (blue <-> green)
get_inactive_color() {
    local active_color=$1
    if [[ "$active_color" == "blue" ]]; then
        echo "green"
    else
        echo "blue"
    fi
}

# Docker Swarm Functions
docker_service_exists() {
    local service_name=$1
    docker service ls --filter "name=${service_name}" --format "{{.Name}}" | grep -q "^${service_name}$"
}

docker_get_service_replicas() {
    local service_name=$1
    if docker_service_exists "$service_name"; then
        docker service ls --filter "name=${service_name}" --format "{{.Replicas}}" | cut -d'/' -f1
    else
        echo "0"
    fi
}

docker_deploy_service() {
    local service_name=$1
    local color=$2
    local replicas=$3
    local service_color="${service_name}-${color}"

    log_info "Deploying Docker service: $service_color with $replicas replicas"

    # Check if service exists
    if docker_service_exists "$service_color"; then
        # Update existing service
        docker service update \
            --replicas="$replicas" \
            --update-parallelism=1 \
            --update-delay=10s \
            --update-failure-action=rollback \
            --update-monitor=60s \
            "$service_color"
    else
        # Create new service (this would need the full docker service create command)
        log_error "Service $service_color does not exist. Please create it first using docker-compose.swarm.yml"
        return 1
    fi
}

docker_health_check() {
    local service_name=$1
    local color=$2
    local timeout=$3
    local service_color="${service_name}-${color}"

    log_info "Performing health check for $service_color"

    local start_time=$(date +%s)
    local end_time=$((start_time + timeout))

    while [[ $(date +%s) -lt $end_time ]]; do
        local running_replicas=$(docker service ls --filter "name=${service_color}" --format "{{.Replicas}}" | cut -d'/' -f1)
        local desired_replicas=$(docker service ls --filter "name=${service_color}" --format "{{.Replicas}}" | cut -d'/' -f2)

        if [[ "$running_replicas" == "$desired_replicas" && "$running_replicas" -gt "0" ]]; then
            # Additional health check via HTTP if port is exposed
            if health_check_http "$service_name" "$color"; then
                log_success "Health check passed for $service_color"
                return 0
            fi
        fi

        log_info "Waiting for $service_color to be healthy ($running_replicas/$desired_replicas ready)..."
        sleep 10
    done

    log_error "Health check failed for $service_color after ${timeout}s"
    return 1
}

docker_scale_service() {
    local service_name=$1
    local color=$2
    local replicas=$3
    local service_color="${service_name}-${color}"

    log_info "Scaling $service_color to $replicas replicas"
    docker service scale "${service_color}=${replicas}"
}

docker_remove_service() {
    local service_name=$1
    local color=$2
    local service_color="${service_name}-${color}"

    if docker_service_exists "$service_color"; then
        log_info "Removing Docker service: $service_color"
        docker service rm "$service_color"
    fi
}

# Kubernetes Functions
k8s_deployment_exists() {
    local deployment_name=$1
    kubectl get deployment "$deployment_name" -n "$NAMESPACE" &>/dev/null
}

k8s_get_deployment_replicas() {
    local deployment_name=$1
    if k8s_deployment_exists "$deployment_name"; then
        kubectl get deployment "$deployment_name" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

k8s_deploy_service() {
    local service_name=$1
    local color=$2
    local replicas=$3
    local deployment_name="${service_name}-${color}"

    log_info "Deploying Kubernetes deployment: $deployment_name with $replicas replicas"

    # Generate deployment YAML
    generate_k8s_deployment "$service_name" "$color" "$replicas" | kubectl apply -f -
}

k8s_health_check() {
    local service_name=$1
    local color=$2
    local timeout=$3
    local deployment_name="${service_name}-${color}"

    log_info "Performing health check for $deployment_name"

    # Wait for rollout to complete
    if kubectl rollout status deployment/"$deployment_name" -n "$NAMESPACE" --timeout="${timeout}s"; then
        log_success "Health check passed for $deployment_name"
        return 0
    else
        log_error "Health check failed for $deployment_name"
        return 1
    fi
}

k8s_scale_deployment() {
    local service_name=$1
    local color=$2
    local replicas=$3
    local deployment_name="${service_name}-${color}"

    log_info "Scaling $deployment_name to $replicas replicas"
    kubectl scale deployment "$deployment_name" --replicas="$replicas" -n "$NAMESPACE"
}

k8s_remove_deployment() {
    local service_name=$1
    local color=$2
    local deployment_name="${service_name}-${color}"

    if k8s_deployment_exists "$deployment_name"; then
        log_info "Removing Kubernetes deployment: $deployment_name"
        kubectl delete deployment "$deployment_name" -n "$NAMESPACE"
    fi
}

# Generate Kubernetes deployment manifest
generate_k8s_deployment() {
    local service_name=$1
    local color=$2
    local replicas=$3
    local deployment_name="${service_name}-${color}"
    local image_tag="${color}"  # Assume images are tagged with color

    cat << EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${deployment_name}
  namespace: ${NAMESPACE}
  labels:
    app: ${service_name}
    color: ${color}
    managed-by: blue-green-deployer
spec:
  replicas: ${replicas}
  selector:
    matchLabels:
      app: ${service_name}
      color: ${color}
  template:
    metadata:
      labels:
        app: ${service_name}
        color: ${color}
    spec:
      containers:
      - name: ${service_name}
        image: brain-researcher-${service_name}:${image_tag}
        ports:
        - containerPort: $(get_service_port "$service_name")
        env:
        - name: DEPLOYMENT_COLOR
          value: "${color}"
        - name: SERVICE_NAME
          value: "${service_name}"
        livenessProbe:
          httpGet:
            path: /health
            port: $(get_service_port "$service_name")
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health
            port: $(get_service_port "$service_name")
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        resources:
          limits:
            cpu: $(get_service_cpu_limit "$service_name")
            memory: $(get_service_memory_limit "$service_name")
          requests:
            cpu: $(get_service_cpu_request "$service_name")
            memory: $(get_service_memory_request "$service_name")
EOF
}

# Get service-specific configurations
get_service_port() {
    local service=$1
    case "$service" in
        "orchestrator") echo "3001" ;;
        "br-kg") echo "5000" ;;
        "agent") echo "8000" ;;
        "web-ui") echo "3000" ;;
        *) echo "8080" ;;
    esac
}

get_service_cpu_limit() {
    local service=$1
    case "$service" in
        "orchestrator") echo "1.5" ;;
        "br-kg") echo "1.0" ;;
        "agent") echo "2.0" ;;
        "web-ui") echo "0.5" ;;
        *) echo "1.0" ;;
    esac
}

get_service_memory_limit() {
    local service=$1
    case "$service" in
        "orchestrator") echo "1.5Gi" ;;
        "br-kg") echo "1Gi" ;;
        "agent") echo "2Gi" ;;
        "web-ui") echo "512Mi" ;;
        *) echo "1Gi" ;;
    esac
}

get_service_cpu_request() {
    local service=$1
    case "$service" in
        "orchestrator") echo "0.75" ;;
        "br-kg") echo "0.5" ;;
        "agent") echo "1.0" ;;
        "web-ui") echo "0.25" ;;
        *) echo "0.5" ;;
    esac
}

get_service_memory_request() {
    local service=$1
    case "$service" in
        "orchestrator") echo "750Mi" ;;
        "br-kg") echo "512Mi" ;;
        "agent") echo "1Gi" ;;
        "web-ui") echo "256Mi" ;;
        *) echo "512Mi" ;;
    esac
}

# HTTP Health Check
health_check_http() {
    local service=$1
    local color=$2
    local port=$(get_service_port "$service")
    local url="http://localhost:${port}/health"

    # For Docker Swarm, we might need to check via the load balancer
    if [[ "$PLATFORM" == "swarm" ]]; then
        # Check through HAProxy or direct service access
        url="http://localhost/health"  # Through load balancer
    fi

    if command -v curl >/dev/null 2>&1; then
        if curl -f -s --max-time 10 "$url" >/dev/null; then
            return 0
        fi
    fi

    return 1
}

# HAProxy Traffic Management
update_haproxy_config() {
    local service=$1
    local active_color=$2
    local inactive_color=$3
    local traffic_percentage=$4  # 0-100, percentage to inactive color

    log_info "Updating HAProxy config for $service: ${traffic_percentage}% to $inactive_color"

    # This would generate and apply HAProxy configuration
    # For now, we'll use HAProxy stats interface to manage weights
    update_haproxy_weights "$service" "$active_color" "$inactive_color" "$traffic_percentage"
}

update_haproxy_weights() {
    local service=$1
    local active_color=$2
    local inactive_color=$3
    local traffic_percentage=$4

    local active_weight=$((100 - traffic_percentage))
    local inactive_weight=$traffic_percentage

    # Update HAProxy server weights using stats interface
    # This requires HAProxy stats socket to be configured
    local haproxy_socket="/var/run/haproxy.sock"

    if [[ -S "$haproxy_socket" ]]; then
        echo "set weight ${service}_backend/${service}-${active_color}-1 ${active_weight}" | socat stdio "$haproxy_socket"
        echo "set weight ${service}_backend/${service}-${inactive_color}-1 ${inactive_weight}" | socat stdio "$haproxy_socket"

        log_info "Updated HAProxy weights: $active_color=$active_weight%, $inactive_color=$inactive_weight%"
    else
        log_warning "HAProxy stats socket not found at $haproxy_socket"
    fi
}

# Platform-agnostic wrapper functions
deploy_service() {
    local service=$1
    local color=$2
    local replicas=$3

    if [[ "$PLATFORM" == "swarm" ]]; then
        docker_deploy_service "$service" "$color" "$replicas"
    elif [[ "$PLATFORM" == "k8s" ]]; then
        k8s_deploy_service "$service" "$color" "$replicas"
    fi
}

health_check_service() {
    local service=$1
    local color=$2
    local timeout=$3

    if [[ "$PLATFORM" == "swarm" ]]; then
        docker_health_check "$service" "$color" "$timeout"
    elif [[ "$PLATFORM" == "k8s" ]]; then
        k8s_health_check "$service" "$color" "$timeout"
    fi
}

scale_service() {
    local service=$1
    local color=$2
    local replicas=$3

    if [[ "$PLATFORM" == "swarm" ]]; then
        docker_scale_service "$service" "$color" "$replicas"
    elif [[ "$PLATFORM" == "k8s" ]]; then
        k8s_scale_deployment "$service" "$color" "$replicas"
    fi
}

remove_service() {
    local service=$1
    local color=$2

    if [[ "$PLATFORM" == "swarm" ]]; then
        docker_remove_service "$service" "$color"
    elif [[ "$PLATFORM" == "k8s" ]]; then
        k8s_remove_deployment "$service" "$color"
    fi
}

get_service_replicas() {
    local service=$1
    local color=$2
    local service_color="${service}-${color}"

    if [[ "$PLATFORM" == "swarm" ]]; then
        docker_get_service_replicas "$service_color"
    elif [[ "$PLATFORM" == "k8s" ]]; then
        k8s_get_deployment_replicas "$service_color"
    fi
}

# Main deployment function
deploy() {
    local service=$1

    if [[ ! " ${SERVICES[@]} " =~ " $service " ]]; then
        log_error "Unknown service: $service. Supported services: ${SERVICES[*]}"
        return 1
    fi

    log_info "Starting blue-green deployment for $service"

    # Load current state
    local state=$(load_state "$service")
    local active_color=$(echo "$state" | jq -r '.active_color')
    local current_replicas=$(echo "$state" | jq -r '.replicas')
    local inactive_color=$(get_inactive_color "$active_color")

    log_info "Current active color: $active_color, deploying to: $inactive_color"

    # Deploy to inactive color
    if ! deploy_service "$service" "$inactive_color" "$current_replicas"; then
        log_error "Failed to deploy $service to $inactive_color"
        return 1
    fi

    # Health check
    if ! health_check_service "$service" "$inactive_color" "$HEALTH_CHECK_TIMEOUT"; then
        log_error "Health check failed for $service-$inactive_color"
        log_info "Cleaning up failed deployment"
        remove_service "$service" "$inactive_color"
        return 1
    fi

    # Gradual traffic switch
    log_info "Starting gradual traffic switch for $service"
    local traffic_steps=(10 25 50 75 100)

    for percentage in "${traffic_steps[@]}"; do
        update_haproxy_config "$service" "$active_color" "$inactive_color" "$percentage"

        log_info "Switched ${percentage}% traffic to $inactive_color, monitoring..."
        sleep "$TRAFFIC_SWITCH_DELAY"

        # Quick health check
        if ! health_check_http "$service" "$inactive_color"; then
            log_error "Health check failed during traffic switch at ${percentage}%"
            log_info "Rolling back traffic to $active_color"
            update_haproxy_config "$service" "$active_color" "$inactive_color" "0"
            remove_service "$service" "$inactive_color"
            return 1
        fi
    done

    # All traffic switched successfully
    log_success "Successfully switched all traffic to $inactive_color"

    # Scale down old version
    log_info "Scaling down old version: $service-$active_color"
    scale_service "$service" "$active_color" "0"

    # Update state
    save_state "$service" "$inactive_color" "$current_replicas"

    # Cleanup old version after delay
    log_info "Waiting before cleanup..."
    sleep 60
    remove_service "$service" "$active_color"

    log_success "Blue-green deployment completed for $service"
    return 0
}

# Rollback function
rollback() {
    local service=$1

    log_info "Starting rollback for $service"

    # Load current state
    local state=$(load_state "$service")
    local active_color=$(echo "$state" | jq -r '.active_color')
    local current_replicas=$(echo "$state" | jq -r '.replicas')
    local inactive_color=$(get_inactive_color "$active_color")

    log_info "Rolling back from $active_color to $inactive_color"

    # Check if previous version exists
    local prev_replicas=$(get_service_replicas "$service" "$inactive_color")
    if [[ "$prev_replicas" -eq "0" ]]; then
        log_error "Previous version ($inactive_color) not available for rollback"
        return 1
    fi

    # Scale up previous version if needed
    if [[ "$prev_replicas" -lt "$current_replicas" ]]; then
        log_info "Scaling up previous version for rollback"
        scale_service "$service" "$inactive_color" "$current_replicas"

        if ! health_check_service "$service" "$inactive_color" "$ROLLBACK_TIMEOUT"; then
            log_error "Failed to scale up previous version for rollback"
            return 1
        fi
    fi

    # Quick traffic switch back
    update_haproxy_config "$service" "$active_color" "$inactive_color" "100"
    sleep 10

    # Health check
    if health_check_http "$service" "$inactive_color"; then
        log_success "Rollback completed successfully"

        # Scale down failed version
        scale_service "$service" "$active_color" "0"

        # Update state
        save_state "$service" "$inactive_color" "$current_replicas"

        return 0
    else
        log_error "Rollback failed - service still unhealthy"
        return 1
    fi
}

# Status function
status() {
    local service=$1

    log_info "Deployment status for $service:"

    # Load state
    local state=$(load_state "$service")
    local active_color=$(echo "$state" | jq -r '.active_color')
    local current_replicas=$(echo "$state" | jq -r '.replicas')
    local inactive_color=$(get_inactive_color "$active_color")
    local timestamp=$(echo "$state" | jq -r '.timestamp')

    echo "  Active Color: $active_color"
    echo "  Replicas: $current_replicas"
    echo "  Last Deployment: $timestamp"

    # Check current replicas
    local active_running=$(get_service_replicas "$service" "$active_color")
    local inactive_running=$(get_service_replicas "$service" "$inactive_color")

    echo "  Running Replicas:"
    echo "    $active_color: $active_running"
    echo "    $inactive_color: $inactive_running"

    # Health check
    echo "  Health Status:"
    if health_check_http "$service" "$active_color"; then
        echo "    $active_color: HEALTHY"
    else
        echo "    $active_color: UNHEALTHY"
    fi

    if [[ "$inactive_running" -gt "0" ]]; then
        if health_check_http "$service" "$inactive_color"; then
            echo "    $inactive_color: HEALTHY"
        else
            echo "    $inactive_color: UNHEALTHY"
        fi
    fi
}

# Cleanup function
cleanup() {
    local service=$1

    log_info "Cleaning up unused deployments for $service"

    # Load state
    local state=$(load_state "$service")
    local active_color=$(echo "$state" | jq -r '.active_color')
    local inactive_color=$(get_inactive_color "$active_color")

    # Remove inactive deployment if it exists and has no traffic
    local inactive_replicas=$(get_service_replicas "$service" "$inactive_color")
    if [[ "$inactive_replicas" -gt "0" ]]; then
        log_info "Removing inactive deployment: $service-$inactive_color"
        remove_service "$service" "$inactive_color"
    fi

    log_success "Cleanup completed for $service"
}

# Usage function
usage() {
    cat << EOF
Usage: $0 [COMMAND] [SERVICE] [OPTIONS]

COMMANDS:
    deploy [SERVICE]     - Deploy service using blue-green strategy
    rollback [SERVICE]   - Rollback to previous deployment
    status [SERVICE]     - Show deployment status
    cleanup [SERVICE]    - Clean up unused deployments

SERVICES:
    ${SERVICES[*]}

OPTIONS:
    --platform=PLATFORM  - Set platform (swarm|k8s), default: swarm
    --namespace=NS       - Kubernetes namespace, default: brain-researcher-core
    --timeout=SECONDS    - Health check timeout, default: 300
    --help               - Show this help message

EXAMPLES:
    $0 deploy orchestrator --platform=swarm
    $0 rollback br-kg --platform=k8s
    $0 status all
    $0 cleanup orchestrator

EOF
}

# Parse command line arguments
parse_args() {
    local command=""
    local service=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            deploy|rollback|status|cleanup)
                command=$1
                ;;
            --platform=*)
                PLATFORM="${1#*=}"
                ;;
            --namespace=*)
                NAMESPACE="${1#*=}"
                ;;
            --timeout=*)
                HEALTH_CHECK_TIMEOUT="${1#*=}"
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            -*)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
            *)
                if [[ -z "$command" ]]; then
                    command=$1
                elif [[ -z "$service" ]]; then
                    service=$1
                fi
                ;;
        esac
        shift
    done

    if [[ -z "$command" ]]; then
        log_error "Command required"
        usage
        exit 1
    fi

    echo "$command $service"
}

# Main function
main() {
    init_state_dir

    local args=$(parse_args "$@")
    local command=$(echo "$args" | cut -d' ' -f1)
    local service=$(echo "$args" | cut -d' ' -f2)

    log_info "Brain Researcher Blue-Green Deployment"
    log_info "Platform: $PLATFORM"
    log_info "Command: $command"
    [[ -n "$service" ]] && log_info "Service: $service"

    case "$command" in
        deploy)
            if [[ -z "$service" ]]; then
                log_error "Service name required for deploy command"
                exit 1
            fi
            deploy "$service"
            ;;
        rollback)
            if [[ -z "$service" ]]; then
                log_error "Service name required for rollback command"
                exit 1
            fi
            rollback "$service"
            ;;
        status)
            if [[ "$service" == "all" || -z "$service" ]]; then
                for svc in "${SERVICES[@]}"; do
                    echo
                    status "$svc"
                done
            else
                status "$service"
            fi
            ;;
        cleanup)
            if [[ "$service" == "all" || -z "$service" ]]; then
                for svc in "${SERVICES[@]}"; do
                    cleanup "$svc"
                done
            else
                cleanup "$service"
            fi
            ;;
        *)
            log_error "Unknown command: $command"
            usage
            exit 1
            ;;
    esac
}

# Check dependencies
check_dependencies() {
    local deps=("jq")

    if [[ "$PLATFORM" == "swarm" ]]; then
        deps+=("docker" "socat")
    elif [[ "$PLATFORM" == "k8s" ]]; then
        deps+=("kubectl")
    fi

    for dep in "${deps[@]}"; do
        if ! command -v "$dep" >/dev/null 2>&1; then
            log_error "Required dependency not found: $dep"
            exit 1
        fi
    done
}

# Entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    check_dependencies
    main "$@"
fi
