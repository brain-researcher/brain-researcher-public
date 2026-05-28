# Code Quality Guide

This guide explains the code quality tools and standards used in the Brain Researcher project.

## Overview

We use pre-commit hooks to automatically enforce code quality standards:
- **Ruff**: Fast Python linter and formatter (replaces flake8, black, isort)
- **Mypy**: Static type checking
- **Bandit**: Security vulnerability scanning
- **Pre-commit hooks**: File formatting and validation

## Setup

### Quick Setup

```bash
# Run the setup script
./scripts/dev/setup_precommit.sh
```

### Manual Setup

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install
pre-commit install --hook-type commit-msg

# Run on all files
pre-commit run --all-files
```

## Tools Configuration

### Ruff (Linting & Formatting)

Ruff is configured in `pyproject.toml`:
- Line length: 88 characters
- Python version: 3.10+
- Includes: pycodestyle, pyflakes, isort, bugbear
- Auto-fixes: import sorting, simple code issues

### Mypy (Type Checking)

Type checking configuration:
- Ignores missing imports
- Warns on redundant casts
- Excludes test files

### Bandit (Security)

Security scanning:
- Low severity threshold
- Excludes test files
- Checks for common vulnerabilities

## Usage

### Automatic Checks

Pre-commit runs automatically when you commit:

```bash
git add file.py
git commit -m "Add new feature"
# Pre-commit runs here
```

### Manual Checks

Run checks manually:

```bash
# Check all files
pre-commit run --all-files

# Check specific files
pre-commit run --files file1.py file2.py

# Run specific hook
pre-commit run ruff --all-files
pre-commit run mypy --all-files
```

### Bypassing Checks

In rare cases where you need to bypass:

```bash
git commit --no-verify -m "Emergency fix"
```

**Note**: Use sparingly and fix issues in next commit.

## Common Issues and Fixes

### Ruff Errors

```bash
# Auto-fix most issues
ruff check --fix .

# Format code
ruff format .
```

### Type Errors

```python
# Add type hints
def process_data(values: List[float]) -> float:
    return sum(values) / len(values)

# Ignore specific line
result = external_function()  # type: ignore
```

### Import Order

Ruff automatically fixes import order:
1. Standard library
2. Third-party packages
3. Local imports

### Line Length

Keep lines under 88 characters:

```python
# Bad
very_long_function_name_with_many_parameters(parameter1, parameter2, parameter3, parameter4)

# Good
very_long_function_name_with_many_parameters(
    parameter1, parameter2, parameter3, parameter4
)
```

## IDE Integration

### VS Code

Install extensions:
- Python
- Ruff
- Mypy

Settings (`settings.json`):
```json
{
    "python.linting.enabled": true,
    "python.linting.ruffEnabled": true,
    "python.formatting.provider": "ruff",
    "editor.formatOnSave": true
}
```

### PyCharm

1. File → Settings → Tools → File Watchers
2. Add Ruff watcher
3. Enable format on save

## Continuous Integration

Pre-commit runs in CI to ensure code quality:
- GitHub Actions automatically runs checks
- PRs must pass all checks
- Auto-fixes are applied when possible

## Best Practices

1. **Run before pushing**: `pre-commit run --all-files`
2. **Keep hooks updated**: `pre-commit autoupdate`
3. **Fix immediately**: Don't accumulate lint errors
4. **Add type hints**: Especially for public functions
5. **Document complex code**: Comments for non-obvious logic

## Disabling Checks

When necessary, disable specific checks:

```python
# Disable for entire file
# ruff: noqa

# Disable specific rule
# ruff: noqa: E501

# Disable for one line
long_line = "very long string"  # noqa: E501

# Type checking
from typing import Any  # type: ignore
```

## Additional Tools

### Running without pre-commit

```bash
# Ruff
ruff check .
ruff format .

# Mypy
mypy brain_researcher

# Bandit
bandit -r brain_researcher
```

### Useful Commands

```bash
# Update all hooks
pre-commit autoupdate

# Clean cache
pre-commit clean

# Uninstall hooks
pre-commit uninstall
```
