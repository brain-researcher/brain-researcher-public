# Real Pipeline Execution E2E (Playwright)

This is an **opt-in** E2E suite that runs a **real analysis** through the Web UI API
(`POST /api/analyses`) and waits for completion.

It is separate from the PRD-gated tests (which use mocks for determinism).

## Prereqs

- Web UI dev server running (default local E2E URL: `http://localhost:3002`)
- Agent + Orchestrator running and reachable from the Web UI
- BR-KG running if your analysis path depends on catalog/KG-backed dataset resolution
- A valid JWT bearer token accepted by the Web UI (`BR_TEST_TOKEN`)

## Setup

```bash
cd apps/web-ui

cp .env.test.template .env.test
# edit .env.test to set BR_TEST_TOKEN (and optionally dataset/template)
# set BR_AGENT_URL / BR_ORCHESTRATOR_URL / BR_KG_URL if you are not using
# the local defaults (8000 / 3001 / 5000)
source .env.test
```

## Run

```bash
npm run e2e:real
```

## Notes

- The local harness starts `npm run dev:3002` and uses the same-origin proxy path by default.
- For local runs, prefer server-side overrides (`BR_AGENT_URL`, `BR_ORCHESTRATOR_URL`,
  `BR_KG_URL`) instead of browser-facing `NEXT_PUBLIC_*` service URLs.
- Default dataset/template:
  - `BR_TEST_DATASET_ID=ds:openneuro:ds000001`
  - `BR_TEST_TEMPLATE_ID=connectivity/nilearn_connectivity`
- Override runtime via `BR_TEST_MAX_RUN_MS` (ms; if < 1000 treated as minutes).
- If the analysis fails, the test prints the analysis detail JSON (truncated) to help debugging.
