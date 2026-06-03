"""Planning MCP tools.

Carved out of ``mcp/server.py`` as part of splitting that monolith into
per-domain router modules. Importing this module registers the
``plan_preflight`` / ``plan_create`` / ``get_latest_plan`` tools on the shared
FastMCP instance via the ``@mcp.tool()`` decorator (an import side effect), so
``server.py`` imports it for its effect.

These tools are thin orchestration over planning helpers that stay in
``server`` (the plan-contract callers, preflight route bundle, display/execution
envelope builders, latest-plan resolvers); they are imported back here.
"""

from __future__ import annotations

from typing import Any

from brain_researcher.services.mcp.param_norm import (
    as_str_list,
    coerce_enum,
    enum_str,
)
from brain_researcher.services.mcp.server import (
    _agent_plan_payload_from_args,
    _apply_plan_preflight_fallback,
    _build_display_summary,
    _build_execution_envelope,
    _build_latest_plan_continuation_prompt,
    _call_agent_plan_contract,
    _first_text_value,
    _plan_payload_thread_id,
    _plan_preflight_route_bundle,
    _resolve_latest_plan_payload,
    _text_value,
    build_handoff_from_plan_payload,
    mcp,
    semantic_matching_scope,
)

# Allowlist surface for planner selection. Downstream treats anything other than
# "diagnostic" as the curated chat-safe surface (see web_service._normalize_allowlist_mode
# and tool_allowlist_loader.resolve_plan_tool_allowlist); the closed set is also pinned
# by the Literal["curated", "diagnostic"] planner request model. The MCP default stays
# None (omitted == curated) so we only coerce a value the caller actually sent.
_ALLOWLIST_MODE_ALIASES = {
    "curated": "curated",
    "default": "curated",
    "chat": "curated",
    "chat_safe": "curated",
    "safe": "curated",
    "diagnostic": "diagnostic",
    "diagnostics": "diagnostic",
    "diag": "diagnostic",
    "full": "diagnostic",
    "full_catalog": "diagnostic",
    "benchmark": "diagnostic",
    "wide": "diagnostic",
}


def _coerce_allowlist_mode(value: str | None) -> str | None:
    """Coerce a supplied allowlist_mode synonym to canonical; keep None passthrough.

    None / omitted is preserved (downstream reads it as curated) to avoid changing
    the response shape; a supplied value normalizes to {curated, diagnostic}.
    """

    if value is None or not str(value).strip():
        return value
    return coerce_enum(value, _ALLOWLIST_MODE_ALIASES, "curated")


@mcp.tool()
def plan_preflight(
    query: str,
    domain: str = "neuroimaging",
    modality: list[str] | None = None,
    inputs: dict[str, Any] | None = None,
    allowlist_mode: (
        enum_str(
            ("curated", "diagnostic"),
            "allowlist surface for planner selection; 'diagnostic' widens to the full catalog",
        )
        | None
    ) = None,
    semantic: bool = False,
    selection_mode: bool = False,
) -> dict[str, Any]:
    """Read-only planning preflight for dataset facts, blockers, and candidate tools."""

    modality = as_str_list(modality) or None
    allowlist_mode = _coerce_allowlist_mode(allowlist_mode)

    with semantic_matching_scope(semantic):
        working_query = _text_value(query)
        if not working_query:
            return {"ok": False, "error": "query_required"}

        route_bundle = _plan_preflight_route_bundle(
            query=working_query,
            domain=domain,
            modality=modality,
            inputs=inputs,
            allowlist_mode=allowlist_mode,
            selection_mode=bool(selection_mode),
            runtime_surface="plan_preflight",
        )
        qsm_gate = route_bundle.get("task_type_gate")
        return {
            "ok": True,
            "query": working_query,
            "domain": domain,
            "modality": route_bundle.get("modality") or [],
            "facts": route_bundle.get("facts") or {},
            "tool_candidates": route_bundle.get("tool_candidates") or [],
            "recommended_next_calls": route_bundle.get("recommended_next_calls") or [],
            "selection_mode": bool(selection_mode),
            "selection_contract": {
                "scoreable_action_rule": (
                    "Use recommended_next_calls or concrete tool/API invocations. "
                    "Do not count repo searches, package probes, version checks, or name mentions as route selection."
                ),
                "do_not_probe_environment": bool(selection_mode),
                "preferred_next_step": (
                    "Call one recommended_next_calls entry next."
                    if route_bundle.get("recommended_next_calls")
                    else "Use tool_search or get_execution_recipe to commit to a concrete route."
                ),
            },
            "routing_diagnostics": route_bundle.get("routing_diagnostics") or {},
            "allowlist_mode": allowlist_mode,
            "task_type_gate": qsm_gate,
            "anti_pitfall_checklist": (qsm_gate or {}).get("anti_pitfall_checklist"),
            "verification_protocol": (qsm_gate or {}).get("verification_protocol"),
        }


