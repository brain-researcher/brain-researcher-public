#!/bin/bash

# Brain Researcher Istio Verification Script
# This script verifies the Istio service mesh installation and configuration

set -e

# Configuration
BRAIN_RESEARCHER_NAMESPACE="brain-researcher"
ISTIO_NAMESPACE="istio-system"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test results tracking
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_WARNINGS=0

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
    ((TESTS_PASSED++))
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
    ((TESTS_WARNINGS++))
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    ((TESTS_FAILED++))
}

log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

# Help function
show_help() {
    cat << EOF
Brain Researcher Istio Verification Script

Usage: $0 [OPTIONS]

Options:
    -h, --help                 Show this help message
    -n, --namespace NAMESPACE  Brain Researcher namespace (default: ${BRAIN_RESEARCHER_NAMESPACE})
    --istio-namespace NAMESPACE Istio namespace (default: ${ISTIO_NAMESPACE})
    --verbose                  Verbose output
    --quick                    Quick verification (skip comprehensive tests)
    --connectivity             Test service connectivity
    --security                 Test security policies
    --performance              Test performance metrics
    --export-report FILE       Export verification report to file

Examples:
    $0                         # Full verification
    $0 --quick                 # Quick verification
    $0 --connectivity          # Test connectivity only
    $0 --export-report report.json

EOF
}

# Parse command line arguments
VERBOSE=false
QUICK=false
TEST_CONNECTIVITY=false
TEST_SECURITY=false
TEST_PERFORMANCE=false
EXPORT_REPORT=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -n|--namespace)
            BRAIN_RESEARCHER_NAMESPACE="$2"
            shift 2
            ;;
        --istio-namespace)
            ISTIO_NAMESPACE="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --quick)
            QUICK=true
            shift
            ;;
        --connectivity)
            TEST_CONNECTIVITY=true
            shift
            ;;
        --security)
            TEST_SECURITY=true
            shift
            ;;
        --performance)
            TEST_PERFORMANCE=true
            shift
            ;;
        --export-report)
            EXPORT_REPORT="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Utility functions
run_command() {
    local cmd="$1"
    local description="$2"
    
    if [[ "$VERBOSE" == "true" ]]; then
        log_info "Running: $cmd"
    fi
    
    if eval "$cmd" &> /dev/null; then
        log_success "$description"
        return 0
    else
        log_error "$description"
        if [[ "$VERBOSE" == "true" ]]; then
            eval "$cmd" || true
        fi
        return 1
    fi
}

check_command_exists() {
    local cmd="$1"
    local description="$2"
    
    if command -v "$cmd" &> /dev/null; then
        log_success "$description is available"
        return 0
    else
        log_error "$description is not available"
        return 1
    fi
}

wait_for_pods() {
    local namespace="$1"
    local label_selector="$2"
    local timeout="$3"
    
    log_info "Waiting for pods in $namespace with selector $label_selector..."
    
    if kubectl wait --for=condition=Ready pods -l "$label_selector" -n "$namespace" --timeout="${timeout}s" &> /dev/null; then
        log_success "Pods are ready in $namespace"
        return 0
    else
        log_error "Pods failed to become ready in $namespace within ${timeout}s"
        return 1
    fi
}

# Verification functions
verify_prerequisites() {
    log_test "Verifying prerequisites..."
    
    check_command_exists "kubectl" "kubectl"
    check_command_exists "istioctl" "istioctl"
    check_command_exists "helm" "helm"
    
    # Check kubectl connectivity
    if kubectl cluster-info &> /dev/null; then
        log_success "Kubernetes cluster is accessible"
    else
        log_error "Cannot connect to Kubernetes cluster"
    fi
    
    # Check Istio version
    local istio_version=$(istioctl version --client --short 2>/dev/null | cut -d' ' -f2 || echo "unknown")
    if [[ "$istio_version" != "unknown" ]]; then
        log_success "Istio client version: $istio_version"
    else
        log_error "Unable to determine Istio client version"
    fi
}

