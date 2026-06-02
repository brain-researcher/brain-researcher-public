"""Deterministic neuroAI generalization-validity checks for scientific review.

These checks are intentionally conservative:
- they only fire on explicit selection / split / accounting metadata
- they do not infer leakage from prose or weak suspicion
- they are designed for neuroAI-style candidate selection across models,
  layers, ROIs, prompts, or similar representations
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from brain_researcher.core.contracts.code_review import CodeReviewBundle, ReviewFinding

_NEUROAI_ANALYSIS_FAMILIES = frozenset(
    {
        "embedding_analysis",
        "neural_encoding_prediction",
        "neuroai",
        "tribe_prediction",
    }
)
_SELECTION_SECTION_KEYS = (
    "selection",
    "winner_selection",
    "model_selection",
    "layer_selection",
    "roi_selection",
    "prompt_selection",
    "evaluation",
    "split",
)
_SELECTION_FLAG_KEYS = (
    "selection_on_test",
    "selected_on_test",
    "winner_selected_on_test",
    "heldout_selection",
    "held_out_selection",
    "test_set_selection",
)
_SELECTION_SCOPE_KEYS = (
    "selection_scope",
    "selection_phase",
    "winner_selection_scope",
    "winner_selection_phase",
)
_WINNER_KEYS = (
    "winner",
    "best_candidate",
    "selected_candidate",
    "best_model",
    "selected_model",
    "best_layer",
    "selected_layer",
    "best_roi",
    "selected_roi",
    "best_prompt",
    "selected_prompt",
    "top_model",
    "top_layer",
    "top_roi",
    "top_prompt",
)
_CANDIDATE_COUNT_KEYS = {
    "models": (
        "n_models",
        "model_count",
        "candidate_model_count",
        "models_compared",
    ),
    "layers": (
        "n_layers",
        "layer_count",
        "candidate_layer_count",
        "layers_compared",
    ),
    "rois": (
        "n_rois",
        "roi_count",
        "candidate_roi_count",
        "rois_compared",
    ),
    "prompts": (
        "n_prompts",
        "prompt_count",
        "candidate_prompt_count",
        "prompts_compared",
    ),
    "candidates": (
        "candidate_count",
        "n_candidates",
        "comparison_count",
        "search_space_size",
    ),
}
_CANDIDATE_LIST_KEYS = {
    "models": ("model_candidates", "candidate_models", "models", "model_grid"),
    "layers": ("layer_candidates", "candidate_layers", "layers", "layer_grid"),
    "rois": ("roi_candidates", "candidate_rois", "rois", "roi_grid"),
    "prompts": ("prompt_candidates", "candidate_prompts", "prompts", "prompt_grid"),
    "candidates": ("candidates", "comparison_candidates", "winner_candidates"),
}
_ACCOUNTING_KEYS = (
    "selection_accounting",
    "multiplicity_accounting",
    "multiple_comparison_correction",
    "multiple_testing_correction",
    "winner_selection_method",
    "winner_selection_criterion",
    "winner_selection_protocol",
    "nested_cv",
    "selection_holdout",
    "independent_validation",
)
_VALIDATION_GUARDRAIL_KEYS = (
    "nested_cv",
    "selection_holdout",
    "independent_validation",
)
_REQUIRED_GROUP_KEYS = (
    "required_group_keys",
    "required_grouping_keys",
    "grouping_required_keys",
    "mandatory_group_keys",
    "required_split_groups",
)
_GROUPED_SPLIT_KEYS = (
    "grouped_split_keys",
    "split_group_keys",
    "group_keys",
    "split_keys",
)
_MANIFEST_PATH_KEYS = (
    "fold_manifest_path",
    "cv_manifest_path",
    "split_manifest_path",
)
_SUBJECT_MANIFEST_PATH_KEYS = ("subject_manifest_path",)
_SUBJECT_INTERSECTION_PATH_KEYS = ("subject_intersection_manifest_path",)
_SUBJECT_SELECTION_SOURCE_KEYS = ("subject_selection_source",)
_SUBJECT_ID_KEYS = ("subject", "subject_id", "participant_id")
_MANIFEST_PARTITION_KEYS = (
    "partition",
    "split",
    "set",
    "role",
    "assignment",
)
_MANIFEST_FOLD_KEYS = (
    "fold",
    "fold_id",
    "outer_fold",
    "cv_fold",
    "split_id",
    "repeat",
    "repeat_id",
)
_OUTER_FOLD_KEYS = (
    "outer_fold",
    "outer_fold_id",
    "outer_cv_fold",
)
_INNER_FOLD_KEYS = (
    "inner_fold",
    "inner_fold_id",
    "inner_cv_fold",
    "selection_fold",
    "validation_fold",
    "val_fold",
    "nested_fold",
)
_FINE_GRAINED_SPLIT_UNITS = frozenset(
    {
        "tr",
        "timepoint",
        "time_point",
        "sample",
        "trial",
        "token",
        "row",
    }
)
_RANDOM_SPLIT_TOKENS = frozenset(
    {
        "random",
        "randomized",
        "randomised",
        "shuffle",
        "shuffled",
    }
)


def _artifact_dict(bundle: CodeReviewBundle, key: str) -> dict[str, Any]:
    value = bundle.observed_artifacts.get(key)
    return value if isinstance(value, dict) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Iterable):
        values = list(value)
    else:
        return []

    cleaned: list[str] = []
    for item in values:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def _explicit_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _normalize_text(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _has_value(value: object) -> bool:
    return value not in (None, "", [], {}, ())


def _review_context(bundle: CodeReviewBundle) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    if isinstance(getattr(bundle, "review_context", None), dict):
        candidates.append(dict(bundle.review_context))

    for artifact_key in ("review_context", "source_summary"):
        artifact = _artifact_dict(bundle, artifact_key)
        if artifact_key == "source_summary":
            nested = artifact.get("review_context")
            if isinstance(nested, dict):
                candidates.append(dict(nested))
        else:
            candidates.append(artifact)

    contract = _artifact_dict(bundle, "review_contract")
    contract_context = contract.get("review_context")
    if isinstance(contract_context, dict):
        candidates.append(dict(contract_context))

    analysis_bundle = _artifact_dict(bundle, "analysis_bundle")
    analysis_context = analysis_bundle.get("review_context")
    if isinstance(analysis_context, dict):
        candidates.append(dict(analysis_context))

    stats_context = bundle.stats_metrics.get("review_context")
    if isinstance(stats_context, dict):
        candidates.append(dict(stats_context))

    kg_context = bundle.kg_context.get("review_context")
    if isinstance(kg_context, dict):
        candidates.append(dict(kg_context))

    merged: dict[str, Any] = {}
    for candidate in candidates:
        merged.update(candidate)
    return merged


def _nested_mapping(context: Mapping[str, object], key: str) -> dict[str, Any]:
    value = context.get(key)
    return value if isinstance(value, dict) else {}


def _section_candidates(context: Mapping[str, object]) -> list[dict[str, Any]]:
    sections = [dict(context)]
    for key in _SELECTION_SECTION_KEYS:
        nested = _nested_mapping(context, key)
        if nested:
            sections.append(nested)
    return sections


def _analysis_family(bundle: CodeReviewBundle) -> str:
    return str(bundle.kg_context.get("analysis_family") or "").strip().lower()


def _is_neuroai_context(
    bundle: CodeReviewBundle, context: Mapping[str, object]
) -> bool:
    analysis_family = _analysis_family(bundle)
    if analysis_family in _NEUROAI_ANALYSIS_FAMILIES:
        return True
    if any(
        key in context
        for key in (
            "model_candidates",
            "layer_candidates",
            "roi_candidates",
            "prompt_candidates",
        )
    ):
        return True
    selection = _nested_mapping(context, "selection")
    return any(key in selection for key in _WINNER_KEYS)


def _collect_selection_flags(context: Mapping[str, object]) -> list[str]:
    flags: list[str] = []
    for section in _section_candidates(context):
        for key in _SELECTION_FLAG_KEYS:
            value = section.get(key)
            if _explicit_bool(value):
                flags.append(f"{key}=true")
                continue
            if isinstance(value, str):
                normalized = _normalize_text(value)
                if any(
                    token in normalized for token in ("test", "heldout", "held_out")
                ):
                    flags.append(f"{key}={normalized}")
        for key in _SELECTION_SCOPE_KEYS:
            value = section.get(key)
            if not isinstance(value, str):
                continue
            normalized = _normalize_text(value)
            if any(token in normalized for token in ("test", "heldout", "held_out")):
                flags.append(f"{key}={normalized}")
    return sorted(dict.fromkeys(flags))


def _collect_winner_fields(context: Mapping[str, object]) -> list[str]:
    winner_fields: list[str] = []
    for section in _section_candidates(context):
        for key in _WINNER_KEYS:
            value = section.get(key)
            if _has_value(value):
                winner_fields.append(f"{key}={value!r}")
    return sorted(dict.fromkeys(winner_fields))


def _collect_group_keys(
    context: Mapping[str, object], keys: tuple[str, ...]
) -> set[str]:
    values: set[str] = set()
    for section in _section_candidates(context):
        for key in keys:
            values.update(_string_list(section.get(key)))
    return {value.lower() for value in values if value}


def _split_unit(context: Mapping[str, object]) -> str:
    for section in _section_candidates(context):
        for key in ("split_unit", "cv_unit", "split_axis"):
            value = section.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_text(value)
    return ""


def _split_strategy(context: Mapping[str, object]) -> str:
    for section in _section_candidates(context):
        for key in ("split_strategy", "split_strategy_detail", "split_method"):
            value = section.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_text(value)
    return ""


def _required_group_keys(context: Mapping[str, object]) -> set[str]:
    return _collect_group_keys(context, _REQUIRED_GROUP_KEYS)


def _grouped_split_keys(context: Mapping[str, object]) -> set[str]:
    return _collect_group_keys(context, _GROUPED_SPLIT_KEYS)


def _candidate_family_counts(context: Mapping[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for section in _section_candidates(context):
        for family, keys in _CANDIDATE_COUNT_KEYS.items():
            for key in keys:
                value = section.get(key)
                if isinstance(value, bool) or value is None:
                    continue
                if isinstance(value, int):
                    if value > 0:
                        counts[family] = max(counts.get(family, 0), value)
                    continue
                if isinstance(value, str):
                    normalized = value.strip()
                    if normalized.isdigit():
                        counts[family] = max(counts.get(family, 0), int(normalized))
                    continue
                if isinstance(value, Iterable) and not isinstance(value, str | bytes):
                    items = [item for item in value if _has_value(item)]
                    if items:
                        counts[family] = max(counts.get(family, 0), len(items))
    for section in _section_candidates(context):
        for family, keys in _CANDIDATE_LIST_KEYS.items():
            for key in keys:
                value = section.get(key)
                if isinstance(value, dict):
                    size = len(value)
                elif isinstance(value, Iterable) and not isinstance(value, str | bytes):
                    size = len([item for item in value if _has_value(item)])
                else:
                    continue
                if size > 0:
                    counts[family] = max(counts.get(family, 0), size)
    return counts


def _has_accounting(context: Mapping[str, object]) -> bool:
    for section in _section_candidates(context):
        for key in _ACCOUNTING_KEYS:
            value = section.get(key)
            if isinstance(value, bool):
                if value:
                    return True
                continue
            if isinstance(value, str):
                normalized = _normalize_text(value)
                if normalized and normalized not in {
                    "false",
                    "no",
                    "0",
                    "none",
                    "null",
                    "missing",
                }:
                    return True
                continue
            if isinstance(value, Mapping):
                if any(_has_value(nested) for nested in value.values()):
                    return True
                continue
            if _has_value(value):
                return True
    return False


def _has_validation_guardrail(context: Mapping[str, object]) -> bool:
    for section in _section_candidates(context):
        for key in _VALIDATION_GUARDRAIL_KEYS:
            value = section.get(key)
            if isinstance(value, bool):
                if value:
                    return True
                continue
            if isinstance(value, str):
                normalized = _normalize_text(value)
                if normalized and normalized not in {
                    "false",
                    "no",
                    "0",
                    "none",
                    "null",
                    "missing",
                }:
                    return True
                continue
            if _has_value(value):
                return True
    return False


def _bundle_run_dir(bundle: CodeReviewBundle) -> Path | None:
    for artifact_key in ("analysis_bundle", "observation", "review_contract"):
        artifact = _artifact_dict(bundle, artifact_key)
        raw = artifact.get("run_dir")
        if isinstance(raw, str) and raw.strip():
            return Path(raw).expanduser()
    raw = getattr(bundle, "run_id", None)
    if isinstance(raw, str) and raw.strip():
        return None
    return None


def _manifest_path_for_keys(
    context: Mapping[str, object],
    bundle: CodeReviewBundle,
    keys: tuple[str, ...],
) -> Path | None:
    for section in _section_candidates(context):
        for key in keys:
            raw = section.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            candidate = Path(raw).expanduser()
            if candidate.is_absolute() and candidate.exists():
                return candidate
            run_dir = _bundle_run_dir(bundle)
            if run_dir is not None:
                resolved = run_dir / candidate
                if resolved.exists():
                    return resolved
    return None


def _manifest_path(
    context: Mapping[str, object], bundle: CodeReviewBundle
) -> Path | None:
    return _manifest_path_for_keys(context, bundle, _MANIFEST_PATH_KEYS)


def _load_manifest_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("rows", "records", "items", "splits", "folds", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            return [dict(row) for row in reader]

    return []


def _load_subject_id_values(path: Path) -> set[str]:
    if path.suffix.lower() in {".json", ".jsonl", ".csv", ".tsv"}:
        try:
            rows = _load_manifest_rows(path)
        except Exception:
            return set()
        return _subject_id_set(rows)

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return set()

    values: set[str] = set()
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.lower() in {"subject", "subject_id", "participant_id"}:
            continue
        values.add(text)
    return values


def _structured_manifest_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() not in {".json", ".jsonl", ".csv", ".tsv"}:
        return []
    try:
        return _load_manifest_rows(path)
    except Exception:
        return []


def _structured_subject_column_gap(path: Path) -> tuple[Path, list[str]] | None:
    rows = _structured_manifest_rows(path)
    if not rows:
        return None
    manifest_keys = _manifest_column_keys(rows)
    if any(key in manifest_keys for key in _SUBJECT_ID_KEYS):
        return None
    return path, sorted(manifest_keys)


def _subject_subset_conflict(
    *,
    superset_path: Path,
    subset_path: Path,
) -> tuple[list[str], int, int] | None:
    superset_ids = _load_subject_id_values(superset_path)
    subset_ids = _load_subject_id_values(subset_path)
    if not superset_ids or not subset_ids:
        return None

    missing_subject_ids = sorted(subset_ids - superset_ids)
    if not missing_subject_ids:
        return None
    return missing_subject_ids, len(superset_ids), len(subset_ids)


def _partition_conflict(
    rows: list[dict[str, Any]],
    *,
    group_keys: set[str],
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...], list[str]] | None:
    if not group_keys:
        return None

    normalized_group_keys = sorted({_normalize_text(key) for key in group_keys if key})
    assignments: dict[
        tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]],
        set[str],
    ] = {}

    for row in rows:
        normalized_row = {
            _normalize_text(key): value
            for key, value in row.items()
            if str(key).strip()
        }
        if not all(
            key in normalized_row and str(normalized_row[key]).strip()
            for key in normalized_group_keys
        ):
            continue

        partition = None
        for key in _MANIFEST_PARTITION_KEYS:
            normalized_key = _normalize_text(key)
            value = normalized_row.get(normalized_key)
            if value is not None and str(value).strip():
                partition = _normalize_text(value)
                break
        if not partition:
            continue

        fold_scope_items: list[tuple[str, str]] = []
        for key in _MANIFEST_FOLD_KEYS:
            normalized_key = _normalize_text(key)
            value = normalized_row.get(normalized_key)
            if value is not None and str(value).strip():
                fold_scope_items.append((normalized_key, str(value).strip()))
        if not fold_scope_items:
            fold_scope_items.append(("manifest_scope", "__all__"))

        group_tuple = tuple(
            (key, str(normalized_row[key]).strip()) for key in normalized_group_keys
        )
        fold_scope = tuple(fold_scope_items)
        assignments.setdefault((fold_scope, group_tuple), set()).add(partition)

    for (fold_scope, group_tuple), partitions in assignments.items():
        if len(partitions) > 1:
            return fold_scope, group_tuple, sorted(partitions)
    return None


def _manifest_column_keys(rows: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        for key in row:
            text = str(key).strip()
            if text:
                keys.add(_normalize_text(text))
    return keys


def _subject_id_set(rows: list[dict[str, Any]]) -> set[str]:
    manifest_keys = _manifest_column_keys(rows)
    subject_key = next((key for key in _SUBJECT_ID_KEYS if key in manifest_keys), None)
    if subject_key is None:
        return set()

    subject_ids: set[str] = set()
    for row in rows:
        for key, value in row.items():
            if _normalize_text(key) != subject_key:
                continue
            text = str(value).strip()
            if text:
                subject_ids.add(text)
    return subject_ids


def _normalized_partition(value: object) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    if "test" in normalized:
        return "test"
    if "val" in normalized:
        return "validation"
    if "train" in normalized:
        return "train"
    return normalized


def _first_normalized_row_value(
    normalized_row: Mapping[str, object],
    keys: Iterable[str],
) -> str | None:
    for key in keys:
        normalized_key = _normalize_text(key)
        value = normalized_row.get(normalized_key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _nested_outer_holdout_conflict(
    rows: list[dict[str, Any]],
    *,
    group_keys: set[str],
) -> tuple[str, tuple[tuple[str, str], ...], list[str]] | None:
    if not group_keys:
        return None

    normalized_group_keys = sorted({_normalize_text(key) for key in group_keys if key})
    assignments: dict[tuple[str, tuple[tuple[str, str], ...]], set[str]] = {}

    for row in rows:
        normalized_row = {
            _normalize_text(key): value
            for key, value in row.items()
            if str(key).strip()
        }
        if not all(
            key in normalized_row and str(normalized_row[key]).strip()
            for key in normalized_group_keys
        ):
            continue

        outer_fold = None
        for key in _OUTER_FOLD_KEYS:
            normalized_key = _normalize_text(key)
            value = normalized_row.get(normalized_key)
            if value is not None and str(value).strip():
                outer_fold = str(value).strip()
                break
        if not outer_fold:
            continue

        partition = None
        for key in _MANIFEST_PARTITION_KEYS:
            normalized_key = _normalize_text(key)
            value = normalized_row.get(normalized_key)
            if value is not None and str(value).strip():
                partition = _normalized_partition(value)
                break
        if not partition:
            continue

        group_tuple = tuple(
            (key, str(normalized_row[key]).strip()) for key in normalized_group_keys
        )
        assignments.setdefault((outer_fold, group_tuple), set()).add(partition)

    for (outer_fold, group_tuple), partitions in assignments.items():
        if "test" in partitions and {"train", "validation"} & partitions:
            return outer_fold, group_tuple, sorted(partitions)
    return None


def _nested_outer_partition_gap(
    rows: list[dict[str, Any]],
) -> tuple[str, list[str]] | None:
    assignments: dict[str, set[str]] = {}

    for row in rows:
        normalized_row = {
            _normalize_text(key): value
            for key, value in row.items()
            if str(key).strip()
        }
        outer_fold = _first_normalized_row_value(normalized_row, _OUTER_FOLD_KEYS)
        if not outer_fold:
            continue

        partition = _first_normalized_row_value(
            normalized_row, _MANIFEST_PARTITION_KEYS
        )
        normalized_partition = _normalized_partition(partition)
        if not normalized_partition:
            continue
        assignments.setdefault(outer_fold, set()).add(normalized_partition)

    for outer_fold, partitions in assignments.items():
        if "test" not in partitions or not ({"train", "validation"} & partitions):
            return outer_fold, sorted(partitions)
    return None


def _nested_inner_partition_gap(
    rows: list[dict[str, Any]],
) -> tuple[str, str, list[str]] | None:
    assignments: dict[tuple[str, str], set[str]] = {}

    for row in rows:
        normalized_row = {
            _normalize_text(key): value
            for key, value in row.items()
            if str(key).strip()
        }
        outer_fold = _first_normalized_row_value(normalized_row, _OUTER_FOLD_KEYS)
        inner_fold = _first_normalized_row_value(normalized_row, _INNER_FOLD_KEYS)
        if not outer_fold or not inner_fold:
            continue

        partition = _first_normalized_row_value(
            normalized_row, _MANIFEST_PARTITION_KEYS
        )
        normalized_partition = _normalized_partition(partition)
        if normalized_partition not in {"train", "validation", "test"}:
            continue
        assignments.setdefault((outer_fold, inner_fold), set()).add(
            normalized_partition
        )

    for (outer_fold, inner_fold), partitions in assignments.items():
        has_train = "train" in partitions
        has_eval = bool({"validation", "test"} & partitions)
        if not (has_train and has_eval):
            return outer_fold, inner_fold, sorted(partitions)
    return None


def _nested_outer_missing_inner_resampling(
    rows: list[dict[str, Any]],
) -> tuple[str, list[str]] | None:
    training_side_partitions: dict[str, set[str]] = {}
    inner_fold_assignments: dict[str, set[str]] = {}

    for row in rows:
        normalized_row = {
            _normalize_text(key): value
            for key, value in row.items()
            if str(key).strip()
        }
        outer_fold = _first_normalized_row_value(normalized_row, _OUTER_FOLD_KEYS)
        if not outer_fold:
            continue

        partition = _first_normalized_row_value(
            normalized_row, _MANIFEST_PARTITION_KEYS
        )
        normalized_partition = _normalized_partition(partition)
        if normalized_partition not in {"train", "validation"}:
            continue

        training_side_partitions.setdefault(outer_fold, set()).add(normalized_partition)
        inner_fold = _first_normalized_row_value(normalized_row, _INNER_FOLD_KEYS)
        if inner_fold:
            inner_fold_assignments.setdefault(outer_fold, set()).add(inner_fold)

    for outer_fold, partitions in training_side_partitions.items():
        if partitions and not inner_fold_assignments.get(outer_fold):
            return outer_fold, sorted(partitions)
    return None


def _nested_cv_manifest_schema_gaps(rows: list[dict[str, Any]]) -> list[str]:
    manifest_keys = _manifest_column_keys(rows)
    gaps: list[str] = []
    if not any(_normalize_text(key) in manifest_keys for key in _OUTER_FOLD_KEYS):
        gaps.append("outer_fold")
    if not any(_normalize_text(key) in manifest_keys for key in _INNER_FOLD_KEYS):
        gaps.append("inner_fold")
    if not any(
        _normalize_text(key) in manifest_keys for key in _MANIFEST_PARTITION_KEYS
    ):
        gaps.append("partition")
    return gaps


def neuroai_selection_on_test_check(bundle: CodeReviewBundle) -> ReviewFinding | None:
    """Block explicit selection-on-test provenance for neuroAI candidate picks."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    selection_flags = _collect_selection_flags(context)
    winner_fields = _collect_winner_fields(context)
    if not selection_flags and not winner_fields:
        return None

    explicit_test_selection = bool(selection_flags)
    if not explicit_test_selection:
        return None

    evidence = [f"review_context.selection_flags={selection_flags}"]
    if winner_fields:
        evidence.append(f"winner_fields={winner_fields[:8]}")

    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SELECTION_ON_TEST",
        severity="error",
        action="block",
        message=(
            "Explicit neuroAI selection metadata indicates the winning "
            "layer / ROI / model / prompt was chosen after inspecting held-out "
            "or test results."
        ),
        suggested_fix=(
            "Move winner selection to a validation fold or nested CV and reserve "
            "the held-out / test set for one final evaluation only."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_split_grouping_mismatch_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block explicit fine-grained splits that violate required grouping keys."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    required_group_keys = _required_group_keys(context)
    if not required_group_keys:
        return None

    grouped_split_keys = _grouped_split_keys(context)
    missing_group_keys = sorted(required_group_keys - grouped_split_keys)
    if not missing_group_keys:
        return None

    split_unit = _split_unit(context)
    split_strategy = _split_strategy(context)
    grouping_required = _explicit_bool(context.get("grouping_required"))
    if grouping_required is False:
        return None

    if not (
        split_unit in _FINE_GRAINED_SPLIT_UNITS
        or any(token in split_strategy for token in _RANDOM_SPLIT_TOKENS)
        or split_strategy.endswith("_split")
    ):
        return None

    evidence = [
        f"required_group_keys={sorted(required_group_keys)}",
        f"grouped_split_keys={sorted(grouped_split_keys)}",
    ]
    if split_unit:
        evidence.append(f"split_unit={split_unit}")
    if split_strategy:
        evidence.append(f"split_strategy={split_strategy}")

    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SPLIT_GROUPING_MISMATCH",
        severity="error",
        action="block",
        message=(
            "Explicit split metadata uses a fine-grained or random split, but the "
            "required grouping keys for the neuroAI / naturalistic setting are not "
            "all carried together."
        ),
        suggested_fix=(
            "Regenerate the split so the required grouping keys remain on the same "
            "side of train / validation / test, or switch to a grouping-aware split "
            "at the declared unit."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_selection_multiplicity_accounting_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn when a reported winner lacks multiplicity / selection accounting."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    counts = _candidate_family_counts(context)
    if not counts:
        return None

    winner_fields = _collect_winner_fields(context)
    if not winner_fields:
        return None

    max_count = max(counts.values())
    if max_count < 3:
        return None

    if _has_accounting(context):
        return None

    evidence = [f"candidate_counts={dict(sorted(counts.items()))}"]
    evidence.append(f"winner_fields={winner_fields[:8]}")

    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SELECTION_MULTIPLICITY_ACCOUNTING",
        severity="warn",
        action="warn",
        message=(
            "A winner is reported after comparing multiple neuroAI candidates, but "
            "no multiplicity or selection accounting is recorded."
        ),
        suggested_fix=(
            "Report the candidate search space, the selection criterion, and the "
            "multiplicity correction / nested validation used to choose the winner."
        ),
        kg_evidence=evidence,
        reason_tags=["generalization"],
    )


def neuroai_winner_without_candidate_set_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn when a winner is declared but the compared candidate set is absent."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    winner_fields = _collect_winner_fields(context)
    if not winner_fields:
        return None

    counts = _candidate_family_counts(context)
    if counts:
        return None

    evidence = [f"winner_fields={winner_fields[:8]}"]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_WINNER_WITHOUT_CANDIDATE_SET",
        severity="warn",
        action="warn",
        message=(
            "A neuroAI winner is declared, but the candidate set that produced the "
            "winner is not recorded."
        ),
        suggested_fix=(
            "Record the compared models / layers / ROIs / prompts or replace "
            "winner language with a single-candidate description."
        ),
        kg_evidence=evidence,
        reason_tags=["generalization"],
    )


