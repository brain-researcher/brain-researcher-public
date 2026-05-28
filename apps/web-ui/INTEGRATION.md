# Web UI Integration (Browser -> Next.js -> Agent/Orchestrator/BR-KG)

## Overview
The Web UI owns the browser-facing `/api/*` surface and fans requests out to
Agent, Orchestrator, and BR-KG through Next.js route handlers. This doc
captures the current ownership split, required configuration, and verification
steps.

## Current Topology (hot path)
- Browser -> Next.js (port 3000)
- Next `/api/chat`, `/api/files`, `/api/datasets`, `/api/threads` plus the compatibility `/api/runs*` facade -> Agent service (port 8000)
- Next `/api/analyses/*`, `/api/share/*`, `/api/user/notifications/*`, `/api/credits/*`, `/api/dashboard/metrics` -> Orchestrator service (port 3001)
- Next `/api/kg/*` and `/api/neurokg/*` -> BR-KG service (port 5000)
- Internal orchestrator execution surfaces remain `/run` and `/api/jobs/*`

## Integration Status (what is wired today)

### 1) API client + transport (done)
- `src/lib/api.ts` centralizes HTTP/SSE calls.
- SSE helpers cover chat/analyses/threads streams; consistent error handling.
- Base URLs come from env vars (see below).

### 2) Chat workspace (done)
- `/api/chat` and `/api/chat/stream` proxied to Agent.
- Modes supported: research (sync), coding (stream with plan/patch/test
  events), imaging/planning (planning engine flag in context).
- Error bubbles rendered in UI.

### 3) Datasets explorer (done)
- Search: `POST /api/datasets/search` -> Agent.
- Detail: `GET /api/datasets/[id]` -> Agent.
- Filters/search inputs affect payload.

### 4) Demo / analyses (done)
- Demo buttons hit `/api/demo/*` or create analyses via `/api/analyses`.
- Top-level `/api/analyses` create/list now resolve through Orchestrator `/run` and
  `/api/analyses`.
- Analysis detail, steps, share, observation, provenance, and stream routes resolve
  through Orchestrator job/analysis APIs only; there is no targeted Agent fallback
  left under `/api/analyses/*`.
- Shared-link resolve/revoke/download routes under `/api/share/*` also resolve
  through Orchestrator share/job APIs only; there is no local stateless-token
  fallback left on the active path.

### 5) Files panel (done)
- Upload/list/download/delete wired to `/api/files*` -> Agent.

### 6) Auth plumbing (done)
- NextAuth session available; middleware protects private pages and whitelists
  API paths; Authorization headers/cookies forwarded to Agent and Orchestrator.

### 7) Testing hooks (done)
- Health endpoints exposed through Next to Agent/BR-KG; Playwright smoke can
  hit chat/files/datasets; agent UI API unit tests present.

## Service Architecture (UI path)

```
Browser
  |
  v
Next.js Web UI (port 3000)
  |-- /api/chat|files|datasets|threads + compatibility /api/runs* -> Agent (port 8000)
  |-- /api/analyses|share|credits|notifications|dashboard -> Orchestrator (port 3001)
  \-- /api/kg/* and /api/neurokg/* -> BR-KG (port 5000)
```

## Environment Configuration

Set these in `apps/web-ui/.env.local` (or your secrets manager):

```env
NEXT_PUBLIC_USE_API_PROXY=true

# Local downstream services for the Next.js proxy layer
AGENT_HOST=127.0.0.1
AGENT_PORT=8000
ORCHESTRATOR_HOST=127.0.0.1
ORCHESTRATOR_PORT=3001
NEUROKG_HOST=127.0.0.1
NEUROKG_PORT=5000

# Optional explicit internal overrides for server-side route handlers
# BR_AGENT_URL=http://127.0.0.1:8000
# BR_ORCHESTRATOR_URL=http://127.0.0.1:3001
# BR_NEUROKG_URL=http://127.0.0.1:5000
```

Notes:
- Keep `NEXT_PUBLIC_USE_API_PROXY=true` unless you intentionally want the
  browser to bypass the Next.js proxy layer.
