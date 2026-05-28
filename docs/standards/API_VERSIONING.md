# API versioning

Source of truth lives in `src/brain_researcher/services/shared/api_version.py`:

- `API_VERSION` (current value: `v1`)
- `API_VERSION_HEADER` (`X-API-Version`)

Conventions:

- Agent + orchestrator responses always include `X-API-Version`.
- The legacy standalone `api_gateway` Python package can also inject
  `X-API-Version` if missing (see
  `src/brain_researcher/legacy/api_gateway/request_transformer.py`), but it is
  not the default runtime path. No standalone reverse-proxy config is shipped in the public tree. `src/brain_researcher/services/api_gateway/` remains only the
  thin compatibility marker for the historical import path.
- OpenAPI is exposed at both `/openapi.json` and `/api/openapi.json` for
  public route consistency, and includes `info.x-api-version`.

If the API version changes, update the shared constant and keep any private
compatibility config in sync.
