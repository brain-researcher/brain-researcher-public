#!/bin/bash

# Brain Researcher Istio Installation Script
# This script installs and configures Istio service mesh for the Brain Researcher platform

set -e

# Configuration
ISTIO_VERSION="1.19.0"
BRAIN_RESEARCHER_NAMESPACE="brain-researcher"
ISTIO_NAMESPACE="istio-system"
HELM_RELEASE_NAME="brain-researcher-istio"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Help function
show_help() {
    cat << EOF
Brain Researcher Istio Installation Script

Usage: $0 [OPTIONS]

Options:
    -h, --help                 Show this help message
    -v, --version VERSION      Istio version to install (default: ${ISTIO_VERSION})
    -n, --namespace NAMESPACE  Brain Researcher namespace (default: ${BRAIN_RESEARCHER_NAMESPACE})
    --dry-run                  Show what would be done without making changes
    --skip-prereqs             Skip prerequisite checks
    --uninstall                Uninstall Istio service mesh
    --upgrade                  Upgrade existing installation
    --values-file FILE         Custom Helm values file
    --minimal                  Install minimal Istio configuration
    --dev                      Development mode with relaxed security

Examples:
    $0                         # Install with default settings
    $0 --dry-run               # Preview installation
    $0 --uninstall             # Remove Istio
    $0 --upgrade               # Upgrade existing installation
    $0 --dev                   # Install for development

EOF
}

# Parse command line arguments
DRY_RUN=false
SKIP_PREREQS=false
UNINSTALL=false
UPGRADE=false
MINIMAL=false
DEV_MODE=false
CUSTOM_VALUES_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -v|--version)
            ISTIO_VERSION="$2"
            shift 2
            ;;
        -n|--namespace)
            BRAIN_RESEARCHER_NAMESPACE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-prereqs)
            SKIP_PREREQS=true
            shift
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        --upgrade)
            UPGRADE=true
            shift
            ;;
        --values-file)
            CUSTOM_VALUES_FILE="$2"
            shift 2
            ;;
        --minimal)
            MINIMAL=true
            shift
            ;;
        --dev)
            DEV_MODE=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Check prerequisites
check_prerequisites() {
    if [[ "$SKIP_PREREQS" == "true" ]]; then
        log_warning "Skipping prerequisite checks"
        return 0
    fi

    log_info "Checking prerequisites..."

    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is required but not installed"
        exit 1
    fi

    # Check if helm is available
    if ! command -v helm &> /dev/null; then
        log_error "helm is required but not installed"
        exit 1
    fi

    # Check if curl is available
    if ! command -v curl &> /dev/null; then
        log_error "curl is required but not installed"
        exit 1
    fi

    # Check kubectl connectivity
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi

    # Check if cluster has sufficient resources
    local nodes=$(kubectl get nodes --no-headers | wc -l)
    if [[ $nodes -lt 1 ]]; then
        log_error "No Kubernetes nodes available"
        exit 1
    fi

    # Check if Brain Researcher namespace exists
    if ! kubectl get namespace "$BRAIN_RESEARCHER_NAMESPACE" &> /dev/null; then
        log_warning "Brain Researcher namespace '$BRAIN_RESEARCHER_NAMESPACE' does not exist, creating it..."
        if [[ "$DRY_RUN" == "false" ]]; then
            kubectl create namespace "$BRAIN_RESEARCHER_NAMESPACE"
        fi
    fi

    log_success "Prerequisites check passed"
}

# Install Istio CLI
install_istioctl() {
    local istioctl_path="/usr/local/bin/istioctl"
    
    if command -v istioctl &> /dev/null; then
        local current_version=$(istioctl version --client --short | cut -d' ' -f2 || echo "unknown")
        if [[ "$current_version" == "$ISTIO_VERSION" ]]; then
            log_info "istioctl $ISTIO_VERSION is already installed"
            return 0
        fi
    fi

    log_info "Installing istioctl $ISTIO_VERSION..."

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would install istioctl $ISTIO_VERSION"
        return 0
    fi

    # Download and install istioctl
    local temp_dir=$(mktemp -d)
    cd "$temp_dir"

    curl -L "https://istio.io/downloadIstio" | ISTIO_VERSION="$ISTIO_VERSION" sh -

    # Move istioctl to PATH
    sudo cp "istio-${ISTIO_VERSION}/bin/istioctl" "$istioctl_path"
    sudo chmod +x "$istioctl_path"

    # Verify installation
    istioctl version --client

    # Cleanup
    cd - > /dev/null
    rm -rf "$temp_dir"

    log_success "istioctl $ISTIO_VERSION installed successfully"
}

