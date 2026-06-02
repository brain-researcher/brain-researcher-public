"""LLM-based scientific judgment critic (Phase 3b).

Independence protocol: input is a structured CodeReviewBundle only — no
narrative, no prior correctness/completeness findings. The critic generates
its own assessment independently before findings are cross-referenced.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle
from brain_researcher.core.contracts.scientific_review import (
    JudgmentVerdict,
    judgment_verdict_llm_schema,
)
from brain_researcher.services.shared.leaves_judgment_router import (
    JudgmentRouter,
    get_default_judgment_router,
)

logger = logging.getLogger(__name__)
DEFAULT_JUDGMENT_GEMINI_MODEL = "gemini-2.5-flash"


def _extract_json_payload(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating Markdown code fences."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("judgment_critic response must be a JSON object")
    return payload


def _build_judgment_prompt(bundle: CodeReviewBundle) -> str:
    bundle_json = bundle.model_dump_json(indent=2)
    schema = json.dumps(judgment_verdict_llm_schema(), indent=2)
    return f"""You are an independent scientific reviewer for a neuroimaging analysis pipeline.

Given the following pipeline bundle (structured data only, no narrative):
{bundle_json}

Assess the scientific quality of this pipeline:
1. Is the estimand fully specified? (what exactly is being measured, with all defining choices explicit)
2. Are all scientific choices explicit? (atlas, confounds, HRF, correlation type, normalization)
3. Is the method choice defensible for the declared task and modality?
4. What questions would a domain expert reviewer ask?
5. If `review_context` indicates predictive evaluation, are split integrity, null-model, and preprocessing-provenance details explicit enough to support out-of-sample claims?
6. If neuroAI-style candidate selection is present, are model/layer/ROI/prompt winner selection, grouping-aware splits, and multiplicity / winner-selection accounting explicit enough to support generalization claims?
7. If the bundle suggests fit/prediction/mechanism language, are there claim-inflation risks (e.g. in-sample fit presented as prediction, prediction presented as mechanism, association presented as causality, reverse inference from region activation to process, or encoding/model fit presented as mechanistic equivalence)?
8. If explicit controversial choices are present (e.g. GSR, dynamic FC, graph thresholding, atlas choice, HRF flexibility), are the sensitivity / robustness checks explicit enough?
9. If explicit behavioral or alternative explanations are recorded (e.g. RT, accuracy, difficulty, eye movement), are they controlled before making cognitive or construct claims?
10. If task-level claims generalize across stimuli or use task-FC/PPI style connectivity analyses, is there explicit support for stimulus randomization and mean-evoked-response control?

Respond ONLY as a JSON object matching this schema (no additional text):
{schema}

Key rules:
- Set estimand_complete=false if the analysis goal lacks explicit atlas, confound model, or statistical test.
- Set method_defensible=false if the method is inappropriate for the declared modality/task.
- If `review_context` flags leakage or circularity, mention it explicitly in `issues`.
- Treat missing split manifests / null models / preprocessing provenance as scientific problems for predictive runs.
- Treat explicit neuroAI winner-selection-on-test, grouping-mismatch splits, or missing multiplicity accounting as scientific problems for predictive/generalization claims.
- Use `issues` for claim-inflation problems such as fit-vs-mechanism, reverse inference, representational-equivalence overreach, or correlation-vs-prediction overreach.
- Use `issues` for controversial-choice problems when the bundle records the choice but not the sensitivity/robustness analysis, especially GSR, dynamic FC, graph-threshold, atlas, or HRF choices.
- Use `issues` for construct-validity problems when explicit behavioral or alternative-explanation imbalances are present without clear control handling, when broad stimulus generalization lacks stimulus-randomization support, or when task-FC/PPI connectivity claims lack explicit mean-evoked-response control.
- If kg_context contains effect_size_priors, assess whether observed effect sizes are plausible given the prior distribution and its source confidence.
- issues: list specific scientific problems (not style).
- reviewer_questions: questions a reviewer would ask in peer review.
"""


def _resolve_judgment_model(model: str | None) -> str | None:
    """Resolve the review critic model.

    Preference order:
    1. Explicit function argument
    2. Dedicated scientific-review env override
    3. Service-wide DEFAULT_LLM_MODEL
    4. Provider-aware fallback, preferring Gemini when available
    """
    if model:
        return model

    for env_key in (
        "SCIENTIFIC_REVIEW_JUDGMENT_MODEL",
        "JUDGMENT_CRITIC_MODEL",
        "DEFAULT_LLM_MODEL",
    ):
        value = os.environ.get(env_key)
        if value:
            return value

    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return DEFAULT_JUDGMENT_GEMINI_MODEL
    if os.environ.get("OPENAI_API_KEY"):
        return "gpt-4o"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude-sonnet-4-6"
    return None


def run_judgment_critic(
    bundle: CodeReviewBundle,
    *,
    model: str | None = None,
    router: JudgmentRouter | None = None,
) -> JudgmentVerdict:
    """Run the independent LLM judgment critic on a CodeReviewBundle.

    Returns JudgmentVerdict. Falls back to a conservative 'questionable'
    verdict if the LLM call fails, so missing critic infrastructure does not
    silently appear as scientific approval.
    """
    try:
        prompt = _build_judgment_prompt(bundle)
        llm_router = router or get_default_judgment_router()
        model_hint = _resolve_judgment_model(model)
        provider_lock = None
        normalized_hint = (model_hint or "").lower()
        if not normalized_hint or "gemini" in normalized_hint:
            provider_lock = "gemini"
        result = llm_router.route_chat(
            prompt=prompt,
            model_hint=model_hint,
            provider_lock=provider_lock,
            task_type="classification",
            strict_json=True,
        )
        data = _extract_json_payload(result.text)
        return JudgmentVerdict.model_validate(data)
    except Exception as exc:
        logger.warning("judgment_critic failed: %s", exc)
        return JudgmentVerdict(
            decision="questionable",
            estimand_complete=True,
            method_defensible=True,
            judgment_status="provider_failed",
            judge_transport_error=str(exc),
            issues=[f"judgment_critic unavailable: {exc}"],
            reviewer_questions=[],
        )


__all__ = ["run_judgment_critic"]
