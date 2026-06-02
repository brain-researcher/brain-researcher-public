# GCE + k3s Production Deployment

This guide deploys **Brain Researcher** to a **GCE VM** running **k3s**, using **Docker Hub** public images and **Let's Encrypt** TLS via cert-manager.

## Prerequisites

- A GCE VM (Ubuntu 22.04+, 4+ vCPUs, 16 GB+ RAM recommended)
- A domain pointing to the VM's external IP (e.g. `brain-researcher.com`)
- Docker Hub account with images pushed (see Step 2)
- SSH access to the VM

## 1. Environment Setup

```bash
export DOMAIN="brain-researcher.com"
export DH_NS="zjc062"                           # Docker Hub namespace
export TAG="$(git rev-parse --short HEAD)"
```

## 2. Build & Push Images

All images are pushed to Docker Hub as public images under `docker.io/${DH_NS}`.

```bash
# br-kg, agent, mcp — root Dockerfile multi-stage targets
docker build --target br-kg -t docker.io/${DH_NS}/br-kg:${TAG} .
docker build --target agent   -t docker.io/${DH_NS}/agent:${TAG}   .
docker build --target mcp     -t docker.io/${DH_NS}/mcp:${TAG}     .

# web-ui — uses its own Dockerfile with build-time NEXT_PUBLIC_* args
docker build \
  -t docker.io/${DH_NS}/web-ui:${TAG} \
  -f apps/web-ui/Dockerfile \
  --build-arg NEXT_PUBLIC_AGENT_API=https://${DOMAIN} \
  --build-arg NEXT_PUBLIC_ORCHESTRATOR_URL=https://${DOMAIN} \
  --build-arg NEXT_PUBLIC_BR_KG_API=https://${DOMAIN}/kg \
  --build-arg NEXT_PUBLIC_WS_URL=wss://${DOMAIN}/ws \
  --build-arg NEXT_PUBLIC_USE_API_PROXY=true \
  --build-arg NEXT_PUBLIC_AUTH_MODE=both \
  --build-arg ORCHESTRATOR_HOST=brain-researcher-orchestrator \
  --build-arg ORCHESTRATOR_PORT=3001 \
  --build-arg AGENT_HOST=brain-researcher-agent \
  --build-arg AGENT_PORT=8000 \
  --build-arg BR_KG_HOST=brain-researcher-br-kg \
  --build-arg BR_KG_PORT=5000 \
  .

# orchestrator — its own Dockerfile
docker build \
  -t docker.io/${DH_NS}/orchestrator:${TAG} \
  -f infrastructure/docker/Dockerfile.orchestrator .

# Push all
for img in br-kg agent mcp web-ui orchestrator; do
  docker push docker.io/${DH_NS}/${img}:${TAG}
done
```

## 3. VM Setup (k3s + Helm)

SSH into the VM and install k3s and Helm:

```bash
curl -sfL https://get.k3s.io | sh -
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

## 4. DNS

Create an A record pointing your domain to the VM's external IP:

```
brain-researcher.com  →  <VM_EXTERNAL_IP>
```

## 5. cert-manager (Let's Encrypt TLS)

```bash
helm repo add jetstack https://charts.jetstack.io && helm repo update
helm upgrade --install cert-manager jetstack/cert-manager \
  -n cert-manager --create-namespace --set crds.enabled=true

cat <<'YAML' | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    email: zijiaochen@stanford.edu
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: traefik
YAML
```

## 6. Create Kubernetes Secrets

Four secret groups are required. Create the namespaces first:

```bash
kubectl create namespace brain-researcher-core
kubectl create namespace brain-researcher-data
```

### 6a. Neo4j Password

```bash
kubectl -n brain-researcher-core create secret generic brain-researcher-database-credentials \
  --from-literal=NEO4J_PASSWORD='<NEO4J_PASSWORD>'
```

### 6b. MCP Auth Token

```bash
kubectl -n brain-researcher-core create secret generic brain-researcher-mcp-auth \
  --from-literal=BR_MCP_AUTH_TOKEN='<random token>'
```

### 6c. LLM API Keys

```bash
kubectl -n brain-researcher-core create secret generic brain-researcher-llm-api-keys \
  --from-literal=GEMINI_API_KEY='<key>' \
  --from-literal=OPENAI_API_KEY='<key>' \
  --from-literal=DEEPSEEK_API_KEY='<key>'
```

### 6d. External Services (NextAuth, OAuth, JWT)

Required for orchestrator and web-ui startup:

```bash
kubectl -n brain-researcher-core create secret generic brain-researcher-external-services \
  --from-literal=NEXTAUTH_URL='https://brain-researcher.com' \
  --from-literal=NEXTAUTH_SECRET='<secret>' \
  --from-literal=AUTH_SECRET='<secret>' \
  --from-literal=JWT_SECRET_KEY='<secret>' \
  --from-literal=JWT_SECRET='<secret>' \
  --from-literal=BR_STUDIO_JUPYTER_TOKEN='<optional jupyter service token>' \
  --from-literal=GOOGLE_CLIENT_ID='<client-id>' \
  --from-literal=GOOGLE_CLIENT_SECRET='<client-secret>'
```

## 7. Helm Deploy

```bash
helm upgrade --install brain-researcher infrastructure/k8s/helm/brain-researcher \
  -n brain-researcher-core --create-namespace \
  -f infrastructure/deployment/gcp/values.prod.yaml \
  --set global.domain="${DOMAIN}" \
  --set global.imageRegistry="docker.io/${DH_NS}" \
  --set global.imageTag="${TAG}"
```

## 8. Google OAuth Console

Add the following authorized redirect URI in the Google Cloud Console:

```
https://brain-researcher.com/api/auth/callback/google
```

## 9. Verification

```bash
# Watch pods come up
kubectl -n brain-researcher-core get pods -w

# Check orchestrator logs
kubectl -n brain-researcher-core logs -l app.kubernetes.io/component=orchestrator

# Verify TLS
curl -Ik https://brain-researcher.com/

# Verify orchestrator health
curl https://brain-researcher.com/health
```

### Checklist

1. All pods Running/Ready
2. `curl -Ik https://brain-researcher.com/` returns 200 with valid cert
3. Web UI loads in browser
4. Google OAuth login works (after adding redirect URI)
5. Dev credentials login: `demo@example.com` / `DemoPass123!`
6. Chat/Agent works end-to-end in web UI

## Ingress Routing Summary

| Path | Backend | Notes |
|------|---------|-------|
| `/` | web-ui:3000 | Catch-all; Next.js handles `/api/*` via internal rewrites |
| `/mcp/setup` | web-ui:3000 | Human MCP client setup page |
| `/mcp` | mcp:7000 | MCP protocol endpoint; browser GET redirects to `/mcp/setup` |
| `/.well-known/oauth-protected-resource` | mcp:7000 | OAuth discovery |
| `/kg` | br-kg:5000 | Knowledge graph API |
| `/ws` | orchestrator:3001 | WebSocket connections |

**Note:** `/api/*` is NOT a separate ingress rule — it falls through to `/` (web-ui). Next.js handles API routes locally and proxies to orchestrator/agent/br-kg via server-side rewrites using `ORCHESTRATOR_HOST`, `AGENT_HOST`, `BR_KG_HOST` env vars.
