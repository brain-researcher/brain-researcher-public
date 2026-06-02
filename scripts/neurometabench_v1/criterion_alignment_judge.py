#!/usr/bin/env python3
"""Criterion alignment judges for Layer A screening rationales.

The default mode is a cheap lexical triage judge. The Gemini mode is intended
for semantic spot checks before paper-level claims, and should still be paired
with human adjudication on a sampled disagreement set.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from statistics import mean
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.shared import DEFAULT_CASES_PATH, case_lookup, load_case_records, read_jsonl

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover - exercised only without Gemini package.
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]


def _tokens(text: str) -> set[str]:
    stopwords = {
        "and",
        "brain",
        "criteria",
        "data",
        "english",
        "human",
        "humans",
        "included",
        "language",
        "meta",
        "only",
        "paper",
        "papers",
        "participants",
        "reported",
        "reporting",
        "results",
        "studies",
        "study",
        "the",
        "with",
    }
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
        if token not in stopwords
    }


def _as_spans(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    spans: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = item.get("text") or item.get("span") or item.get("quote")
        else:
            text = item
        if text is not None and str(text).strip():
            spans.append(str(text).strip())
    return spans


def _json_object_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if start >= 0 and end > start else text


def _parse_judge_response(raw: str) -> dict[str, Any]:
    text = _json_object_text(raw)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        label_match = re.search(
            r'"?label"?\s*:\s*"?(yes|partial|no|cannot_judge)"?',
            text,
            flags=re.IGNORECASE,
        )
        score_match = re.search(r'"?support_score"?\s*:\s*([01](?:\.\d+)?)', text)
        reason_match = re.search(r'"?reason"?\s*:\s*"([^"\n]{0,800})', text, flags=re.DOTALL)
        return {
            "label": label_match.group(1).lower() if label_match else "cannot_judge",
            "support_score": score_match.group(1) if score_match else None,
            "reason": reason_match.group(1).strip() if reason_match else "Recovered from malformed judge JSON.",
            "parse_recovered": True,
        }


def judge_decision(case: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    criteria = {
        str(item.get("criterion_id")): item
        for item in case.get("screening_criteria", [])
        if item.get("criterion_id")
    }
    criterion_ids = [str(cid) for cid in decision.get("criterion_ids", []) if str(cid).strip()]
    spans = _as_spans(decision.get("evidence_spans"))
    reason = str(decision.get("reason") or "")

    unknown_ids = [cid for cid in criterion_ids if cid not in criteria]
    if not criterion_ids:
        label = "cannot_judge"
        score = 0.0
        rationale = "No criterion_ids were supplied."
    elif not spans:
        label = "cannot_judge"
        score = 0.0
        rationale = "No evidence_spans were supplied."
    elif unknown_ids:
        label = "partial"
        score = 0.25
        rationale = f"Unknown criterion_ids: {', '.join(unknown_ids)}."
    else:
        evidence_tokens = _tokens(" ".join(spans + [reason]))
        criterion_tokens = set()
        for cid in criterion_ids:
            criterion_tokens |= _tokens(str(criteria[cid].get("text") or ""))
        overlap = evidence_tokens & criterion_tokens
        score = len(overlap) / len(criterion_tokens) if criterion_tokens else 0.0
        if score >= 0.25 or len(overlap) >= 2:
            label = "yes"
            rationale = f"Evidence overlaps criterion terms: {', '.join(sorted(overlap)[:8])}."
        elif score > 0:
            label = "partial"
            rationale = f"Weak evidence/criterion overlap: {', '.join(sorted(overlap))}."
        else:
            label = "no"
            rationale = "Evidence spans do not lexically overlap the referenced criteria."

    return {
        "case_id": case.get("case_id"),
        "meta_pmid": case.get("meta_pmid"),
        "pmid": decision.get("pmid"),
        "decision": decision.get("decision"),
        "criterion_ids": criterion_ids,
        "label": label,
        "alignment_score": round(score, 6),
        "rationale": rationale,
        "judge_mode": "heuristic_first_pass",
    }


def semantic_judge_decision(
    case: dict[str, Any],
    decision: dict[str, Any],
    *,
    client: Any,
    model: str,
) -> dict[str, Any]:
    criteria = {
        str(item.get("criterion_id")): item
        for item in case.get("screening_criteria", [])
        if item.get("criterion_id")
    }
    criterion_ids = [str(cid) for cid in decision.get("criterion_ids", []) if str(cid).strip()]
    spans = _as_spans(decision.get("evidence_spans"))
    title = str(decision.get("title") or "")
    abstract = str(decision.get("abstract") or "")
    reason = str(decision.get("reason") or "")

    criterion_text = "\n".join(
        f"- {cid}: {criteria[cid].get('text', '')}"
        for cid in criterion_ids
        if cid in criteria
    )
    if not criterion_ids or not criterion_text or not spans:
        fallback = judge_decision(case, decision)
        fallback["judge_mode"] = "gemini_semantic_unavailable_fallback"
        return fallback

    prompt = f"""You are judging a neuroimaging meta-analysis screening rationale.

Criterion or criteria:
{criterion_text}

Paper title:
{title or "(not provided)"}

Paper abstract:
{abstract or "(not provided)"}

BR evidence span(s):
{json.dumps(spans, ensure_ascii=False)}

BR reason:
{reason or "(not provided)"}

Question: Do the evidence span(s), in the context of the title/abstract when available,
actually support using the referenced criterion/criteria for this include/exclude/uncertain decision?

