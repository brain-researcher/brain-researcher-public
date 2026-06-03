"""Schemas and helpers for the derived memory layer."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

UTC = timezone.utc

RelationType = Literal[
    "supports",
    "contradicts",
    "conditions",
    "refines",
    "supersedes",
]

ClaimConfidence = Literal["preliminary", "moderate", "strong", "contested"]
ClaimSpecificity = Literal[
    "dataset_specific",
    "method_specific",
    "generalizable",
    "unknown",
]
ClaimStatus = Literal["active", "superseded"]
EpisodicStatus = Literal["success", "partial", "failed", "interrupted"]
MemoryCardType = Literal[
    "episodic_run_memory",
    "claim_memory",
    "claim_relation_event",
    "code_review_verdict",
]

MEMORY_CARD_TYPES = {
    "episodic_run_memory",
    "claim_memory",
    "claim_relation_event",
    "code_review_verdict",
}

_WORD_RE = re.compile(r"[a-z0-9_:+.-]+")
_EMBEDDING_DIMS = 64


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def normalize_space(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def unique_non_empty(values: list[Any] | tuple[Any, ...] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        text = normalize_space(raw)
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def normalize_token_text(value: Any) -> str:
    return normalize_space(value).lower()


def short_hash(*parts: Any, prefix: str, length: int = 16) -> str:
    joined = "||".join(
        normalize_token_text(part) for part in parts if normalize_space(part)
    )
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def tokenize_embedding_text(value: str) -> list[str]:
    return _WORD_RE.findall(normalize_token_text(value))


def build_embedding_vector(text: str, *, dims: int = _EMBEDDING_DIMS) -> list[float]:
    tokens = tokenize_embedding_text(text)
    if not tokens:
        return [0.0] * dims
    vector = [0.0] * dims
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = digest[0] % dims
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        weight = 1.0 + (digest[2] / 255.0)
        vector[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        return [0.0] * dims
    return [round(value / norm, 6) for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(float(a) * float(b) for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _status_or_unknown(value: Any) -> str | None:
    text = normalize_space(value)
    return text or None


class MemoryRecordBaseV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    card_id: str | None = None
    card_type: MemoryCardType
    created_at: str = Field(default_factory=utc_now_iso)
    stable_key: str | None = None
    tags: list[str] = Field(default_factory=list)
    embedding_text: str = ""
    embedding_vector: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize_common(self) -> MemoryRecordBaseV1:
        self.tags = unique_non_empty(self.tags)
        self.embedding_text = normalize_space(self.embedding_text)
        has_meaningful_vector = any(
            abs(float(value)) > 1e-12 for value in (self.embedding_vector or [])
        )
        if self.embedding_text and not has_meaningful_vector:
            self.embedding_vector = build_embedding_vector(self.embedding_text)
        elif not self.embedding_vector:
            self.embedding_vector = build_embedding_vector(self.embedding_text)
        return self


class ClaimEvidenceRefV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str | None = None
    session_id: str | None = None
    claim_id: str | None = None
    paper_id: str | None = None
    target_id: str | None = None
    polarity: str | None = None
    metric: str | None = None
    value: float | None = None
    confidence: str | None = None
    source_ref: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _normalize_values(self) -> ClaimEvidenceRefV1:
        self.run_id = _status_or_unknown(self.run_id)
        self.session_id = _status_or_unknown(self.session_id)
        self.claim_id = _status_or_unknown(self.claim_id)
        self.paper_id = _status_or_unknown(self.paper_id)
        self.target_id = _status_or_unknown(self.target_id)
        self.polarity = _status_or_unknown(self.polarity)
        self.metric = _status_or_unknown(self.metric)
        self.confidence = _status_or_unknown(self.confidence)
        self.source_ref = _status_or_unknown(self.source_ref)
        self.description = _status_or_unknown(self.description)
        return self

    def identity_key(self) -> str:
        return "||".join(
            [
                normalize_token_text(self.run_id),
                normalize_token_text(self.claim_id),
                normalize_token_text(self.paper_id),
                normalize_token_text(self.target_id),
                normalize_token_text(self.polarity),
                normalize_token_text(self.source_ref),
                normalize_token_text(self.description),
            ]
        )


class ClaimRelationLinkV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim_id: str
    relation: RelationType
    note: str | None = None

    @model_validator(mode="after")
    def _normalize(self) -> ClaimRelationLinkV1:
        self.claim_id = normalize_space(self.claim_id)
        self.note = _status_or_unknown(self.note)
        return self


class EpisodicRunMemoryV1(MemoryRecordBaseV1):
    card_type: Literal["episodic_run_memory"] = "episodic_run_memory"
    source_run_id: str
    source_session_id: str | None = None
    task_description: str
    task_type: str | None = None
    dataset_refs: list[str] = Field(default_factory=list)
    modality: list[str] = Field(default_factory=list)
    tool_sequence: list[str] = Field(default_factory=list)
    key_parameters: dict[str, Any] = Field(default_factory=dict)
    workflow_pattern: str | None = None
    status: EpisodicStatus
    output_summary: str
    failure_mode: str | None = None
    quality_indicators: dict[str, Any] = Field(default_factory=dict)
    what_worked: list[str] = Field(default_factory=list)
    what_failed: list[str] = Field(default_factory=list)
    next_time_hints: list[str] = Field(default_factory=list)
    resume_point: str | None = None
    provenance_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize(self) -> EpisodicRunMemoryV1:
        self.source_run_id = normalize_space(self.source_run_id)
        self.source_session_id = _status_or_unknown(self.source_session_id)
        self.task_description = normalize_space(self.task_description)
        self.task_type = _status_or_unknown(self.task_type)
        self.dataset_refs = unique_non_empty(self.dataset_refs)
        self.modality = unique_non_empty(self.modality)
        self.tool_sequence = unique_non_empty(self.tool_sequence)
        self.workflow_pattern = _status_or_unknown(self.workflow_pattern)
        self.output_summary = normalize_space(self.output_summary)
        self.failure_mode = _status_or_unknown(self.failure_mode)
        self.what_worked = unique_non_empty(self.what_worked)
        self.what_failed = unique_non_empty(self.what_failed)
        self.next_time_hints = unique_non_empty(self.next_time_hints)
        self.resume_point = _status_or_unknown(self.resume_point)
        self.provenance_refs = unique_non_empty(self.provenance_refs)
        if not self.stable_key:
            self.stable_key = f"episodic_run_memory:{self.source_run_id}"
        if not self.card_id:
            self.card_id = short_hash(self.stable_key, prefix="mem_epi")
        if not self.embedding_text:
            self.embedding_text = " | ".join(
                part
                for part in [
                    self.task_description,
                    self.output_summary,
                    " ".join(self.what_worked[:3]),
                    " ".join(self.what_failed[:3]),
                    " ".join(self.tags),
                ]
                if part
            )
        return super()._normalize_common()


class CodeReviewMemoryV1(MemoryRecordBaseV1):
    """Lightweight memory card written after each artifact-time code review."""

    card_type: Literal["code_review_verdict"] = "code_review_verdict"
    source_run_id: str
    workflow_id: str | None = None
    review_mode: str = "artifact"  # "plan" | "artifact"
    decision: str  # approve | approve_with_warnings | revise | block
    risk_level: str  # low | medium | high | critical
    finding_count: int = 0
    blocking_finding_count: int = 0
    # Domain stats surfaced at top level for search/index
    mean_fd: float | None = None
    r_squared: float | None = None
    flag_rate: float | None = None
    step_success_rate: float | None = None
    artifact_completeness_ratio: float | None = None

    @model_validator(mode="after")
    def _normalize_review(self) -> CodeReviewMemoryV1:
        self.source_run_id = normalize_space(self.source_run_id)
        if not self.stable_key:
            self.stable_key = f"code_review_verdict:{self.source_run_id}"
        if not self.card_id:
            self.card_id = short_hash(self.stable_key, prefix="mem_rev")
        if not self.embedding_text:
            parts = [f"code_review {self.decision} {self.risk_level}"]
            if self.workflow_id:
                parts.append(self.workflow_id)
            parts.append(self.source_run_id)
            self.embedding_text = " ".join(parts)
        return super()._normalize_common()


class ClaimMemoryV1(MemoryRecordBaseV1):
    card_type: Literal["claim_memory"] = "claim_memory"
    source_run_ids: list[str]
    source_session_ids: list[str] = Field(default_factory=list)
    claim_text: str
    claim_type: str | None = None
    claim_polarity: str | None = None
    domain: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    specificity: ClaimSpecificity = "unknown"
    analytic_conditions: list[str] = Field(default_factory=list)
    supporting_evidence: list[ClaimEvidenceRefV1] = Field(default_factory=list)
    conflicting_evidence: list[ClaimEvidenceRefV1] = Field(default_factory=list)
    confidence: ClaimConfidence = "preliminary"
    status: ClaimStatus = "active"
    last_tested_at: str | None = None
    times_tested: int = 1
    superseded_by: str | None = None
    related_claims: list[ClaimRelationLinkV1] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _normalize(self) -> ClaimMemoryV1:
        self.source_run_ids = unique_non_empty(self.source_run_ids)
        self.source_session_ids = unique_non_empty(self.source_session_ids)
        self.claim_text = normalize_space(self.claim_text)
        self.claim_type = _status_or_unknown(self.claim_type)
        self.claim_polarity = _status_or_unknown(self.claim_polarity)
        self.domain = _status_or_unknown(self.domain)
        self.target_ids = unique_non_empty(self.target_ids)
        self.analytic_conditions = unique_non_empty(self.analytic_conditions)
        self.superseded_by = _status_or_unknown(self.superseded_by)
        if not isinstance(self.extra, dict):
            self.extra = {}
        claim_updates = self.extra.get("claim_updates")
        if isinstance(claim_updates, list):
            deduped_updates: list[dict[str, Any]] = []
            seen_updates: set[str] = set()
            for item in claim_updates:
                if not isinstance(item, dict):
                    continue
                key = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if key in seen_updates:
                    continue
                seen_updates.add(key)
                deduped_updates.append(item)
            self.extra["claim_updates"] = deduped_updates
        if self.last_tested_at is None:
            self.last_tested_at = self.created_at
        if self.times_tested < 1:
            self.times_tested = max(1, len(self.source_run_ids))
        if not self.stable_key:
            preferred_identity = (
                next(
                    (
                        item.claim_id
                        for item in [
                            *self.supporting_evidence,
                            *self.conflicting_evidence,
                        ]
                        if item.claim_id
                    ),
                    None,
                )
                or None
            )
            if preferred_identity:
                self.stable_key = f"claim_memory:{preferred_identity}"
            else:
                self.stable_key = short_hash(
                    self.claim_text,
                    "|".join(self.target_ids),
                    prefix="claim_key",
                    length=24,
                )
        if not self.card_id:
            self.card_id = short_hash(self.stable_key, prefix="mem_claim")
        if not self.embedding_text:
            self.embedding_text = " | ".join(
                part
                for part in [
                    self.claim_text,
                    " ".join(self.target_ids),
                    " ".join(self.analytic_conditions),
                    " ".join(self.tags),
                ]
                if part
            )
        return super()._normalize_common()


class ClaimRelationEventV1(MemoryRecordBaseV1):
    card_type: Literal["claim_relation_event"] = "claim_relation_event"
    triggering_run_id: str | None = None
    lhs_claim_id: str
    rhs_claim_id: str
    relation_type: RelationType
    note: str | None = None
    evidence_refs: list[ClaimEvidenceRefV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize(self) -> ClaimRelationEventV1:
        self.triggering_run_id = _status_or_unknown(self.triggering_run_id)
        self.lhs_claim_id = normalize_space(self.lhs_claim_id)
        self.rhs_claim_id = normalize_space(self.rhs_claim_id)
        self.note = _status_or_unknown(self.note)
        if not self.stable_key:
            self.stable_key = "claim_relation_event:" + ":".join(
                [
                    normalize_token_text(self.triggering_run_id) or "no_run",
                    normalize_token_text(self.lhs_claim_id),
                    normalize_token_text(self.relation_type),
                    normalize_token_text(self.rhs_claim_id),
                ]
            )
        if not self.card_id:
            self.card_id = short_hash(self.stable_key, prefix="mem_rel")
        if not self.embedding_text:
            self.embedding_text = " | ".join(
                part
                for part in [
                    self.relation_type,
                    self.note or "",
                    self.lhs_claim_id,
                    self.rhs_claim_id,
                ]
                if part
            )
        return super()._normalize_common()


MemoryRecord = (
    EpisodicRunMemoryV1 | ClaimMemoryV1 | ClaimRelationEventV1 | CodeReviewMemoryV1
)


def build_memory_record(card_type: str, card_data: dict[str, Any]) -> MemoryRecord:
    payload = dict(card_data or {})
    payload.setdefault("card_type", card_type)
    normalized_card_type = normalize_space(card_type)
    if normalized_card_type == "episodic_run_memory":
        payload.setdefault(
            "source_run_id",
            short_hash(
                payload.get("task_description")
                or payload.get("output_summary")
                or utc_now_iso(),
                prefix="manual_run",
            ),
        )
        return EpisodicRunMemoryV1.model_validate(payload)
    if normalized_card_type == "claim_memory":
        payload.setdefault(
            "source_run_ids",
            [
                short_hash(
                    payload.get("claim_text") or utc_now_iso(),
                    prefix="manual_run",
                )
            ],
        )
        return ClaimMemoryV1.model_validate(payload)
    if normalized_card_type == "claim_relation_event":
        return ClaimRelationEventV1.model_validate(payload)
    if normalized_card_type == "code_review_verdict":
        return CodeReviewMemoryV1.model_validate(payload)
    raise ValueError(f"unsupported memory card type: {card_type}")


__all__ = [
    "ClaimConfidence",
    "ClaimEvidenceRefV1",
    "ClaimMemoryV1",
    "ClaimRelationEventV1",
    "ClaimRelationLinkV1",
    "CodeReviewMemoryV1",
    "ClaimSpecificity",
    "ClaimStatus",
    "EpisodicRunMemoryV1",
    "EpisodicStatus",
    "MEMORY_CARD_TYPES",
    "MemoryCardType",
    "MemoryRecord",
    "RelationType",
    "build_embedding_vector",
    "build_memory_record",
    "cosine_similarity",
    "normalize_space",
    "normalize_token_text",
    "short_hash",
    "unique_non_empty",
    "utc_now_iso",
]
