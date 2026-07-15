#!/usr/bin/env bash
# Documentation management script

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if MkDocs is installed
check_mkdocs() {
    if ! command -v mkdocs &> /dev/null; then
        print_error "MkDocs is not installed!"
        echo "Install with: python -m pip install -e '.[docs,dev]'"
        exit 1
    fi
}

# Function to install documentation dependencies
install_deps() {
    print_status "Installing documentation dependencies..."
    cd "$PROJECT_ROOT"
    python -m pip install -e ".[docs,dev]"
    print_status "Dependencies installed successfully!"
}

# Build both supported configurations strictly and never write a tracked or
# persistent site/ directory. Failed output is retained under /tmp for review.
build_strict_variants() {
    check_mkdocs
    cd "$PROJECT_ROOT"

    local output_root
    output_root="$(mktemp -d "${TMPDIR:-/tmp}/brain-researcher-docs.XXXXXX")"
    print_status "Building full and simple documentation in $output_root"

    if ! mkdocs build --strict --clean -f mkdocs.yml -d "$output_root/full"; then
        print_error "Full documentation build failed; output retained at $output_root/full"
        return 1
    fi
    if ! mkdocs build --strict --clean -f mkdocs-simple.yml -d "$output_root/simple"; then
        print_error "Simple documentation build failed; output retained at $output_root/simple"
        return 1
    fi

    rm -rf "$output_root"
    print_status "Both strict documentation builds passed."
}

# Function to build documentation
build_docs() {
    check_mkdocs
    cd "$PROJECT_ROOT"
    print_status "Building the full documentation site strictly..."
    mkdocs build --strict --clean -f mkdocs.yml
    print_status "Documentation built at $PROJECT_ROOT/site/"
}

# Function to serve documentation locally
serve_docs() {
    check_mkdocs
    print_status "Starting documentation server..."
    print_status "Documentation will be available at http://localhost:8000"
    cd "$PROJECT_ROOT"
    mkdocs serve --dev-addr 0.0.0.0:8000
}

# Function to deploy documentation
deploy_docs() {
    check_mkdocs
    print_status "Deploying documentation..."
    cd "$PROJECT_ROOT"

    # Check if we're in a git repo
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        print_error "Not in a git repository!"
        exit 1
    fi

    # Deploy with mike for versioning
    if command -v mike &> /dev/null; then
        VERSION=$(python -c "import brain_researcher; print(brain_researcher.__version__)")
        print_status "Deploying version $VERSION..."
        mike deploy --push --update-aliases $VERSION latest
        mike set-default --push latest
    else
        print_warning "Mike not installed, deploying without versioning..."
        mkdocs gh-deploy --force
    fi

    print_status "Documentation deployed successfully!"
}

# Function to create a new documentation page
new_page() {
    local path="${1:-}"
    if [ -z "$path" ]; then
        print_error "Please provide a path for the new page"
        echo "Usage: $0 new path/to/page.md"
        exit 1
    fi

    local full_path="$PROJECT_ROOT/docs/$path"
    local dir=$(dirname "$full_path")

    # Create directory if it doesn't exist
    mkdir -p "$dir"

    # Create template
    cat > "$full_path" << EOF
# Page Title

Brief description of what this page covers.

## Overview

Introduce the topic here.

## Section 1

Content for section 1.

### Subsection 1.1

Detailed content.

## Section 2

Content for section 2.

## Examples

\`\`\`python
# Example code
import brain_researcher

# Your example here
\`\`\`

## See Also

- [Related Page 1](../path/to/page1.md)
- [Related Page 2](../path/to/page2.md)
EOF

    print_status "Created new documentation page: $path"
    print_status "Don't forget to add it to mkdocs.yml navigation!"
}

# Function to check documentation
check_docs() {
    check_mkdocs
    print_status "Checking documentation links, images, code paths, and navigation..."
    cd "$PROJECT_ROOT"
    python -m pytest -q \
        --confcutdir=tests/unit/config \
        -p no:cacheprovider \
        tests/unit/config/test_docs_integrity.py
    build_strict_variants
    print_status "Documentation integrity check passed!"
}

# Function to show usage
usage() {
    echo "Usage: $0 {install|build|serve|deploy|new|check|help}"
    echo ""
    echo "Commands:"
    echo "  install  - Install documentation dependencies"
    echo "  build    - Build documentation"
    echo "  serve    - Serve documentation locally (http://localhost:8000)"
    echo "  deploy   - Deploy documentation to GitHub Pages"
    echo "  new PATH - Create a new documentation page"
    echo "  check    - Check documentation for errors"
    echo "  help     - Show this help message"
}

# Main script logic
case "${1:-help}" in
    install)
        install_deps
        ;;
    build)
        build_docs
        ;;
    serve)
        serve_docs
        ;;
    deploy)
        deploy_docs
        ;;
    new)
        new_page "${2:-}"
        ;;
    check)
        check_docs
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        print_error "Invalid command: $1"
        usage
        exit 1
        ;;
esac
