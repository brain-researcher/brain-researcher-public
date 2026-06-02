#!/bin/bash

# Brain Researcher Rollback Script
# Safely rollback to a previous deployment state

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKUP_DIR="/var/backups/brain-researcher"
LOG_FILE="/var/log/brain-researcher/rollback_$(date +%Y%m%d_%H%M%S).log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.prod.yml}
HEALTH_CHECK_TIMEOUT=${HEALTH_CHECK_TIMEOUT:-300}

# Logging
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

# Help function
show_help() {
    cat << EOF
Usage: $0 [OPTIONS]

Rollback Brain Researcher to a previous deployment state.

OPTIONS:
    -b, --backup FILE       Specific backup file to restore from
    -l, --list              List available backups
    -f, --force             Skip confirmation prompts
    -n, --dry-run           Show what would be done without executing
    -s, --skip-health       Skip health checks after rollback
    -h, --help              Show this help

EXAMPLES:
    # Rollback to latest backup
    $0

    # List available backups
    $0 --list

    # Rollback to specific backup
    $0 --backup /var/backups/brain-researcher/backup_20240101_120000.tar.gz

    # Dry run to see what would happen
    $0 --dry-run

EOF
}

# Parse arguments
parse_args() {
    BACKUP_FILE=""
    LIST_BACKUPS=false
    FORCE=false
    DRY_RUN=false
    SKIP_HEALTH=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -b|--backup)
                BACKUP_FILE="$2"
                shift 2
                ;;
            -l|--list)
                LIST_BACKUPS=true
                shift
                ;;
            -f|--force)
                FORCE=true
                shift
                ;;
            -n|--dry-run)
                DRY_RUN=true
                shift
                ;;
            -s|--skip-health)
                SKIP_HEALTH=true
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

