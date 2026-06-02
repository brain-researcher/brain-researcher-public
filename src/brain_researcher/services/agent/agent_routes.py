"""/agent/* Blueprint-less routes for the BR-KG agent web service.

Carved out of ``agent/web_service.py``: the 6 plain ``@app.route('/agent/...')``
handlers (studio plan, run_info, run_plan, plan export to nipype/workflow, kg
tools debug). Registration is via the explicit ``register(app)`` function
(called by ``web_service`` on every import, so the test suite's per-test app
reimport re-wires correctly). This module imports its third-party / type / prior
-slice deps directly; the web_service helpers it still needs are imported back
lazily inside each handler. (``agent_plan_contract`` is intentionally NOT here:
its ``@ttl_cache`` + ``@app.route`` decorator stack needs separate handling.)
"""

from __future__ import annotations

import os
import time
from typing import Any

from flask import Response, jsonify, request, stream_with_context
from pydantic import ValidationError

from brain_researcher.services.agent.plan_execution import (
    _execute_plan_with_streaming,
    _proxy_plan_stream,
    _submit_plan_job,
)
from brain_researcher.services.agent.planner.catalog_loader import search_by_intent
from brain_researcher.services.agent.planner.kg_bridge import (
    get_family_stats_for_operation,
    get_preferred_families_for_pipeline,
)
from brain_researcher.services.agent.planner.models import RunPlanRequest
from brain_researcher.services.agent.studio_planner import build_studio_plan
from brain_researcher.services.agent.tool_candidate_service import (
    generate_tool_candidates,
)
from brain_researcher.services.agent.tool_context import _get_contract_tool_retriever
from brain_researcher.services.shared.job_store_registry import (
    peek_initialized_job_store,
)


def agent_studio_plan():
    """Studio typed planner endpoint driven by deterministic candidate scaffolds."""
    import secrets as _secrets

    from brain_researcher.services.agent.web_service import (
        _metrics,
        _plan_surface_allowset,
        _studio_plan_allowlist_mode,
        _studio_plan_filter_candidates,
        _studio_plan_normalize_ops,
        logger,
    )

    start_time = time.perf_counter()
    try:
        payload = request.get_json(force=True) or {}
    except Exception as exc:
        logger.warning("Invalid JSON for /agent/studio/plan: %s", exc)
        return jsonify({"error": "invalid_json"}), 400

    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_json"}), 400

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return (
            jsonify({"error": "missing_prompt", "message": "prompt is required"}),
            400,
        )

    notebook_context: dict[str, Any] = payload.get("notebook_context") or {}
    thread_id: str | None = payload.get("thread_id")
    session_id: str | None = payload.get("session_id")
    top_k: int = min(max(int(payload.get("top_k") or 5), 1), 12)
    metadata: dict[str, Any] = payload.get("metadata") or {}
    allowlist_mode = _studio_plan_allowlist_mode(payload)
    plan_allowset = _plan_surface_allowset(allowlist_mode)

    # Build preflight context
    preflight_ctx: dict[str, Any] = {
        "runtime_surface": "studio",
    }
    if thread_id:
        preflight_ctx["thread_id"] = thread_id
    if session_id:
        preflight_ctx["session_id"] = session_id
    if allowlist_mode:
        preflight_ctx["allowlist_mode"] = allowlist_mode
    preflight_ctx.update({k: v for k, v in metadata.items() if k not in preflight_ctx})

    # Retrieve real tool candidates via the shared retrieval stack
    bundle = None
    tool_candidates: list[dict[str, Any]] = []
    try:
        bundle = generate_tool_candidates(
            prompt,
            ctx=preflight_ctx,
            tool_retriever=_get_contract_tool_retriever(),
            top_k=top_k,
        )
        tool_candidates = _studio_plan_filter_candidates(
            list(bundle.tool_candidates or []),
            plan_allowset,
        )
    except Exception as exc:
        logger.debug("Studio plan candidate retrieval failed (continuing): %s", exc)
    plan_id = f"sp_{_secrets.token_hex(8)}"
    deterministic_plan = build_studio_plan(
        prompt=prompt,
        notebook_context=notebook_context,
        tool_candidates=tool_candidates,
        query_understanding=getattr(bundle, "query_understanding", None),
        resolution_state=getattr(bundle, "resolution_state", None),
        tool_candidate_diagnostics=getattr(bundle, "tool_candidate_diagnostics", None),
    )
    assistant_message = (
        str((deterministic_plan or {}).get("assistant_message") or "").strip()
        or "Updated the notebook plan."
    )
    raw_ops = [
        op
        for op in list((deterministic_plan or {}).get("ops") or [])
        if isinstance(op, dict)
    ]
    normalized_ops, allowlist_error = _studio_plan_normalize_ops(
        raw_ops,
        plan_allowset,
        plan_id=plan_id,
    )
    if allowlist_error is not None:
        return allowlist_error

    _metrics.record(
        "studio_plan_duration_ms", (time.perf_counter() - start_time) * 1000
    )
    return (
        jsonify(
            {
                "plan_id": plan_id,
                "assistant_message": assistant_message,
                "ops": normalized_ops,
                "source": "agent_typed",
                "tool_candidates": [
                    {
                        "tool_id": c.get("tool_id"),
                        "source": c.get("source"),
                        "score": c.get("score"),
                    }
                    for c in tool_candidates[:5]
                ],
            }
        ),
        200,
    )