verify_namespaces() {
    log_test "Verifying namespaces..."
    
    # Check Istio namespace
    if kubectl get namespace "$ISTIO_NAMESPACE" &> /dev/null; then
        log_success "Istio namespace '$ISTIO_NAMESPACE' exists"
    else
        log_error "Istio namespace '$ISTIO_NAMESPACE' does not exist"
    fi
    
    # Check Brain Researcher namespace
    if kubectl get namespace "$BRAIN_RESEARCHER_NAMESPACE" &> /dev/null; then
        log_success "Brain Researcher namespace '$BRAIN_RESEARCHER_NAMESPACE' exists"
        
        # Check sidecar injection label
        local injection_label=$(kubectl get namespace "$BRAIN_RESEARCHER_NAMESPACE" -o jsonpath='{.metadata.labels.istio-injection}' 2>/dev/null || echo "")
        if [[ "$injection_label" == "enabled" ]]; then
            log_success "Sidecar injection is enabled for '$BRAIN_RESEARCHER_NAMESPACE'"
        else
            log_warning "Sidecar injection is not enabled for '$BRAIN_RESEARCHER_NAMESPACE'"
        fi
    else
        log_error "Brain Researcher namespace '$BRAIN_RESEARCHER_NAMESPACE' does not exist"
    fi
}