# List available backups
list_backups() {
    log_info "Available backups:"

    if [[ ! -d "$BACKUP_DIR" ]]; then
        log_warn "No backup directory found at $BACKUP_DIR"
        return 1
    fi

    local backups
    backups=$(find "$BACKUP_DIR" -name "backup_*.tar.gz" -type f | sort -r)

    if [[ -z "$backups" ]]; then
        log_warn "No backups found"
        return 1
    fi

    echo
    printf "%-30s %-20s %-15s %s\n" "BACKUP FILE" "DATE" "SIZE" "GIT COMMIT"
    printf "%-30s %-20s %-15s %s\n" "$(printf '%.0s-' {1..30})" "$(printf '%.0s-' {1..20})" "$(printf '%.0s-' {1..15})" "$(printf '%.0s-' {1..40})"

    while IFS= read -r backup; do
        local basename=$(basename "$backup")
        local timestamp=${basename#backup_}
        timestamp=${timestamp%.tar.gz}
        local formatted_date=$(echo "$timestamp" | sed 's/_/ /')
        local size=$(du -h "$backup" | cut -f1)

        # Try to extract metadata
        local commit="unknown"
        local temp_meta=$(mktemp)
        if tar -xzf "$backup" -O "*/metadata.json" 2>/dev/null | jq -r '.git_commit // "unknown"' > "$temp_meta" 2>/dev/null; then
            commit=$(cat "$temp_meta" | cut -c1-8)
        fi
        rm -f "$temp_meta"

        printf "%-30s %-20s %-15s %s\n" "$basename" "$formatted_date" "$size" "$commit"
    done <<< "$backups"

    echo
}

# Find latest backup
find_latest_backup() {
    if [[ -n "$BACKUP_FILE" ]]; then
        if [[ ! -f "$BACKUP_FILE" ]]; then
            log_error "Backup file not found: $BACKUP_FILE"
            exit 1
        fi
        echo "$BACKUP_FILE"
        return
    fi

    # Check for latest backup hint
    if [[ -f "/tmp/brain-researcher-latest-backup" ]]; then
        local latest=$(cat /tmp/brain-researcher-latest-backup)
        if [[ -f "$latest" ]]; then
            echo "$latest"
            return
        fi
    fi

    # Find most recent backup
    local latest_backup
    latest_backup=$(find "$BACKUP_DIR" -name "backup_*.tar.gz" -type f | sort -r | head -n 1)

    if [[ -z "$latest_backup" ]]; then
        log_error "No backup files found in $BACKUP_DIR"
        exit 1
    fi

    echo "$latest_backup"
}

# Validate backup file
validate_backup() {
    local backup_file="$1"

    log_info "Validating backup file: $backup_file"

    # Check if file exists
    if [[ ! -f "$backup_file" ]]; then
        log_error "Backup file does not exist: $backup_file"
        return 1
    fi

    # Check if it's a valid tar.gz
    if ! tar -tzf "$backup_file" >/dev/null 2>&1; then
        log_error "Invalid backup file (not a valid tar.gz): $backup_file"
        return 1
    fi

    # Check if it contains expected files
    local contents
    contents=$(tar -tzf "$backup_file")

    if ! echo "$contents" | grep -q "metadata.json"; then
        log_warn "Backup does not contain metadata.json - may be an old backup format"
    fi

    log_success "Backup validation passed"
    return 0
}

# Show backup information
show_backup_info() {
    local backup_file="$1"
    local temp_dir=$(mktemp -d)

    log_info "Backup information:"

    # Extract and show metadata
    if tar -xzf "$backup_file" -C "$temp_dir" "*/metadata.json" 2>/dev/null; then
        local metadata_file=$(find "$temp_dir" -name "metadata.json")
        if [[ -f "$metadata_file" ]]; then
            echo
            echo "Backup Details:"
            echo "==============="
            jq -r '
                "Timestamp: " + .timestamp +
                "\nEnvironment: " + .environment +
                "\nCompose File: " + .compose_file +
                "\nGit Branch: " + .git_branch +
                "\nGit Commit: " + .git_commit
            ' "$metadata_file" 2>/dev/null || cat "$metadata_file"
            echo
        fi
    fi

    # Show backup contents
    echo "Backup Contents:"
    echo "=================="
    tar -tzf "$backup_file" | head -20
    local total_files=$(tar -tzf "$backup_file" | wc -l)
    if [[ $total_files -gt 20 ]]; then
        echo "... and $((total_files - 20)) more files"
    fi
    echo

    # Show file size
    local size=$(du -h "$backup_file" | cut -f1)
    echo "Backup size: $size"
    echo

    rm -rf "$temp_dir"
}

# Get current system state
save_current_state() {
    log_info "Saving current system state before rollback..."

    local pre_rollback_backup="/tmp/pre-rollback-state-$(date +%Y%m%d_%H%M%S).tar.gz"

    # Create temporary directory for current state
    local temp_dir=$(mktemp -d)
    local state_dir="$temp_dir/current-state"
    mkdir -p "$state_dir"

    # Save current Docker state
    if docker-compose -f "$PROJECT_ROOT/$COMPOSE_FILE" config > "$state_dir/docker-compose.yml" 2>/dev/null; then
        log_info "Saved current Docker Compose configuration"
    fi

    # Save current database if it exists
    if [[ -d "$PROJECT_ROOT/data/br-kg/db" ]]; then
        cp -r "$PROJECT_ROOT/data/br-kg/db" "$state_dir/br-kg_db"
        log_info "Saved current BR-KG database"
    fi

    # Save environment file
    if [[ -f "$PROJECT_ROOT/.env" ]]; then
        cp "$PROJECT_ROOT/.env" "$state_dir/"
        log_info "Saved current environment configuration"
    fi

    # Create metadata
    cat > "$state_dir/rollback_metadata.json" << EOF
{
    "pre_rollback_timestamp": "$(date -Iseconds)",
    "git_commit": "$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || echo 'unknown')",
    "git_branch": "$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')",
    "compose_file": "$COMPOSE_FILE"
}
EOF

    # Create tar archive
    tar -czf "$pre_rollback_backup" -C "$temp_dir" current-state
    rm -rf "$temp_dir"

    echo "$pre_rollback_backup" > /tmp/brain-researcher-pre-rollback-backup
    log_success "Current state saved to: $pre_rollback_backup"
}

# Perform the rollback
perform_rollback() {
    local backup_file="$1"
    local temp_dir=$(mktemp -d)

    log_info "Performing rollback from: $backup_file"

    # Extract backup
    log_info "Extracting backup..."
    tar -xzf "$backup_file" -C "$temp_dir"

    local backup_name=$(basename "$backup_file" .tar.gz)
    local backup_content_dir="$temp_dir/$backup_name"

    if [[ ! -d "$backup_content_dir" ]]; then
        # Try to find the actual content directory
        backup_content_dir=$(find "$temp_dir" -type d -maxdepth 1 | grep -v "^$temp_dir$" | head -n 1)
    fi

    if [[ ! -d "$backup_content_dir" ]]; then
        log_error "Could not find backup content directory"
        rm -rf "$temp_dir"
        return 1
    fi

    # Stop current services
    log_info "Stopping current services..."
    if [[ "$DRY_RUN" != "true" ]]; then
        cd "$PROJECT_ROOT"
        docker-compose -f "$COMPOSE_FILE" down || true
    else
        log_info "[DRY RUN] Would stop services with: docker-compose -f $COMPOSE_FILE down"
    fi

    # Restore database
    if [[ -d "$backup_content_dir/br-kg_db" ]]; then
        log_info "Restoring BR-KG database..."
        if [[ "$DRY_RUN" != "true" ]]; then
            rm -rf "$PROJECT_ROOT/data/br-kg/db"
            mkdir -p "$PROJECT_ROOT/data/br-kg"
            cp -r "$backup_content_dir/br-kg_db" "$PROJECT_ROOT/data/br-kg/db"
        else
            log_info "[DRY RUN] Would restore database from backup"
        fi
    fi

    # Restore configuration files
    if [[ -f "$backup_content_dir/$COMPOSE_FILE" ]]; then
        log_info "Restoring Docker Compose configuration..."
        if [[ "$DRY_RUN" != "true" ]]; then
            cp "$backup_content_dir/$COMPOSE_FILE" "$PROJECT_ROOT/"
        else
            log_info "[DRY RUN] Would restore compose file"
        fi
    fi

    if [[ -f "$backup_content_dir/.env" ]]; then
        log_info "Restoring environment configuration..."
        if [[ "$DRY_RUN" != "true" ]]; then
            cp "$backup_content_dir/.env" "$PROJECT_ROOT/"
        else
            log_info "[DRY RUN] Would restore .env file"
        fi
    fi

    # Start services with restored configuration
    if [[ "$DRY_RUN" != "true" ]]; then
        log_info "Starting services with restored configuration..."
        cd "$PROJECT_ROOT"
        docker-compose -f "$COMPOSE_FILE" up -d
    else
        log_info "[DRY RUN] Would start services with restored configuration"
    fi

    # Cleanup
    rm -rf "$temp_dir"

    log_success "Rollback completed successfully"
}

# Wait for services to be healthy
wait_for_health() {
    log_info "Waiting for services to be healthy after rollback..."

    # Use the health check script
    local health_script="$SCRIPT_DIR/health_check.sh"
    if [[ -x "$health_script" ]]; then
        local retries=0
        local max_retries=30  # 5 minutes with 10s intervals

        while [[ $retries -lt $max_retries ]]; do
            if "$health_script" --quiet; then
                log_success "All services are healthy after rollback"
                return 0
            fi

            log_info "Services not ready yet, waiting... ($retries/$max_retries)"
            sleep 10
            retries=$((retries + 1))
        done

        log_error "Services failed to become healthy after rollback"
        return 1
    else
        log_warn "Health check script not found, skipping health verification"
        return 0
    fi
}

# Confirmation prompt
confirm_rollback() {
    local backup_file="$1"

    if [[ "$FORCE" == "true" ]]; then
        return 0
    fi

    echo
    log_warn "⚠️  WARNING: This will rollback your Brain Researcher deployment!"
    echo
    echo "Current deployment will be stopped and replaced with:"
    echo "  Backup: $(basename "$backup_file")"
    echo "  Location: $backup_file"
    echo
    echo "This operation will:"
    echo "  • Stop all current services"
    echo "  • Replace the database with backup data"
    echo "  • Replace configuration files"
    echo "  • Start services with restored state"
    echo

    read -p "Are you sure you want to continue? (y/N): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Rollback cancelled by user"
        exit 0
    fi
}

# Main rollback function
main() {
    # Initialize logging
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"

    log_info "Starting Brain Researcher rollback process"

    # Handle list backups
    if [[ "$LIST_BACKUPS" == "true" ]]; then
        list_backups
        exit 0
    fi

    # Find backup to restore
    local backup_file
    backup_file=$(find_latest_backup)

    log_info "Selected backup: $backup_file"

    # Validate backup
    if ! validate_backup "$backup_file"; then
        exit 1
    fi

    # Show backup information
    show_backup_info "$backup_file"

    # Get confirmation
    confirm_rollback "$backup_file"

    # Save current state
    if [[ "$DRY_RUN" != "true" ]]; then
        save_current_state
    fi

    # Perform rollback
    perform_rollback "$backup_file"

    # Wait for health if not dry run and not skipped
    if [[ "$DRY_RUN" != "true" && "$SKIP_HEALTH" != "true" ]]; then
        if ! wait_for_health; then
            log_error "Rollback completed but services are not healthy"
            log_info "Check service logs: docker-compose -f $COMPOSE_FILE logs"
            exit 1
        fi
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
        log_success "🔄 Dry run completed - no changes were made"
    else
        log_success "🎉 Rollback completed successfully!"
        log_info "Services should be accessible at their normal endpoints"
        log_info "Pre-rollback state saved for potential recovery"
    fi
}

# Error handling
cleanup_on_error() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        log_error "Rollback failed with exit code $exit_code"
        log_error "Check log file: $LOG_FILE"
    fi
    exit $exit_code
}

trap cleanup_on_error EXIT

# Parse arguments and run main
parse_args "$@"
main