def agent_run_info():
    """Lightweight Run/Plan lookup (best-effort; Neo4j optional)."""
    from brain_researcher.services.agent.web_service import (
        _get_neo4j_driver,
        logger,
    )

    run_id = request.args.get("run_id")
    if not run_id:
        return jsonify({"error": "run_id is required"}), 400

    driver = _get_neo4j_driver()
    if driver is None:
        return jsonify({"error": "Neo4j unavailable"}), 503

    cypher = """
    MATCH (r:Run {id:$run_id})
    OPTIONAL MATCH (p:Plan)-[:HAS_RUN]->(r)
    OPTIONAL MATCH (r)-[:HAS_EVIDENCE]->(e:ToolEvidence)
    OPTIONAL MATCH (t:Tool)-[:HAS_EVIDENCE]->(e)
    OPTIONAL MATCH (tv:ToolVersion)-[:USED_IN_RUN]->(r)
    OPTIONAL MATCH (r)-[:USED_DATASET]->(d:Dataset)
    RETURN r AS run,
           p.id AS plan_id,
           collect(DISTINCT coalesce(t.tool_id, t.id)) AS tools,
           collect(DISTINCT coalesce(tv.version_id, tv.id)) AS tool_versions,
           collect(DISTINCT coalesce(d.dataset_id, d.id)) AS datasets
    LIMIT 1
    """
    try:
        with driver.session() as session:
            row = session.run(cypher, run_id=run_id).single()
            if not row:
                return jsonify({"error": "run_id not found"}), 404
            run_props = row.get("run") or {}
            payload = {
                "run_id": run_id,
                "plan_id": row.get("plan_id") or run_props.get("plan_id"),
                "status": run_props.get("last_state"),
                "latency_ms": run_props.get("last_latency_ms"),
                "dataset_id": run_props.get("dataset_id"),
                "tools": [t for t in row.get("tools") or [] if t],
                "tool_versions": [tv for tv in row.get("tool_versions") or [] if tv],
                "datasets": [ds for ds in row.get("datasets") or [] if ds],
                "updated_at": run_props.get("updated_at"),
            }
            return jsonify(payload), 200
    except Exception as exc:
        logger.debug("run_info lookup failed for %s: %s", run_id, exc)
        return jsonify({"error": "lookup_failed", "detail": str(exc)}), 500


