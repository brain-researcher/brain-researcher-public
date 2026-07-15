# Deployment assets

This directory contains deployment notes and operator artifacts with different
support levels. It does not provide a verified one-command production deploy.

| Surface | Status | Boundary |
|---|---|---|
| [Root Docker Compose entrypoint](../../README.md#quick-start-local-docker) | **active local starting point** | Compose is the maintained local stack; runtime credentials and optional profiles may still be required. |
| [Helm chart](../k8s/helm/brain-researcher/) | **experimental/incomplete** | `helm template` is currently a syntax/render inspection only. Default values produce invalid leading-slash images such as `/agent:latest`, and the image and secret semantics are not deployment-ready. Do not apply the rendered output to a cluster. |
| [`gce_k3s/QUICKSTART.md`](gce_k3s/QUICKSTART.md) | **experimental/incomplete** | Requires GCP, registry, DNS, cluster, and secret setup. Its checked-in command only renders operator-supplied image values for inspection; it does not install a deployment. |
| [`gcp/GKE_QUICKSTART.md`](gcp/GKE_QUICKSTART.md) | **historical** | Despite its directory name, it describes an older GCE VM plus k3s path. Do not treat it as a current GKE contract. |
| [`blue_green.sh`](blue_green.sh) | **experimental** | Stateful operator helper for pre-existing Swarm or Kubernetes services. It can change live traffic and writes deployment state; it is not a default release command. |
| `conda/` and `docker/` helper assets | **historical/operator-specific** | Support files for earlier deployment work, not complete deployment recipes. |
| Any real cloud or cluster rollout | **private-input-required** | Requires operator-owned credentials, registry/image tags, DNS, secrets, storage choices, policy review, and a deployment-specific values file. None are shipped preconfigured. |

## Working directory

Run repository-relative validation from the repository root:

```bash
cd "$(git rev-parse --show-toplevel)"
PUBLIC_HOSTNAME=localhost docker compose --env-file .env.example config --quiet
helm template brain-researcher infrastructure/k8s/helm/brain-researcher \
  -f infrastructure/k8s/helm/brain-researcher/values.yaml \
  > /tmp/brain-researcher-rendered.yaml
```

These commands validate local configuration/rendering only. They do not build or
publish images, create cloud resources, change DNS, create secrets, or apply
anything to a cluster. A successful Helm render does not make the chart
apply-ready: inspect the output and expect the current defaults to contain
invalid images such as `/agent:latest` until the chart's image and secret
semantics are repaired.

## Operational boundary

Copy deployment values into a private operator workspace, replace every
placeholder through your secret-management process, inspect the rendered output,
and use the exact commit/image tag intended for the rollout. The root
[`DEPLOYMENT.md`](../../DEPLOYMENT.md) is retained as a historical guide and is
not the current executable contract.
