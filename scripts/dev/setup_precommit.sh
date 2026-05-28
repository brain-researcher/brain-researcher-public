#!/bin/bash
# Setup pre-commit hooks for the project

echo "Setting up pre-commit hooks..."

# Install pre-commit if not already installed
if ! command -v pre-commit &> /dev/null; then
    echo "Installing pre-commit..."
    pip install pre-commit
fi

# Install the pre-commit hooks
echo "Installing pre-commit hooks..."
pre-commit install

# Install commit-msg hook for commit message linting
pre-commit install --hook-type commit-msg

# Run pre-commit on all files to check current status
echo "Running pre-commit on all files (this may take a moment)..."
pre-commit run --all-files || true

echo "Pre-commit setup complete!"
echo ""
echo "Pre-commit will now run automatically on staged files before each commit."
echo "To run manually: pre-commit run --all-files"
echo "To update hooks: pre-commit autoupdate"