def agent_run_plan_contract():
    """Submit plan execution to worker queue and return job info.

    PR-4 Phase 4 (Issue #1): No longer executes tools in Flask thread.
    Instead, creates a job that workers will claim and execute asynchronously.

    Clients should stream from /jobs/{job_id}/stream for real-time events.
    """
    from brain_researcher.services.agent.web_service import (
        _PLAN_CACHE,
        PlanAllowlistError,
        _allowlist_violation_response,
        _collect_disallowed_tools_from_payload,
        logger,
    )

    try:
        payload = request.get_json(force=True) or {}
    except Exception as exc:  # pragma: no cover
        logger.warning("Invalid JSON payload for /agent/run_plan: %s", exc)
        payload = {}

    try:
        run_request = RunPlanRequest.model_validate(payload)
    except ValidationError as exc:
        return (
            jsonify({"error": "invalid_run_plan_request", "details": exc.errors()}),
            422,
        )
    provided_plan_payload = (
        run_request.plan.model_dump(mode="json")
        if run_request.plan is not None
        else None
    )

    if not run_request.por_token:
        return (
            jsonify(
                {
                    "error": "missing_por_token",
                    "message": "por_token is required to execute a plan",
                }
            ),
            400,
        )

    # Security: Validate POR token signature when configured/enforced.
    try:
        from brain_researcher.services.shared.planner.por_tokens import (
            verify_por_token_from_env,
        )

        claims = verify_por_token_from_env(
            token=run_request.por_token,
            plan_id=run_request.plan_id,
            version=run_request.version,
        )
        if claims is None:
            logger.warning(
                "POR token signature validation disabled (BR_POR_TOKEN_SECRET not set)"
            )
    except RuntimeError as exc:
        logger.error("POR token enforcement is enabled but secret is missing: %s", exc)
        return jsonify({"error": "por_token_secret_required"}), 500
    except ValueError as exc:
        return (
            jsonify({"error": "invalid_por_token", "message": str(exc)}),
            403,
        )

    # PR-4 Phase 4: Submit to worker instead of executing in Flask
    wants_sse = (
        "text/event-stream" in (request.headers.get("Accept", ""))
        or request.args.get("stream") == "1"
    )
    if wants_sse:
        # If the registered job store is unavailable in this process,
        # fall back to direct streaming execution so /agent/run_plan remains usable.
        _job_store = peek_initialized_job_store()
        if _job_store is None:
            cached_plan = provided_plan_payload or _PLAN_CACHE.get(run_request.plan_id)
            if not cached_plan:
                return (
                    jsonify(
                        {
                            "error": "plan_not_found",
                            "message": f"Plan {run_request.plan_id} not found in cache. Must POST /agent/plan first.",
                        }
                    ),
                    404,
                )
            disallowed = _collect_disallowed_tools_from_payload(cached_plan)
            if disallowed:
                return _allowlist_violation_response(
                    "Plan contains tools blocked by the environment allowlist",
                    disallowed=disallowed,
                    plan_id=run_request.plan_id,
                    denied_tool_id=next(iter(disallowed or []), None),
                    denial_stage="run_plan_submission",
                    denial_reason_code="plan_contains_disallowed_tools",
                )
            logger.warning(
                "Job store not initialized; streaming plan %s directly in request thread",
                run_request.plan_id,
            )
            return Response(
                stream_with_context(_execute_plan_with_streaming(run_request)),
                mimetype="text/event-stream",
            )
    try:
        job_info = _submit_plan_job(
            plan_id=run_request.plan_id,
            version=run_request.version,
            por_token=run_request.por_token,
            plan_payload=provided_plan_payload,
        )
        if wants_sse:
            return _proxy_plan_stream(job_info)
        return (
            jsonify(
                {
                    "message": "Plan execution submitted to worker queue",
                    **job_info,
                }
            ),
            202,
        )  # 202 Accepted
    except PlanAllowlistError as exc:
        return _allowlist_violation_response(
            "Plan contains tools blocked by the environment allowlist",
            disallowed=exc.disallowed,
            plan_id=exc.plan_id,
            denied_tool_id=next(iter(exc.disallowed or []), None),
            denial_stage="run_plan_submission",
            denial_reason_code="plan_contains_disallowed_tools",
        )
    except ValueError as exc:
        return (
            jsonify(
                {
                    "error": "plan_not_found",
                    "message": str(exc),
                }
            ),
            404,
        )
    except Exception as exc:
        logger.error(f"Failed to submit plan execution job: {exc}", exc_info=True)
        return (
            jsonify(
                {
                    "error": "job_submission_failed",
                    "message": str(exc),
                }
            ),
            500,
        )


