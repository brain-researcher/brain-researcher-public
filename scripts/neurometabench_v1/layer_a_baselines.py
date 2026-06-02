#!/usr/bin/env python3
"""Deterministic Layer A baselines for NeurometaBench v1 candidate pools.

The ASReview-style baseline here is intentionally dependency-free. It models
the active-learning loop shape used by ASReview-like screening systems:
rank an initial candidate, receive a specialist label, update a lightweight
text model, and continue. It is not a wrapper around the external ``asreview``
package and does not require network access.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.neurometabench_v1.shared import (
    DEFAULT_CASES_PATH,
    DEFAULT_DATA_DIR,
    load_case_records,
    load_closed_world_candidate_rows,
    load_mixed_pool_candidates,
    read_csv_rows,
    sort_pmids,
    write_jsonl,
)

LAYER_A_SYSTEMS = ("rule", "asreview_style")
LAYER_A_CANDIDATE_SOURCES = ("closed_world", "mixed_pool", "auto")
ASREVIEW_MODES = ("style", "external", "auto")


@dataclass(frozen=True)
class ExternalASReviewDetection:
    checked: bool
    available: bool
    module_name: str = "asreview"
    version: str | None = None
    import_error: str | None = None
    import_error_type: str | None = None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "available": self.available,
            "module_name": self.module_name,
            "version": self.version,
            "import_error": self.import_error,
            "import_error_type": self.import_error_type,
        }


@dataclass(frozen=True)
class Candidate:
    pmid: str
    row: dict[str, str]
    label: str | None


def _unchecked_external_asreview_metadata() -> dict[str, Any]:
    return {
        "checked": False,
        "available": None,
        "module_name": "asreview",
        "version": None,
        "import_error": None,
        "import_error_type": None,
    }


def _external_asreview_metadata(detection: ExternalASReviewDetection | None) -> dict[str, Any]:
    if detection is None:
        return _unchecked_external_asreview_metadata()
    return detection.as_metadata()


def detect_external_asreview() -> ExternalASReviewDetection:
    """Detect whether the optional external ``asreview`` package is importable."""

    module_name = "asreview"
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception as exc:  # pragma: no cover - defensive for unusual import hooks
        return ExternalASReviewDetection(
            checked=True,
            available=False,
            import_error=f"{type(exc).__name__}: {exc}",
            import_error_type=type(exc).__name__,
        )
    if spec is None:
        return ExternalASReviewDetection(
            checked=True,
            available=False,
            import_error="ModuleNotFoundError: No module named 'asreview'",
            import_error_type="ModuleNotFoundError",
        )

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return ExternalASReviewDetection(
            checked=True,
            available=False,
            import_error=f"{type(exc).__name__}: {exc}",
            import_error_type=type(exc).__name__,
        )

    version: str | None = None
    try:
        version = importlib.metadata.version(module_name)
    except importlib.metadata.PackageNotFoundError:
        raw_version = getattr(module, "__version__", None)
        version = str(raw_version) if raw_version else None
    except Exception:  # pragma: no cover - version metadata is best effort
        raw_version = getattr(module, "__version__", None)
        version = str(raw_version) if raw_version else None
    return ExternalASReviewDetection(checked=True, available=True, version=version)


def _external_asreview_unavailable_message(detection: ExternalASReviewDetection) -> str:
    detail = detection.import_error or "optional package was not importable"
    return (
        "ASReview external mode requested, but the optional package 'asreview' is unavailable. "
        "Activate an environment that already provides ASReview, or rerun with "
        f"--asreview-mode style/auto. Detection detail: {detail}"
    )


def _external_asreview_unverified_message(detection: ExternalASReviewDetection) -> str:
    version = detection.version or "unknown version"
    return (
        "ASReview external mode is detectable "
        f"({detection.module_name} {version}), but this harness has not verified an external "
        "ASReview API wrapper yet. Refusing to emit external_asreview predictions. "
        "Use --asreview-mode style for the dependency-free ASReview-style baseline until the "
        "wrapper is implemented and tested."
    )


def _annotate_asreview_prediction(
    prediction: dict[str, Any] | None,
    *,
    requested_mode: str,
    resolved_mode: str,
    backend: str,
    detection: ExternalASReviewDetection | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any] | None:
    if prediction is None:
        return None

    out = dict(prediction)
    metadata = dict(out.get("metadata") or {})
    metadata.update(
        {
            "asreview_mode_requested": requested_mode,
            "asreview_mode_resolved": resolved_mode,
            "asreview_backend": backend,
            "external_asreview_attempted": backend == "external_asreview",
            "external_asreview_detection": _external_asreview_metadata(detection),
            "fallback_from_external_asreview": fallback_reason is not None,
            "fallback_reason": fallback_reason,
        }
    )
    if fallback_reason is not None:
        metadata["fallback_from"] = "external_asreview"
        metadata["fallback_to"] = "asreview_style"
    else:
        metadata["fallback_from"] = None
        metadata["fallback_to"] = None

    out["metadata"] = metadata
    out["asreview_mode_requested"] = requested_mode
    out["asreview_mode_resolved"] = resolved_mode
    out["asreview_backend"] = backend
    return out


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(text: str) -> list[str]:
    stopwords = {
        "and",
        "article",
        "articles",
        "brain",
        "control",
        "controls",
        "data",
        "english",
        "functional",
        "human",
        "humans",
        "imaging",
        "included",
        "language",
        "magnetic",
        "meta",
        "mri",
        "only",
        "original",
        "paper",
        "papers",
        "participant",
        "participants",
        "reported",
        "reporting",
        "resonance",
        "review",
        "reviews",
        "studies",
        "study",
        "the",
        "using",
        "with",
    }
    seen: set[str] = set()
    out: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text.lower()):
        token = token.strip("-")
        if not token or token in stopwords or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _case_text(case: dict[str, Any]) -> str:
    return " ".join(
        _clean_text(case.get(field))
        for field in ("topic", "search", "inclusion", "exclusion", "additional_methods", "method", "modality")
    )


def _candidate_text(candidate: Candidate) -> str:
    row = candidate.row
    return " ".join(
        _clean_text(row.get(field))
        for field in (
            "title",
            "abstract",
            "author",
            "Author",
            "year",
            "reason",
            "posthoc_reason",
            "SourceSheet",
        )
    )


def _pmid_key(pmid: str) -> tuple[int, str]:
    return (int(pmid), pmid) if str(pmid).isdigit() else (10**20, str(pmid))


def _selected_n(case: dict[str, Any], fallback: int) -> int:
    raw = str(case.get("selected_n") or "").strip()
    match = re.search(r"\d+", raw)
    if not match:
        return fallback
    return max(1, min(int(match.group()), fallback))


def _normalize_label(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"yes", "include", "included", "selected", "true", "1"}:
        return "include"
    if text in {"no", "exclude", "excluded", "false", "0"}:
        return "exclude"
    return None


def _candidate_label(row: dict[str, str], gt_pmids: set[str], pmid: str, meta_pmid: str) -> str | None:
    # Curated row labels only apply to the row's own meta-analysis. Mixed-pool
    # noise often comes from another case, where a YES label would be wrong for
    # the current target.
    if str(row.get("meta_pmid") or "").strip() == meta_pmid:
        for field in ("corrected_status", "final_status", "posthoc_status", "status"):
            label = _normalize_label(row.get(field))
            if label:
                return label
    if pmid in gt_pmids:
        return "include"
    if gt_pmids:
        return "exclude"
    return None


def _candidate_row(pmid: str) -> dict[str, str]:
    return {"study_pmid": str(pmid)}


def _metadata_by_pmid(data_dir: Path) -> dict[str, dict[str, str]]:
    """Return best-effort candidate metadata keyed by PMID.

    The mixed-pool source is PMID-only, but the repository contains title/author
    metadata for most PMIDs. Prefer title-bearing files and preserve the first
    row for a PMID to keep the lookup deterministic.
    """

    out: dict[str, dict[str, str]] = {}
    for filename in (
        "included_studies_wt.csv",
        "all_studies_annotated_wt.csv",
        "all_studies_annotated.csv",
        "all_studies.csv",
    ):
        src = data_dir / filename
        if not src.exists():
            continue
        for row in read_csv_rows(src):
            pmid = str(row.get("study_pmid") or row.get("pmid") or "").strip()
            if pmid and pmid not in out:
                out[pmid] = dict(row)
    return out


def load_layer_a_candidate_pool(
    case: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    candidate_source: str = "auto",
    mixed_noise_ratio: int = 5,
    mixed_seed: int = 0,
    mixed_max_total: int | None = None,
) -> tuple[str, list[Candidate]]:
    """Load a deterministic Layer A candidate pool for one case.

    ``candidate_source="auto"`` prefers curated closed-world rows when they
    exist and otherwise falls back to the mixed GT+noise pool.
    """

    if candidate_source not in LAYER_A_CANDIDATE_SOURCES:
        raise ValueError(f"Unsupported candidate_source={candidate_source!r}")

    meta_pmid = str(case.get("meta_pmid") or "")
    gt_pmids = {str(pmid) for pmid in case.get("gt_pmids", []) if str(pmid).strip()}
    rows: list[dict[str, str]] = []
    resolved_source = candidate_source

    if candidate_source in {"closed_world", "auto"}:
        rows = load_closed_world_candidate_rows(data_dir, meta_pmid)
        if rows:
            resolved_source = "closed_world"
        elif candidate_source == "closed_world":
            return resolved_source, []

    if not rows:
        metadata = _metadata_by_pmid(data_dir)
        pmids = load_mixed_pool_candidates(
            data_dir,
            meta_pmid,
            noise_ratio=mixed_noise_ratio,
            seed=mixed_seed,
            max_total=mixed_max_total,
        )
        rows = []
        for pmid in sort_pmids(pmids):
            row = dict(metadata.get(str(pmid), _candidate_row(pmid)))
            row.setdefault("study_pmid", str(pmid))
            rows.append(row)
        resolved_source = "mixed_pool"

    candidates: list[Candidate] = []
    seen: set[str] = set()
    for row in rows:
        pmid = str(row.get("study_pmid") or row.get("pmid") or "").strip()
        if not pmid or pmid in seen:
            continue
        seen.add(pmid)
        candidates.append(Candidate(pmid=pmid, row=dict(row), label=_candidate_label(row, gt_pmids, pmid, meta_pmid)))
    return resolved_source, candidates


def lexical_rule_score(case: dict[str, Any], candidate: Candidate) -> float:
    query_tokens = set(_tokens(_case_text(case)))
    doc_tokens = _tokens(_candidate_text(candidate))
    if not query_tokens or not doc_tokens:
        return 0.0
    score = 0.0
    for token in doc_tokens:
        if token in query_tokens:
            score += 1.0
        elif any(token in query or query in token for query in query_tokens):
            score += 0.25
    title = (candidate.row.get("title") or "").lower()
    for phrase in ("functional mri", "voxel-based morphometry", "gray matter", "grey matter", "pet"):
        if phrase in title and any(part in query_tokens for part in phrase.split()):
            score += 0.5
    return score


def _criterion_ids(case: dict[str, Any], decision: str) -> list[str]:
    polarity = "include" if decision == "include" else "exclude"
    ids = [
        str(row.get("criterion_id"))
        for row in case.get("screening_criteria", [])
        if row.get("criterion_id") and row.get("polarity") == polarity
    ]
    return ids[:3]


def _decision_record(
    case: dict[str, Any],
    candidate: Candidate,
    *,
    decision: str,
    reason: str,
    confidence: float,
    rank: int,
    score: float | None = None,
    specialist_label: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "pmid": candidate.pmid,
        "study_pmid": candidate.pmid,
        "decision": decision,
        "rank": rank,
        "title": _clean_text(candidate.row.get("title")),
        "criterion_ids": _criterion_ids(case, decision),
        "evidence_spans": [],
        "reason": reason,
        "confidence": round(max(0.0, min(1.0, confidence)), 6),
    }
    if score is not None:
        record["score"] = round(score, 6)
    if specialist_label is not None:
        record["specialist_label"] = specialist_label
    return record


def build_rule_baseline_prediction(
    case: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    candidate_source: str = "auto",
    mixed_noise_ratio: int = 5,
    mixed_seed: int = 0,
    mixed_max_total: int | None = None,
) -> dict[str, Any] | None:
    """Build a deterministic lexical rule baseline prediction for one case."""

    resolved_source, candidates = load_layer_a_candidate_pool(
        case,
        data_dir=data_dir,
        candidate_source=candidate_source,
        mixed_noise_ratio=mixed_noise_ratio,
        mixed_seed=mixed_seed,
        mixed_max_total=mixed_max_total,
    )
    if not candidates:
        return None

    scored = [(candidate, lexical_rule_score(case, candidate)) for candidate in candidates]
    scored.sort(key=lambda item: (-item[1], _pmid_key(item[0].pmid)))
    top_n = _selected_n(case, len(scored))
    ranked_pmids = [candidate.pmid for candidate, _ in scored]
    predicted_pmids = ranked_pmids[:top_n]
    predicted = set(predicted_pmids)
    max_score = max((score for _, score in scored), default=0.0) or 1.0
    decision_records = [
        _decision_record(
            case,
            candidate,
            decision="include" if candidate.pmid in predicted else "exclude",
            reason=(
                "Selected by deterministic lexical overlap with the case query and candidate metadata."
                if candidate.pmid in predicted
                else "Not selected because higher-scoring candidates filled the deterministic top-n rule budget."
            ),
            confidence=0.5 + 0.49 * (score / max_score) if candidate.pmid in predicted else 0.5,
            rank=rank,
            score=score,
        )
        for rank, (candidate, score) in enumerate(scored, 1)
    ]
    return {
        "case_id": case.get("case_id"),
        "meta_pmid": case.get("meta_pmid"),
        "system": "layer_a_rule_lexical",
        "candidate_source": resolved_source,
        "ranked_pmids": ranked_pmids,
        "predicted_pmids": predicted_pmids,
        "decision_records": decision_records,
        "baseline": True,
        "baseline_family": "deterministic_rule",
        "selection_rule": "lexical_overlap_top_selected_n",
        "selected_n": top_n,
        "n_candidates": len(candidates),
        "metadata": {
            "network_required": False,
            "deterministic": True,
            "uses_specialist_feedback": False,
            "mixed_noise_ratio": mixed_noise_ratio if resolved_source == "mixed_pool" else None,
            "mixed_seed": mixed_seed if resolved_source == "mixed_pool" else None,
        },
    }


def _model_score(
    candidate: Candidate,
    *,
    prior_score: float,
    include_terms: Counter[str],
    exclude_terms: Counter[str],
    n_include: int,
    n_exclude: int,
) -> float:
    doc_terms = _tokens(_candidate_text(candidate))
    vocab = set(include_terms) | set(exclude_terms) | set(doc_terms)
    if not doc_terms or not vocab:
        return prior_score

    alpha = 1.0
    include_total = sum(include_terms.values()) + alpha * len(vocab)
    exclude_total = sum(exclude_terms.values()) + alpha * len(vocab)
    log_odds = math.log((n_include + 1) / (n_exclude + 1))
    for token in doc_terms:
        p_inc = (include_terms[token] + alpha) / include_total
        p_exc = (exclude_terms[token] + alpha) / exclude_total
        log_odds += math.log(p_inc / p_exc)
    return prior_score + log_odds


def build_asreview_style_prediction(
    case: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    candidate_source: str = "auto",
    mixed_noise_ratio: int = 5,
    mixed_seed: int = 0,
    mixed_max_total: int | None = None,
    screening_budget: int | None = None,
    prior_weight: float = 0.25,
) -> dict[str, Any] | None:
    """Build an ASReview-like active-learning/specialist prediction.

    The specialist labels come from candidate annotations when available and
    otherwise from the benchmark case ground truth. The active learner only
    observes a label after choosing a candidate to screen.
    """

    resolved_source, candidates = load_layer_a_candidate_pool(
        case,
        data_dir=data_dir,
        candidate_source=candidate_source,
        mixed_noise_ratio=mixed_noise_ratio,
        mixed_seed=mixed_seed,
        mixed_max_total=mixed_max_total,
    )
    labeled_candidates = [candidate for candidate in candidates if candidate.label in {"include", "exclude"}]
    if not labeled_candidates:
        return None

    default_budget = _selected_n(case, len(labeled_candidates))
    budget = default_budget if screening_budget is None else max(0, min(int(screening_budget), len(labeled_candidates)))
    prior_scores = {candidate.pmid: lexical_rule_score(case, candidate) for candidate in labeled_candidates}
    unscreened = {candidate.pmid: candidate for candidate in labeled_candidates}
    include_terms: Counter[str] = Counter()
    exclude_terms: Counter[str] = Counter()
    n_include = 0
    n_exclude = 0
    ranked_pmids: list[str] = []
    predicted_pmids: list[str] = []
    decision_records: list[dict[str, Any]] = []

    for rank in range(1, budget + 1):
        scored = [
            (
                _model_score(
                    candidate,
                    prior_score=prior_weight * prior_scores[candidate.pmid],
                    include_terms=include_terms,
                    exclude_terms=exclude_terms,
                    n_include=n_include,
                    n_exclude=n_exclude,
                ),
                candidate,
            )
            for candidate in unscreened.values()
        ]
        scored.sort(key=lambda item: (-item[0], _pmid_key(item[1].pmid)))
        score, candidate = scored[0]
        del unscreened[candidate.pmid]
        ranked_pmids.append(candidate.pmid)

        label = candidate.label or "exclude"
        decision = "include" if label == "include" else "exclude"
        if decision == "include":
            predicted_pmids.append(candidate.pmid)
            include_terms.update(_tokens(_candidate_text(candidate)))
            n_include += 1
        else:
            exclude_terms.update(_tokens(_candidate_text(candidate)))
            n_exclude += 1

        decision_records.append(
            _decision_record(
                case,
                candidate,
                decision=decision,
                reason=(
                    "ASReview-style active learner selected this candidate; specialist feedback labeled it as include."
                    if decision == "include"
                    else "ASReview-style active learner selected this candidate; specialist feedback labeled it as exclude."
                ),
                confidence=0.95,
                rank=rank,
                score=score,
                specialist_label=label,
            )
        )

    remainder = sorted(unscreened.values(), key=lambda candidate: (-prior_scores[candidate.pmid], _pmid_key(candidate.pmid)))
    ranked_pmids.extend(candidate.pmid for candidate in remainder)

    return {
        "case_id": case.get("case_id"),
        "meta_pmid": case.get("meta_pmid"),
        "system": "layer_a_asreview_style_specialist",
        "candidate_source": resolved_source,
        "ranked_pmids": ranked_pmids,
        "predicted_pmids": predicted_pmids,
        "decision_records": decision_records,
        "baseline": True,
        "baseline_family": "asreview_style_active_learning",
        "active_learning_model": "dependency_free_multinomial_nb_like_text_model",
        "specialist_feedback_source": (
            "candidate_annotation_status_or_benchmark_ground_truth_after_screening"
        ),
        "screening_budget": budget,
        "default_screening_budget_policy": "selected_n" if screening_budget is None else "explicit",
        "n_candidates": len(candidates),
        "n_labeled_candidates": len(labeled_candidates),
        "metadata": {
            "network_required": False,
            "deterministic": True,
            "external_asreview_required": False,
            "asreview_mode_requested": "style",
            "asreview_mode_resolved": "style",
            "asreview_backend": "asreview_style",
            "external_asreview_attempted": False,
            "external_asreview_detection": _unchecked_external_asreview_metadata(),
            "fallback_from_external_asreview": False,
            "fallback_reason": None,
            "fallback_from": None,
            "fallback_to": None,
            "uses_specialist_feedback": True,
            "feedback_observed_after_candidate_selection": True,
            "mixed_noise_ratio": mixed_noise_ratio if resolved_source == "mixed_pool" else None,
            "mixed_seed": mixed_seed if resolved_source == "mixed_pool" else None,
        },
    }


def build_external_asreview_prediction(
    case: dict[str, Any],
    *,
    external_asreview_detection: ExternalASReviewDetection | None = None,
    **_: Any,
) -> dict[str, Any] | None:
    """Guarded placeholder for real external ASReview execution.

    The package is optional, and the harness must not claim external ASReview
    execution until the API wrapper is verified against the installed package.
    """

    detection = external_asreview_detection or detect_external_asreview()
    if not detection.available:
        raise RuntimeError(_external_asreview_unavailable_message(detection))
    raise NotImplementedError(_external_asreview_unverified_message(detection))


def build_asreview_baseline_prediction(
    case: dict[str, Any],
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    candidate_source: str = "auto",
    mixed_noise_ratio: int = 5,
    mixed_seed: int = 0,
    mixed_max_total: int | None = None,
    screening_budget: int | None = None,
    prior_weight: float = 0.25,
    asreview_mode: str = "style",
    external_asreview_detection: ExternalASReviewDetection | None = None,
) -> dict[str, Any] | None:
    """Build an ASReview baseline prediction according to the requested mode."""

    if asreview_mode not in ASREVIEW_MODES:
        raise ValueError(f"Unsupported asreview_mode={asreview_mode!r}")

    if asreview_mode == "style":
        return _annotate_asreview_prediction(
            build_asreview_style_prediction(
                case,
                data_dir=data_dir,
                candidate_source=candidate_source,
                mixed_noise_ratio=mixed_noise_ratio,
                mixed_seed=mixed_seed,
                mixed_max_total=mixed_max_total,
                screening_budget=screening_budget,
                prior_weight=prior_weight,
            ),
            requested_mode="style",
            resolved_mode="style",
            backend="asreview_style",
        )

    detection = external_asreview_detection or detect_external_asreview()
    if asreview_mode == "external":
        return build_external_asreview_prediction(case, external_asreview_detection=detection)

    if detection.available:
        return build_external_asreview_prediction(case, external_asreview_detection=detection)

    return _annotate_asreview_prediction(
        build_asreview_style_prediction(
            case,
            data_dir=data_dir,
            candidate_source=candidate_source,
            mixed_noise_ratio=mixed_noise_ratio,
            mixed_seed=mixed_seed,
            mixed_max_total=mixed_max_total,
            screening_budget=screening_budget,
            prior_weight=prior_weight,
        ),
        requested_mode="auto",
        resolved_mode="style",
        backend="asreview_style",
        detection=detection,
        fallback_reason="external_asreview_unavailable",
    )


def build_layer_a_baseline_predictions(
    cases_path: Path,
    output: Path,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    systems: Iterable[str] = LAYER_A_SYSTEMS,
    meta_pmids: Iterable[str] = (),
    candidate_source: str = "auto",
    only_with_gt: bool = True,
    max_cases: int | None = None,
    mixed_noise_ratio: int = 5,
    mixed_seed: int = 0,
    mixed_max_total: int | None = None,
    screening_budget: int | None = None,
    asreview_mode: str = "style",
) -> dict[str, Any]:
    """Write v1 prediction JSONL rows for deterministic Layer A baselines."""

    requested_systems = tuple(systems)
    unknown = sorted(set(requested_systems) - set(LAYER_A_SYSTEMS))
    if unknown:
        raise ValueError(f"Unsupported systems: {unknown}")
    if asreview_mode not in ASREVIEW_MODES:
        raise ValueError(f"Unsupported asreview_mode={asreview_mode!r}")
    wanted_meta_pmids = {str(pmid).strip() for pmid in meta_pmids if str(pmid).strip()}
    external_asreview_detection: ExternalASReviewDetection | None = None
    if "asreview_style" in requested_systems and asreview_mode in {"external", "auto"}:
        external_asreview_detection = detect_external_asreview()
        if asreview_mode == "external" and not external_asreview_detection.available:
            raise RuntimeError(_external_asreview_unavailable_message(external_asreview_detection))

    cases = load_case_records(cases_path)
    cases = [
        case
        for case in cases
        if case.get("primary_task_layer") == "layer_a_screening_with_justification"
        or "layer_a_screening_with_justification" in (case.get("task_layers") or [])
    ]
    if wanted_meta_pmids:
        cases = [
            case
            for case in cases
            if str(case.get("meta_pmid") or "").strip() in wanted_meta_pmids
            or str(case.get("case_id") or "").strip() in wanted_meta_pmids
            or f"neurometabench:{str(case.get('meta_pmid') or '').strip()}" in wanted_meta_pmids
        ]
    if only_with_gt:
        cases = [case for case in cases if case.get("has_gt")]
    if max_cases is not None:
        cases = cases[: max(0, int(max_cases))]

    predictions: list[dict[str, Any]] = []
    skipped_cases: list[dict[str, Any]] = []
    for case in cases:
        before = len(predictions)
        if "rule" in requested_systems:
            prediction = build_rule_baseline_prediction(
                case,
                data_dir=data_dir,
                candidate_source=candidate_source,
                mixed_noise_ratio=mixed_noise_ratio,
                mixed_seed=mixed_seed,
                mixed_max_total=mixed_max_total,
            )
            if prediction is not None:
                predictions.append(prediction)
        if "asreview_style" in requested_systems:
            prediction = build_asreview_baseline_prediction(
                case,
                data_dir=data_dir,
                candidate_source=candidate_source,
                mixed_noise_ratio=mixed_noise_ratio,
                mixed_seed=mixed_seed,
                mixed_max_total=mixed_max_total,
                screening_budget=screening_budget,
                asreview_mode=asreview_mode,
                external_asreview_detection=external_asreview_detection,
            )
            if prediction is not None:
                predictions.append(prediction)
        if len(predictions) == before:
            skipped_cases.append(
                {
                    "case_id": case.get("case_id"),
                    "meta_pmid": case.get("meta_pmid"),
                    "reason": "no_candidate_pool_or_no_labels",
                }
            )

    write_jsonl(predictions, output)
    return {
        "output": str(output),
        "n_cases_considered": len(cases),
        "n_predictions": len(predictions),
        "systems": list(requested_systems),
        "meta_pmids": sorted(wanted_meta_pmids),
        "candidate_source": candidate_source,
        "only_with_gt": only_with_gt,
        "mixed_noise_ratio": mixed_noise_ratio,
        "mixed_seed": mixed_seed,
        "mixed_max_total": mixed_max_total,
        "screening_budget": screening_budget,
        "asreview_mode": asreview_mode,
        "external_asreview_detection": _external_asreview_metadata(external_asreview_detection),
        "skipped_cases": skipped_cases,
    }


def _parse_systems(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _load_meta_pmids_file(path: Path) -> list[str]:
    pmids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if clean and not clean.startswith("#"):
            pmids.append(clean)
    return pmids


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=Path("/tmp/neurometabench_v1/layer_a_baseline_predictions.jsonl"))
    parser.add_argument("--systems", default="rule,asreview_style")
    parser.add_argument("--meta-pmid", action="append", default=[], help="Layer A meta-analysis PMID to include. Repeatable.")
    parser.add_argument("--meta-pmids-file", type=Path, help="Text file with one meta-analysis PMID per line.")
    parser.add_argument("--candidate-source", choices=LAYER_A_CANDIDATE_SOURCES, default="auto")
    parser.add_argument(
        "--asreview-mode",
        choices=ASREVIEW_MODES,
        default="style",
        help=(
            "ASReview baseline backend: style keeps the dependency-free ASReview-style baseline; "
            "external requires the optional asreview package and currently refuses unverified execution; "
            "auto uses external only when detectable, otherwise records a style fallback in metadata."
        ),
    )
    parser.add_argument("--include-empty-gt", action="store_true")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--mixed-noise-ratio", type=int, default=5)
    parser.add_argument("--mixed-seed", type=int, default=0)
    parser.add_argument("--mixed-max-total", type=int)
    parser.add_argument(
        "--screening-budget",
        type=int,
        help="Number of candidates the ASReview-style specialist baseline screens; defaults to selected_n per case.",
    )
    args = parser.parse_args()
    meta_pmids = list(args.meta_pmid)
    if args.meta_pmids_file is not None:
        meta_pmids.extend(_load_meta_pmids_file(args.meta_pmids_file))
    print(
        json.dumps(
            build_layer_a_baseline_predictions(
                args.cases,
                args.output,
                data_dir=args.data_dir,
                systems=_parse_systems(args.systems),
                meta_pmids=meta_pmids,
                candidate_source=args.candidate_source,
                only_with_gt=not args.include_empty_gt,
                max_cases=args.max_cases,
                mixed_noise_ratio=args.mixed_noise_ratio,
                mixed_seed=args.mixed_seed,
                mixed_max_total=args.mixed_max_total,
                screening_budget=args.screening_budget,
                asreview_mode=args.asreview_mode,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
