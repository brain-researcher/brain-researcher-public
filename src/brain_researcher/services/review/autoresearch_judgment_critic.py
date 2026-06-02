"""LLM-based scientific judgment critic for autoresearch loops."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from brain_researcher.core.contracts.autoresearch_review import AutoresearchReviewBundle
from brain_researcher.core.contracts.scientific_review import (
    JudgmentVerdict,
    judgment_verdict_llm_schema,
)
from brain_researcher.services.review.judgment_critic import _resolve_judgment_model
from brain_researcher.services.shared.leaves_judgment_router import (
    JudgmentChatResult,
    JudgmentRouter,
    get_default_judgment_router,
)

logger = logging.getLogger(__name__)


def _strip_json_fence(candidate: str) -> str:
    raw = str(candidate or "").strip()
    if raw.lower().startswith("json"):
        return raw[4:].strip()
    return raw


def _parse_json_object(candidate: str) -> dict[str, Any]:
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("autoresearch judgment critic response must be a JSON object")
    return payload


def _extract_balanced_json_object(text: str) -> str | None:
    raw = str(text or "")
    for start_idx, char in enumerate(raw):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end_idx in range(start_idx, len(raw)):
            current = raw[end_idx]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
                continue
            if current == "{":
                depth += 1
                continue
            if current == "}":
                depth -= 1
                if depth == 0:
                    return raw[start_idx : end_idx + 1]
    return None


def _extract_json_payload(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty response")

    candidates: list[str] = [raw]
    if raw.lower().startswith("json"):
        candidates.append(_strip_json_fence(raw))

    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE):
        fenced = _strip_json_fence(match.group(1))
        if fenced:
            candidates.append(fenced)

    balanced = _extract_balanced_json_object(raw)
    if balanced:
        candidates.append(balanced)

    seen: set[str] = set()
    parse_errors: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        try:
            return _parse_json_object(cleaned)
        except Exception as exc:  # pylint: disable=broad-except
            parse_errors.append(str(exc))

    detail = parse_errors[-1] if parse_errors else "no parseable JSON object found"
    raise ValueError(f"invalid JSON response: {detail}")


def _build_judgment_prompt(bundle: AutoresearchReviewBundle) -> str:
    bundle_json = bundle.model_dump_json(indent=2)
    schema = json.dumps(judgment_verdict_llm_schema(), indent=2)
    return f"""You are an independent scientific reviewer for an autoresearch loop in predictive neuroscience.

You are NOT checking formatting. You are judging whether the scientific claims are matched to the evidence in the loop bundle.

Bundle:
{bundle_json}

Assess the bundle with these questions:
1. Is the estimand and evaluation target complete enough to justify the report claims?
2. Are any components being overclaimed relative to their apparent fold noise, marginal gains, or missing validation evidence?
3. Does the report honestly separate primary analysis from sensitivity/exploratory analyses?
4. Are the missing validation steps important enough that the loop should continue instead of stopping?
5. What would a skeptical reviewer ask next?

Interpretation guidance:
- Treat `claim_strength_declared=scientifically_convincing` as a strong claim that requires actual validation evidence, not just prose.
- Penalize reports that treat marginal or noisy hard-target wins as robust without caveats.
- Reward explicit acknowledgment of null KG value, target noise, or non-determinism when supported by the bundle.
- Use `issues` for specific scientific problems; use `reviewer_questions` for concrete next-step questions.

Respond ONLY as a JSON object matching this schema:
{schema}
"""


def _build_repair_prompt(raw_text: str) -> str:
    schema = json.dumps(judgment_verdict_llm_schema(), indent=2)
    clipped = raw_text[:6000]
    return f"""The previous scientific-review response was not valid JSON for the required schema.

Return ONLY one valid JSON object matching this schema:
{schema}

Do not include markdown fences, prose, or explanations.

Previous invalid response:
```text
{clipped}
```
"""


def _route_judgment_prompt(
    llm_router: JudgmentRouter,
    *,
    prompt: str,
    model_hint: str | None,
) -> JudgmentChatResult:
    provider_lock = None
    normalized_hint = (model_hint or "").lower()
    if not normalized_hint or "gemini" in normalized_hint:
        provider_lock = "gemini"
    return llm_router.route_chat(
        prompt=prompt,
        model_hint=model_hint,
        provider_lock=provider_lock,
        task_type="classification",
        strict_json=True,
    )


def _validated_verdict_from_text(text: str) -> JudgmentVerdict:
    data = _extract_json_payload(text)
    verdict = JudgmentVerdict.model_validate(data)
    return verdict.model_copy(
        update={
            "judgment_status": "ok",
            "judge_transport_error": None,
            "raw_response_text": text,
        }
    )


def run_autoresearch_judgment_critic(
    bundle: AutoresearchReviewBundle,
    *,
    model: str | None = None,
    router: JudgmentRouter | None = None,
) -> JudgmentVerdict:
    """Run the independent LLM judgment critic on an autoresearch bundle."""
    prompt = _build_judgment_prompt(bundle)
    model_hint = _resolve_judgment_model(model)

    try:
        llm_router = router or get_default_judgment_router()
        result = _route_judgment_prompt(
            llm_router,
            prompt=prompt,
            model_hint=model_hint,
        )
    except Exception as exc:
        logger.warning("autoresearch_judgment_critic provider failure: %s", exc)
        return JudgmentVerdict(
            decision="questionable",
            estimand_complete=True,
            method_defensible=True,
            judgment_status="provider_failed",
            judge_transport_error=str(exc),
            issues=[f"autoresearch_judgment_critic unavailable: {exc}"],
            reviewer_questions=[],
        )

    first_raw = result.text
    try:
        return _validated_verdict_from_text(first_raw)
    except Exception as exc:
        logger.warning(
            "autoresearch_judgment_critic parse failure, attempting repair: %s", exc
        )
        first_error = str(exc)

    try:
        repair_result = _route_judgment_prompt(
            llm_router,
            prompt=_build_repair_prompt(first_raw),
            model_hint=model_hint,
        )
    except Exception as exc:
        logger.warning("autoresearch_judgment_critic repair provider failure: %s", exc)
        return JudgmentVerdict(
            decision="questionable",
            estimand_complete=True,
            method_defensible=True,
            judgment_status="provider_failed",
            judge_transport_error=f"initial_parse_failed: {first_error}; repair_provider_failed: {exc}",
            raw_response_text=first_raw,
            issues=[
                "autoresearch_judgment_critic unavailable: "
                f"initial_parse_failed: {first_error}; repair_provider_failed: {exc}"
            ],
            reviewer_questions=[],
        )

    repair_raw = repair_result.text
    try:
        return _validated_verdict_from_text(repair_raw)
    except Exception as exc:
        logger.warning("autoresearch_judgment_critic repair parse failed: %s", exc)
        transport_error = f"initial_parse_failed: {first_error}; repair_failed: {exc}"
        return JudgmentVerdict(
            decision="questionable",
            estimand_complete=True,
            method_defensible=True,
            judgment_status="parse_failed",
            judge_transport_error=transport_error,
            raw_response_text=repair_raw or first_raw,
            issues=[f"autoresearch_judgment_critic unavailable: {transport_error}"],
            reviewer_questions=[],
        )


__all__ = ["run_autoresearch_judgment_critic"]