verify_istio_components() {
    log_test "Verifying Istio core components..."
    
    # Check Istiod
    if kubectl get deployment istiod -n "$ISTIO_NAMESPACE" &> /dev/null; then
        log_success "Istiod deployment exists"
        
        local ready_replicas=$(kubectl get deployment istiod -n "$ISTIO_NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        local desired_replicas=$(kubectl get deployment istiod -n "$ISTIO_NAMESPACE" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
        
        if [[ "$ready_replicas" -eq "$desired_replicas" ]]; then
            log_success "Istiod is ready ($ready_replicas/$desired_replicas replicas)"
        else
            log_error "Istiod is not ready ($ready_replicas/$desired_replicas replicas)"
        fi
    else
        log_error "Istiod deployment not found"
    fi
    
    # Check Istio ingress gateway
    if kubectl get deployment istio-ingressgateway -n "$ISTIO_NAMESPACE" &> /dev/null; then
        log_success "Istio ingress gateway deployment exists"
    elif kubectl get deployment -l app=istio-ingressgateway -n "$ISTIO_NAMESPACE" &> /dev/null; then
        log_success "Istio ingress gateway deployment exists (with label selector)"
    else
        log_warning "Istio ingress gateway deployment not found"
    fi
    
    # Check Istio proxy version
    local proxy_version=$(istioctl proxy-status 2>/dev/null | head -n 2 | tail -n 1 | awk '{print $3}' || echo "")
    if [[ -n "$proxy_version" ]]; then
        log_success "Istio proxy version: $proxy_version"
    else
        log_warning "Unable to determine Istio proxy version"
    fi
}

verify_brain_researcher_resources() {
    log_test "Verifying Brain Researcher Istio resources..."
    
    # Check Gateways
    local gateways=$(kubectl get gateway -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo "0")
    if [[ "$gateways" -gt 0 ]]; then
        log_success "Found $gateways Gateway(s)"
        if [[ "$VERBOSE" == "true" ]]; then
            kubectl get gateway -n "$BRAIN_RESEARCHER_NAMESPACE"
        fi
    else
        log_warning "No Gateways found"
    fi
    
    # Check VirtualServices
    local virtual_services=$(kubectl get virtualservice -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo "0")
    if [[ "$virtual_services" -gt 0 ]]; then
        log_success "Found $virtual_services VirtualService(s)"
    else
        log_warning "No VirtualServices found"
    fi
    
    # Check DestinationRules
    local destination_rules=$(kubectl get destinationrule -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo "0")
    if [[ "$destination_rules" -gt 0 ]]; then
        log_success "Found $destination_rules DestinationRule(s)"
    else
        log_warning "No DestinationRules found"
    fi
    
    # Check PeerAuthentications
    local peer_auths=$(kubectl get peerauthentication -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo "0")
    if [[ "$peer_auths" -gt 0 ]]; then
        log_success "Found $peer_auths PeerAuthentication(s)"
    else
        log_warning "No PeerAuthentications found"
    fi
    
    # Check AuthorizationPolicies
    local auth_policies=$(kubectl get authorizationpolicy -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo "0")
    if [[ "$auth_policies" -gt 0 ]]; then
        log_success "Found $auth_policies AuthorizationPolicy(ies)"
    else
        log_warning "No AuthorizationPolicies found"
    fi
}

verify_istio_analysis() {
    log_test "Running Istio configuration analysis..."
    
    local analysis_output=$(istioctl analyze -n "$BRAIN_RESEARCHER_NAMESPACE" 2>&1)
    local analysis_exit_code=$?
    
    if [[ $analysis_exit_code -eq 0 ]]; then
        if echo "$analysis_output" | grep -q "No validation issues found"; then
            log_success "Istio configuration analysis passed - no issues found"
        else
            log_success "Istio configuration analysis completed"
            if [[ "$VERBOSE" == "true" ]]; then
                echo "$analysis_output"
            fi
        fi
    else
        log_error "Istio configuration analysis found issues:"
        echo "$analysis_output"
    fi
}

test_service_connectivity() {
    if [[ "$TEST_CONNECTIVITY" != "true" && "$QUICK" == "true" ]]; then
        return 0
    fi
    
    log_test "Testing service connectivity..."
    
    # Get list of services in Brain Researcher namespace
    local services=$(kubectl get svc -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers -o custom-columns=":metadata.name" 2>/dev/null || echo "")
    
    if [[ -z "$services" ]]; then
        log_warning "No services found in $BRAIN_RESEARCHER_NAMESPACE namespace"
        return 0
    fi
    
    # Create a test pod for connectivity testing
    local test_pod="istio-connectivity-test"
    
    log_info "Creating test pod for connectivity testing..."
    kubectl run "$test_pod" --image=curlimages/curl:latest --rm -i --restart=Never -n "$BRAIN_RESEARCHER_NAMESPACE" -- sleep 3600 &> /dev/null &
    local test_pod_pid=$!
    
    # Wait for test pod to be ready
    sleep 10
    
    if kubectl wait --for=condition=Ready pod/"$test_pod" -n "$BRAIN_RESEARCHER_NAMESPACE" --timeout=60s &> /dev/null; then
        log_success "Test pod created successfully"
        
        # Test connectivity to each service
        while IFS= read -r service; do
            if [[ -n "$service" ]]; then
                local result=$(kubectl exec "$test_pod" -n "$BRAIN_RESEARCHER_NAMESPACE" -- curl -s -o /dev/null -w "%{http_code}" "http://$service:8080/health" --max-time 10 2>/dev/null || echo "000")
                
                if [[ "$result" =~ ^[2-3][0-9][0-9]$ ]]; then
                    log_success "Connectivity test passed for service: $service (HTTP $result)"
                else
                    log_warning "Connectivity test failed for service: $service (HTTP $result)"
                fi
            fi
        done <<< "$services"
        
        # Clean up test pod
        kubectl delete pod "$test_pod" -n "$BRAIN_RESEARCHER_NAMESPACE" &> /dev/null || true
        wait $test_pod_pid 2>/dev/null || true
    else
        log_error "Test pod failed to become ready"
        kubectl delete pod "$test_pod" -n "$BRAIN_RESEARCHER_NAMESPACE" &> /dev/null || true
    fi
}

test_mtls_configuration() {
    if [[ "$TEST_SECURITY" != "true" && "$QUICK" == "true" ]]; then
        return 0
    fi
    
    log_test "Testing mTLS configuration..."
    
    # Get services with Istio sidecars
    local services=$(kubectl get pods -n "$BRAIN_RESEARCHER_NAMESPACE" -o json 2>/dev/null | \
        jq -r '.items[] | select(.spec.containers[]?.name == "istio-proxy") | .metadata.labels.app // .metadata.name' 2>/dev/null || echo "")
    
    if [[ -z "$services" ]]; then
        log_warning "No services with Istio sidecars found"
        return 0
    fi
    
    while IFS= read -r service; do
        if [[ -n "$service" ]]; then
            local tls_check=$(istioctl authn tls-check "$service.$BRAIN_RESEARCHER_NAMESPACE.svc.cluster.local" 2>/dev/null | tail -n 1 || echo "")
            
            if echo "$tls_check" | grep -q "OK"; then
                log_success "mTLS check passed for service: $service"
            elif echo "$tls_check" | grep -q "STRICT\|PERMISSIVE"; then
                log_success "mTLS is configured for service: $service"
            else
                log_warning "mTLS check inconclusive for service: $service"
                if [[ "$VERBOSE" == "true" ]]; then
                    echo "$tls_check"
                fi
            fi
        fi
    done <<< "$services"
}

test_observability() {
    if [[ "$TEST_PERFORMANCE" != "true" && "$QUICK" == "true" ]]; then
        return 0
    fi
    
    log_test "Testing observability features..."
    
    # Check if Prometheus is accessible
    if kubectl get svc prometheus -n "$BRAIN_RESEARCHER_NAMESPACE" &> /dev/null; then
        log_success "Prometheus service found"
        
        # Test Prometheus metrics endpoint
        local prometheus_test=$(kubectl exec -n "$BRAIN_RESEARCHER_NAMESPACE" deployment/prometheus -- wget -qO- http://localhost:9090/-/ready 2>/dev/null || echo "error")
        if [[ "$prometheus_test" == "Prometheus is Ready." ]]; then
            log_success "Prometheus is ready and serving metrics"
        else
            log_warning "Prometheus may not be ready"
        fi
    else
        log_warning "Prometheus service not found"
    fi
    
    # Check if Kiali is accessible
    if kubectl get svc kiali -n "$ISTIO_NAMESPACE" &> /dev/null; then
        log_success "Kiali service found"
    else
        log_warning "Kiali service not found"
    fi
    
    # Check if Jaeger is available
    if kubectl get svc jaeger-query -n "$ISTIO_NAMESPACE" &> /dev/null; then
        log_success "Jaeger query service found"
    else
        log_warning "Jaeger service not found"
    fi
}

test_gateway_connectivity() {
    log_test "Testing gateway connectivity..."
    
    # Get ingress gateway external IP
    local gateway_ip=$(kubectl get svc istio-ingressgateway -n "$ISTIO_NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)
    
    if [[ -z "$gateway_ip" ]]; then
        # Try to get external hostname
        gateway_ip=$(kubectl get svc istio-ingressgateway -n "$ISTIO_NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)
    fi
    
    if [[ -z "$gateway_ip" ]]; then
        # If LoadBalancer type, try NodePort
        local node_port=$(kubectl get svc istio-ingressgateway -n "$ISTIO_NAMESPACE" -o jsonpath='{.spec.ports[?(@.name=="http2")].nodePort}' 2>/dev/null)
        if [[ -n "$node_port" ]]; then
            local node_ip=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null)
            if [[ -n "$node_ip" ]]; then
                gateway_ip="$node_ip:$node_port"
                log_success "Found gateway at NodePort: $gateway_ip"
            else
                log_warning "Could not determine gateway external access point"
                return 0
            fi
        else
            log_warning "Could not determine gateway external IP or hostname"
            return 0
        fi
    else
        log_success "Found gateway external IP: $gateway_ip"
    fi
    
    # Test gateway connectivity (basic HTTP check)
    if command -v curl &> /dev/null; then
        local gateway_response=$(curl -s -o /dev/null -w "%{http_code}" "http://$gateway_ip" --max-time 10 2>/dev/null || echo "000")
        
        if [[ "$gateway_response" =~ ^[2-4][0-9][0-9]$ ]]; then
            log_success "Gateway is responding (HTTP $gateway_response)"
        else
            log_warning "Gateway connectivity test inconclusive (HTTP $gateway_response)"
        fi
    else
        log_warning "curl not available for gateway connectivity test"
    fi
}

generate_report() {
    local report_data="{
        \"timestamp\": \"$(date -u +"%Y-%m-%dT%H:%M:%SZ")\",
        \"brain_researcher_namespace\": \"$BRAIN_RESEARCHER_NAMESPACE\",
        \"istio_namespace\": \"$ISTIO_NAMESPACE\",
        \"tests\": {
            \"passed\": $TESTS_PASSED,
            \"failed\": $TESTS_FAILED,
            \"warnings\": $TESTS_WARNINGS,
            \"total\": $((TESTS_PASSED + TESTS_FAILED + TESTS_WARNINGS))
        },
        \"istio_version\": \"$(istioctl version --client --short 2>/dev/null | cut -d' ' -f2 || echo 'unknown')\",
        \"kubernetes_version\": \"$(kubectl version --short --client 2>/dev/null | grep 'Client Version' | cut -d' ' -f3 || echo 'unknown')\",
        \"resources\": {
            \"gateways\": $(kubectl get gateway -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo 0),
            \"virtual_services\": $(kubectl get virtualservice -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo 0),
            \"destination_rules\": $(kubectl get destinationrule -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo 0),
            \"peer_authentications\": $(kubectl get peerauthentication -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo 0),
            \"authorization_policies\": $(kubectl get authorizationpolicy -n "$BRAIN_RESEARCHER_NAMESPACE" --no-headers 2>/dev/null | wc -l || echo 0)
        }
    }"
    
    if [[ -n "$EXPORT_REPORT" ]]; then
        echo "$report_data" | jq '.' > "$EXPORT_REPORT" 2>/dev/null || echo "$report_data" > "$EXPORT_REPORT"
        log_success "Verification report exported to: $EXPORT_REPORT"
    fi
    
    return "$report_data"
}

