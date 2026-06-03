# UI Wiring Checklist (UI <-> Agent <-> BR-KG)

Use this checklist to verify that the Web UI (Next.js) is correctly wired to the
Agent and BR-KG services across dev/CI/prod. It replaces the legacy
Browser -> Next -> Orchestrator -> Agent/KG/NICLIP flow. The current UI uses
Agent for chat/files/datasets plus the legacy `/api/runs*` compatibility facade,
BR-KG for graph routes, and Orchestrator for
job execution state, analyses details, share, credits, and notifications.

## 0. Current Topology (ground truth)
- Browser -> Next.js Web UI (port 3000)
- Public `/api/chat`, `/api/files`, `/api/datasets`, `/api/threads`, and legacy `/api/runs*` compatibility facade -> Agent service (port 8000)
- `/api/kg/*`, `/api/br-kg/*` -> BR-KG service (port 5000)
- Public `/api/analyses/*`, `/api/share/*`, `/api/user/notifications/*`, `/api/credits/*`, `/api/dashboard/metrics` -> Next.js facades over Orchestrator service (port 3001)
- Internal Orchestrator-owned execution surfaces: `/run`, `/api/jobs/*`, `/api/analyses/*`
- Public analysis facade: top-level `/api/analyses` list/create now normalize directly
  through Orchestrator `/api/analyses` and `/run`; detail/steps/share/export stream
  from Orchestrator job/analysis APIs with no targeted Agent fallback under
  `/api/analyses/*`.
- Public shared-link facade: `/api/share/*` resolve/revoke/download routes now
  normalize through Orchestrator share/job APIs only, with no local stateless-token
  fallback left on the active path.

## Status Summary (2025-12-09)

| Endpoint | Status | Notes |
|----------|--------|-------|
| `/api/health` | ✅ | 3000 → 8000 |
| `/api/br-kg/health` | ✅ | 3000 → 5000 → Neo4j |
| `/api/chat` | ✅ | Research mode |
| `/api/chat/stream` | ✅ | Coding mode SSE |
| `/api/files/*` | ✅ | Upload/list/download/delete |
| `/api/datasets/*` | ✅ | Search/detail |
| `/api/runs/*` | ✅ | Legacy compatibility create/list/status/stream |
| `/api/runs/from-dataset` | ✅ | Legacy Dataset→Run alias that now submits to Orchestrator `/run` |
| Playwright smoke | ✅ | `tests/e2e/smoke.smoke.spec.ts` |

## 1. Config & Proxy
- [x] `.env.local` (or equivalent) defines:
  - `NEXT_PUBLIC_USE_API_PROXY=true`
  - local downstream ownership through `AGENT_HOST` / `AGENT_PORT`,
    `ORCHESTRATOR_HOST` / `ORCHESTRATOR_PORT`, and `BR_KG_HOST` / `BR_KG_PORT`
    or explicit server-side overrides such as `BR_AGENT_URL`,
    `BR_ORCHESTRATOR_URL`, `BR_KG_URL`
  - no unintended browser-direct `NEXT_PUBLIC_AGENT_API`,
    `NEXT_PUBLIC_BR_KG_API`, or `NEXT_PUBLIC_ORCHESTRATOR_URL` in proxy mode
  - no lingering legacy `ORCHESTRATOR_URL` variables in the Web UI environment.
- [x] Next API routes proxy correctly:
  - Chat: `/api/chat`, `/api/chat/stream` -> Agent `/api/chat*`
  - Tools: `/api/tools`, `/api/tools/run` -> Agent `/api/tools*`
  - Compatibility runs: `/api/runs`, `/api/runs/[id]`, `/api/runs/[id]/stream` -> Agent
  - Analysis facade: `/api/analyses` create/list/detail -> Orchestrator `/run` and `/api/analyses/*`
  - Analysis detail/share/export/steps/stream: `/api/analyses/[id]/*` -> Orchestrator `/api/jobs/*` or `/api/analyses/*`
  - Files: `/api/files/upload`, `/api/files`, `/api/files/[id]` (GET/DELETE)
  - Datasets: `/api/datasets/search`, `/api/datasets/[id]` -> Agent
  - Threads: `/api/threads/*` -> Agent
  - Health & demo: `/api/health`, `/api/demo/**` -> Agent
  - BR-KG: `/api/kg/search` -> BR-KG `/api/kg/search`; `/api/br-kg/graph`
    -> BR-KG `/api/graph`; `/api/br-kg/health` -> BR-KG `/health`
- [x] `src/middleware.ts` allows these API paths (no auth redirect/307 on them).
- [x] Quick curl from dev shell succeeds:
  - `curl -s http://127.0.0.1:3000/api/health`
  - `curl -s http://127.0.0.1:3000/api/br-kg/health`