def export_plan_to_nipype_endpoint():
    """Export a Plan DAG as a Nipype workflow script.

    Request body:
    {
        "plan_id": "optional-if-plan-provided",
        "plan": { /* optional full Plan object */ },
        "options": {
            "plugin": "MultiProc",
            "plugin_args": {"n_procs": 4},
            "output_dir": "/optional/custom/path",
            "strict": false
        }
    }

    Response (success):
    {
        "plan_id": "...",
        "workflow_file": "/workflows/<plan_id>/workflow.py",
        "config_file": "/workflows/<plan_id>/nipype.cfg",
        "original_plan_file": "/workflows/<plan_id>/plan.json",
        "run_command": "python /workflows/<plan_id>/workflow.py",
        "skipped_steps": [...],
        "warnings": [...],
        "graph_generated": false,
        "graph_file": "/.../graph.png"
    }
    """
    from brain_researcher.services.agent.web_service import (
        _PLAN_CACHE,
        NipypeExportRequest,
        logger,
    )

    try:
        payload = request.get_json(force=True) or {}
    except Exception as exc:
        logger.warning("Invalid JSON payload for /agent/plan/export/nipype: %s", exc)
        return jsonify({"error": "invalid_json"}), 400

    try:
        export_request = NipypeExportRequest.model_validate(payload)
    except ValidationError as exc:
        return (
            jsonify({"error": "invalid_export_request", "details": exc.errors()}),
            422,
        )

    # Get Plan object - either from payload or from cache
    plan_dict = None
    plan_id = None

    if export_request.plan:
        plan_dict = export_request.plan
        plan_id = plan_dict.get("plan_id")
    elif export_request.plan_id:
        plan_id = export_request.plan_id
        cached_plan = _PLAN_CACHE.get(plan_id)
        if not cached_plan:
            return (
                jsonify(
                    {
                        "error": "plan_not_found",
                        "message": f"Plan {plan_id} not found in cache. Provide plan payload or POST /agent/plan first.",
                    }
                ),
                404,
            )
        plan_dict = cached_plan
    else:
        return (
            jsonify(
                {
                    "error": "missing_plan",
                    "message": "Either plan_id or plan payload is required",
                }
            ),
            400,
        )

    # Parse options
    options = export_request.options or {}
    plugin = options.get("plugin", "MultiProc")
    plugin_args = options.get("plugin_args", {})
    strict = options.get("strict", False)

    # Determine output directory
    output_dir = options.get("output_dir")
    if not output_dir:
        # Default to /tmp/workflows or configurable base
        base_workflow_dir = os.getenv("BR_WORKFLOW_OUTPUT_DIR", "/tmp/workflows")
        output_dir = base_workflow_dir

    try:
        # Import and convert plan
        from brain_researcher.services.agent.adapters.plan_to_nipype import (
            export_plan_to_nipype,
        )
        from brain_researcher.services.shared.planner.models import Plan

        # Validate and create Plan object
        plan = Plan.model_validate(plan_dict)

        # Export to Nipype
        result = export_plan_to_nipype(
            plan=plan,
            output_dir=output_dir,
            plugin=plugin,
            plugin_args=plugin_args,
            strict=strict,
        )

        if result.get("status") == "error":
            return jsonify(result), 500

        return jsonify(result), 200

    except ValidationError as exc:
        return (
            jsonify(
                {
                    "error": "invalid_plan",
                    "details": exc.errors(),
                }
            ),
            422,
        )
    except ValueError as exc:
        # Strict mode violation
        return (
            jsonify(
                {
                    "error": "export_failed",
                    "message": str(exc),
                }
            ),
            400,
        )
    except Exception as exc:
        logger.exception(f"Nipype export failed: {exc}")
        return (
            jsonify(
                {
                    "error": "export_failed",
                    "message": str(exc),
                }
            ),
            500,
        )


