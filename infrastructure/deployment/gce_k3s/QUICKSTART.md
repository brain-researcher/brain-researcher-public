# GCE + k3s Quickstart (single node)

This guide deploys **Brain Researcher** to a **single-node k3s** cluster running on a
**GCE VM**.

## 0) Prereqs

- A GCP project with `gcloud` configured
- A Linux VM with a public IP (Ubuntu 22.04+ recommended)
- `kubectl` + `helm`
- A container registry accessible from the VM (Docker Hub public repos are simplest)
- Optional: `cert-manager` if you want LetsEncrypt-managed TLS

## 1) (Optional) Create the VM (gcloud)

Choose project/region/zone:

```bash
export PROJECT_ID="your-project"
export REGION="us-central1"
export ZONE="${REGION}-a"
gcloud config set project "${PROJECT_ID}"
```

Create a custom 8 vCPU / 16GB VM and 512GB SSD boot disk:

```bash
export VM_NAME="br-k3s-1"

gcloud compute instances create "${VM_NAME}" \
  --zone "${ZONE}" \
  --machine-type "e2-custom-8-16384" \
  --boot-disk-size "512GB" \
  --boot-disk-type "pd-ssd" \
  --image-family "ubuntu-2204-lts" \
  --image-project "ubuntu-os-cloud" \
  --tags "k3s-node"
```

Open inbound ports for HTTP/HTTPS (Traefik typically binds 80/443 in k3s):

```bash
gcloud compute firewall-rules create br-k3s-http \
  --direction=INGRESS --priority=1000 --network=default \
  --action=ALLOW --rules=tcp:80,tcp:443 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=k3s-node
```

SSH into the VM:

```bash
gcloud compute ssh "${VM_NAME}" --zone "${ZONE}"
```

## 2) Install k3s

```bash
curl -sfL https://get.k3s.io | sh -
sudo k3s kubectl get nodes
```

Configure kubectl (optional if you run `kubectl` as root):

```bash
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
kubectl get nodes
```

## 3) Install Helm

```bash
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

## 4) (Optional) Install cert-manager

If you want TLS via LetsEncrypt, install cert-manager and create a ClusterIssuer
named `letsencrypt-prod`.

## 5) Create required secrets

The Helm chart expects a Neo4j password secret by default (see
`infrastructure/k8s/helm/brain-researcher/templates/neo4j-statefulset.yaml`).

```bash
export DOMAIN="brain-researcher.example.com"

kubectl create namespace brain-researcher-core || true

kubectl -n brain-researcher-core create secret generic br-neo4j-password-k8s \
  --from-literal=password='CHANGE_ME'

# Required (Orchestrator): shared JWT secret used by Orchestrator auth + NextAuth HS256 sessions.
# Tip: set NEXTAUTH_SECRET equal to JWT_SECRET_KEY so all services agree.
kubectl -n brain-researcher-core create secret generic brain-researcher-external-services \
  --from-literal=JWT_SECRET_KEY='CHANGE_ME_LONG_RANDOM' \
  --from-literal=NEXTAUTH_SECRET='CHANGE_ME_LONG_RANDOM' \
  --from-literal=NEXTAUTH_URL="https://${DOMAIN}" \
  --from-literal=BR_STUDIO_JUPYTER_TOKEN='OPTIONAL_JUPYTER_SERVICE_TOKEN'

# Required (MCP, preferred): keyed-token auth registry for BR_MCP_AUTH_MODE=token_or_jwt.
# Generate tokens out of band, hash them into BR_MCP_AUTH_TOKENS_JSON, and keep the
# plaintext bearer token somewhere safe; it cannot be recovered from the cluster secret later.
kubectl -n brain-researcher-core create secret generic brain-researcher-mcp-auth \
  --from-literal=BR_MCP_AUTH_TOKENS_JSON='{"prod-break-glass":{"token_hash":"CHANGE_ME_SHA256_OR_HMAC","label":"prod-break-glass"}}' \
  --from-literal=BR_MCP_TOKEN_PEPPER='CHANGE_ME_LONG_RANDOM'

# Optional legacy fallback: single plaintext bearer token. Use only if you intentionally
# want a recoverable break-glass token stored directly in the cluster secret.
# kubectl -n brain-researcher-core create secret generic brain-researcher-mcp-auth \
#   --from-literal=BR_MCP_AUTH_TOKEN='CHANGE_ME_LONG_RANDOM'

# Recommended (Agent/MCP/BR-KG): LLM and literature-search API keys.
kubectl -n brain-researcher-core create secret generic brain-researcher-llm-api-keys \
  --from-literal=GOOGLE_API_KEY='CHANGE_ME' \
  --from-literal=GEMINI_API_KEY='CHANGE_ME' \
  --from-literal=DEEPXIV_TOKEN='CHANGE_ME_OPTIONAL'
