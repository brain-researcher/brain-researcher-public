# JupyterHub Deployment Skeleton

This directory contains the MVP deployment overlay for the hosted Brain Researcher workspace.

The intended hosted-cloud product shape is:

- `JupyterHub` as the entry point and session manager
- `JupyterLab` as the primary workspace UI
- `Neurodesk` as the neuroimaging tool and compute base image
- `BR MCP` as the domain intelligence layer behind the notebook assistant

This skeleton is intentionally thin. It is not a replacement for the full product wrapper, and it does not define the local Docker or HPC user paths. Those modes use coding agents plus `BR MCP` with a different transport/profile, while this overlay targets the hosted notebook experience only.

## Files

- `values.mvp.yaml`: upstream `jupyterhub/jupyterhub` Helm chart values for the Brain Researcher hosted workspace MVP
- `bootstrap-configmap.yaml`: starter ConfigMap that seeds bootstrap scripts and placeholder workspace content inside single-user pods

## Expected install shape

```bash
helm upgrade --install br-workspace jupyterhub/jupyterhub \
  -n brain-researcher-workspace --create-namespace \
  -f infrastructure/jupyterhub/values.mvp.yaml
```

## What this skeleton assumes

- A Kubernetes cluster with an ingress controller and cert-manager already available
- A shared storage class suitable for user home directories
- A prebuilt `jupyter-singleuser` image that includes or bootstraps Neurodesk access
- An in-cluster BR MCP endpoint reachable by the JupyterHub hub and single-user pods

## Placeholder values to replace

- OIDC client ID and secret
- Hub proxy secret token
- Single-user image tag
- MCP service URL
- TLS secret and issuer settings, if the cluster differs from the default naming

## Next implementation steps

- Replace placeholders with environment-specific values
- Replace the bootstrap placeholder with the notebook assistant bridge and real starter notebooks
- Add a production-ready single-user image definition
- Add mode-specific docs for local Docker and HPC clients that use `BR MCP` directly
