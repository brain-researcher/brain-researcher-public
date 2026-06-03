# Spec: Tool Selection Explainability + WS Contract

## Summary
Unify tool discovery on KG, expose explainable candidate lists to UI and `/agent/plan`, and formalize API/WS contracts across the active split-service surfaces. The canonical runtime path is Web UI + Agent + Orchestrator + BR-KG. Improve pipeline/dashboard WS behavior, add WS protocol v1, and make failures explainable (blocked/degraded). Add structured telemetry to support future ML selection.

## Goals
- Canonical HTTP routes: `/api/{service}/v1/*` (orchestrator under `/api/orchestrator/v1/*`).
- Canonical WS routes: `/ws/{service}/*` (no path versioning; payload versioned).
- KG is the only discovery source; runtime resolve/availability overlays determine executability.
- Return explainable candidates (full + top-K) in plan/run responses and expose in UI.
- WS protocol v1 with hello/subscribe/ack, snapshot + delta, resume checkpoints.
- Clear transport vs data health states; pipeline page falls back to polling when WS fails.
- Strong tenant isolation + owner visibility; dev can relax.
- Telemetry for tool selection events to train ML model later.

## Non-Goals (explicit)
- Full ML selector replacing rules (only framework + telemetry, rules remain default).
- Cross-tenant ACL/sharing.
- Reintroducing a standalone single-port front door as the canonical runtime surface.
- WS path versioning (no `/ws/.../v2` for now).
- Major dashboard redesign (only semantics + fallback behavior).

## Canonical Routing
### Production (edge reverse proxy + service mounts are canonical)
- HTTP: `/api/{service}/v1/*`
  - Agent: `/api/agent/v1/*`
  - Orchestrator: `/api/orchestrator/v1/*`
  - KG: `/api/kg/v1/*` (as applicable)
- WS: `/ws/{service}/*`
  - Orchestrator: `/ws/orchestrator/...`

### Dev split-services
- Web UI runs on 3000 and owns the public browser-facing `/api/*` surface.
- Agent runs on 8000.
- Orchestrator runs on 3001.
- BR-KG runs on 5000.
- Compatibility shims may still exist, but they are not part of the canonical
  runtime contract.

### Health and metrics
- External:
  - `/api/health`: Web UI/browser-facing health aggregation when needed.
  - `/metrics`: service-specific metrics, restricted access.
- Per-service:
  - `/api/{service}/v1/health`
  - `/api/{service}/v1/metrics`
- Access:
  - `/health` public minimal; `/health?detail=1` or auth-protected detailed.
  - `/metrics` ops/admin only, no public access.

## Migration / Compatibility
- One minor release (>=45 days) compatibility window.
- HTTP aliases:
  - `/orchestrator/*` -> `/api/orchestrator/v1/*` (rewrite, not redirect).
- WS aliases:
  - Legacy `/ws/*` supported with deprecation notice in messages.
- Deprecation:
  - HTTP: `Deprecation: true`, `Sunset: <date>`, `Link: <new>; rel="successor-version"`.
  - WS: `type:"deprecation_notice"` message.

## Authentication and Isolation
- Prod: WS and HTTP must be authenticated.
- Browser WS uses NextAuth cookie (same-host required). No tokens in URL.
- The browser-facing layer parses cookie/session -> `user_id`, `tenant_id`, then
  forwards identity to backend services.
- Missing tenant:
  - dev -> `tenant_id=default`.
  - prod -> 403 (`missing_tenant`).
- Strong tenant isolation:
  - All job/run data and WS streams filtered by tenant_id.
  - Default visibility: private to owner; optional tenant-visible.

## Trust Boundary (Browser-facing layer -> Backend)
- HMAC signature required on injected headers.
- Headers: `X-User-Id`, `X-Tenant-Id`, `X-Gateway-Timestamp`, `X-Gateway-Signature`.
- Signature: `v1=base64url(HMAC_SHA256(secret, canonical_string))`
- Canonical string includes timestamp, method, path+query, user_id, tenant_id, body_sha256 (if JSON).
- Timestamp window: 60s (±30s).