print_summary() {
    local total_tests=$((TESTS_PASSED + TESTS_FAILED + TESTS_WARNINGS))
    
    echo ""
    echo "=================================================="
    echo "         ISTIO VERIFICATION SUMMARY"
    echo "=================================================="
    echo "Total Tests: $total_tests"
    echo "Passed: $TESTS_PASSED"
    echo "Failed: $TESTS_FAILED"
    echo "Warnings: $TESTS_WARNINGS"
    echo ""
    
    if [[ $TESTS_FAILED -eq 0 ]]; then
        if [[ $TESTS_WARNINGS -eq 0 ]]; then
            log_success "All tests passed! Istio installation is healthy."
            echo ""
            echo "Your Brain Researcher service mesh is ready for use!"
        else
            log_warning "Tests passed with $TESTS_WARNINGS warning(s). Review the warnings above."
        fi
    else
        log_error "$TESTS_FAILED test(s) failed. Please review the errors above."
        echo ""
        echo "Common troubleshooting steps:"
        echo "1. Check pod logs: kubectl logs -f deployment/istiod -n $ISTIO_NAMESPACE"
        echo "2. Run Istio analysis: istioctl analyze"
        echo "3. Check service mesh status: istioctl proxy-status"
        echo "4. Verify configuration: kubectl get all -n $ISTIO_NAMESPACE"
    fi
    
    echo ""
    echo "Next steps:"
    echo "1. Deploy your Brain Researcher services"
    echo "2. Monitor with Kiali: kubectl port-forward svc/kiali 20001:20001 -n $ISTIO_NAMESPACE"
    echo "3. View metrics with Prometheus: kubectl port-forward svc/prometheus 9090:9090 -n $BRAIN_RESEARCHER_NAMESPACE"
    echo "=================================================="
}

