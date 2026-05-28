#!/bin/bash
# Development setup script for Brain Researcher

echo "Setting up Brain Researcher development environment..."

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Export PYTHONPATH to include the project root
export PYTHONPATH="${PYTHONPATH}:${SCRIPT_DIR}"

echo "PYTHONPATH set to: $PYTHONPATH"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install the package in development mode
echo "Installing Brain Researcher in development mode..."
pip install -e ".[dev]"

echo ""
echo "Setup complete! You can now:"
echo "  - Run the CLI: brain-researcher"
echo "  - Start BR-KG: br serve kg --host 0.0.0.0 --port 5000"
echo "  - Start the full local stack: ./scripts/dev/dev-services.sh"
echo "  - Run tests: pytest"
echo ""
