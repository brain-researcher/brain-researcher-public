"""Utility helpers to parse OpenNeuro GLM FitLins specification artifacts."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


_SPEC_PATTERN = re.compile(
    r"^(?P<dataset>ds\d+)-(?P<task>.+?)_specs\.json$", re.IGNORECASE
)


@dataclass
class ContrastSpec:
    name: str
    condition_list: List[str]
    weights: List[float]
    test: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class TaskSpec:
    dataset_id: str
    task_name: str
    spec_path: Path
    bids_model_version: Optional[str] = None
    model_name: Optional[str] = None
    group_by: Optional[List[str]] = None
    subjects: List[str] = field(default_factory=list)
    task_metadata: Dict[str, object] = field(default_factory=dict)
    contrasts: List[ContrastSpec] = field(default_factory=list)
    extra_metadata: Dict[str, object] = field(default_factory=dict)
    fitlins_params: Dict[str, object] = field(default_factory=dict)
    auxiliary_resources: List[Path] = field(default_factory=list)


def discover_task_specs(statsmodel_root: Path) -> List[TaskSpec]:
    """Discover task specification bundles within the statsmodel directory."""

    statsmodel_root = Path(statsmodel_root)
    if not statsmodel_root.exists():
        logger.warning("Statsmodel directory missing: %s", statsmodel_root)
        return []

    task_specs: List[TaskSpec] = []

    for dataset_dir in sorted(p for p in statsmodel_root.iterdir() if p.is_dir()):
        for spec_path in sorted(dataset_dir.glob("*_specs.json")):
            match = _SPEC_PATTERN.match(spec_path.name)
            if not match:
                continue

            dataset_id = match.group("dataset")
            task_name = match.group("task")

            task_specs.append(
                _build_task_spec(
                    dataset_dir=dataset_dir,
                    dataset_id=dataset_id,
                    task_name=task_name,
                    spec_path=spec_path,
                )
            )

    return task_specs


def _build_task_spec(
    dataset_dir: Path,
    dataset_id: str,
    task_name: str,
    spec_path: Path,
) -> TaskSpec:
    """Load the various JSON files associated with a single task."""

    spec_data = _safe_load_json(spec_path) or {}

    bids_model_version = spec_data.get("BIDSModelVersion")
    model_name = spec_data.get("Name")
    nodes = spec_data.get("Nodes") or []
    group_by: Optional[List[str]] = None
    if nodes:
        first_node = nodes[0]
        if isinstance(first_node, dict):
            group_by = first_node.get("GroupBy")

    task_spec = TaskSpec(
        dataset_id=dataset_id,
        task_name=task_name,
        spec_path=spec_path,
        bids_model_version=bids_model_version,
        model_name=model_name,
        group_by=group_by,
        extra_metadata={
            k: v
            for k, v in spec_data.items()
            if k not in {"BIDSModelVersion", "Name", "Nodes", "Input"}
        },
        fitlins_params=_extract_fitlins_params(spec_data),
    )

    # Subjects (from *_subjects or spec Input field)
    subjects = spec_data.get("Input", {}).get("subject")
    subjects_json = dataset_dir / f"{dataset_id}-{task_name}_subjects.json"
    if subjects_json.exists():
        subjects_data = _safe_load_json(subjects_json) or {}
        subjects = subjects_data.get("Subjects", subjects)
        task_spec.auxiliary_resources.append(subjects_json)
    if isinstance(subjects, Iterable):
        task_spec.subjects = [str(sub) for sub in subjects if sub is not None]

    # Task metadata (basic details)
    basic_details = dataset_dir / f"{dataset_id}_basic-details.json"
    if basic_details.exists():
        details_data = _safe_load_json(basic_details) or {}
        tasks_meta = details_data.get("Tasks", {})
        task_spec.task_metadata = tasks_meta.get(task_name, {})
        task_spec.auxiliary_resources.append(basic_details)

    # Contrasts
    contrasts_json = dataset_dir / f"{dataset_id}-{task_name}_contrasts.json"
    if contrasts_json.exists():
        contrast_data = _safe_load_json(contrasts_json) or {}
        task_spec.contrasts = _parse_contrasts(contrast_data.get("Contrasts") or [])
        task_spec.auxiliary_resources.append(contrasts_json)

    return task_spec


def _parse_contrasts(items: Iterable[object]) -> List[ContrastSpec]:
    contrasts: List[ContrastSpec] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "")
        if not name:
            continue
        condition_list = [str(cond) for cond in item.get("ConditionList") or []]
        weights_raw = item.get("Weights") or []
        weights: List[float] = []
        for value in weights_raw:
            try:
                weights.append(float(value))
            except (TypeError, ValueError):
                logger.debug("Invalid weight %s in contrast %s", value, name)
        test = item.get("Test")
        metadata = {
            k: v
            for k, v in item.items()
            if k not in {"Name", "ConditionList", "Weights", "Test"}
        }
        contrasts.append(
            ContrastSpec(
                name=name,
                condition_list=condition_list,
                weights=weights,
                test=test,
                metadata=metadata,
            )
        )
    return contrasts


def _extract_fitlins_params(spec_data: Dict[str, object]) -> Dict[str, object]:
    """Extract FitLins parameters from a BIDS Stats Model spec."""
    params: Dict[str, object] = {}
    nodes = spec_data.get("Nodes") or []
    run_node = None
    for node in nodes:
        if isinstance(node, dict) and str(node.get("Level", "")).lower() == "run":
            run_node = node
            break
    if not run_node:
        return params

    instr = run_node.get("Transformations", {}).get("Instructions", [])
    for step in instr:
        if str(step.get("Name", "")).lower() == "convolve":
            params["hrf_model"] = step.get("Model")
            params["hrf_derivative"] = step.get("Derivative")
            params["hrf_dispersion"] = step.get("Dispersion")
            params["convolve_input"] = step.get("Input")
            break

    model_block = (
        run_node.get("Model", {}) if isinstance(run_node.get("Model"), dict) else {}
    )
    if model_block.get("Type"):
        params["model_type"] = model_block.get("Type")
    opts = (
        model_block.get("Options", {})
        if isinstance(model_block.get("Options"), dict)
        else {}
    )
    if opts:
        params["model_options"] = opts
        if "HighPassFilterCutoff" in opts:
            params["high_pass"] = opts.get("HighPassFilterCutoff")

    x_terms = model_block.get("X", [])
    confounds: List[str] = []
    if isinstance(x_terms, list):
        for term in x_terms:
            if not isinstance(term, str):
                continue
            lowered = term.lower()
            if lowered.startswith("trans_") or lowered.startswith("rot_"):
                confounds.append(term)
            elif "comp_cor" in lowered or "cosine" in lowered or "motion" in lowered:
                confounds.append(term)
    if confounds:
        params["confounds_terms"] = sorted(set(confounds))

    return params


def _safe_load_json(path: Path) -> Optional[Dict[str, object]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        logger.debug("Spec file missing: %s", path)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse JSON %s: %s", path, exc)
    return None