## Roles / Permissions (minimum)
- Roles: owner, member, admin (tenant), ops (platform).
- Run details: owner/member/admin/ops (tenant scoped).
- candidates_full: owner/member/admin/ops (member defaults to summary in UI).
- Explain export / share: owner/admin/ops.
- Bind creds: owner (personal) / admin (tenant) / ops (platform). Member can request only.
- Approve creds: admin/ops.
- Sensitive fields (logs_full/stack/path): owner/admin/ops (still redacted).
- /metrics: ops (admin optional), not public.
- policy override: member/owner can request run.override (clamped), admin/ops can change tenant policy.

## WS Protocol v1
### Handshake flow
1) Server -> `hello` (aka `connection_info`):
   - `protocol_version`, `server_time`, `heartbeat_interval_ms`, `max_message_bytes`, `supports_resume`.
2) Client -> `subscribe`:
   - `{type:"subscribe", request_id, streams:[{stream:"job", job_id, channels, resume_checkpoint_id?, limits?}]}`
3) Server -> `subscribe_ack`:
   - `{type:"subscribe_ack", request_id, stream_id, applied_subscriptions, applied_limits, last_checkpoint_id, resume_status}`
4) Server -> `pipeline_snapshot` (always), then delta replay if resume ok.

### Messages
Common envelope:
```
{ "stream_id": "job:job_123", "checkpoint_id": 124, "type": "graph_patch", "payload": {...} }
```
Types:
- `pipeline_snapshot`: payload = graph snapshot (see schema)
- `graph_patch`: node/edge add/update/remove (JSON Merge Patch semantics)
- `log_append`, `timeline_append`, `artifact_append`
- `resync_required` (gap/expired/stream_changed)

### Resume
- Job-level only. Dashboard is snapshot-only (no resume).
- Ring buffer per job: N events (200-500) or last 5 minutes, plus optional max bytes.
- If resume gap: send snapshot then `resync_required`.

### Close codes
- Use standard codes and send error message before close.
- 1008 UNAUTHORIZED/FORBIDDEN/INCOMPATIBLE_VERSION
- 1003 UNSUPPORTED_PROTOCOL
- 1007 INVALID_MESSAGE
- 1011 INTERNAL_ERROR
- 1013 TRY_AGAIN_LATER
- 1000 normal

### Backpressure
- Graph patches merge (last-write-wins).
- Logs/resources may drop with `dropped_notice`.
- If overload persists, send snapshot + resync_required then close (1013).

## Pipeline Graph Schema (v1)
Used by `GET /api/orchestrator/v1/jobs/{id}/graph` and `pipeline_snapshot`.
```
{
  "schema_version": "1.0",
  "job_id": "job_123",
  "stream_id": "run_ulid_...",
  "plan": {"plan_id": "plan_abc", "version": 1},
  "owner": {"user_id": "u_1", "tenant_id": "t_default"},
  "generated_at": "2026-01-03T12:34:56Z",
  "last_checkpoint_id": 123,
  "nodes": [ ... ],
  "edges": [ ... ]
}
```
Node required: `id, kind, type, label, status`. Optional: `progress, timing, resources, error, meta, artifacts`.

## Tool Discovery and Selection
### Discovery
- KG is the only discovery source.
- Resolve maps `kg_id -> registry_tool_id`.
- Availability overlay uses runtime registry/health/policy.

### Selection timing
- Plan time: choose primary + alternates (same constraints).
- Run start: resolve + preflight; lock concrete tool_id@version/backend.
- Step start: allow fallback within alternates if primary unavailable.
 - Record run policy context: policy_bundle_id/checksum, catalog_version/sha, selection_engine_version.
 - Optional dev drift: allow_policy_drift=true only in dev; emit policy_changed event with from/to bundle and affected steps.

