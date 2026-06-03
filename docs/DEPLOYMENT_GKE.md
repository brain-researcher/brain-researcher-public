# Brain Researcher - GKE Deployment Guide

This guide covers deploying Brain Researcher to Google Kubernetes Engine (GKE).

## Prerequisites

1. **Google Cloud SDK** installed and configured (`gcloud auth login`)
2. **kubectl** configured for your cluster
3. **Helm 3.x** installed
4. **Docker images** built and pushed to GCR/Artifact Registry

## Quick Start

### 1. Create GKE Cluster

```bash
# Create a standard cluster with autoscaling
gcloud container clusters create brain-researcher \
  --zone us-central1-a \
  --num-nodes 3 \
  --machine-type e2-standard-4 \
  --enable-autoscaling --min-nodes 2 --max-nodes 10 \
  --enable-network-policy \
  --workload-pool=YOUR_PROJECT_ID.svc.id.goog

# For GPU workloads (NICLIP, heavy inference)
gcloud container node-pools create gpu-pool \
  --cluster brain-researcher \
  --zone us-central1-a \
  --machine-type n1-standard-8 \
  --accelerator type=nvidia-tesla-t4,count=1 \
  --num-nodes 1 \
  --enable-autoscaling --min-nodes 0 --max-nodes 3
```

### 2. Configure kubectl

```bash
gcloud container clusters get-credentials brain-researcher --zone us-central1-a
```

### 3. Create Namespaces

```bash
kubectl create namespace brain-researcher-core
kubectl create namespace brain-researcher-data
kubectl create namespace brain-researcher-monitoring
```

### 4. Create Secrets

```bash
# Copy and configure deployment.env
cp deployment.env.example deployment.env
# Edit deployment.env with your values

# Create secret from env file
kubectl create secret generic brain-researcher-secrets \
  --from-env-file=deployment.env \
  -n brain-researcher-core

# Copy secrets to other namespaces if needed
kubectl get secret brain-researcher-secrets -n brain-researcher-core -o yaml | \
  sed 's/namespace: brain-researcher-core/namespace: brain-researcher-data/' | \
  kubectl apply -f -
```

### 5. Deploy with Helm

```bash
# Install/upgrade using the active GKE production overlay
helm upgrade --install brain-researcher infrastructure/k8s/helm/brain-researcher \
  -f infrastructure/deployment/gcp/values.prod.yaml \
  -n brain-researcher-core \
  --set global.domain=your-domain.com \
  --set global.imageRegistry=gcr.io/YOUR_PROJECT_ID

# Check deployment status
kubectl get pods -n brain-researcher-core -w
```

### 6. Deploy Monitoring Stack

```bash
# Monitoring assets live under infrastructure/monitoring/
ls infrastructure/monitoring

# Grafana dashboards and provisioning files live under:
ls infrastructure/monitoring/grafana
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     GKE Ingress (nginx-ingress)                          │
│                     + cert-manager (Let's Encrypt)                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐           ┌───────────────┐           ┌────────────────┐
│   Web UI      │           │    Agent      │           │ Orchestrator   │
│   (Next.js)   │           │   (Flask)     │           │   worker       │
│ Deployment    │           │ Deployment    │           │ Deployment     │
│ (Ingress)     │           │ (Ingress)     │           │ (no ingress)   │
└───────────────┘           └───────────────┘           └────────────────┘
        │                           │
        │                           │
        └──────────────→────────────┘
                    calls (HTTP)
                                    │
                                    ▼
                            ┌───────────────┐           ┌───────────────┐
                            │   BR-KG     │◄─────────►│    Redis      │
                            │   (Flask)     │           │   (Cluster)   │
                            │  Deployment   │           │               │
                            │  1 replica    │           └───────────────┘
                            └───────────────┘
                                    │
                                    ▼
                            ┌───────────────┐
                            │    Neo4j      │
                            │ StatefulSet   │
                            │ (PVC 100Gi)   │
                            └───────────────┘
```

### Namespace Layout

| Namespace | Contents |
|-----------|----------|
| `brain-researcher-core` | Web UI, Agent, BR-KG, Orchestrator worker (no ingress) |
| `brain-researcher-data` | Neo4j, Redis (PostgreSQL optional) |
| `brain-researcher-monitoring` | Prometheus, Grafana, Alertmanager |

## Health Verification

After deployment, verify all services:

