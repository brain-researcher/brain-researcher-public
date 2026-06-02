"""Evidence item contract (v1).

Evidence items are UI- and benchmark-friendly pointers to things the agent used
or produced (KG hits, web snippets, files, tool outputs).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .epistemic import EvidenceProvenanceV1


class EvidenceType(str, Enum):
    kg = "kg"
    web = "web"
    file = "file"
    tool = "tool"
    artifact = "artifact"


class QuoteSpanV1(BaseModel):
    """Span metadata that locates a quote within an evidence payload."""

    # 0-based, end-exclusive character offsets into the payload text.
    start_char: int
    end_char: int

    # Optional line ranges (1-based) for UIs that prefer line highlighting.
    start_line: int | None = None
    end_line: int | None = None

    # Optional content hash for integrity checks.
    text_sha256: str | None = None


class EvidenceItemV1(BaseModel):
    schema_version: Literal["evidence-item-v1"] = "evidence-item-v1"

    evidence_id: str
    type: EvidenceType

    ref: str = Field(
        description="A stable reference (path/url/id) usable to locate the evidence"
    )
    payload_ref: str | None = Field(
        default=None, description="Optional pointer to a payload blob (file/uri)"
    )
    quote_span: QuoteSpanV1 | dict[str, Any] | None = Field(
        default=None,
        description="Optional quote span metadata (e.g., line range, char offsets)",
    )

    confidence: float | None = None
    evidence_provenance: EvidenceProvenanceV1 | None = Field(
        default=None,
        description="Whether this evidence is direct single-study support, a cross-study inference input, or a theory-only artifact.",
    )
    raw_data_available: bool | None = Field(
        default=None,
        description="Whether original raw data are available for this evidence item.",
    )
    direct_statistical_test: bool | None = Field(
        default=None,
        description="Whether this evidence contains a direct statistical test of the linked claim.",
    )
    provenance_ref: str | None = Field(
        default=None, description="Pointer to the producing tool call/provenance"
    )

    extra: dict[str, Any] = Field(default_factory=dict)


__all__ = ["EvidenceItemV1", "EvidenceType", "QuoteSpanV1"]
