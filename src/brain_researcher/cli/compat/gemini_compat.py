from __future__ import annotations

import json
import os
from typing import Any, Dict, Tuple

from brain_researcher.services.agent import telemetry
from brain_researcher.services.agent.llm_budget_manager import (
    LLMBudgetManager,
    get_shared_llm_budget_manager,
)
from brain_researcher.services.agent.managed_credential_pool import (
    get_shared_managed_pool,
)
from brain_researcher.services.agent.router import LLMRouter

_BUDGET_MANAGER = get_shared_llm_budget_manager()
_MANAGED_POOL = get_shared_managed_pool()
_ROUTER = LLMRouter(budget_manager=_BUDGET_MANAGER, managed_pool=_MANAGED_POOL)


def run_simple_chat(
    prompt: str,
    model: str | None = None,
    domain_filter: list[str] | None = None,
    function_filter: list[str] | None = None,
    risk_filter: list[str] | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """Execute a single-turn chat with Gemini-compat flags.

    Returns: (text, execution_meta)
    where execution_meta = {
      provider, model, route, transport, fallback_reason, usage
    }
    """
    mdl = model or os.environ.get("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
    run_id = telemetry.new_run_id()
    with telemetry.span_context(
        "agent.chat",
        {
            "channel": "cli",
            "request_type": "chat",
            "run_id": run_id,
        },
    ) as span:
        result = _ROUTER.route_chat(
            prompt,
            model_hint=mdl,
        )
        metadata = result.metadata
        span_record = span.finish(
            status="ok",
            provider=metadata.provider,
            model=metadata.model,
            route=metadata.route,
            transport=metadata.transport,
            credential=metadata.credential,
            bill_to=metadata.bill_to,
        )
    latency_ms = metadata.latency_ms or int(round(span_record["duration_ms"]))
    event_payload = {
        "run_id": run_id,
        "channel": "cli",
        "request_type": "chat",
        "prompt_hash": telemetry.prompt_hash(prompt),
        "prompt_length": len(prompt or ""),
        "llm": {
            "provider": metadata.provider,
            "model": metadata.model,
            "requested_model": mdl,
            "route": metadata.route,
            "transport": metadata.transport,
            "credential": metadata.credential,
            "bill_to": metadata.bill_to,
            "usage": metadata.usage or {},
            "fallback_reason": metadata.fallback_reason,
            "latency_ms": latency_ms,
        },
        "spans": [span_record],
    }
    try:
        telemetry.record_event(event_payload, event_type="chat")
    except Exception:
        pass

    text = result.text
    return text, {
        "provider": metadata.provider,
        "model": metadata.model,
        "route": metadata.route,
        "transport": metadata.transport,
        "fallback_reason": metadata.fallback_reason,
        "usage": metadata.usage or {},
        "credential": metadata.credential,
        "bill_to": metadata.bill_to,
        "run_id": run_id,
    }


def _get_billing_badge(bill_to: str | None, cost: float | None) -> str:
    """Generate a billing badge for CLI output.

    Args:
        bill_to: Billing target (e.g., "local_oauth", "byok", "managed")
        cost: Estimated cost in USD

    Returns:
        Badge string with emoji and cost info
    """
    if not bill_to:
        return ""

    if bill_to == "local_oauth":
        return "🎁 Free"
    if "byok" in bill_to.lower():
        if cost is not None and cost > 0:
            return f"🔑 BYOK (${cost:.4f})"
        return "🔑 BYOK"
    if "managed" in bill_to.lower():
        if cost is not None and cost > 0:
            return f"💳 Managed (${cost:.4f})"
        return "💳 Managed"

    # Unknown billing type
    if cost is not None and cost > 0:
        return f"${cost:.4f}"
    return ""


def emit_result(text: str, meta: Dict[str, Any], json_output: bool = False) -> str:
    """Format the result for CLI output.

    If json_output is True, returns a JSON string with unified fields.
    Otherwise, returns a compact human-readable string.
    """
    run_id = meta.get("run_id")
    if json_output:
        payload = {
            "provider": meta.get("provider"),
            "model": meta.get("model"),
            "route": meta.get("route"),
            "transport": meta.get("transport"),
            "fallback_reason": meta.get("fallback_reason"),
            "usage": meta.get("usage", {}),
            "credential": meta.get("credential"),
            "bill_to": meta.get("bill_to"),
            "estimated_cost": meta.get("estimated_cost"),
            "budget_remaining": meta.get("budget_remaining"),
            "quota_remaining": meta.get("quota_remaining"),
            "run_id": run_id,
            "text": text,
        }
        return json.dumps(payload, ensure_ascii=False)

    # Human-readable output with billing badge
    header = (
        f"[{meta.get('provider')}] {meta.get('model')} "
        f"route={meta.get('route')} transport={meta.get('transport')}"
        + (
            f" reason={meta.get('fallback_reason')}"
            if meta.get("route") == "fallback"
            else ""
        )
    )
    if run_id:
        header = f"{header} run={run_id}"

    # Add billing badge
    badge = _get_billing_badge(meta.get("bill_to"), meta.get("estimated_cost"))
    if badge:
        header = f"{header} {badge}"

    return f"{header}\n\n{text}"
