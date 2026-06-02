"""
Router abstraction for large language model invocations.

This module centralises how the agent, CLI, and MCP entrypoints resolve
providers, invoke transports (local CLI, SDK, or remote APIs), and emit
consistent telemetry metadata.  The Gemini CLI cascade remains the default
route when `USE_GEMINI_CLI=true` and the requested model is a Gemini variant.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from brain_researcher.services.llm_gateway import gemini_cli
from brain_researcher.services.llm_gateway.circuit_breaker import CircuitBreaker
from brain_researcher.services.llm_gateway.cost_calculator import calculate_cost
from brain_researcher.services.llm_gateway.credential_resolver import (
    CredentialResolver,
    ResolvedCredential,
)
from brain_researcher.services.llm_gateway.llm import get_llm
from brain_researcher.services.llm_gateway.llm_metrics_emitter import emit_llm_metrics
from brain_researcher.services.llm_gateway.rate_limit import (
    RateLimitExceeded,
    TokenBucketRateLimiter,
)
from brain_researcher.services.llm_gateway.token_counter import TokenCounter

if TYPE_CHECKING:
    from brain_researcher.services.llm_gateway.managed_credential_pool import (
        ManagedCredentialPool,
    )

# Optional imports for budget tracking
try:
    from brain_researcher.services.llm_gateway.llm_budget_manager import (
        BudgetExhaustedError,
        LLMBudgetManager,
    )
except ImportError:
    LLMBudgetManager = None  # type: ignore
    BudgetExhaustedError = Exception  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_PRIMARY_MODEL = "gemini-3-flash-preview"
DEFAULT_GEMINI_CHAT_MODEL = "gemini-3.1-flash-lite-preview"
DEFAULT_GEMINI_CODING_MODEL = "gemini-3-flash-preview"


def _run_coro_sync(coro):
    """Run an async coroutine from a sync context without nesting event loops."""
    try:
        asyncio.run  # type: ignore[attr-defined]  # noqa: B018
    except Exception:
        # asyncio not available; bail out
        raise

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread
        return asyncio.run(coro)

    # Running inside an event loop; execute coroutine in a helper thread
    result_box: dict[str, Any] = {}
    error_box: dict[str, BaseException] = {}

    def _runner():
        try:
            result_box["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - propagation path
            error_box["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()

    if error_box:
        raise error_box["error"]
    return result_box.get("value")


def _fire_and_forget(coro):
    """Schedule a coroutine without blocking the caller."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()
        return
    loop.create_task(coro)


def infer_provider(model_name: str | None) -> str:
    """
    Infer the logical provider name from a model identifier.

    Returns lowercase provider slug (google, openai, anthropic, deepseek, etc.).
    """
    if not model_name:
        return "unknown"
    name = model_name.lower()
    if "gemini" in name or "google" in name:
        return "google"
    if "gpt" in name or "o3" in name or "o1" in name:
        return "openai"
    if "claude" in name or "anthropic" in name:
        return "anthropic"
    if "deepseek" in name:
        return "deepseek"
    if "qwen" in name:
        return "alibaba"
    return "unknown"


@dataclass
class LLMRouteMetadata:
    """Telemetry metadata describing how an LLM invocation was routed."""

    provider: str
    model: str
    route: str = "primary"
    transport: str = "sdk"
    fallback_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int | None = None
    credential: str | None = None
    bill_to: str | None = None
    estimated_cost: float | None = None
    budget_remaining: dict[str, float] | None = None
    quota_remaining: dict[str, int] | None = None
    # Budget tracking fields (Track 1)
    budget_id: str | None = None
    allocation_id: str | None = None


@dataclass
class LLMChatResult:
    """Outcome of a single chat invocation routed through the LLMRouter."""

    text: str
    metadata: LLMRouteMetadata


