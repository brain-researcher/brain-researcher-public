#!/usr/bin/env python3
"""Trace BR anchor use in NeuroMetaBench Layer B artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

TRACE_FILENAME = "br_anchor_trace.json"
RECONCILIATION_ANCHORS_FILENAME = "br_reconciliation_anchors.json"
CANONICAL_RECONCILIATION_FIELDS = {
    "study_id",
    "study_pmid",
    "doi",
    "pmcid",
    "source_asset",
    "source_file",
    "sample_size",
    "coordinate_space",
    "original_study_ids",
}
ANCHOR_TARGET_ARTIFACTS = {
    "included_studies.csv",
    "coordinate_table.csv",
    "provenance_manifest.json",
    "spatial_report.md",
    "metrics.json",
    "pmid_study_reconciliation.json",
    "normalization_manifest.json",
}
PROVENANCE_CALL_KEYS = (
    "br_calls",
    "br_calls_made",
    "br_tool_calls",
    "brain_researcher_calls",
    "tool_calls",
    "tools_used",
)
BR_TOKEN_RE = re.compile(
    r"(brain[-_ ]researcher|mcp__brain|br[_-](?:kg|search|audit)|kg_search)",
    re.IGNORECASE,
)
PMID_TOKEN_RE = re.compile(r"\b\d{6,9}\b")
WORD_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9_-]{4,}\b")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _contains_br_token(value: Any) -> bool:
    return bool(BR_TOKEN_RE.search(_json_text(value)))


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}):
        return []
    return [value]


def _value_texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    texts = []
    for item in values:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            texts.append(text)
    return texts


def _contains_value(text: str, values: list[str]) -> bool:
    if not text or not values:
        return False
    haystack = text.lower()
    return any(value.lower() in haystack for value in values)


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _anchor_from_mapping(
    row: dict[str, Any],
    *,
    source: str,
    index: int,
    force_br: bool = False,
) -> dict[str, Any] | None:
    text = _json_text(row)
    tool = (
        row.get("tool")
        or row.get("tool_name")
        or row.get("name")
        or row.get("function")
        or row.get("server")
        or ""
    )
    if not force_br and not tool and not _contains_br_token(row):
        return None
    if (
        not force_br
        and tool
        and not _contains_br_token(tool)
        and not _contains_br_token(row)
    ):
        return None

    purpose = (
        row.get("purpose")
        or row.get("query")
        or row.get("input")
        or row.get("arguments")
        or row.get("description")
        or row.get("details")
        or row.get("notes")
        or ""
    )
    result_summary = (
        row.get("result_summary")
        or row.get("result")
        or row.get("output")
        or row.get("response")
        or row.get("summary")
        or row.get("outcome")
        or row.get("action")
        or row.get("impact")
        or row.get("details")
        or ""
    )
    changed_bundle = row.get("changed_bundle")
    if isinstance(changed_bundle, str):
        changed_bundle = changed_bundle.strip().lower() in {"true", "1", "yes"}
    elif not isinstance(changed_bundle, bool):
        changed_bundle = None
    return {
        "anchor_id": f"{source}:{index}",
        "source": source,
        "tool": str(tool) if tool else _infer_tool_name(text),
        "purpose": _stringify_short(purpose),
        "result_summary": _stringify_short(result_summary),
        "changed_bundle": changed_bundle,
        "anchor_text": _stringify_short(text, limit=2000),
    }


def _anchor_from_reconciliation_row(
    row: dict[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    canonical_value = row.get("canonical_value", row.get("value"))
    evidence_summary = (
        row.get("evidence_summary")
        or row.get("result_summary")
        or row.get("summary")
        or row.get("result")
        or ""
    )
    evidence_source = row.get("evidence_source") or row.get("source") or "BR MCP"
    changed_bundle = row.get("changed_bundle")
    if isinstance(changed_bundle, str):
        changed_bundle = changed_bundle.strip().lower() in {"true", "1", "yes"}
    elif not isinstance(changed_bundle, bool):
        changed_bundle = None
    return {
        "anchor_id": str(row.get("anchor_id") or f"br_reconciliation_anchors:{index}"),
        "source": "br_reconciliation_anchors",
        "tool": _stringify_short(evidence_source) or "BR MCP",
        "purpose": _stringify_short(row.get("purpose") or row.get("target_field") or ""),
        "result_summary": _stringify_short(evidence_summary),
        "changed_bundle": changed_bundle,
        "target_artifact": _stringify_short(row.get("target_artifact") or ""),
        "target_field": _stringify_short(row.get("target_field") or ""),
        "study_id": _stringify_short(row.get("study_id") or ""),
        "canonical_value": canonical_value,
        "confidence": _stringify_short(row.get("confidence") or ""),
        "anchor_text": _stringify_short(row, limit=2000),
    }


def _infer_tool_name(text: str) -> str:
    match = BR_TOKEN_RE.search(text)
    return match.group(0) if match else "unknown_br_tool"


def _stringify_short(value: Any, *, limit: int = 500) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else _json_text(value)
    text = " ".join(text.split())
    return text[:limit]


def _anchors_from_provenance(provenance_path: Path) -> list[dict[str, Any]]:
    data = _load_json(provenance_path)
    if not isinstance(data, dict):
        return []
    anchors: list[dict[str, Any]] = []
    candidate_rows: list[Any] = []
    for key in PROVENANCE_CALL_KEYS:
        candidate_rows.extend(_as_list(data.get(key)))

    for row in candidate_rows:
        if isinstance(row, dict):
            anchor = _anchor_from_mapping(
                row,
                source="provenance_manifest",
                index=len(anchors),
                force_br=True,
            )
            if anchor is not None:
                anchors.append(anchor)
        elif _contains_br_token(row):
            anchors.append(
                {
                    "anchor_id": f"provenance_manifest:{len(anchors)}",
                    "source": "provenance_manifest",
                    "tool": _infer_tool_name(str(row)),
                    "purpose": _stringify_short(row),
                    "result_summary": "",
                    "changed_bundle": None,
                    "anchor_text": _stringify_short(row, limit=2000),
                }
            )

    for row in _walk_dicts(data):
        if row in candidate_rows or any(key in row for key in PROVENANCE_CALL_KEYS):
            continue
        anchor = _anchor_from_mapping(
            row,
            source="provenance_manifest_nested",
            index=len(anchors),
        )
        if anchor is not None:
            anchors.append(anchor)
    return _dedupe_anchors(anchors)


def _anchors_from_json_file(path: Path, *, source: str) -> list[dict[str, Any]]:
    data = _load_json(path)
    anchors: list[dict[str, Any]] = []
    for row in _walk_dicts(data):
        anchor = _anchor_from_mapping(row, source=source, index=len(anchors))
        if anchor is not None:
            anchors.append(anchor)
    return _dedupe_anchors(anchors)


def _parse_reconciliation_anchor_payload(path: Path) -> tuple[Any, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"read_error:{type(exc).__name__}"
    except json.JSONDecodeError as exc:
        return None, f"json_decode_error:{exc.msg}"
    return data, None


def _anchor_rows_from_payload(data: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(data, dict):
        raw_rows = (
            data.get("anchors")
            or data.get("reconciliation_anchors")
            or data.get("br_reconciliation_anchors")
        )
    else:
        raw_rows = data
    if not isinstance(raw_rows, list):
        return [], "anchors_not_list"
    rows = [row for row in raw_rows if isinstance(row, dict)]
    if len(rows) != len(raw_rows):
        return rows, "non_object_anchor_rows"
    return rows, None


def _anchors_from_reconciliation_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data, error = _parse_reconciliation_anchor_payload(path)
    if error is not None:
        return []
    rows, _ = _anchor_rows_from_payload(data)
    return _dedupe_anchors(
        [
            _anchor_from_reconciliation_row(row, index=index)
            for index, row in enumerate(rows)
        ]
    )


def _anchors_from_stdout(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    anchors: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or not _contains_br_token(stripped):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = {"message": stripped}
        if isinstance(parsed, dict):
            anchor = _anchor_from_mapping(parsed, source="stdout_jsonl", index=len(anchors))
            if anchor is not None:
                anchors.append(anchor)
    return _dedupe_anchors(anchors)


def _dedupe_anchors(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for anchor in anchors:
        key = (
            str(anchor.get("tool") or ""),
            str(anchor.get("purpose") or ""),
            str(anchor.get("result_summary") or ""),
            str(anchor.get("target_field") or ""),
            str(anchor.get("canonical_value") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        anchor = dict(anchor)
        anchor["anchor_id"] = f"br_anchor_{len(deduped):04d}"
        deduped.append(anchor)
    return deduped


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _artifact_texts(case_dir: Path) -> dict[str, str]:
    texts = {
        "coordinate_table.csv": _csv_text(case_dir / "coordinate_table.csv"),
        "included_studies.csv": _csv_text(case_dir / "included_studies.csv"),
        "provenance_manifest.json": _read_text(case_dir / "provenance_manifest.json"),
        "spatial_report.md": _read_text(case_dir / "spatial_report.md"),
        "metrics.json": _read_text(case_dir / "metrics.json"),
        "pmid_study_reconciliation.json": _read_text(
            case_dir / "pmid_study_reconciliation.json"
        ),
        "normalization_manifest.json": _read_text(
            case_dir / "normalization_manifest.json"
        ),
        "normalized_artifacts/coordinate_table.normalized.csv": _csv_text(
            case_dir / "normalized_artifacts" / "coordinate_table.normalized.csv"
        ),
        "normalized_artifacts/included_studies.normalized.csv": _csv_text(
            case_dir / "normalized_artifacts" / "included_studies.normalized.csv"
        ),
    }
    return {key: value for key, value in texts.items() if value}


def _csv_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except csv.Error:
        return _read_text(path)
    return _json_text(rows)


def _tokens(anchor: dict[str, Any]) -> set[str]:
    text = " ".join(
        str(anchor.get(field) or "")
        for field in (
            "tool",
            "purpose",
            "result_summary",
            "target_artifact",
            "target_field",
            "study_id",
            "canonical_value",
            "anchor_text",
        )
    )
    tokens = set(PMID_TOKEN_RE.findall(text))
    tokens.update(token.lower() for token in WORD_TOKEN_RE.findall(text))
    return {
        token
        for token in tokens
        if token.lower()
        not in {
            "brain",
            "researcher",
            "result",
            "query",
            "tool",
            "calls",
            "called",
            "purpose",
            "source",
        }
    }


def _consumes(tokens: set[str], text: str) -> bool:
    if not tokens or not text:
        return False
    haystack = text.lower()
    return any(token.lower() in haystack for token in tokens)


def _add_consumption_flags(
    anchors: list[dict[str, Any]],
    *,
    case_dir: Path,
) -> list[dict[str, Any]]:
    artifact_texts = _artifact_texts(case_dir)
    provenance_text = artifact_texts.get("provenance_manifest.json", "")
    report_text = artifact_texts.get("spatial_report.md", "")
    artifact_text = "\n".join(
        text
        for key, text in artifact_texts.items()
        if key
        not in {
            "provenance_manifest.json",
            "spatial_report.md",
            "metrics.json",
        }
    )
    enriched = []
    for anchor in anchors:
        tokens = _tokens(anchor)
        changed_bundle = anchor.get("changed_bundle") is True
        canonical_values = _value_texts(anchor.get("canonical_value"))
        target_artifact = str(anchor.get("target_artifact") or "").strip()
        target_text = artifact_texts.get(target_artifact, "")
        if not target_text and target_artifact:
            target_text = artifact_texts.get(Path(target_artifact).name, "")
        value_in_report = _contains_value(report_text, canonical_values)
        value_in_artifact = _contains_value(artifact_text, canonical_values)
        value_in_target_artifact = _contains_value(target_text, canonical_values)
        explicit_contract_anchor = anchor.get("source") == "br_reconciliation_anchors"
        enriched_anchor = dict(anchor)
        enriched_anchor["consumed_by_provenance"] = (
            anchor.get("source", "").startswith("provenance_manifest")
            or _consumes(tokens, provenance_text)
        )
        enriched_anchor["consumed_by_report"] = (
            value_in_report if explicit_contract_anchor else _consumes(tokens, report_text)
        )
        enriched_anchor["consumed_by_artifact"] = (
            value_in_artifact or value_in_target_artifact
            if explicit_contract_anchor
            else changed_bundle or _consumes(tokens, artifact_text)
        )
        enriched_anchor["consumed_by_target_artifact"] = value_in_target_artifact
        enriched_anchor["anchor_tokens"] = sorted(tokens)[:40]
        enriched.append(enriched_anchor)
    return enriched


def _known_target_artifact(target_artifact: str) -> bool:
    if not target_artifact:
        return False
    return (
        target_artifact in ANCHOR_TARGET_ARTIFACTS
        or Path(target_artifact).name in ANCHOR_TARGET_ARTIFACTS
    )


def validate_br_reconciliation_anchors(case_dir: Path) -> dict[str, Any]:
    """Validate the explicit BR reconciliation anchor contract for one case."""

    case_dir = Path(case_dir)
    path = case_dir / RECONCILIATION_ANCHORS_FILENAME
    if not path.exists():
        return {
            "present": False,
            "path": None,
            "n_anchors": 0,
            "n_valid_anchors": 0,
            "n_valid_target_fields": 0,
            "n_consumed": 0,
            "n_changed_bundle": 0,
            "n_changed_consumed": 0,
            "pass": False,
            "invalid_reasons": ["missing_br_reconciliation_anchors_json"],
        }

    data, parse_error = _parse_reconciliation_anchor_payload(path)
    invalid_reasons: list[str] = []
    if parse_error is not None:
        return {
            "present": True,
            "path": str(path),
            "n_anchors": 0,
            "n_valid_anchors": 0,
            "n_valid_target_fields": 0,
            "n_consumed": 0,
            "n_changed_bundle": 0,
            "n_changed_consumed": 0,
            "pass": False,
            "invalid_reasons": [parse_error],
        }

    rows, row_error = _anchor_rows_from_payload(data)
    if row_error is not None:
        invalid_reasons.append(row_error)

    anchors = _add_consumption_flags(
        [
            _anchor_from_reconciliation_row(row, index=index)
            for index, row in enumerate(rows)
        ],
        case_dir=case_dir,
    )
    n_valid_target_fields = 0
    n_valid_anchors = 0
    n_consumed = 0
    n_changed_bundle = 0
    n_changed_consumed = 0
    anchor_results = []
    for anchor in anchors:
        reasons = []
        target_field = str(anchor.get("target_field") or "").strip()
        target_artifact = str(anchor.get("target_artifact") or "").strip()
        canonical_values = _value_texts(anchor.get("canonical_value"))
        consumed = bool(
            anchor.get("consumed_by_report")
            or anchor.get("consumed_by_artifact")
            or anchor.get("consumed_by_target_artifact")
        )
        changed_bundle = anchor.get("changed_bundle") is True
        if target_field not in CANONICAL_RECONCILIATION_FIELDS:
            reasons.append(f"invalid_target_field:{target_field or '<missing>'}")
        else:
            n_valid_target_fields += 1
        if not _known_target_artifact(target_artifact):
            reasons.append(f"invalid_target_artifact:{target_artifact or '<missing>'}")
        if not canonical_values:
            reasons.append("missing_canonical_value")
        if changed_bundle and not consumed:
            reasons.append("changed_bundle_anchor_not_consumed")
        if not reasons:
            n_valid_anchors += 1
        if consumed:
            n_consumed += 1
        if changed_bundle:
            n_changed_bundle += 1
            if consumed:
                n_changed_consumed += 1
        invalid_reasons.extend(reasons)
        anchor_results.append(
            {
                "anchor_id": anchor.get("anchor_id"),
                "target_field": target_field,
                "target_artifact": target_artifact,
                "canonical_value": anchor.get("canonical_value"),
                "changed_bundle": changed_bundle,
                "consumed": consumed,
                "consumed_by_report": anchor.get("consumed_by_report"),
                "consumed_by_artifact": anchor.get("consumed_by_artifact"),
                "consumed_by_target_artifact": anchor.get(
                    "consumed_by_target_artifact"
                ),
                "valid": not reasons,
                "invalid_reasons": reasons,
            }
        )

    n_anchors = len(anchors)
    contract_pass = (
        n_anchors > 0
        and n_valid_anchors == n_anchors
        and n_consumed > 0
        and n_changed_consumed == n_changed_bundle
    )
    return {
        "present": True,
        "path": str(path),
        "n_anchors": n_anchors,
        "n_valid_anchors": n_valid_anchors,
        "n_valid_target_fields": n_valid_target_fields,
        "n_consumed": n_consumed,
        "n_changed_bundle": n_changed_bundle,
        "n_changed_consumed": n_changed_consumed,
        "pass": contract_pass,
        "invalid_reasons": sorted(set(invalid_reasons)),
        "anchors": anchor_results,
    }


def trace_case_br_anchors(
    case_dir: Path,
    *,
    episode_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Write a per-case BR anchor trace and return the trace payload."""

    case_dir = Path(case_dir)
    output_dir = output_dir or case_dir
    anchors: list[dict[str, Any]] = []
    anchor_validation = validate_br_reconciliation_anchors(case_dir)
    anchors.extend(
        _anchors_from_reconciliation_file(case_dir / RECONCILIATION_ANCHORS_FILENAME)
    )
    anchors.extend(_anchors_from_provenance(case_dir / "provenance_manifest.json"))
    anchors.extend(_anchors_from_json_file(case_dir / "trajectory.json", source="trajectory"))
    if episode_dir is not None:
        episode_dir = Path(episode_dir)
        anchors.extend(_anchors_from_json_file(episode_dir / "trajectory.json", source="episode_trajectory"))
        anchors.extend(_anchors_from_stdout(episode_dir / "stdout.txt"))
    anchors = _dedupe_anchors(anchors)
    anchors = _add_consumption_flags(anchors, case_dir=case_dir)

    retrieved_or_audited = any(
        anchor.get("purpose") or anchor.get("result_summary") for anchor in anchors
    )
    consumed = any(
        anchor.get("consumed_by_report") or anchor.get("consumed_by_artifact")
        for anchor in anchors
    )
    non_contract_anchor_count = sum(
        1 for anchor in anchors if anchor.get("source") != "br_reconciliation_anchors"
    )
    br_call_count = non_contract_anchor_count or len(anchors)
    payload = {
        "case_dir": str(case_dir),
        "episode_dir": str(episode_dir) if episode_dir else None,
        "anchors": anchors,
        "summary": {
            "br_call_count": br_call_count,
            "br_anchor_count": len(anchors),
            "retrieved_or_audited_anchor_present": retrieved_or_audited,
            "artifact_or_report_consumes_br_result": consumed,
            "br_effective_use_pass": bool(anchors) and retrieved_or_audited and consumed,
            "br_reconciliation_anchor_present": anchor_validation["present"],
            "br_reconciliation_anchor_count": anchor_validation["n_anchors"],
            "br_reconciliation_anchor_valid_count": anchor_validation[
                "n_valid_anchors"
            ],
            "br_reconciliation_anchor_consumed_count": anchor_validation[
                "n_consumed"
            ],
            "br_reconciliation_anchor_changed_count": anchor_validation[
                "n_changed_bundle"
            ],
            "br_reconciliation_anchor_changed_consumed_count": anchor_validation[
                "n_changed_consumed"
            ],
            "br_reconciliation_anchor_pass": anchor_validation["pass"],
            "n_consumed_by_provenance": sum(
                1 for anchor in anchors if anchor.get("consumed_by_provenance")
            ),
            "n_consumed_by_report": sum(
                1 for anchor in anchors if anchor.get("consumed_by_report")
            ),
            "n_consumed_by_artifact": sum(
                1 for anchor in anchors if anchor.get("consumed_by_artifact")
            ),
        },
        "br_reconciliation_anchors": anchor_validation,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / TRACE_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--episode-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    payload = trace_case_br_anchors(
        args.case_dir,
        episode_dir=args.episode_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
