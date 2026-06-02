#!/bin/bash

# Brain Researcher Data Ingestion Script
# This script provides various options for running data ingestion

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project directory
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_DIR"

# Function to print colored messages
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to show help
show_help() {
    cat << EOF
🧠 Brain Researcher Data Ingestion Tool

Usage: ./run_ingestion.sh [OPTIONS]

Options:
    quick           Run quick test with limited data
    full            Run full ingestion of all sources
    brainmap        Load only BrainMap data
    core            Load core sources (Cognitive Atlas, PubMed, BrainMap)
    ondemand        Register on-demand evidence adapters (NeuroQuery/NiMARE/Neuroscout/Allen HBA)
    docker          Start Docker services and run full ingestion
    test            Run tests to verify installation
    clean           Clean temporary files and cache
    help            Show this help message

Examples:
    ./run_ingestion.sh quick          # Quick test
    ./run_ingestion.sh full           # Full ingestion
    ./run_ingestion.sh brainmap       # Load only BrainMap
    ./run_ingestion.sh ondemand       # Register on-demand adapters
    ./run_ingestion.sh docker         # Start Docker and ingest

Configuration:
    Edit configs/br-kg/data_config.json to customize ingestion settings

EOF
}

# Function to check Python environment
check_environment() {
    print_info "Checking environment..."

    # Check Python version
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        print_success "Python $PYTHON_VERSION found"
    else
        print_error "Python 3 not found"
        exit 1
    fi

    # Check if virtual environment is activated
    if [[ "$VIRTUAL_ENV" != "" ]]; then
        print_success "Virtual environment activated: $VIRTUAL_ENV"
    else
        print_warning "No virtual environment detected. Consider activating one."
    fi

    # Check for required directories
    if [ ! -d "data/br-kg/cache" ]; then
        print_info "Creating data/br-kg/cache directory..."
        mkdir -p data/br-kg/cache
    else
        print_success "data/br-kg/cache directory present"
    fi

    # Check for config file
    if [ ! -f "configs/br-kg/data_config.json" ]; then
        print_warning "configs/br-kg/data_config.json not found. Using defaults."
    else
        print_success "Configuration file found"
    fi

    if [ -d "data/br-kg/raw/evidence" ]; then
        print_success "Evidence directory detected (data/br-kg/raw/evidence)"
    else
        print_warning "Evidence directory missing; on-demand adapters will fall back to API calls."
    fi

    # Check graph backend configuration
    if [ -n "$NEO4J_URI" ] && [ -n "$NEO4J_PASSWORD" ]; then
        print_success "Neo4j backend detected (NEO4J_URI set)"
    else
        print_error "Neo4j is required. Set NEO4J_URI/NEO4J_PASSWORD before running ingestion."
        exit 1
    fi
}

# Function to run quick test
run_quick_test() {
    print_info "Running quick test ingestion..."
    python3 launch_ingestion.py --config configs/br-kg/data_config.json --quick --report
    print_success "Quick test completed!"
}

# Function to run full ingestion
run_full_ingestion() {
    print_info "Running full data ingestion..."
    print_warning "This may take several hours depending on data sources"

    # Confirm with user
    read -p "Are you sure you want to proceed? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Ingestion cancelled"
        exit 0
    fi

    python3 launch_ingestion.py --config configs/br-kg/data_config.json --report
    print_success "Full ingestion completed!"
}

# Function to load only BrainMap
run_brainmap_only() {
    print_info "Loading BrainMap data..."
    python3 launch_ingestion.py --config configs/br-kg/data_config.json --sources brainmap --report
    print_success "BrainMap ingestion completed!"
}

# Function to load core sources
run_core_sources() {
    print_info "Loading core sources (Cognitive Atlas, Nilearn Atlases, Neurobagel)..."
    python3 launch_ingestion.py --config configs/br-kg/data_config.json --sources cognitive_atlas nilearn_atlases neurobagel --report
    print_success "Core sources loaded!"
}

run_on_demand_sources() {
    print_info "Registering on-demand evidence adapters (NeuroQuery, NiMARE, Neuroscout, Allen HBA)..."
    python3 launch_ingestion.py --config configs/br-kg/data_config.json --sources neuroquery nimare neuroscout allen_hba
    print_success "On-demand adapters registered!"
}

# Function to run with Docker
run_with_docker() {
    print_info "Starting Docker services..."

    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        print_error "Docker not found. Please install Docker first."
        exit 1
    fi

    # Check if docker-compose exists
    if [ ! -f "docker-compose.yml" ]; then
        print_error "docker-compose.yml not found"
        exit 1
    fi

    # Start services
    docker-compose up -d br-kg orchestrator redis

    print_info "Waiting for services to start..."
    sleep 10

    # Run ingestion
    python3 launch_ingestion.py --config configs/br-kg/data_config.json --docker --report

    print_success "Docker-based ingestion completed!"
    print_info "Services are still running. Use 'docker-compose down' to stop them."
}

# Function to run tests
run_tests() {
    print_info "Running tests..."

    # Test imports
    python3 -c "
from brain_researcher.core.ingestion.loaders.brainmap_unified import BrainMapUnifiedLoader
from brain_researcher.services.br_kg.etl.load_all import MasterDataLoader
print('✅ Imports successful')
"

    # Test BrainMap loader
    python3 -c "
from brain_researcher.core.ingestion.loaders.brainmap_unified import BrainMapUnifiedLoader
loader = BrainMapUnifiedLoader(use_api=False)
experiments = loader.load_experiments()
print(f'✅ BrainMap loader test: {len(experiments)} experiments loaded')
"

    # Run unit tests if pytest is available
    if command -v pytest &> /dev/null; then
        print_info "Running unit tests..."
        pytest tests/unit/ingestion/test_brainmap_loader.py -v
    fi

    print_info "Verifying on-demand adapter registration..."
    python3 launch_ingestion.py --config configs/br-kg/data_config.json --sources neuroquery nimare neuroscout allen_hba >/dev/null
    print_success "On-demand adapters respond"

    print_success "All tests passed!"
}

# Function to clean temporary files
clean_temp_files() {
    print_info "Cleaning temporary files..."

    # Remove cache directories
    rm -rf /tmp/brainmap_cache
    rm -rf data/*/cache

    # Remove log files
    rm -f *.log

    # Remove __pycache__
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

    print_success "Cleanup completed!"
}

# Main script logic
main() {
    case "${1:-help}" in
        quick)
            check_environment
            run_quick_test
            ;;
        full)
            check_environment
            run_full_ingestion
            ;;
        brainmap)
            check_environment
            run_brainmap_only
            ;;
        core)
            check_environment
            run_core_sources
            ;;
        ondemand)
            check_environment
            run_on_demand_sources
            ;;
        docker)
            check_environment
            run_with_docker
            ;;
        test)
            check_environment
            run_tests
            ;;
        clean)
            clean_temp_files
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
