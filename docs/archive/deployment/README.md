# Historical deployment index

<!-- docs-status: historical -->

This index records deployment-oriented material removed or downgraded during
the public deployment-contract cleanup. It is
provenance, not an executable guide. The linked files may contain stale dependencies, missing paths,
destructive commands, mutable image tags, or unverified production claims.

Use the current
[local deployment guide](https://github.com/brain-researcher/brain-researcher-public/blob/main/DEPLOYMENT.md)
and
[deployment status matrix](https://github.com/brain-researcher/brain-researcher-public/blob/main/infrastructure/deployment/README.md)
for active instructions.

All historical links below are pinned to the exact public commit immediately
before the cleanup:
`d2d889a238b47d6b4409723223d6832693d298f6`.

| Historical asset | Why it is not active | Exact snapshot |
|---|---|---|
| Root production guide | Referenced helpers that were not shipped and claimed unverified production, backup, and rollback behavior. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/DEPLOYMENT.md) |
| Misnamed GKE quickstart | Described a VM-plus-k3s path and depended on missing operator overlays. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/deployment/gcp/GKE_QUICKSTART.md) |
| GCE plus k3s walkthrough | Included cloud and cluster mutation steps without a supported release target. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/deployment/gce_k3s/QUICKSTART.md) |
| k3s Traefik mutation overlay | Changed live cluster entrypoint timeouts but had no supported cluster or rollout contract. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/deployment/gce_k3s/traefik-helmchartconfig.yaml) |
| Cloudflare walkthrough | Assumed hosting behavior and configuration that were not shipped or verified. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/apps/web-ui/CLOUDFLARE_DEPLOYMENT.md) |
| HPC Dockerfile | Installed a nonexistent Python extra and attempted to build an incomplete JavaScript package. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/docker/Dockerfile.hpc) |
| HPC Singularity definition | Referenced an unpublished `hpc-latest` image and advertised unverified CLI/runtime behavior. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/docker/Singularity.def) |
| Load-balanced deployment script | Mutated Docker Swarm services and local state without a supported target or recovery contract. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/deploy-load-balanced.sh) |
| Blue/green traffic switcher | Mutated Swarm or Kubernetes traffic and wrote deployment state without a verified release workflow. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/deployment/blue_green.sh) |
| Cloudflare infrastructure helpers | Installed tools, wrote credentials, and mutated DNS, zone, Worker, and Terraform state without a supported hosting target. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/tree/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/cloudflare) |
| Host Nginx setup | Installed system packages, rewrote host configuration, and reloaded Nginx around an unverified Cloudflare topology. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/tree/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/nginx) |
| Istio helpers and secondary Helm chart | Included cluster mutation commands, stale paths and dependencies, and a chart that did not pass `helm lint`. | [Scripts](https://github.com/brain-researcher/brain-researcher-public/tree/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/istio) · [Chart](https://github.com/brain-researcher/brain-researcher-public/tree/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/k8s/helm/brain-researcher-istio) |
| Monitoring startup helper | Started a second Compose stack with mutable pulls, fixed ports, a blocking wait, and default credentials outside the supported local path. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/monitoring/service_stack/start_monitoring.sh) |
| Swarm/Kubernetes autoscaler | Defaulted to Docker Swarm and could continuously scale Swarm services or patch Kubernetes Deployments without a supported target or explicit execution gate. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/infrastructure/autoscaling/autoscaler.py) |
| Cloudflare Pages deployment scripts and config | Deployed to a fixed Pages project, included tenant-specific identifiers, and claimed hosted success without a supported target or runtime smoke. | [Static deploy](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/scripts/services/web_ui/deploy.sh) · [SSR deploy](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/scripts/services/web_ui/deploy-ssr.sh) · [Wrangler config](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/apps/web-ui/wrangler.toml) |
| Railway deployment helpers and hosted probe | Logged into Railway, pushed a release, or probed a placeholder hosted URL without a verified Railway project or release contract. | [Deploy](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/scripts/services/br-kg/deploy_to_railway.sh) · [Preparation](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/scripts/services/br-kg/deploy.sh) · [Probe](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/scripts/services/br-kg/test_railway_deployment.sh) |
| Hosted BR-KG pseudo-test | Used literal placeholder hostnames and printed deployment success messages without a configured target or assertions suitable for a unit test. | [Snapshot](https://github.com/brain-researcher/brain-researcher-public/blob/d2d889a238b47d6b4409723223d6832693d298f6/tests/unit/br_kg/test_brain_researcher_deployment.py) |

The unsafe files themselves are not copied into an archive directory because
that would leave runnable-looking stale commands in the active tree.
Git history is the archive and provides exact provenance when inspection is needed.
