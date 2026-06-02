# Brain Researcher API Gateway

This package is the legacy full-gateway compatibility surface.

## Ownership boundary

- `src/brain_researcher/services/gateway/`: legacy single-port compatibility gateway
- `src/brain_researcher/cli/commands/services/gateway_launcher.py`: legacy launcher wrapper
- `src/brain_researcher/services/api_gateway/`: package-level compatibility marker
  for the historical import root only

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

No standalone reverse-proxy config or Docker image is shipped in the public tree.
Use the canonical legacy package directly when you explicitly need that stack,
and provide your own local config outside the release archive:

```bash
python -m brain_researcher.legacy.api_gateway.cli --help
python -m brain_researcher.legacy.api_gateway.cli serve --config /path/to/local-gateway.yaml
```

If you are changing the active local/prod runtime topology, do not edit this
package. This package is compatibility-only.