# Main execution
main() {
    log_info "Starting Brain Researcher Istio verification..."
    log_info "Brain Researcher namespace: $BRAIN_RESEARCHER_NAMESPACE"
    log_info "Istio namespace: $ISTIO_NAMESPACE"
    
    if [[ "$QUICK" == "true" ]]; then
        log_info "Running quick verification..."
    fi
    
    # Core verification tests
    verify_prerequisites
    verify_namespaces
    verify_istio_components
    verify_brain_researcher_resources
    verify_istio_analysis
    test_gateway_connectivity
    
    # Optional comprehensive tests
    if [[ "$QUICK" != "true" ]] || [[ "$TEST_CONNECTIVITY" == "true" ]]; then
        test_service_connectivity
    fi
    
    if [[ "$QUICK" != "true" ]] || [[ "$TEST_SECURITY" == "true" ]]; then
        test_mtls_configuration
    fi
    
    if [[ "$QUICK" != "true" ]] || [[ "$TEST_PERFORMANCE" == "true" ]]; then
        test_observability
    fi
    
    # Generate report if requested
    if [[ -n "$EXPORT_REPORT" ]]; then
        generate_report
    fi
    
    print_summary
    
    # Exit with appropriate code
    if [[ $TESTS_FAILED -gt 0 ]]; then
        exit 1
    else
        exit 0
    fi
}

# Handle script interruption
trap 'log_error "Verification interrupted"; exit 1' INT TERM

# Run main function
main "$@"