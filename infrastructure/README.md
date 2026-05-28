# Brain Researcher Infrastructure

This directory contains the infrastructure and deployment assets for the Brain
Researcher platform, including the legacy multi-service web stack and the new
workspace-oriented architecture built around JupyterHub, Neurodesk, and BR MCP.

> **OSS preview boundary:** this directory mixes current production overlays,
> deployment skeletons, and legacy/experimental scaling assets. Check the
> current release-gate report before treating a component as deployed or
> production-ready.

## Overview

The infrastructure includes:

- **Production overlays**: k3s/GCE and GCP Helm values used for current hosted services
- **Workspace skeletons**: JupyterHub values and single-user image definitions
- **Legacy stack assets**: Docker Swarm, HAProxy, PgBouncer, monitoring, and scaling examples
- **Experimental autoscaling**: prototype autoscaler configuration and scripts

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Load Balancer │────│   API Gateway    │────│   Services      │
│   (HAProxy/     │    │   (Multiple      │    │   (Replicated   │
│   Ingress)      │    │   Instances)     │    │   Instances)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Monitoring    │    │   Auto-scaler    │    │   Database      │
│   (Prometheus   │    │   (Python        │    │   Connection    │
│   Grafana)      │    │   ML-based)      │    │   Pool (PgBouncer) │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Directory Structure

```
infrastructure/
├── jupyterhub/
│   ├── README.md                 # Hosted workspace deployment notes
│   └── values.mvp.yaml           # JupyterHub MVP values overlay
├── autoscaling/
│   ├── autoscaler.py              # Intelligent auto-scaling engine
│   └── autoscaler-config.json     # Service scaling configurations
├── database/
│   ├── pgbouncer.ini              # Connection pooling configuration
│   ├── userlist.txt               # Database user authentication
│   └── init.sql                   # Database initialization script
├── docker/
│   ├── Dockerfile.jupyter-singleuser  # JupyterLab single-user image skeleton
│   └── ...
├── deployment/
│   └── ...
├── haproxy/
│   └── haproxy.cfg                # Load balancer configuration
├── monitoring/
│   └── prometheus.yml             # Metrics collection configuration
├── deploy-load-balanced.sh        # Main deployment script
└── README.md                      # This file
```

## Workspace Architecture

The new product direction distinguishes between:

- **Hosted cloud**: `JupyterHub + JupyterLab + notebook assistant + BR MCP over HTTP`
- **Local Docker**: `coding agent + BR MCP over stdio / Docker stdio`
- **HPC**: `coding agent + BR MCP over stdio`, with heavy execution routed
  through Neurodesk and Slurm recipes

The hosted deployment skeleton lives under `infrastructure/jupyterhub/`. It is
intentionally separate from the existing `brain-researcher` Helm chart because
the workspace layer has a different lifecycle, auth surface, and storage model
from the core backend services.

## Quick Start

### Docker Swarm Deployment

```bash
# Deploy with default settings
./infrastructure/deploy-load-balanced.sh swarm dev

# Deploy for production
POSTGRES_PASSWORD=secure_password \
OPENAI_API_KEY=your_key \
./infrastructure/deploy-load-balanced.sh swarm prod
```

These commands are retained for legacy-stack testing. The current hosted
deployment path is documented by the overlays under
`infrastructure/deployment/gce_k3s/` and the release-gate reports in
`docs/release/`.

### Kubernetes Deployment

```bash
# Deploy to Kubernetes
./infrastructure/deploy-load-balanced.sh k8s dev

# Deploy with custom namespace
kubectl create namespace brain-researcher-prod
./infrastructure/deploy-load-balanced.sh k8s prod
```

## Components

### 1. Auto-scaling Engine (`autoscaling/autoscaler.py`)

Prototype features:
- CPU and memory-based scaling
- Custom application metrics integration
- Predictive scaling using machine learning
- Multi-service coordination
- Cost optimization

**Configuration:**
```json
{
  "services": [
    {
      "name": "orchestrator",
      "min_replicas": 3,
      "max_replicas": 12,
      "target_cpu_percent": 65,
      "enable_predictive": true
    }
  ]
}
```

