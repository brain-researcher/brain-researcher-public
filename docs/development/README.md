# Development Documentation

This directory contains guides and documentation for developers working on the Brain Researcher project.

## Contents

- [Code Quality Guide](code_quality_guide.md) - Pre-commit hooks, linting, and code standards
- Additional development guides will be added here

## Quick Links

### Setup
1. Clone the repository
2. Install dependencies: `pip install -e ".[dev]"`
3. Set up pre-commit: `./scripts/dev/setup_precommit.sh`

### Development Workflow
1. Create a feature branch
2. Make changes
3. Run tests: `pytest`
4. Check code quality: `pre-commit run --all-files`
5. Commit changes (pre-commit runs automatically)
6. Push and create PR

### Tools
- **Ruff**: Linting and formatting
- **Mypy**: Type checking
- **Pytest**: Testing
- **Pre-commit**: Git hooks
- **Bandit**: Security scanning
