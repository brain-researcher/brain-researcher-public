"""Build autoresearch-specific scientific review bundles."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.autoresearch_review import (
    AutoresearchComponentSummary,
    AutoresearchIterationSummary,
    AutoresearchReviewBundle,
    ValidationEvidenceItem,
)
from brain_researcher.services.review.autoresearch_line_workspace import (
    infer_line_type_from_workspace as infer_workspace_line_type,
)
from brain_researcher.services.review.autoresearch_line_workspace import (
    load_autoresearch_line_state,
    resolve_autoresearch_workspace_layout,
)

_COMPONENTS = (
    "ICA_Cognition",
    "ICA_TobaccoUse",
    "ICA_PersonalityEmotion",
    "ICA_IllicitDrugUse",
    "ICA_MentalHealth",
)

_VALIDATION_PATTERNS: dict[str, tuple[str, ...]] = {
    "permutation_baseline": ("permutation", "permute", "label_shuffle"),
    "alternate_folds": (
        "alternate_fold",
        "alternate folds",
        "repeated_cv",
        "repeat_cv",
    ),
    "deterministic_audit": ("deterministic_audit", "deterministic rerun"),
    "alternate_parcellation_or_gsr": (
        "parcellation",
        "aparc",
        "schaefer200",
        "gsr",
    ),
    "external_cohort_replication": (
        "external cohort",
        "replication cohort",
        "heldout cohort",
    ),
}

_SELF_CRITIQUE_SECTION_TITLES = (
    "so what",
    "method sensitivity",
    "structured exploratory pass",
    "claim strength",
)


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = _read_text(path)
    if not text:
        return rows
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _sha256_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _compute_fingerprint(
    *,
    ledger_text: str | None,
    report_text: str | None,
    predict_text: str | None,
) -> str:
    payload = {
        "experiments_sha256": _sha256_text(ledger_text),
        "final_report_sha256": _sha256_text(report_text),
        "predict_sha256": _sha256_text(predict_text),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _row_results(row: dict[str, Any]) -> dict[str, Any]:
    results = row.get("results") if isinstance(row.get("results"), dict) else {}
    if results:
        return results
    legacy: dict[str, Any] = {}
    for key in (
        "aggregate_mean_r",
        "coverage_fraction",
        "n_hit_mean",
        "n_hit_best",
        "per_component",
    ):
        value = row.get(key)
        if value is not None:
            legacy[key] = value
    return legacy


def _row_summary(row: dict[str, Any]) -> AutoresearchIterationSummary:
    results = _row_results(row)
    config = row.get("config") if isinstance(row.get("config"), dict) else {}
    critique = (
        row.get("self_critique") if isinstance(row.get("self_critique"), dict) else {}
    )
    verdict = critique.get("verdict", row.get("verdict"))
    model = config.get("model", row.get("model"))
    path_value = config.get("path", row.get("path"))
    fc_metric = config.get("fc_metric", row.get("metric"))
    if not fc_metric:
        terms = config.get("terms")
        if isinstance(terms, list) and terms:
            fc_metric = "+".join(str(term) for term in terms if term is not None)
    return AutoresearchIterationSummary(
        iteration=(
            row.get("iteration") if isinstance(row.get("iteration"), int) else None
        ),
        action_type=(
            str(row.get("action_type")).strip() or None
            if row.get("action_type") is not None
            else None
        ),
        aggregate_mean_r=(
            float(results["aggregate_mean_r"])
            if isinstance(results.get("aggregate_mean_r"), int | float)
            else None
        ),
        coverage_fraction=(
            float(results["coverage_fraction"])
            if isinstance(results.get("coverage_fraction"), int | float)
            else None
        ),
        n_hit_mean=(
            int(results["n_hit_mean"])
            if isinstance(results.get("n_hit_mean"), int | float)
            else None
        ),
        verdict=str(verdict).strip() or None if verdict is not None else None,
        model=str(model).strip() or None if model is not None else None,
        fc_metric=str(fc_metric).strip() or None if fc_metric is not None else None,
        path=str(path_value).strip() or None if path_value is not None else None,
    )


def _best_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_value = float("-inf")
    for row in rows:
        results = _row_results(row)
        value = results.get("aggregate_mean_r")
        if not isinstance(value, int | float):
            continue
        if value > best_value:
            best = row
            best_value = float(value)
    return best


def _component_summaries(
    rows: list[dict[str, Any]],
) -> list[AutoresearchComponentSummary]:
    by_component: dict[str, AutoresearchComponentSummary] = {
        component: AutoresearchComponentSummary(component=component)
        for component in _COMPONENTS
    }

    for row in rows:
        iteration = (
            row.get("iteration") if isinstance(row.get("iteration"), int) else None
        )
        results = _row_results(row)
        per_component = (
            results.get("per_component")
            if isinstance(results.get("per_component"), list)
            else []
        )
        for record in per_component:
            if not isinstance(record, dict):
                continue
            component = str(record.get("component") or "").strip()
            if not component:
                continue
            summary = by_component.setdefault(
                component, AutoresearchComponentSummary(component=component)
            )
            fold_mean = record.get("fold_mean_r")
            latest_fold = (
                float(fold_mean) if isinstance(fold_mean, int | float) else None
            )
            summary.latest_fold_mean_r = latest_fold
            summary.latest_iteration = iteration
            ref_mean = record.get("reference_mean_r", record.get("ref_mean_r"))
            ref_best = record.get("reference_best_r", record.get("ref_best_r"))
            if isinstance(ref_mean, int | float):
                summary.reference_mean_r = float(ref_mean)
            if isinstance(ref_best, int | float):
                summary.reference_best_r = float(ref_best)
            if latest_fold is not None and (
                summary.best_fold_mean_r is None
                or latest_fold > summary.best_fold_mean_r
            ):
                summary.best_fold_mean_r = latest_fold
                summary.best_iteration = iteration
            if bool(record.get("hit_mean")):
                summary.ever_hit_mean = True
            if bool(record.get("hit_best")):
                summary.ever_hit_best = True

    return list(by_component.values())


def _quality_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    action_types: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    kg_modes: Counter[str] = Counter()
    n_path_b_rows = 0
    for row in rows:
        action = row.get("action_type")
        if isinstance(action, str) and action.strip():
            action_types[action.strip()] += 1
        critique = row.get("self_critique")
        if isinstance(critique, dict):
            verdict = critique.get("verdict")
            if isinstance(verdict, str) and verdict.strip():
                verdicts[verdict.strip()] += 1
        mode = row.get("kg_integration_mode")
        if isinstance(mode, str) and mode.strip():
            kg_modes[mode.strip()] += 1
        config = row.get("config")
        if (
            isinstance(config, dict)
            and str(config.get("path") or "").strip().upper() == "B"
        ):
            n_path_b_rows += 1
    return {
        "n_rows": len(rows),
        "action_types": dict(action_types),
        "verdicts": dict(verdicts),
        "kg_modes": dict(kg_modes),
        "n_path_b_rows": n_path_b_rows,
    }


def _extract_claim_strength(report_text: str | None) -> str | None:
    if not report_text:
        return None
    match = re.search(
        r"(?:^|\n)\s*(?:[-*]\s*)?(?:\*\*)?claim_strength(?:\*\*)?\s*:\s*"
        r"(contract[-_ ]satisfied|internally[-_ ]supported|scientifically[-_ ]convincing)",
        report_text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return None
    return match.group(1).strip().lower().replace("-", "_").replace(" ", "_")


def _extract_validation_missing(report_text: str | None) -> list[str]:
    if not report_text:
        return []
    match = re.search(
        r"(?:^|\n)\s*(?:[-*]\s*)?(?:\*\*)?validation_missing(?:\*\*)?\s*:\s*(.+)",
        report_text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return []
    return [item.strip() for item in re.split(r"[;,]", match.group(1)) if item.strip()]


def _section_present(report_text: str, section: str) -> bool:
    escaped = re.escape(section)
    patterns = (
        rf"(?im)^\s*#{{1,6}}\s*{escaped}\s*$",
        rf"(?im)^\s*(?:[-*]\s*)?\*\*{escaped}\*\*\s*:?\s*$",
        rf"(?im)^\s*(?:[-*]\s*)?{escaped}\s*:\s*$",
    )
    return any(re.search(pattern, report_text) for pattern in patterns)


def _extract_self_critique_sections(report_text: str | None) -> list[str]:
    if not report_text:
        return []
    return [
        section
        for section in _SELF_CRITIQUE_SECTION_TITLES
        if _section_present(report_text, section)
    ]


def _validation_mentions(
    report_text: str | None, keywords: tuple[str, ...]
) -> list[str]:
    if not report_text:
        return []
    lowered = report_text.lower()
    hits = []
    for keyword in keywords:
        if keyword.lower() in lowered:
            hits.append(keyword)
    return hits


def _artifact_paths_for_validation(
    outputs_dir: Path,
    logs_dir: Path | None,
    keywords: tuple[str, ...],
) -> list[str]:
    candidates: list[str] = []
    search_dirs = [outputs_dir]
    if logs_dir is not None and logs_dir.exists():
        search_dirs.append(logs_dir)
    for root in search_dirs:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            if any(keyword.lower() in name for keyword in keywords):
                candidates.append(str(path))
    return sorted(dict.fromkeys(candidates))


def _validation_evidence(
    report_text: str | None,
    outputs_dir: Path,
    logs_dir: Path | None,
) -> list[ValidationEvidenceItem]:
    items: list[ValidationEvidenceItem] = []
    for name, keywords in _VALIDATION_PATTERNS.items():
        artifact_paths = _artifact_paths_for_validation(outputs_dir, logs_dir, keywords)
        mentions = _validation_mentions(report_text, keywords)
        if artifact_paths:
            status = "present"
            summary = f"Found {len(artifact_paths)} artifact(s) for {name}."
        elif mentions:
            status = "mentioned_only"
            summary = f"Report mentions {name} but no artifact was found."
        else:
            status = "missing"
            summary = f"No report mention or artifact found for {name}."
        items.append(
            ValidationEvidenceItem(
                name=name,
                status=status,
                artifact_paths=artifact_paths,
                report_mentions=mentions,
                summary=summary,
            )
        )
    return items


_TRUSTED_FULL_PIPELINE_PERMUTATION_GENERATORS = frozenset(
    {
        "br_full_pipeline_permutation_harness",
        "br.workflow.full_pipeline_permutation_harness",
    }
)
_TRUSTED_FULL_PIPELINE_INPUT_SCOPES = frozenset(
    {"raw_inputs", "workflow_invocation", "full_pipeline"}
)


def _load_json_if_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _is_trusted_full_pipeline_probe(probe: dict[str, Any]) -> bool:
    scope = str(probe.get("pipeline_scope") or "").strip().lower()
    generated_by = str(probe.get("generated_by") or "").strip().lower()
    input_scope = str(probe.get("input_scope") or "").strip().lower()
    return (
        scope == "full_pipeline"
        and generated_by in _TRUSTED_FULL_PIPELINE_PERMUTATION_GENERATORS
        and input_scope in _TRUSTED_FULL_PIPELINE_INPUT_SCOPES
        and bool(str(probe.get("pipeline_invocation_sha256") or "").strip())
    )


def _label_probe_rank(probe: dict[str, Any]) -> tuple[int, int]:
    return (
        int(_is_trusted_full_pipeline_probe(probe)),
        int(probe.get("n_permutations", 0) or 0),
    )


def _discover_autoresearch_review_sidecars(
    autoresearch_dir: Path,
    outputs_dir: Path,
    logs_dir: Path | None,
) -> dict[str, Any]:
    """Pick up feature_contract and label-permutation-null sidecars emitted
    anywhere under the autoresearch workspace (or its logs directory).

    Multiple feature contracts: take the first one found by deterministic walk
    order. Multiple label-permutation probes: prefer trusted full-pipeline
    probes over feature-matrix-only probes regardless of permutation count.
    """

    search_roots: list[Path] = []
    for candidate in (autoresearch_dir, outputs_dir, logs_dir):
        if candidate is None:
            continue
        if not candidate.exists():
            continue
        if any(candidate == root or candidate in root.parents for root in search_roots):
            continue
        search_roots.append(candidate)

    feature_contracts: list[dict[str, Any]] = []
    label_probes: list[dict[str, Any]] = []
    for root in search_roots:
        for candidate in sorted(root.rglob("feature_contract.json")):
            payload = _load_json_if_dict(candidate)
            if payload is not None:
                feature_contracts.append(payload)
        for candidate in sorted(root.rglob("label_permutation_null.json")):
            if "review_probes" not in candidate.parts:
                continue
            payload = _load_json_if_dict(candidate)
            if payload is not None:
                label_probes.append(payload)

    discovered: dict[str, Any] = {}
    if feature_contracts:
        discovered["feature_contract"] = feature_contracts[0]
    if label_probes:
        discovered["label_permutation_null"] = max(label_probes, key=_label_probe_rank)
    return discovered


def build_autoresearch_review_bundle(
    autoresearch_dir: str | Path,
    *,
    logs_dir: str | Path | None = None,
    task_id: str = "liu_component_v1",
) -> AutoresearchReviewBundle:
    """Build a scientific review bundle for an autoresearch loop workspace."""
    resolved_autoresearch_dir = Path(autoresearch_dir).resolve()
    layout = resolve_autoresearch_workspace_layout(resolved_autoresearch_dir)
    inferred_logs_dir = Path(layout.runner_logs_dir)
    resolved_logs_dir = (
        Path(logs_dir).resolve()
        if logs_dir
        else inferred_logs_dir.resolve() if inferred_logs_dir.exists() else None
    )

    ledger_path = Path(layout.experiments_path)
    final_report_path = Path(layout.final_report_path)
    predict_path = resolved_autoresearch_dir / "predict.py"
    line_state_path = Path(layout.line_state_path)

    ledger_text = _read_text(ledger_path)
    report_text = _read_text(final_report_path)
    predict_text = _read_text(predict_path)
    line_state = load_autoresearch_line_state(line_state_path)
    rows = _read_jsonl(ledger_path)
    latest = rows[-1] if rows else None
    best = _best_row(rows)
    quality = _quality_summary(rows)
    outputs_dir = Path(layout.outputs_dir)

    sidecars = _discover_autoresearch_review_sidecars(
        resolved_autoresearch_dir, outputs_dir, resolved_logs_dir
    )

    review_context = {
        "predict_sha256": _sha256_text(predict_text),
        "ledger_path": str(ledger_path),
        "final_report_path": str(final_report_path),
        "predict_path": str(predict_path),
        "line_state_path": str(line_state_path),
        "line_state_schema_version": (
            line_state.source_schema_version or line_state.schema_version
            if line_state is not None
            else None
        ),
        "workspace_layout_schema_version": layout.schema_version,
        "reference_dirs": list(layout.reference_dirs),
        "line_type": str(
            (line_state.line_type if line_state is not None else "")
            or infer_workspace_line_type(resolved_autoresearch_dir)
        ),
        "line_status": str(line_state.status) if line_state is not None else "",
        "parent_workspace": (
            line_state.parent_workspace if line_state is not None else None
        ),
        "reference_workspace": (
            line_state.reference_workspace if line_state is not None else None
        ),
        "loaded_modules": line_state.loaded_modules if line_state is not None else [],
        "forbidden_modules": (
            line_state.forbidden_modules if line_state is not None else []
        ),
        "training_backend": (
            str(line_state.training_backend or "") if line_state is not None else ""
        ),
        "success_criterion": (
            str(line_state.success_criterion or "") if line_state is not None else ""
        ),
    }

    if sidecars.get("feature_contract"):
        review_context["feature_contract"] = sidecars["feature_contract"]
    if sidecars.get("label_permutation_null"):
        probe = sidecars["label_permutation_null"]
        review_context["review_probes"] = {"label_permutation_null": probe}
        review_context["null_model"] = {"permutation_null": probe}

    return AutoresearchReviewBundle(
        task_id=task_id,
        autoresearch_dir=str(resolved_autoresearch_dir),
        logs_dir=str(resolved_logs_dir) if resolved_logs_dir is not None else None,
        fingerprint=_compute_fingerprint(
            ledger_text=ledger_text,
            report_text=report_text,
            predict_text=predict_text,
        ),
        final_report_present=final_report_path.exists(),
        ledger_row_count=len(rows),
        latest_iteration=latest.get("iteration") if isinstance(latest, dict) else None,
        best_iteration=best.get("iteration") if isinstance(best, dict) else None,
        latest_summary=_row_summary(latest) if isinstance(latest, dict) else None,
        best_summary=_row_summary(best) if isinstance(best, dict) else None,
        recent_iterations=[_row_summary(row) for row in rows[-10:]],
        component_summaries=_component_summaries(rows),
        quality_summary=quality,
        claim_strength_declared=_extract_claim_strength(report_text),
        validation_missing_declared=_extract_validation_missing(report_text),
        validation_evidence=_validation_evidence(
            report_text, outputs_dir, resolved_logs_dir
        ),
        self_critique_sections=_extract_self_critique_sections(report_text),
        final_report_text=report_text,
        review_context=review_context,
    )


__all__ = ["build_autoresearch_review_bundle"]
