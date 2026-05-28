# Brain Researcher Helm Chart

This local Helm chart deploys the Brain Researcher service stack on Kubernetes. It is a repository-local deployment scaffold for contributors and operators; no public Helm repository is published for the OSS preview.

## Prerequisites

- Kubernetes 1.20+
- Helm 3.8+
- cert-manager (for SSL certificates)
- Ingress controller (nginx recommended)
- StorageClass for persistent volumes

## Installation

### Quick Start

```bash
# Install from the repository-local chart
helm install brain-researcher ./infrastructure/k8s/helm/brain-researcher \
  -f ./infrastructure/k8s/helm/brain-researcher/values.yaml

# Or install with an environment-specific overlay
helm install brain-researcher ./infrastructure/k8s/helm/brain-researcher \
  -f ./infrastructure/deployment/gce_k3s/values.prod.yaml
```

### Development Installation

```bash
# Clone the repository
git clone https://github.com/zjc062/brain_researcher.git
cd brain_researcher

# Install from local chart
helm install brain-researcher ./infrastructure/k8s/helm/brain-researcher -f ./infrastructure/k8s/helm/brain-researcher/values.yaml
```

## Configuration

The following table lists the configurable parameters and their default values.

### Global Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.domain` | Domain for the platform | `brain-researcher.local` |
| `global.imageRegistry` | Global image registry | `""` |
| `global.imageTag` | Global image tag | `latest` |
| `global.imagePullPolicy` | Global image pull policy | `IfNotPresent` |
| `global.storageClass` | Global storage class | `brain-researcher-standard` |

### Service Configuration

| Service | Parameter | Description | Default |
|---------|-----------|-------------|---------|
| nginx | `nginx.enabled` | Enable nginx proxy | `true` |
| nginx | `nginx.replicaCount` | Number of nginx replicas | `2` |
| orchestrator | `orchestrator.enabled` | Enable orchestrator | `true` |
| orchestrator | `orchestrator.replicaCount` | Number of orchestrator replicas | `3` |
| agent | `agent.enabled` | Enable agent service | `true` |
| agent | `agent.replicaCount` | Number of agent replicas | `2` |
| neurokg | `neurokg.enabled` | Enable BR-KG service | `true` |
| niclip | `niclip.enabled` | Enable NICLIP service | `true` |
| web-ui | `webUi.enabled` | Enable web UI | `true` |
| web-ui | `webUi.replicaCount` | Number of web UI replicas | `2` |
| postgres | `postgres.enabled` | Enable PostgreSQL | `true` |
| redis | `redis.enabled` | Enable Redis | `true` |
| prometheus | `prometheus.enabled` | Enable Prometheus | `true` |
| grafana | `grafana.enabled` | Enable Grafana | `true` |

### Storage Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `storage.classes.standard.name` | Standard storage class name | `brain-researcher-standard` |
| `storage.classes.fastSsd.name` | Fast SSD storage class name | `brain-researcher-fast-ssd` |
| `storage.sharedData.enabled` | Enable shared data storage | `true` |
| `storage.sharedData.size` | Shared data storage size | `200Gi` |

### Security Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `networkPolicies.enabled` | Enable network policies | `true` |
| `secrets.llmApiKeys.create` | Create LLM API keys secret | `true` |
| `secrets.databaseCredentials.create` | Create database credentials secret | `true` |
| `certManager.enabled` | Enable cert-manager integration | `true` |

### Ingress Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress | `true` |
| `ingress.className` | Ingress class name | `nginx` |
| `ingress.hosts` | List of ingress hosts | See values.yaml |
| `ingress.tls` | TLS configuration | See values.yaml |

## Examples

### Production Deployment

