"""API-fee USD billing helpers for hosted MCP requests."""

from __future__ import annotations

import contextvars
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from brain_researcher.services.agent.router import (
    LLMChatResult,
    LLMRouteMetadata,
    LLMRouter,
    infer_provider,
)
from brain_researcher.services.agent.api_fee_debit import (
    ApiFeeDebitIdentity,
    ApiFeeReservationError,
    ApiFeeReservationResult,
    call_with_platform_api_fee_reservation,
    record_usage_and_debit_platform_api_fee,
)
from brain_researcher.services.agent.cost_calculator import calculate_cost
from brain_researcher.services.agent.logging.token_counter import TokenCounter
from brain_researcher.services.agent.managed_credential_pool import (
    get_shared_managed_pool,
)

_T = TypeVar("_T")


@dataclass
class McpApiFeeContext:
    workspace_id: str
    user_id: str
    request_id: str
    counter: int = 0


_CURRENT_API_FEE_CONTEXT: contextvars.ContextVar[McpApiFeeContext | None] = (
    contextvars.ContextVar("mcp_api_fee_context", default=None)
)


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _normalize_identity(value: Any, fallback: str | None = None) -> str | None:
    text = str(value or "").strip()
    if text:
        return text
    return fallback


def set_mcp_api_fee_context(
    *,
    user_id: str | None,
    workspace_id: str | None = None,
    request_id: str | None = None,
) -> contextvars.Token[McpApiFeeContext | None]:
    """Set the current MCP wallet identity for one authenticated request."""

    normalized_user = _normalize_identity(user_id)
    if not normalized_user or normalized_user in {"__break_glass__", "__jwt__"}:
        return _CURRENT_API_FEE_CONTEXT.set(None)

    context = McpApiFeeContext(
        workspace_id=_normalize_identity(workspace_id, "default") or "default",
        user_id=normalized_user,
        request_id=_normalize_identity(request_id, None) or uuid.uuid4().hex,
    )
    return _CURRENT_API_FEE_CONTEXT.set(context)


def reset_mcp_api_fee_context(
    token: contextvars.Token[McpApiFeeContext | None],
) -> None:
    _CURRENT_API_FEE_CONTEXT.reset(token)


def current_mcp_api_fee_identity() -> ApiFeeDebitIdentity | None:
    context = _CURRENT_API_FEE_CONTEXT.get()
    if context is None:
        return None
    return ApiFeeDebitIdentity(
        workspace_id=context.workspace_id,
        user_id=context.user_id,
    )


def current_mcp_api_fee_budget_id() -> str | None:
    context = _CURRENT_API_FEE_CONTEXT.get()
    if context is None:
        return None
    return f"mcp-api-usd:{context.workspace_id}:{context.user_id}"


def _next_idempotency_key(call_prefix: str) -> str:
    context = _CURRENT_API_FEE_CONTEXT.get()
    if context is None:
        return f"llm-api-fee:mcp:{uuid.uuid4().hex}:{call_prefix}:1"
    context.counter += 1
    return (
        f"llm-api-fee:mcp:{context.request_id}:{call_prefix or 'provider'}:"
        f"{context.counter}"
    )


def _api_fee_precall_reservation_enabled() -> bool:
    return _truthy_env("BR_PLATFORM_API_FEE_PRECALL_RESERVATION", "1")


def mcp_platform_api_fee_required() -> bool:
    """Whether hosted MCP platform provider calls must reserve API-USD first."""

    return _truthy_env("BR_MCP_PLATFORM_API_FEE_REQUIRED", "0")


def _missing_identity_error() -> ApiFeeReservationError:
    return ApiFeeReservationError(
        ApiFeeReservationResult(
            status="failed",
            reason="missing_identity",
        )
    )


def _provider_for_model(model: str, provider_lock: str | None = None) -> str:
    provider = str(provider_lock or "").strip().lower() or infer_provider(model)
    if provider == "gemini":
        provider = "google"
    return provider or "unknown"


def _route_chat_preflight_metadata(
    *,
    prompt: str,
    kwargs: dict[str, Any],
    budget_id: str | None,
) -> LLMRouteMetadata:
    model = (
        str(
            kwargs.get("model_hint")
            or kwargs.get("model")
            or os.getenv("DEFAULT_LLM_MODEL")
            or "unknown"
        ).strip()
        or "unknown"
    )
    provider = _provider_for_model(model, kwargs.get("provider_lock"))
    token_provider = provider if provider in {"openai", "anthropic", "google"} else "default"
    prompt_tokens = max(1, TokenCounter.estimate_tokens(prompt, token_provider))
    completion_tokens = max(
        1,
        _env_int("BR_PLATFORM_API_FEE_RESERVE_OUTPUT_TOKENS", 4096),
    )
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    bill_to = f"managed:{budget_id}" if budget_id else "managed"
    cost = calculate_cost(provider, model, usage, bill_to=bill_to)
    reserve_cost = float(cost.get("total_cost") or 0.0)
    if not cost.get("pricing_available"):
        reserve_cost = _env_float("BR_PLATFORM_API_FEE_UNPRICED_RESERVE_USD", 0.05)
    reserve_cost = max(
        reserve_cost,
        _env_float("BR_PLATFORM_API_FEE_MIN_RESERVE_USD", 0.001),
    )
    return LLMRouteMetadata(
        provider=provider,
        model=model,
        route="mcp_preflight",
        transport="preflight",
        usage=usage,
        credential="managed_mcp_preflight",
        bill_to=bill_to,
        estimated_cost=reserve_cost,
        budget_id=budget_id,
    )