class LLMRouter:
    """
    High-level entrypoint for routing chat prompts to the appropriate provider.

    The router is intentionally lightweight: it detects when the Gemini CLI
    cascade should be used, delegates to the specialised provider router, and
    otherwise relies on the existing langchain-based factory.
    """

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver | None = None,
        use_gemini_cli: bool | None = None,
        budget_manager: LLMBudgetManager | None = None,
        managed_pool: ManagedCredentialPool | None = None,
    ) -> None:
        self.credential_resolver = credential_resolver or CredentialResolver(
            managed_pool=managed_pool
        )
        if use_gemini_cli is None:
            use_gemini_cli = os.environ.get("USE_GEMINI_CLI", "true").lower() == "true"
        self.use_gemini_cli = bool(use_gemini_cli)
        self.budget_manager = budget_manager
        self._gemini_router = GeminiCLIRouter(
            credential_resolver=self.credential_resolver,
            budget_manager=self.budget_manager,
        )

    def route_chat(
        self,
        prompt: str,
        model_hint: str | None = None,
        *,
        provider_lock: str | None = None,
        credential_name: str | None = None,
        thinking_budget: int | None = None,
        budget_id: str | None = None,
        task_type: str | None = None,
        strict_json: bool | None = None,
        ctx_tokens: int | None = None,
        **_: Any,
    ) -> LLMChatResult:
        """
        Route a prompt through the configured provider.

        Args:
            prompt: User prompt to execute.
            model_hint: Preferred model name (defaults to DEFAULT_LLM_MODEL env).
            credential_name: Optional credential override.
            thinking_budget: Optional Gemini CLI thinking budget.

        Extra kwargs (e.g., budget_id) are ignored for backward compatibility.

        Returns:
            LLMChatResult with response text and telemetry metadata.
        """
        from brain_researcher.services.llm_gateway.codegen.model_policy import (
            select_model,
        )

        normalized_provider_lock = (provider_lock or "").strip().lower() or None
        # Let coding tasks fall through to DEFAULT_CODING_MODEL when no explicit hint exists.
        base_model = model_hint
        if not base_model and task_type != "code":
            base_model = os.environ.get(
                "DEFAULT_LLM_MODEL", DEFAULT_GEMINI_PRIMARY_MODEL
            )
        if normalized_provider_lock == "gemini" and (
            not base_model or "gemini" not in base_model.lower()
        ):
            base_model = (
                os.environ.get("CODE_AGENT_GEMINI_MODEL")
                or os.environ.get("DEFAULT_CODING_MODEL")
                or DEFAULT_GEMINI_CODING_MODEL
            )
        model = select_model(
            base_model,
            task_type=task_type,
            strict_json=strict_json,
            ctx_tokens=ctx_tokens,
        )
        if not model:
            model = os.environ.get("DEFAULT_LLM_MODEL", DEFAULT_GEMINI_PRIMARY_MODEL)
        if normalized_provider_lock == "gemini" and (
            not model or "gemini" not in model.lower()
        ):
            model = (
                os.environ.get("CODE_AGENT_GEMINI_MODEL")
                or os.environ.get("DEFAULT_CODING_MODEL")
                or DEFAULT_GEMINI_CODING_MODEL
            )

        if "gemini" in model.lower() and self.use_gemini_cli:
            return self._gemini_router.route_chat(
                prompt=prompt,
                model_hint=model,
                provider_lock=normalized_provider_lock,
                credential_name=credential_name,
                thinking_budget=thinking_budget,
                budget_id=budget_id,
                task_type=task_type,
                strict_json=strict_json,
                ctx_tokens=ctx_tokens,
            )

        return self._invoke_generic_llm(
            prompt=prompt,
            model=model,
            credential_name=credential_name,
            budget_id=budget_id,
        )

    def _invoke_generic_llm(
        self,
        *,
        prompt: str,
        model: str,
        credential_name: str | None = None,
        budget_id: str | None = None,
    ) -> LLMChatResult:
        """Invoke non-Gemini models via the existing langchain factory."""
        credential = self.credential_resolver.resolve_for_chat(
            model_hint=model,
            credential_name=credential_name,
            budget_id=budget_id,
        )

        byok_result = self._attempt_byok_openai(
            prompt=prompt,
            model=model,
            route="primary",
            credential=credential,
        )
        if byok_result:
            return byok_result

        start = time.time()
        llm = get_llm(model)
        response = llm.invoke(prompt)
        text = getattr(response, "content", None) or str(response)

        usage: dict[str, Any] = {}
        # LangChain's AIMessage may expose usage metadata in different attributes.
        for attr in ("usage_metadata", "response_metadata", "metadata"):
            data = getattr(response, attr, None)
            if isinstance(data, dict):
                usage = data.get("usage", data)
                break

        latency_ms = int((time.time() - start) * 1000)
        provider = infer_provider(model)
        if credential and (credential.metadata or {}).get("is_managed") and budget_id:
            bill_to_val = f"managed:{budget_id}"
        else:
            bill_to_val = (
                (credential.metadata or {}).get("source") if credential else None
            )
        allocation_id = (
            (credential.metadata or {}).get("allocation_id") if credential else None
        )

        # Calculate cost
        cost_breakdown = calculate_cost(
            provider=provider,
            model=model,
            usage=usage or {},
            bill_to=bill_to_val,
        )

        metadata = LLMRouteMetadata(
            provider=provider,
            model=model,
            route="primary",
            transport="sdk",
            usage=usage or {},
            latency_ms=latency_ms,
            credential=credential.kind if credential else None,
            bill_to=bill_to_val,
            estimated_cost=cost_breakdown.get("total_cost"),
            budget_id=budget_id,
            allocation_id=allocation_id,
        )
        emit_llm_metrics(metadata)
        return LLMChatResult(text=text, metadata=metadata)

    def _attempt_byok_openai(
        self,
        *,
        prompt: str,
        model: str,
        route: str,
        credential: ResolvedCredential | None,
    ) -> LLMChatResult | None:
        """Attempt to satisfy a request using a BYOK OpenAI credential."""
        if credential and credential.kind == "byok_openai" and credential.api_key:
            try:
                from openai import OpenAI  # type: ignore

                client = OpenAI(api_key=credential.api_key)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=4096,
                )
                text = response.choices[0].message.content or ""
                usage = {}
                if response.usage:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }

                bill_to_val = (credential.metadata or {}).get("name") or (
                    credential.metadata or {}
                ).get("source")

                # Calculate cost
                cost_breakdown = calculate_cost(
                    provider="openai",
                    model=model,
                    usage=usage or {},
                    bill_to=bill_to_val,
                )

                metadata = LLMRouteMetadata(
                    provider="openai",
                    model=model,
                    route=route,
                    transport="sdk",
                    usage=usage or {},
                    credential=credential.kind,
                    bill_to=bill_to_val,
                    estimated_cost=cost_breakdown.get("total_cost"),
                )
                emit_llm_metrics(metadata)
                return LLMChatResult(text=text, metadata=metadata)
            except Exception as exc:  # pylint: disable=broad-except
                logger.info("BYOK OpenAI failed: %s", exc)
                raise exc

        return None