**Usage:**
```bash
# Run continuous auto-scaling
python3 infrastructure/autoscaling/autoscaler.py \
  --platform=docker_swarm \
  --config=infrastructure/autoscaling/autoscaler-config.json

# Single scaling cycle
python3 infrastructure/autoscaling/autoscaler.py --once
```

### 2. Load Balancer (HAProxy)

**Features:**
- Multiple load balancing strategies (round-robin, least-connections, etc.)
- Health checks and automatic failover
- Session affinity and sticky sessions
- SSL termination and security headers
- Real-time statistics and monitoring

**Access Points:**
- Main application: `http://localhost`
- Statistics dashboard: `http://localhost:8080/stats`
- Admin interface: `http://localhost:8080/admin`

**Configuration highlights:**
```yaml
# Backend for Orchestrator service
backend orchestrator_backend:
  balance leastconn
  cookie ORCHESTRATOR insert indirect nocache secure httponly
  server orch-1 orchestrator:3001 check weight 100 maxconn 200
```

### 3. Database Connection Pooling (PgBouncer)

**Features:**
- Transaction-level connection pooling
- Multiple connection pools for different services
- Authentication and security
- Connection limits and timeouts
- Performance monitoring

**Configuration:**
```ini
[databases]
brain_researcher = host=postgres port=5432 pool_size=50
brain_researcher_readonly = host=postgres port=5432 pool_size=30

[pgbouncer]
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 50
```

### 4. Blue-Green Deployment

**Features:**
- Zero-downtime deployments
- Automatic health checks
- Gradual traffic switching
- Automatic rollback on failure
- Support for both Docker Swarm and Kubernetes

**Usage:**
```bash
# Deploy new version
./infrastructure/deployment/blue_green.sh deploy orchestrator --platform=swarm

# Rollback if needed
./infrastructure/deployment/blue_green.sh rollback orchestrator

# Check status
./infrastructure/deployment/blue_green.sh status orchestrator
```

### 5. Kubernetes HPA (Horizontal Pod Autoscaler)

**Features:**
- CPU and memory-based scaling
- Custom metrics support (Prometheus adapter required)
- Advanced scaling policies
- Service-specific configurations

**Custom Metrics Supported:**
- HTTP requests per second
- Queue depth from Redis
- Response time percentiles
- Database query rates
- WebSocket connections

## Service Scaling Configurations

| Service | Min Replicas | Max Replicas | CPU Target | Memory Target | Special Notes |
|---------|--------------|--------------|------------|---------------|---------------|
| Orchestrator | 3 | 12 | 65% | 70% | Queue-depth aware scaling |
| BR-KG | 2 | 8 | 70% | 75% | Read-heavy optimization |
| Agent | 2 | 6 | 80% | 85% | Conservative scaling (expensive) |
| Web UI | 2 | 8 | 70% | 80% | Fast scaling for user traffic |
| API Gateway | 2 | 6 | 70% | 75% | Connection-aware scaling |

## Monitoring and Metrics

### Prometheus Metrics Collected

**System Metrics:**
- CPU usage and load average
- Memory utilization
- Disk I/O and network traffic
- Connection pool statistics

**Application Metrics:**
- Request rates and latencies
- Queue depths and processing times
- Database query performance
- LLM inference times and token counts

**Auto-scaling Metrics:**
- Scaling decisions and confidence scores
- Resource utilization trends
- Predictive scaling accuracy

### Grafana Dashboards

Access Grafana at `http://localhost:3000/grafana`

**Available Dashboards:**
- System Overview
- Service Performance
- Load Balancer Statistics
- Database Connections
- Auto-scaling Activity

## Production Deployment

### Environment Variables

Required environment variables for production:

```bash
# Database
POSTGRES_PASSWORD=your_secure_password
POSTGRES_USER=postgres

# API Keys
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
DEEPSEEK_API_KEY=your_deepseek_key

# Security
GRAFANA_ADMIN_PASSWORD=secure_grafana_password
REDIS_PASSWORD=secure_redis_password

# URLs (for external services)
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_key
```