def route_chat_with_mcp_api_fee(
    prompt: str,
    *,
    call_prefix: str = "llm",
    **kwargs: Any,
) -> LLMChatResult:
    """Route an MCP LLM call through the shared API-USD wallet when possible."""

    router = LLMRouter(managed_pool=get_shared_managed_pool())
    identity = current_mcp_api_fee_identity()
    budget_id = current_mcp_api_fee_budget_id()
    if mcp_platform_api_fee_required() and (identity is None or budget_id is None):
        raise _missing_identity_error()

    call_kwargs = dict(kwargs)
    if budget_id and not call_kwargs.get("budget_id"):
        call_kwargs["budget_id"] = budget_id

    if identity and budget_id and _api_fee_precall_reservation_enabled():
        preflight = _route_chat_preflight_metadata(
            prompt=prompt,
            kwargs=call_kwargs,
            budget_id=budget_id,
        )
        return call_with_platform_api_fee_reservation(
            preflight,
            lambda: router.route_chat(prompt, **call_kwargs),
            identity=identity,
            idempotency_key=_next_idempotency_key(call_prefix),
        )

    result = router.route_chat(prompt, **call_kwargs)
    debit_result = record_usage_and_debit_platform_api_fee(
        result.metadata,
        identity=identity,
        idempotency_key=_next_idempotency_key(call_prefix),
    )
    result.metadata.api_fee_debit = debit_result.__dict__
    return result


def _direct_call_metadata(
    *,
    provider: str,
    model: str,
    call_prefix: str,
    estimated_cost_usd: float | None,
    usage: dict[str, Any] | None,
) -> LLMRouteMetadata:
    budget_id = current_mcp_api_fee_budget_id()
    reserve_cost = float(
        estimated_cost_usd
        if estimated_cost_usd is not None
        else _env_float("BR_MCP_PLATFORM_API_FEE_DIRECT_RESERVE_USD", 0.05)
    )
    reserve_cost = max(
        reserve_cost,
        _env_float("BR_PLATFORM_API_FEE_MIN_RESERVE_USD", 0.001),
    )
    return LLMRouteMetadata(
        provider=provider,
        model=model,
        route=f"mcp_direct:{call_prefix}",
        transport="sdk",
        usage=usage or {},
        credential="managed_mcp_direct",
        bill_to=f"managed:{budget_id}" if budget_id else "managed",
        estimated_cost=reserve_cost,
        budget_id=budget_id,
    )


def call_mcp_platform_api_with_fee(
    provider_call: Callable[[], _T],
    *,
    provider: str,
    model: str,
    call_prefix: str,
    estimated_cost_usd: float | None = None,
    usage: dict[str, Any] | None = None,
) -> _T:
    """Run a direct MCP provider SDK call behind the API-USD wallet."""

    metadata = _direct_call_metadata(
        provider=provider,
        model=model,
        call_prefix=call_prefix,
        estimated_cost_usd=estimated_cost_usd,
        usage=usage,
    )
    identity = current_mcp_api_fee_identity()
    if mcp_platform_api_fee_required() and identity is None:
        raise _missing_identity_error()

    if not mcp_platform_api_fee_required() and identity is None:
        return provider_call()
    if _api_fee_precall_reservation_enabled():
        return call_with_platform_api_fee_reservation(
            metadata,
            provider_call,
            identity=identity,
            idempotency_key=_next_idempotency_key(call_prefix),
        )
    result = provider_call()
    record_usage_and_debit_platform_api_fee(
        metadata,
        identity=identity,
        idempotency_key=_next_idempotency_key(call_prefix),
    )
    return result


def api_fee_error_payload(exc: ApiFeeReservationError) -> dict[str, Any]:
    reservation = exc.result
    return {
        "ok": False,
        "error": "api_fee_credit_required",
        "message": (
            "This hosted MCP provider call requires API-USD credits. "
            "Monthly API-USD credits are shared with the web app."
        ),
        "api_fee_reservation": reservation.__dict__,
    }


__all__ = [
    "api_fee_error_payload",
    "call_mcp_platform_api_with_fee",
    "current_mcp_api_fee_budget_id",
    "current_mcp_api_fee_identity",
    "mcp_platform_api_fee_required",
    "reset_mcp_api_fee_context",
    "route_chat_with_mcp_api_fee",
    "set_mcp_api_fee_context",
]