# Prepare Helm values
prepare_helm_values() {
    local values_file="${PROJECT_ROOT}/infrastructure/k8s/helm/brain-researcher-istio/values.yaml"
    local temp_values="/tmp/brain-researcher-istio-values.yaml"

    if [[ -n "$CUSTOM_VALUES_FILE" ]]; then
        if [[ ! -f "$CUSTOM_VALUES_FILE" ]]; then
            log_error "Custom values file not found: $CUSTOM_VALUES_FILE"
            exit 1
        fi
        values_file="$CUSTOM_VALUES_FILE"
    fi

    cp "$values_file" "$temp_values"

    # Apply modifications based on flags
    if [[ "$DEV_MODE" == "true" ]]; then
        log_info "Applying development mode configuration..."
        # Relax security settings for development
        yq eval '.security.globalMtls.mode = "PERMISSIVE"' -i "$temp_values"
        yq eval '.security.authorizationPolicies.denyAll.enabled = false' -i "$temp_values"
        yq eval '.telemetry.tracing.samplingRate = 100.0' -i "$temp_values"
    fi

    if [[ "$MINIMAL" == "true" ]]; then
        log_info "Applying minimal configuration..."
        # Disable non-essential features
        yq eval '.observability.kiali.enabled = false' -i "$temp_values"
        yq eval '.telemetry.tracing.enabled = false' -i "$temp_values"
        yq eval '.multiCluster.enabled = false' -i "$temp_values"
    fi

    # Update namespace
    yq eval ".global.brainResearcher.namespace = \"$BRAIN_RESEARCHER_NAMESPACE\"" -i "$temp_values"

    echo "$temp_values"
}

# Install Istio using Helm
install_istio() {
    log_info "Installing Istio service mesh..."

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would install Istio with Helm"
        return 0
    fi

    # Add Istio Helm repository
    helm repo add istio https://istio-release.storage.googleapis.com/charts
    helm repo update

    # Install Istio base
    log_info "Installing Istio base..."
    helm upgrade --install istio-base istio/base \
        --namespace "$ISTIO_NAMESPACE" \
        --create-namespace \
        --version "$ISTIO_VERSION" \
        --wait

    # Install Istiod
    log_info "Installing Istiod..."
    helm upgrade --install istiod istio/istiod \
        --namespace "$ISTIO_NAMESPACE" \
        --version "$ISTIO_VERSION" \
        --wait

    # Install Istio Gateway
    log_info "Installing Istio Gateway..."
    helm upgrade --install istio-ingressgateway istio/gateway \
        --namespace "$ISTIO_NAMESPACE" \
        --version "$ISTIO_VERSION" \
        --set service.type=LoadBalancer \
        --wait

    log_success "Istio core components installed successfully"
}

# Install Brain Researcher Istio configuration
install_brain_researcher_config() {
    log_info "Installing Brain Researcher Istio configuration..."

    local values_file=$(prepare_helm_values)
    local helm_chart_dir="${PROJECT_ROOT}/infrastructure/k8s/helm/brain-researcher-istio"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would install Brain Researcher Istio configuration"
        helm template "$HELM_RELEASE_NAME" "$helm_chart_dir" \
            --namespace "$BRAIN_RESEARCHER_NAMESPACE" \
            --values "$values_file" \
            --dry-run
        return 0
    fi

    # Install Brain Researcher Istio configuration
    if [[ "$UPGRADE" == "true" ]]; then
        log_info "Upgrading existing Brain Researcher Istio configuration..."
        helm upgrade "$HELM_RELEASE_NAME" "$helm_chart_dir" \
            --namespace "$BRAIN_RESEARCHER_NAMESPACE" \
            --values "$values_file" \
            --wait
    else
        helm upgrade --install "$HELM_RELEASE_NAME" "$helm_chart_dir" \
            --namespace "$BRAIN_RESEARCHER_NAMESPACE" \
            --create-namespace \
            --values "$values_file" \
            --wait
    fi

    # Cleanup temporary values file
    rm -f "$values_file"

    log_success "Brain Researcher Istio configuration installed successfully"
}

# Enable sidecar injection for Brain Researcher namespace
enable_sidecar_injection() {
    log_info "Enabling sidecar injection for $BRAIN_RESEARCHER_NAMESPACE namespace..."

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would enable sidecar injection"
        return 0
    fi

    kubectl label namespace "$BRAIN_RESEARCHER_NAMESPACE" istio-injection=enabled --overwrite

    log_success "Sidecar injection enabled for $BRAIN_RESEARCHER_NAMESPACE"
}

# Apply additional configurations
apply_additional_configs() {
    log_info "Applying additional Istio configurations..."

    local config_dir="${PROJECT_ROOT}/k8s/istio"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would apply additional configurations from $config_dir"
        return 0
    fi

    # Apply Istio operator if it exists
    if [[ -f "$config_dir/installation/istio-operator.yaml" ]]; then
        log_info "Applying Istio operator configuration..."
        kubectl apply -f "$config_dir/installation/istio-operator.yaml"
    fi

    log_success "Additional configurations applied"
}