@mcp.tool()
def plan_create(
    query: str,
    domain: str = "neuroimaging",
    modality: list[str] | None = None,
    inputs: dict[str, Any] | None = None,
    allowlist_mode: (
        enum_str(
            ("curated", "diagnostic"),
            "allowlist surface for planner selection; 'diagnostic' widens to the full catalog",
        )
        | None
    ) = None,
    query_understanding: dict[str, Any] | None = None,
    include_debug: bool = False,
    semantic: bool = False,
) -> dict[str, Any]:
    """Create a read-only plan contract with display and execution envelopes."""

    modality = as_str_list(modality) or None
    allowlist_mode = _coerce_allowlist_mode(allowlist_mode)

    with semantic_matching_scope(semantic):
        working_query = _text_value(query)
        if not working_query:
            return {"ok": False, "error": "query_required"}

        try:
            payload = _agent_plan_payload_from_args(
                query=working_query,
                domain=domain,
                modality=modality,
                inputs=inputs,
                allowlist_mode=allowlist_mode,
                query_understanding=query_understanding,
                include_debug=bool(include_debug),
            )
        except Exception as exc:
            return {
                "ok": False,
                "error": "invalid_plan_request",
                "message": str(exc),
            }

        status_code, plan_payload = _call_agent_plan_contract(payload)
        if status_code >= 400:
            response = {"ok": False, "status_code": status_code}
            response.update(plan_payload)
            return response
        plan_payload = _apply_plan_preflight_fallback(
            plan_payload,
            query=working_query,
            domain=domain,
            modality=modality,
            inputs=inputs,
            allowlist_mode=allowlist_mode,
            query_understanding=query_understanding,
        )

        display_summary, markdown = _build_display_summary(
            plan_payload,
            query=working_query,
        )
        response: dict[str, Any] = {
            "ok": True,
            "display": {
                "markdown": markdown,
                "summary": display_summary,
            },
            "execution": _build_execution_envelope(plan_payload),
        }
        if include_debug:
            response["debug"] = {
                "routing_diagnostics": plan_payload.get("routing_diagnostics"),
                "context": (plan_payload.get("context") or {}),
                "candidates": plan_payload.get("candidates"),
                "planner_state": plan_payload.get("planner_state"),
                "planner_events": plan_payload.get("planner_events"),
            }
        return response


@mcp.tool()
def get_latest_plan(thread_id: str | None = None) -> dict[str, Any]:
    """Return the latest validated Brain Researcher handoff block."""

    requested_thread_id = _text_value(thread_id)
    plan_payload, source_meta = _resolve_latest_plan_payload(requested_thread_id)
    if not plan_payload:
        message = (
            f'No validated Brain Researcher plan found for thread "{requested_thread_id}".'
            if requested_thread_id
            else "No validated Brain Researcher plan found."
        )
        return {
            "ok": False,
            "error": "plan_not_found",
            "thread_id": requested_thread_id,
            "source": source_meta.get("source"),
            "message": message,
            "continuation_prompt": _build_latest_plan_continuation_prompt(
                handoff={},
                thread_id=requested_thread_id,
            ),
        }

    handoff = build_handoff_from_plan_payload(plan_payload)
    resolved_thread_id = _first_text_value(
        source_meta.get("thread_id"),
        _plan_payload_thread_id(plan_payload),
        requested_thread_id,
    )
    return {
        "ok": True,
        "thread_id": resolved_thread_id,
        "source": source_meta.get("source"),
        "source_job_id": source_meta.get("source_job_id"),
        "plan_id": handoff.get("plan_id"),
        "handoff": handoff,
        "continuation_prompt": _build_latest_plan_continuation_prompt(
            handoff=handoff,
            thread_id=resolved_thread_id,
        ),
    }
