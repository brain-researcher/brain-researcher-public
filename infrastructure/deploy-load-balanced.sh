#!/bin/bash

# Brain Researcher Load Balanced Deployment Script
# Deploys the complete load-balanced infrastructure for Brain Researcher
#
# Usage: ./deploy-load-balanced.sh [platform] [environment]
# Platforms: swarm, k8s
# Environments: dev, staging, prod

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PLATFORM="${1:-swarm}"
ENVIRONMENT="${2:-dev}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${BLUE}INFO${NC}: $*"
}

log_success() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${GREEN}SUCCESS${NC}: $*"
}

log_warning() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${YELLOW}WARNING${NC}: $*"
}

log_error() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] ${RED}ERROR${NC}: $*"
}

# Check prerequisites
check_prerequisites() {
    local required_tools=()

    if [[ "$PLATFORM" == "swarm" ]]; then
        required_tools+=("docker" "docker-compose")
    elif [[ "$PLATFORM" == "k8s" ]]; then
        required_tools+=("kubectl" "helm")
    fi

    required_tools+=("jq" "curl")

    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            log_error "Required tool not found: $tool"
            exit 1
        fi
    done

    log_success "Prerequisites check passed"
}

# Initialize Docker Swarm if needed
init_swarm() {
    if ! docker node ls >/dev/null 2>&1; then
        log_info "Initializing Docker Swarm"
        docker swarm init
        log_success "Docker Swarm initialized"
    else
        log_info "Docker Swarm already initialized"
    fi

    # Label nodes for placement constraints
    local node_id=$(docker node ls --filter "role=manager" --format "{{.ID}}" | head -n1)

    log_info "Setting up node labels"
    docker node update --label-add tier=web "$node_id"
    docker node update --label-add tier=api "$node_id"
    docker node update --label-add tier=compute "$node_id"
    docker node update --label-add tier=storage "$node_id"
    docker node update --label-add tier=monitoring "$node_id"
    docker node update --label-add tier=orchestrator "$node_id"

    log_success "Node labels configured"
}

# Deploy with Docker Swarm
deploy_swarm() {
    log_info "Deploying Brain Researcher with Docker Swarm"

    # Initialize swarm
    init_swarm

    # Create necessary networks
    log_info "Creating Docker networks"
    docker network create --driver overlay brain-researcher-frontend --attachable || true
    docker network create --driver overlay brain-researcher-backend --attachable || true

    # Create secrets
    log_info "Creating Docker secrets"
    create_docker_secrets

    # Create configs
    log_info "Creating Docker configs"
    create_docker_configs

    # Deploy stack
    log_info "Deploying Docker stack"
    docker stack deploy \
        --compose-file "$PROJECT_ROOT/docker-compose.swarm.yml" \
        --with-registry-auth \
        brain-researcher

    log_success "Docker Swarm deployment completed"
}

# Deploy with Kubernetes
deploy_k8s() {
    log_info "Deploying Brain Researcher with Kubernetes"

    # Check if kubectl can connect
    if ! kubectl cluster-info >/dev/null 2>&1; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi

    # Apply Kubernetes manifests
    log_info "Applying Kubernetes manifests"
    kubectl apply -f "$PROJECT_ROOT/infrastructure/k8s/manifests/"

    # Install Helm charts if available
    if [[ -d "$PROJECT_ROOT/infrastructure/k8s/helm/brain-researcher" ]]; then
        log_info "Installing Helm chart"
        helm upgrade --install brain-researcher \
            "$PROJECT_ROOT/infrastructure/k8s/helm/brain-researcher/" \
            --namespace brain-researcher-core \
            --create-namespace \
            --values "$PROJECT_ROOT/infrastructure/k8s/helm/brain-researcher/values.yaml"
    fi

    log_success "Kubernetes deployment completed"
}

# Create Docker secrets
create_docker_secrets() {
    # Database passwords
    echo "${POSTGRES_PASSWORD:-secure_db_password}" | \
        docker secret create postgres_password - 2>/dev/null || true

    # API keys
    echo "${OPENAI_API_KEY:-}" | \
        docker secret create openai_api_key - 2>/dev/null || true
    echo "${ANTHROPIC_API_KEY:-}" | \
        docker secret create anthropic_api_key - 2>/dev/null || true

    log_info "Docker secrets created"
}