- Set `BR_ORCHESTRATOR_URL` explicitly for server-side route handlers if the
  Orchestrator is not reachable through `ORCHESTRATOR_HOST` / `ORCHESTRATOR_PORT`.
- The canonical dev topology is split services; do not derive Orchestrator from
  Agent or legacy compatibility mounts.
- Keep NextAuth secrets alongside the above; API routes forward auth headers to
  downstream services.

## Running the Full Stack (dev)

1) Start backends (hot path only):
```bash
br serve agent --host 0.0.0.0 --port 8000
br serve orchestrator --host 0.0.0.0 --port 3001
br serve kg --host 0.0.0.0 --port 5000
```

2) Start Web UI:
```bash
cd apps/web-ui
npm install        # first time
npm run dev        # or: pnpm dev / br serve web
```

3) Quick health smoke:
```bash
curl -s http://127.0.0.1:3000/api/health
curl -s http://127.0.0.1:3000/api/kg/health
```

## Key Integration Points (current)

### Chat (research / coding / imaging)
- Next proxies `/api/chat` and `/api/chat/stream` to Agent.
- Coding mode: uses stream endpoint; UI consumes `plan/patch/test/message/done`
  events and renders side cards.
- Imaging/planning: sets `ctx.use_planning_engine=true` (or tools mode) so Agent
  can branch to the planning engine.

### Datasets
- Search via `POST /api/datasets/search` -> Agent -> BR-KG as needed.
- Detail via `GET /api/datasets/[id]` -> Agent.

### Demo / analyses
- Landing page demo buttons trigger `/api/demo/*` or create analyses through
  `/api/analyses`; UI subscribes to `/api/analyses/[id]/stream` for progress.
- `/api/runs*` remains a compatibility-only Agent-backed surface for legacy and
  checkpoint/resume-sensitive callers.
- `/api/analyses` is the public analysis facade; create/list/detail/share/stream
  all normalize through Orchestrator-backed routes.

### Files
- Upload/list/download/delete wired to `/api/files*` -> Agent; supports NIfTI,
  CSV, JSON, etc.

### Auth
- NextAuth session required for protected pages; middleware whitelists API
  paths; downstream services read Authorization for ownership checks.

## Linear Issue Tracking

This integration work addresses the following Linear issues:
- **NEURO-6**: Landing Page Hero Section (UI-002)
- **NEURO-28**: Chat Interface Component (UI-003) 
- **NEURO-29**: Evidence Rail Component (UI-004)
- **NEURO-30**: Execution Progress Display (UI-005)

## Testing Checklist (UI wiring)

- [ ] `/api/health` and `/api/kg/health` return 200 through Next.
- [ ] Chat: research and coding modes work; coding stream shows plan/patch/test.
- [ ] Datasets: search and detail respond via Agent.
- [ ] Demo buttons create analyses and stream progress.
- [ ] Files: upload/list/delete via `/api/files*`.
- [ ] Auth: protected pages redirect when signed out; API calls carry auth.
- [ ] Playwright smoke (health/chat/files/datasets) passes in dev/CI.

Note: `/api/analyses` endpoints require auth. For Playwright runs that exercise
analyses creation/listing, set `E2E_AUTH_TOKEN` to a valid JWT.

## Troubleshooting (current topology)

### Services not responding
1. Verify Agent (8000) and BR-KG (5000) are running: `lsof -i :8000`, `lsof -i :5000`.
2. Check Next dev server logs for proxy errors.
3. Curl through Next: `curl -v http://127.0.0.1:3000/api/health`.

### Streaming issues
1. Ensure requests use `/api/chat/stream` in coding mode.
2. Check SSE response headers (`Content-Type: text/event-stream`).
3. Confirm middleware is not redirecting `/api/*` paths.

### Auth issues
1. Verify NextAuth session at `/api/auth/session`.
2. Ensure Authorization header/cookies are forwarded in API route handlers.
3. For dev without auth, set Agent `DISABLE_AUTH_FOR_DEV=1`.

## Next Steps
- Keep UI wiring aligned with Agent API changes.
- Expand Playwright smoke to cover coding stream regressions.
- Add prod-ready env examples for hosted deployments.