```

If you don't want to use Gemini, omit `brain-researcher-llm-api-keys` and set
`DEFAULT_LLM_MODEL` accordingly.

If you want to enable DeepXiv-backed literature search in prod, add
`DEEPXIV_TOKEN` to `brain-researcher-llm-api-keys`. This key is consumed by the
`mcp` deployment directly and by `br-kg` via `extraEnvFrom`. Switching the
internal literature provider still requires setting `BR_LITERATURE_PROVIDER=deepxiv`
on the target services when you are ready to cut over.

## 6) Build & push images

Build/push the images your deployment enables (`agent`, `orchestrator`, `web-ui`, `br-kg`, `mcp`).

Example (replace with your registry):

```bash
export IMAGE_REGISTRY="docker.io/<dockerhub_user_or_org>"
export TAG="$(git rev-parse --short HEAD)"
export RELEASE="brain-researcher"  # must match your `helm upgrade --install <RELEASE>`

docker build -t ${IMAGE_REGISTRY}/agent:${TAG} -f infrastructure/docker/Dockerfile.agent .
docker push ${IMAGE_REGISTRY}/agent:${TAG}

docker build -t ${IMAGE_REGISTRY}/orchestrator:${TAG} -f infrastructure/docker/Dockerfile.orchestrator .
docker push ${IMAGE_REGISTRY}/orchestrator:${TAG}

# Web UI build needs build-time vars for Next.js client bundle + server rewrites.
# These internal hostnames assume RELEASE=brain-researcher and the chart's default Service names.
docker build -t ${IMAGE_REGISTRY}/web-ui:${TAG} \
  -f apps/web-ui/Dockerfile \
  --build-arg NEXT_PUBLIC_USE_API_PROXY=true \
  --build-arg NEXT_PUBLIC_WS_URL="wss://${DOMAIN}/ws" \
  --build-arg NEXT_PUBLIC_BR_KG_API="https://${DOMAIN}/kg" \
  --build-arg NEXT_PUBLIC_ORCHESTRATOR_URL="https://${DOMAIN}" \
  --build-arg NEXT_PUBLIC_AGENT_API="https://${DOMAIN}" \
  --build-arg ORCHESTRATOR_HOST="${RELEASE}-orchestrator" \
  --build-arg ORCHESTRATOR_PORT="3001" \
  --build-arg AGENT_HOST="${RELEASE}-agent" \
  --build-arg AGENT_PORT="8000" \
  --build-arg BR_KG_HOST="${RELEASE}-br-kg" \
  --build-arg BR_KG_PORT="5000" \
  .
docker push ${IMAGE_REGISTRY}/web-ui:${TAG}

docker build -t ${IMAGE_REGISTRY}/br-kg:${TAG} -f Dockerfile --target br-kg .
docker push ${IMAGE_REGISTRY}/br-kg:${TAG}

docker build -t ${IMAGE_REGISTRY}/mcp:${TAG} -f infrastructure/docker/Dockerfile.mcp .
docker push ${IMAGE_REGISTRY}/mcp:${TAG}
```

## 7) Deploy (Helm)

```bash
export DOMAIN="brain-researcher.example.com"

helm upgrade --install brain-researcher infrastructure/k8s/helm/brain-researcher \
  -n brain-researcher-core --create-namespace \
  -f infrastructure/deployment/gce_k3s/values.prod.yaml \
  --set global.domain="${DOMAIN}" \
  --set global.imageRegistry="${IMAGE_REGISTRY}" \
  --set global.imageTag="${TAG}"
```

## 8) Verify

```bash
kubectl -n brain-researcher-core get pods
kubectl -n brain-researcher-core get ingress
```

If your k3s install includes Traefik, it will manage the Ingress. Point your DNS
`A` record at the VM public IP.

## 9) Widen Traefik websocket timeouts (hosted Marimo)

The hosted Marimo workspace (`/hub/{service}`) is a long-lived websocket. Traefik's
default entrypoint `idleTimeout` (180s) drops idle kernel sockets and shows up as
"kernel not found" / reconnect churn in the workspace iframe. This cannot be fixed
with per-Ingress annotations on Traefik (responding timeouts are entrypoint-level),
so apply the bundled `HelmChartConfig` once per cluster:

```bash
kubectl apply -f infrastructure/deployment/gce_k3s/traefik-helmchartconfig.yaml
kubectl -n kube-system rollout status deploy/traefik
```

On an nginx-ingress cluster you don't need this — the per-session Marimo Ingress
already carries `proxy-read-timeout` / `proxy-send-timeout` annotations
(see `BR_MARIMO_RUNTIME_INGRESS_WS_TIMEOUT`). Operators on other controllers can
inject custom annotations via `BR_MARIMO_RUNTIME_INGRESS_ANNOTATIONS_JSON`.