# Create Docker configs
create_docker_configs() {
    # HAProxy configuration
    docker config create haproxy_config \
        "$SCRIPT_DIR/haproxy/haproxy.cfg" 2>/dev/null || true

    # PgBouncer configuration
    docker config create pgbouncer_config \
        "$SCRIPT_DIR/database/pgbouncer.ini" 2>/dev/null || true
    docker config create pgbouncer_userlist \
        "$SCRIPT_DIR/database/userlist.txt" 2>/dev/null || true

    # Prometheus configuration
    docker config create prometheus_config \
        "$SCRIPT_DIR/monitoring/prometheus.yml" 2>/dev/null || true

    log_info "Docker configs created"
}

# Wait for services to be healthy
wait_for_services() {
    log_info "Waiting for services to become healthy"

    local services=("haproxy" "postgres" "redis-master" "pgbouncer")
    local max_wait=300  # 5 minutes
    local start_time=$(date +%s)

    for service in "${services[@]}"; do
        log_info "Waiting for $service to be healthy"

        while true; do
            local current_time=$(date +%s)
            local elapsed=$((current_time - start_time))

            if [[ $elapsed -gt $max_wait ]]; then
                log_error "Timeout waiting for $service to be healthy"
                return 1
            fi

            if check_service_health "$service"; then
                log_success "$service is healthy"
                break
            fi

            sleep 10
        done
    done

    log_success "All core services are healthy"
}

# Check service health
check_service_health() {
    local service=$1

    case "$PLATFORM" in
        "swarm")
            check_docker_service_health "$service"
            ;;
        "k8s")
            check_k8s_service_health "$service"
            ;;
    esac
}

check_docker_service_health() {
    local service="brain-researcher_$1"

    local running_tasks=$(docker service ls --filter "name=$service" --format "{{.Replicas}}" | cut -d'/' -f1)
    local desired_tasks=$(docker service ls --filter "name=$service" --format "{{.Replicas}}" | cut -d'/' -f2)

    [[ "$running_tasks" == "$desired_tasks" && "$running_tasks" != "0" ]]
}

check_k8s_service_health() {
    local service=$1
    kubectl get deployment "$service" -n brain-researcher-core -o jsonpath='{.status.readyReplicas}' >/dev/null 2>&1
}

# Setup monitoring
setup_monitoring() {
    log_info "Setting up monitoring and alerting"

    if [[ "$PLATFORM" == "swarm" ]]; then
        # Monitoring is included in the Docker Swarm stack
        log_info "Monitoring services deployed with main stack"
    elif [[ "$PLATFORM" == "k8s" ]]; then
        # Deploy Prometheus Operator or standalone monitoring
        setup_k8s_monitoring
    fi

    log_success "Monitoring setup completed"
}

setup_k8s_monitoring() {
    # Check if Prometheus Operator is available
    if kubectl get crd prometheuses.monitoring.coreos.com >/dev/null 2>&1; then
        log_info "Prometheus Operator detected, creating ServiceMonitors"
        create_service_monitors
    else
        log_warning "Prometheus Operator not found, deploying standalone monitoring"
        deploy_standalone_monitoring
    fi
}

create_service_monitors() {
    # This would create ServiceMonitor resources for Prometheus Operator
    log_info "Creating ServiceMonitor resources"
    # Implementation would depend on specific monitoring requirements
}

deploy_standalone_monitoring() {
    # Deploy Prometheus, Grafana, and AlertManager
    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

    # Apply monitoring manifests (would need separate monitoring manifests)
    # kubectl apply -f "$SCRIPT_DIR/monitoring/k8s/"
    log_info "Standalone monitoring deployment would be implemented here"
}

# Configure load balancer
configure_load_balancer() {
    log_info "Configuring load balancer"

    if [[ "$PLATFORM" == "swarm" ]]; then
        # HAProxy configuration is handled via Docker configs
        log_info "HAProxy configured via Docker config"

        # Wait for HAProxy to be ready
        local max_attempts=30
        local attempt=1

        while [[ $attempt -le $max_attempts ]]; do
            if curl -f -s http://localhost:8080/stats >/dev/null 2>&1; then
                log_success "HAProxy is ready and serving traffic"
                break
            fi

            log_info "Waiting for HAProxy... (attempt $attempt/$max_attempts)"
            sleep 10
            ((attempt++))
        done

        if [[ $attempt -gt $max_attempts ]]; then
            log_error "HAProxy failed to start within expected time"
            return 1
        fi

    elif [[ "$PLATFORM" == "k8s" ]]; then
        # Kubernetes Ingress configuration
        log_info "Kubernetes Ingress configured via manifests"

        # Check ingress status
        kubectl get ingress -n brain-researcher-core
    fi

    log_success "Load balancer configuration completed"
}

