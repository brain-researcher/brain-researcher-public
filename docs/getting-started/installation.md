# Installation

This guide will help you install Brain Researcher and its dependencies.

If you opened this file from an exported analysis bundle, the recommended
install entrypoint is:

1. `.bundle_support/docker-compose.yml`
2. `.bundle_support/.env.example`
3. `.bundle_support/quickstart.md`

Use `.bundle_support/environment.yml` only if Docker is not available in your
environment.

## Prerequisites

- Python 3.10 or higher
- Git
- (Optional) Docker and Docker Compose for containerized deployment

## Installation Methods

### 1. Development Installation (Recommended)

Clone the repository and install in development mode:

```bash
# Clone the repository
git clone https://github.com/zjc062/brain_researcher.git
cd brain_researcher

# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install with all dependencies
pip install -e ".[all]"
```

### 2. Minimal Installation

For a minimal installation with only core features:

```bash
pip install -e .
```

### 3. Feature-Specific Installation

Install only the components you need:

```bash
# Knowledge Graph features (Neo4j-backed)
pip install -e ".[neurokg]"

# LLM Agent features
pip install -e ".[agent]"

# Web UI (Gradio helper components)
pip install -e ".[ui]"

# Documentation building
pip install -e ".[docs]"
```

### 4. Docker Installation

Use Docker for a fully containerized setup:

```bash
# Build and start all services
docker compose up -d
```

## Environment Setup

### API Keys

Set up required API keys:

```bash
# Create .env file
cp .env.example .env

# Edit .env and add your keys
export DEEPSEEK_API_KEY="your-api-key"
export OPENAI_API_KEY="your-openai-key"  # Optional
```

### Database Initialization

Initialize the BR-KG database:

```bash
# Initialize database
brain-researcher db init

# Verify installation
brain-researcher db status
```

### Data Management

Set up Git LFS for large files:

```bash
# Install Git LFS
git lfs install

# Pull data files
git lfs pull

# Check data status
python scripts/data/download_data.py check
```

## Verification

Verify your installation:

```bash
# Check CLI is installed
brain-researcher --help

# Check version
brain-researcher version

# Run tests
pytest
```

## Platform-Specific Notes

### macOS

If you encounter issues with scientific packages:

```bash
# Install using conda/mamba
conda install -c conda-forge nilearn nibabel
```

### Windows

Use WSL2 for best compatibility:

```bash
# In WSL2 terminal
sudo apt update
sudo apt install python3-pip python3-venv
```

### Linux

Install system dependencies:

```bash
# Ubuntu/Debian
sudo apt install python3-dev build-essential

# Fedora/RHEL
sudo dnf install python3-devel gcc
```

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure you've installed with `pip install -e .`
2. **Database connection**: Check if BR-KG service is running on port 5000
3. **Memory issues**: Some neuroimaging operations require significant RAM

### Getting Help

- Read the repository [README](../../README.md)
- Report issues on [GitHub](https://github.com/zjc062/brain_researcher/issues)
- Follow private vulnerability reporting in [SECURITY.md](../../SECURITY.md)

## Next Steps

- Follow the [Quick Start Guide](quickstart.md)
- Learn about [Configuration](configuration.md)
- Explore the [CLI Usage](../user-guide/cli.md)
