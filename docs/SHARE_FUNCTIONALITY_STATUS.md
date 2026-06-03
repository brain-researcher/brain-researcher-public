# Share Functionality Status

**Date**: 2026-03-09
**Status**: Active and stateful

## Summary

Analysis sharing is now owned by the Orchestrator state store.
The active browser-facing share surface is:

- `POST /api/analyses/{analysis_id}/share` -> Next.js facade -> Orchestrator
- `GET /api/share/{token}` -> Next.js facade -> Orchestrator share resolver + Orchestrator job detail
- `DELETE /api/share/{token}` -> Next.js facade -> Orchestrator revoke
- `GET /api/share/{token}/artifacts/download?url=...` -> Next.js facade -> Orchestrator artifact download
- `GET /api/share/{token}/artifacts/{path}` -> Next.js facade -> Orchestrator artifact metadata + canonical artifact URL proxy

There is no active local stateless token issuance, verification, or revocation path left in the Web UI.

## Current Ownership Model

### Token issuance and storage
- Share creation is initiated through [analysis share route](<repo>/apps/web-ui/src/app/api/analyses/[analysisId]/share/route.ts).
- Orchestrator persists stateful analysis share tokens in SQLite via [analyses_endpoints.py](<repo>/src/brain_researcher/services/orchestrator/analyses_endpoints.py) and [sqlite_state_store.py](<repo>/src/brain_researcher/services/orchestrator/sqlite_state_store.py).
- New share records persist `created_by`, so revoke authorization can be enforced centrally.

### Token resolution and revoke
- Canonical share resolve/revoke live in [share_endpoints.py](<repo>/src/brain_researcher/services/orchestrator/share_endpoints.py).
- Web UI share routes use [share-access.ts](<repo>/apps/web-ui/src/lib/server/share-access.ts) as the single helper for Orchestrator-backed share resolution.
- Revoke authorization is enforced by Orchestrator for owner-tagged records.

### Artifact access
- Shared artifact downloads only accept canonical Orchestrator job artifact URLs:
  - `/api/jobs/{id}/artifacts/files/...`
- Both shared artifact routes enforce summary/full share semantics before proxying the artifact payload.
- The direct shared artifact path route no longer reads files from local disk.

## Active Files

### Web UI facades
- [apps/web-ui/src/app/api/share/[token]/route.ts](<repo>/apps/web-ui/src/app/api/share/[token]/route.ts)
- [apps/web-ui/src/app/api/share/[token]/stream/route.ts](<repo>/apps/web-ui/src/app/api/share/[token]/stream/route.ts)
- [apps/web-ui/src/app/api/share/[token]/artifacts/download/route.ts](<repo>/apps/web-ui/src/app/api/share/[token]/artifacts/download/route.ts)
- [apps/web-ui/src/app/api/share/[token]/artifacts/[...path]/route.ts](<repo>/apps/web-ui/src/app/api/share/[token]/artifacts/[...path]/route.ts)
- [apps/web-ui/src/lib/server/share-access.ts](<repo>/apps/web-ui/src/lib/server/share-access.ts)

### Orchestrator authority
- [src/brain_researcher/services/orchestrator/analyses_endpoints.py](<repo>/src/brain_researcher/services/orchestrator/analyses_endpoints.py)
- [src/brain_researcher/services/orchestrator/share_endpoints.py](<repo>/src/brain_researcher/services/orchestrator/share_endpoints.py)
- [src/brain_researcher/services/orchestrator/sqlite_state_store.py](<repo>/src/brain_researcher/services/orchestrator/sqlite_state_store.py)

## Runtime expectations

### Environment
Set the normal Web UI + Orchestrator envs in `apps/web-ui/.env.local`:

```env
NEXT_PUBLIC_USE_API_PROXY=true

# Server-side downstream targets for Next.js route handlers
BR_ORCHESTRATOR_URL=http://127.0.0.1:3001

# Optional explicit internal overrides if share pages also need Agent/BR-KG
# BR_AGENT_URL=http://127.0.0.1:8000
# BR_KG_URL=http://127.0.0.1:5000
```

No share-specific HMAC secret is required on the active Web UI path anymore.
Share token persistence depends on the Orchestrator state store being enabled.

### Dev smoke
```bash
# Create a share link through the normal authenticated flow
curl -X POST http://127.0.0.1:3000/api/analyses/<analysis_id>/share \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <jwt>' \
  -d '{"share_level":"summary","expires_in_hours":24}'

# Resolve it publicly
curl http://127.0.0.1:3000/api/share/<token>
```

## Retired implementation

The following local Web UI modules are retired and should stay absent from the active path:

- `apps/web-ui/src/lib/server/share-token.ts`
- `apps/web-ui/src/lib/server/share-token-revocation.ts`
- `apps/web-ui/src/lib/server/share-security.ts`

They implemented an older stateless/HMAC share-token model and local revoke file, which is no longer the source of truth.

## Guardrails

The active ownership contract is enforced by:

- [tests/unit/config/test_orchestrator_agent_boundary_contract.py](<repo>/tests/unit/config/test_orchestrator_agent_boundary_contract.py)
- [apps/web-ui/tests/unit/api/share.routes.spec.ts](<repo>/apps/web-ui/tests/unit/api/share.routes.spec.ts)
- [apps/web-ui/tests/unit/api/share.artifacts-download.routes.spec.ts](<repo>/apps/web-ui/tests/unit/api/share.artifacts-download.routes.spec.ts)
- [apps/web-ui/tests/unit/api/share.artifacts-path.routes.spec.ts](<repo>/apps/web-ui/tests/unit/api/share.artifacts-path.routes.spec.ts)
- [tests/unit/orchestrator/test_share_endpoints.py](<repo>/tests/unit/orchestrator/test_share_endpoints.py)

## Residual compatibility note

Legacy ownerless rows in the share store remain revocable by any authenticated user because they have no `created_by` to enforce. New share links store ownership metadata and use centralized revoke checks.
