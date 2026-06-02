from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "apps/web-ui/src/lib/api.ts": (
        "const ANALYSES_BASE = '/api/analyses';",
        "`/api/analyses/*` is the browser-facing analysis facade backed by the",
    ),
    "apps/web-ui/tests/unit/lib/api.submit-run.spec.ts": (
        "posts chat/coprocess runs through /api/analyses with canonical checkpoint_id",
        "toContain('/api/analyses')",
    ),
    "apps/web-ui/src/lib/config.ts": (
        "// Downstream service endpoints. Public browser traffic should still go through",
        "ORCHESTRATOR: getEnvVar('ORCHESTRATOR_HOST', 'localhost'),",
        "run: `${SERVICE_URLS.ORCHESTRATOR}/run`,",
        "jobs: `${SERVICE_URLS.ORCHESTRATOR}/api/jobs`,",
        "analyses: `${SERVICE_URLS.ORCHESTRATOR}/api/analyses`,",
        "runs: `${SERVICE_URLS.AGENT}/api/runs`, // legacy compatibility only; canonical browser analysis create/list use orchestrator run/analyses",
    ),
    "apps/web-ui/src/lib/service-endpoints.ts": (
        "Agent-backed public routes include chat/files/datasets/threads plus the",
        "Canonical browser analysis create/list now",
        "Orchestrator-backed public routes include analyses/jobs/share/credits/dashboard/notifications.",
    ),
    "apps/web-ui/src/lib/server/downstream.ts": (
        "Agent owns direct execution/chat/file surfaces used behind public",
        "The public `/api/runs` surface is compatibility-only",
        "Orchestrator owns `/run` plus the canonical job/analysis resources behind",
        "Do not infer Orchestrator from Agent or legacy compatibility flags.",
    ),
    "apps/web-ui/src/app/api/runs/route.ts": (
        "Compatibility-only public facade. New analysis flows should prefer",
        "`/api/analyses` and Orchestrator-owned job resources; keep this only for",
        "resolveAgentBaseUrl()",
        "const COMPAT_HEADER_VALUE = 'agent-runs'",
    ),
    "apps/web-ui/src/app/api/runs/[runId]/route.ts": (
        "Compatibility-only detail facade for legacy run consumers.",
        "resolveAgentBaseUrl()",
        "const COMPAT_HEADER_VALUE = 'agent-runs'",
    ),
    "apps/web-ui/src/app/api/runs/[runId]/stream/route.ts": (
        "Compatibility-only SSE facade for legacy run consumers.",
        "resolveAgentBaseUrl()",
        "const COMPAT_HEADER_VALUE = 'agent-runs'",
    ),
    "apps/web-ui/src/app/api/projects/route.ts": (
        "resolveOrchestratorBaseUrl",
        "/api/analyses?limit=${runsLimit}",
        "const status = normalizeStatus(analysis.state ?? analysis.status)",
    ),
    "apps/web-ui/src/lib/server/demo-seed.ts": (
        "resolveOrchestratorBaseUrl",
        "/api/jobs/${encodeURIComponent(analysisId)}",
        "requested_job_id: analysisId",
        "demo_seed: true",
    ),
    "apps/web-ui/src/app/api/runs/from-dataset/route.ts": (
        "Compatibility route name only. Dataset-triggered run creation now",
        "resolveOrchestratorBaseUrl()}/run",
        "Unable to reach orchestrator service.",
    ),
    "apps/web-ui/tests/unit/api/runs.from-dataset.routes.spec.ts": (
        "http://orchestrator/run",
    ),
    "apps/web-ui/src/app/api/analyses/route.ts": (
        "`/api/analyses` is the public browser-facing analysis facade.",
        "Create/list/detail/stream/share/export all resolve through Orchestrator",
        "Agent remains responsible for `/act`, `/api/chat`,",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/steps/route.ts": (
        "Orchestrator `/api/jobs/{id}/steps` is the canonical step surface.",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/steps/stream/route.ts": (
        "const targetUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/steps/stream`",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/analysis-stream/route.ts": (
        "const targetUrl = `${orchBase}/api/jobs/${encodeURIComponent(analysisId)}/analysis-stream${search}`",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/share/route.ts": (
        "const upstream = await fetch(`${orchBase}/api/analyses/${encodeURIComponent(analysisId)}/share`, {",
        "return NextResponse.json(json ?? { detail: text || upstream.statusText }, { status: upstream.status })",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/artifacts/download/route.ts": (
        "Only Orchestrator /api/jobs/{id}/artifacts/files paths are allowed.",
        "const upstreamUrl = `${resolveOrchestratorBaseUrl()}${normalized}`",
    ),
    "apps/web-ui/src/app/api/share/[token]/artifacts/download/route.ts": (
        "Only Orchestrator /api/jobs/{id}/artifacts/files paths are allowed.",
        "const upstreamUrl = `${resolveOrchestratorBaseUrl()}${normalized}`",
    ),
    "apps/web-ui/src/app/api/share/[token]/route.ts": (
        "const resolved = await resolveSharedAnalysisAccess(token)",
        "return NextResponse.json(resolved.body, { status: resolved.status })",
    ),
    "apps/web-ui/src/app/api/share/[token]/stream/route.ts": (
        "const resolved = await resolveSharedAnalysisAccess(token)",
        "return streamAnalysisProgress(req, resolved.analysisId)",
    ),
    "apps/web-ui/src/app/api/share/[token]/artifacts/[...path]/route.ts": (
        "const resolved = await resolveSharedAnalysisAccess(token)",
        "Artifact is missing a canonical Orchestrator download URL.",
        "return new Response(upstream.body, {",
    ),
    "apps/web-ui/src/lib/server/share-access.ts": (
        "resolveSharedAnalysisAccess",
        "fetch(`${orchBase}/api/share/${encodeURIComponent(trimmed)}`",
        "return { ok: false, status: 502, body: { detail: 'Upstream unavailable.' } }",
    ),
    "apps/web-ui/src/app/analyses/[analysisId]/page.tsx": (
        "upstreamUrl: stringValue(record.download_url) || stringValue(record.url) || null",
    ),
    "apps/web-ui/src/lib/brain-map-artifacts.ts": (
        "asTrimmedString(record.download_url) ??",
        "asTrimmedString(record.url) ??",
    ),
    "apps/web-ui/src/lib/server/analysis-detail.ts": (
        "const [orchJob, orchObservation] = await Promise.all([",
        "const jobPayload = parsePayloadJson(jobJson?.payload_json)",
    ),
    "apps/web-ui/src/lib/brain-researcher-api.ts": (
        "const ORCHESTRATOR_API = serviceEndpoints.orchestratorBase",
        "`${ORCHESTRATOR_API}/copilot/suggest`",
        "`${ORCHESTRATOR_API}/copilot/autocomplete`",
        "`${ORCHESTRATOR_API}/copilot/learn`",
    ),
    "src/brain_researcher/services/orchestrator/copilot_endpoints.py": (
        '@router.post("/suggest", response_model=CopilotSuggestResponse)',
        '@router.post("/autocomplete", response_model=CopilotAutocompleteResponse)',
        '@router.post("/learn", response_model=CopilotLearnResponse)',
    ),
    "src/brain_researcher/services/agent/README.md": (
        "primary downstream backend for Web UI chat, files, datasets, threads, and",
        "Next.js owns the public browser-facing `/api/*` surface.",
        "Orchestrator owns `/run`, `/api/jobs/*`, and JobStore-backed analysis inspection",
        "### Orchestrator-owned job surfaces",
    ),
    "apps/web-ui/README.md": (
        "public `/api/*` routes proxy",
        "NEXT_PUBLIC_USE_API_PROXY=true",
        "ORCHESTRATOR_PORT=3001",
        "BR_ORCHESTRATOR_URL=http://localhost:3001",
        "BR_KG_URL=http://localhost:5000",
        "**Orchestrator**: `/run`, `/api/jobs/*`, `/api/analyses/*`, share, dashboard, credits",
    ),
    "apps/web-ui/INTEGRATION.md": (
        "The Web UI owns the browser-facing `/api/*` surface",
        "Next `/api/analyses/*`, `/api/share/*`, `/api/user/notifications/*`, `/api/credits/*`, `/api/dashboard/metrics` -> Orchestrator service (port 3001)",
        "Top-level `/api/analyses` create/list now resolve through Orchestrator `/run` and",
        "there is no targeted Agent fallback",
        "compatibility-only Agent-backed surface for legacy and",
        "there is no local stateless-token",
    ),
    "apps/web-ui/CONFIG.md": (
        "The Web UI then forwards to Agent, Orchestrator, or BR-KG as needed",
        "Orchestrator",
        "NEXT_PUBLIC_ORCHESTRATOR_URL=http://localhost:3001",
        "ORCHESTRATOR_PORT=3001",
        "NEXT_PUBLIC_BR_KG_API=http://localhost:5000",
        "`BR_ORCHESTRATOR_URL`, `BR_KG_URL`",
        "| Orchestrator | 3001",
        "serviceEndpoints.orchestrator('/api/jobs')",
    ),
    "docs/ENVIRONMENT_SETUP.md": (
        "**Orchestrator service (port 3001)**: `/run`, `/health`, `/docs`, `/api/jobs`, `/api/analyses`, `/api/cache/*`",
        "**Web UI public proxy (port 3000)**: browser-facing `/api/*` routes.",
        "submit/list now go through `/api/analyses*`",
    ),
    "docs/user-guide/cli.md": (
        "Use the agent service for `/act`, `/chat`, and the legacy `/api/runs*` compatibility facade.",
        "Use the orchestrator service for `/run`, `/api/jobs`, `/api/analyses`, `/api/cache/*`, canonical analysis submit/list APIs, and job inspection APIs.",
        "The Web UI owns the public browser-facing `/api/*` surface",
    ),
    "docs/UI_WIRING_CHECKLIST.md": (
        "Internal Orchestrator-owned execution surfaces: `/run`, `/api/jobs/*`, `/api/analyses/*`",
        "Public analysis facade: top-level `/api/analyses` list/create now normalize directly",
        "Analysis facade: `/api/analyses` create/list/detail -> Orchestrator `/run` and `/api/analyses/*`",
        "no targeted Agent fallback under",
        "Analysis detail/share/export/steps/stream: `/api/analyses/[id]/*` -> Orchestrator `/api/jobs/*` or `/api/analyses/*`",
        "no local stateless-token",
        "Legacy Dataset→Run alias that now submits to Orchestrator `/run`",
        "caller-supplied demo ids",
    ),
    "docs/testing/TESTING_GUIDE.md": (
        "curl -X POST http://localhost:3001/run",
        "curl http://localhost:3001/api/jobs/{job_id}",
        "curl -X POST http://localhost:8000/act",
        'self.client.post("/run", json={',
        "locust -f locustfile.py --host=http://localhost:3001",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "apps/web-ui/src/lib/api.ts": (
        "const JOBS_BASE = serviceEndpoints.orchestratorApi('/api/runs');",
        "const RUNS_BASE = '/api/runs';",
    ),
    "apps/web-ui/src/lib/config.ts": (
        "// Orchestrator endpoints (legacy alias to Agent)",
        "jobs: `${SERVICE_URLS.AGENT}/api/runs`,",
        "ORCHESTRATOR: getEnvVar('ORCHESTRATOR_HOST', getEnvVar('AGENT_HOST', 'localhost'))",
        "getEnvVar('NEXT_PUBLIC_API_URL',",
        "getEnvVar('NEXT_PUBLIC_AGENT_URL',",
    ),
    "apps/web-ui/src/lib/brain-researcher-api.ts": (
        "const ORCHESTRATOR_API =\n  process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ||\n  process.env.NEXT_PUBLIC_API_URL || // legacy public-api alias\n  process.env.NEXT_PUBLIC_AGENT_URL ||",
        "`${AGENT_API}/copilot/suggest`",
        "`${AGENT_API}/copilot/autocomplete`",
        "`${AGENT_API}/copilot/learn`",
    ),
    "src/brain_researcher/services/agent/web_service.py": ("/copilot/",),
    "apps/web-ui/src/lib/server/downstream.ts": ("(compat ? '/orchestrator' : '')",),
    "apps/web-ui/src/app/api/runs/route.ts": ("const AGENT_BASE =",),
    "apps/web-ui/src/app/api/runs/[runId]/route.ts": ("const AGENT_BASE =",),
    "apps/web-ui/src/app/api/runs/[runId]/stream/route.ts": ("const AGENT_BASE =",),
    "apps/web-ui/src/app/api/projects/route.ts": ("/api/runs?limit=",),
    "src/brain_researcher/services/agent/README.md": (
        "single backend API",
        "No Orchestrator in the hot path.",
        "wraps `/act_llm` internally",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/steps/route.ts": (
        "Agent `/api/runs/{id}` only for legacy runs that have no JobStore record.",
        "resolveAgentBaseUrl",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/steps/stream/route.ts": (
        "resolveAgentBaseUrl",
        "agent-backed stream",
        "fetchRun(",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/analysis-stream/route.ts": (
        "resolveAgentBaseUrl",
        "fallbackUrl",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/share/route.ts": (
        "resolveAgentBaseUrl",
        "buildAnalysisDetail",
        "issueShareToken",
        "getRequestAuthToken",
        "stateless tokens",
    ),
    "apps/web-ui/src/app/api/analyses/[analysisId]/artifacts/download/route.ts": (
        "resolveAgentBaseUrl",
        "path.startsWith('/api/runs/')",
        "path.startsWith('/api/files/')",
    ),
    "apps/web-ui/src/app/api/share/[token]/artifacts/download/route.ts": (
        "resolveAgentBaseUrl",
        "path.startsWith('/api/runs/')",
        "path.startsWith('/api/files/')",
        "verifyShareToken",
    ),
    "apps/web-ui/src/app/api/share/[token]/route.ts": (
        "verifyShareToken",
        "revokeShareToken",
        "issueInternalJwt",
        "getRequestAuthToken",
        "revocation: 'local'",
    ),
    "apps/web-ui/src/app/api/share/[token]/stream/route.ts": ("verifyShareToken",),
    "apps/web-ui/src/app/api/share/[token]/artifacts/[...path]/route.ts": (
        "verifyShareToken",
        "createReadStream",
        "statSync",
        "resolveArtifactPath(",
        "findRepoRoot(",
    ),
    "apps/web-ui/src/app/analyses/[analysisId]/page.tsx": (
        "const upstreamUrl = a?.url || a?.download_url || null",
    ),
    "apps/web-ui/src/lib/server/analysis-detail.ts": (
        "resolveAgentBaseUrl",
        "agent:/api/runs/",
    ),
    "apps/web-ui/src/lib/server/demo-seed.ts": (
        "resolveAgentBaseUrl",
        "/api/runs",
        "last intentional",
    ),
    "apps/web-ui/README.md": (
        "API proxied to Agent on 8000",
        "NEXT_PUBLIC_BR_KG_API=http://localhost:5001",
    ),
    "apps/web-ui/INTEGRATION.md": (
        "The Orchestrator is no longer on the UI hot path",
        "Next `/api/*` -> Agent service (port 8000)",
        "Orchestrator routes are served by the agent at `/orchestrator`",
        "`/api/runs` remains available for legacy/internal use; UI should prefer",
        "Top-level `/api/analyses` create/list currently normalize against Agent `/api/runs`.",
        "targeted compatibility fallback",
    ),
    "apps/web-ui/src/app/api/analyses/route.ts": (
        "create/list normalization still proxies against Agent `/api/runs`",
    ),
    "apps/web-ui/CONFIG.md": (
        "gateway front door (default 8000)",
        "Orchestrator ports (3001/8010) stay behind the gateway and are not used on the UI hot path.",
        "ORCHESTRATOR_PORT=8000",
        "NEXT_PUBLIC_BR_KG_API=http://localhost:5001",
        "BR_KG_PORT=5001",
        "Set `NEXT_PUBLIC_WS_URL` only if you have a WS endpoint enabled on the Agent",
    ),
    "docs/UI_WIRING_CHECKLIST.md": (
        "Compatibility note: top-level `/api/analyses` list/create still normalize through Agent `/api/runs`",
        "Analysis facade: `/api/analyses` create/list -> Agent `/api/runs` with Web UI normalization",
        "create runs via compatibility `/api/runs`",
    ),
    "docs/testing/TESTING_GUIDE.md": (
        "curl -X POST http://localhost:8000/api/run",
        "curl http://localhost:8000/api/jobs/{job_id}",
        'self.client.post("/api/run", json={',
        "locust -f locustfile.py --host=http://localhost:8000",
    ),
}


def test_orchestrator_agent_boundary_docs_use_current_ownership_contract() -> None:
    for relpath, expected_substrings in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in expected_substrings:
            assert needle in text, f"Missing expected text in {relpath}: {needle}"


def test_orchestrator_agent_boundary_docs_do_not_reintroduce_stale_contracts() -> None:
    for relpath, forbidden_substrings in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, f"Found stale text in {relpath}: {needle}"


def test_legacy_web_ui_share_token_modules_stay_retired() -> None:
    retired_paths = (
        "apps/web-ui/src/lib/server/share-token.ts",
        "apps/web-ui/src/lib/server/share-token-revocation.ts",
        "apps/web-ui/src/lib/server/share-security.ts",
    )
    for relpath in retired_paths:
        assert not (
            REPO_ROOT / relpath
        ).exists(), f"Retired file reintroduced: {relpath}"


def test_retired_agent_http_copilot_surface_stays_removed() -> None:
    retired_test = REPO_ROOT / "tests/services/agent/test_copilot_api.py"
    assert not retired_test.exists(), "Retired Agent HTTP copilot test reintroduced"
