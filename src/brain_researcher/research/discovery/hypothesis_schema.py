"""Typed discovery hypothesis ledger models and helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


class HypothesisEntryV1(BaseModel):
    """Typed ledger row for a discovery branch hypothesis."""

    model_config = ConfigDict(extra="allow")

    schema_version: Literal["hypothesis-entry-v1"] = "hypothesis-entry-v1"
    hypothesis_id: str = Field(description="Stable hypothesis identifier")
    branch_id: str | None = Field(
        default=None, description="Canonical branch identifier, if available"
    )
    branch_name: str | None = Field(
        default=None, description="Human-readable branch label, if available"
    )
    round_id: str | None = Field(
        default=None, description="Round identifier associated with the entry"
    )
    status: str | None = Field(
        default=None, description="Entry lifecycle status, if tracked"
    )
    created_at: str | None = Field(
        default=None, description="UTC timestamp when the entry was created"
    )
    updated_at: str | None = Field(
        default=None, description="UTC timestamp when the entry was updated"
    )
    prior_claim: str | None = Field(
        default=None, description="Short prior hypothesis statement"
    )
    expected_effect: str | None = Field(
        default=None, description="Expected effect or separation signal"
    )
    expected_direction: str | None = Field(
        default=None, description="Expected directionality of the branch signal"
    )
    prior_confidence: float | None = Field(
        default=None, description="Confidence attached to the prior belief"
    )
    observed_effect: str | None = Field(
        default=None, description="Observed outcome or measurement summary"
    )
    failure_modes: list[str] = Field(
        default_factory=list, description="Structured failure modes attributed"
    )
    decision: str | None = Field(
        default=None, description="Decision made after the observation"
    )
    posterior_confidence: float | None = Field(
        default=None, description="Posterior confidence after the observation"
    )
    evidence_ids: list[str] = Field(
        default_factory=list, description="Evidence ids supporting the entry"
    )
    kg_context: dict[str, Any] = Field(
        default_factory=dict, description="KG context associated with the entry"
    )
    tags: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)

        if "kg_context" not in data and isinstance(data.get("kg"), dict):
            data["kg_context"] = data.pop("kg")

        if "evidence_ids" not in data:
            if "evidence_id" in data:
                data["evidence_ids"] = _as_str_list(data.pop("evidence_id"))
            elif "evidence" in data:
                data["evidence_ids"] = _as_str_list(data.get("evidence"))

        prior = data.get("prior")
        if isinstance(prior, dict):
            data.setdefault(
                "prior_claim", prior.get("claim") or prior.get("hypothesis")
            )
            data.setdefault(
                "expected_effect",
                prior.get("expected_effect") or prior.get("effect"),
            )
            data.setdefault(
                "expected_direction",
                prior.get("expected_direction") or prior.get("direction"),
            )
            if (
                data.get("prior_confidence") is None
                and prior.get("confidence") is not None
            ):
                data["prior_confidence"] = prior.get("confidence")

        outcome = data.get("outcome")
        if isinstance(outcome, dict):
            data.setdefault(
                "observed_effect",
                outcome.get("observed_effect") or outcome.get("summary"),
            )
            if not data.get("failure_modes"):
                data["failure_modes"] = _as_str_list(outcome.get("failure_modes"))
            if data.get("decision") is None and outcome.get("decision") is not None:
                data["decision"] = outcome.get("decision")

        posterior = data.get("posterior")
        if isinstance(posterior, dict):
            if data.get("decision") is None and posterior.get("decision") is not None:
                data["decision"] = posterior.get("decision")
            if (
                data.get("posterior_confidence") is None
                and posterior.get("confidence") is not None
            ):
                data["posterior_confidence"] = posterior.get("confidence")
            if not data.get("failure_modes"):
                data["failure_modes"] = _as_str_list(posterior.get("failure_modes"))
            if not data.get("tags"):
                data["tags"] = _as_str_list(posterior.get("tags"))

        if "failure_mode" in data and not data.get("failure_modes"):
            data["failure_modes"] = _as_str_list(data.pop("failure_mode"))
        if "tag" in data and not data.get("tags"):
            data["tags"] = _as_str_list(data.pop("tag"))

        if isinstance(data.get("kg_context"), dict):
            data["kg_context"] = dict(data["kg_context"])

        return data


def branch_keys(entry: HypothesisEntryV1) -> set[str]:
    keys = {
        key.strip()
        for key in (entry.branch_id, entry.branch_name)
        if isinstance(key, str) and key.strip()
    }
    if not keys:
        keys.add(entry.hypothesis_id)
    return keys


def summarize_hypothesis_ledger(
    entries: Sequence[HypothesisEntryV1],
    *,
    branch_id: str | None = None,
) -> dict[str, Any]:
    relevant = [
        entry
        for entry in entries
        if branch_id is None or branch_id in branch_keys(entry)
    ]
    latest = relevant[-1] if relevant else None

    failure_modes: list[str] = []
    evidence_ids: list[str] = []
    tags: list[str] = []
    kg_context: dict[str, Any] = {}
    seen_failure_modes: set[str] = set()
    seen_evidence_ids: set[str] = set()
    seen_tags: set[str] = set()

    for entry in relevant:
        for failure_mode in entry.failure_modes:
            if failure_mode not in seen_failure_modes:
                seen_failure_modes.add(failure_mode)
                failure_modes.append(failure_mode)
        for evidence_id in entry.evidence_ids:
            if evidence_id not in seen_evidence_ids:
                seen_evidence_ids.add(evidence_id)
                evidence_ids.append(evidence_id)
        for tag in entry.tags:
            if tag not in seen_tags:
                seen_tags.add(tag)
                tags.append(tag)
        if entry.kg_context:
            kg_context.update(entry.kg_context)

    summary = {
        "count": len(relevant),
        "entries": relevant,
        "latest": latest,
        "failure_modes": failure_modes,
        "evidence_ids": evidence_ids,
        "tags": tags,
        "kg_context": kg_context,
        "decision": latest.decision if latest is not None else None,
        "posterior_confidence": (
            latest.posterior_confidence if latest is not None else None
        ),
    }
    return summary


__all__ = [
    "HypothesisEntryV1",
    "branch_keys",
    "summarize_hypothesis_ledger",
]
