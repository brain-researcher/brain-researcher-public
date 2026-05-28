# Docker Guide

This guide explains how to use Docker with the Brain Researcher project.

## Overview

The Brain Researcher project uses a unified multi-stage Dockerfile that can build different images:
- **neurokg**: BR-KG API service (Neo4j-backed)
- **agent**: LangGraph agent service
- **web-ui**: Next.js Web UI
- **development**: Full development environment
- **cli**: Command-line interface

## Quick Start

### Running All Services

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Service URLs

- BR-KG API: http://localhost:5000
- Agent API: http://localhost:8000
- Web UI (Next.js): http://localhost:3000
- Redis: localhost:6379

## Development Usage

### Development Container

```bash
# Start development container
docker-compose -f docker-compose.dev.yml up dev

# In another terminal, execute commands in the container
docker exec -it brain-researcher-dev bash

# Run Jupyter Lab
docker exec -it brain-researcher-dev jupyter lab --ip=0.0.0.0 --allow-root
```

### Running CLI Commands

```bash
# Build CLI image
docker-compose -f docker-compose.dev.yml build cli

# Run CLI commands
docker-compose -f docker-compose.dev.yml run --rm cli db status
docker-compose -f docker-compose.dev.yml run --rm cli query search "motor cortex"
```

### Development Services

```bash
# Start only development services
docker-compose -f docker-compose.dev.yml --profile services up
```

## Building Images

### Build Specific Target

```bash
# Build BR-KG service
docker build --target neurokg -t brain-researcher-neurokg .

# Build Agent service
docker build --target agent -t brain-researcher-agent .

# Build UI service
docker build --target ui -t brain-researcher-ui .

# Build development image
docker build --target development -t brain-researcher-dev .
```

### Build All Services

```bash
docker-compose build
```

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# API Keys
OPENAI_API_KEY=your-key-here
ANTHROPIC_API_KEY=your-key-here
DEEPSEEK_API_KEY=your-key-here

# Service Configuration
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=change-me
NEUROKG_API_URL=http://neurokg:5000

# Development
FLASK_ENV=development
DASH_DEBUG=true
```

### Volume Mounts

The docker-compose files mount these directories:
- `./data:/app/data` - Data files and databases
- `./logs:/app/logs` - Application logs
- `.:/app` - Full source code (development only)

After starting the `neo4j` service, seed it with the bundled mini dump:

```bash
scripts/tools/dev/seed_from_dump.sh tests/fixtures/neurokg/mini_dump
```

## Deployment

### Production Build

```bash
# Build production images
docker-compose build --no-cache

# Start with production settings
docker-compose up -d

# Scale services
docker-compose up -d --scale agent=3
```

### Health Checks

All services include health checks:

```bash
# Check service health
docker-compose ps

# Manual health check
curl http://localhost:5000/health
curl http://localhost:8000/health
```

## Troubleshooting

### Common Issues

1. **Port conflicts**
   ```bash
# Check what's using the port
lsof -i :5000

# Use different ports
NEUROKG_PORT=5002 docker-compose up
   ```

2. **Permission issues**
   ```bash
   # Fix data directory permissions
   sudo chown -R $USER:$USER data/
   ```

3. **Out of memory**
   ```bash
   # Increase Docker memory limit
   # Docker Desktop: Preferences > Resources
   ```

### Debugging

```bash
# View container logs
docker-compose logs neurokg
docker-compose logs -f agent

# Execute commands in container
docker-compose exec neurokg bash
docker-compose exec agent python -c "import brain_researcher; print(brain_researcher.__version__)"

# Inspect container
docker inspect brain-researcher-neurokg
```

### Cleanup

```bash
# Remove containers and networks
docker-compose down

# Remove volumes as well
docker-compose down -v

# Remove all Brain Researcher images
docker images | grep brain-researcher | awk '{print $3}' | xargs docker rmi

# Full cleanup
docker system prune -a
```

## Advanced Usage

### Custom Builds

```dockerfile
# Build with specific Python version
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim AS base
```

### Multi-platform Builds

```bash
# Build for multiple platforms
docker buildx build --platform linux/amd64,linux/arm64 -t brain-researcher:latest .
```

### Using Docker Registry

```bash
# Tag and push to registry
docker tag brain-researcher-neurokg:latest myregistry.com/brain-researcher/neurokg:latest
docker push myregistry.com/brain-researcher/neurokg:latest

# Update docker-compose.yml
services:
  neurokg:
    image: myregistry.com/brain-researcher/neurokg:latest
```

## Best Practices

1. **Use specific tags** for production
2. **Mount data directories** as volumes
3. **Set resource limits** in production
4. **Use health checks** for monitoring
5. **Keep images small** with multi-stage builds
6. **Use .dockerignore** to exclude unnecessary files
7. **Run as non-root user** in production