Return one JSON object only. The label must be one of: yes, partial, no, cannot_judge.
Example:
{{"label":"yes","support_score":1.0,"reason":"The evidence span directly states the criterion."}}"""
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=2048,
            response_mime_type="application/json",
        ),
    )
    raw = (getattr(resp, "text", None) or "").strip()
    parsed = _parse_judge_response(raw)
    label = str(parsed.get("label") or "cannot_judge").strip().lower()
    if label not in {"yes", "partial", "no", "cannot_judge"}:
        label = "cannot_judge"
    try:
        score = float(parsed.get("support_score"))
    except (TypeError, ValueError):
        score = {"yes": 1.0, "partial": 0.5, "no": 0.0, "cannot_judge": 0.0}[label]
    return {
        "case_id": case.get("case_id"),
        "meta_pmid": case.get("meta_pmid"),
        "pmid": decision.get("pmid"),
        "decision": decision.get("decision"),
        "criterion_ids": criterion_ids,
        "label": label,
        "alignment_score": round(max(0.0, min(1.0, score)), 6),
        "rationale": str(parsed.get("reason") or ""),
        "judge_mode": "gemini_semantic",
        "judge_model": model,
        "parse_recovered": bool(parsed.get("parse_recovered")),
    }


def repeated_semantic_judge_decision(
    case: dict[str, Any],
    decision: dict[str, Any],
    *,
    client: Any,
    model: str,
    repeat: int,
) -> dict[str, Any]:
    repeat = max(1, repeat)
    judgments = [
        semantic_judge_decision(case, decision, client=client, model=model)
        for _ in range(repeat)
    ]
    first = dict(judgments[0])
    labels = [str(item.get("label") or "cannot_judge") for item in judgments]
    label_counts: dict[str, int] = {}
    for label in labels:
        label_counts[label] = label_counts.get(label, 0) + 1
    majority_label = max(label_counts.items(), key=lambda item: (item[1], item[0]))[0]
    matching = sum(1 for label in labels if label == majority_label)
    first["label"] = majority_label
    first["alignment_score"] = round(
        mean(float(item.get("alignment_score") or 0.0) for item in judgments),
        6,
    )
    first["rationale"] = judgments[0].get("rationale")
    first["repeat"] = repeat
    first["repeat_label_counts"] = label_counts
    first["repeat_self_agreement"] = round(matching / repeat, 6)
    if repeat > 1:
        first["repeat_judgments"] = [
            {
                "label": item.get("label"),
                "alignment_score": item.get("alignment_score"),
                "rationale": item.get("rationale"),
            }
            for item in judgments
        ]
    return first


def judge_prediction_files(
    cases_path: Path,
    prediction_paths: list[Path],
    output: Path,
    *,
    judge_mode: str = "heuristic",
    model: str = "gemini-2.5-flash",
    limit: int | None = None,
    repeat: int = 1,
) -> dict[str, Any]:
    cases = case_lookup(load_case_records(cases_path))
    items: list[dict[str, Any]] = []
    client = None
    if judge_mode == "gemini":
        if genai is None:
            raise RuntimeError("google-genai package is not installed")
        client = genai.Client()
    for prediction_path in prediction_paths:
        for prediction in read_jsonl(prediction_path):
            key = str(prediction.get("case_id") or prediction.get("meta_pmid") or "")
            case = cases.get(key)
            if case is None:
                continue
            for decision in prediction.get("decision_records") or []:
                if isinstance(decision, dict):
                    if judge_mode == "gemini":
                        row = repeated_semantic_judge_decision(
                            case,
                            decision,
                            client=client,
                            model=model,
                            repeat=repeat,
                        )
                    else:
                        row = judge_decision(case, decision)
                    row["system"] = prediction.get("system")
                    row["prediction_path"] = str(prediction_path)
                    items.append(row)
                    if limit is not None and len(items) >= limit:
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_text(
                            json.dumps({"items": items, "summary": summarize(items)}, indent=2),
                            encoding="utf-8",
                        )
                        return {"output": str(output), "n_items": len(items), "summary": summarize(items)}

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"items": items, "summary": summarize(items)}, indent=2), encoding="utf-8")
    return {"output": str(output), "n_items": len(items), "summary": summarize(items)}


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {"n_items": 0, "label_counts": {}, "mean_alignment_score": None}
    label_counts: dict[str, int] = {}
    for item in items:
        label = str(item.get("label") or "unknown")
        label_counts[label] = label_counts.get(label, 0) + 1
    out: dict[str, Any] = {
        "n_items": len(items),
        "label_counts": label_counts,
        "mean_alignment_score": round(mean(float(item.get("alignment_score") or 0.0) for item in items), 6),
        "judge_modes": sorted({str(item.get("judge_mode") or "unknown") for item in items}),
        "note": (
            "Use human adjudication or validated Gemini repeated judging for headline benchmark claims; "
            "heuristic mode is first-pass triage only."
        ),
    }
    agreement_values = [
        float(item["repeat_self_agreement"])
        for item in items
        if item.get("repeat_self_agreement") is not None
    ]
    if agreement_values:
        out["mean_repeat_self_agreement"] = round(mean(agreement_values), 6)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--predictions", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=Path("/tmp/neurometabench_v1/criterion_alignment_judge.json"))
    parser.add_argument("--judge-mode", choices=["heuristic", "gemini"], default="heuristic")
    parser.add_argument("--model", default="gemini-2.5-flash")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of repeated semantic judgments per item in --judge-mode gemini.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            judge_prediction_files(
                args.cases,
                args.predictions,
                args.output,
                judge_mode=args.judge_mode,
                model=args.model,
                limit=args.limit,
                repeat=args.repeat,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
