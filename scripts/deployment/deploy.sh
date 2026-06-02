#!/bin/bash

# Brain Researcher Production Deployment Script
# This script handles the complete deployment process for the Brain Researcher platform

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/var/log/brain-researcher/deploy_${TIMESTAMP}.log"

# Default configuration
ENVIRONMENT=${ENVIRONMENT:-production}
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.prod.yml}
BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-30}
HEALTH_CHECK_TIMEOUT=${HEALTH_CHECK_TIMEOUT:-300}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Error handling
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Deployment failed with exit code $exit_code"
        log_error "Check log file: $LOG_FILE"

        # Rollback on failure
        if [ "${ROLLBACK_ON_FAILURE:-true}" = "true" ]; then
            log_info "Initiating rollback..."
            rollback
        fi
    fi
    exit $exit_code
}

trap cleanup EXIT

# Help function
show_help() {
    cat << EOF
Usage: $0 [OPTIONS]

Deploy Brain Researcher platform to production environment.

OPTIONS:
    -e, --environment ENV     Target environment (default: production)
    -f, --compose-file FILE   Docker compose file (default: docker-compose.prod.yml)
    -b, --backup             Create backup before deployment
    -r, --rollback           Rollback to previous version
    -s, --skip-tests         Skip health checks and tests
    -v, --verbose            Verbose output
    -h, --help              Show this help message

EXAMPLES:
    # Standard production deployment
    $0

    # Deploy to staging environment
    $0 --environment staging --compose-file docker-compose.yml

    # Deploy with backup
    $0 --backup

    # Rollback to previous version
    $0 --rollback

EOF
}

# Parse command line arguments
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -e|--environment)
                ENVIRONMENT="$2"
                shift 2
                ;;
            -f|--compose-file)
                COMPOSE_FILE="$2"
                shift 2
                ;;
            -b|--backup)
                CREATE_BACKUP=true
                shift
                ;;
            -r|--rollback)
                DO_ROLLBACK=true
                shift
                ;;
            -s|--skip-tests)
                SKIP_TESTS=true
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
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# Prerequisites check
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if running as root or with sudo
    if [[ $EUID -eq 0 ]] && [[ "${ALLOW_ROOT:-false}" != "true" ]]; then
        log_error "This script should not be run as root unless explicitly allowed"
        log_error "Set ALLOW_ROOT=true if you really need to run as root"
        exit 1
    fi

    # Check required commands
    local required_commands=("docker" "docker-compose" "curl" "jq")
    for cmd in "${required_commands[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            log_error "$cmd is required but not installed"
            exit 1
        fi
    done

    # Check Docker daemon
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running or not accessible"
        exit 1
    fi

    # Check compose file exists
    if [[ ! -f "$PROJECT_ROOT/$COMPOSE_FILE" ]]; then
        log_error "Compose file not found: $PROJECT_ROOT/$COMPOSE_FILE"
        exit 1
    fi

    # Create log directory
    sudo mkdir -p /var/log/brain-researcher
    sudo chown "$USER:$USER" /var/log/brain-researcher 2>/dev/null || true

    log_success "Prerequisites check passed"
}

# Create backup of current deployment
create_backup() {
    log_info "Creating backup of current deployment..."

    local backup_dir="/var/backups/brain-researcher"
    sudo mkdir -p "$backup_dir"
    local backup_name="backup_${TIMESTAMP}"
    local backup_path="${backup_dir}/${backup_name}"

    # Create backup directory
    mkdir -p "$backup_path"

    # Backup database if it exists
    if [[ -d "$PROJECT_ROOT/data/br-kg/db" ]]; then
        log_info "Backing up BR-KG database..."
        cp -r "$PROJECT_ROOT/data/br-kg/db" "$backup_path/br-kg_db"
    fi

    # Backup configuration files
    log_info "Backing up configuration files..."
    cp "$PROJECT_ROOT/$COMPOSE_FILE" "$backup_path/"

    # Backup environment file
    if [[ -f "$PROJECT_ROOT/.env" ]]; then
        cp "$PROJECT_ROOT/.env" "$backup_path/"
    fi

    # Create backup metadata
    cat > "$backup_path/metadata.json" << EOF
{
    "timestamp": "${TIMESTAMP}",
    "environment": "${ENVIRONMENT}",
    "compose_file": "${COMPOSE_FILE}",
    "git_commit": "$(git rev-parse HEAD 2>/dev/null || echo 'unknown')",
    "git_branch": "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
}
EOF

    # Compress backup
    log_info "Compressing backup..."
    tar -czf "${backup_path}.tar.gz" -C "$backup_dir" "$backup_name"
    rm -rf "$backup_path"

    # Set backup path for potential rollback
    echo "$backup_path.tar.gz" > /tmp/brain-researcher-latest-backup

    # Clean old backups
    log_info "Cleaning old backups (older than $BACKUP_RETENTION_DAYS days)..."
    find "$backup_dir" -name "backup_*.tar.gz" -mtime +$BACKUP_RETENTION_DAYS -delete 2>/dev/null || true

    log_success "Backup created: ${backup_path}.tar.gz"
}