# Verify installation
verify_installation() {
    log_info "Verifying Istio installation..."

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would verify installation"
        return 0
    fi

    # Check if Istio system pods are running
    log_info "Checking Istio system pods..."
    kubectl get pods -n "$ISTIO_NAMESPACE"

    # Check if Istio is healthy
    log_info "Running Istio analysis..."
    istioctl analyze

    # Check if Brain Researcher resources are created
    log_info "Checking Brain Researcher Istio resources..."
    kubectl get gateway,virtualservice,destinationrule,peerauthentication,authorizationpolicy -n "$BRAIN_RESEARCHER_NAMESPACE"

    # Check sidecar injection
    log_info "Checking sidecar injection status..."
    kubectl get namespace "$BRAIN_RESEARCHER_NAMESPACE" -o jsonpath='{.metadata.labels.istio-injection}'
    echo ""

    log_success "Installation verification completed"
}

# Uninstall Istio
uninstall_istio() {
    log_info "Uninstalling Istio service mesh..."

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] Would uninstall Istio"
        return 0
    fi

    # Remove Brain Researcher configuration
    log_info "Removing Brain Researcher Istio configuration..."
    helm uninstall "$HELM_RELEASE_NAME" -n "$BRAIN_RESEARCHER_NAMESPACE" || true

    # Remove sidecar injection label
    kubectl label namespace "$BRAIN_RESEARCHER_NAMESPACE" istio-injection- || true

    # Uninstall Istio components
    log_info "Uninstalling Istio gateway..."
    helm uninstall istio-ingressgateway -n "$ISTIO_NAMESPACE" || true

    log_info "Uninstalling Istiod..."
    helm uninstall istiod -n "$ISTIO_NAMESPACE" || true

    log_info "Uninstalling Istio base..."
    helm uninstall istio-base -n "$ISTIO_NAMESPACE" || true

    # Clean up CRDs
    log_info "Cleaning up Istio CRDs..."
    kubectl get crd -o name | grep --color=never 'istio.io' | xargs -r kubectl delete || true

    # Remove namespace if empty
    if kubectl get all -n "$ISTIO_NAMESPACE" --no-headers 2>/dev/null | wc -l | grep -q "^0$"; then
        log_info "Removing empty Istio namespace..."
        kubectl delete namespace "$ISTIO_NAMESPACE" || true
    fi

    log_success "Istio uninstallation completed"
}

# Print installation summary
print_summary() {
    if [[ "$DRY_RUN" == "true" ]]; then
        echo ""
        log_info "=== DRY RUN SUMMARY ==="
        log_info "Would install Istio $ISTIO_VERSION"
        log_info "Would configure Brain Researcher service mesh"
        log_info "Target namespace: $BRAIN_RESEARCHER_NAMESPACE"
        return 0
    fi

    echo ""
    log_success "=== INSTALLATION COMPLETE ==="
    log_success "Istio version: $ISTIO_VERSION"
    log_success "Brain Researcher namespace: $BRAIN_RESEARCHER_NAMESPACE"
    log_success "Istio namespace: $ISTIO_NAMESPACE"
    
    echo ""
    log_info "Next steps:"
    log_info "1. Verify installation: ${SCRIPT_DIR}/verify_installation.sh"
    log_info "2. Deploy Brain Researcher services with sidecar injection"
    log_info "3. Access Kiali dashboard: kubectl port-forward svc/kiali 20001:20001 -n $ISTIO_NAMESPACE"
    
    echo ""
    log_info "Useful commands:"
    log_info "- Check proxy status: istioctl proxy-status"
    log_info "- Analyze configuration: istioctl analyze"
    log_info "- View service mesh: kubectl get svc,pods -n $ISTIO_NAMESPACE"
}

# Main execution
main() {
    log_info "Starting Brain Researcher Istio installation..."
    log_info "Version: $ISTIO_VERSION"
    log_info "Namespace: $BRAIN_RESEARCHER_NAMESPACE"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log_warning "Running in dry-run mode - no changes will be made"
    fi

    if [[ "$UNINSTALL" == "true" ]]; then
        uninstall_istio
        log_success "Uninstallation completed"
        exit 0
    fi

    check_prerequisites
    install_istioctl
    install_istio
    install_brain_researcher_config
    enable_sidecar_injection
    apply_additional_configs
    verify_installation
    print_summary
}

# Handle script interruption
trap 'log_error "Installation interrupted"; exit 1' INT TERM

# Run main function
main "$@"