### Blocked results
- HTTP 200 with `type="blocked_result"` and `status="blocked"`.
- `blocking_reasons[]` (enum) + detail.
- `candidates_full[]` with `available=false` and reasons.
 - If overrides requested: return `requested_overrides`, `applied_overrides`, `rejected_overrides[]` with reason_code and detail.

### Reason codes
Structured reasons with `{code, summary, delta, severity, evidence}`.
Minimal enums include:
- Matching: INTENT_MATCH, TAG_MATCH, SYNONYM_MATCH, DESCRIPTION_MATCH, MODALITY_MATCH, IO_COMPATIBLE, PARAM_SCHEMA_COMPATIBLE
- Availability: AVAILABLE, RESOLVE_FAILED, DEPENDENCY_MISSING, TOOL_NOT_INSTALLED, CONFIG_MISSING, RESOURCE_REQUIRED, RESOURCE_UNAVAILABLE
- Policy/permission: POLICY_ALLOWED, POLICY_BLOCKED, PERMISSION_DENIED, VERSION_MISMATCH
- Quality/cost: RELIABILITY_BONUS, RECENT_FAILURE_PENALTY, LATENCY_PENALTY, COST_PENALTY, EXTERNAL_NET_PENALTY

## Candidates in API
- Top-level: `candidates_full[]` with full trace, bounded by `max_total` (default 200).
- Per-step: `candidates_top[]` (default N=15), unavailable max M=5.
- Query param `?candidates=full|summary|none`.
- Pagination: `/api/orchestrator/v1/runs/{run_id}/candidates?cursor=...&step_id=...&level=...`.

## Pipeline identity & run selection
- pipelineId = stable pipeline definition; jobId/runId = execution instance (primary key).
- URLs:
  - `/pipelines/{pipelineId}`: show pipeline overview and current run selector.
  - `/pipelines/{pipelineId}/runs/{jobId}`: pinned run view (shareable).
- Default current run selection (tenant+user scoped):
  1) latest running/queued/claimed (by started_at/created_at desc)
  2) latest completed/failed/cancelled (by finished_at desc)
  3) none -> empty state with Run Pipeline CTA
- Auto-follow current run by default; manual selection switches to fixed mode with “Resume auto-follow”.

## Caching and Fallback
- L1 KG results: TTL 20 min. Key includes tenant, query_hash, planner_mode, catalog_version.
- L2 resolve/availability: TTL 2 min. Key includes policy_version/tenant.
- Event invalidation: registry/policy/tenant changes clear L2; failures can mark tool unavailable (2-5 min).

Fallback on KG failure:
- Retry budget <= 3-4s (connect 0.5s, read 1.5-2s, 2 retries with jitter).
- Use local catalog snapshot (`configs/tools_catalog_merged.json`) up to 24h staleness (hard 7d).
- If no cache, use default minimal toolset with degraded metadata.

Metadata additions: `status`, `source`, `errors`, `catalog_version`, `catalog_sha256`, `cache_age_seconds`.

## Tool version/variant resolution
- If user pins version/features, must satisfy or mark unavailable (include available_versions).
- Default (no pin):
  - Exclude deprecated; experimental only if policy allows.
  - Choose highest stable/supported available in runtime.
  - Prefer compatible version within same major/minor when schema is compatible.
- Multi-backend: prefer stable backend; local/container over remote unless explicitly requested.

## Policy Storage
- KG holds immutable `ToolPolicyBundle` + `ToolPolicyRule` nodes; pointer selects active bundle.
- Bundle immutable; pointer change = rollback.
- Run pin: `policy_bundle_id`, `policy_version`, `policy_checksum`, `policy_pointer`.

## Overrides (user relax & retry)
- Default: per-run override only; optional “remember” writes user profile.
- Response returns clamp results: requested/applied/rejected overrides with reason_code.
- Policy clamp enforced before execution; rejected overrides do not apply.