### SSL/TLS Configuration

For production, configure SSL certificates:

1. **Docker Swarm**: Place certificates in `infrastructure/haproxy/ssl/`
2. **Kubernetes**: Use cert-manager for automatic certificate management

### Database Security

1. Change default passwords in `infrastructure/database/userlist.txt`
2. Generate proper password hashes:
   ```bash
   echo -n "your_password_username" | md5sum
   ```
3. Use different passwords for each environment

### Backup Configuration

Set up automated backups for:
- PostgreSQL databases
- Redis data
- Application configurations
- Monitoring data

## Troubleshooting

### Common Issues

**Services not scaling:**
```bash
# Check auto-scaler logs
docker service logs brain-researcher_autoscaler

# Verify metrics collection
curl http://localhost:9090/api/v1/query?query=up
```

**Load balancer not distributing traffic:**
```bash
# Check HAProxy stats
curl http://localhost:8080/stats

# Verify backend health
./infrastructure/deployment/blue_green.sh status all
```

**Database connection issues:**
```bash
# Check PgBouncer status
docker exec -it brain-researcher_pgbouncer_1 psql -p 6432 -U postgres -c "SHOW POOLS;"

# Monitor connection counts
docker exec -it brain-researcher_pgbouncer_1 psql -p 6432 -U postgres -c "SHOW CLIENTS;"
```

### Health Checks

```bash
# Run comprehensive health checks
./infrastructure/deploy-load-balanced.sh health-check

# Check service status
./infrastructure/deploy-load-balanced.sh status

# Individual service health
curl http://localhost/health
curl http://localhost/api/health
curl http://localhost/orchestrator/health
```

## Performance Tuning

### Auto-scaling Tuning

Adjust scaling parameters in `autoscaler-config.json`:

```json
{
  "services": [{
    "name": "orchestrator",
    "scale_up_threshold": 80,        # Increase for less aggressive scaling
    "scale_down_threshold": 30,      # Decrease for more conservative scaling
    "cooldown_minutes": 5,           # Increase to prevent flapping
    "enable_predictive": true        # Enable ML-based predictions
  }]
}
```

### Database Connection Pooling

Tune PgBouncer parameters in `pgbouncer.ini`:

```ini
default_pool_size = 50              # Increase for high-concurrency workloads
max_client_conn = 1000              # Adjust based on expected connections
query_timeout = 300                 # Increase for long-running queries
```

### Load Balancer Optimization

Modify HAProxy configuration for specific workloads:

```yaml
# For CPU-intensive services
balance leastconn

# For stateful services
balance source

# For high-throughput services
balance roundrobin
```

## Migration Guide

### From Single Instance to Load Balanced

1. **Backup existing data:**
   ```bash
   docker exec postgres pg_dump brain_researcher > backup.sql
   ```

2. **Deploy load balanced infrastructure:**
   ```bash
   ./infrastructure/deploy-load-balanced.sh swarm prod
   ```

3. **Migrate data:**
   ```bash
   docker exec -i new_postgres psql brain_researcher < backup.sql
   ```

4. **Update application configuration:**
   - Point applications to load balancer endpoints
   - Update database connections to use PgBouncer

### From Docker Compose to Swarm

1. **Initialize Docker Swarm:**
   ```bash
   docker swarm init
   ```

2. **Deploy using Swarm configuration:**
   ```bash
   docker stack deploy -c docker-compose.swarm.yml brain-researcher
   ```

3. **Verify services are running:**
   ```bash
   docker stack services brain-researcher
   ```

## Contributing

When contributing to the infrastructure:

1. **Test changes** in development environment first
2. **Update configuration** files and documentation
3. **Add monitoring** for new metrics or services
4. **Follow security** best practices for production deployments

## Support

For infrastructure-related issues:

1. Check the troubleshooting section above
2. Review service logs: `docker service logs <service_name>`
3. Monitor system metrics in Grafana
4. Consult the auto-scaler logs for scaling decisions

## License

This infrastructure configuration is part of the Brain Researcher project and follows the same licensing terms.
