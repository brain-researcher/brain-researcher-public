# Brain Researcher API Gateway

This package is a thin compatibility marker for the retired full-gateway
surface. It preserves the historical
`brain_researcher.services.api_gateway` import root only.
This package is the legacy full-gateway compatibility surface.
The canonical Python owner now lives under `src/brain_researcher/legacy/api_gateway/`.

## Ownership boundary

- `src/brain_researcher/services/gateway/`: legacy single-port compatibility gateway
- `src/brain_researcher/cli/commands/services/gateway_launcher.py`: legacy launcher wrapper
- `src/brain_researcher/services/api_gateway/`: package-level compatibility marker
  for the historical import root only
- `src/brain_researcher/legacy/api_gateway/`: canonical Python owner for the
  retired full-gateway runtime

## Default runtime path

The current default runtime path is split services:

```bash
br serve agent
br serve orchestrator
br serve web
```

## What still lives here

The root `api_gateway/` package is no longer the canonical deployment target.
It exists to support:

- the historical package root import path
- tests/experiments that still exercise the old standalone reverse proxy
- the package marker README and `__init__.py` shim only

No runtime implementation modules live in this directory. If you need to change
legacy gateway behavior, update `src/brain_researcher/legacy/api_gateway/`
instead.

This compatibility marker preserves the root package only. The old service-local
submodule tree is no longer retained under `src/brain_researcher/services/api_gateway/`.

No standalone reverse-proxy config or Docker image is shipped in the public tree.
Use the canonical legacy package directly when you explicitly need that stack,
and provide your own local config outside the release archive:

```bash
python -m brain_researcher.legacy.api_gateway.cli --help
python -m brain_researcher.legacy.api_gateway.cli serve --config /path/to/local-gateway.yaml
```

If you are changing the active local/prod runtime topology, do not edit this
package. This package is compatibility-only.