```yaml
# Example values.prod.yaml snippet
global:
  domain: brain-researcher.company.com
  environment: production
  imageRegistry: your-registry.com
  imageTag: v1.0.0

nginx:
  replicaCount: 4
  resources:
    requests:
      memory: "256Mi"
      cpu: "200m"
    limits:
      memory: "512Mi"
      cpu: "400m"

orchestrator:
  replicaCount: 6
  autoscaling:
    minReplicas: 6
    maxReplicas: 20

niclip:
  resources:
    limits:
      nvidia.com/gpu: 1
  nodeSelector:
    kubernetes.io/gpu: nvidia

storage:
  classes:
    standard:
      provisioner: "ebs.csi.aws.com"
    fastSsd:
      provisioner: "ebs.csi.aws.com"

certManager:
  clusterIssuer:
    email: "devops@company.com"
    dns01:
      enabled: true
      provider: "route53"

secrets:
  llmApiKeys:
    data:
      openaiApiKey: "your-production-openai-key"
      anthropicApiKey: "your-production-anthropic-key"
```

Canonical production overlays in this repo live under:

- `infrastructure/deployment/gce_k3s/values.prod.yaml`
- `infrastructure/deployment/gcp/values.prod.yaml`

### Development Deployment

```yaml
# dev-values.yaml
global:
  domain: brain-researcher.dev
  environment: development

nginx:
  replicaCount: 1

orchestrator:
  replicaCount: 1
  autoscaling:
    enabled: false

niclip:
  enabled: false  # Disable GPU-intensive service in dev

postgres:
  persistence:
    size: 10Gi

redis:
  persistence:
    size: 1Gi

storage:
  sharedData:
    size: 50Gi

features:
  debugMode: true
  demoMode: true

testing:
  enabled: true
  generateTestData: true
```

### Minimal Deployment

```yaml
# minimal-values.yaml
global:
  domain: localhost

nginx:
  replicaCount: 1
  service:
    type: NodePort

orchestrator:
  replicaCount: 1
  autoscaling:
    enabled: false

agent:
  replicaCount: 1

webUi:
  replicaCount: 1
  autoscaling:
    enabled: false

niclip:
  enabled: false

prometheus:
  enabled: false

grafana:
  enabled: false

ingress:
  enabled: false

networkPolicies:
  enabled: false
```

## Upgrading

```bash
# Upgrade from the local chart
helm upgrade brain-researcher ./infrastructure/k8s/helm/brain-researcher

# Upgrade with new values
helm upgrade brain-researcher ./infrastructure/k8s/helm/brain-researcher -f new-values.yaml

# Rollback to previous version
helm rollback brain-researcher 1
```

## Uninstalling

```bash
# Uninstall the chart
helm uninstall brain-researcher

# Clean up PVCs (if needed)
kubectl delete pvc -n brain-researcher-core -l app.kubernetes.io/instance=brain-researcher
kubectl delete pvc -n brain-researcher-data -l app.kubernetes.io/instance=brain-researcher
```

## Troubleshooting

### Common Issues

1. **ImagePullBackOff**
   - Check image names and registry credentials
   - Verify imagePullSecrets are configured

2. **Pending Pods**
   - Check storage class availability
   - Verify node resources and affinity rules

3. **CrashLoopBackOff**
   - Check resource limits
   - Verify environment variables and secrets

4. **Network Issues**
   - Review network policies
   - Check service endpoints and DNS resolution

### Debug Commands

```bash
# Check pod status
kubectl get pods -n brain-researcher-core

# View pod logs
kubectl logs -n brain-researcher-core -l app.kubernetes.io/name=brain-researcher

# Describe failing pods
kubectl describe pod -n brain-researcher-core <pod-name>

# Check services and endpoints
kubectl get services,endpoints -n brain-researcher-core

# Verify secrets and configmaps
kubectl get secrets,configmaps -n brain-researcher-core
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test the chart thoroughly
5. Submit a pull request

## Support

- Documentation: [`../../../../docs/README.md`](../../../../docs/README.md)
- Issues: https://github.com/zjc062/brain_researcher/issues
- Release gates: [`../../../../docs/release/`](../../../../docs/release/)

## License

This project is licensed under the MIT License - see the [LICENSE](../../../../LICENSE) file for details.