def export_plan_to_workflow():
    """Export a Plan DAG as a workflow script (Nipype or Pydra).

    Request body:
    {
        "plan_id": "optional-if-plan-provided",
        "plan": { /* optional full Plan object */ },
        "format": "nipype" | "pydra",
        "options": {
            "plugin": "MultiProc",  // Nipype only
            "plugin_args": {"n_procs": 4},  // Nipype only
            "output_dir": "/optional/custom/path",
            "strict": false
        }
    }

    Response (success):
    {
        "plan_id": "...",
        "format": "nipype" | "pydra",
        "workflow_file": "/workflows/<plan_id>/workflow.py",
        "original_plan_file": "/workflows/<plan_id>/plan.json",
        "run_command": "python /workflows/<plan_id>/workflow.py",
        "skipped_steps": [...],
        "warnings": [...]
    }
    """
    from brain_researcher.services.agent.web_service import (
        _PLAN_CACHE,
        WorkflowExportRequest,
        logger,
    )

    try:
        payload = request.get_json(force=True) or {}
    except Exception as exc:
        logger.warning("Invalid JSON payload for /agent/plan/export: %s", exc)
        return jsonify({"error": "invalid_json"}), 400

    try:
        export_request = WorkflowExportRequest.model_validate(payload)
    except ValidationError as exc:
        return (
            jsonify({"error": "invalid_export_request", "details": exc.errors()}),
            422,
        )

    # Validate format
    export_format = export_request.format.lower()
    if export_format not in ("nipype", "pydra"):
        return (
            jsonify(
                {
                    "error": "invalid_format",
                    "message": f"Unsupported format '{export_format}'. Use 'nipype' or 'pydra'.",
                }
            ),
            400,
        )

    # Get Plan object - either from payload or from cache
    plan_dict = None
    plan_id = None

    if export_request.plan:
        plan_dict = export_request.plan
        plan_id = plan_dict.get("plan_id")
    elif export_request.plan_id:
        plan_id = export_request.plan_id
        cached_plan = _PLAN_CACHE.get(plan_id)
        if not cached_plan:
            return (
                jsonify(
                    {
                        "error": "plan_not_found",
                        "message": f"Plan {plan_id} not found in cache. Provide plan payload or POST /agent/plan first.",
                    }
                ),
                404,
            )
        plan_dict = cached_plan
    else:
        return (
            jsonify(
                {
                    "error": "missing_plan",
                    "message": "Either plan_id or plan payload is required",
                }
            ),
            400,
        )

    # Parse options
    options = export_request.options or {}
    strict = options.get("strict", False)

    # Determine output directory
    output_dir = options.get("output_dir")
    if not output_dir:
        base_workflow_dir = os.getenv("BR_WORKFLOW_OUTPUT_DIR", "/tmp/workflows")
        output_dir = base_workflow_dir

    try:
        from brain_researcher.services.shared.planner.models import Plan

        # Validate and create Plan object
        plan = Plan.model_validate(plan_dict)

        if export_format == "nipype":
            # Nipype export
            from brain_researcher.services.agent.adapters.plan_to_nipype import (
                export_plan_to_nipype,
            )

            plugin = options.get("plugin", "MultiProc")
            plugin_args = options.get("plugin_args", {})

            result = export_plan_to_nipype(
                plan=plan,
                output_dir=output_dir,
                plugin=plugin,
                plugin_args=plugin_args,
                strict=strict,
            )
        else:
            # Pydra export
            from brain_researcher.services.agent.adapters.plan_to_pydra import (
                export_plan_to_pydra,
            )

            result = export_plan_to_pydra(
                plan=plan,
                output_dir=output_dir,
                strict=strict,
            )

        if result.get("status") == "error":
            return jsonify(result), 500

        return jsonify(result), 200

    except ValidationError as exc:
        return (
            jsonify(
                {
                    "error": "invalid_plan",
                    "details": exc.errors(),
                }
            ),
            422,
        )
    except ValueError as exc:
        # Strict mode violation
        return (
            jsonify(
                {
                    "error": "export_failed",
                    "message": str(exc),
                }
            ),
            400,
        )
    except Exception as exc:
        logger.exception(f"Workflow export failed: {exc}")
        return (
            jsonify(
                {
                    "error": "export_failed",
                    "message": str(exc),
                }
            ),
            500,
        )