```bash
# Check all pods are running
kubectl get pods -n brain-researcher-core
kubectl get pods -n brain-researcher-data
kubectl get pods -n brain-researcher-monitoring

# Check services
kubectl get svc -n brain-researcher-core

# Test health endpoints via port-forward
kubectl port-forward svc/agent 8000:8000 -n brain-researcher-core &
curl http://localhost:8000/api/health/full | jq

# Or via ingress (after DNS setup)
curl https://your-domain.com/api/health/full | jq
```

Expected `/api/health/full` response:
```json
{
  "status": "ok",
  "services": [
    {"name": "agent", "status": "ok", "latency_ms": 0},
    {"name": "br-kg", "status": "ok", "latency_ms": 15},
    {"name": "neo4j", "status": "ok", "latency_ms": 25},
    {"name": "job_store", "status": "ok"}
  ],
  "neo4j": {
    "status": "ok",
    "node_count": 786852,
    "relationship_count": 3243624
  },
  "queue": {"queued": 0, "active_workers": 2},
  "env": "production",
  "build_git_sha": "abc1234"
}
```

## Monitoring Access

After ingress setup:

| Service | URL | Default Credentials |
|---------|-----|---------------------|
| Grafana | https://grafana.your-domain.com | admin / (from secret) |
| Prometheus | https://prometheus.your-domain.com | N/A |
| Alertmanager | https://alertmanager.your-domain.com | N/A |

## Scaling

```bash
# Manual scaling
kubectl scale deployment web-ui --replicas=4 -n brain-researcher-core

# HPA is configured for most services
kubectl get hpa -n brain-researcher-core
```

## Troubleshooting

### Neo4j Connection Issues

```bash
# Check Neo4j pod logs
kubectl logs -l app=neo4j -n brain-researcher-data

# Connect to Neo4j shell
kubectl exec -it neo4j-0 -n brain-researcher-data -- cypher-shell -u neo4j

# Verify BR-KG can reach Neo4j
kubectl exec -it deploy/br-kg -n brain-researcher-core -- \
  curl http://neo4j.brain-researcher-data:7474/
```

### Agent Memory Issues

```bash
# Check resource usage
kubectl top pod -n brain-researcher-core

# View pod details
kubectl describe pod -l app=agent -n brain-researcher-core

# Adjust limits in values.yaml or via --set
helm upgrade brain-researcher . \
  --set agent.resources.limits.memory=6Gi
```

### Service Not Responding

```bash
# Check endpoints
kubectl get endpoints -n brain-researcher-core

# Check service selector matches pods
kubectl describe svc agent -n brain-researcher-core

# View logs
kubectl logs -l app=agent -n brain-researcher-core --tail=100
```

### Ingress/TLS Issues

```bash
# Check ingress status
kubectl get ingress -n brain-researcher-core

# Check cert-manager certificates
kubectl get certificates -n brain-researcher-core

# View ingress controller logs
kubectl logs -l app.kubernetes.io/name=ingress-nginx -n ingress-nginx
```

## Backup & Recovery

### Neo4j Backup

```bash
# Create backup
kubectl exec neo4j-0 -n brain-researcher-data -- \
  neo4j-admin database dump neo4j --to-path=/backups/

# Copy backup locally
kubectl cp brain-researcher-data/neo4j-0:/backups/neo4j.dump ./neo4j-backup.dump
```

### Restore

```bash
# Stop Neo4j
kubectl scale statefulset neo4j --replicas=0 -n brain-researcher-data

# Copy backup to pod and restore
kubectl scale statefulset neo4j --replicas=1 -n brain-researcher-data
# Wait for pod to be ready
kubectl exec neo4j-0 -n brain-researcher-data -- \
  neo4j-admin database load neo4j --from-path=/backups/neo4j.dump --overwrite-destination
```

## CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: Deploy to GKE

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: google-github-actions/auth@v2
        with:
          credentials_json: ${{ secrets.GCP_SA_KEY }}

      - uses: google-github-actions/setup-gcloud@v2

      - run: gcloud container clusters get-credentials brain-researcher --zone us-central1-a

      - name: Build and push images
        run: |
          docker build -t gcr.io/$PROJECT_ID/agent:$GITHUB_SHA ./brain_researcher
          docker push gcr.io/$PROJECT_ID/agent:$GITHUB_SHA

      - name: Deploy with Helm
        run: |
          helm upgrade --install brain-researcher infrastructure/k8s/helm/brain-researcher \
            -n brain-researcher-core \
            -f infrastructure/deployment/gcp/values.prod.yaml \
            --set global.imageRegistry=gcr.io/$PROJECT_ID \
            --set global.imageTag=$GITHUB_SHA
```