# Run health checks
run_health_checks() {
    log_info "Running comprehensive health checks"

    local endpoints=(
        "http://localhost/health"
        "http://localhost/api/health"
        "http://localhost/orchestrator/health"
        "http://localhost/br-kg/health"
    )

    for endpoint in "${endpoints[@]}"; do
        log_info "Checking $endpoint"

        if curl -f -s --max-time 30 "$endpoint" >/dev/null; then
            log_success "$endpoint is responding"
        else
            log_error "$endpoint is not responding"
        fi
    done

    # Check autoscaler
    if [[ -f "$SCRIPT_DIR/autoscaling/autoscaler.py" ]]; then
        log_info "Testing autoscaler configuration"
        python3 "$SCRIPT_DIR/autoscaling/autoscaler.py" --once --config "$SCRIPT_DIR/autoscaling/autoscaler-config.json"
    fi

    log_success "Health checks completed"
}

# Show deployment summary
show_deployment_summary() {
    log_success "Brain Researcher Load Balanced Deployment Summary"
    echo
    echo "Platform: $PLATFORM"
    echo "Environment: $ENVIRONMENT"
    echo

    if [[ "$PLATFORM" == "swarm" ]]; then
        echo "Docker Stack Services:"
        docker stack services brain-researcher --format "table {{.Name}}\t{{.Mode}}\t{{.Replicas}}\t{{.Image}}"
        echo
        echo "Access Points:"
        echo "  - Main Application: http://localhost"
        echo "  - HAProxy Stats: http://localhost:8080/stats"
        echo "  - Grafana: http://localhost:3000/grafana"
        echo "  - Prometheus: http://localhost:9090"

    elif [[ "$PLATFORM" == "k8s" ]]; then
        echo "Kubernetes Deployments:"
        kubectl get deployments -n brain-researcher-core
        echo
        echo "Services:"
        kubectl get services -n brain-researcher-core
        echo
        echo "Ingress:"
        kubectl get ingress -n brain-researcher-core
    fi

    echo
    log_success "Deployment completed successfully!"
    echo
    echo "Next steps:"
    echo "1. Verify all services are healthy"
    echo "2. Check monitoring dashboards"
    echo "3. Test load balancing and auto-scaling"
    echo "4. Configure SSL certificates for production"
    echo "5. Set up backup and disaster recovery"
}

# Cleanup function
cleanup() {
    if [[ "$PLATFORM" == "swarm" ]]; then
        log_info "Removing Docker stack"
        docker stack rm brain-researcher || true

        log_info "Removing Docker networks"
        docker network rm brain-researcher-frontend brain-researcher-backend || true

    elif [[ "$PLATFORM" == "k8s" ]]; then
        log_info "Removing Kubernetes resources"
        kubectl delete -f "$PROJECT_ROOT/infrastructure/k8s/manifests/" || true

        if command -v helm >/dev/null 2>&1; then
            helm uninstall brain-researcher -n brain-researcher-core || true
        fi
    fi
}

# Main deployment function
main() {
    log_info "Brain Researcher Load Balanced Deployment"
    log_info "Platform: $PLATFORM, Environment: $ENVIRONMENT"

    # Check prerequisites
    check_prerequisites

    # Deploy based on platform
    case "$PLATFORM" in
        "swarm")
            deploy_swarm
            ;;
        "k8s")
            deploy_k8s
            ;;
        *)
            log_error "Unsupported platform: $PLATFORM"
            echo "Supported platforms: swarm, k8s"
            exit 1
            ;;
    esac

    # Wait for core services
    wait_for_services

    # Configure load balancer
    configure_load_balancer

    # Setup monitoring
    setup_monitoring

    # Run health checks
    run_health_checks

    # Show summary
    show_deployment_summary
}

# Handle script arguments
case "${1:-deploy}" in
    "deploy")
        main
        ;;
    "cleanup")
        cleanup
        ;;
    "health-check")
        run_health_checks
        ;;
    "status")
        if [[ "$PLATFORM" == "swarm" ]]; then
            docker stack services brain-researcher
        elif [[ "$PLATFORM" == "k8s" ]]; then
            kubectl get all -n brain-researcher-core
        fi
        ;;
    *)
        echo "Usage: $0 [deploy|cleanup|health-check|status] [platform] [environment]"
        echo "Platforms: swarm, k8s"
        echo "Environments: dev, staging, prod"
        exit 1
        ;;
esac