def neuroai_selection_validation_gap_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Warn when winner selection lacks explicit nested/held-out validation metadata."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    winner_fields = _collect_winner_fields(context)
    if not winner_fields:
        return None

    counts = _candidate_family_counts(context)
    max_count = max(counts.values(), default=0)
    if max_count < 2:
        return None

    if _has_validation_guardrail(context):
        return None

    evidence = [f"candidate_counts={dict(sorted(counts.items()))}"]
    evidence.append(f"winner_fields={winner_fields[:8]}")

    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SELECTION_VALIDATION_GAP",
        severity="warn",
        action="warn",
        message=(
            "A neuroAI winner is reported after multi-candidate comparison, but "
            "the bundle does not record nested CV, a dedicated selection holdout, "
            "or independent validation."
        ),
        suggested_fix=(
            "Record the validation stage used for winner selection, such as nested "
            "CV, a separate model-selection split, or an independent validation set."
        ),
        kg_evidence=evidence,
        reason_tags=["generalization"],
    )


def neuroai_split_manifest_partition_conflict_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block explicit manifest rows that place the same group tuple in multiple partitions."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    manifest_path = _manifest_path(context, bundle)
    if manifest_path is None:
        return None

    try:
        rows = _load_manifest_rows(manifest_path)
    except Exception:
        return None
    if not rows:
        return None

    group_keys = _required_group_keys(context) or _grouped_split_keys(context)
    conflict = _partition_conflict(rows, group_keys=group_keys)
    if conflict is None:
        return None

    fold_scope, group_tuple, partitions = conflict
    evidence = [
        f"manifest_path={manifest_path}",
        f"conflict_group={dict(group_tuple)}",
        f"conflict_partitions={partitions}",
        f"fold_scope={dict(fold_scope)}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SPLIT_MANIFEST_PARTITION_CONFLICT",
        severity="error",
        action="block",
        message=(
            "The split/fold manifest assigns the same required grouping tuple to "
            "multiple partitions within the same fold scope."
        ),
        suggested_fix=(
            "Regenerate the manifest so each required group tuple stays on one side "
            "of train/validation/test within a fold."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_split_manifest_missing_group_keys_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block manifest-backed neuroAI splits that omit declared required grouping columns."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    required_group_keys = _required_group_keys(context)
    if not required_group_keys:
        return None

    manifest_path = _manifest_path(context, bundle)
    if manifest_path is None:
        return None

    try:
        rows = _load_manifest_rows(manifest_path)
    except Exception:
        return None
    if not rows:
        return None

    manifest_keys = _manifest_column_keys(rows)
    missing_keys = sorted(
        _normalize_text(key)
        for key in required_group_keys
        if _normalize_text(key) not in manifest_keys
    )
    if not missing_keys:
        return None

    evidence = [
        f"manifest_path={manifest_path}",
        f"required_group_keys={sorted(_normalize_text(key) for key in required_group_keys)}",
        f"manifest_keys={sorted(manifest_keys)}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SPLIT_MANIFEST_MISSING_GROUP_KEYS",
        severity="error",
        action="block",
        message=(
            "The split/fold manifest is missing one or more declared required grouping "
            "columns, so grouping-aware generalization cannot be validated."
        ),
        suggested_fix=(
            "Regenerate the manifest with the declared required grouping columns, or "
            "downgrade the grouping claim to match the available manifest schema."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_subject_manifest_coverage_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block split manifests that reference subjects absent from the subject manifest."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    split_manifest_path = _manifest_path(context, bundle)
    subject_manifest_path = _manifest_path_for_keys(
        context, bundle, _SUBJECT_MANIFEST_PATH_KEYS
    )
    if split_manifest_path is None or subject_manifest_path is None:
        return None

    try:
        split_rows = _load_manifest_rows(split_manifest_path)
        subject_rows = _load_manifest_rows(subject_manifest_path)
    except Exception:
        return None
    if not split_rows or not subject_rows:
        return None

    split_subject_ids = _subject_id_set(split_rows)
    subject_manifest_ids = _subject_id_set(subject_rows)
    if not split_subject_ids or not subject_manifest_ids:
        return None

    missing_subject_ids = sorted(split_subject_ids - subject_manifest_ids)
    if not missing_subject_ids:
        return None

    evidence = [
        f"split_manifest_path={split_manifest_path}",
        f"subject_manifest_path={subject_manifest_path}",
        f"missing_subject_ids={missing_subject_ids[:20]}",
        f"split_subject_count={len(split_subject_ids)}",
        f"subject_manifest_count={len(subject_manifest_ids)}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SUBJECT_MANIFEST_COVERAGE",
        severity="error",
        action="block",
        message=(
            "The split/fold manifest references subject IDs that are missing from "
            "the declared subject manifest."
        ),
        suggested_fix=(
            "Regenerate the subject and split manifests from the same subject set, "
            "or update the declared subject manifest to cover the evaluated split."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_declared_subject_set_missing_subject_column_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block declared structured subject-set manifests that omit a usable subject column."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    manifest_specs = [
        ("subject_manifest_path", _SUBJECT_MANIFEST_PATH_KEYS),
        ("subject_intersection_manifest_path", _SUBJECT_INTERSECTION_PATH_KEYS),
        ("subject_selection_source", _SUBJECT_SELECTION_SOURCE_KEYS),
    ]
    for label, keys in manifest_specs:
        manifest_path = _manifest_path_for_keys(context, bundle, keys)
        if manifest_path is None:
            continue
        gap = _structured_subject_column_gap(manifest_path)
        if gap is None:
            continue

        path, manifest_keys = gap
        evidence = [
            f"{label}={path}",
            f"manifest_keys={manifest_keys}",
            f"expected_subject_keys={list(_SUBJECT_ID_KEYS)}",
        ]
        return ReviewFinding(
            rule_id="REVIEW_NEUROAI_DECLARED_SUBJECT_SET_MISSING_SUBJECT_COLUMN",
            severity="error",
            action="block",
            message=(
                "A declared structured subject-set manifest is missing a usable "
                "subject identifier column."
            ),
            suggested_fix=(
                "Regenerate the declared subject-set manifest with one of "
                "`subject`, `subject_id`, or `participant_id`, or switch to a plain "
                "one-subject-per-line source file."
            ),
            kg_evidence=evidence,
            reason_tags=["leakage", "generalization"],
        )
    return None


def neuroai_subject_intersection_coverage_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block split manifests that reference subjects absent from the subject-intersection manifest."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    split_manifest_path = _manifest_path(context, bundle)
    intersection_manifest_path = _manifest_path_for_keys(
        context, bundle, _SUBJECT_INTERSECTION_PATH_KEYS
    )
    if split_manifest_path is None or intersection_manifest_path is None:
        return None

    try:
        split_rows = _load_manifest_rows(split_manifest_path)
        intersection_rows = _load_manifest_rows(intersection_manifest_path)
    except Exception:
        return None
    if not split_rows or not intersection_rows:
        return None

    split_subject_ids = _subject_id_set(split_rows)
    intersection_subject_ids = _subject_id_set(intersection_rows)
    if not split_subject_ids or not intersection_subject_ids:
        return None

    missing_subject_ids = sorted(split_subject_ids - intersection_subject_ids)
    if not missing_subject_ids:
        return None

    evidence = [
        f"split_manifest_path={split_manifest_path}",
        f"subject_intersection_manifest_path={intersection_manifest_path}",
        f"missing_subject_ids={missing_subject_ids[:20]}",
        f"split_subject_count={len(split_subject_ids)}",
        f"subject_intersection_count={len(intersection_subject_ids)}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SUBJECT_INTERSECTION_COVERAGE",
        severity="error",
        action="block",
        message=(
            "The split/fold manifest references subject IDs that are missing from "
            "the declared subject-intersection manifest."
        ),
        suggested_fix=(
            "Regenerate the split and intersection manifests from the same eligible "
            "subject set, or update the declared subject-intersection manifest."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_nested_cv_outer_holdout_conflict_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block nested-CV manifests whose outer-holdout subjects reappear in inner train/validation rows."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    selection = _nested_mapping(context, "selection")
    nested_declared = _explicit_bool(selection.get("nested_cv"))
    if nested_declared is not True:
        return None

    manifest_path = _manifest_path(context, bundle)
    if manifest_path is None:
        return None

    try:
        rows = _load_manifest_rows(manifest_path)
    except Exception:
        return None
    if not rows:
        return None

    group_keys = _required_group_keys(context) or _grouped_split_keys(context)
    conflict = _nested_outer_holdout_conflict(rows, group_keys=group_keys)
    if conflict is None:
        return None

    outer_fold, group_tuple, partitions = conflict
    evidence = [
        f"manifest_path={manifest_path}",
        f"outer_fold={outer_fold}",
        f"conflict_group={dict(group_tuple)}",
        f"conflict_partitions={partitions}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_NESTED_CV_OUTER_HOLDOUT_CONFLICT",
        severity="error",
        action="block",
        message=(
            "A nested-CV manifest assigns the same required grouping tuple to outer "
            "test and inner train/validation partitions within the same outer fold."
        ),
        suggested_fix=(
            "Regenerate the nested-CV manifest so outer-holdout subjects never "
            "re-enter inner train/validation partitions for the same outer fold."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_nested_cv_schema_missing_fold_keys_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block nested-CV claims whose manifest schema cannot encode outer/inner fold structure."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    selection = _nested_mapping(context, "selection")
    nested_declared = _explicit_bool(selection.get("nested_cv"))
    if nested_declared is not True:
        return None

    manifest_path = _manifest_path(context, bundle)
    if manifest_path is None:
        return None

    try:
        rows = _load_manifest_rows(manifest_path)
    except Exception:
        return None
    if not rows:
        return None

    gaps = _nested_cv_manifest_schema_gaps(rows)
    if not gaps:
        return None

    evidence = [
        f"manifest_path={manifest_path}",
        f"missing_nested_cv_keys={gaps}",
        f"manifest_keys={sorted(_manifest_column_keys(rows))}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_NESTED_CV_SCHEMA_MISSING_FOLD_KEYS",
        severity="error",
        action="block",
        message=(
            "A bundle declares nested CV, but the split/fold manifest schema is "
            "missing the fold keys needed to encode outer and inner resampling "
            "structure."
        ),
        suggested_fix=(
            "Emit a nested-CV manifest with explicit outer-fold, inner-fold, and "
            "partition columns before claiming nested resampling."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_nested_cv_outer_partition_gap_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block nested-CV manifests whose outer folds are missing held-out or training-side partitions."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    selection = _nested_mapping(context, "selection")
    nested_declared = _explicit_bool(selection.get("nested_cv"))
    if nested_declared is not True:
        return None

    manifest_path = _manifest_path(context, bundle)
    if manifest_path is None:
        return None

    try:
        rows = _load_manifest_rows(manifest_path)
    except Exception:
        return None
    if not rows:
        return None

    if _nested_cv_manifest_schema_gaps(rows):
        return None

    conflict = _nested_outer_partition_gap(rows)
    if conflict is None:
        return None

    outer_fold, partitions = conflict
    evidence = [
        f"manifest_path={manifest_path}",
        f"outer_fold={outer_fold}",
        f"observed_partitions={partitions}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_NESTED_CV_OUTER_PARTITION_GAP",
        severity="error",
        action="block",
        message=(
            "A nested-CV outer fold is missing either a held-out test partition or "
            "the training-side partitions needed for model selection."
        ),
        suggested_fix=(
            "Regenerate the nested-CV manifest so every outer fold records both a "
            "test holdout and the training-side partitions used for inner selection."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_nested_cv_inner_partition_gap_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block nested-CV manifests whose inner folds lack train/evaluation partition pairs."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    selection = _nested_mapping(context, "selection")
    nested_declared = _explicit_bool(selection.get("nested_cv"))
    if nested_declared is not True:
        return None

    manifest_path = _manifest_path(context, bundle)
    if manifest_path is None:
        return None

    try:
        rows = _load_manifest_rows(manifest_path)
    except Exception:
        return None
    if not rows:
        return None

    if _nested_cv_manifest_schema_gaps(rows):
        return None

    conflict = _nested_inner_partition_gap(rows)
    if conflict is None:
        return None

    outer_fold, inner_fold, partitions = conflict
    evidence = [
        f"manifest_path={manifest_path}",
        f"outer_fold={outer_fold}",
        f"inner_fold={inner_fold}",
        f"observed_partitions={partitions}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_NESTED_CV_INNER_PARTITION_GAP",
        severity="error",
        action="block",
        message=(
            "A nested-CV inner fold is missing either the training partition or the "
            "evaluation partition needed for inner-loop selection."
        ),
        suggested_fix=(
            "Regenerate the nested-CV manifest so every inner fold records both "
            "training and validation/evaluation assignments."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_nested_cv_outer_missing_inner_resampling_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block nested-CV manifests whose outer folds never record inner-fold assignments on training-side rows."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    selection = _nested_mapping(context, "selection")
    nested_declared = _explicit_bool(selection.get("nested_cv"))
    if nested_declared is not True:
        return None

    manifest_path = _manifest_path(context, bundle)
    if manifest_path is None:
        return None

    try:
        rows = _load_manifest_rows(manifest_path)
    except Exception:
        return None
    if not rows:
        return None

    if _nested_cv_manifest_schema_gaps(rows):
        return None

    conflict = _nested_outer_missing_inner_resampling(rows)
    if conflict is None:
        return None

    outer_fold, training_side_partitions = conflict
    evidence = [
        f"manifest_path={manifest_path}",
        f"outer_fold={outer_fold}",
        f"training_side_partitions={training_side_partitions}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_NESTED_CV_OUTER_MISSING_INNER_RESAMPLING",
        severity="error",
        action="block",
        message=(
            "A nested-CV outer fold contains training-side rows, but none of those "
            "rows record an inner-fold assignment for model-selection resampling."
        ),
        suggested_fix=(
            "Regenerate the nested-CV manifest so each outer fold explicitly records "
            "inner-fold assignments on the training-side rows used for model selection."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_subject_intersection_subset_conflict_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block when the declared subject-intersection manifest is not a subset of the subject manifest."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    subject_manifest_path = _manifest_path_for_keys(
        context, bundle, _SUBJECT_MANIFEST_PATH_KEYS
    )
    intersection_manifest_path = _manifest_path_for_keys(
        context, bundle, _SUBJECT_INTERSECTION_PATH_KEYS
    )
    if subject_manifest_path is None or intersection_manifest_path is None:
        return None

    subject_manifest_ids = _load_subject_id_values(subject_manifest_path)
    intersection_subject_ids = _load_subject_id_values(intersection_manifest_path)
    if not subject_manifest_ids or not intersection_subject_ids:
        return None

    missing_subject_ids = sorted(intersection_subject_ids - subject_manifest_ids)
    if not missing_subject_ids:
        return None

    evidence = [
        f"subject_manifest_path={subject_manifest_path}",
        f"subject_intersection_manifest_path={intersection_manifest_path}",
        f"missing_subject_ids={missing_subject_ids[:20]}",
        f"subject_manifest_count={len(subject_manifest_ids)}",
        f"subject_intersection_count={len(intersection_subject_ids)}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SUBJECT_INTERSECTION_SUBSET_CONFLICT",
        severity="error",
        action="block",
        message=(
            "The declared subject-intersection manifest contains subject IDs that "
            "are not present in the declared subject manifest."
        ),
        suggested_fix=(
            "Regenerate the subject-intersection manifest from the declared subject "
            "manifest, or update the subject manifest to match the eligible set."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_subject_selection_source_coverage_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block when split/fold manifests reference subject IDs missing from the subject-selection source."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    split_manifest_path = _manifest_path(context, bundle)
    selection_source_path = _manifest_path_for_keys(
        context, bundle, _SUBJECT_SELECTION_SOURCE_KEYS
    )
    if split_manifest_path is None or selection_source_path is None:
        return None

    try:
        split_rows = _load_manifest_rows(split_manifest_path)
    except Exception:
        return None
    if not split_rows:
        return None

    split_subject_ids = _subject_id_set(split_rows)
    selection_source_ids = _load_subject_id_values(selection_source_path)
    if not split_subject_ids or not selection_source_ids:
        return None

    missing_subject_ids = sorted(split_subject_ids - selection_source_ids)
    if not missing_subject_ids:
        return None

    evidence = [
        f"split_manifest_path={split_manifest_path}",
        f"subject_selection_source={selection_source_path}",
        f"missing_subject_ids={missing_subject_ids[:20]}",
        f"split_subject_count={len(split_subject_ids)}",
        f"subject_selection_count={len(selection_source_ids)}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SUBJECT_SELECTION_SOURCE_COVERAGE",
        severity="error",
        action="block",
        message=(
            "The split/fold manifest references subject IDs that are missing from "
            "the declared subject-selection source."
        ),
        suggested_fix=(
            "Regenerate the split manifest from the declared subject-selection "
            "source, or update the selection source file to match the evaluated split."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_subject_manifest_selection_source_subset_conflict_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block subject manifests that contain IDs absent from the declared subject-selection source."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    subject_manifest_path = _manifest_path_for_keys(
        context, bundle, _SUBJECT_MANIFEST_PATH_KEYS
    )
    selection_source_path = _manifest_path_for_keys(
        context, bundle, _SUBJECT_SELECTION_SOURCE_KEYS
    )
    if subject_manifest_path is None or selection_source_path is None:
        return None

    conflict = _subject_subset_conflict(
        superset_path=selection_source_path,
        subset_path=subject_manifest_path,
    )
    if conflict is None:
        return None

    missing_subject_ids, selection_source_count, subject_manifest_count = conflict
    evidence = [
        f"subject_selection_source={selection_source_path}",
        f"subject_manifest_path={subject_manifest_path}",
        f"missing_subject_ids={missing_subject_ids[:20]}",
        f"subject_selection_count={selection_source_count}",
        f"subject_manifest_count={subject_manifest_count}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SUBJECT_MANIFEST_SELECTION_SOURCE_CONFLICT",
        severity="error",
        action="block",
        message=(
            "The declared subject manifest contains subject IDs that are not present "
            "in the declared subject-selection source."
        ),
        suggested_fix=(
            "Regenerate the subject manifest from the declared subject-selection "
            "source, or update the source file to match the reviewed subject set."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


def neuroai_subject_intersection_selection_source_subset_conflict_check(
    bundle: CodeReviewBundle,
) -> ReviewFinding | None:
    """Block subject-intersection manifests that contain IDs absent from the selection source."""

    context = _review_context(bundle)
    if not _is_neuroai_context(bundle, context):
        return None

    intersection_manifest_path = _manifest_path_for_keys(
        context, bundle, _SUBJECT_INTERSECTION_PATH_KEYS
    )
    selection_source_path = _manifest_path_for_keys(
        context, bundle, _SUBJECT_SELECTION_SOURCE_KEYS
    )
    if intersection_manifest_path is None or selection_source_path is None:
        return None

    conflict = _subject_subset_conflict(
        superset_path=selection_source_path,
        subset_path=intersection_manifest_path,
    )
    if conflict is None:
        return None

    missing_subject_ids, selection_source_count, intersection_count = conflict
    evidence = [
        f"subject_selection_source={selection_source_path}",
        f"subject_intersection_manifest_path={intersection_manifest_path}",
        f"missing_subject_ids={missing_subject_ids[:20]}",
        f"subject_selection_count={selection_source_count}",
        f"subject_intersection_count={intersection_count}",
    ]
    return ReviewFinding(
        rule_id="REVIEW_NEUROAI_SUBJECT_INTERSECTION_SELECTION_SOURCE_CONFLICT",
        severity="error",
        action="block",
        message=(
            "The declared subject-intersection manifest contains subject IDs that "
            "are not present in the declared subject-selection source."
        ),
        suggested_fix=(
            "Regenerate the subject-intersection manifest from the declared "
            "subject-selection source, or update the source file to match the "
            "eligible reviewed set."
        ),
        kg_evidence=evidence,
        reason_tags=["leakage", "generalization"],
    )


__all__ = [
    "neuroai_declared_subject_set_missing_subject_column_check",
    "neuroai_nested_cv_inner_partition_gap_check",
    "neuroai_nested_cv_outer_missing_inner_resampling_check",
    "neuroai_nested_cv_outer_partition_gap_check",
    "neuroai_nested_cv_outer_holdout_conflict_check",
    "neuroai_nested_cv_schema_missing_fold_keys_check",
    "neuroai_selection_multiplicity_accounting_check",
    "neuroai_selection_on_test_check",
    "neuroai_selection_validation_gap_check",
    "neuroai_subject_manifest_coverage_check",
    "neuroai_subject_manifest_selection_source_subset_conflict_check",
    "neuroai_subject_intersection_coverage_check",
    "neuroai_subject_intersection_selection_source_subset_conflict_check",
    "neuroai_subject_intersection_subset_conflict_check",
    "neuroai_subject_selection_source_coverage_check",
    "neuroai_split_manifest_missing_group_keys_check",
    "neuroai_split_manifest_partition_conflict_check",
    "neuroai_split_grouping_mismatch_check",
    "neuroai_winner_without_candidate_set_check",
]