- [x] CLI parity quick check:
  - `AGENT_URL=http://127.0.0.1:8000 br chat ask "hello"`
  - `AGENT_URL=http://127.0.0.1:8000 br chat code "ls" --repo .`
  - `AGENT_URL=http://127.0.0.1:8000 br files ls`

## 2. API Client & Streaming
- [x] Frontend calls go through a single client module (e.g. `src/lib/api.ts`),
      not ad-hoc `fetch` calls scattered across components.
- [x] Chat/datasets/files and the legacy compatibility runs facade all share the same error handling surface.
- [x] Streaming helpers exist and are reused:
  - `openChatStream` (or equivalent) for `/api/chat/stream`
  - `openThreadStream` for `/api/threads/[id]/stream`
  - `openRunStream` for legacy compatibility `/api/runs/[id]/stream`
- [x] Stream event types `plan`, `patch`, `test`, `message`, `done` are parsed
      and dispatched consistently (see `use-chat.ts` streamCodingChat).

## 3. Core Pages
- [x] **Chat (/chat)** supports at least `research`, `coding`, `imaging` modes:
  - Research: `tools.mode="auto"` or `"disabled"` is sent.
  - Coding: `tools.mode="coding"`; `ctx.tools.mode="coding"`; includes
    `repo_root` / `file_paths`; uses `/api/chat/stream` and renders
    `plan/patch/test` events (implemented in `chat-workspace.tsx` and `use-chat.ts`).
  - Imaging/Planning: `ctx.use_planning_engine=true` (or `tools.mode="imaging"`
    / `"auto"`) so PlanningEngine path is reachable.
  - Chat errors render user-friendly bubbles, not raw stack traces.
- [x] **Datasets (/en/datasets)**
  - Search: `POST /api/datasets/search` -> Agent returns `{results, total,
    limit, offset}` and UI respects filters/search term.
  - Detail: `GET /api/datasets/[id]` -> Agent.
- [x] **Demo / Landing (/)**
  - Demo buttons call `/api/demo/*`; curated demo seeding now creates
    deterministic placeholder analyses through Orchestrator `/run` using
    caller-supplied demo ids, with no targeted Agent fallback.
- [x] **Files panel**
  - Upload via `/api/files/upload`.
  - List via `/api/files`.
  - Download/Delete via `/api/files/[id]`.
- [x] **Runs (/en/runs)**
  - List: `/en/runs` shows all user runs with status badges.
  - Detail: `/en/runs/[runId]` shows progress, logs, pipeline steps.
  - SSE: Live streaming of legacy compatibility run progress via `/api/runs/[id]/stream`.
- [x] **Demo acceptance (opt-in)**
  - Motor GLM: `POST /api/demo/glm` returns `run_id`; artifacts include PNG + CSV; completes <120s.
  - Connectivity: `POST /api/demo/connectivity` returns `run_id`; heatmap PNG + metrics JSON.
  - Demo Playwright (optional): `DEMO_SMOKE=1 npm run test:e2e -- demo.smoke.spec.ts`.

## 4. Auth Wiring (NextAuth <-> Agent)
- [ ] `/api/auth/[...nextauth]` login works; session includes user & token.
- [x] Middleware guards protected pages (chat/datasets) and redirects unauth
      users to login. (Chat is whitelisted for dev convenience)
- [x] API routes proxy Authorization header/cookies through to Agent.
- [x] Agent resolves user via JWT (or `DISABLE_AUTH_FOR_DEV=1` fallback) and
      enforces ownership on `/api/threads/*` and compatibility `/api/runs/*`.

## 5. Health & Tests
- [x] `curl` through Next to Agent/BR-KG `/api/health` endpoints returns 200.
- [x] Playwright smoke covers health/chat/files/datasets/runs in dev & CI.
- [x] `pytest tests/unit/agent/test_ui_api.py` and other UI API unit tests pass.

## 6. Local Dev Service Startup

**Quick start (all services):**
```bash
./scripts/dev/dev-services.sh
```

**Individual services:**
```bash
# BR-KG (against Neo4j, not sqlite mock):
br serve kg --host 0.0.0.0 --port 5000

# Agent:
DISABLE_AUTH_FOR_DEV=1 br serve agent --host 0.0.0.0 --port 8000

# Orchestrator:
br serve orchestrator --host 0.0.0.0 --port 3001

# Next.js Web UI:
br serve web --host 0.0.0.0 --port 3000
```

**Selective startup:**
```bash
./scripts/dev/dev-services.sh --no-br-kg  # Skip BR-KG
./scripts/dev/dev-services.sh --no-ui       # API services only
```
