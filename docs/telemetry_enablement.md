# Telemetry & Feedback Enablement (Beta)

> Note: feedback endpoints live on Orchestrator at port 3001; the web UI itself
> remains on port 3000.

## Services to run
- **Telemetry API** (usage/events/metrics):
  ```bash
  uvicorn brain_researcher.services.telemetry.api:app --host 0.0.0.0 --port 8003
  ```
- **Orchestrator** (feedback endpoints live here): start as usual (`python start_orchestrator.py` or `uvicorn brain_researcher.services.orchestrator.main_enhanced:app --port 3001`).
  Prefer `br serve orchestrator --port 3001`.

## Environment variables
- For the orchestrator (emits events from feedback submissions):
  - `TELEMETRY_INTERNAL_URL=http://localhost:8003` (or your deployed telemetry base URL)
  - `TELEMETRY_SERVICE_TOKEN=<optional-api-key>`
  - `FEEDBACK_DATA_DIR=./data/feedback` (default)
- For the web UI (Next.js):
  - `NEXT_PUBLIC_USE_API_PROXY=true` (recommended; keeps feedback and analytics same-origin)
  - `NEXT_PUBLIC_TELEMETRY_UPSTREAM=http://localhost:8003` (used by `/api/telemetry/*` proxy)
  - `NEXT_PUBLIC_ENABLE_FEEDBACK_WIDGET=true` (default; set `false` to hide)

## API paths (UI side)
- Feedback form → `POST /api/feedback` (proxied by the Web UI to Orchestrator)
- Feedback screenshot → `POST /api/feedback/screenshot` (proxied by the Web UI to Orchestrator)
- Telemetry batch/events/metrics → `/api/telemetry/**` (proxied to telemetry service)

## Event / metric contract
- UI emits with `event_type`, `service`, `feature_name`, `action`, `user_id`, `session_id`, `context`, `parameters`, `duration_ms`, `success`, `privacy_level`.
- Metrics endpoint expected shape: `POST /telemetry/metrics { start_time, end_time, granularity, services[], metric_types[] }` returning `{ metrics: AnalyticsMetrics }` (see `src/types/analytics.ts`).

## Quick verification
1) Start telemetry + orchestrator.
2) In the UI, open any page; the floating feedback button should render (unless disabled by env).
3) Submit feedback with a screenshot — check `data/feedback/feedback.db` and see telemetry event at `http://localhost:8003/telemetry/events/collect` logs.
4) Open analytics dashboard → charts should call `/api/telemetry/metrics` instead of mock data.
