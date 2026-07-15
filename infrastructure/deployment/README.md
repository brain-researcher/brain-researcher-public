# Deployment asset status

This page defines the support boundary for public deployment documentation and
shipped infrastructure assets. The only **supported** deployment path is the
root Docker Compose stack for local development. Files it directly consumes are
part of that local path; every other deployment asset is experimental or
historical even when it is not named individually below. No public production
deployment is supported.

| Surface | Status | Verifiable boundary |
|---|---|---|
| [Root local guide](../../DEPLOYMENT.md) and [`docker-compose.yml`](../../docker-compose.yml) | **active** | Local development only. Validate with Compose, start locally, and run the shipped health smoke. |
| [`docker-compose.prod.yml`](../../docker-compose.prod.yml), Compose overrides, and their Nginx, HAProxy, PgBouncer, and database configuration | **experimental** | Operator-specific static assets. They are not a supported production target or a published-image contract. |
| [Main Helm chart](../k8s/helm/brain-researcher/) and raw Kubernetes manifests, including [Istio templates](../k8s/istio/) | **experimental** | `helm lint` and `helm template` for the linked chart are static inspection only. No cluster apply, image availability, storage, ingress, or secret provisioning is verified. |
| [Monitoring configuration](../monitoring/) | **experimental** | Static dashboards, rules, and Compose configuration only. The unverified startup helper was removed; this is not a second supported local stack. |
| [JupyterHub design values](../jupyterhub/) and [OpenNeuro add-on](../k8s/addons/) | **experimental** | Static operator sketches only. No pinned upstream chart, published workspace image, credential contract, or cluster execution has been verified. |
| Legacy CDN/CloudFront assets under `src/brain_researcher/infrastructure/cdn/` | **experimental** | Unreferenced static design assets. No AWS target, Terraform state, image/runtime contract, or apply workflow is supported. |
| [`restart_services_with_niclip.sh`](../../scripts/services/restart_services_with_niclip.sh) | **experimental** | Destructive local service-control helper retained for later script inventory. It is not the supported deployment path and must be reviewed before use. |
| [`gce_k3s/QUICKSTART.md`](gce_k3s/QUICKSTART.md) | **experimental** | Render-only chart inspection. It does not create a VM, cluster, namespace, secret, or release. |
| [`gcp/GKE_QUICKSTART.md`](gcp/GKE_QUICKSTART.md) | **historical** | Tombstone for an older VM-plus-k3s document that was stored under a misleading GKE path. It is not an active quickstart. |
| [Cloudflare note](../../apps/web-ui/CLOUDFLARE_DEPLOYMENT.md) | **experimental** | Records an unverified hosting idea and a local Web build check, not a hosted deployment recipe. |
| [Deployment archive index](../../docs/archive/deployment/README.md) | **historical** | Links exact Git snapshots for removed production, HPC, load-balancing, and traffic-switching material. |
| Retired autoscaling, Cloudflare automation, host Nginx setup, and Istio install/chart helpers | **historical** | Removed from the active tree because they mutated external systems or failed static validation without a supported target. Exact snapshots are in the archive index. |
| Any real cloud or cluster rollout | **private-input-required** | An operator must supply reviewed infrastructure, immutable images, credentials, DNS, TLS, storage, secrets, observability, backup, rollback, and an explicit rollout target outside this public contract. |

## Local Compose contract

Follow the root [local deployment guide](../../DEPLOYMENT.md). The key
validation and health commands, run from the repository root, are:

```bash
# Fresh checkout only; preserve an existing local secret file.
test -e .env || cp .env.example .env
```

Before continuing, edit `.env`, replace the required placeholders, and keep the
file out of version control. Then validate and start the stack:

```bash
PUBLIC_HOSTNAME=localhost docker compose --env-file .env config --quiet
docker compose up -d --build --wait --wait-timeout 300
docker compose ps --all
bash scripts/smoke/health_smoke.sh
```

If a service is not healthy, inspect its logs:

```bash
docker compose logs --tail=200
```

When finished, stop the stack without deleting its volumes:

```bash
docker compose down
```

A successful Compose parse does not validate credentials or runtime health; a
successful health smoke does not establish production readiness.

## Static Helm inspection

Run the following commands from the repository root with Helm installed. They
do not install or apply resources:

```bash
helm lint infrastructure/k8s/helm/brain-researcher
helm template brain-researcher infrastructure/k8s/helm/brain-researcher \
  --namespace brain-researcher-core \
  > /tmp/brain-researcher-rendered.yaml
```

Review the rendered images, namespaces, storage, ingress, service accounts, and
all `existingSecret` references. The chart expects deployment-specific secrets
to be pre-created; this repository does not supply their values. Rendering is a
syntax and semantics inspection gate, never execution authority.
