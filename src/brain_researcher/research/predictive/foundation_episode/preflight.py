"""Score-blind preparation for the foundation MVE-100 v2 discovery episode.

Preflight may inspect representation inputs plus target and exchangeability
identities, but it never selects, converts, or models a real endpoint value.
It writes ordinary operational records for a later, separately authorized
discovery run.
"""

from __future__ import annotations

import ast
import csv
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import numpy as np

from brain_researcher.research.predictive.foundation_episode import codex_cli
from brain_researcher.research.predictive.foundation_episode.codex_cli import (
    CodexCLIResult,
    build_codex_cli_argv,
    run_score_blind_liveness_probe,
)
from brain_researcher.research.predictive.foundation_episode.contracts import (
    CONTROLLER_CALL_BUDGETS,
    COVERAGE_STRATA,
    DISCOVERY_SCOPE,
    EPISODE_ID,
    ICA_TARGET_COLUMNS,
    PARTITION_SEED,
    PHASE_AWAITING_DISCOVERY_AUTHORIZATION,
    TARGET_NAME,
    FoundationEpisodeError,
    authorization_template,
    build_episode_contract,
    build_metric_catalog,
    controller_cadence_batches,
    sanitize_operational_catalog,
)
from brain_researcher.research.predictive.foundation_episode.controller import (
    controller_response_schema_for_slot_count,
)
from brain_researcher.research.predictive.foundation_episode.splits import (
    SplitPlans,
    build_group_safe_split_plans,
)

PREFLIGHT_SCHEMA = "br.foundation_episode.preflight.v3"
INPUT_MANIFEST_SCHEMA = "br.foundation_episode.input_manifest.v3"
TIMING_PROBE_SCHEMA = "br.foundation_episode.synthetic_timing_probe.v2"
ENVIRONMENT_MANIFEST_SCHEMA = "br.foundation_episode.environment_manifest.v2"
CONTROLLER_PROMPT_SCHEMA = "br.foundation_episode.controller_prompt.v2"
CONTROLLER_TRANSPORT_SCHEMA = "br.foundation_episode.controller_transport.v1"
CONTROLLER_LIVENESS_SCHEMA = "br.foundation_episode.controller_liveness.v1"
FIXED_ENGINE_SYMBOLS = (
    "_build_estimator",
    "_fit_cpm_fold",
    "_torch_matrix_model_candidates",
    "_train_brainnet_single_split",
    "_train_torch_matrix_model_single_split",
    "_vectorized_upper_triangle_to_symmetric",
    "_normalized_graph_operator",
    "_torch_matrix_forward",
)
ENGINE_DEPENDENCY_FILENAMES = ("_banghcp_common.py", "_banghcp_raw_target.py")
_TERM_FILENAME = re.compile(r"^term_(\d+)_iu\.h5$")
_ANCHOR_TERMS = (0, 14, 17, 19, 20, 40, 120)
_ROW_REMOVAL_INDEX = 254
_LIU_COMPARABILITY_RULES = {
    "must_label_outputs_as_reconstructed": True,
    "must_not_claim_direct_paper_reproduction": True,
    "must_not_compare_against_raw_target_pmats_or_memory_scores": True,
    "must_report_pearson_r_as_primary_literature_metric": True,
    "must_treat_r2_as_secondary_internal_metric": True,
    "must_use_component_targets": True,
}


@dataclass(frozen=True, slots=True)
class FoundationPreflightRequest:
    """Private file locations used during score-blind preparation only."""

    term_cache_dir: Path
    subject_ids_path: Path
    target_table_path: Path
    target_manifest_path: Path
    subject_intersection_path: Path
    exchangeability_manifest_path: Path
    term_names_path: Path
    term_prefixes_path: Path
    catalog_path: Path
    output_dir: Path
    kernel_source_path: Path
    kernel_symbols: tuple[str, ...] = ()
    seed: int = PARTITION_SEED


@dataclass(frozen=True, slots=True)
class FoundationPreflightResult:
    phase: str
    artifacts: Mapping[str, str]
    launch_ready: bool


def _regular_file(path: Path, *, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise FoundationEpisodeError(f"{label} must be a regular file")
    return candidate


def _regular_directory(path: Path, *, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_dir():
        raise FoundationEpisodeError(f"{label} must be a real directory")
    return candidate


def _write_json(
    path: Path, payload: Mapping[str, object], *, mode: int = 0o644
) -> None:
    """Write a small ordinary JSON record atomically for resume-safe reads."""

    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_preflight_bundle(
    output: Path, write_bundle: Callable[[Path], None]
) -> None:
    """Atomically publish a complete preflight bundle without replacing one."""

    target = Path(output)
    if target.exists() or target.is_symlink():
        raise FoundationEpisodeError(
            "preflight output directory must not already exist"
        )
    parent = target.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _regular_directory(parent, label="preflight output parent")
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=parent))
    published = False
    try:
        write_bundle(staging)
        if target.exists() or target.is_symlink():
            raise FoundationEpisodeError(
                "preflight output directory must not already exist"
            )
        os.rename(staging, target)
        published = True
    finally:
        if not published:
            shutil.rmtree(staging, ignore_errors=True)


def _read_json_object(path: Path) -> dict[str, object]:
    _regular_file(path, label="JSON input")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FoundationEpisodeError(f"invalid JSON object: {path}") from exc
    if not isinstance(payload, dict):
        raise FoundationEpisodeError("JSON input must be an object")
    return payload