## Selection Engine
- Default rules engine, `selection_engine_version=rules_v1`.
- ML engine later; routing by global flag + tenant/user + task type.
- ML timeout 300ms (max 500ms) then fallback to rules.
- Response includes `selection_engine_version` and `selection_fallback_from` if fallback occurs.

## Credential handling
- Dev: auto-inject via managed credential pool; if missing -> CONFIG_MISSING.
- Prod: auto-inject only if tenant binding exists and policy allows; otherwise blocked with suggested actions.
- Credential requests:
  - owner/admin can bind; member can request.
  - request_id stored on run/step; default 24h expiry with notifications.
  - approval can optionally auto-retry (tenant/policy setting).

## Telemetry (Training Data)
### tool_selection_event (per step / attempt)
- Inputs (required): tenant‑salted `query_hash`, intent/task_type, constraints (structured), context summary (modality/input_kinds), tenant_id_hash, user_id_hash.
- Repro/trace (required): selection_engine_version, policy_bundle_id+checksum, catalog_version+sha, planner_mode, plan_id+step_id.
- Candidate features (top‑K=20 + hard negatives): tool_id@version@backend, semantic_score, availability+reason_code, reliability_score, cost features (bucketed), policy penalties, final_score, rank, is_filtered_out.
- Outcome (required): selected_tool_id, selected_from, outcome, failure_reason_code, runtime_duration_ms, attempt_index, user_cancelled.
- Aggregates: filtered_counts_by_reason, filtered_sample[] (max 3–5 per reason).

### Storage
- DB: default 90 days (configurable 30/90/180), indexed (ts, tenant_id, task_type, tool_id, outcome).
- Object storage: Parquet daily partitions (dt, tenant, task). JSONL fallback if Parquet unavailable.
- Default export window: 90 days.

## Explain Export
- Endpoint: `GET /api/orchestrator/v1/runs/{run_id}/explain/export?format=json|md&level=summary|full`
- Default redaction; `include_sensitive=1` only for owner/admin/ops.
- Share links: `POST /api/orchestrator/v1/runs/{run_id}/explain/share` -> `share_id`.
- Share snapshot stored (object store preferred, fallback run_dir). TTL 15-60 min, with cleanup.

## Redaction (prod default)
- Always avoid absolute paths, tokens, full stacks.
- Owner/admin/ops can request more detail (still redacted for secrets).
- Member sees summary only (messages truncated, no params, no full logs).

## Audit events (DB)
- explain_export_generated / explain_share_created / explain_share_accessed
- credential_request_created / approved / expired
- policy_override_requested / applied / clamped
- authz_denied (security)
- Retention default 90 days (configurable 30/90/180); store hashed IP/UA for share access.

## UI/UX Changes
- Pipeline page:
  - Default auto-follow current run; manual selection switches to fixed mode.
  - Status shows Live (WS) / Polling (degraded) / Disconnected.
  - Polling fallback for key data only (10s running/queued; 30-60s completed).
- Candidates UI:
  - Plan debug drawer shows top-K summary.
  - Tool panel shows full candidates with filters.
  - Unavailable grouped and collapsed by default.

## Implementation Plan (high-level)
1) Define canonical routes across the active split-service surfaces (HTTP + WS), add alias rewrites.
2) Implement WS protocol v1 with dual-protocol compatibility.
3) Add pipeline graph endpoint and snapshot + delta schema.
4) Implement candidate structures and blocked_result payload.
5) Implement policy bundle pinning and run metadata fields.
6) Add tool_selection_event telemetry and export pipeline.
7) Update UI components to display new candidates and status semantics.
8) Add Playwright smoke check for WS banner and pipeline.

## Testing
- Route alias tests: old -> new.
- WS handshake: hello/subscribe/ack/snapshot.
- Resume: replay within window; snapshot+resync when gap.
- Candidate payload shape + blocked_result.
- UI: banner state and polling fallback.
- Playwright `launch_services_clean.sh check`.
