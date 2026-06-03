# Brain Researcher Production Deployment Guide

This guide provides comprehensive instructions for deploying Brain Researcher in a production environment.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Deployment Methods](#deployment-methods)
- [Monitoring & Health Checks](#monitoring--health-checks)
- [Backup & Recovery](#backup--recovery)
- [Troubleshooting](#troubleshooting)
- [Security Considerations](#security-considerations)

## Architecture Overview

Brain Researcher follows a microservices architecture with the following components:

```
┌─────────────────┐
│   Nginx         │
│   (Ports 80/443)│
└─────────────────┘
          │
          ├──────────────▶ Orchestrator (3001)
          ├──────────────▶ Agent Service (8000)
          ├──────────────▶ BR-KG API (5000)
          └──────────────▶ Web UI (3000)

Agent Service ───────────▶ Redis (6379)
BR-KG API ─────────────▶ Neo4j (7474 / 7687)
```

## Prerequisites

### System Requirements

- **OS**: Linux (Ubuntu 20.04+ or CentOS 8+)
- **RAM**: Minimum 8GB, Recommended 16GB+
- **CPU**: Minimum 4 cores, Recommended 8+ cores
- **Storage**: Minimum 50GB free space, Recommended 100GB+ (SSD preferred)
- **Network**: Reliable internet connection for AI model APIs

### Required Software

1. **Docker & Docker Compose**
   ```bash
   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh

   # Install Docker Compose
   sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
   sudo chmod +x /usr/local/bin/docker-compose
   ```

2. **Git LFS** (for large model files)
   ```bash
   sudo apt-get install git-lfs  # Ubuntu/Debian
   # or
   sudo yum install git-lfs      # CentOS/RHEL
   ```

3. **Basic utilities**
   ```bash
   sudo apt-get install curl jq htop
   ```

### API Keys Required

- **OpenAI API Key** (required for LLM functionality)
- **Anthropic API Key** (optional, for Claude models)
- **DeepSeek API Key** (optional, for alternative models)

## Quick Start

### 1. Clone Repository
```bash
git clone https://github.com/your-org/brain-researcher.git
cd brain-researcher
git lfs pull  # Download large files
```

### 2. Configure Environment
```bash
# Copy and customize environment variables
cp .env.example .env
nano .env  # Edit with your configuration
```

### 3. Deploy with Script
```bash
# Production deployment
./scripts/deployment/deploy.sh --backup --environment production

# Or step by step
./scripts/deployment/deploy.sh --help
```

### 4. Verify Deployment
```bash
# Check service health
./scripts/deployment/health_check.sh

# View service status
docker-compose -f docker-compose.prod.yml ps
```

## Configuration

### Environment Variables

Key configuration variables in `.env`:

```bash
# === Required ===
OPENAI_API_KEY=your_openai_api_key_here
JWT_SECRET=your_secure_jwt_secret_32_chars_min

# === Database ===
POSTGRES_PASSWORD=secure_password
REDIS_PASSWORD=secure_redis_password

# === Domain (Production) ===
DOMAIN=yourdomain.com
SSL_EMAIL=admin@yourdomain.com
CORS_ORIGINS=https://yourdomain.com

# === Performance ===
BR_KG_MEMORY_LIMIT=3g
AGENT_MEMORY_LIMIT=4g
WEB_CONCURRENCY=4
```

### Service Configuration

#### Nginx Routing (Production Compose)
Edit `infrastructure/nginx/brain-researcher-compose.conf` for:
- SSL/TLS certificates
- Domain configuration
- Load balancing
- Security headers

Current `docker-compose.prod.yml` mounts this file directly; it does not run a
separate `api-gateway` container.

#### Historical Standalone API Gateway
No standalone API Gateway config or Docker image is shipped in the public tree.
The current production path is Nginx plus split services. The legacy Python
package remains importable for compatibility experiments, but those experiments
must provide their own local config outside the release archive.

## Deployment Methods

### Method 1: Automated Script (Recommended)

```bash
# Full production deployment with backup
./scripts/deployment/deploy.sh \
  --backup \
  --environment production \
  --compose-file docker-compose.prod.yml

# Staging deployment
./scripts/deployment/deploy.sh \
  --environment staging \
  --compose-file docker-compose.yml
```

### Method 2: Manual Docker Compose

```bash
# Start production stack
docker-compose -f docker-compose.prod.yml up -d

# Check logs
docker-compose -f docker-compose.prod.yml logs -f

# Stop stack
docker-compose -f docker-compose.prod.yml down
```

### Method 3: CI/CD Pipeline

The included GitHub Actions workflow (`.github/workflows/ci.yml`) provides:
- Automated testing
- Docker image building
- Security scanning
- Automated deployment to staging/production

## Monitoring & Health Checks

### Health Check Script

```bash
# Check all services once
./scripts/deployment/health_check.sh

# Continuous monitoring
./scripts/deployment/health_check.sh --continuous --interval 30

# JSON output for monitoring systems
./scripts/deployment/health_check.sh --json
```

### Monitoring Stack

Current `docker-compose.prod.yml` exposes service health endpoints, but it does
not bundle Prometheus or Grafana by default.

Health endpoints:
- Nginx ingress: http://localhost/health
- Orchestrator: http://localhost:3001/health
- Agent: http://localhost:8000/health
- BR-KG: http://localhost:5000/health
- Web UI: http://localhost:3000/api/health

### Key Metrics to Monitor

- Request latency and throughput
- Error rates per service
- Memory and CPU usage
- Database connection pool status
- Queue depths and processing times

## Backup & Recovery

### Automated Backups

The deployment script creates backups of:
- BR-KG database
- Configuration files
- Environment settings
- Docker Compose configurations

```bash
# Create manual backup
./scripts/deployment/deploy.sh --backup

# List available backups
./scripts/deployment/rollback.sh --list

# Restore from backup
./scripts/deployment/rollback.sh --backup /path/to/backup.tar.gz
```

### Backup Strategy

- **Frequency**: Daily automated backups
- **Retention**: 30 days (configurable)
- **Location**: `/var/backups/brain-researcher/`
- **Format**: Compressed tar archives with metadata

## Rollback Procedures

### Automatic Rollback

Failed deployments automatically trigger rollback:

```bash
# Manual rollback to latest backup
./scripts/deployment/rollback.sh

# Rollback to specific backup
./scripts/deployment/rollback.sh --backup backup_20240101_120000.tar.gz

# Dry run (preview changes)
./scripts/deployment/rollback.sh --dry-run
```

### Emergency Procedures

1. **Service Down**: Restart individual services
   ```bash
   docker-compose -f docker-compose.prod.yml restart service-name
   ```

2. **Database Issues**: Restore from backup
   ```bash
   ./scripts/deployment/rollback.sh --force
   ```

3. **Complete System Failure**: Full rollback
   ```bash
   ./scripts/deployment/rollback.sh --force --skip-health
   ```

## SSL/TLS Configuration

### Let's Encrypt (Recommended)

```bash
# Install certbot
sudo apt-get install certbot

# Get certificates
sudo certbot certonly --standalone -d yourdomain.com

# Update infrastructure/nginx/brain-researcher-compose.conf with certificate paths
# Restart nginx
docker-compose -f docker-compose.prod.yml restart nginx
```

### Custom Certificates

1. Place certificates in `ssl/` directory:
   ```
   ssl/
   ├── brain-researcher.crt
   ├── brain-researcher.key
   └── ca-bundle.crt
   ```

2. Update `infrastructure/nginx/brain-researcher-compose.conf` with correct paths
3. Restart services

## Troubleshooting

### Common Issues

#### Services Won't Start

1. Check Docker daemon:
   ```bash
   sudo systemctl status docker
   ```

2. Check ports availability:
   ```bash
   sudo netstat -tlnp | grep -E ':(80|443|3000|3001|5000|6379|7474|7687|8000)'
   ```

3. Check logs:
   ```bash
   docker-compose -f docker-compose.prod.yml logs service-name
   ```

#### Database Connection Issues

1. Check Neo4j data and the optional GLM FitLins SQLite cache:
   ```bash
   ls -la data/neo4j/
   ls -la data/br-kg/db/
   ```

2. Test database connectivity:
   ```bash
   docker-compose -f docker-compose.prod.yml exec neo4j \
     cypher-shell -a bolt://localhost:7687 -u neo4j -p "$NEO4J_PASSWORD" 'RETURN 1'
   ```

#### Performance Issues

1. Check resource usage:
   ```bash
   docker stats
   htop
   ```

2. Check disk space:
   ```bash
   df -h
   ```

3. Check service health and ingress routing:
   ```bash
   curl http://localhost/health
   curl http://localhost:3001/health
   curl http://localhost:8000/health
   curl http://localhost:5000/health
   ```

### Log Files

- **Deployment**: `/var/log/brain-researcher/deploy_*.log`
- **Health Checks**: `/var/log/brain-researcher/health_check.log`
- **Services**: Access via `docker-compose logs`

### Getting Help

1. Check the logs first
2. Run health checks to identify failing services
3. Review configuration files for errors
4. Check GitHub issues for similar problems

## Security Considerations

### Production Security Checklist

- [ ] Change all default passwords
- [ ] Configure firewall rules
- [ ] Enable SSL/TLS encryption
- [ ] Set up proper CORS origins
- [ ] Configure rate limiting
- [ ] Enable security headers in Nginx
- [ ] Regularly update Docker images
- [ ] Monitor security logs
- [ ] Backup encryption
- [ ] Network segmentation

### Firewall Configuration

```bash
# Allow essential ports
sudo ufw allow 22     # SSH
sudo ufw allow 80     # HTTP
sudo ufw allow 443    # HTTPS
sudo ufw enable
```

### Regular Maintenance

- Update Docker images monthly
- Review and rotate API keys quarterly
- Monitor security advisories
- Test backup/restore procedures
- Review access logs weekly

## Performance Tuning

### Resource Optimization

1. **Memory Settings**
   ```bash
   # In .env file
   BR_KG_MEMORY_LIMIT=4g    # Increase for large datasets
   AGENT_MEMORY_LIMIT=6g      # Increase for complex models
   ```

2. **CPU Optimization**
   ```bash
   WEB_CONCURRENCY=8          # Match CPU cores
   GUNICORN_WORKERS=4         # CPU cores / 2
   ```

3. **Database Tuning**
   - Enable WAL mode for SQLite
   - Configure Redis memory policy
   - Optimize query patterns

### Scaling Considerations

- **Horizontal Scaling**: Use Docker Swarm or Kubernetes
- **Load Balancing**: Configure multiple instances behind Nginx
- **Database Scaling**: Consider PostgreSQL for large deployments
- **Caching**: Implement Redis caching strategies

---

For additional support, please refer to the project documentation or open an issue on GitHub.