def _read_subject_ids(path: Path) -> tuple[str, ...]:
    _regular_file(path, label="subject list")
    try:
        values = tuple(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise FoundationEpisodeError("cannot read subject list") from exc
    if len(values) != 326 or len(set(values)) != 326:
        raise FoundationEpisodeError(
            "subject list must contain exactly 326 unique rows"
        )
    return values


def _read_term_metadata(path: Path, *, label: str) -> tuple[str, ...]:
    _regular_file(path, label=label)
    try:
        values = tuple(
            text
            for line in path.read_text(encoding="utf-8").splitlines()
            if (text := line.strip()) and not text.startswith("#")
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise FoundationEpisodeError(f"cannot read {label}") from exc
    if len(values) < 76:
        raise FoundationEpisodeError(f"{label} has fewer than 76 usable rows")
    return values


def _validate_declared_target_path(
    value: object, *, expected_target_table_path: Path, label: str
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise FoundationEpisodeError(f"{label} does not declare its target table")
    declared = _regular_file(Path(value), label=f"{label} target table").resolve()
    expected = _regular_file(
        expected_target_table_path, label="requested target table"
    ).resolve()
    if declared != expected:
        raise FoundationEpisodeError(f"{label} points to a different target table")


def _read_liu_target_manifest(
    path: Path, *, expected_target_table_path: Path | None = None
) -> dict[str, object]:
    """Validate only the public target/comparability contract, never target values."""

    manifest = _read_json_object(path)
    validation = manifest.get("validation")
    targets = manifest.get("targets")
    rules = manifest.get("comparability_rules")
    expected_header = ("Subject", *ICA_TARGET_COLUMNS)
    if (
        manifest.get("comparability_status") != "reconstructed_not_paper_exact"
        or not isinstance(validation, Mapping)
        or validation.get("row_count") != 326
        or validation.get("subject_id_column") != "Subject"
        or tuple(validation.get("fieldnames", ())) != expected_header
        or tuple(validation.get("target_columns", ())) != ICA_TARGET_COLUMNS
        or not isinstance(targets, list)
        or not isinstance(rules, Mapping)
        or any(
            rules.get(key) is not value
            for key, value in _LIU_COMPARABILITY_RULES.items()
        )
    ):
        raise FoundationEpisodeError(
            "Liu target manifest comparability contract is invalid"
        )
    target = next(
        (
            row
            for row in targets
            if isinstance(row, Mapping) and row.get("target_column") == TARGET_NAME
        ),
        None,
    )
    if (
        not isinstance(target, Mapping)
        or target.get("reference_mean_r") != 0.215
        or target.get("reference_best_r") != 0.42
    ):
        raise FoundationEpisodeError(
            "Liu target manifest lacks ICA_Cognition references"
        )
    if expected_target_table_path is not None:
        _validate_declared_target_path(
            manifest.get("behavior_csv_path"),
            expected_target_table_path=expected_target_table_path,
            label="Liu target manifest",
        )
    return {
        "target_table_header": expected_header,
        "comparability_status": "reconstructed_not_paper_exact",
        "reference_mean_r": 0.215,
        "reference_best_r": 0.42,
        "comparability_rules": dict(_LIU_COMPARABILITY_RULES),
    }


def _read_target_table_subjects(
    path: Path, *, expected_header: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read the target header and Subject cells without touching target values."""

    _regular_file(path, label="target table")
    expected = tuple(expected_header)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = tuple(next(reader, ()))
            if header != expected:
                raise FoundationEpisodeError(
                    "target table must contain only Subject plus the five ICA targets"
                )
            subject_column = header.index("Subject")
            subjects: list[str] = []
            seen: set[str] = set()
            for row in reader:
                if len(row) != len(header):
                    raise FoundationEpisodeError(
                        "target table contains a malformed row"
                    )
                subject = row[subject_column].strip()
                if not subject or subject in seen:
                    raise FoundationEpisodeError(
                        "target table Subject values are invalid"
                    )
                seen.add(subject)
                subjects.append(subject)
    except FoundationEpisodeError:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise FoundationEpisodeError("cannot read target table Subject values") from exc
    if len(subjects) != 326:
        raise FoundationEpisodeError("target table must contain exactly 326 subjects")
    return tuple(subjects), header


def _read_subject_list(path: Path, *, label: str) -> tuple[str, ...]:
    _regular_file(path, label=label)
    try:
        values = tuple(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise FoundationEpisodeError(f"cannot read {label}") from exc
    if not values or len(values) != len(set(values)):
        raise FoundationEpisodeError(f"{label} must contain unique values")
    return values


def _read_ica_subject_intersection(
    path: Path, *, expected_target_table_path: Path | None = None
) -> tuple[str, ...]:
    """Read the explicit ICA-Cognition subject order used by the feature cache."""

    intersection = _read_json_object(path)
    subjects = tuple(intersection.get("selected_subject_ids", ()))
    if (
        intersection.get("target_column") != TARGET_NAME
        or intersection.get("alignment_status") != "verified_subject_list_file"
        or intersection.get("pyspi_subject_count") != 326
        or intersection.get("reference_subject_count") != 326
        or intersection.get("selected_subject_count") != 326
        or intersection.get("selected_subject_reference_indices") != list(range(326))
        or len(subjects) != 326
        or len(set(subjects)) != 326
        or any(
            not isinstance(subject, str)
            or not subject.strip()
            or subject != subject.strip()
            for subject in subjects
        )
    ):
        raise FoundationEpisodeError("ICA subject intersection is invalid")
    if expected_target_table_path is not None:
        _validate_declared_target_path(
            intersection.get("behavior_csv_path"),
            expected_target_table_path=expected_target_table_path,
            label="ICA subject intersection",
        )
    return subjects


def _read_exchangeability_identities(
    path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Read Family_ID only from the frozen exchangeability manifest."""

    manifest = _read_json_object(path)
    rows = manifest.get("subjects")
    if (
        manifest.get("schema_version") != "hcp_exchangeability_manifest_v1"
        or manifest.get("n_subjects") != 326
        or not isinstance(rows, list)
        or len(rows) != 326
    ):
        raise FoundationEpisodeError("exchangeability manifest is invalid")
    subjects: list[str] = []
    families: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("index") != index:
            raise FoundationEpisodeError(
                "exchangeability manifest row order is invalid"
            )
        subject = row.get("subject_id")
        family = row.get("family_id")
        if (
            not isinstance(subject, str)
            or not subject.strip()
            or subject != subject.strip()
            or not isinstance(family, str)
            or not family.strip()
            or family != family.strip()
            or subject in seen
        ):
            raise FoundationEpisodeError(
                "exchangeability manifest identities are invalid"
            )
        seen.add(subject)
        subjects.append(subject)
        families.append(family)
    return tuple(subjects), tuple(families)


def _validate_subject_sequence_closure(
    *,
    recovered_subjects: Sequence[str],
    target_subjects: Sequence[str],
    intersection_subjects: Sequence[str],
    exchangeability_subjects: Sequence[str],
) -> None:
    expected = tuple(recovered_subjects)
    if tuple(target_subjects) != expected:
        raise FoundationEpisodeError(
            "target table Subject order does not match recovered feature subjects"
        )
    if tuple(intersection_subjects) != expected:
        raise FoundationEpisodeError(
            "ICA subject intersection does not match recovered feature subjects"
        )
    if tuple(exchangeability_subjects) != expected:
        raise FoundationEpisodeError(
            "exchangeability subjects do not match recovered feature subjects"
        )


def _row_order_record(
    *,
    cache: Path,
    terms: Sequence[Mapping[str, object]],
    subject_ids_path: Path,
    subject_intersection_path: Path,
    generator_path: Path,
) -> dict[str, object]:
    """Check cache sidecars, raw327 anchors, and explicit ICA intersection."""

    sidecars = [
        cache / f"term_{int(term['term_index'])}_iu.meta.json" for term in terms
    ]
    if len(sidecars) != 76 or any(
        not item.is_file() or item.is_symlink() for item in sidecars
    ):
        raise FoundationEpisodeError(
            "all 76 term sidecars are required for row-order verification"
        )
    declared_subject_files: set[str] = set()
    for term, sidecar in zip(terms, sidecars, strict=True):
        record = _read_json_object(sidecar)
        index = term.get("term_index")
        if (
            record.get("term_index") != index
            or record.get("subject_count") != 326
            or record.get("feature_count") != 4950
        ):
            raise FoundationEpisodeError(
                "term sidecar does not match its matrix dimensions"
            )
        if Path(str(record.get("output_h5", ""))).name != f"term_{index}_iu.h5":
            raise FoundationEpisodeError(
                "term sidecar points to a different matrix name"
            )
        subject_file = Path(str(record.get("subject_list_path", ""))).name
        if subject_file != subject_ids_path.name:
            raise FoundationEpisodeError("term sidecar names a different subject list")
        declared_subject_files.add(subject_file)
    if len(declared_subject_files) != 1:
        raise FoundationEpisodeError("term sidecars disagree about subject ordering")
    project_root = generator_path.parents[3]
    raw_subject_path = (
        project_root / "manifests" / "lane_b_subjects_raw327_complete_rest.txt"
    )
    raw_subjects = _read_subject_list(
        raw_subject_path, label="raw row-order subject list"
    )
    current_subjects = _read_subject_ids(subject_ids_path)
    if len(raw_subjects) != 327 or raw_subjects[_ROW_REMOVAL_INDEX] == "":
        raise FoundationEpisodeError("raw row-order provenance is invalid")
    removed_subject = raw_subjects[_ROW_REMOVAL_INDEX]
    expected = tuple(
        item for item in sorted(raw_subjects, key=int) if item != removed_subject
    )
    if current_subjects != expected:
        raise FoundationEpisodeError(
            "recovered subject order differs from raw-row removal provenance"
        )
    intersection_subjects = _read_ica_subject_intersection(subject_intersection_path)
    if intersection_subjects != current_subjects:
        raise FoundationEpisodeError(
            "ICA subject intersection does not confirm recovered feature order"
        )
    raw_cache = cache.parent / f"{cache.name}_lane_b_raw327"
    try:
        import h5py

        for index in _ANCHOR_TERMS:
            current_path = cache / f"term_{index}_iu.h5"
            raw_path = raw_cache / f"term_{index}_iu.h5"
            with (
                h5py.File(current_path, "r") as current,
                h5py.File(raw_path, "r") as raw,
            ):
                current_values = np.asarray(current[f"term_{index}_iu"])
                raw_values = np.asarray(raw[f"term_{index}_iu"])
            if current_values.shape != (326, 4950) or raw_values.shape != (327, 4950):
                raise FoundationEpisodeError("row-order anchor dimensions are invalid")
            if not np.array_equal(
                current_values, np.delete(raw_values, _ROW_REMOVAL_INDEX, axis=0)
            ):
                raise FoundationEpisodeError(
                    "row-order anchor arrays differ after declared removal"
                )
    except FoundationEpisodeError:
        raise
    except Exception as exc:
        raise FoundationEpisodeError("cannot verify row-order anchors") from exc
    return {
        "sidecar_count": 76,
        "sidecars_valid": True,
        "subject_order_verified": True,
        "ica_intersection_verified": True,
        "reference_indices_verified": True,
        "raw_row_count": 327,
        "removed_row_index": _ROW_REMOVAL_INDEX,
        "anchor_terms": list(_ANCHOR_TERMS),
        "anchors_equal_after_removal": True,
        "files": [item.name for item in sidecars],
    }


def _inspect_term_cache(
    path: Path,
    *,
    subject_ids_path: Path,
    subject_intersection_path: Path,
    generator_path: Path,
) -> tuple[Path, dict[str, object]]:
    cache = _regular_directory(path, label="term cache")
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise FoundationEpisodeError("h5py is required for term inspection") from exc
    members: list[tuple[int, Path]] = []
    for member in cache.iterdir():
        match = _TERM_FILENAME.fullmatch(member.name)
        if match is not None:
            members.append((int(match.group(1)), member))
    members.sort(key=lambda item: item[0])
    if len(members) != 76 or len({index for index, _ in members}) != 76:
        raise FoundationEpisodeError("term cache must contain exactly 76 term matrices")
    terms: list[dict[str, object]] = []
    for index, member in members:
        _regular_file(member, label="term matrix")
        dataset_name = f"term_{index}_iu"
        try:
            with h5py.File(member, "r") as handle:
                if set(handle.keys()) != {dataset_name}:
                    raise FoundationEpisodeError("term matrix dataset name is invalid")
                dataset = handle[dataset_name]
                shape = tuple(int(value) for value in dataset.shape)
                dtype = np.dtype(dataset.dtype)
        except FoundationEpisodeError:
            raise
        except Exception as exc:
            raise FoundationEpisodeError("cannot inspect term matrix") from exc
        if shape != (326, 4950) or dtype.kind not in {"f", "i", "u"}:
            raise FoundationEpisodeError("term matrix must be numeric 326 by 4950")
        terms.append(
            {
                "term_index": index,
                "dataset": dataset_name,
                "file": member.name,
                "shape": [326, 4950],
                "dtype": dtype.str,
            }
        )
    if not terms:
        raise AssertionError("term inspection unexpectedly found no terms")
    return members[0][1], {
        "term_count": 76,
        "terms": terms,
        "row_order": _row_order_record(
            cache=cache,
            terms=terms,
            subject_ids_path=subject_ids_path,
            subject_intersection_path=subject_intersection_path,
            generator_path=generator_path,
        ),
    }


def _import_kernel_module(path: Path) -> ModuleType:
    _regular_file(path, label="engine source")
    module_name = f"_foundation_mve24_kernel_{uuid.uuid4().hex}"
    source_directory = str(path.parent)
    sibling_names = ("_banghcp_common", "_banghcp_raw_target")
    previous = {name: sys.modules.get(name) for name in sibling_names}
    try:
        sys.path.insert(0, source_directory)
        for name in sibling_names:
            sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError("no Python module loader")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        raise FoundationEpisodeError("engine source could not be imported") from exc
    finally:
        if sys.path and sys.path[0] == source_directory:
            sys.path.pop(0)
        for name in sibling_names:
            sys.modules.pop(name, None)
            if previous[name] is not None:
                sys.modules[name] = previous[name]


def _kernel_record(
    path: Path, *, required_symbols: Sequence[str], catalog: Mapping[str, object]
) -> dict[str, object]:
    _regular_file(path, label="engine source")
    for filename in ENGINE_DEPENDENCY_FILENAMES:
        _regular_file(path.parent / filename, label="engine dependency")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise FoundationEpisodeError("engine source is not parseable Python") from exc
    required = tuple(dict.fromkeys((*FIXED_ENGINE_SYMBOLS, *required_symbols)))
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    if missing := sorted(set(required) - defined):
        raise FoundationEpisodeError(
            f"engine source lacks required callable(s): {', '.join(missing)}"
        )
    module = _import_kernel_module(path)
    if missing := [
        name for name in required if not callable(getattr(module, name, None))
    ]:
        raise FoundationEpisodeError(
            f"engine callable(s) are unavailable: {', '.join(missing)}"
        )
    declared: set[str] = set()
    for attribute in (
        "FOUNDATION_OPERATIONAL_KEYS",
        "MATRIX_ONLY_CLASSIFIERS",
        "CLASSIFIER_METADATA",
        "CLASSIFIER_REGISTRY",
        "VALID_CLASSIFIERS",
    ):
        value = getattr(module, attribute, ())
        if isinstance(value, Mapping):
            declared.update(key for key in value if isinstance(key, str))
        elif not isinstance(value, str) and isinstance(value, Sequence):
            declared.update(key for key in value if isinstance(key, str))
    planned = [
        entry.get("classifier_key")
        for entry in catalog.get("classifier_catalog", [])
        if isinstance(entry, Mapping) and entry.get("runnable") is True
    ]
    return {
        "provided": True,
        "actual_imported": True,
        "symbols": list(required),
        "runnable_key_capabilities": [
            {"operational_key": key, "passed": key in declared}
            for key in planned
            if isinstance(key, str)
        ],
        "dependencies_present": True,
    }


def _validate_metric_catalog_against_engine(
    *, kernel_source_path: Path, metric_catalog: Mapping[str, object]
) -> None:
    module = _import_kernel_module(kernel_source_path)
    descriptor = getattr(module, "metric_descriptor", None)
    terms = metric_catalog.get("terms")
    if not callable(descriptor) or not isinstance(terms, list):
        raise FoundationEpisodeError("engine cannot verify metric metadata")
    for term in terms:
        if not isinstance(term, Mapping):
            raise FoundationEpisodeError("metric catalog is malformed")
        try:
            engine_term = descriptor(term.get("term_index"))
        except Exception as exc:
            raise FoundationEpisodeError("engine rejected a term index") from exc
        if (
            not isinstance(engine_term, Mapping)
            or engine_term.get("term_name") != term.get("metric_alias")
            or engine_term.get("term_prefix") != term.get("metric_family")
        ):
            raise FoundationEpisodeError("metric catalog differs from engine metadata")


def _first_parameter_values(grid: Mapping[str, object]) -> dict[str, object]:
    selected: dict[str, object] = {}
    for key, values in grid.items():
        if isinstance(values, str) or not isinstance(values, Sequence) or not values:
            raise FoundationEpisodeError("engine probe grid is invalid")
        selected[key] = values[0]
    return selected


def _probe_fold_local_capability(
    *, term_path: Path, plans: SplitPlans, kernel_source_path: Path, seed: int
) -> dict[str, object]:
    """Exercise five real engine paths against synthetic labels only."""

    try:
        import h5py
        import torch
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise FoundationEpisodeError("h5py and torch are required for probes") from exc
    engine = _import_kernel_module(kernel_source_path)
    private = plans.private_plan
    outer_folds = private.get("outer_folds") if isinstance(private, Mapping) else None
    if (
        not isinstance(outer_folds, list)
        or not outer_folds
        or not isinstance(outer_folds[0], Mapping)
    ):
        raise FoundationEpisodeError("private split plan has no outer folds")
    rows = np.asarray(outer_folds[0].get("train_row_indices", ()), dtype=np.int64)
    rows = rows[: min(32, len(rows))]
    if len(rows) < 8:
        raise FoundationEpisodeError("probe requires at least eight training rows")
    match = _TERM_FILENAME.fullmatch(term_path.name)
    if match is None:
        raise FoundationEpisodeError("probe term filename is invalid")
    try:
        with h5py.File(term_path, "r") as handle:
            matrix = np.asarray(
                handle[f"term_{match.group(1)}_iu"][rows, :], dtype=np.float32
            )
    except Exception as exc:
        raise FoundationEpisodeError("cannot read probe term matrix") from exc
    if matrix.shape != (len(rows), 4950) or not np.all(np.isfinite(matrix)):
        raise FoundationEpisodeError("probe matrix is invalid")
    split = max(4, len(rows) * 3 // 4)
    x_train, x_valid = matrix[:split], matrix[split:]
    labels = np.random.default_rng(seed).normal(size=len(rows)).astype(np.float32)
    y_train, y_valid = labels[:split], labels[split:]
    device = "cuda" if torch.cuda.is_available() else "cpu"

    def sklearn_probe(classifier: str) -> None:
        estimator, grid = engine._build_estimator(
            classifier,
            (1.0,),
            seed,
            n_train_samples=len(x_train),
            n_features=x_train.shape[1],
        )
        estimator.set_params(**_first_parameter_values(grid))
        estimator.fit(x_train, y_train)
        estimator.predict(x_valid)

    def cpm_probe() -> None:
        engine._fit_cpm_fold(
            X_train=x_train,
            y_train=y_train,
            X_eval=x_valid,
            top_k=min(25, x_train.shape[1]),
        )

    def brainnet_probe() -> None:
        config = engine._torch_matrix_model_candidates("brainnetcnn")[0]
        engine._train_brainnet_single_split(
            X_train=x_train,
            y_train=y_train,
            X_val=x_valid,
            y_val=y_valid,
            raw_edge_count=4950,
            kept_edge_indices=list(range(4950)),
            config=config,
            seed=seed,
        )

    def graph_probe() -> None:
        config = engine._torch_matrix_model_candidates("graph_transformer")[0]
        engine._train_torch_matrix_model_single_split(
            classifier="graph_transformer",
            X_train=x_train,
            y_train=y_train,
            X_val=x_valid,
            y_val=y_valid,
            raw_edge_count=4950,
            kept_edge_indices=list(range(4950)),
            config=config,
            seed=seed,
        )

    probes = {
        "ridge": lambda: sklearn_probe("ridge"),
        "cpm": cpm_probe,
        "xgboost": lambda: sklearn_probe("xgboost"),
        "brainnetcnn": brainnet_probe,
        "graph_transformer": graph_probe,
    }
    rows_out: list[dict[str, object]] = []
    for family, callback in probes.items():
        if device == "cuda":
            torch.cuda.empty_cache()
        started = time.perf_counter()
        try:
            callback()
        except Exception as exc:
            rows_out.append(
                {
                    "family": family,
                    "passed": False,
                    "runtime_seconds": time.perf_counter() - started,
                    "error_type": type(exc).__name__,
                }
            )
        else:
            rows_out.append(
                {
                    "family": family,
                    "passed": True,
                    "runtime_seconds": time.perf_counter() - started,
                }
            )
    return {
        "schema_version": TIMING_PROBE_SCHEMA,
        "score_blind": True,
        "synthetic_labels_only": True,
        "real_endpoint_selected": False,
        "real_endpoint_converted": False,
        "real_endpoint_used": False,
        "device": device,
        "sample_row_count": int(len(rows)),
        "probes": rows_out,
    }


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _environment_manifest() -> dict[str, object]:
    try:
        import torch
    except ImportError:  # pragma: no cover - environment dependent
        torch = None  # type: ignore[assignment]
    available = bool(torch is not None and torch.cuda.is_available())
    count = int(torch.cuda.device_count()) if available else 0
    return {
        "schema_version": ENVIRONMENT_MANIFEST_SCHEMA,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "packages": {
            name: _package_version(name)
            for name in ("numpy", "h5py", "scikit-learn", "torch", "xgboost", "openai")
        },
        "gpu": {
            "cuda_available": available,
            "device_count": count,
            "device_name": str(torch.cuda.get_device_name(0)) if available else None,
        },
    }


def _single_idle_gpu(*, check_timing: str) -> dict[str, object]:
    environment = _environment_manifest()
    gpu = environment["gpu"]
    assert isinstance(gpu, Mapping)
    available = gpu.get("cuda_available") is True
    count = gpu.get("device_count")
    idle = False
    if available and count == 1:
        try:
            completed = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            observed = {
                line.strip() for line in completed.stdout.splitlines() if line.strip()
            }
            external = observed - {str(os.getpid())}
            idle = completed.returncode == 0 and not external
        except (OSError, subprocess.SubprocessError):
            idle = False
    return {
        "cuda_available": available,
        "device_count": count,
        "idle": idle,
        "ready": available and count == 1 and idle,
        "check_timing": check_timing,
        "own_process_excluded": True,
    }


def _controller_prompt_artifact(contract: Mapping[str, object]) -> dict[str, object]:
    controller = contract.get("controller")
    resource = contract.get("resource_tool_gate")
    cadence = controller_cadence_batches()
    evidence_release = contract.get("evidence_release")
    expected_evidence_batches = [
        {
            "batch": row["batch"],
            "ledger_cutoff_slot": row["ledger_cutoff_slot"],
            "score_release_after_slot": row["score_release_after_slot"],
            "no_within_batch_peeking": row["no_within_batch_peeking"],
        }
        for row in cadence
    ]
    if (
        not isinstance(controller, Mapping)
        or not isinstance(resource, Mapping)
        or contract.get("proposal_batches") != cadence
        or any(
            resource.get(key) != value for key, value in CONTROLLER_CALL_BUDGETS.items()
        )
        or not isinstance(evidence_release, Mapping)
        or evidence_release.get("batches") != expected_evidence_batches
        or evidence_release.get("within_batch_score_visibility") != "forbidden"
    ):
        raise FoundationEpisodeError("episode contract lacks controller settings")
    return {
        "schema_version": CONTROLLER_PROMPT_SCHEMA,
        "provider": controller.get("provider"),
        "cli_binary": controller.get("cli_binary"),
        "model": controller.get("model"),
        "reasoning_effort": controller.get("reasoning_effort"),
        "prompt_delivery": "stdin_only",
        "strict_json_schema": True,
        "controller_batches": len(cadence),
        "decisions_per_batch": int(cadence[0]["decision_count"]),
        "controller_call_budgets": dict(CONTROLLER_CALL_BUDGETS),
    }


def _controller_transport_artifact(contract: Mapping[str, object]) -> dict[str, object]:
    """Freeze the exact score-blind Codex CLI policy, without a real prompt."""

    controller = contract.get("controller")
    _controller_prompt_artifact(contract)
    if (
        not isinstance(controller, Mapping)
        or controller.get("provider") != "codex.cli"
        or controller.get("cli_binary") != codex_cli.CODEX_CLI_BINARY
        or controller.get("model") != codex_cli.CODEX_CLI_MODEL
        or controller.get("reasoning_effort") != codex_cli.CODEX_CLI_REASONING_EFFORT
        or controller.get("skill_search_enabled") is not False
        or controller.get("skills_include_instructions") is not False
        or controller.get("tool_event_policy") != "forbidden_fail_closed"
        or controller.get("strict_json_schema") is not True
        or controller.get("event_audit") != {"format": "jsonl", "complete": True}
    ):
        raise FoundationEpisodeError(
            "episode contract lacks Codex CLI controller policy"
        )
    argv = build_codex_cli_argv(
        output_schema_path="<FROZEN_OUTPUT_SCHEMA>",
        output_last_message_path="<PRIVATE_FINAL_OUTPUT>",
        scratch_dir="<EMPTY_READ_ONLY_SCRATCH>",
    )
    sanitized_argv = list(argv)
    sanitized_argv[0] = "<CODEX_CLI_BINARY>"
    return {
        "schema_version": CONTROLLER_TRANSPORT_SCHEMA,
        "provider": "codex.cli",
        "cli_binary": codex_cli.CODEX_CLI_BINARY,
        "cli_version": codex_cli.CODEX_CLI_VERSION,
        "model": codex_cli.CODEX_CLI_MODEL,
        "reasoning_effort": codex_cli.CODEX_CLI_REASONING_EFFORT,
        "argv_policy": argv,
        "sanitized_argv_policy": sanitized_argv,
        "prompt_delivery": "stdin_only",
        "output_schema_artifact": "public/controller_output_schema.json",
        "output_last_message": "temporary_private_file",
        "working_directory": "fresh_empty_read_only_scratch",
        "tool_event_policy": "forbidden_fail_closed",
        "strict_json_schema": True,
        "event_audit": {"format": "jsonl", "complete": True},
    }


def _controller_liveness_artifact(result: CodexCLIResult) -> dict[str, object]:
    """Keep only score-blind sanitized liveness evidence in the bundle."""

    record = result.persistence_record()
    expected = {
        "final_json",
        "sanitized_argv",
        "cli_version",
        "validation_result",
        "tool_event_count",
    }
    if (
        set(record) != expected
        or record.get("final_json") != '{"liveness":"SYNTHETIC_OK"}'
        or record.get("cli_version") != codex_cli.CODEX_CLI_VERSION
        or record.get("validation_result")
        != {
            "event_stream": "valid",
            "final_json": "valid_json_object",
            "strict_output_schema": True,
        }
        or record.get("tool_event_count") != 0
        or not isinstance(record.get("sanitized_argv"), list)
    ):
        raise FoundationEpisodeError("Codex CLI liveness evidence is invalid")
    return {
        "schema_version": CONTROLLER_LIVENESS_SCHEMA,
        "score_blind": True,
        "target_values_seen": False,
        "passed": True,
        **record,
    }


def _runnable_stratum_counts(catalog: Mapping[str, object]) -> dict[str, int]:
    counts = dict.fromkeys(COVERAGE_STRATA, 0)
    operational = catalog.get("classifier_catalog")
    if not isinstance(operational, list):
        return counts
    for row in operational:
        if not isinstance(row, Mapping) or row.get("runnable") is not True:
            continue
        stratum = row.get("stratum")
        if isinstance(stratum, str) and stratum in counts:
            counts[stratum] += 1
    return counts


def _catalog_is_expected(catalog: Mapping[str, object]) -> bool:
    concepts = catalog.get("concept_count")
    source_reported = catalog.get("source_reported_count")
    operational = catalog.get("classifier_catalog")
    runnable = (
        sum(
            1
            for row in operational
            if isinstance(row, Mapping) and row.get("runnable") is True
        )
        if isinstance(operational, list)
        else -1
    )
    stratum_counts = _runnable_stratum_counts(catalog)
    return (
        concepts == 94
        and source_reported == 82
        and isinstance(operational, list)
        and len(operational) == 49
        and runnable == 21
        and all(count > 0 for count in stratum_counts.values())
    )


def run_preflight(request: FoundationPreflightRequest) -> FoundationPreflightResult:
    """Prepare a score-blind bundle and stop before authorization or discovery."""

    if not isinstance(request, FoundationPreflightRequest):
        raise FoundationEpisodeError("request must be a FoundationPreflightRequest")
    if request.seed != PARTITION_SEED:
        raise FoundationEpisodeError(
            f"preflight seed must equal frozen partition seed {PARTITION_SEED}"
        )
    output = Path(request.output_dir)
    if output.exists() or output.is_symlink():
        raise FoundationEpisodeError(
            "preflight output directory must not already exist"
        )
    subjects = _read_subject_ids(request.subject_ids_path)
    target_manifest = _read_liu_target_manifest(
        request.target_manifest_path,
        expected_target_table_path=request.target_table_path,
    )
    target_subjects, target_header = _read_target_table_subjects(
        request.target_table_path,
        expected_header=target_manifest["target_table_header"],
    )
    intersection_subjects = _read_ica_subject_intersection(
        request.subject_intersection_path,
        expected_target_table_path=request.target_table_path,
    )
    exchangeability_subjects, families = _read_exchangeability_identities(
        request.exchangeability_manifest_path
    )
    _validate_subject_sequence_closure(
        recovered_subjects=subjects,
        target_subjects=target_subjects,
        intersection_subjects=intersection_subjects,
        exchangeability_subjects=exchangeability_subjects,
    )
    term_names = _read_term_metadata(request.term_names_path, label="term names")
    term_prefixes = _read_term_metadata(
        request.term_prefixes_path, label="term prefixes"
    )
    term_path, term_manifest = _inspect_term_cache(
        request.term_cache_dir,
        subject_ids_path=request.subject_ids_path,
        subject_intersection_path=request.subject_intersection_path,
        generator_path=request.kernel_source_path.parent / "prepare_term_iu_cache.py",
    )
    metric_catalog = build_metric_catalog(
        [row["term_index"] for row in term_manifest["terms"]],
        metric_aliases=term_names,
        metric_families=term_prefixes,
    )
    catalog = sanitize_operational_catalog(_read_json_object(request.catalog_path))
    if not _catalog_is_expected(catalog):
        raise FoundationEpisodeError(
            "catalog must report 94 concepts, 82 source count, 49 operational entries, 21 runnable entries, and all coverage strata"
        )
    runnable_stratum_counts = _runnable_stratum_counts(catalog)
    kernel = _kernel_record(
        request.kernel_source_path,
        required_symbols=request.kernel_symbols,
        catalog=catalog,
    )
    _validate_metric_catalog_against_engine(
        kernel_source_path=request.kernel_source_path, metric_catalog=metric_catalog
    )
    plans = build_group_safe_split_plans(
        subject_ids=subjects, family_ids=families, seed=request.seed
    )
    gpu = _single_idle_gpu(check_timing="before_synthetic_probes")
    probes = _probe_fold_local_capability(
        term_path=term_path,
        plans=plans,
        kernel_source_path=request.kernel_source_path,
        seed=request.seed,
    )
    contract = build_episode_contract(seed=request.seed)
    environment = _environment_manifest()
    prompt = _controller_prompt_artifact(contract)
    controller_output_schema = controller_response_schema_for_slot_count(2)
    controller_transport = _controller_transport_artifact(contract)
    # This real CLI seam is synthetic and score-blind.  It completes before the
    # bundle directory is created, so a failed liveness probe cannot leave
    # authorization, state, receipt, or discovery artifacts behind.
    controller_liveness = _controller_liveness_artifact(
        run_score_blind_liveness_probe()
    )
    runtime_inputs = {
        "schema_version": "br.foundation_episode.runtime_inputs.v3",
        "term_cache_dir": str(
            _regular_directory(request.term_cache_dir, label="term cache").resolve()
        ),
        "subject_ids_path": str(
            _regular_file(request.subject_ids_path, label="subject list").resolve()
        ),
        "target_table_path": str(
            _regular_file(request.target_table_path, label="target table").resolve()
        ),
        "target_manifest_path": str(
            _regular_file(
                request.target_manifest_path, label="target manifest"
            ).resolve()
        ),
        "subject_intersection_path": str(
            _regular_file(
                request.subject_intersection_path, label="subject intersection"
            ).resolve()
        ),
        "exchangeability_manifest_path": str(
            _regular_file(
                request.exchangeability_manifest_path,
                label="exchangeability manifest",
            ).resolve()
        ),
        "kernel_source_path": str(
            _regular_file(request.kernel_source_path, label="engine source").resolve()
        ),
    }
    input_manifest = {
        "schema_version": INPUT_MANIFEST_SCHEMA,
        "subject_count": 326,
        "family_count": len(set(families)),
        "target_table_header": list(target_header),
        "target_table_header_verified": target_header
        == tuple(target_manifest["target_table_header"]),
        "target_subject_sequence_verified": True,
        "subject_intersection_sequence_verified": True,
        "exchangeability_subject_sequence_verified": True,
        "family_source": "exchangeability_manifest",
        "target_manifest": target_manifest,
        "runnable_stratum_counts": runnable_stratum_counts,
        "real_endpoint_selected": False,
        "real_endpoint_converted": False,
        "real_endpoint_used": False,
        "term_cache": term_manifest,
        "kernel": kernel,
    }
    row_order = term_manifest["row_order"]
    all_probes = probes.get("probes")
    probes_passed = (
        isinstance(all_probes, list)
        and len(all_probes) == 5
        and all(
            isinstance(row, Mapping) and row.get("passed") is True for row in all_probes
        )
    )
    capabilities = kernel.get("runnable_key_capabilities")
    capabilities_passed = (
        isinstance(capabilities, list)
        and len(capabilities) == 21
        and all(
            isinstance(row, Mapping) and row.get("passed") is True
            for row in capabilities
        )
    )
    launch_ready = bool(
        probes_passed
        and capabilities_passed
        and gpu["ready"]
        and row_order.get("subject_order_verified") is True
        and row_order.get("anchors_equal_after_removal") is True
        and controller_liveness["passed"] is True
        and (Path(__file__).resolve().parent / "runner.py").is_file()
    )
    phase = PHASE_AWAITING_DISCOVERY_AUTHORIZATION if launch_ready else "NOT_LAUNCHABLE"
    artifacts = {
        "episode_contract": "episode_contract.json",
        "input_manifest": "input_manifest.json",
        "private_split_plan": "private/split_plan.private.json",
        "public_split_plan": "public/split_plan.public.json",
        "sanitized_catalog": "public/sanitized_catalog.json",
        "metric_catalog": "public/metric_catalog.json",
        "controller_prompt": "public/controller_prompt.json",
        "controller_output_schema": "public/controller_output_schema.json",
        "controller_transport": "public/controller_transport.json",
        "controller_liveness": "private/controller_liveness.json",
        "timing_probe": "timing_probe.json",
        "environment_manifest": "environment_manifest.json",
        "runtime_inputs": "private/runtime_inputs.json",
        "authorization_template": "authorization.template.json",
        "preflight": "preflight.json",
    }
    preflight_record = {
        "schema_version": PREFLIGHT_SCHEMA,
        "episode_id": EPISODE_ID,
        "scope": DISCOVERY_SCOPE,
        "phase": phase,
        "preflight_only": True,
        "launch_ready": launch_ready,
        "term_count": 76,
        "subject_count": 326,
        "five_probes_passed": probes_passed,
        "controller_liveness_passed": controller_liveness["passed"],
        "runnable_stratum_counts": runnable_stratum_counts,
        "one_idle_gpu": gpu["ready"],
        "gpu_check_timing": gpu["check_timing"],
        "own_process_excluded_from_gpu_check": gpu["own_process_excluded"],
        "row_order_verified": row_order.get("subject_order_verified") is True
        and row_order.get("anchors_equal_after_removal") is True,
        "real_endpoint_selected": False,
        "real_endpoint_converted": False,
        "real_endpoint_used": False,
        "discovery_started": False,
        "confirmation": "NOT_GRANTED_REQUIRES_SEPARATE_AUTHORIZATION",
    }

    def write_bundle(staging: Path) -> None:
        _write_json(staging / artifacts["episode_contract"], contract)
        _write_json(staging / artifacts["input_manifest"], input_manifest)
        _write_json(
            staging / artifacts["private_split_plan"], plans.private_plan, mode=0o600
        )
        _write_json(staging / artifacts["public_split_plan"], plans.public_plan)
        _write_json(staging / artifacts["sanitized_catalog"], catalog)
        _write_json(staging / artifacts["metric_catalog"], metric_catalog)
        _write_json(staging / artifacts["controller_prompt"], prompt)
        _write_json(
            staging / artifacts["controller_output_schema"], controller_output_schema
        )
        _write_json(staging / artifacts["controller_transport"], controller_transport)
        _write_json(
            staging / artifacts["controller_liveness"], controller_liveness, mode=0o600
        )
        _write_json(staging / artifacts["timing_probe"], probes)
        _write_json(staging / artifacts["environment_manifest"], environment)
        _write_json(staging / artifacts["runtime_inputs"], runtime_inputs, mode=0o600)
        _write_json(
            staging / artifacts["authorization_template"], authorization_template()
        )
        _write_json(staging / artifacts["preflight"], preflight_record)

    _publish_preflight_bundle(output, write_bundle)
    return FoundationPreflightResult(
        phase=phase, artifacts=artifacts, launch_ready=launch_ready
    )


__all__ = [
    "ENGINE_DEPENDENCY_FILENAMES",
    "FIXED_ENGINE_SYMBOLS",
    "FoundationPreflightRequest",
    "FoundationPreflightResult",
    "_environment_manifest",
    "_inspect_term_cache",
    "_read_exchangeability_identities",
    "_read_ica_subject_intersection",
    "_read_liu_target_manifest",
    "_read_term_metadata",
    "_read_target_table_subjects",
    "_validate_subject_sequence_closure",
    "_validate_metric_catalog_against_engine",
    "run_preflight",
]
