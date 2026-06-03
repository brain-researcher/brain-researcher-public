"""Psych-101 ingest skeleton for BR-KG.

This loader keeps the first integration pass intentionally lightweight:
it normalizes dataset metadata, normalizes experiment rows, infers task
families and task labels with simple hooks, and emits graph-ready records.
Optional writes can be sent through a Neo4j-like DB object that exposes
``create_node`` and ``create_relationship``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from brain_researcher.services.br_kg.task_family_matcher import (
    TaskFamilyMatcher,
)
from brain_researcher.services.br_kg.utils.task_taxonomy import TaskTaxonomyResolver

_TASK_FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "decision-making",
        (
            "decision",
            "choice",
            "choose",
            "bandit",
            "lottery",
            "risk",
            "preference",
            "gamble",
            "reward",
        ),
    ),
    (
        "learning",
        (
            "learning",
            "reinforcement",
            "feedback",
            "supervised",
            "trial and error",
            "trial-and-error",
            "policy",
            "mdp",
        ),
    ),
    (
        "memory",
        (
            "memory",
            "recall",
            "recognition",
            "retrieval",
            "encoding",
            "working memory",
            "n-back",
        ),
    ),
    (
        "attention",
        (
            "attention",
            "search",
            "flanker",
            "stroop",
            "target",
            "visual search",
        ),
    ),
    (
        "social cognition",
        (
            "social",
            "trust",
            "ultimatum",
            "other",
            "partner",
            "game",
        ),
    ),
)

_EXPERIMENT_LABEL_KEYS = (
    "experiment_label",
    "experiment_name",
    "name",
    "title",
    "paradigm",
    "task",
    "task_name",
    "task_label",
)
_EXPERIMENT_CONTEXT_KEYS = (
    "experiment_label",
    "experiment_name",
    "name",
    "title",
    "paradigm",
    "task",
    "task_name",
    "task_label",
    "description",
    "prompt",
    "task_description",
    "notes",
)
_EXPERIMENT_PATH_KEYS = (
    "experiment_path",
    "source_path",
    "file_path",
    "path",
    "filename",
    "source_file",
    "source_files",
    "files",
)
_ONTOLOGY_PATH_KEYS = (
    "experiment_path",
    "source_path",
    "file_path",
    "path",
    "filename",
)
_LOW_SIGNAL_PATH_TOKENS = {
    "convert",
    "csv",
    "data",
    "dataset",
    "datasets",
    "default",
    "file",
    "files",
    "huggingface",
    "json",
    "jsonl",
    "parquet",
    "refs",
    "resolve",
    "split",
    "splits",
    "test",
    "train",
    "validation",
}
_ONTOLOGY_PRIORITY = {
    "exact_alias": 4,
    "aggressive_fuzzy_guarded": 3,
    "fuzzy_alias": 2,
    "guardrail_rejected": 1,
    "ambiguous_rejected": 1,
    "noise_rejected": 0,
    "unmapped": 0,
}
_DEFAULT_TAXONOMY_PATH = (
    Path(__file__).resolve().parents[6]
    / "configs"
    / "taxonomy"
    / "exports"
    / "task_families_master.yaml"
)
_DEFAULT_ALIAS_EXTENSIONS_PATH = (
    Path(__file__).resolve().parents[6]
    / "configs"
    / "taxonomy"
    / "exports"
    / "task_family_alias_extensions.yaml"
)
_DEFAULT_CURATED_REGISTRY_PATH = (
    Path(__file__).resolve().parents[6]
    / "configs"
    / "taxonomy"
    / "crosswalks"
    / "psych101_experiments__to__tasks.v1.yaml"
)

_DATASET_ID_KEYS = ("dataset_id", "id", "accession", "slug")
_DATASET_NAME_KEYS = ("name", "title", "dataset_name", "label")
_DATASET_DESCRIPTION_KEYS = ("description", "summary", "abstract", "notes")
_DATASET_URL_KEYS = ("url", "homepage", "homepage_url", "source_url")
_DATASET_DOI_KEYS = ("doi", "paper_doi", "citation_doi")
_PRESERVED_AUDIT_KEYS = (
    "target_population",
    "sampling_frame",
    "inclusion_criteria",
    "exclusion_criteria",
    "cohort_metadata",
    "audit_group_keys",
    "group_counts",
    "missingness_by_group",
    "sample_weights",
    "sample_weight_summary",
    "site_or_cohort",
    "site",
    "cohort",
    "group",
    "fairness_audit",
)

_TRUTHY = {"1", "true", "yes", "on"}
_GENERIC_EXPERIMENT_NAME_RE = re.compile(
    r"^(?:exp(?:eriment)?|task|run|trial)[\s\-_]*\d+[a-z]?$"
)
_GENERIC_TASK_LABELS = {
    "choice task",
    "memory task",
}


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _collapse_ws(value: str) -> str:
    return " ".join(value.split())


def _normalize_key(value: Any) -> str:
    text = _coerce_text(value)
    if not text:
        return ""
    return _collapse_ws(text).lower()


def _title_case_label(value: str) -> str:
    cleaned = _collapse_ws(value.replace("_", " ").replace("-", " "))
    return " ".join(part.capitalize() for part in cleaned.split())


def _is_generic_experiment_name(value: str | None) -> bool:
    text = _normalize_key(value)
    if not text:
        return True
    return bool(_GENERIC_EXPERIMENT_NAME_RE.fullmatch(text))


def _is_generic_task_label(value: str | None) -> bool:
    text = _normalize_key(value)
    if not text:
        return True
    if _is_generic_experiment_name(text):
        return True
    return text in _GENERIC_TASK_LABELS


def _is_low_signal_ontology_candidate(field: str, text: str) -> bool:
    normalized = _normalize_key(text)
    if not normalized:
        return True
    if field in _EXPERIMENT_LABEL_KEYS and _is_generic_experiment_name(normalized):
        return True
    if field not in _EXPERIMENT_PATH_KEYS:
        return False
    if field not in _ONTOLOGY_PATH_KEYS:
        return True

    tokens = normalized.split()
    if not tokens:
        return True
    if _is_generic_experiment_name(normalized):
        return True
    if all(token in _LOW_SIGNAL_PATH_TOKENS for token in tokens):
        return True
    if any(token in _LOW_SIGNAL_PATH_TOKENS for token in tokens) and any(
        token in {"http", "https", "huggingface", "parquet", "datasets"}
        for token in tokens
    ):
        return True
    return False


def _slugify(value: str) -> str:
    cleaned = _normalize_key(value)
    if not cleaned:
        return ""
    slug = []
    last_was_sep = False
    for ch in cleaned:
        if ch.isalnum():
            slug.append(ch)
            last_was_sep = False
        elif ch in {" ", "-", "_", "/", ":"} and not last_was_sep:
            slug.append("-")
            last_was_sep = True
    return "".join(slug).strip("-")


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    text = _normalize_key(value)
    return text in _TRUTHY


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        if isinstance(value, float) and value != value:  # NaN
            return None
        return bool(value)
    text = _normalize_key(value)
    if not text:
        return None
    if text in {"true", "t", "yes", "y", "1", "open"}:
        return True
    if text in {"false", "f", "no", "n", "0", "closed"}:
        return False
    return None


def _split_multi_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items
    text = _coerce_text(value)
    if not text:
        return []
    parts: list[str] = []
    current = text.replace("\n", ",").replace("|", ",").replace(";", ",")
    for chunk in current.split(","):
        item = chunk.strip()
        if item:
            parts.append(item)
    return parts or [text]


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return int(value)
    text = _coerce_text(value)
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        if isinstance(value, float) and value != value:  # NaN
            return None
        return float(value)
    text = _coerce_text(value)
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _pick_first(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping:
            value = mapping.get(key)
            if value is not None and _coerce_text(value) is not None:
                return value
    return None


def _sanitize_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_metadata_value(item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, list | tuple | set):
        return [
            _sanitize_metadata_value(item)
            for item in value
            if item not in (None, "", [], {})
        ]
    if isinstance(value, bool | int | float):
        return value
    if value is None:
        return None
    text = _coerce_text(value)
    return text if text is not None else str(value)


def _extract_preserved_audit_metadata(raw: Mapping[str, Any]) -> dict[str, Any]:
    preserved: dict[str, Any] = {}
    for key in _PRESERVED_AUDIT_KEYS:
        if key not in raw:
            continue
        value = _sanitize_metadata_value(raw.get(key))
        if value in (None, "", [], {}):
            continue
        preserved[key] = value

    fairness_audit = preserved.get("fairness_audit")
    if isinstance(fairness_audit, Mapping):
        group_audit = fairness_audit.get("group_audit")
        if (
            "audit_group_keys" not in preserved
            and isinstance(group_audit, Mapping)
            and group_audit.get("resolved_group_keys")
        ):
            preserved["audit_group_keys"] = list(
                group_audit.get("resolved_group_keys") or []
            )
        if (
            "group_counts" not in preserved
            and isinstance(group_audit, Mapping)
            and group_audit.get("group_counts")
        ):
            preserved["group_counts"] = _sanitize_metadata_value(
                group_audit.get("group_counts")
            )

    cohort_metadata = preserved.get("cohort_metadata")
    if isinstance(cohort_metadata, Mapping):
        group_audit = cohort_metadata.get("group_audit")
        if (
            "audit_group_keys" not in preserved
            and isinstance(group_audit, Mapping)
            and group_audit.get("resolved_group_keys")
        ):
            preserved["audit_group_keys"] = list(
                group_audit.get("resolved_group_keys") or []
            )
        if (
            "group_counts" not in preserved
            and isinstance(group_audit, Mapping)
            and group_audit.get("group_counts")
        ):
            preserved["group_counts"] = _sanitize_metadata_value(
                group_audit.get("group_counts")
            )

    if "site_or_cohort" not in preserved:
        site = _coerce_text(raw.get("site"))
        cohort = _coerce_text(raw.get("cohort"))
        derived = _dedupe([item for item in (site, cohort) if item])
        if len(derived) == 1:
            preserved["site_or_cohort"] = derived[0]
        elif derived:
            preserved["site_or_cohort"] = derived

        return preserved


def _rollup_group_counts(
    group_counts_list: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rolled: dict[str, Any] = {}
    for group_counts in group_counts_list:
        for group_key, payload in group_counts.items():
            if not isinstance(payload, Mapping):
                continue
            target = rolled.setdefault(
                str(group_key),
                {
                    "participant_counts": {},
                    "row_counts": {},
                    "missing_participant_count": 0,
                    "missing_row_count": 0,
                    "n_levels": 0,
                },
            )
            for metric_key in ("participant_counts", "row_counts"):
                metric_payload = payload.get(metric_key)
                if not isinstance(metric_payload, Mapping):
                    continue
                bucket = target.setdefault(metric_key, {})
                for value_key, value_count in metric_payload.items():
                    bucket[str(value_key)] = int(bucket.get(str(value_key), 0)) + int(
                        _coerce_int(value_count) or 0
                    )
            target["missing_participant_count"] = int(
                target.get("missing_participant_count", 0)
            ) + int(
                _coerce_int(
                    payload.get("missing_participants")
                    or payload.get("missing_participant_count")
                )
                or 0
            )
            target["missing_row_count"] = int(target.get("missing_row_count", 0)) + int(
                _coerce_int(
                    payload.get("missing_rows") or payload.get("missing_row_count")
                )
                or 0
            )
            target["n_levels"] = max(
                int(target.get("n_levels", 0)),
                len(target.get("participant_counts", {})),
            )
    return rolled


def _synthesize_dataset_cohort_metadata(
    experiments: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    cohort_blocks = [
        experiment.get("cohort_metadata")
        for experiment in experiments
        if isinstance(experiment.get("cohort_metadata"), Mapping)
    ]
    if not cohort_blocks:
        return None

    requested = _dedupe(
        [
            key
            for block in cohort_blocks
            for key in _split_multi_value(block.get("requested_group_keys"))
        ]
    )
    resolved = _dedupe(
        [
            key
            for block in cohort_blocks
            for key in _split_multi_value(
                ((block.get("group_audit") or {}).get("resolved_group_keys"))
                or block.get("resolved_group_keys")
            )
        ]
    )
    missing = _dedupe(
        [
            key
            for block in cohort_blocks
            for key in _split_multi_value(
                ((block.get("group_audit") or {}).get("missing_group_keys"))
                or block.get("missing_group_keys")
            )
        ]
    )
    group_counts = _rollup_group_counts(
        [
            (block.get("group_audit") or {}).get("group_counts") or {}
            for block in cohort_blocks
        ]
    )
    return {
        "schema_version": "br-cohort-metadata-v1",
        "participant_id_scope": "experiment_local",
        "aggregation_scope": "dataset_rollup_from_experiments",
        "group_audit": {
            "requested_group_keys": requested,
            "resolved_group_keys": resolved,
            "missing_group_keys": missing,
            "group_counts": group_counts,
        },
    }


def _normalize_open_loop_flag(row: Mapping[str, Any]) -> bool | None:
    for key in ("open_loop", "is_open_loop", "closed_loop"):
        if key not in row:
            continue
        value = row.get(key)
        if value is None:
            continue
        coerced = _coerce_bool(value)
        if coerced is None:
            continue
        if key == "closed_loop":
            return not coerced
        return coerced
    return None


def _repo_text_candidate_from_path(value: str) -> list[str]:
    cleaned = value.replace("\\", "/").strip()
    if not cleaned:
        return []

    segments = [segment for segment in cleaned.split("/") if segment]
    if not segments:
        return [cleaned]

    candidates = [cleaned]
    for segment in segments:
        stem = Path(segment).stem or segment
        candidates.extend(
            part
            for part in (
                stem,
                stem.replace("_", " "),
                stem.replace("-", " "),
            )
            if part
        )

    if len(segments) >= 2:
        prefix = " ".join(Path(segment).stem or segment for segment in segments[:-1])
        tail = Path(segments[-1]).stem or segments[-1]
        candidates.extend(part for part in (prefix, f"{prefix} {tail}") if part)

    return _dedupe([_collapse_ws(candidate) for candidate in candidates if candidate])


def _collect_text_candidates(
    row: Mapping[str, Any],
    *,
    keys: Sequence[str],
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if key in _EXPERIMENT_PATH_KEYS:
            for item in _split_multi_value(value):
                for candidate in _repo_text_candidate_from_path(item):
                    candidates.append((key, candidate))
            continue
        for item in _split_multi_value(value):
            text = _collapse_ws(item)
            if text:
                candidates.append((key, text))
    return candidates


def _task_ontology_match_priority(
    method: str | None,
    score: float | None,
) -> tuple[int, float]:
    return (_ONTOLOGY_PRIORITY.get(method or "unmapped", 0), float(score or 0.0))


@dataclass(frozen=True)
class Psych101GraphRecordBundle:
    """Graph-ready output from a Psych-101 ingest pass."""

    nodes: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    normalized_dataset: dict[str, Any]
    normalized_experiments: list[dict[str, Any]]


@dataclass(frozen=True)
class Psych101CuratedMapping:
    experiment_id: str | None
    experiment_slug: str | None
    experiment_names: tuple[str, ...]
    task_label: str | None
    canonical_task_id: str | None
    canonical_task_label: str | None
    canonical_task_links: dict[str, Any]
    family_id: str | None
    family_label: str | None
    subfamily_id: str | None
    subfamily_label: str | None
    paradigm_name: str | None
    confidence: float
    source: str
    note: str | None


class Psych101IngestLoader:
    """Normalize Psych-101 metadata and emit graph-ready records."""

    def __init__(
        self,
        *,
        dataset_id: str = "psych101",
        source_name: str = "Psych-101",
        default_dataset_label: str = "Dataset",
        taxonomy_path: Path | str | None = None,
        alias_extensions_path: Path | str | None = None,
        curated_registry_path: Path | str | None = None,
        task_family_matcher: TaskFamilyMatcher | None = None,
        enable_task_family_matcher: bool = True,
    ) -> None:
        self.dataset_id = dataset_id
        self.source_name = source_name
        self.default_dataset_label = default_dataset_label
        self.taxonomy_path = (
            Path(taxonomy_path) if taxonomy_path else _DEFAULT_TAXONOMY_PATH
        )
        self.alias_extensions_path = (
            Path(alias_extensions_path)
            if alias_extensions_path
            else _DEFAULT_ALIAS_EXTENSIONS_PATH
        )
        self.curated_registry_path = (
            Path(curated_registry_path)
            if curated_registry_path
            else _DEFAULT_CURATED_REGISTRY_PATH
        )
        self.enable_task_family_matcher = bool(enable_task_family_matcher)
        self._task_family_matcher = task_family_matcher
        self._curated_registry: list[Psych101CuratedMapping] | None = None

    def _get_task_family_matcher(self) -> TaskFamilyMatcher | None:
        if not self.enable_task_family_matcher:
            return None
        if self._task_family_matcher is not None:
            return self._task_family_matcher
        if not self.taxonomy_path.exists():
            return None
        try:
            self._task_family_matcher = TaskFamilyMatcher(
                taxonomy_path=self.taxonomy_path,
                alias_extensions_path=(
                    self.alias_extensions_path
                    if self.alias_extensions_path.exists()
                    else None
                ),
                enable_fuzzy=True,
            )
        except Exception:
            self._task_family_matcher = None
        return self._task_family_matcher

    def _get_curated_registry(self) -> list[Psych101CuratedMapping]:
        if self._curated_registry is not None:
            return self._curated_registry
        if not self.curated_registry_path.exists():
            self._curated_registry = []
            return self._curated_registry

        payload = (
            yaml.safe_load(self.curated_registry_path.read_text(encoding="utf-8")) or {}
        )
        mappings = payload.get("mappings") if isinstance(payload, dict) else None
        defaults = payload.get("defaults") if isinstance(payload, dict) else None
        default_source = (
            str((defaults or {}).get("source") or "psych101_curated_registry")
            if isinstance(defaults, Mapping)
            else "psych101_curated_registry"
        )
        out: list[Psych101CuratedMapping] = []
        for mapping in mappings or []:
            if not isinstance(mapping, Mapping):
                continue
            canonical_task = mapping.get("canonical_task")
            family = mapping.get("family")
            provenance = mapping.get("provenance")
            match = mapping.get("match")
            experiment_names = []
            if isinstance(match, Mapping):
                experiment_names = [
                    _normalize_key(name)
                    for name in _split_multi_value(match.get("experiment_names"))
                    if _normalize_key(name)
                ]
            links = {}
            if isinstance(canonical_task, Mapping):
                raw_links = canonical_task.get("links")
                if isinstance(raw_links, Mapping):
                    links = {str(key): value for key, value in raw_links.items()}
            out.append(
                Psych101CuratedMapping(
                    experiment_id=_normalize_key(mapping.get("experiment_id")),
                    experiment_slug=_normalize_key(mapping.get("experiment_slug")),
                    experiment_names=tuple(_dedupe(experiment_names)),
                    task_label=_coerce_text(mapping.get("task_label")),
                    canonical_task_id=_coerce_text(
                        canonical_task.get("canonical_id")
                        if isinstance(canonical_task, Mapping)
                        else None
                    ),
                    canonical_task_label=_coerce_text(
                        canonical_task.get("label")
                        if isinstance(canonical_task, Mapping)
                        else None
                    ),
                    canonical_task_links=links,
                    family_id=_coerce_text(
                        family.get("family_id") if isinstance(family, Mapping) else None
                    ),
                    family_label=_coerce_text(
                        family.get("family_label")
                        if isinstance(family, Mapping)
                        else None
                    ),
                    subfamily_id=_coerce_text(
                        family.get("subfamily_id")
                        if isinstance(family, Mapping)
                        else None
                    ),
                    subfamily_label=_coerce_text(
                        family.get("subfamily_label")
                        if isinstance(family, Mapping)
                        else None
                    ),
                    paradigm_name=_coerce_text(
                        family.get("paradigm_name")
                        if isinstance(family, Mapping)
                        else None
                    ),
                    confidence=_coerce_float(
                        provenance.get("confidence")
                        if isinstance(provenance, Mapping)
                        else None
                    )
                    or 1.0,
                    source=_coerce_text(
                        mapping.get("source")
                        or (
                            provenance.get("source")
                            if isinstance(provenance, Mapping)
                            else None
                        )
                    )
                    or default_source,
                    note=_coerce_text(
                        provenance.get("rationale")
                        if isinstance(provenance, Mapping)
                        else None
                    ),
                )
            )
        self._curated_registry = out
        return self._curated_registry

    def _task_ontology_candidates(
        self,
        row: Mapping[str, Any],
        *,
        context_text: str | None = None,
    ) -> list[dict[str, Any]]:
        raw = dict(row or {})
        candidates = _collect_text_candidates(raw, keys=_EXPERIMENT_LABEL_KEYS)
        candidates.extend(_collect_text_candidates(raw, keys=_ONTOLOGY_PATH_KEYS))

        seen: set[tuple[str, str]] = set()
        ordered: list[dict[str, Any]] = []
        for field, text in candidates:
            normalized = _normalize_key(text)
            marker = (field, normalized)
            if (
                not normalized
                or marker in seen
                or _is_low_signal_ontology_candidate(field, text)
            ):
                continue
            seen.add(marker)
            ordered.append(
                {
                    "field": field,
                    "text": text,
                    "normalized": normalized,
                }
            )
        return ordered

    @staticmethod
    def _extract_experiment_slug(value: str | None) -> str | None:
        text = _coerce_text(value)
        if not text:
            return None
        cleaned = text.replace("\\", "/")
        first_segment = cleaned.split("/", 1)[0]
        return _normalize_key(Path(first_segment).stem or first_segment)

    def _resolve_curated_experiment_mapping(
        self,
        row: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        registry = self._get_curated_registry()
        if not registry:
            return None

        exact_ids = {
            _normalize_key(value)
            for value in (
                row.get("experiment_id"),
                row.get("experiment_path"),
                row.get("source_path"),
                row.get("file_path"),
                row.get("path"),
                row.get("filename"),
            )
            if _normalize_key(value)
        }
        experiment_names = {
            _normalize_key(value)
            for value in (
                row.get("experiment_name"),
                row.get("name"),
                row.get("title"),
                Path(str(row.get("experiment_id") or "")).stem or None,
            )
            if _normalize_key(value)
        }
        experiment_slugs = {
            slug
            for slug in (
                self._extract_experiment_slug(row.get("experiment_id")),
                self._extract_experiment_slug(row.get("experiment_path")),
                self._extract_experiment_slug(row.get("source_path")),
                self._extract_experiment_slug(row.get("file_path")),
                self._extract_experiment_slug(row.get("path")),
                self._extract_experiment_slug(row.get("filename")),
            )
            if slug
        }

        best: tuple[int, Psych101CuratedMapping, str, str] | None = None
        for entry in registry:
            match_field = None
            match_text = None
            priority = -1

            if entry.experiment_id and entry.experiment_id in exact_ids:
                match_field = "experiment_id"
                match_text = entry.experiment_id
                priority = 3
            elif entry.experiment_slug and entry.experiment_slug in experiment_slugs:
                if entry.experiment_names and not (
                    set(entry.experiment_names) & experiment_names
                ):
                    continue
                match_field = "experiment_slug"
                match_text = entry.experiment_slug
                priority = 2 if entry.experiment_names else 1

            if priority < 0 or match_field is None or match_text is None:
                continue
            if best is None or priority > best[0]:
                best = (priority, entry, match_field, match_text)

        if best is None:
            return None

        _, entry, match_field, match_text = best
        return {
            "matched": True,
            "match_method": "psych101_curated_registry",
            "match_score": entry.confidence,
            "match_field": match_field,
            "match_text": match_text,
            "family_id": entry.family_id,
            "family_label": entry.family_label,
            "family_description": None,
            "subfamily_id": entry.subfamily_id,
            "subfamily_label": entry.subfamily_label,
            "paradigm_name": entry.paradigm_name,
            "canonical_task_id": entry.canonical_task_id,
            "canonical_task_label": entry.canonical_task_label,
            "canonical_task_links": entry.canonical_task_links,
            "task_label": entry.task_label,
            "source": entry.source,
            "note": entry.note,
            "evidence": [
                {
                    "field": "curated_registry",
                    "text": match_text,
                    "matched": True,
                    "match_method": "psych101_curated_registry",
                    "match_score": entry.confidence,
                    "source": entry.source,
                    "note": entry.note,
                }
            ],
        }

    def _resolve_task_ontology_match(
        self,
        row: Mapping[str, Any],
        *,
        context_text: str | None = None,
    ) -> dict[str, Any]:
        matcher = self._get_task_family_matcher()
        candidates = self._task_ontology_candidates(row, context_text=context_text)
        evidence: list[dict[str, Any]] = []
        best: dict[str, Any] | None = None

        for candidate in candidates:
            if matcher is None:
                candidate["match_method"] = "unmapped"
                candidate["match_score"] = None
                evidence.append(candidate)
                continue

            record, method, score = matcher.match(candidate["text"])
            candidate["match_method"] = method
            candidate["match_score"] = score
            candidate["matched"] = record is not None
            if record is not None:
                candidate["family_id"] = record.family_id
                candidate["family_label"] = record.family_label
                candidate["family_description"] = record.family_description
                candidate["subfamily_id"] = record.subfamily_id
                candidate["subfamily_label"] = record.subfamily_label
                candidate["paradigm_name"] = record.paradigm_name
                priority = _task_ontology_match_priority(method, score)
                if best is None or priority > best["_priority"]:
                    best = {
                        "_priority": priority,
                        "record": record,
                        "candidate": candidate,
                        "method": method,
                        "score": score,
                    }
            evidence.append(candidate)

        if best is None:
            return {
                "matched": False,
                "match_method": None if matcher is not None else "unmapped",
                "match_score": None,
                "match_field": None,
                "match_text": None,
                "family_id": None,
                "family_label": None,
                "family_description": None,
                "subfamily_id": None,
                "subfamily_label": None,
                "paradigm_name": None,
                "evidence": evidence,
            }

        candidate = best["candidate"]
        record = best["record"]
        return {
            "matched": True,
            "match_method": best["method"],
            "match_score": best["score"],
            "match_field": candidate["field"],
            "match_text": candidate["text"],
            "family_id": record.family_id,
            "family_label": record.family_label,
            "family_description": record.family_description,
            "subfamily_id": record.subfamily_id,
            "subfamily_label": record.subfamily_label,
            "paradigm_name": record.paradigm_name,
            "evidence": evidence,
        }

    def normalize_dataset_metadata(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        """Normalize dataset-level metadata into a compact canonical shape."""
        raw = dict(metadata or {})
        preserved_audit = _extract_preserved_audit_metadata(raw)
        dataset_id = _coerce_text(_pick_first(raw, _DATASET_ID_KEYS)) or self.dataset_id
        name = _coerce_text(_pick_first(raw, _DATASET_NAME_KEYS)) or self.source_name
        description = _coerce_text(_pick_first(raw, _DATASET_DESCRIPTION_KEYS))
        url = _coerce_text(_pick_first(raw, _DATASET_URL_KEYS))
        doi = _coerce_text(_pick_first(raw, _DATASET_DOI_KEYS))

        task_families = self.extract_task_families(
            " ".join(
                part
                for part in (
                    name,
                    description,
                    _coerce_text(raw.get("domain")),
                    " ".join(_split_multi_value(raw.get("tags"))),
                )
                if part
            ),
            raw,
        )

        normalized = {
            "id": dataset_id,
            "dataset_id": dataset_id,
            "name": name,
            "source": _coerce_text(raw.get("source")) or self.source_name,
            "description": description,
            "doi": doi,
            "url": url,
            "license": _coerce_text(raw.get("license")),
            "version": _coerce_text(raw.get("version"))
            or _coerce_text(raw.get("dataset_version")),
            "n_participants": _coerce_int(
                _pick_first(raw, ("n_participants", "participants", "sample_size"))
            ),
            "n_trials": _coerce_int(
                _pick_first(raw, ("n_trials", "trials", "n_samples"))
            ),
            "n_experiments": _coerce_int(
                _pick_first(raw, ("n_experiments", "experiments", "n_tasks"))
            ),
            "task_families": task_families,
            "tags": _dedupe(
                [_coerce_text(tag) or "" for tag in _split_multi_value(raw.get("tags"))]
            ),
            **preserved_audit,
            "provenance": {
                "source": self.source_name,
                "dataset_id": dataset_id,
                "normalized_from": sorted(k for k, v in raw.items() if v is not None),
                "preserved_audit_keys": sorted(preserved_audit.keys()),
            },
        }
        return {
            key: value
            for key, value in normalized.items()
            if value not in (None, [], {})
        }

    def normalize_experiment_row(
        self,
        row: Mapping[str, Any],
        *,
        index: int | None = None,
        dataset_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Normalize one Psych-101 experiment row."""
        raw = dict(row or {})
        preserved_audit = _extract_preserved_audit_metadata(raw)
        dataset_id = (
            _coerce_text(_pick_first(raw, ("dataset_id", "psych101_id")))
            or _coerce_text((dataset_metadata or {}).get("dataset_id"))
            or self.dataset_id
        )

        explicit_label = _pick_first(raw, _EXPERIMENT_LABEL_KEYS)
        label_text = _coerce_text(explicit_label)
        context_candidates = _collect_text_candidates(
            raw, keys=_EXPERIMENT_CONTEXT_KEYS
        )
        path_candidates = _collect_text_candidates(raw, keys=_EXPERIMENT_PATH_KEYS)
        context_text = " ".join(text for _, text in context_candidates[:6] if text)
        if not context_text:
            context_text = " ".join(
                part
                for part in (
                    label_text,
                    _coerce_text(raw.get("description")),
                    _coerce_text(raw.get("prompt")),
                    _coerce_text(raw.get("paradigm")),
                    _coerce_text(raw.get("task")),
                    _coerce_text(raw.get("task_description")),
                )
                if part
            )

        ontology_match = self._resolve_curated_experiment_mapping(
            raw
        ) or self._resolve_task_ontology_match(
            raw,
            context_text=context_text,
        )
        task_families = self.extract_task_families(
            context_text,
            raw,
            ontology_match=ontology_match,
        )
        task_subfamilies = _dedupe(
            [
                item
                for item in [
                    _coerce_text(_pick_first(raw, ("task_subfamily", "subfamily"))),
                    _coerce_text(ontology_match.get("subfamily_label")),
                ]
                if item
            ]
        )
        task_paradigms = _dedupe(
            [
                item
                for item in [
                    _coerce_text(_pick_first(raw, ("task_paradigm", "paradigm_name"))),
                    _coerce_text(ontology_match.get("paradigm_name")),
                ]
                if item
            ]
        )
        task_labels = self.extract_task_labels(
            context_text,
            raw,
            task_families=task_families,
            ontology_match=ontology_match,
        )
        curated_task_label = _coerce_text(ontology_match.get("task_label"))
        canonical_task_label = _coerce_text(ontology_match.get("canonical_task_label"))
        if curated_task_label:
            task_labels = _dedupe([curated_task_label, *task_labels])
        if canonical_task_label:
            task_labels = _dedupe([canonical_task_label, *task_labels])

        experiment_id = (
            _coerce_text(
                _pick_first(raw, ("experiment_id", "id", "trialset_id", "run_id"))
            )
            or _coerce_text(_pick_first(raw, _EXPERIMENT_LABEL_KEYS))
            or f"{dataset_id}:experiment:{index if index is not None else 0}"
        )

        if ontology_match.get("matched"):
            task_family_id = ontology_match.get("family_id")
            task_family_label = ontology_match.get("family_label")
            task_subfamily_id = ontology_match.get("subfamily_id")
            task_subfamily_label = ontology_match.get("subfamily_label")
            task_paradigm_name = ontology_match.get("paradigm_name")
        else:
            task_family_id = None
            task_family_label = None
            task_subfamily_id = None
            task_subfamily_label = None
            task_paradigm_name = None

        source_paths = _dedupe(
            [
                _collapse_ws(text)
                for field, text in path_candidates
                if field in _EXPERIMENT_PATH_KEYS and text
            ]
        )
        experiment_path = _coerce_text(_pick_first(raw, _ONTOLOGY_PATH_KEYS))
        experiment_slug = self._extract_experiment_slug(
            experiment_path or experiment_id
        )
        display_name = label_text
        if _is_generic_experiment_name(display_name):
            display_name = (
                curated_task_label
                or canonical_task_label
                or _coerce_text(ontology_match.get("paradigm_name"))
                or display_name
            )
        if not display_name and task_labels:
            display_name = _title_case_label(task_labels[0])

        normalized = {
            "id": experiment_id,
            "experiment_id": experiment_id,
            "dataset_id": dataset_id,
            "experiment_name": label_text or display_name,
            "experiment_path": experiment_path,
            "experiment_slug": experiment_slug,
            "name": display_name,
            "description": _coerce_text(
                _pick_first(raw, ("description", "prompt", "notes"))
            ),
            "paradigm": _coerce_text(
                _pick_first(raw, ("paradigm", "task", "task_name"))
            ),
            "canonical_task_id": _coerce_text(ontology_match.get("canonical_task_id")),
            "canonical_task_label": canonical_task_label,
            "canonical_task_cogat_id": _coerce_text(
                (ontology_match.get("canonical_task_links") or {}).get("cogat")
                if isinstance(ontology_match.get("canonical_task_links"), Mapping)
                else None
            ),
            "task_families": task_families,
            "task_family_id": task_family_id,
            "task_family_label": task_family_label,
            "task_subfamily_id": task_subfamily_id,
            "task_subfamily_label": task_subfamily_label,
            "task_paradigm_name": task_paradigm_name,
            "task_subfamilies": task_subfamilies,
            "task_paradigms": task_paradigms,
            "task_labels": task_labels,
            "task_label": task_labels[0] if task_labels else None,
            "task_ontology": ontology_match,
            "task_ontology_match_method": ontology_match.get("match_method"),
            "task_ontology_match_score": ontology_match.get("match_score"),
            "task_ontology_match_field": ontology_match.get("match_field"),
            "task_ontology_match_text": ontology_match.get("match_text"),
            "task_ontology_evidence": ontology_match.get("evidence"),
            "condition": _coerce_text(
                _pick_first(raw, ("condition", "condition_label"))
            ),
            "model": _coerce_text(_pick_first(raw, ("model", "agent", "policy"))),
            "outcome": _coerce_text(
                _pick_first(raw, ("outcome", "choice", "response"))
            ),
            "n_participants": _coerce_int(
                _pick_first(raw, ("n_participants", "participants", "sample_size"))
            ),
            "n_trials": _coerce_int(
                _pick_first(raw, ("n_trials", "trials", "n_samples"))
            ),
            "confidence": _coerce_float(
                _pick_first(raw, ("confidence", "score", "similarity"))
            ),
            "is_open_loop": _normalize_open_loop_flag(raw),
            **preserved_audit,
            "provenance": {
                "source": self.source_name,
                "dataset_id": dataset_id,
                "row_index": index,
                "source_paths": source_paths,
                "normalized_from": sorted(k for k, v in raw.items() if v is not None),
                "preserved_audit_keys": sorted(preserved_audit.keys()),
            },
            "raw": raw,
        }
        return {
            key: value
            for key, value in normalized.items()
            if value not in (None, [], {})
        }

    def extract_task_families(
        self,
        text: str | None,
        row: Mapping[str, Any] | None = None,
        *,
        ontology_match: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Infer coarse task-family labels from explicit fields and text hooks."""
        candidates: list[str] = []
        raw = dict(row or {})

        for key in ("task_family", "task_families", "family", "domain"):
            value = raw.get(key)
            if value is None:
                continue
            candidates.extend(_split_multi_value(value))

        if ontology_match and ontology_match.get("family_label"):
            candidates.append(str(ontology_match["family_label"]))

        text_norm = _normalize_key(text)
        for family, keywords in _TASK_FAMILY_RULES:
            if any(keyword in text_norm for keyword in keywords):
                candidates.append(family)

        return _dedupe([_collapse_ws(item) for item in candidates if item])

    def extract_task_labels(
        self,
        text: str | None,
        row: Mapping[str, Any] | None = None,
        *,
        task_families: Sequence[str] | None = None,
        ontology_match: Mapping[str, Any] | None = None,
    ) -> list[str]:
        """Infer task labels from explicit labels and family-level hints."""
        raw = dict(row or {})
        candidates: list[str] = []

        if ontology_match and ontology_match.get("paradigm_name"):
            candidates.append(str(ontology_match["paradigm_name"]))

        if text:
            text_norm = _normalize_key(text)
            if "n-back" in text_norm or "working memory" in text_norm:
                candidates.append("n-back task")
            if "bandit" in text_norm:
                candidates.append("bandit task")
            if "two-step" in text_norm:
                candidates.append("two-step task")
            if "choice" in text_norm:
                candidates.append("choice task")
            if "memory" in text_norm:
                candidates.append("memory task")

        for key in ("task_label", "task_labels", "task_name", "task", "paradigm"):
            value = raw.get(key)
            if value is None:
                continue
            candidates.extend(_split_multi_value(value))

        if not candidates and task_families:
            candidates.extend(f"{family} task" for family in task_families[:1])

        cleaned = [_collapse_ws(item) for item in candidates if item]
        deduped = _dedupe(cleaned)
        specific = [item for item in deduped if not _is_generic_task_label(item)]
        return specific or deduped

    def task_mapping_candidates(self, experiment: Mapping[str, Any]) -> list[str]:
        """Return ordered task labels to try against canonical Task nodes."""
        candidates = [
            _coerce_text(experiment.get("canonical_task_label")),
            _coerce_text(experiment.get("task_paradigm_name")),
            _coerce_text(experiment.get("task_label")),
            _coerce_text(experiment.get("paradigm")),
            _coerce_text(experiment.get("name")),
        ]
        candidates.extend(
            _coerce_text(value) for value in experiment.get("task_labels", [])
        )
        return _dedupe([candidate for candidate in candidates if candidate])

    @staticmethod
    def _is_local_psych101_task_node(
        node_id: str | None,
        node_props: Mapping[str, Any] | None = None,
    ) -> bool:
        text_id = _coerce_text(node_id) or _coerce_text(
            node_props.get("id") if isinstance(node_props, Mapping) else None
        )
        if text_id and text_id.startswith("psych101:task:"):
            return True
        if (
            isinstance(node_props, Mapping)
            and _coerce_text(node_props.get("schema_version")) == "psych101-task-v1"
        ):
            return True
        return False

    @staticmethod
    def _task_description_from_experiment(experiment: Mapping[str, Any]) -> str | None:
        description = _coerce_text(experiment.get("description"))
        if description:
            return description
        evidence = experiment.get("task_ontology_evidence")
        if not isinstance(evidence, Sequence):
            return None
        for item in evidence:
            if not isinstance(item, Mapping):
                continue
            field = _coerce_text(item.get("field"))
            text = _coerce_text(item.get("text"))
            if field in {"description", "prompt", "task_description", "notes"} and text:
                return text
        return None

    def build_graph_plan(
        self,
        dataset_metadata: Mapping[str, Any],
        experiment_rows: Sequence[Mapping[str, Any]],
    ) -> Psych101GraphRecordBundle:
        """Convert normalized records into graph-ready nodes and relationships."""
        normalized_dataset = self.normalize_dataset_metadata(dataset_metadata)
        normalized_experiments = [
            self.normalize_experiment_row(
                row, index=index, dataset_metadata=normalized_dataset
            )
            for index, row in enumerate(experiment_rows)
        ]
        if "cohort_metadata" not in normalized_dataset:
            synthesized_cohort = _synthesize_dataset_cohort_metadata(
                normalized_experiments
            )
            if synthesized_cohort is not None:
                normalized_dataset["cohort_metadata"] = synthesized_cohort
                normalized_dataset.setdefault(
                    "audit_group_keys",
                    list(
                        (synthesized_cohort.get("group_audit") or {}).get(
                            "resolved_group_keys", []
                        )
                    ),
                )

        nodes: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        dataset_node_id = normalized_dataset["dataset_id"]
        nodes.append(
            {
                "node_id": dataset_node_id,
                "labels": [self.default_dataset_label, "Psych101Dataset"],
                "properties": {
                    **normalized_dataset,
                    "schema_version": "psych101-dataset-v1",
                    "source": self.source_name,
                },
            }
        )

        family_nodes: dict[str, dict[str, Any]] = {}
        task_nodes: dict[str, dict[str, Any]] = {}
        task_family_relationships: set[tuple[str, str]] = set()

        for experiment in normalized_experiments:
            experiment_id = experiment["experiment_id"]
            ontology_match = experiment.get("task_ontology")
            if not isinstance(ontology_match, Mapping):
                ontology_match = {}
            nodes.append(
                {
                    "node_id": experiment_id,
                    "labels": ["Experiment", "Psych101Experiment"],
                    "properties": {
                        **experiment,
                        "schema_version": "psych101-experiment-v1",
                        "source": self.source_name,
                    },
                }
            )
            relationships.append(
                {
                    "start_node": dataset_node_id,
                    "end_node": experiment_id,
                    "rel_type": "HAS_EXPERIMENT",
                    "properties": {
                        "source": self.source_name,
                        "confidence": 1.0,
                    },
                }
            )

            family_refs: list[tuple[str, dict[str, Any], bool]] = []
            canonical_family_id = _coerce_text(experiment.get("task_family_id"))
            canonical_family_label = _coerce_text(experiment.get("task_family_label"))
            canonical_subfamily_id = _coerce_text(experiment.get("task_subfamily_id"))
            canonical_subfamily_label = _coerce_text(
                experiment.get("task_subfamily_label")
            )
            canonical_family_description = _coerce_text(
                ontology_match.get("family_description")
            )

            if canonical_family_id and canonical_family_label:
                family_refs.append(
                    (
                        canonical_family_id,
                        {
                            "id": canonical_family_id,
                            "name": canonical_family_label,
                            "family_id": canonical_family_id,
                            "family_label": canonical_family_label,
                            "family_description": canonical_family_description,
                            "subfamily_id": canonical_subfamily_id,
                            "subfamily_label": canonical_subfamily_label,
                            "ontology_source": "task_family_taxonomy",
                            "source": self.source_name,
                            "schema_version": "psych101-task-family-v1",
                        },
                        True,
                    )
                )

            for family in experiment.get("task_families", []):
                if canonical_family_label and _normalize_key(family) == _normalize_key(
                    canonical_family_label
                ):
                    continue
                family_id = f"psych101:family:{_slugify(family)}"
                family_refs.append(
                    (
                        family_id,
                        {
                            "id": family_id,
                            "name": family,
                            "source": self.source_name,
                            "schema_version": "psych101-task-family-v1",
                        },
                        False,
                    )
                )

            for family_id, family_props, is_canonical in family_refs:
                if family_id not in family_nodes:
                    family_nodes[family_id] = {
                        "node_id": family_id,
                        "labels": ["TaskFamily"],
                        "properties": family_props,
                    }
                relationships.append(
                    {
                        "start_node": experiment_id,
                        "end_node": family_id,
                        "rel_type": "CLASSIFIED_UNDER",
                        "properties": {
                            "source": self.source_name,
                            "confidence": 1.0 if is_canonical else 0.75,
                            "ontology_match_method": experiment.get(
                                "task_ontology_match_method"
                            ),
                            "ontology_match_score": experiment.get(
                                "task_ontology_match_score"
                            ),
                            "subfamily_id": (
                                canonical_subfamily_id if is_canonical else None
                            ),
                            "subfamily_label": (
                                canonical_subfamily_label if is_canonical else None
                            ),
                        },
                    }
                )

            for label in experiment.get("task_labels", []):
                task_id = f"psych101:task:{_slugify(label)}"
                task_description = self._task_description_from_experiment(experiment)
                if task_id not in task_nodes:
                    task_audit_props = {
                        key: experiment.get(key)
                        for key in (
                            "target_population",
                            "sampling_frame",
                            "cohort_metadata",
                            "audit_group_keys",
                            "site_or_cohort",
                            "site",
                            "cohort",
                            "fairness_audit",
                        )
                        if experiment.get(key) not in (None, "", [], {})
                    }
                    task_nodes[task_id] = {
                        "node_id": task_id,
                        "labels": ["Task"],
                        "properties": {
                            "id": task_id,
                            "name": label,
                            "description": task_description,
                            "description_source": (
                                "psych101_experiment_text" if task_description else None
                            ),
                            "canonical_name": experiment.get("canonical_task_label")
                            or experiment.get("task_paradigm_name"),
                            "canonical_task_id": experiment.get("canonical_task_id"),
                            "canonical_task_cogat_id": experiment.get(
                                "canonical_task_cogat_id"
                            ),
                            "family_id": canonical_family_id,
                            "family_label": canonical_family_label,
                            "subfamily_id": canonical_subfamily_id,
                            "subfamily_label": canonical_subfamily_label,
                            "ontology_match_method": experiment.get(
                                "task_ontology_match_method"
                            ),
                            "ontology_match_score": experiment.get(
                                "task_ontology_match_score"
                            ),
                            **task_audit_props,
                            "source": self.source_name,
                            "schema_version": "psych101-task-v1",
                        },
                    }
                elif task_description and not task_nodes[task_id]["properties"].get(
                    "description"
                ):
                    task_nodes[task_id]["properties"]["description"] = task_description
                    task_nodes[task_id]["properties"][
                        "description_source"
                    ] = "psych101_experiment_text"
                for audit_key in (
                    "target_population",
                    "sampling_frame",
                    "cohort_metadata",
                    "audit_group_keys",
                    "site_or_cohort",
                    "site",
                    "cohort",
                    "fairness_audit",
                ):
                    if experiment.get(audit_key) not in (
                        None,
                        "",
                        [],
                        {},
                    ) and task_nodes[task_id]["properties"].get(audit_key) in (
                        None,
                        "",
                        [],
                        {},
                    ):
                        task_nodes[task_id]["properties"][audit_key] = experiment.get(
                            audit_key
                        )
                relationships.append(
                    {
                        "start_node": experiment_id,
                        "end_node": task_id,
                        "rel_type": "USES_TASK",
                        "properties": {
                            "source": self.source_name,
                            "confidence": 0.85,
                        },
                    }
                )
                if (
                    canonical_family_id
                    and (task_id, canonical_family_id) not in task_family_relationships
                ):
                    relationships.append(
                        {
                            "start_node": task_id,
                            "end_node": canonical_family_id,
                            "rel_type": "BELONGS_TO_FAMILY",
                            "properties": {
                                "source": self.source_name,
                                "confidence": 1.0,
                                "subfamily_id": canonical_subfamily_id,
                                "subfamily_label": canonical_subfamily_label,
                            },
                        }
                    )
                    task_family_relationships.add((task_id, canonical_family_id))

        nodes.extend(family_nodes.values())
        nodes.extend(task_nodes.values())

        return Psych101GraphRecordBundle(
            nodes=nodes,
            relationships=relationships,
            normalized_dataset=normalized_dataset,
            normalized_experiments=normalized_experiments,
        )

    def ingest(
        self,
        dataset_metadata: Mapping[str, Any],
        experiment_rows: Sequence[Mapping[str, Any]],
        *,
        db: Any | None = None,
    ) -> dict[str, Any]:
        """Build a graph plan and optionally write it through a DB-like object."""
        plan = self.build_graph_plan(dataset_metadata, experiment_rows)
        stats = {
            "dataset_nodes": 0,
            "experiment_nodes": 0,
            "task_family_nodes": 0,
            "task_nodes": 0,
            "relationships": 0,
            "task_map_relationships": 0,
        }

        if db is None:
            return {
                "plan": plan,
                "stats": stats,
            }

        for node in plan.nodes:
            labels = node["labels"]
            props = dict(node["properties"])
            node_id = node["node_id"]
            db.create_node(labels, props, node_id=node_id)
            if "Psych101Dataset" in labels:
                stats["dataset_nodes"] += 1
            elif "Psych101Experiment" in labels:
                stats["experiment_nodes"] += 1
            elif "TaskFamily" in labels:
                stats["task_family_nodes"] += 1
            elif "Task" in labels:
                stats["task_nodes"] += 1

        for rel in plan.relationships:
            db.create_relationship(
                rel["start_node"],
                rel["end_node"],
                rel["rel_type"],
                dict(rel.get("properties") or {}),
            )
            stats["relationships"] += 1

        resolver = None
        if hasattr(db, "find_nodes") and hasattr(db, "get_node"):
            try:
                resolver = TaskTaxonomyResolver(db)
            except Exception:
                resolver = None

        if resolver is not None and hasattr(db, "find_relationships"):
            for experiment in plan.normalized_experiments:
                experiment_id = experiment["experiment_id"]
                curated_task_id = _coerce_text(experiment.get("canonical_task_id"))
                curated_task_cogat_id = _coerce_text(
                    experiment.get("canonical_task_cogat_id")
                )
                curated_task_label = _coerce_text(
                    experiment.get("canonical_task_label")
                )
                for candidate in self.task_mapping_candidates(experiment):
                    local_task_node_id = f"psych101:task:{_slugify(candidate)}"
                    if db.get_node(local_task_node_id) is None:
                        continue
                    match_result = None
                    canonical_node_id = None
                    canonical_task = {}
                    direct_lookup_candidates = [
                        ("id", curated_task_cogat_id),
                        ("id", curated_task_id),
                        ("task_id", curated_task_id),
                        ("canonical_id", curated_task_id),
                        ("name", curated_task_label),
                    ]
                    for lookup_key, lookup_value in direct_lookup_candidates:
                        if not lookup_value:
                            continue
                        if lookup_key == "id":
                            existing_node = db.get_node(lookup_value)
                            if (
                                existing_node
                                and "Task" in (existing_node.get("labels") or [])
                                and not self._is_local_psych101_task_node(
                                    lookup_value,
                                    existing_node,
                                )
                            ):
                                canonical_node_id = lookup_value
                                canonical_task = existing_node
                                break
                            continue
                        existing_nodes = [
                            (node_id, node_props)
                            for node_id, node_props in db.find_nodes(
                                "Task", {lookup_key: lookup_value}
                            )
                            if not self._is_local_psych101_task_node(
                                node_id,
                                node_props,
                            )
                        ]
                        if existing_nodes:
                            canonical_node_id = existing_nodes[0][0]
                            canonical_task = existing_nodes[0][1] or {}
                            break

                    if canonical_node_id is None:
                        match_result = resolver.match_label(candidate)
                        if not match_result:
                            continue
                        canonical_node_id = resolver.ensure_canonical_task(match_result)
                        if not canonical_node_id:
                            continue
                        canonical_task = db.get_node(canonical_node_id) or {}

                    if self._is_local_psych101_task_node(
                        canonical_node_id,
                        canonical_task,
                    ):
                        continue
                    if canonical_node_id == local_task_node_id:
                        continue
                    existing = db.find_relationships(
                        start_node=local_task_node_id,
                        end_node=canonical_node_id,
                        rel_type="MAPS_TO",
                    )
                    local_task = db.get_node(local_task_node_id) or {}
                    canonical_definition = _coerce_text(
                        canonical_task.get("definition")
                        or canonical_task.get("description")
                    )
                    canonical_definition_source = _coerce_text(
                        canonical_task.get("definition_source")
                    )
                    if canonical_definition or canonical_node_id:
                        merged_task = dict(local_task)
                        merged_task["canonical_task_id"] = canonical_node_id
                        merged_task["canonical_task_name"] = canonical_task.get(
                            "name"
                        ) or (
                            match_result.match.get("label")
                            if match_result is not None
                            else curated_task_label
                        )
                        merged_task["canonical_definition"] = canonical_definition
                        if canonical_definition_source:
                            merged_task["canonical_definition_source"] = (
                                canonical_definition_source
                            )
                        if canonical_definition and not merged_task.get("description"):
                            merged_task["description"] = canonical_definition
                            merged_task["description_source"] = (
                                "cognitive_atlas_definition"
                            )
                        labels = local_task.get("labels") or ["Task"]
                        db.create_node(labels, merged_task, node_id=local_task_node_id)
                    if existing:
                        break
                    db.create_relationship(
                        local_task_node_id,
                        canonical_node_id,
                        "MAPS_TO",
                        {
                            "source": (
                                f"{self.source_name.lower().replace(' ', '_')}_taxonomy"
                                if match_result is not None
                                else "psych101_curated_registry"
                            ),
                            "match_method": (
                                match_result.method
                                if match_result is not None
                                else "psych101_curated_registry"
                            ),
                            "confidence": (
                                match_result.match.get("confidence")
                                if match_result is not None
                                else experiment.get("task_ontology_match_score")
                            ),
                            "canonical_id": (
                                match_result.match.get("canonical_id")
                                if match_result is not None
                                else curated_task_id
                            ),
                            "canonical_label": (
                                match_result.match.get("label")
                                if match_result is not None
                                else curated_task_label
                            ),
                            "experiment_id": experiment_id,
                        },
                    )
                    stats["relationships"] += 1
                    stats["task_map_relationships"] += 1
                    break

        return {
            "plan": plan,
            "stats": stats,
        }


def normalize_psych101_dataset_metadata(
    metadata: Mapping[str, Any],
    *,
    dataset_id: str = "psych101",
    source_name: str = "Psych-101",
    taxonomy_path: Path | str | None = None,
    alias_extensions_path: Path | str | None = None,
    curated_registry_path: Path | str | None = None,
    task_family_matcher: TaskFamilyMatcher | None = None,
    enable_task_family_matcher: bool = True,
) -> dict[str, Any]:
    """Pure helper wrapper around :class:`Psych101IngestLoader`."""
    loader = Psych101IngestLoader(
        dataset_id=dataset_id,
        source_name=source_name,
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_extensions_path,
        curated_registry_path=curated_registry_path,
        task_family_matcher=task_family_matcher,
        enable_task_family_matcher=enable_task_family_matcher,
    )
    return loader.normalize_dataset_metadata(metadata)


def normalize_psych101_experiment_row(
    row: Mapping[str, Any],
    *,
    index: int | None = None,
    dataset_metadata: Mapping[str, Any] | None = None,
    dataset_id: str = "psych101",
    source_name: str = "Psych-101",
    taxonomy_path: Path | str | None = None,
    alias_extensions_path: Path | str | None = None,
    curated_registry_path: Path | str | None = None,
    task_family_matcher: TaskFamilyMatcher | None = None,
    enable_task_family_matcher: bool = True,
) -> dict[str, Any]:
    """Pure helper wrapper around :class:`Psych101IngestLoader`."""
    loader = Psych101IngestLoader(
        dataset_id=dataset_id,
        source_name=source_name,
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_extensions_path,
        curated_registry_path=curated_registry_path,
        task_family_matcher=task_family_matcher,
        enable_task_family_matcher=enable_task_family_matcher,
    )
    return loader.normalize_experiment_row(
        row,
        index=index,
        dataset_metadata=dataset_metadata,
    )


def build_psych101_graph_plan(
    dataset_metadata: Mapping[str, Any],
    experiment_rows: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str = "psych101",
    source_name: str = "Psych-101",
    taxonomy_path: Path | str | None = None,
    alias_extensions_path: Path | str | None = None,
    curated_registry_path: Path | str | None = None,
    task_family_matcher: TaskFamilyMatcher | None = None,
    enable_task_family_matcher: bool = True,
) -> Psych101GraphRecordBundle:
    """Pure helper wrapper that returns graph-ready Psych-101 records."""
    loader = Psych101IngestLoader(
        dataset_id=dataset_id,
        source_name=source_name,
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_extensions_path,
        curated_registry_path=curated_registry_path,
        task_family_matcher=task_family_matcher,
        enable_task_family_matcher=enable_task_family_matcher,
    )
    return loader.build_graph_plan(dataset_metadata, experiment_rows)


def ingest_psych101(
    dataset_metadata: Mapping[str, Any],
    experiment_rows: Sequence[Mapping[str, Any]],
    *,
    db: Any | None = None,
    dataset_id: str = "psych101",
    source_name: str = "Psych-101",
    taxonomy_path: Path | str | None = None,
    alias_extensions_path: Path | str | None = None,
    curated_registry_path: Path | str | None = None,
    task_family_matcher: TaskFamilyMatcher | None = None,
    enable_task_family_matcher: bool = True,
) -> dict[str, Any]:
    """Convenience wrapper for tools and tests."""
    loader = Psych101IngestLoader(
        dataset_id=dataset_id,
        source_name=source_name,
        taxonomy_path=taxonomy_path,
        alias_extensions_path=alias_extensions_path,
        curated_registry_path=curated_registry_path,
        task_family_matcher=task_family_matcher,
        enable_task_family_matcher=enable_task_family_matcher,
    )
    return loader.ingest(dataset_metadata, experiment_rows, db=db)


__all__ = [
    "build_psych101_graph_plan",
    "ingest_psych101",
    "Psych101GraphRecordBundle",
    "Psych101IngestLoader",
    "normalize_psych101_dataset_metadata",
    "normalize_psych101_experiment_row",
]
