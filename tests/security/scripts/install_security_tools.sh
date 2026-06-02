#!/bin/bash
"""
Install security testing tools for Brain Researcher.

This script installs all required security testing dependencies.
"""

set -e

echo "Installing Security Testing Tools for Brain Researcher..."
echo "========================================================="

# Update pip
echo "📦 Updating pip..."
python -m pip install --upgrade pip

# Install SAST tools
echo "🔍 Installing SAST tools..."
pip install bandit[toml]>=1.7.0
pip install safety>=2.0.0
pip install semgrep>=1.0.0

# Install additional security tools
echo "🛡️  Installing additional security tools..."
pip install pip-audit>=2.0.0
pip install detect-secrets>=1.4.0

# Install pre-commit if not already installed
echo "🪝 Installing pre-commit..."
pip install pre-commit>=3.0.0

# Install pytest plugins for security testing
echo "🧪 Installing pytest security plugins..."
pip install pytest-security>=0.1.0
pip install pytest-json-report>=1.5.0
pip install pytest-timeout>=2.1.0

# Verify installations
echo ""
echo "✅ Verifying installations..."
echo "--------------------------------"

echo -n "Bandit: "
bandit --version 2>/dev/null || echo "❌ Not installed"

echo -n "Safety: "
safety --version 2>/dev/null || echo "❌ Not installed"

echo -n "Semgrep: "
semgrep --version 2>/dev/null || echo "❌ Not installed"

echo -n "Pre-commit: "
pre-commit --version 2>/dev/null || echo "❌ Not installed"

echo -n "Pip-audit: "
pip-audit --version 2>/dev/null || echo "❌ Not installed"

echo ""
echo "🎉 Security tools installation completed!"
echo ""
echo "Next steps:"
echo "1. Run validation: python tests/security/scripts/validate_setup.py"
echo "2. Run security scan: python tests/security/scripts/run_security_scan.py"
echo "3. Install pre-commit hooks: pre-commit install"