class GeminiCLIRouter:
    """
    Provider router that encapsulates the Gemini CLI cascade.

    Order of attempts:
        1. Gemini local CLI via OAuth (when available)
        2. BYOK Gemini API key via google-generativeai SDK
        3. BYOK OpenAI key (GPT-5 fallback) or configured default LLM
    """

    DEFAULT_CASCADE = (
        DEFAULT_GEMINI_CHAT_MODEL,
        DEFAULT_GEMINI_CODING_MODEL,
        "gpt-5",
    )

    def __init__(
        self,
        *,
        credential_resolver: CredentialResolver | None = None,
        rate_limiter: TokenBucketRateLimiter | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        budget_manager: LLMBudgetManager | None = None,
    ) -> None:
        self.credential_resolver = credential_resolver or CredentialResolver()
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(
            rps=int(os.environ.get("GEMINI_LOCAL_RPS", "30")),
            rpm=int(os.environ.get("GEMINI_LOCAL_RPM", "300")),
        )
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=int(os.environ.get("GEMINI_CB_FAILS", "5")),
            recovery_timeout_sec=int(os.environ.get("GEMINI_CB_RECOVERY", "60")),
        )
        self.budget_manager = budget_manager

    # ---- Public API -----------------------------------------------------

    def route_chat(
        self,
        *,
        prompt: str,
        model_hint: str | None = None,
        provider_lock: str | None = None,
        credential_name: str | None = None,
        thinking_budget: int | None = None,
        budget_id: str | None = None,
        task_type: str | None = None,
        strict_json: bool | None = None,
        ctx_tokens: int | None = None,
    ) -> LLMChatResult:
        start_time = time.time()
        cascade = self._cascade_for(
            model_hint,
            provider_lock=provider_lock,
            task_type=task_type,
            strict_json=strict_json,
            ctx_tokens=ctx_tokens,
        )
        last_exc: Exception | None = None
        last_reason: str | None = None

        for attempt_idx, model in enumerate(cascade):
            route = "primary" if attempt_idx == 0 else "fallback"
            try:
                # Resolve credential (with budget_id if provided)
                cred = self.credential_resolver.resolve_for_chat(
                    model_hint=model,
                    credential_name=credential_name,
                    budget_id=budget_id,
                )

                # Pre-invocation budget check (if budget_id provided and manager available)
                allocation_id = None
                if budget_id and self.budget_manager:
                    # Estimate tokens for budget check
                    estimated_tokens = (
                        TokenCounter.estimate_tokens(prompt, "google") * 2
                    )

                    try:
                        budget_decision = _run_coro_sync(
                            self.budget_manager.pre_invocation_check(
                                budget_id=budget_id,
                                model=model,
                                estimated_tokens=estimated_tokens,
                                provider=infer_provider(model),
                            )
                        )

                        if not budget_decision.approved:
                            reason = budget_decision.reason or "budget_exceeded"
                            logger.warning(
                                "Budget check failed for %s: %s", budget_id, reason
                            )
                            raise BudgetExhaustedError(reason)

                        allocation_id = budget_decision.allocation_id

                    except BudgetExhaustedError:
                        last_reason = "budget_exceeded"
                        raise
                    except Exception as budget_exc:
                        logger.error(f"Budget check error: {budget_exc}")
                        # Allow call to proceed if budget check fails
                        pass

                # Attempt the model invocation
                result = self._attempt_model(
                    prompt=prompt,
                    model=model,
                    route=route,
                    credential=cred,
                    thinking_budget=thinking_budget,
                    budget_id=budget_id,
                    allocation_id=allocation_id,
                    task_type=task_type,
                    strict_json=strict_json,
                    ctx_tokens=ctx_tokens,
                )

                if result is not None:
                    latency_ms = int((time.time() - start_time) * 1000)
                    result.metadata.latency_ms = latency_ms
                    if last_reason and not result.metadata.fallback_reason:
                        result.metadata.fallback_reason = last_reason

                    # Set budget tracking fields
                    result.metadata.budget_id = budget_id
                    result.metadata.allocation_id = allocation_id

                    return result

                last_reason = "no_credential"
                continue

            except gemini_cli.GeminiAuthError as exc:
                logger.error("Gemini auth failed: %s", exc)
                raise RuntimeError(
                    "Gemini authentication failed. Please run `gemini login`."
                ) from exc
            except RateLimitExceeded as exc:
                logger.info("Local Gemini rate limited: %s; trying next", exc)
                last_exc = exc
                last_reason = "local_rate_limited"
                continue
            except gemini_cli.GeminiQuotaError as exc:
                logger.info("Gemini quota exhausted: %s; trying next", exc)
                last_exc = exc
                last_reason = "quota_exhausted"
                continue
            except gemini_cli.GeminiTimeoutError as exc:
                logger.info("Gemini timed out: %s; trying next", exc)
                last_exc = exc
                last_reason = "timeout"
                continue
            except gemini_cli.GeminiProcessError as exc:
                logger.info("Gemini process error on %s: %s; trying next", model, exc)
                last_exc = exc
                last_reason = "process_error"
                continue
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Fallback model %s failed: %s", model, exc)
                last_exc = exc
                last_reason = "exception"
                continue

        if last_exc:
            raise last_exc
        raise RuntimeError("All fallback models failed with no exception captured")

    # ---- Internal helpers -----------------------------------------------

    def _cascade_for(
        self,
        model_hint: str | None,
        *,
        provider_lock: str | None = None,
        task_type: str | None = None,
        strict_json: bool | None = None,
        ctx_tokens: int | None = None,
    ) -> Iterable[str]:
        def _dedupe(chain: Iterable[str]) -> tuple[str, ...]:
            deduped: list[str] = []
            for model_name in chain:
                if model_name and model_name not in deduped:
                    deduped.append(model_name)
            return tuple(deduped)

        normalized_provider_lock = (provider_lock or "").strip().lower() or None
        if normalized_provider_lock == "gemini":
            primary = (
                model_hint
                if (model_hint and "gemini" in model_hint.lower())
                else (
                    os.environ.get("CODE_AGENT_GEMINI_MODEL")
                    or os.environ.get("DEFAULT_CODING_MODEL")
                    or DEFAULT_GEMINI_CODING_MODEL
                )
            )
            if task_type == "code" or strict_json:
                return _dedupe((primary, DEFAULT_GEMINI_CODING_MODEL))
            primary_name = primary.lower()
            chain: tuple[str, ...]
            if "flash-lite" in primary_name:
                chain = (primary, DEFAULT_GEMINI_CODING_MODEL)
            elif "flash" in primary_name:
                chain = (primary, DEFAULT_GEMINI_CHAT_MODEL)
            else:
                chain = (
                    primary,
                    DEFAULT_GEMINI_CODING_MODEL,
                    DEFAULT_GEMINI_CHAT_MODEL,
                )
            return _dedupe(chain)

        if not model_hint:
            if (
                task_type == "code"
                or strict_json
                or (ctx_tokens and ctx_tokens > 120_000)
            ):
                return (
                    DEFAULT_GEMINI_CODING_MODEL,
                    DEFAULT_GEMINI_CHAT_MODEL,
                    "gpt-5",
                )
            return self.DEFAULT_CASCADE

        name = model_hint.lower()

        # Strict JSON / coding tasks bias toward the stronger Gemini 3 model.
        if (task_type == "code" or strict_json) and "gemini" in name:
            return _dedupe((model_hint, DEFAULT_GEMINI_CODING_MODEL, "gpt-5"))

        if "flash-lite" in name:
            return _dedupe((model_hint, DEFAULT_GEMINI_CODING_MODEL, "gpt-5"))
        if "flash" in name:
            return _dedupe((model_hint, DEFAULT_GEMINI_CHAT_MODEL, "gpt-5"))
        if "pro" in name:
            return _dedupe(
                (
                    model_hint,
                    DEFAULT_GEMINI_CODING_MODEL,
                    DEFAULT_GEMINI_CHAT_MODEL,
                    "gpt-5",
                )
            )
        if "gpt" in name or "openai" in name:
            return _dedupe(
                (model_hint, DEFAULT_GEMINI_CODING_MODEL, DEFAULT_GEMINI_CHAT_MODEL)
            )
        return _dedupe(
            (model_hint,) + tuple(m for m in self.DEFAULT_CASCADE if m != model_hint)
        )

    def _attempt_model(
        self,
        *,
        prompt: str,
        model: str,
        route: str,
        credential: ResolvedCredential | None,
        thinking_budget: int | None,
        budget_id: str | None = None,
        allocation_id: str | None = None,
        task_type: str | None = None,
        strict_json: bool | None = None,
        ctx_tokens: int | None = None,
    ) -> LLMChatResult | None:
        if model.startswith("gemini-"):
            return self._attempt_gemini(
                prompt=prompt,
                model=model,
                route=route,
                credential=credential,
                thinking_budget=thinking_budget,
                budget_id=budget_id,
                allocation_id=allocation_id,
                task_type=task_type,
                strict_json=strict_json,
                ctx_tokens=ctx_tokens,
            )
        # GPT/openai fallbacks (or other non-Gemini names) go through generic path.
        return self._attempt_generic(
            prompt=prompt,
            model=model,
            route=route,
            credential=credential,
            budget_id=budget_id,
            allocation_id=allocation_id,
            task_type=task_type,
        )

    def _attempt_gemini(
        self,
        *,
        prompt: str,
        model: str,
        route: str,
        credential: ResolvedCredential | None,
        thinking_budget: int | None,
        budget_id: str | None = None,
        allocation_id: str | None = None,
        task_type: str | None = None,
        strict_json: bool | None = None,
        ctx_tokens: int | None = None,
    ) -> LLMChatResult | None:
        if credential is None:
            logger.info("No Gemini credential available; skipping %s", model)
            return None

        # Determine structured bill_to format
        is_managed = credential.metadata and credential.metadata.get(
            "is_managed", False
        )
        if is_managed and budget_id:
            bill_to = f"managed:{budget_id}"
        elif credential.kind.startswith("byok"):
            cred_name = (credential.metadata or {}).get("name") or "unknown"
            bill_to = f"byok:{cred_name}"
        else:
            bill_to = "local_oauth"

        if credential.kind in {"byok_gemini", "managed_gemini"} and credential.api_key:
            try:
                import google.generativeai as genai  # type: ignore

                genai.configure(api_key=credential.api_key)
                model_obj = genai.GenerativeModel(model)
                response = model_obj.generate_content(prompt)
                text = getattr(response, "text", "") or ""
                usage = {}
                usage_meta = getattr(response, "usage_metadata", None)
                if usage_meta:
                    usage = {
                        "prompt_tokens": getattr(
                            usage_meta, "prompt_token_count", None
                        ),
                        "completion_tokens": getattr(
                            usage_meta, "candidates_token_count", None
                        ),
                        "total_tokens": getattr(usage_meta, "total_token_count", None),
                    }
                    usage = {k: v for k, v in usage.items() if v is not None}

                # Calculate cost
                cost_breakdown = calculate_cost(
                    provider="google",
                    model=model,
                    usage=usage or {},
                    bill_to=bill_to,
                )

                # Post-invocation budget recording (fire-and-forget)
                budget_remaining = None
                if self.budget_manager and allocation_id and usage:
                    try:
                        from decimal import Decimal

                        cost_usd = Decimal(str(cost_breakdown.get("total_cost", 0)))
                        _fire_and_forget(
                            self.budget_manager.post_invocation_record(
                                allocation_id=allocation_id,
                                input_tokens=usage.get("prompt_tokens", 0),
                                output_tokens=usage.get("completion_tokens", 0),
                                cost_usd=cost_usd,
                                provider="google",
                                model=model,
                                bill_to=bill_to,
                            )
                        )
                        # Note: budget_remaining is not fetched here to avoid blocking
                        # It can be fetched separately via get_budget_status API
                    except Exception as e:
                        logger.error(f"Failed to record budget spend: {e}")

                metadata = LLMRouteMetadata(
                    provider="google",
                    model=model,
                    route=route,
                    transport="sdk",
                    usage=usage or {},
                    credential=credential.kind,
                    bill_to=bill_to,
                    estimated_cost=cost_breakdown.get("total_cost"),
                    budget_id=budget_id,
                    allocation_id=allocation_id,
                    budget_remaining=budget_remaining,
                )
                emit_llm_metrics(metadata)
                return LLMChatResult(text=text, metadata=metadata)
            except ImportError:
                logger.warning("google-generativeai not installed; falling back to CLI")
            except Exception as exc:  # pylint: disable=broad-except
                logger.info("%s Gemini SDK failed: %s", credential.kind, exc)
                raise exc

        if credential.kind == "local_gemini":
            self.rate_limiter.try_acquire()

            def _execute() -> gemini_cli.GeminiResult:
                return gemini_cli.execute_chat(
                    prompt,
                    model=model,
                    thinking_budget=thinking_budget,
                    strict_json=strict_json,
                    task_type=task_type,
                )

            result = self.circuit_breaker.call(_execute)

            # Calculate cost
            cost_breakdown = calculate_cost(
                provider="google",
                model=model,
                usage=result.usage or {},
                bill_to=bill_to,
            )

            # Post-invocation budget recording (fire-and-forget)
            budget_remaining = None
            if self.budget_manager and allocation_id and result.usage:
                try:
                    from decimal import Decimal

                    cost_usd = Decimal(str(cost_breakdown.get("total_cost", 0)))
                    _fire_and_forget(
                        self.budget_manager.post_invocation_record(
                            allocation_id=allocation_id,
                            input_tokens=result.usage.get("prompt_tokens", 0),
                            output_tokens=result.usage.get("completion_tokens", 0),
                            cost_usd=cost_usd,
                            provider="google",
                            model=model,
                            bill_to=bill_to,
                        )
                    )
                    # Note: budget_remaining not fetched to avoid blocking
                except Exception as e:
                    logger.error(f"Failed to record budget spend: {e}")

            metadata = LLMRouteMetadata(
                provider="google",
                model=model,
                route=route,
                transport="cli",
                usage=result.usage or {},
                credential=credential.kind,
                bill_to=bill_to,
                estimated_cost=cost_breakdown.get("total_cost"),
                budget_id=budget_id,
                allocation_id=allocation_id,
                budget_remaining=budget_remaining,
            )
            emit_llm_metrics(metadata)
            return LLMChatResult(text=result.text, metadata=metadata)

        logger.info(
            "Credential %s not applicable to Gemini model %s", credential.kind, model
        )
        return None

    def _attempt_generic(
        self,
        *,
        prompt: str,
        model: str,
        route: str,
        credential: ResolvedCredential | None,
        budget_id: str | None = None,
        allocation_id: str | None = None,
        task_type: str | None = None,
    ) -> LLMChatResult | None:
        # Determine structured bill_to format
        if credential:
            is_managed = credential.metadata and credential.metadata.get(
                "is_managed", False
            )
            if is_managed and budget_id:
                bill_to_val = f"managed:{budget_id}"
            elif credential.kind.startswith("byok"):
                cred_name = (credential.metadata or {}).get("name") or "unknown"
                bill_to_val = f"byok:{cred_name}"
            else:
                bill_to_val = (credential.metadata or {}).get("source") or "unknown"
        else:
            bill_to_val = "unknown"

        # Attempt BYOK OpenAI credential first
        if credential and credential.kind == "byok_openai" and credential.api_key:
            try:
                from openai import OpenAI  # type: ignore

                client = OpenAI(api_key=credential.api_key)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=4096,
                )
                text = response.choices[0].message.content or ""
                usage = {}
                if response.usage:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }

                # Calculate cost
                cost_breakdown = calculate_cost(
                    provider="openai",
                    model=model,
                    usage=usage,
                    bill_to=bill_to_val,
                )

                # Post-invocation budget recording (fire-and-forget)
                budget_remaining = None
                if self.budget_manager and allocation_id and usage:
                    try:
                        from decimal import Decimal

                        cost_usd = Decimal(str(cost_breakdown.get("total_cost", 0)))
                        _fire_and_forget(
                            self.budget_manager.post_invocation_record(
                                allocation_id=allocation_id,
                                input_tokens=usage.get("prompt_tokens", 0),
                                output_tokens=usage.get("completion_tokens", 0),
                                cost_usd=cost_usd,
                                provider="openai",
                                model=model,
                                bill_to=bill_to_val,
                            )
                        )
                        # Note: budget_remaining not fetched to avoid blocking
                    except Exception as e:
                        logger.error(f"Failed to record budget spend: {e}")

                metadata = LLMRouteMetadata(
                    provider="openai",
                    model=model,
                    route=route,
                    transport="sdk",
                    usage=usage,
                    credential=credential.kind,
                    bill_to=bill_to_val,
                    estimated_cost=cost_breakdown.get("total_cost"),
                    budget_id=budget_id,
                    allocation_id=allocation_id,
                    budget_remaining=budget_remaining,
                )
                emit_llm_metrics(metadata)
                return LLMChatResult(text=text, metadata=metadata)
            except Exception as exc:  # pylint: disable=broad-except
                logger.info("BYOK OpenAI failed: %s", exc)
                raise exc

        # Fall back to configured LLM factory
        llm = get_llm(model)
        response = llm.invoke(prompt)
        text = getattr(response, "content", None) or str(response)

        provider = infer_provider(model)

        # Calculate cost
        cost_breakdown = calculate_cost(
            provider=provider,
            model=model,
            usage={},
            bill_to=bill_to_val,
        )

        # Post-invocation budget recording (fire-and-forget, no usage data for fallback)
        budget_remaining = None
        if self.budget_manager and allocation_id:
            try:
                from decimal import Decimal

                cost_usd = Decimal(str(cost_breakdown.get("total_cost", 0)))
                _fire_and_forget(
                    self.budget_manager.post_invocation_record(
                        allocation_id=allocation_id,
                        input_tokens=0,  # No usage data available
                        output_tokens=0,
                        cost_usd=cost_usd,
                        provider=provider,
                        model=model,
                        bill_to=bill_to_val,
                    )
                )
                # Note: budget_remaining not fetched to avoid blocking
            except Exception as e:
                logger.error(f"Failed to record budget spend: {e}")

        metadata = LLMRouteMetadata(
            provider=provider,
            model=model,
            route=route,
            transport="sdk",
            usage={},
            credential=credential.kind if credential else None,
            bill_to=bill_to_val,
            estimated_cost=cost_breakdown.get("total_cost"),
            budget_id=budget_id,
            allocation_id=allocation_id,
            budget_remaining=budget_remaining,
        )
        emit_llm_metrics(metadata)
        return LLMChatResult(text=text, metadata=metadata)
