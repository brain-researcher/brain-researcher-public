"""Research-only KGGen evaluator for Gabriel coverage experiments.

This module compares baseline Gabriel records against KGGen-derived candidates
without writing to Neo4j. It reuses Gabriel variable/gating logic so both arms
are scored consistently.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brain_researcher.services.br_kg.etl.gabriel_generator import (
    DEFAULT_OUTPUT_ROOT,
    resolve_manifest_path,
)
from brain_researcher.services.br_kg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)
from brain_researcher.services.br_kg.etl.loaders.gabriel_measurements import (
    DEFAULT_HIGH_PRECISION_THRESHOLDS,
    DEFAULT_REQUIRED_PROVENANCE_FIELDS,
    GabrielVariables,
    compute_gabriel_variables,
    evaluate_high_precision_gate,
)

logger = logging.getLogger(__name__)

ADAPTER_VERSION = "kggen-adapter/v1"
EVAL_SCHEMA_VERSION = "gabriel-kggen-eval-v1"


@dataclass
class ArmStats:
    name: str
    records_total: int
    records_accepted: int
    records_rejected: int
    parse_errors: int
    unique_edges_accepted: int
    acceptance_rate: float
    avg_mapping_confidence: float
    avg_claim_strength: float
    avg_method_rigor: float
    avg_provenance_completeness: float
    rejection_reasons: dict[str, int]


def evaluate_kggen_coverage(
    *,
    kggen_input: Path | str,
    output_dir: Path | str,
    manifest_path: Path | str | None = None,
    baseline_jsonl_paths: list[Path | str] | None = None,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    sample_size: int = 300,
    seed: int = 13,
    quality_profile: str = "balanced",
    annotate_fraction: float = 0.10,
    strict_provenance: bool = True,
) -> dict[str, Any]:
    """Run research-only baseline-vs-KGGen coverage evaluation."""

    if sample_size <= 0:
        raise ValueError("sample_size must be > 0")
    if annotate_fraction < 0 or annotate_fraction > 1:
        raise ValueError("annotate_fraction must be in [0, 1]")

    output_dir_path = Path(output_dir).expanduser().resolve()
    output_dir_path.mkdir(parents=True, exist_ok=True)

    thresholds = _resolve_quality_thresholds(quality_profile)
    required_provenance_fields = tuple(DEFAULT_REQUIRED_PROVENANCE_FIELDS)

    baseline_payload = _load_baseline_records(
        manifest_path=manifest_path,
        baseline_jsonl_paths=baseline_jsonl_paths or [],
        output_root=output_root,
    )
    kggen_payload = _load_kggen_records(
        input_path=kggen_input,
        strict_provenance=strict_provenance,
        required_provenance_fields=required_provenance_fields,
    )

    baseline_papers = _paper_id_set(baseline_payload["records"])
    kggen_papers = _paper_id_set(kggen_payload["records"])
    overlap_papers = sorted(baseline_papers & kggen_papers)
    if not overlap_papers:
        raise RuntimeError(
            "No overlapping paper IDs between baseline and KGGen candidates. "
            "Ensure KGGen input includes paper IDs matching baseline records."
        )

    sampled_papers = _sample_paper_ids(overlap_papers, sample_size=sample_size, seed=seed)
    baseline_records = _filter_records_by_paper_ids(baseline_payload["records"], sampled_papers)
    kggen_records = _filter_records_by_paper_ids(kggen_payload["records"], sampled_papers)

    baseline_eval = _evaluate_arm(
        name="baseline",
        records=baseline_records,
        parse_errors=baseline_payload["parse_errors"],
        thresholds=thresholds,
        required_provenance_fields=required_provenance_fields,
    )
    kggen_eval = _evaluate_arm(
        name="kggen",
        records=kggen_records,
        parse_errors=kggen_payload["parse_errors"],
        thresholds=thresholds,
        required_provenance_fields=required_provenance_fields,
    )

    coverage = _compute_coverage_metrics(
        baseline_edges=baseline_eval["accepted_edges"],
        kggen_edges=kggen_eval["accepted_edges"],
    )

    report: dict[str, Any] = {
        "schema_version": EVAL_SCHEMA_VERSION,
        "generated_at": _utc_now_iso(),
        "configuration": {
            "manifest_path": baseline_payload["manifest_path"],
            "baseline_jsonl_paths": baseline_payload["input_paths"],
            "kggen_input": str(Path(kggen_input).expanduser().resolve()),
            "quality_profile": quality_profile,
            "quality_gate": thresholds,
            "sample_size": sample_size,
            "seed": seed,
            "annotate_fraction": annotate_fraction,
            "strict_provenance": strict_provenance,
            "required_provenance_fields": list(required_provenance_fields),
        },
        "sample": {
            "baseline_papers": len(baseline_papers),
            "kggen_papers": len(kggen_papers),
            "overlap_papers": len(overlap_papers),
            "papers_evaluated": len(sampled_papers),
            "paper_ids": sampled_papers,
            "records_evaluated_baseline": len(baseline_records),
            "records_evaluated_kggen": len(kggen_records),
            "manual_annotation_target": int(round(len(sampled_papers) * annotate_fraction)),
        },
        "baseline": asdict(_arm_stats_from_eval(baseline_eval)),
        "kggen": asdict(_arm_stats_from_eval(kggen_eval)),
        "coverage": coverage,
        "quality": {
            "pass_rate_baseline": baseline_eval["acceptance_rate"],
            "pass_rate_kggen": kggen_eval["acceptance_rate"],
            "pass_rate_delta": kggen_eval["acceptance_rate"] - baseline_eval["acceptance_rate"],
            "avg_mapping_confidence_baseline": baseline_eval["avg_mapping_confidence"],
            "avg_mapping_confidence_kggen": kggen_eval["avg_mapping_confidence"],
            "avg_provenance_completeness_baseline": baseline_eval["avg_provenance_completeness"],
            "avg_provenance_completeness_kggen": kggen_eval["avg_provenance_completeness"],
        },
        "ops": {
            "parse_error_rate_baseline": _ratio(
                baseline_payload["parse_errors"], max(1, baseline_payload["records_total"])
            ),
            "parse_error_rate_kggen": _ratio(
                kggen_payload["parse_errors"], max(1, kggen_payload["records_total"])
            ),
            "manual_review_items_baseline": len(baseline_eval["review_queue"]),
            "manual_review_items_kggen": len(kggen_eval["review_queue"]),
            "cost_per_accepted_record": None,
        },
        "artifacts": {},
    }

    report_path = output_dir_path / "report.json"
    review_queue_path = output_dir_path / "review_queue_combined.jsonl"
    kggen_adapted_path = output_dir_path / "kggen_adapted.jsonl"
    sample_path = output_dir_path / "sample_paper_ids.json"

    _write_json(report_path, report)
    _write_jsonl(
        review_queue_path,
        baseline_eval["review_queue"] + kggen_eval["review_queue"],
    )
    _write_jsonl(kggen_adapted_path, kggen_records)
    _write_json(sample_path, {"paper_ids": sampled_papers})

    report["artifacts"] = {
        "report_path": str(report_path),
        "review_queue_path": str(review_queue_path),
        "kggen_adapted_path": str(kggen_adapted_path),
        "sample_paper_ids_path": str(sample_path),
    }
    _write_json(report_path, report)
    return report


def _load_baseline_records(
    *,
    manifest_path: Path | str | None,
    baseline_jsonl_paths: list[Path | str],
    output_root: Path | str,
) -> dict[str, Any]:
    resolved_manifest: str | None = None
    input_paths: list[Path] = []

    if baseline_jsonl_paths:
        input_paths = [Path(path).expanduser().resolve() for path in baseline_jsonl_paths]
    else:
        resolved = resolve_manifest_path(manifest_path, output_root)
        resolved_manifest = str(resolved)
        manifest = json.loads(resolved.read_text(encoding="utf-8"))
        for shard in manifest.get("shards", []):
            raw_path = str(shard.get("path") or "").strip()
            if not raw_path:
                continue
            shard_path = Path(raw_path).expanduser().resolve()
            if shard_path.exists() and shard_path.is_file():
                input_paths.append(shard_path)

    records, parse_errors = _read_jsonl_files(input_paths)
    return {
        "manifest_path": resolved_manifest,
        "input_paths": [str(path) for path in input_paths],
        "records": records,
        "records_total": len(records),
        "parse_errors": parse_errors,
    }


def _load_kggen_records(
    *,
    input_path: Path | str,
    strict_provenance: bool,
    required_provenance_fields: tuple[str, ...],
) -> dict[str, Any]:
    resolved_input = Path(input_path).expanduser().resolve()
    files = _resolve_input_files(resolved_input)

    adapted_records: list[dict[str, Any]] = []
    parse_errors = 0
    error_reasons: Counter[str] = Counter()

    for file_path in files:
        if file_path.suffix.lower() in {".jsonl", ".ndjson"}:
            with file_path.open("r", encoding="utf-8") as handle:
                for line_number, raw_line in enumerate(handle, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        parse_errors += 1
                        error_reasons["json_decode_error"] += 1
                        continue
                    records, errors = _adapt_kggen_item(
                        payload,
                        source_path=file_path,
                        ordinal=line_number,
                        strict_provenance=strict_provenance,
                        required_provenance_fields=required_provenance_fields,
                    )
                    adapted_records.extend(records)
                    parse_errors += len(errors)
                    error_reasons.update(errors)
            continue

        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
            items = payload["records"]
        else:
            items = [payload]

        for index, item in enumerate(items, start=1):
            records, errors = _adapt_kggen_item(
                item,
                source_path=file_path,
                ordinal=index,
                strict_provenance=strict_provenance,
                required_provenance_fields=required_provenance_fields,
            )
            adapted_records.extend(records)
            parse_errors += len(errors)
            error_reasons.update(errors)

    return {
        "input_path": str(resolved_input),
        "files": [str(path) for path in files],
        "records": adapted_records,
        "records_total": len(adapted_records),
        "parse_errors": parse_errors,
        "error_reasons": dict(error_reasons),
    }


def _resolve_input_files(input_path: Path) -> list[Path]:
    if not input_path.exists():
        raise FileNotFoundError(f"KGGen input not found: {input_path}")
    if input_path.is_file():
        return [input_path]

    files = sorted(
        path
        for path in input_path.rglob("*")
        if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".ndjson"}
    )
    if not files:
        raise FileNotFoundError(f"No JSON/JSONL files found under: {input_path}")
    return files


def _read_jsonl_files(paths: list[Path]) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    parse_errors = 0

    for file_path in paths:
        with file_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if isinstance(payload, dict):
                    records.append(payload)
                else:
                    parse_errors += 1
    return records, parse_errors


def _adapt_kggen_item(
    payload: Any,
    *,
    source_path: Path,
    ordinal: int,
    strict_provenance: bool,
    required_provenance_fields: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(payload, dict):
        return [], ["payload_not_object"]

    if _looks_like_gabriel_record(payload):
        normalized = _normalize_gabriel_like_record(
            payload,
            source_path=source_path,
            ordinal=ordinal,
        )
        missing = _missing_provenance_fields(normalized, required_provenance_fields)
        if strict_provenance and missing:
            return [], [f"missing_provenance:{','.join(sorted(missing))}"]
        return [normalized], []

    if "graph" in payload and isinstance(payload["graph"], dict):
        return _adapt_graph_payload(
            payload["graph"],
            parent_payload=payload,
            source_path=source_path,
            ordinal=ordinal,
            strict_provenance=strict_provenance,
            required_provenance_fields=required_provenance_fields,
        )

    if "relations" in payload:
        return _adapt_graph_payload(
            payload,
            parent_payload=payload,
            source_path=source_path,
            ordinal=ordinal,
            strict_provenance=strict_provenance,
            required_provenance_fields=required_provenance_fields,
        )

    if _looks_like_relation_row(payload):
        record = _record_from_relation_payload(
            payload,
            source_path=source_path,
            ordinal=ordinal,
            parent_payload=payload,
        )
        missing = _missing_provenance_fields(record, required_provenance_fields)
        if strict_provenance and missing:
            return [], [f"missing_provenance:{','.join(sorted(missing))}"]
        return [record], []

    return [], ["unrecognized_payload_shape"]


def _adapt_graph_payload(
    graph_payload: dict[str, Any],
    *,
    parent_payload: dict[str, Any],
    source_path: Path,
    ordinal: int,
    strict_provenance: bool,
    required_provenance_fields: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    relations = graph_payload.get("relations")
    if not isinstance(relations, list | tuple | set):
        return [], ["relations_missing"]

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for rel_index, relation in enumerate(relations, start=1):
        relation_payload: dict[str, Any]
        if isinstance(relation, dict):
            relation_payload = {
                **parent_payload,
                **relation,
            }
        elif isinstance(relation, list | tuple) and len(relation) >= 3:
            relation_payload = {
                **parent_payload,
                "subject": relation[0],
                "predicate": relation[1],
                "object": relation[2],
            }
        else:
            errors.append("invalid_relation_entry")
            continue

        record = _record_from_relation_payload(
            relation_payload,
            source_path=source_path,
            ordinal=ordinal * 100000 + rel_index,
            parent_payload=parent_payload,
        )
        missing = _missing_provenance_fields(record, required_provenance_fields)
        if strict_provenance and missing:
            errors.append(f"missing_provenance:{','.join(sorted(missing))}")
            continue
        records.append(record)

    return records, errors


def _normalize_gabriel_like_record(
    payload: dict[str, Any],
    *,
    source_path: Path,
    ordinal: int,
) -> dict[str, Any]:
    record = json.loads(json.dumps(payload))
    run = dict(record.get("run") or {})
    run.setdefault("run_id", f"kggen:{_stable_hash(f'{source_path}:{ordinal}')[:12]}")
    run.setdefault("tool", "kggen")
    run.setdefault("model", str(record.get("model") or "kggen-unknown"))
    run.setdefault("prompt_hash", _stable_hash(f"{source_path}:prompt:{ordinal}"))
    run.setdefault("template_hash", ADAPTER_VERSION)
    run.setdefault("raw_response_path", str(source_path))
    run.setdefault("loader_version", ADAPTER_VERSION)
    run.setdefault("timestamp", _utc_now_iso())
    record["run"] = run
    record["generator_source"] = "kggen"
    record["generator_version"] = str(
        record.get("generator_version") or ADAPTER_VERSION
    )
    return record


def _record_from_relation_payload(
    payload: dict[str, Any],
    *,
    source_path: Path,
    ordinal: int,
    parent_payload: dict[str, Any],
) -> dict[str, Any]:
    subject = _as_nonempty_str(
        payload.get("subject"),
        payload.get("head"),
        payload.get("source"),
        payload.get("from"),
    )
    predicate = _as_nonempty_str(
        payload.get("predicate"),
        payload.get("relation"),
        payload.get("edge"),
        payload.get("rel"),
    )
    obj = _as_nonempty_str(
        payload.get("object"),
        payload.get("tail"),
        payload.get("target"),
        payload.get("to"),
    )

    if not subject:
        subject = "unknown_subject"
    if not predicate:
        predicate = "related_to"
    if not obj:
        obj = "unknown_object"

    explicit_confidence = _first_float(
        payload.get("mapping_confidence"),
        payload.get("confidence"),
        payload.get("score"),
    )
    mapping_confidence = _infer_mapping_confidence(
        payload,
        explicit_confidence=explicit_confidence,
    )
    claim_strength = _infer_claim_strength(
        payload,
        explicit_confidence=explicit_confidence,
    )

    evidence_quote = _as_nonempty_str(
        payload.get("evidence_quote"),
        payload.get("evidence"),
        payload.get("context"),
        payload.get("sentence"),
        payload.get("support_text"),
    )
    has_statistical_detail = bool(
        payload.get("has_statistical_detail")
        or payload.get("p_value")
        or payload.get("statistic")
    )
    method_rigor = _infer_method_rigor(
        payload,
        has_statistical_detail=has_statistical_detail,
        evidence_quote=evidence_quote,
    )
    evidence_quality_score = _infer_evidence_quality_score(
        payload,
        has_statistical_detail=has_statistical_detail,
        evidence_quote=evidence_quote,
    )
    mention_frequency = _coerce_int(payload.get("mention_frequency"), default=1, minimum=0)
    max_frequency = _coerce_int(payload.get("max_frequency"), default=5, minimum=1)
    max_frequency = max(max_frequency, mention_frequency, 1)

    context_overlap = _clamp01(payload.get("context_overlap"), default=0.45)
    modal_density = _clamp01(payload.get("modal_density"), default=0.45)
    statistical_density = _clamp01(
        payload.get("statistical_density"),
        default=0.35 if has_statistical_detail else 0.25,
    )
    assertive_verb_ratio = _clamp01(
        payload.get("assertive_verb_ratio"),
        default=0.55,
    )
    sample_size_adequacy = _clamp01(
        payload.get("sample_size_adequacy"),
        default=0.45,
    )
    roi_definition_clear = _coerce_bool(payload.get("roi_definition_clear"), default=False)

    paper = _extract_paper_payload(payload, parent_payload=parent_payload, source_path=source_path, ordinal=ordinal)
    relation_text = f"{subject} {predicate} {obj}"

    run_id = f"kggen:{_stable_hash(f'{source_path}:{ordinal}')[:12]}"
    record = {
        "run": {
            "run_id": run_id,
            "tool": "kggen",
            "model": _as_nonempty_str(payload.get("model"), parent_payload.get("model"), "kggen-unknown"),
            "prompt_hash": _stable_hash(f"{source_path}:prompt:{ordinal}"),
            "template_hash": ADAPTER_VERSION,
            "raw_response_path": str(source_path),
            "loader_version": ADAPTER_VERSION,
            "timestamp": _utc_now_iso(),
        },
        "paper": paper,
        "target": {
            "type": _as_nonempty_str(payload.get("target_type"), "Concept"),
            "id": _as_nonempty_str(
                payload.get("target_id"),
                payload.get("canonical_id"),
                f"concept:{_slugify(obj)}",
            ),
            "label": obj,
        },
        "mapping": {
            "canonical_id": _as_nonempty_str(
                payload.get("canonical_id"),
                payload.get("target_id"),
                f"concept:{_slugify(obj)}",
            ),
            "mapping_type": _as_nonempty_str(payload.get("mapping_type"), "related"),
            "mapping_confidence": mapping_confidence,
        },
        "claim": {
            "id": f"claim:{_stable_hash(relation_text)[:12]}",
            "text": _as_nonempty_str(payload.get("claim_text"), relation_text),
            "polarity": _normalize_polarity(
                payload.get("polarity")
                or payload.get("direction")
                or "supports"
            ),
            "claim_strength": claim_strength,
        },
        "evidence": {
            "span_id": f"evidence:{_stable_hash(f'{relation_text}:{ordinal}')[:12]}",
            "quote": evidence_quote or relation_text,
            "section": _as_nonempty_str(payload.get("section"), "unknown"),
            "page": payload.get("page"),
            "char_start": payload.get("char_start"),
            "char_end": payload.get("char_end"),
            "has_statistical_detail": has_statistical_detail,
            "locatable": bool(evidence_quote),
            "direct_quote": bool(evidence_quote),
        },
        "signals": {
            "mention_frequency": mention_frequency,
            "max_frequency": max_frequency,
            "title_hit": bool(payload.get("title_hit")),
            "abstract_hit": bool(payload.get("abstract_hit")),
            "semantic_similarity": mapping_confidence,
            "ontology_match": bool(
                payload.get("ontology_match") or payload.get("target_id") or payload.get("canonical_id")
            ),
            "context_overlap": context_overlap,
            "modal_density": modal_density,
            "statistical_density": statistical_density,
            "assertive_verb_ratio": assertive_verb_ratio,
            "preregistration": bool(payload.get("preregistration")),
            "threshold_correction_reported": bool(payload.get("threshold_correction_reported")),
            "sample_size_adequacy": sample_size_adequacy,
            "roi_definition_clear": roi_definition_clear,
            "open_data_or_code": bool(payload.get("open_data_or_code")),
            "method_rigor": method_rigor,
            "evidence_quality_score": evidence_quality_score,
        },
        "generator_source": "kggen",
        "generator_version": _as_nonempty_str(
            payload.get("generator_version"),
            parent_payload.get("generator_version"),
            ADAPTER_VERSION,
        ),
    }
    return record


def _extract_paper_payload(
    payload: dict[str, Any],
    *,
    parent_payload: dict[str, Any],
    source_path: Path,
    ordinal: int,
) -> dict[str, Any]:
    paper_info = payload.get("paper")
    if isinstance(paper_info, dict):
        raw = paper_info
    else:
        raw = payload

    paper_id = _as_nonempty_str(
        raw.get("id"),
        raw.get("paper_id"),
        raw.get("publication_id"),
        raw.get("doc_id"),
        raw.get("pmid"),
        raw.get("doi"),
        parent_payload.get("paper_id"),
        parent_payload.get("pmid"),
        parent_payload.get("doi"),
    )
    if not paper_id:
        paper_id = f"paper:{_stable_hash(f'{source_path}:{ordinal}')[:12]}"

    title = _as_nonempty_str(
        raw.get("title"),
        raw.get("paper_title"),
        parent_payload.get("title"),
        parent_payload.get("paper_title"),
        paper_id,
    )

    paper: dict[str, Any] = {
        "id": paper_id,
        "title": title,
    }
    pmid = _as_nonempty_str(raw.get("pmid"), parent_payload.get("pmid"))
    doi = _as_nonempty_str(raw.get("doi"), parent_payload.get("doi"))
    if pmid:
        paper["pmid"] = pmid
    if doi:
        paper["doi"] = doi

    year_value = raw.get("year", parent_payload.get("year"))
    try:
        if year_value is not None:
            paper["year"] = int(year_value)
    except (TypeError, ValueError):
        pass

    journal = _as_nonempty_str(raw.get("journal"), parent_payload.get("journal"))
    if journal:
        paper["journal"] = journal
    return paper


def _looks_like_gabriel_record(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload.get("paper"), dict)
        and isinstance(payload.get("target"), dict)
        and isinstance(payload.get("claim"), dict)
    )


def _looks_like_relation_row(payload: dict[str, Any]) -> bool:
    keys = {"subject", "head", "source", "from"}
    rel_keys = {"predicate", "relation", "edge", "rel"}
    obj_keys = {"object", "tail", "target", "to"}
    return (
        any(key in payload for key in keys)
        and any(key in payload for key in rel_keys)
        and any(key in payload for key in obj_keys)
    )


def _missing_provenance_fields(
    record: dict[str, Any],
    required_fields: tuple[str, ...],
) -> list[str]:
    combined: dict[str, Any] = {}
    combined.update(record)
    run = record.get("run")
    if isinstance(run, dict):
        combined.update(run)
    prov = record.get("prov")
    if isinstance(prov, dict):
        combined.update(prov)

    missing: list[str] = []
    for field in required_fields:
        value = combined.get(field)
        if value is None:
            missing.append(field)
        elif isinstance(value, str) and not value.strip():
            missing.append(field)
    return missing


def _evaluate_arm(
    *,
    name: str,
    records: list[dict[str, Any]],
    parse_errors: int,
    thresholds: dict[str, Any],
    required_provenance_fields: tuple[str, ...],
) -> dict[str, Any]:
    accepted_edges: set[str] = set()
    rejected = 0
    accepted = 0
    reason_counts: Counter[str] = Counter()
    review_queue: list[dict[str, Any]] = []
    variables_list: list[GabrielVariables] = []

    for index, record in enumerate(records, start=1):
        variables = compute_gabriel_variables(
            record,
            required_provenance_fields=required_provenance_fields,
        )
        variables_list.append(variables)
        ok, reasons = evaluate_high_precision_gate(variables, thresholds)
        if ok:
            accepted += 1
            accepted_edges.add(_edge_key(record))
            continue

        rejected += 1
        reason_counts.update(reasons)
        review_queue.append(
            {
                "source": name,
                "record_index": index,
                "paper_id": _paper_id(record),
                "target_id": _target_id(record),
                "claim_id": str((record.get("claim") or {}).get("id") or ""),
                "reasons": reasons,
                "variables": asdict(variables),
            }
        )

    total = len(records)
    metrics = _aggregate_variable_metrics(variables_list)
    return {
        "name": name,
        "records_total": total,
        "records_accepted": accepted,
        "records_rejected": rejected,
        "parse_errors": parse_errors,
        "acceptance_rate": _ratio(accepted, max(1, total)),
        "accepted_edges": accepted_edges,
        "unique_edges_accepted": len(accepted_edges),
        "rejection_reasons": dict(reason_counts),
        "review_queue": review_queue,
        **metrics,
    }


def _arm_stats_from_eval(payload: dict[str, Any]) -> ArmStats:
    return ArmStats(
        name=str(payload["name"]),
        records_total=int(payload["records_total"]),
        records_accepted=int(payload["records_accepted"]),
        records_rejected=int(payload["records_rejected"]),
        parse_errors=int(payload["parse_errors"]),
        unique_edges_accepted=int(payload["unique_edges_accepted"]),
        acceptance_rate=float(payload["acceptance_rate"]),
        avg_mapping_confidence=float(payload["avg_mapping_confidence"]),
        avg_claim_strength=float(payload["avg_claim_strength"]),
        avg_method_rigor=float(payload["avg_method_rigor"]),
        avg_provenance_completeness=float(payload["avg_provenance_completeness"]),
        rejection_reasons=dict(payload["rejection_reasons"]),
    )


def _aggregate_variable_metrics(variables_list: list[GabrielVariables]) -> dict[str, float]:
    if not variables_list:
        return {
            "avg_mapping_confidence": 0.0,
            "avg_claim_strength": 0.0,
            "avg_method_rigor": 0.0,
            "avg_provenance_completeness": 0.0,
        }

    count = float(len(variables_list))
    return {
        "avg_mapping_confidence": sum(v.mapping_confidence for v in variables_list) / count,
        "avg_claim_strength": sum(v.claim_strength for v in variables_list) / count,
        "avg_method_rigor": sum(v.method_rigor for v in variables_list) / count,
        "avg_provenance_completeness": sum(v.provenance_completeness for v in variables_list)
        / count,
    }


def _compute_coverage_metrics(
    *,
    baseline_edges: set[str],
    kggen_edges: set[str],
) -> dict[str, Any]:
    overlap = baseline_edges & kggen_edges
    new_edges = kggen_edges - baseline_edges
    baseline_count = len(baseline_edges)
    kggen_count = len(kggen_edges)
    yield_delta = kggen_count - baseline_count
    return {
        "baseline_high_conf_edges": baseline_count,
        "kggen_high_conf_edges": kggen_count,
        "overlap_high_conf_edges": len(overlap),
        "new_high_conf_edges": len(new_edges),
        "edge_recall_proxy": _ratio(len(overlap), baseline_count) if baseline_count else None,
        "edge_yield_delta": yield_delta,
        "edge_yield_delta_pct": _ratio(yield_delta, baseline_count) if baseline_count else None,
    }


def _edge_key(record: dict[str, Any]) -> str:
    paper_id = _paper_id(record)
    target_id = _target_id(record)
    claim = record.get("claim") or {}
    claim_text = _normalize_whitespace(str(claim.get("text") or ""))
    polarity = _normalize_polarity(claim.get("polarity"))
    claim_hash = _stable_hash(claim_text)[:12]
    return "|".join([paper_id, target_id, polarity, claim_hash])


def _paper_id(record: dict[str, Any]) -> str:
    paper = record.get("paper") or {}
    if isinstance(paper, dict):
        value = paper.get("id") or paper.get("pmid") or paper.get("doi")
        if value:
            return str(value)
    return "paper:unknown"


def _target_id(record: dict[str, Any]) -> str:
    target = record.get("target") or {}
    mapping = record.get("mapping") or {}
    if isinstance(mapping, dict):
        value = mapping.get("canonical_id")
        if value:
            return str(value)
    if isinstance(target, dict):
        value = target.get("id") or target.get("label")
        if value:
            return str(value)
    return "target:unknown"


def _paper_id_set(records: list[dict[str, Any]]) -> set[str]:
    return {paper_id for paper_id in (_paper_id(record) for record in records) if paper_id}


def _filter_records_by_paper_ids(
    records: list[dict[str, Any]],
    paper_ids: list[str],
) -> list[dict[str, Any]]:
    allowed = set(paper_ids)
    return [record for record in records if _paper_id(record) in allowed]


def _sample_paper_ids(
    paper_ids: list[str],
    *,
    sample_size: int,
    seed: int,
) -> list[str]:
    if len(paper_ids) <= sample_size:
        return sorted(paper_ids)
    rng = random.Random(seed)
    sampled = rng.sample(paper_ids, sample_size)
    sampled.sort()
    return sampled


def _resolve_quality_thresholds(quality_profile: str) -> dict[str, Any]:
    profile = str(quality_profile).strip().lower()
    thresholds = dict(DEFAULT_HIGH_PRECISION_THRESHOLDS)
    profile_cfg = GabrielMeasurementLoader.QUALITY_PROFILES.get(profile)
    if profile_cfg is None:
        logger.warning(
            "Unknown quality profile '%s'; falling back to high_precision thresholds",
            quality_profile,
        )
        profile_cfg = GabrielMeasurementLoader.QUALITY_PROFILES["high_precision"]
    thresholds.update(profile_cfg)
    return thresholds


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def _as_nonempty_str(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _normalize_polarity(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"supports", "support", "positive", "increase", "increases"}:
        return "supports"
    if normalized in {"refutes", "refute", "negative", "decrease", "decreases"}:
        return "refutes"
    if normalized in {"mixed", "conflicting", "contradictory"}:
        return "mixed"
    return "uncertain"


def _clamp01(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _coerce_int(value: Any, *, default: int, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(int(minimum), parsed)


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _infer_mapping_confidence(
    payload: dict[str, Any],
    *,
    explicit_confidence: float | None,
) -> float:
    if explicit_confidence is not None:
        return _clamp01(explicit_confidence, default=0.0)

    semantic_similarity = _clamp01(payload.get("semantic_similarity"), default=0.55)
    context_overlap = _clamp01(payload.get("context_overlap"), default=0.45)
    abbreviation_penalty = _clamp01(
        payload.get("abbreviation_ambiguity"),
        default=0.10,
    )
    ontology_match = _coerce_bool(
        payload.get("ontology_match"),
        default=False,
    ) or bool(payload.get("target_id") or payload.get("canonical_id"))

    score = (
        0.60 * semantic_similarity
        + 0.25 * (1.0 if ontology_match else 0.0)
        + 0.15 * context_overlap
        - 0.30 * abbreviation_penalty
    )
    return max(0.0, min(1.0, score))


def _infer_claim_strength(
    payload: dict[str, Any],
    *,
    explicit_confidence: float | None,
) -> float:
    explicit_claim_strength = _first_float(payload.get("claim_strength"))
    if explicit_claim_strength is not None:
        return _clamp01(explicit_claim_strength, default=0.0)

    modal_density = _clamp01(payload.get("modal_density"), default=0.45)
    statistical_density = _clamp01(payload.get("statistical_density"), default=0.30)
    assertive_verb_ratio = _clamp01(
        payload.get("assertive_verb_ratio"),
        default=0.55,
    )

    derived = (
        0.40 * (1.0 - modal_density)
        + 0.30 * statistical_density
        + 0.30 * assertive_verb_ratio
    )
    if explicit_confidence is not None:
        confidence_hint = _clamp01(explicit_confidence, default=0.0)
        derived = 0.75 * derived + 0.25 * confidence_hint
    return max(0.0, min(1.0, derived))


def _infer_method_rigor(
    payload: dict[str, Any],
    *,
    has_statistical_detail: bool,
    evidence_quote: str,
) -> float:
    explicit_method_rigor = _first_float(payload.get("method_rigor"))
    if explicit_method_rigor is not None:
        return _clamp01(explicit_method_rigor, default=0.0)

    section = _as_nonempty_str(payload.get("section"), "unknown").strip().lower()
    sample_default = 0.55 if section in {"abstract", "results", "methods"} else 0.45
    if has_statistical_detail:
        sample_default = max(sample_default, 0.62)

    prereg = _coerce_bool(payload.get("preregistration"), default=False)
    threshold = _coerce_bool(
        payload.get("threshold_correction_reported"),
        default=False,
    )
    sample = _clamp01(payload.get("sample_size_adequacy"), default=sample_default)
    roi_clear = _coerce_bool(payload.get("roi_definition_clear"), default=False)
    open_data = _coerce_bool(payload.get("open_data_or_code"), default=False)
    statistical_density = _clamp01(
        payload.get("statistical_density"),
        default=0.55 if has_statistical_detail else 0.30,
    )
    assertive_verb_ratio = _clamp01(
        payload.get("assertive_verb_ratio"),
        default=0.55,
    )
    confidence_hint = _clamp01(
        _first_float(
            payload.get("confidence"),
            payload.get("mapping_confidence"),
            payload.get("score"),
        ),
        default=0.0,
    )

    text_hints = _normalize_whitespace(
        " ".join(
            part
            for part in [
                _as_nonempty_str(evidence_quote),
                _as_nonempty_str(payload.get("claim_text")),
                _as_nonempty_str(payload.get("subject")),
                _as_nonempty_str(payload.get("predicate")),
                _as_nonempty_str(payload.get("object")),
                _as_nonempty_str(payload.get("target_label")),
            ]
            if part
        ).lower()
    )

    prereg_score = (
        1.0
        if prereg
        else (0.70 if _contains_any_term(text_hints, _PREREGISTRATION_HINT_TERMS) else 0.0)
    )
    threshold_score = (
        1.0
        if threshold
        else (0.65 if _contains_any_term(text_hints, _THRESHOLD_HINT_TERMS) else 0.0)
    )
    roi_score = (
        1.0
        if roi_clear
        else (0.65 if _contains_any_term(text_hints, _ROI_HINT_TERMS) else 0.0)
    )
    open_data_score = (
        1.0
        if open_data
        else (0.55 if _contains_any_term(text_hints, _OPEN_DATA_HINT_TERMS) else 0.0)
    )

    if section in {"results", "methods"}:
        section_signal = 1.0
    elif section == "abstract":
        section_signal = 0.75
    elif section in {"discussion", "conclusion"}:
        section_signal = 0.55
    elif section in {"title", "unknown"}:
        section_signal = 0.35
    else:
        section_signal = 0.45

    stat_signal = 1.0 if has_statistical_detail else statistical_density
    evidence_signal = 1.0 if evidence_quote else 0.0

    score = (
        0.18 * prereg_score
        + 0.16 * threshold_score
        + 0.25 * sample
        + 0.14 * roi_score
        + 0.08 * open_data_score
        + 0.12 * stat_signal
        + 0.08 * section_signal
        + 0.04 * evidence_signal
        + 0.03 * assertive_verb_ratio
        + 0.07 * confidence_hint
    )
    return max(0.0, min(1.0, score))


_PREREGISTRATION_HINT_TERMS = (
    "preregistration",
    "pre-registration",
    "preregistered",
    "pre-registered",
    "registered report",
)
_THRESHOLD_HINT_TERMS = (
    "fwe",
    "fdr",
    "bonferroni",
    "false discovery rate",
    "family-wise",
    "multiple comparison",
    "multiple-comparison",
    "cluster corrected",
    "cluster-level corrected",
)
_ROI_HINT_TERMS = (
    "cortex",
    "gyrus",
    "sulcus",
    "insula",
    "hippocamp",
    "amygdala",
    "thalam",
    "striat",
    "cerebell",
    "prefrontal",
    "frontal",
    "parietal",
    "temporal",
    "occipital",
    "precuneus",
)
_OPEN_DATA_HINT_TERMS = (
    "openneuro",
    "osf",
    "github",
    "gitlab",
    "zenodo",
    "figshare",
    "data available",
    "code available",
    "publicly available",
    "shared dataset",
)


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    if not text:
        return False
    return any(term in text for term in terms)


def _infer_evidence_quality_score(
    payload: dict[str, Any],
    *,
    has_statistical_detail: bool,
    evidence_quote: str,
) -> float:
    explicit_score = _first_float(payload.get("evidence_quality_score"))
    if explicit_score is not None:
        return _clamp01(explicit_score, default=0.0)

    section = _as_nonempty_str(payload.get("section"), "unknown").strip().lower()
    if section in {"results", "methods"}:
        section_score = 0.25
    elif section == "abstract":
        section_score = 0.15
    else:
        section_score = 0.05

    score = section_score
    if has_statistical_detail:
        score += 0.35
    if evidence_quote:
        score += 0.20
        score += 0.20
    return max(0.0, min(1.0, score))


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "unknown"


def _stable_hash(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _ratio(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
