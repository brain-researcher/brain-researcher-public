# GCE + k3s chart inspection

> **Status: experimental, render-only.** This page does not provision GCE,
> install k3s, create Kubernetes resources, or deploy Brain Researcher. It is a
> static inspection path for the checked-in Helm chart.

For the supported local path, use the root
[local deployment guide](../../../DEPLOYMENT.md). For all deployment asset
boundaries, use the [status matrix](../README.md).

## Inspect the chart

Run from the repository root with Helm installed:

```bash
helm lint infrastructure/k8s/helm/brain-researcher
helm template brain-researcher infrastructure/k8s/helm/brain-researcher \
  --namespace brain-researcher-core \
  > /tmp/brain-researcher-rendered.yaml
```

Then inspect the output without applying it:

```bash
grep -nE '^(kind:|[[:space:]]*(image:|secretKeyRef:|storageClassName:|host:))' \
  /tmp/brain-researcher-rendered.yaml
```

Check at least:

- every image repository and tag is explicit and actually published;
- every referenced secret name and key will be created by the operator;
- namespaces, service accounts, storage classes, ingress, DNS, and TLS match
  the intended cluster;
- the rendered objects contain no placeholder credentials or local-only hosts.

A clean lint or render result proves chart syntax only. The public repository
does not provide the immutable images, secrets, cloud resources, or rollout and
recovery procedures needed to turn this inspection into a production deploy.

The former VM provisioning and cluster mutation walkthrough remains available
only as an
[exact Git snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/deployment/gce_k3s/QUICKSTART.md).
