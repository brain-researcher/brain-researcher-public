#!/usr/bin/env python3
"""Normalize external Layer A model artifacts into prediction JSONL.

This module is an adapter scaffold. It reads artifacts already produced by a
reasoning-only model or coding agent and writes the standard Layer A prediction
records consumed by ``evaluate_study_set.py``. It does not call model CLIs,
network APIs, or live agent runtimes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ADAPTER_NAME = "neurometabench_v1_layer_a_model_adapter"
INPUT_FORMATS = ("decision_records_jsonl", "prediction_jsonl", "run_bundle")


@dataclass(frozen=True)
class SelectedInput:
    path: Path
    input_format: str
    rows: list[dict[str, Any]]
    selected_from: str


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no} is not a JSON object")
            rows.append(payload)
    return rows


def _write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _first_present(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            return value
    return None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: OrderedDict[str, None] = OrderedDict()
    for value in values:
        text = _clean_str(value)
        if text:
            seen.setdefault(text, None)
    return list(seen.keys())


def _as_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return [_clean_str(value)] if _clean_str(value) else []

    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = _first_present(
                item,
                (
                    "criterion_id",
                    "criterion_ids",
                    "id",
                    "criterion",
                    "text",
                    "span",
                    "quote",
                    "label",
                    "name",
                ),
            )
        else:
            text = item
        text = _clean_str(text)
        if text:
            out.append(text)
    return _dedupe_preserve_order(out)


def _pmid_from_item(item: Any) -> str:
    if isinstance(item, dict):
        item = _first_present(item, ("pmid", "study_pmid", "id"))
    return _clean_str(item)


def _pmid_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        pmid = _pmid_from_item(value)
        return [pmid] if pmid else []
    return _dedupe_preserve_order([_pmid_from_item(item) for item in value])


def _normalize_decision(value: Any) -> str:
    text = _clean_str(value).lower()
    if text in {"include", "included", "yes", "y", "true", "1", "selected"}:
        return "include"
    if text in {"exclude", "excluded", "no", "n", "false", "0", "reject", "rejected"}:
        return "exclude"
    if text in {"uncertain", "unsure", "maybe", "unknown", "borderline"}:
        return "uncertain"
    return "uncertain"


def _normalize_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, score))


def normalize_decision_record(row: dict[str, Any]) -> dict[str, Any]:
    """Return one normalized candidate decision record."""

    pmid = _clean_str(_first_present(row, ("pmid", "study_pmid", "id")))
    criterion_value = _first_present(
        row, ("criterion_ids", "criterion_refs", "criterion_hits")
    )
    out: dict[str, Any] = {
        "pmid": pmid,
        "decision": _normalize_decision(row.get("decision")),
        "reason": _clean_str(
            _first_present(row, ("reason", "rationale", "explanation"))
        ),
        "evidence_spans": _as_string_list(
            _first_present(row, ("evidence_spans", "evidence_span", "quotes", "quote"))
        ),
        "criterion_ids": _as_string_list(criterion_value),
        "confidence": _normalize_confidence(row.get("confidence")),
    }
    for field in ("title", "abstract", "doi"):
        value = _clean_str(row.get(field))
        if value:
            out[field] = value
    return out


def _resolve_execution_mode(
    rows: list[dict[str, Any]],
    execution_mode: str | None,
) -> str:
    if execution_mode:
        return execution_mode
    source_modes = _unique_non_empty(row.get("execution_mode") for row in rows)
    if len(source_modes) == 1:
        return source_modes[0]
    return "unknown"


def _unique_non_empty(values: Any) -> list[str]:
    return _dedupe_preserve_order([_clean_str(value) for value in values])


def _case_key(
    row: dict[str, Any], case_id: str | None, meta_pmid: str | None
) -> tuple[str, str]:
    row_case_id = _clean_str(row.get("case_id") or case_id)
    row_meta_pmid = _clean_str(row.get("meta_pmid") or meta_pmid)
    return row_case_id, row_meta_pmid


def _adapter_provenance(
    *,
    input_path: Path,
    input_format: str,
    system: str,
    execution_mode: str,
    candidate_source: str | None,
    selected_input: SelectedInput | None = None,
    source_rows: list[dict[str, Any]] | None = None,
    existing: Any = None,
) -> dict[str, Any]:
    provenance = dict(existing) if isinstance(existing, dict) else {}
    rows = source_rows or []
    source_systems = _unique_non_empty(row.get("system") for row in rows)
    source_execution_modes = _unique_non_empty(
        row.get("execution_mode") for row in rows
    )
    provenance.update(
        {
            "adapter": ADAPTER_NAME,
            "adapter_version": 1,
            "system": system,
            "input_path": str(input_path),
            "input_format": input_format,
            "execution_mode": execution_mode,
        }
    )
    if candidate_source:
        provenance["candidate_source"] = candidate_source
    if source_systems:
        provenance["source_systems"] = source_systems
    if source_execution_modes:
        provenance["source_execution_modes"] = source_execution_modes
    if selected_input is not None:
        provenance["run_bundle_input_path"] = str(input_path)
        provenance["selected_input_path"] = str(selected_input.path)
        provenance["selected_input_format"] = selected_input.input_format
    return provenance


def _prediction_pmids_from_decisions(
    decision_records: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    ranked_pmids = _dedupe_preserve_order(
        [row.get("pmid", "") for row in decision_records]
    )
    included_pmids = _dedupe_preserve_order(
        [
            row.get("pmid", "")
            for row in decision_records
            if row.get("decision") == "include" and row.get("pmid")
        ]
    )
    return ranked_pmids, included_pmids


def _normalize_decision_predictions(
    rows: list[dict[str, Any]],
    *,
    input_path: Path,
    input_format: str,
    system: str,
    case_id: str | None,
    meta_pmid: str | None,
    execution_mode: str | None,
    candidate_source: str | None,
    selected_input: SelectedInput | None,
) -> list[dict[str, Any]]:
    grouped: OrderedDict[tuple[str, str], list[dict[str, Any]]] = OrderedDict()
    source_rows_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        pmid = _clean_str(_first_present(row, ("pmid", "study_pmid", "id")))
        if not pmid:
            continue
        key = _case_key(row, case_id, meta_pmid)
        grouped.setdefault(key, []).append(normalize_decision_record(row))
        source_rows_by_key.setdefault(key, []).append(row)

    predictions: list[dict[str, Any]] = []
    for (row_case_id, row_meta_pmid), decision_records in grouped.items():
        source_rows = source_rows_by_key[(row_case_id, row_meta_pmid)]
        resolved_execution_mode = _resolve_execution_mode(source_rows, execution_mode)
        ranked_pmids, included_pmids = _prediction_pmids_from_decisions(
            decision_records
        )
        prediction: dict[str, Any] = {
            "case_id": row_case_id or None,
            "meta_pmid": row_meta_pmid or None,
            "system": system,
            "execution_mode": resolved_execution_mode,
            "included_pmids": included_pmids,
            "predicted_pmids": included_pmids,
            "ranked_pmids": ranked_pmids,
            "decision_records": decision_records,
            "provenance": _adapter_provenance(
                input_path=input_path,
                input_format=input_format,
                system=system,
                execution_mode=resolved_execution_mode,
                candidate_source=candidate_source,
                selected_input=selected_input,
                source_rows=source_rows,
            ),
        }
        if candidate_source:
            prediction["candidate_source"] = candidate_source
        predictions.append(prediction)
    return predictions


def _normalize_prediction_row(
    row: dict[str, Any],
    *,
    input_path: Path,
    input_format: str,
    system: str,
    case_id: str | None,
    meta_pmid: str | None,
    execution_mode: str | None,
    candidate_source: str | None,
    selected_input: SelectedInput | None,
) -> dict[str, Any]:
    out = dict(row)
    row_case_id = _clean_str(row.get("case_id") or case_id)
    row_meta_pmid = _clean_str(row.get("meta_pmid") or meta_pmid)
    raw_records = row.get("decision_records")
    if isinstance(raw_records, list):
        decision_records = [
            normalize_decision_record(record)
            for record in raw_records
            if isinstance(record, dict)
            and _clean_str(_first_present(record, ("pmid", "study_pmid", "id")))
        ]
    else:
        decision_records = []

    ranked_pmids = _pmid_list(_first_present(row, ("ranked_pmids", "candidate_pmids")))
    included_pmids = _pmid_list(
        _first_present(
            row,
            (
                "included_pmids",
                "predicted_pmids",
                "selected_pmids",
                "study_pmids",
                "pmids",
            ),
        )
    )
    if not ranked_pmids and decision_records:
        ranked_pmids, decision_includes = _prediction_pmids_from_decisions(
            decision_records
        )
        if not included_pmids:
            included_pmids = decision_includes
    if not ranked_pmids:
        ranked_pmids = list(included_pmids)

    resolved_execution_mode = _resolve_execution_mode([row], execution_mode)
    out.update(
        {
            "case_id": row_case_id or None,
            "meta_pmid": row_meta_pmid or None,
            "system": system,
            "execution_mode": resolved_execution_mode,
            "included_pmids": included_pmids,
            "predicted_pmids": included_pmids,
            "ranked_pmids": ranked_pmids,
            "decision_records": decision_records,
            "provenance": _adapter_provenance(
                input_path=input_path,
                input_format=input_format,
                system=system,
                execution_mode=resolved_execution_mode,
                candidate_source=candidate_source,
                selected_input=selected_input,
                source_rows=[row],
                existing=row.get("provenance"),
            ),
        }
    )
    if candidate_source:
        out["candidate_source"] = candidate_source
    return out


def _normalize_prediction_predictions(
    rows: list[dict[str, Any]],
    *,
    input_path: Path,
    input_format: str,
    system: str,
    case_id: str | None,
    meta_pmid: str | None,
    execution_mode: str | None,
    candidate_source: str | None,
    selected_input: SelectedInput | None,
) -> list[dict[str, Any]]:
    return [
        _normalize_prediction_row(
            row,
            input_path=input_path,
            input_format=input_format,
            system=system,
            case_id=case_id,
            meta_pmid=meta_pmid,
            execution_mode=execution_mode,
            candidate_source=candidate_source,
            selected_input=selected_input,
        )
        for row in rows
    ]


def _extract_json_records(path: Path) -> tuple[str, list[dict[str, Any]]] | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        if _looks_like_prediction_rows(payload):
            return "prediction_jsonl", list(payload)
        if _looks_like_decision_rows(payload):
            return "decision_records_jsonl", list(payload)
        return None
    if not isinstance(payload, dict):
        return None

    prediction_keys = ("predictions", "prediction", "layer_a_predictions")
    decision_keys = (
        "screening_decisions",
        "decisions",
        "decision_records",
        "candidate_decisions",
    )
    for key in prediction_keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return "prediction_jsonl", [value]
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return "prediction_jsonl", list(value)
    for key in decision_keys:
        value = payload.get(key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return "decision_records_jsonl", list(value)
    return None


def _looks_like_prediction_rows(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    prediction_keys = {
        "ranked_pmids",
        "included_pmids",
        "predicted_pmids",
        "selected_pmids",
        "candidate_pmids",
        "decision_records",
    }
    return any(any(key in row for key in prediction_keys) for row in rows)


def _looks_like_decision_rows(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    return any(
        _first_present(row, ("pmid", "study_pmid", "id")) and "decision" in row
        for row in rows
    )


def _read_run_bundle_candidate(
    path: Path, input_format: str
) -> list[dict[str, Any]] | None:
    if input_format in {"prediction_jsonl", "decision_records_jsonl"}:
        rows = _read_jsonl(path)
        if input_format == "prediction_jsonl" and _looks_like_prediction_rows(rows):
            return rows
        if input_format == "decision_records_jsonl" and _looks_like_decision_rows(rows):
            return rows
        return None

    extracted = _extract_json_records(path)
    if extracted is None:
        return None
    _, rows = extracted
    return rows


def select_run_bundle_input(bundle_dir: Path) -> SelectedInput:
    """Choose the first evaluable prediction or decision artifact in a run bundle."""

    candidates = (
        ("predictions.jsonl", "prediction_jsonl"),
        ("layer_a_predictions.jsonl", "prediction_jsonl"),
        ("screening_decisions.jsonl", "decision_records_jsonl"),
        ("decision_records.jsonl", "decision_records_jsonl"),
        ("trajectory.json", "json"),
        ("observation.json", "json"),
    )
    if not bundle_dir.is_dir():
        raise ValueError(f"run_bundle input must be a directory: {bundle_dir}")

    for filename, input_format in candidates:
        path = bundle_dir / filename
        if not path.exists() or not path.is_file():
            continue
        if input_format == "json":
            extracted = _extract_json_records(path)
            if extracted is None:
                continue
            selected_format, rows = extracted
        else:
            rows = _read_run_bundle_candidate(path, input_format)
            if rows is None:
                continue
            selected_format = input_format
        return SelectedInput(
            path=path,
            input_format=selected_format,
            rows=rows,
            selected_from="run_bundle",
        )
    raise FileNotFoundError(
        f"No evaluable Layer A prediction or decision artifact found in {bundle_dir}"
    )


def adapt_model_outputs(
    input_path: Path,
    output_path: Path,
    *,
    input_format: str,
    system: str,
    case_id: str | None = None,
    meta_pmid: str | None = None,
    execution_mode: str | None = None,
    candidate_source: str | None = None,
) -> dict[str, Any]:
    """Normalize existing model artifacts into Layer A prediction JSONL."""

    if input_format not in INPUT_FORMATS:
        raise ValueError(f"Unsupported input_format={input_format!r}")

    selected_input: SelectedInput | None = None
    effective_input_path = input_path
    effective_input_format = input_format
    if input_format == "run_bundle":
        selected_input = select_run_bundle_input(input_path)
        rows = selected_input.rows
        effective_input_path = selected_input.path
        effective_input_format = selected_input.input_format
    else:
        rows = _read_jsonl(input_path)

    if effective_input_format == "decision_records_jsonl":
        predictions = _normalize_decision_predictions(
            rows,
            input_path=input_path,
            input_format=input_format,
            system=system,
            case_id=case_id,
            meta_pmid=meta_pmid,
            execution_mode=execution_mode,
            candidate_source=candidate_source,
            selected_input=selected_input,
        )
    elif effective_input_format == "prediction_jsonl":
        predictions = _normalize_prediction_predictions(
            rows,
            input_path=input_path,
            input_format=input_format,
            system=system,
            case_id=case_id,
            meta_pmid=meta_pmid,
            execution_mode=execution_mode,
            candidate_source=candidate_source,
            selected_input=selected_input,
        )
    else:
        raise ValueError(
            f"Unsupported selected input_format={effective_input_format!r}"
        )

    _write_jsonl(predictions, output_path)
    return {
        "adapter": ADAPTER_NAME,
        "input": str(input_path),
        "output": str(output_path),
        "input_format": input_format,
        "effective_input": str(effective_input_path),
        "effective_input_format": effective_input_format,
        "system": system,
        "execution_mode": execution_mode or "auto",
        "candidate_source": candidate_source,
        "n_source_rows": len(rows),
        "n_predictions": len(predictions),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input JSONL file or run-bundle directory.",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Output prediction JSONL path."
    )
    parser.add_argument("--input-format", choices=INPUT_FORMATS, required=True)
    parser.add_argument(
        "--system",
        required=True,
        help="Normalized system label to write on predictions.",
    )
    parser.add_argument(
        "--case-id", help="Fallback case_id for rows that do not include one."
    )
    parser.add_argument(
        "--meta-pmid", help="Fallback meta_pmid for rows that do not include one."
    )
    parser.add_argument(
        "--execution-mode",
        help="Reasoning/execution mode label, for example reasoning_only or coding_agent.",
    )
    parser.add_argument(
        "--candidate-source",
        help="Candidate pool/source label to attach to predictions.",
    )
    args = parser.parse_args(argv)

    summary = adapt_model_outputs(
        args.input,
        args.output,
        input_format=args.input_format,
        system=args.system,
        case_id=args.case_id,
        meta_pmid=args.meta_pmid,
        execution_mode=args.execution_mode,
        candidate_source=args.candidate_source,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