# Rollback to previous version
rollback() {
    log_info "Rolling back to previous deployment..."

    # Find latest backup
    local latest_backup
    if [[ -f "/tmp/brain-researcher-latest-backup" ]]; then
        latest_backup=$(cat /tmp/brain-researcher-latest-backup)
    else
        latest_backup=$(find /var/backups/brain-researcher -name "backup_*.tar.gz" | sort -r | head -n 1)
    fi

    if [[ -z "$latest_backup" || ! -f "$latest_backup" ]]; then
        log_error "No backup found for rollback"
        exit 1
    fi

    log_info "Using backup: $latest_backup"

    # Stop current services
    log_info "Stopping current services..."
    docker-compose -f "$PROJECT_ROOT/$COMPOSE_FILE" down || true

    # Extract backup
    local temp_dir="/tmp/brain-researcher-rollback-${TIMESTAMP}"
    mkdir -p "$temp_dir"
    tar -xzf "$latest_backup" -C "$temp_dir"

    local backup_name=$(basename "$latest_backup" .tar.gz)
    local backup_path="${temp_dir}/${backup_name}"

    # Restore database
    if [[ -d "$backup_path/br-kg_db" ]]; then
        log_info "Restoring BR-KG database..."
        rm -rf "$PROJECT_ROOT/data/br-kg/db"
        mkdir -p "$PROJECT_ROOT/data/br-kg"
        cp -r "$backup_path/br-kg_db" "$PROJECT_ROOT/data/br-kg/db"
    fi

    # Restore configuration
    if [[ -f "$backup_path/$COMPOSE_FILE" ]]; then
        cp "$backup_path/$COMPOSE_FILE" "$PROJECT_ROOT/"
    fi

    if [[ -f "$backup_path/.env" ]]; then
        cp "$backup_path/.env" "$PROJECT_ROOT/"
    fi

    # Start services with rollback version
    log_info "Starting services with rollback version..."
    docker-compose -f "$PROJECT_ROOT/$COMPOSE_FILE" up -d

    # Wait for services to be healthy
    if ! wait_for_health; then
        log_error "Rollback health check failed"
        exit 1
    fi

    # Cleanup
    rm -rf "$temp_dir"

    log_success "Rollback completed successfully"
}

# Pre-deployment checks
pre_deployment_checks() {
    log_info "Running pre-deployment checks..."

    # Check disk space
    local available_space=$(df "$PROJECT_ROOT" | awk 'NR==2 {print $4}')
    local required_space=5000000  # 5GB in KB

    if [[ $available_space -lt $required_space ]]; then
        log_error "Insufficient disk space. Available: ${available_space}KB, Required: ${required_space}KB"
        exit 1
    fi

    # Check environment variables
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        log_warn "No .env file found. Using default environment variables"
    fi

    # Validate compose file
    log_info "Validating Docker Compose configuration..."
    if ! docker-compose -f "$PROJECT_ROOT/$COMPOSE_FILE" config -q; then
        log_error "Invalid Docker Compose configuration"
        exit 1
    fi

    # Check if services are already running
    local running_services
    running_services=$(docker-compose -f "$PROJECT_ROOT/$COMPOSE_FILE" ps -q)
    if [[ -n "$running_services" ]]; then
        log_warn "Some services are already running"
    fi

    log_success "Pre-deployment checks passed"
}

# Deploy services
deploy_services() {
    log_info "Deploying Brain Researcher services..."

    cd "$PROJECT_ROOT"

    # Pull latest images
    log_info "Pulling latest Docker images..."
    docker-compose -f "$COMPOSE_FILE" pull

    # Build custom images
    log_info "Building custom images..."
    docker-compose -f "$COMPOSE_FILE" build --no-cache

    # Start services
    log_info "Starting services..."
    docker-compose -f "$COMPOSE_FILE" up -d

    # Show service status
    log_info "Service status:"
    docker-compose -f "$COMPOSE_FILE" ps

    log_success "Services deployed successfully"
}

# Wait for services to be healthy
wait_for_health() {
    log_info "Waiting for services to be healthy..."

    local timeout=${HEALTH_CHECK_TIMEOUT}
    local elapsed=0
    local check_interval=10

    local services=(
        "nginx:80:/health"
        "orchestrator:3001:/health"
        "agent:8000:/health"
        "br-kg:5000:/health"
        "web-ui:3000:/api/health"
    )

    while [[ $elapsed -lt $timeout ]]; do
        local all_healthy=true

        for service in "${services[@]}"; do
            local name="${service%%:*}"
            local remainder="${service#*:}"
            local port="${remainder%%:*}"
            local path="${remainder#*:}"

            if ! curl -sf "http://localhost:${port}${path}" &>/dev/null; then
                log_info "Waiting for $name (port $port) to be healthy..."
                all_healthy=false
                break
            fi
        done

        if [[ "$all_healthy" == "true" ]]; then
            log_success "All services are healthy"
            return 0
        fi

        sleep $check_interval
        elapsed=$((elapsed + check_interval))
    done

    log_error "Health check timeout after ${timeout} seconds"
    return 1
}

