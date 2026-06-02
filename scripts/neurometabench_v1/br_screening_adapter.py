#!/usr/bin/env python3
"""Convert BR NeurometaBench screening outputs to v1 prediction JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.shared import DEFAULT_CASES_PATH, case_lookup, load_case_records, write_jsonl


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_br_screening_anchors(case_dir: Path) -> list[dict[str, Any]]:
    path = case_dir / "br_screening_anchors.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    anchors = payload.get("anchors") if isinstance(payload, dict) else payload
    if not isinstance(anchors, list):
        return []
    return [anchor for anchor in anchors if isinstance(anchor, dict)]


def _meta_pmid_from_case_dir(case_dir: Path) -> str:
    meta_pmid = case_dir.name
    results_path = case_dir / "results.json"
    if results_path.exists():
        try:
            payload = json.loads(results_path.read_text(encoding="utf-8"))
            meta_pmid = str(payload.get("meta_pmid") or meta_pmid)
        except Exception:
            pass
    return meta_pmid


def _discover_case_dirs(br_output_dir: Path) -> list[tuple[str, Path]]:
    if (br_output_dir / "screening_decisions.jsonl").exists():
        return [(_meta_pmid_from_case_dir(br_output_dir), br_output_dir)]

    case_dirs: list[tuple[str, Path]] = []
    if not br_output_dir.exists():
        return case_dirs
    for child in sorted(br_output_dir.iterdir()):
        if child.is_dir() and (child / "screening_decisions.jsonl").exists():
            case_dirs.append((_meta_pmid_from_case_dir(child), child))
    return case_dirs


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return [str(value)]
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = item.get("text") or item.get("span") or item.get("quote")
        else:
            text = item
        if text is not None and str(text).strip():
            out.append(str(text).strip())
    return out


def _normalize_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, score))


def normalize_screening_decision(row: dict[str, Any]) -> dict[str, Any]:
    decision = str(row.get("decision") or "uncertain").strip().lower()
    if decision not in {"include", "exclude", "uncertain"}:
        decision = "uncertain"
    pmid = str(row.get("pmid") or row.get("study_pmid") or "").strip()
    return {
        "pmid": pmid,
        "decision": decision,
        "title": str(row.get("title") or "").strip(),
        "abstract": str(row.get("abstract") or "").strip(),
        "criterion_ids": _as_string_list(row.get("criterion_ids") or row.get("criterion_refs")),
        "evidence_spans": _as_string_list(row.get("evidence_spans") or row.get("evidence_span")),
        "reason": str(row.get("reason") or row.get("rationale") or "").strip(),
        "confidence": _normalize_confidence(row.get("confidence")),
    }


def convert_br_screening_outputs(
    cases_path: Path,
    br_output_dir: Path,
    output: Path,
    *,
    candidate_source: str = "unknown",
) -> dict[str, Any]:
    predictions: list[dict[str, Any]] = []
    cases = case_lookup(load_case_records(cases_path))
    for meta_pmid, case_dir in _discover_case_dirs(br_output_dir):
        case = cases.get(meta_pmid)
        if case is None:
            continue
        screening_path = case_dir / "screening_decisions.jsonl"
        decisions = _read_jsonl(screening_path)
        decision_records = [
            normalize_screening_decision(row)
            for row in decisions
            if str(row.get("pmid") or row.get("study_pmid") or "").strip()
        ]
        ranked_pmids = [row["pmid"] for row in decision_records if row.get("pmid")]
        predicted_pmids = [
            row["pmid"]
            for row in decision_records
            if row.get("pmid") and row.get("decision") in {"include", "uncertain"}
        ]
        prediction = {
            "case_id": case["case_id"],
            "meta_pmid": meta_pmid,
            "system": "brain_researcher_screening",
            "candidate_source": candidate_source,
            "ranked_pmids": ranked_pmids,
            "predicted_pmids": predicted_pmids,
            "decision_records": decision_records,
            "source_output_dir": str(case_dir),
        }
        anchors = _read_br_screening_anchors(case_dir)
        if anchors:
            prediction["br_screening_anchors"] = anchors
            prediction["br_screening_anchors_file"] = str(
                case_dir / "br_screening_anchors.json"
            )
        predictions.append(prediction)
    write_jsonl(predictions, output)
    return {
        "output": str(output),
        "n_cases": len(predictions),
        "br_output_dir": str(br_output_dir),
        "candidate_source": candidate_source,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--br-output-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("/tmp/neurometabench_v1/br_predictions.jsonl"))
    parser.add_argument(
        "--candidate-source",
        choices=["unknown", "pubmed", "closed_world", "mixed_pool", "union", "pmc_reference_list"],
        default="unknown",
        help="Candidate source used by the BR screening run.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            convert_br_screening_outputs(
                args.cases,
                args.br_output_dir,
                args.output,
                candidate_source=args.candidate_source,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
