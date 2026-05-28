# brain-researcher-istio (EXPERIMENTAL)

Istio service-mesh overlay for Brain Researcher. **Not validated for v0.1.0** — the templates have pre-existing bugs that surface during `helm template` rendering:

- `templates/telemetry.yaml`: a Jinja2-style `selectattr | map | first | default` expression was inlined where helm expects Go-template syntax. v0.1.0 hardcodes the default bucket list with a TODO; the chain needs a proper Helm `range` + comparison rewrite to honor `.Values.telemetry.metrics.prometheus.customMetrics`.
- `templates/virtual-services.yaml`: calls `include "...virtualServiceSpec" .Values.virtualServices.webui` and the helper at `_helpers.tpl:141` then evaluates `.Chart.Name` against the sub-value context (not root). Fix: pass `(dict "root" $ "value" .Values.virtualServices.webui)` into the include and rewrite helpers to read from the dict.

## What works

- `helm dependency build` succeeds after bumping `istio-base` → `base`, `istio-gateway` → `gateway` and version `1.19.0` → `1.27.2` (the original chart names were renamed upstream; the original version was removed from the istio chart repo). Fixed in `Chart.yaml`.

## Supported deployment paths in v0.1.0

- **Helm**: use the main chart at `../brain-researcher/` — `helm template brain-researcher ../brain-researcher/` renders 26 K8s resources cleanly.
- **Raw manifests**: use `../manifests/` — `kubectl apply --dry-run=client` passes for 9/10 (08-ingress needs Istio CRDs installed first, which is the intended use of this subchart once fixed).

## Roadmap

Fix in v0.2: rewrite `telemetry.yaml` bucket lookup and `_helpers.tpl` virtualServiceSpec context handling, add `helm lint` + `helm template` to CI.
