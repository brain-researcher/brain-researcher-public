"""Shared helpers for stable browse/resolve asset provenance records."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"[^a-z0-9]+")

_NODE_TO_LEVEL = {
    "runlevel": "run",
    "sessionlevel": "session",
    "subjectlevel": "subject",
    "datasetlevel": "dataset",
    "datalevel": "dataset",
    "grouplevel": "group",
}


def _normalize_token(value: Any) -> str:
    return _TOKEN_RE.sub("", str(value or "").strip().lower())


def _normalize_subject_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("sub-"):
        return text
    return f"sub-{text}"


def _normalize_session_id(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("ses-"):
        return text
    return f"ses-{text}"


def infer_level(level: str | None = None, node: str | None = None) -> str:
    explicit = str(level or "").strip()
    if explicit:
        return explicit
    return _NODE_TO_LEVEL.get(_normalize_token(node), "")


def _coerce_roots(roots: Iterable[str | Path | None]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root:
            continue
        try:
            candidate = Path(root).expanduser().resolve()
        except Exception:
            candidate = Path(root).expanduser()
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def relative_path_for(
    source_path: str | Path | None,
    *,
    roots: Iterable[str | Path | None] = (),
) -> str:
    if not source_path:
        return ""
    try:
        candidate = Path(source_path).expanduser().resolve()
    except Exception:
        candidate = Path(source_path).expanduser()
    for root in _coerce_roots(roots):
        try:
            return str(candidate.relative_to(root))
        except Exception:
            continue
    return ""


def build_canonical_id(
    *,
    kind: str,
    preferred_id: str | None = None,
    dataset_id: str | None = None,
    derivative_kind: str | None = None,
    subject_id: str | None = None,
    session_id: str | None = None,
    task: str | None = None,
    run: str | None = None,
    datatype: str | None = None,
    suffix: str | None = None,
    space: str | None = None,
    contrast: str | None = None,
    statistic: str | None = None,
    level: str | None = None,
    basename: str | None = None,
) -> str:
    preferred = str(preferred_id or "").strip()
    if preferred:
        return preferred

    parts = [
        str(kind or "").strip().lower(),
        str(dataset_id or "").strip().lower(),
        str(derivative_kind or "").strip().lower(),
        _normalize_subject_id(subject_id).lower(),
        _normalize_session_id(session_id).lower(),
        str(task or "").strip().lower(),
        str(run or "").strip().lower(),
        str(datatype or "").strip().lower(),
        str(suffix or "").strip().lower(),
        str(space or "").strip().lower(),
        str(contrast or "").strip().lower(),
        str(statistic or "").strip().lower(),
        str(infer_level(level, None) or "").strip().lower(),
    ]
    normalized = [_normalize_token(part) for part in parts if str(part or "").strip()]
    if not normalized and basename:
        normalized.append(_normalize_token(basename))
    if not normalized:
        normalized.append(_normalize_token(kind or "asset"))
    return ":".join(normalized)


def compact_manifest_fields(
    metadata: dict[str, Any] | None,
    *,
    exclude: Iterable[str] = (),
) -> dict[str, Any]:
    payload = dict(metadata or {})
    excluded = {str(key) for key in exclude}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in excluded:
            continue
        if value is None or value == "" or value == [] or value == {}:
            continue
        out[str(key)] = value
    return out


def build_provenance_record(
    *,
    kind: str,
    preferred_id: str | None = None,
    source: str | None = None,
    source_path: str | Path | None = None,
    roots: Iterable[str | Path | None] = (),
    dataset_id: str | None = None,
    derivative_kind: str | None = None,
    subject_id: str | None = None,
    session_id: str | None = None,
    task: str | None = None,
    run: str | None = None,
    datatype: str | None = None,
    suffix: str | None = None,
    space: str | None = None,
    contrast: str | None = None,
    statistic: str | None = None,
    level: str | None = None,
    estimator: str | None = None,
    checksum: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_fields = compact_manifest_fields(
        metadata,
        exclude={
            "dataset_id",
            "derivative_kind",
            "subject_id",
            "session_id",
            "task",
            "run",
            "datatype",
            "suffix",
            "space",
            "contrast",
            "statistic",
            "level",
            "estimator",
            "checksum",
            "sha256",
            "source",
        },
    )
    src_path = str(source_path or "").strip()
    path_name = Path(src_path).name if src_path else ""
    normalized_level = infer_level(level, metadata.get("node") if metadata else None)
    return {
        "canonical_id": build_canonical_id(
            kind=kind,
            preferred_id=preferred_id,
            dataset_id=dataset_id,
            derivative_kind=derivative_kind,
            subject_id=subject_id,
            session_id=session_id,
            task=task,
            run=run,
            datatype=datatype,
            suffix=suffix,
            space=space,
            contrast=contrast,
            statistic=statistic,
            level=normalized_level,
            basename=path_name,
        ),
        "source": str(source or "").strip(),
        "source_path": src_path,
        "relative_path": relative_path_for(src_path, roots=roots),
        "checksum": str(
            checksum
            or (metadata or {}).get("checksum")
            or (metadata or {}).get("sha256")
            or ""
        ).strip(),
        "level": normalized_level,
        "estimator": str(estimator or (metadata or {}).get("estimator") or "").strip(),
        "manifest_fields": manifest_fields,
    }
