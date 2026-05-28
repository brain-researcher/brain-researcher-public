"""Independent critic for autoresearch runtime verdicts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain_researcher.autoresearch.quality_protocol import GateVerdict
from brain_researcher.autoresearch.state_contract import GateCheck
from brain_researcher.core.contracts.llm_router import LLMRouterProtocol

logger = logging.getLogger(__name__)


def _extract_json_payload(text: str) -> dict[str, Any]:
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
        raise ValueError("critic response must be a JSON object")
    return payload


@dataclass(frozen=True)
class CriticVerdict:
    decision: str
    summary: str
    judgment: GateCheck
    completeness: GateCheck
    raw_payload: dict[str, Any]


def _gate_from_payload(payload: dict[str, Any]) -> GateCheck:
    return GateCheck(
        passed=bool(payload.get("passed")),
        reasons=tuple(str(item) for item in payload.get("reasons", [])),
        required_actions=tuple(
            str(item) for item in payload.get("required_actions", [])
        ),
        metadata=dict(payload.get("metadata") or {}),
    )


def _build_prompt(
    *,
    line_id: str,
    results: dict[str, Any],
    rubric_text: str,
) -> str:
    schema = {
        "decision": (
            f"{GateVerdict.PROCEED.value}|"
            f"{GateVerdict.NEEDS_DIAGNOSIS.value}|"
            f"{GateVerdict.NEEDS_EXPLORATION.value}|"
            f"{GateVerdict.STOP_HUMAN_REVIEW.value}"
        ),
        "summary": "short string",
        "judgment": {
            "passed": True,
            "reasons": ["string"],
            "required_actions": ["string"],
            "metadata": {"optional_key": "optional value"},
        },
        "completeness": {
            "passed": True,
            "reasons": ["string"],
            "required_actions": ["string"],
            "metadata": {"optional_key": "optional value"},
        },
    }
    results_json = json.dumps(results, indent=2, sort_keys=True)
    schema_json = json.dumps(schema, indent=2, sort_keys=True)
    return f"""You are an independent autoresearch critic for the `{line_id}` line.

You must judge only from:
1. the machine-readable scorer/runtime results below
2. the rubric below

Do not assume access to any prior chain-of-thought, agent rationale, or hidden context.
Do not restate the rubric. Decide whether judgment and completeness pass independently.

Runtime results:
{results_json}

Rubric:
{rubric_text}

Return ONLY a JSON object matching this shape:
{schema_json}
"""


def run_independent_critic(
    *,
    line_id: str,
    results: dict[str, Any],
    rubric_path: Path | str,
    router: LLMRouterProtocol,
    model: str = "claude-sonnet-4-6",
) -> CriticVerdict:
    rubric_text = Path(rubric_path).expanduser().resolve().read_text(encoding="utf-8")
    prompt = _build_prompt(line_id=line_id, results=results, rubric_text=rubric_text)
    try:
        response = router.route_chat(
            prompt=prompt,
            model_hint=model,
            task_type="classification",
            strict_json=True,
        )
        payload = _extract_json_payload(response.text)
        return CriticVerdict(
            decision=str(payload.get("decision") or GateVerdict.NEEDS_DIAGNOSIS.value),
            summary=str(payload.get("summary") or "").strip(),
            judgment=_gate_from_payload(dict(payload.get("judgment") or {})),
            completeness=_gate_from_payload(dict(payload.get("completeness") or {})),
            raw_payload=payload,
        )
    except Exception as exc:
        logger.warning("independent autoresearch critic failed: %s", exc)
        reason = f"critic unavailable: {exc}"
        fallback_gate = GateCheck(
            passed=False,
            reasons=(reason,),
            required_actions=("Inspect scorer output manually before promotion.",),
        )
        return CriticVerdict(
            decision=GateVerdict.STOP_HUMAN_REVIEW.value,
            summary=reason,
            judgment=fallback_gate,
            completeness=fallback_gate,
            raw_payload={
                "decision": GateVerdict.STOP_HUMAN_REVIEW.value,
                "summary": reason,
            },
        )


__all__ = ["CriticVerdict", "run_independent_critic"]