# Run smoke tests
run_smoke_tests() {
    log_info "Running smoke tests..."

    # Test ingress health
    log_info "Testing Nginx ingress..."
    if ! curl -sf http://localhost/health | jq -e '.status == "healthy"' &>/dev/null; then
        log_error "Nginx ingress health check failed"
        return 1
    fi

    # Test Orchestrator
    log_info "Testing Orchestrator..."
    if ! curl -sf http://localhost:3001/health &>/dev/null; then
        log_error "Orchestrator health check failed"
        return 1
    fi

    # Test Agent (may take longer to start)
    log_info "Testing Agent service..."
    local agent_retries=10
    while [[ $agent_retries -gt 0 ]]; do
        if curl -sf http://localhost:8000/health &>/dev/null; then
            break
        fi
        log_info "Agent not ready, retrying... ($agent_retries attempts left)"
        sleep 10
        ((agent_retries--))
    done

    if [[ $agent_retries -eq 0 ]]; then
        log_error "Agent health check failed"
        return 1
    fi

    # Test BR-KG
    log_info "Testing BR-KG..."
    if ! curl -sf http://localhost:5000/health &>/dev/null; then
        log_error "BR-KG health check failed"
        return 1
    fi

    # Test Web UI
    log_info "Testing Web UI..."
    if ! curl -sf http://localhost:3000/api/health &>/dev/null; then
        log_error "Web UI check failed"
        return 1
    fi

    # Test proxied request flow through nginx
    log_info "Testing proxied request flow through nginx..."
    if ! curl -sf http://localhost/api/agent/health &>/dev/null; then
        log_error "Proxied request flow test failed"
        return 1
    fi

    log_success "All smoke tests passed"
    return 0
}

# Post-deployment tasks
post_deployment() {
    log_info "Running post-deployment tasks..."

    # Update service registry
    log_info "Updating service registry..."

    # Setup log rotation
    setup_log_rotation

    # Create systemd service for monitoring (optional)
    setup_monitoring

    # Clean up old Docker images
    log_info "Cleaning up old Docker images..."
    docker image prune -af --filter "until=24h" || true

    log_success "Post-deployment tasks completed"
}

# Setup log rotation
setup_log_rotation() {
    log_info "Setting up log rotation..."

    cat << 'EOF' | sudo tee /etc/logrotate.d/brain-researcher > /dev/null
/var/log/brain-researcher/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 644 brain-researcher brain-researcher
    postrotate
        # Restart services if needed
        systemctl reload brain-researcher-services 2>/dev/null || true
    endscript
}
EOF

    log_success "Log rotation configured"
}

# Setup monitoring
setup_monitoring() {
    log_info "Setting up monitoring..."

    # Create systemd service for health monitoring
    cat << 'EOF' | sudo tee /etc/systemd/system/brain-researcher-monitor.service > /dev/null
[Unit]
Description=Brain Researcher Health Monitor
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=brain-researcher
ExecStart=/bin/bash /opt/brain-researcher/scripts/health_monitor.sh
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable brain-researcher-monitor 2>/dev/null || true

    log_success "Monitoring setup completed"
}

# Main deployment function
main() {
    log_info "Starting Brain Researcher deployment (Environment: $ENVIRONMENT)"
    log_info "Using compose file: $COMPOSE_FILE"
    log_info "Log file: $LOG_FILE"

    # Handle rollback
    if [[ "${DO_ROLLBACK:-false}" == "true" ]]; then
        rollback
        exit 0
    fi

    # Check prerequisites
    check_prerequisites

    # Create backup if requested
    if [[ "${CREATE_BACKUP:-false}" == "true" ]]; then
        create_backup
    fi

    # Pre-deployment checks
    pre_deployment_checks

    # Deploy services
    deploy_services

    # Wait for health
    if ! wait_for_health; then
        log_error "Deployment failed - services not healthy"
        exit 1
    fi

    # Run tests unless skipped
    if [[ "${SKIP_TESTS:-false}" != "true" ]]; then
        if ! run_smoke_tests; then
            log_error "Deployment failed - smoke tests failed"
            exit 1
        fi
    fi

    # Post-deployment tasks
    post_deployment

    log_success "🎉 Brain Researcher deployment completed successfully!"
    log_info "Services are available at:"
    log_info "  - Nginx ingress: http://localhost"
    log_info "  - Web UI: http://localhost:3000"
    log_info "  - Direct Orchestrator: http://localhost:3001"
    log_info "  - Agent Service: http://localhost:8000"
    log_info "  - BR-KG API: http://localhost:5000"
}

# Run main function with all arguments
parse_args "$@"
main
