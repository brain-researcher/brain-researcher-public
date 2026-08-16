"""Injected source-intake adapters for public TRIBE v2 materialization.

No remote collection, annotation endpoint, or audio path is embedded here.
Callers provide their own catalog and byte-fetch or render adapters.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import CONDITIONS


class SourceIntakeError(ValueError):
    """A caller-supplied source localization is incomplete or inconsistent."""


class SourceRenderPolicyBlocked(SourceIntakeError):
    """The caller declined a requested source rendering operation."""


@dataclass(frozen=True, slots=True)
class CandidateLocalization:
    collection_key: str
    parent_key: str
    condition: str
    annotation_key: str
    start_seconds: float
    end_seconds: float
    member_key: str | None = None


def _text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceIntakeError(f"{label} must be non-empty text")
    return value.strip()


def localize_annotation(record: Mapping[str, Any]) -> CandidateLocalization:
    """Turn one caller-provided annotation record into a typed localization."""

    if not isinstance(record, Mapping):
        raise SourceIntakeError("annotation record must be an object")
    condition = _text(record.get("condition"), label="condition")
    if condition not in CONDITIONS:
        raise SourceIntakeError("condition must be speech or tools")
    start = record.get("start_seconds")
    end = record.get("end_seconds")
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int | float)
        or not isinstance(end, int | float)
        or not float(start) >= 0.0
        or not float(end) > float(start)
    ):
        raise SourceIntakeError("annotation interval must be finite and ordered")
    member = record.get("member_key")
    if member is not None:
        member = _text(member, label="member_key")
    return CandidateLocalization(
        collection_key=_text(record.get("collection_key"), label="collection_key"),
        parent_key=_text(record.get("parent_key"), label="parent_key"),
        condition=condition,
        annotation_key=_text(record.get("annotation_key"), label="annotation_key"),
        start_seconds=float(start),
        end_seconds=float(end),
        member_key=member,
    )


def fetch_selected_member(
    localization: CandidateLocalization,
    *,
    fetch_member: Callable[[str], bytes],
) -> bytes:
    """Fetch one explicit member through the caller-provided transport adapter."""

    if localization.member_key is None:
        raise SourceIntakeError("localization has no member_key")
    payload = fetch_member(localization.member_key)
    if not isinstance(payload, bytes) or not payload:
        raise SourceIntakeError("fetch_member must return non-empty bytes")
    return payload


def render_annotation_localization(
    localization: CandidateLocalization,
    *,
    render_interval: Callable[[CandidateLocalization], bytes],
    allow_render: bool,
) -> bytes:
    """Render one annotation interval only when the caller grants that action."""

    if not allow_render:
        raise SourceRenderPolicyBlocked("rendering requires explicit caller permission")
    payload = render_interval(localization)
    if not isinstance(payload, bytes) or not payload:
        raise SourceIntakeError("render_interval must return non-empty bytes")
    return payload


__all__ = [
    "CandidateLocalization",
    "SourceIntakeError",
    "SourceRenderPolicyBlocked",
    "fetch_selected_member",
    "localize_annotation",
    "render_annotation_localization",
]
