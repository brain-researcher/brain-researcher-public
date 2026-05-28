# Brain Researcher Orchestrator Service

The Orchestrator is the analysis-job and workflow service in the split-service
runtime.

## Ownership boundary

- `src/brain_researcher/services/orchestrator/`: job execution, job inspection,
  analysis APIs, dashboard metrics, share/credits/notification backends

The active local/prod topology is split services:
- Web UI (3000)
- Agent (8000)
- Orchestrator (3001)
- BR-KG (5000)

## Current web topology

```text
Browser
  -> Web UI (3000)
     -> Agent (8000) for chat/files/datasets/runs/threads
     -> BR-KG (5000) for graph routes
     -> Orchestrator (3001) for analyses, job inspection, share, credits,
        notifications, and dashboard metrics
```

The Web UI owns the public browser-facing `/api/*` surface. Orchestrator is one
of the upstream services that those route handlers call.

## Core responsibilities

- Accept analysis runs via `/run`
- Persist and serve job state via `/api/jobs/*`
- Stream progress, steps, and analysis updates
- Expose dashboard/queue metrics used by the Web UI
- Coordinate with Agent and BR-KG during multi-step workflows

## Common endpoints

- `GET /health`
- `POST /run`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/stream`
- `GET /api/jobs/{job_id}/steps`
- `GET /api/analyses/{analysis_id}`
- `GET /api/analyses/{analysis_id}/export`
- `POST /api/analyses/{analysis_id}/share`
- `GET /api/dashboard/metrics`

## Analysis bundle export

`GET /api/analyses/{analysis_id}/export` returns a zip of the run-centric
analysis bundle. The archive includes the canonical run files
(`analysis_bundle.json`, `observation.json`, `trajectory.json`, traces, and
artifacts) plus a `.bundle_support/` directory with end-user install assets.

Use these files as the install entrypoint after download:

- `.bundle_support/docker-compose.yml`: primary startup path for BR end users
- `.bundle_support/.env.example`: copy to `.env` and fill in required secrets
- `.bundle_support/quickstart.md`: shortest path to launch and verify the stack
- `.bundle_support/installation.md`: fuller installation and troubleshooting guide
- `.bundle_support/environment.yml`: fallback for advanced users who cannot use Docker

For direct users, prefer the Docker path. `environment.yml` is included as a
fallback, not the default install flow.

## Running locally

```bash
# Preferred CLI path
br serve orchestrator --host 0.0.0.0 --port 3001

# Direct ASGI launch
uvicorn brain_researcher.services.orchestrator.main_enhanced:app --host 0.0.0.0 --port 3001 --reload
```

## Docker

```bash
docker-compose up orchestrator
```

## Key environment variables

- `AGENT_URL` - default `http://localhost:8000`
- `NEUROKG_URL` - default `http://localhost:5000`
- `REDIS_URL` - optional job/queue backing store
- `ORCHESTRATOR_ALLOWED_ORIGINS` - additional CORS origins

## Related components

- Web UI proxy routes: `apps/web-ui/src/app/api/`
- Agent service: `src/brain_researcher/services/agent/`
- BR-KG service: `src/brain_researcher/services/neurokg/`