def debug_kg_tools():
    """
    Return KG hint details for a given intent (and optional pipeline).

    Query params:
      - intent (required): operation/intent id, e.g., dmri_tractography
      - pipeline (optional): pipeline template id, e.g., pipeline.tractography
      - per_family (optional int): number of exemplar tools to return per family (default: 5)
    """
    from brain_researcher.services.agent.web_service import (
        _infer_family_id,
        _tool_summary,
        logger,
    )

    intent_id = (request.args.get("intent") or "").strip()
    if not intent_id:
        return (
            jsonify(
                {
                    "error": "missing_intent",
                    "message": "query parameter 'intent' is required",
                }
            ),
            400,
        )

    pipeline_id = (request.args.get("pipeline") or "").strip() or None
    try:
        per_family = int(request.args.get("per_family", 5))
    except Exception:
        return (
            jsonify(
                {
                    "error": "invalid_per_family",
                    "message": "per_family must be an integer",
                }
            ),
            400,
        )
    per_family = max(1, min(per_family, 50))

    tools_for_intent = search_by_intent(intent_id)
    tools_by_family: dict[str, list[Any]] = {}
    for tool in tools_for_intent:
        fam = _infer_family_id(getattr(tool, "package", "") or "")
        tools_by_family.setdefault(fam, []).append(tool)

    # Stable ordering: NiWrap first, then id
    for fam_tools in tools_by_family.values():
        fam_tools.sort(
            key=lambda t: (
                not (
                    t.runtime_kind == "container"
                    and bool(getattr(t, "entrypoint", None))
                ),
                t.id,
            )
        )

    # KG hints (graceful fallback when Neo4j not configured)
    try:
        family_counts = (
            {  # noqa: C416  (verbatim from web_service; behavior-neutral move)
                fid: cnt for fid, cnt in get_family_stats_for_operation(intent_id)
            }
        )
        preferred_families = (
            get_preferred_families_for_pipeline(pipeline_id) if pipeline_id else []
        )
        kg_hints_enabled = bool(family_counts or preferred_families)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("KG hint lookup failed: %s", exc)
        family_counts = {}
        preferred_families = []
        kg_hints_enabled = False

    family_ids = (
        set(tools_by_family.keys())
        | set(family_counts.keys())
        | set(preferred_families)
    )
    families_payload: list[dict[str, Any]] = []
    for fam_id in sorted(family_ids):
        tools_list = tools_by_family.get(fam_id, [])
        families_payload.append(
            {
                "family": fam_id,
                "preferred": fam_id in preferred_families,
                "kg_tool_count": family_counts.get(fam_id),
                "runtime_kinds": (
                    sorted({t.runtime_kind for t in tools_list}) if tools_list else []
                ),
                "examples": [_tool_summary(t) for t in tools_list[:per_family]],
                "example_count": len(tools_list),
            }
        )

    return jsonify(
        {
            "intent": intent_id,
            "pipeline": pipeline_id,
            "kg_hints_enabled": kg_hints_enabled,
            "families": families_payload,
            "counts": {
                "tools_for_intent": len(tools_for_intent),
                "families_with_tools": len(tools_by_family),
                "families_total": len(family_ids),
            },
        }
    )


def register(app):
    """Register the /agent/* routes on the Flask app (called by app.py each import)."""
    app.add_url_rule(
        "/agent/studio/plan", methods=["POST"], view_func=agent_studio_plan
    )
    app.add_url_rule("/agent/run_info", methods=["GET"], view_func=agent_run_info)
    app.add_url_rule(
        "/agent/run_plan", methods=["POST"], view_func=agent_run_plan_contract
    )
    app.add_url_rule(
        "/agent/plan/export/nipype",
        methods=["POST"],
        view_func=export_plan_to_nipype_endpoint,
    )
    app.add_url_rule(
        "/agent/plan/export", methods=["POST"], view_func=export_plan_to_workflow
    )
    app.add_url_rule("/agent/debug/kg/tools", methods=["GET"], view_func=debug_kg_tools)
