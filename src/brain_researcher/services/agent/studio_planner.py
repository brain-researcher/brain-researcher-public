"""Deterministic Studio notebook planning from retrieved tool candidates."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from brain_researcher.services.agent.planner.kg_utils import normalize_dataset_id
from brain_researcher.services.agent.studio_scaffold_registry import (
    load_studio_scaffold_registry,
)
from brain_researcher.services.tools.runtime_profiles import (
    normalize_runtime_package_name,
)

_NEURODESK_HINT_PATTERN = re.compile(
    r"\b(?:module\s+load|neurodesk|cat12|fsl|ants|mrtrix)\b"
)
_MODULE_LOAD_PATTERN = re.compile(r"module\s+load\s+([^\s;]+)")
_FMRI_QC_HINT_PATTERN = re.compile(
    r"\b(?:bold|fmri|fmriprep|confounds?|carpet|qc|quality control|motion)\b"
)
_GLM_HINT_PATTERN = re.compile(
    r"\b(?:glm|first[\s-]?level|design matrix|contrast|openneuro|events\.tsv|trial_type)\b"
)
_SUBJECT_HINT_PATTERN = re.compile(
    r"\bsub[-_]?([a-zA-Z0-9]+)\b|\bparticipant(?:[-_\s]?label)?(?:\s+|=)([a-zA-Z0-9]+)\b",
    re.IGNORECASE,
)
_TASK_HINT_PATTERN = re.compile(r"\btask[-_\s]?([a-zA-Z0-9]+)\b", re.IGNORECASE)
_SPACE_HINT_PATTERN = re.compile(
    r"\bspace[-_\s]?([a-zA-Z0-9]+)\b|\b(MNI[0-9A-Za-z]+)\b"
)
_TR_HINT_PATTERN = re.compile(r"\bTR\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
_BIDS_TOKEN_PATTERNS = {
    "subject": re.compile(r"(?:^|[_/])sub-([a-zA-Z0-9]+)"),
    "session": re.compile(r"(?:^|[_/])ses-([a-zA-Z0-9]+)"),
    "task": re.compile(r"_task-([a-zA-Z0-9]+)"),
    "space": re.compile(r"_space-([a-zA-Z0-9]+)"),
}
_GENERIC_NOTE_HINTS = {"markdown", "note", "summary", "research goal", "hypothesis"}
_TASK_STOPWORDS = {"run", "fmri", "bold", "analysis", "design", "matrix"}
_DEFAULT_SPACE = "MNI152NLin2009cAsym"


def _prompt_mentions_neurodesk_module_execution(prompt: str) -> bool:
    lowered = prompt.lower()
    return bool(_NEURODESK_HINT_PATTERN.search(lowered)) or any(
        token in prompt for token in ["模块", "运行 CAT12", "运行 FSL", "Neurodesk"]
    )


def _prompt_mentions_fmri_qc(prompt: str) -> bool:
    lowered = prompt.lower()
    return bool(_FMRI_QC_HINT_PATTERN.search(lowered)) or any(
        token in prompt for token in ["地毯图", "混杂", "运动参数", "质量控制", "BOLD"]
    )


def _prompt_mentions_glm_scaffold(prompt: str) -> bool:
    lowered = prompt.lower()
    return bool(_GLM_HINT_PATTERN.search(lowered)) or any(
        token in prompt for token in ["设计矩阵", "对比", "一阶 GLM", "一阶模型"]
    )


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _string_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, item in value.items():
        key_text = _coerce_text(key)
        item_text = _coerce_text(item)
        if key_text and item_text:
            out[key_text] = item_text
    return out


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _coerce_text(item)
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out


def _last_cell_id(notebook_context: Mapping[str, Any] | None) -> str | None:
    cells = list((notebook_context or {}).get("cells") or [])
    if not cells:
        return None
    last = cells[-1]
    if isinstance(last, Mapping):
        value = last.get("id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _append_markdown_and_code(
    *,
    markdown: str,
    code: str,
    last_cell_id: str | None,
    tool_id: str | None = None,
    source_tag: str = "studio_agent_deterministic",
) -> list[dict[str, Any]]:
    shared_metadata = {"source": source_tag}
    if tool_id:
        shared_metadata["tool_id"] = tool_id
    return [
        {
            "type": "append",
            "cell_type": "markdown",
            "source": markdown,
            "after_cell_id": last_cell_id,
            "metadata": dict(shared_metadata),
        },
        {
            "type": "append",
            "cell_type": "code",
            "source": code,
            "metadata": dict(shared_metadata),
        },
    ]


def _extract_module_loads(prompt: str) -> list[str]:
    matches = [
        match.strip() for match in _MODULE_LOAD_PATTERN.findall(prompt) if match.strip()
    ]
    if matches:
        return matches
    lowered = prompt.lower()
    if "cat12" in lowered or "spm12" in lowered:
        return ["cat12"]
    if "mrtrix" in lowered:
        return ["mrtrix3"]
    if "ants" in lowered:
        return ["ants"]
    if "fsl" in lowered:
        return ["fsl"]
    return []


def _infer_neurodesk_modules(prompt: str, tool_id: str | None) -> list[str]:
    explicit = _extract_module_loads(prompt)
    if explicit:
        return explicit
    if tool_id == "spm12_vbm":
        return ["cat12"]
    if tool_id == "fsl_bet":
        return ["fsl"]
    package_name = normalize_runtime_package_name(tool_id)
    return [package_name] if package_name else []


def _normalize_subject_label(value: Any) -> str | None:
    text = _coerce_text(value)
    if not text:
        return None
    if text.lower().startswith("sub-"):
        text = text[4:]
    return text or None


def _normalize_task_label(value: Any) -> str | None:
    text = _coerce_text(value)
    if not text:
        return None
    lowered = text.lower()
    if lowered in _TASK_STOPWORDS:
        return None
    if lowered.startswith("task-"):
        lowered = lowered[5:]
    return lowered or None


def _normalize_space_label(value: Any) -> str | None:
    text = _coerce_text(value)
    if not text:
        return None
    if text.lower().startswith("space-"):
        text = text[6:]
    return text or None


def _parse_subject_from_prompt(prompt: str) -> str | None:
    match = _SUBJECT_HINT_PATTERN.search(prompt)
    if not match:
        return None
    return _normalize_subject_label(
        next((item for item in match.groups() if item), None)
    )


def _parse_task_from_prompt(prompt: str) -> str | None:
    match = _TASK_HINT_PATTERN.search(prompt)
    if not match:
        return None
    return _normalize_task_label(match.group(1))


def _parse_space_from_prompt(prompt: str) -> str | None:
    match = _SPACE_HINT_PATTERN.search(prompt)
    if not match:
        return None
    return _normalize_space_label(next((item for item in match.groups() if item), None))


def _parse_tr_from_prompt(prompt: str) -> float | None:
    match = _TR_HINT_PATTERN.search(prompt)
    if not match:
        return None
    return _coerce_float(match.group(1))


def _parse_bids_tokens(path_like: str | None) -> dict[str, str]:
    path_text = _coerce_text(path_like)
    if not path_text:
        return {}
    tokens: dict[str, str] = {}
    for key, pattern in _BIDS_TOKEN_PATTERNS.items():
        match = pattern.search(path_text)
        if match:
            tokens[key] = match.group(1)
    return tokens


def _entity_values(query_understanding: Any, entity_type: str) -> list[str]:
    entities = _obj_get(query_understanding, "entities", [])
    if not isinstance(entities, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for entity in entities:
        if _coerce_text(_obj_get(entity, "entity_type")) != entity_type:
            continue
        value = _coerce_text(_obj_get(entity, "normalized_form")) or _coerce_text(
            _obj_get(entity, "text")
        )
        if entity_type == "task":
            value = _normalize_task_label(value)
        if not value or value in seen:
            continue
        values.append(value)
        seen.add(value)
    return values


def _dataset_metadata_values(dataset: Any, *keys: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    containers = [
        _obj_get(_obj_get(dataset, "resources"), "dataset_metadata", {}),
        _obj_get(dataset, "metadata", {}),
    ]
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        for key in keys:
            raw = container.get(key)
            if isinstance(raw, list):
                items = raw
            else:
                items = [raw]
            for item in items:
                text = _coerce_text(item)
                if key.startswith("task"):
                    text = _normalize_task_label(text)
                if not text or text in seen:
                    continue
                values.append(text)
                seen.add(text)
    return values


def _pick_primary_dataset(query_understanding: Any) -> Any | None:
    for collection_name in ("resolved_datasets", "candidate_datasets"):
        datasets = _obj_get(query_understanding, collection_name, [])
        if isinstance(datasets, list) and datasets:
            return datasets[0]
    return None


def _derivative_hits(query_understanding: Any) -> list[Any]:
    hits = _obj_get(query_understanding, "existing_derivatives", [])
    return hits if isinstance(hits, list) else []


def _clarification_answers(
    resolution_state: Mapping[str, Any] | None,
) -> dict[str, str]:
    state = dict(resolution_state or {})
    generic = state.get("generic_clarifications")
    answers = generic.get("answers") if isinstance(generic, Mapping) else []
    if not isinstance(answers, list):
        return {}
    out: dict[str, str] = {}
    for item in answers:
        if not isinstance(item, Mapping):
            continue
        answer = _coerce_text(item.get("answer"))
        clarification_key = _coerce_text(item.get("clarification_key"))
        question = _coerce_text(item.get("question"))
        if answer and clarification_key:
            out[clarification_key.lower()] = answer
        if answer and question:
            out[question.lower()] = answer
    return out


def _discover_subject_labels(*roots: str | None) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for root in roots:
        root_text = _coerce_text(root)
        if not root_text:
            continue
        path = Path(root_text)
        if not path.exists():
            continue
        for child in sorted(path.glob("sub-*")):
            if not child.is_dir():
                continue
            label = _normalize_subject_label(child.name)
            if label and label not in seen:
                labels.append(label)
                seen.add(label)
    return labels


def _discover_matching_path(root: str | None, patterns: Iterable[str]) -> str | None:
    root_text = _coerce_text(root)
    if not root_text:
        return None
    base = Path(root_text)
    if not base.exists():
        return None
    for pattern in patterns:
        try:
            for match in base.glob(pattern):
                if match.is_file():
                    return str(match)
        except OSError:
            continue
    return None


def _default_output_root(
    bids_root: str | None,
    notebook_context: Mapping[str, Any] | None,
    tool_id: str | None,
) -> str:
    root_name = tool_id or "studio"
    bids_root_text = _coerce_text(bids_root)
    if bids_root_text:
        return str(
            Path(bids_root_text) / "derivatives" / "brain_researcher" / root_name
        )
    notebook_path = _coerce_text((notebook_context or {}).get("notebook_path"))
    if notebook_path:
        return str(Path(notebook_path).resolve().parent / "outputs" / root_name)
    return str(Path("outputs") / root_name)


def _task_candidates(query_understanding: Any, dataset: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for value in _entity_values(query_understanding, "task"):
        if value not in seen:
            values.append(value)
            seen.add(value)
    for value in _dataset_metadata_values(dataset, "tasks", "task", "TaskName"):
        if value not in seen:
            values.append(value)
            seen.add(value)
    return values


def _choose_derivative_root(
    derivatives: Mapping[str, str],
    family_spec: Mapping[str, Any],
) -> str | None:
    preferences = family_spec.get("derivative_preferences")
    if isinstance(preferences, list):
        for family in preferences:
            family_text = _coerce_text(family)
            if family_text and derivatives.get(family_text):
                return derivatives[family_text]
    for candidate in derivatives.values():
        candidate_text = _coerce_text(candidate)
        if candidate_text:
            return candidate_text
    return None


def _resolved_paths(
    *,
    bids_root: str | None,
    derivative_root: str | None,
    output_root: str,
    subject_label: str,
    task: str | None,
    space: str,
    anat_suffix: str,
) -> dict[str, str]:
    session = None
    bold_path = None
    confounds_path = None
    events_path = None
    t1w_path = None

    if derivative_root:
        task_patterns = []
        if task:
            task_patterns.extend(
                [
                    f"sub-{subject_label}/**/*task-{task}*desc-preproc_bold.nii.gz",
                    f"sub-{subject_label}/**/*task-{task}*bold.nii.gz",
                ]
            )
        task_patterns.extend(
            [
                f"sub-{subject_label}/**/*desc-preproc_bold.nii.gz",
                f"sub-{subject_label}/**/*bold.nii.gz",
            ]
        )
        bold_path = _discover_matching_path(derivative_root, task_patterns)
        if bold_path:
            tokens = _parse_bids_tokens(bold_path)
            session = tokens.get("session")
            if not task:
                task = tokens.get("task")
            if tokens.get("space"):
                space = tokens["space"]

            bold_candidate = Path(bold_path)
            confounds_candidate = Path(
                str(bold_candidate).replace(
                    "desc-preproc_bold.nii.gz",
                    "desc-confounds_timeseries.tsv",
                )
            )
            if confounds_candidate.exists():
                confounds_path = str(confounds_candidate)

        t1w_path = _discover_matching_path(
            derivative_root,
            [
                f"sub-{subject_label}/**/*desc-preproc_{anat_suffix}.nii.gz",
                f"sub-{subject_label}/**/*{anat_suffix}.nii.gz",
            ],
        )

    if bids_root and not events_path:
        task_patterns = []
        if task:
            task_patterns.append(f"sub-{subject_label}/**/*task-{task}*_events.tsv")
        task_patterns.append(f"sub-{subject_label}/**/*_events.tsv")
        events_path = _discover_matching_path(bids_root, task_patterns)

    if bids_root and not t1w_path:
        t1w_path = _discover_matching_path(
            bids_root,
            [
                f"sub-{subject_label}/**/*_{anat_suffix}.nii.gz",
                f"sub-{subject_label}/**/*{anat_suffix}.nii.gz",
            ],
        )

    if bids_root and task and not events_path:
        func_dir = Path(bids_root) / f"sub-{subject_label}"
        if session:
            func_dir = func_dir / f"ses-{session}"
        func_dir = func_dir / "func"
        stem_parts = [f"sub-{subject_label}"]
        if session:
            stem_parts.append(f"ses-{session}")
        stem_parts.append(f"task-{task}")
        events_path = str(func_dir / ("_".join(stem_parts) + "_events.tsv"))

    if derivative_root and task and not bold_path:
        func_dir = Path(derivative_root) / f"sub-{subject_label}"
        if session:
            func_dir = func_dir / f"ses-{session}"
        func_dir = func_dir / "func"
        stem_parts = [f"sub-{subject_label}"]
        if session:
            stem_parts.append(f"ses-{session}")
        stem_parts.extend([f"task-{task}", f"space-{space}", "desc-preproc"])
        bold_path = str(func_dir / ("_".join(stem_parts) + "_bold.nii.gz"))
        confounds_path = str(
            func_dir / ("_".join(stem_parts[:-1]) + "_desc-confounds_timeseries.tsv")
        )

    if not t1w_path:
        anat_root = derivative_root or bids_root or output_root
        anat_dir = Path(anat_root) / f"sub-{subject_label}" / "anat"
        t1w_path = str(anat_dir / f"sub-{subject_label}_{anat_suffix}.nii.gz")

    return {
        "bold_path": bold_path or "",
        "confounds_path": confounds_path or "",
        "events_path": events_path or "",
        "t1w_path": t1w_path or "",
        "session_label": session or "",
    }


def _extract_resolved_params(
    *,
    prompt: str,
    notebook_context: Mapping[str, Any] | None,
    query_understanding: Any,
    resolution_state: Mapping[str, Any] | None,
    family_name: str,
    family_spec: Mapping[str, Any],
    tool_id: str | None,
) -> dict[str, Any]:
    dataset = _pick_primary_dataset(query_understanding)
    resources = _obj_get(dataset, "resources", None)

    dataset_id = normalize_dataset_id(_coerce_text(_obj_get(dataset, "dataset_id")))
    dataset_name = (
        _coerce_text(_obj_get(dataset, "display_name"))
        or _coerce_text(_obj_get(dataset, "name"))
        or _coerce_text(_obj_get(resources, "display_name"))
        or _coerce_text(_obj_get(resources, "dataset_name"))
    )
    source_repo = _coerce_text(_obj_get(dataset, "source_repo")) or _coerce_text(
        _obj_get(resources, "source_repo")
    )
    primary_url = _coerce_text(_obj_get(dataset, "primary_url"))
    bids_root = (
        _coerce_text(_obj_get(resources, "bids_path"))
        or _coerce_text(_obj_get(dataset, "bids_path"))
        or _coerce_text(_obj_get(dataset, "local_path"))
    )
    derivatives = _string_dict(_obj_get(resources, "derivatives", {}))
    for hit in _derivative_hits(query_understanding):
        kind = _coerce_text(_obj_get(hit, "kind"))
        path = _coerce_text(_obj_get(hit, "path"))
        if kind and path:
            derivatives.setdefault(kind, path)
    if bids_root:
        for family in ("fmriprep", "mriqc", "glmfitlins", "fitlins"):
            inferred = Path(bids_root) / "derivatives" / family
            if inferred.exists():
                derivatives.setdefault(family, str(inferred))

    derivative_root = _choose_derivative_root(derivatives, family_spec)
    defaults = family_spec.get("defaults") if isinstance(family_spec, Mapping) else {}
    if not isinstance(defaults, Mapping):
        defaults = {}

    answers = _clarification_answers(resolution_state)
    subject_label = (
        _parse_subject_from_prompt(prompt)
        or _normalize_subject_label(answers.get("participant_label"))
        or _normalize_subject_label(answers.get("subject"))
    )
    discovered_subjects = _discover_subject_labels(derivative_root, bids_root)
    subject_label = subject_label or (
        discovered_subjects[0] if discovered_subjects else "01"
    )

    task_candidates = _task_candidates(query_understanding, dataset)
    task = _parse_task_from_prompt(prompt) or (
        task_candidates[0] if len(task_candidates) == 1 else None
    )
    if not task and task_candidates:
        task = task_candidates[0]
    if not task:
        task = _normalize_task_label(answers.get("task"))
    if not task:
        task = _normalize_task_label(defaults.get("task"))

    space = (
        _parse_space_from_prompt(prompt)
        or _normalize_space_label(answers.get("space"))
        or _normalize_space_label(defaults.get("space"))
        or _DEFAULT_SPACE
    )
    t_r = _parse_tr_from_prompt(prompt) or _coerce_float(defaults.get("t_r")) or 2.0
    output_root = _default_output_root(bids_root, notebook_context, tool_id)
    anat_suffix = _coerce_text(defaults.get("anat_suffix")) or "T1w"
    paths = _resolved_paths(
        bids_root=bids_root,
        derivative_root=derivative_root,
        output_root=output_root,
        subject_label=subject_label,
        task=task,
        space=space,
        anat_suffix=anat_suffix,
    )
    path_tokens = _parse_bids_tokens(paths.get("bold_path"))
    if path_tokens.get("space"):
        space = path_tokens["space"]
    if path_tokens.get("task") and not task:
        task = path_tokens["task"]

    available_derivatives = _string_list(
        _obj_get(resources, "available_derivatives", [])
    )
    analysis_goal = _coerce_text(_obj_get(resources, "analysis_goal")) or family_name

    return {
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "source_repo": source_repo,
        "primary_url": primary_url,
        "bids_root": bids_root,
        "derivatives": derivatives,
        "available_derivatives": available_derivatives,
        "derivative_root": derivative_root,
        "participant_label": subject_label,
        "participant_labels": [f"sub-{label}" for label in discovered_subjects]
        or [f"sub-{subject_label}"],
        "task": task,
        "task_candidates": task_candidates,
        "space": space,
        "t_r": t_r,
        "analysis_goal": analysis_goal,
        "output_root": output_root,
        "atlas_path": _coerce_text(defaults.get("atlas_path"))
        or "data/atlas/atlas_labels.nii.gz",
        **paths,
    }


def _selected_tool_label(tool_id: str | None, params: Mapping[str, Any]) -> str:
    dataset_name = _coerce_text(params.get("dataset_name"))
    dataset_id = _coerce_text(params.get("dataset_id"))
    dataset_ref = dataset_name or dataset_id
    if tool_id and dataset_ref:
        return f"`{tool_id}` for `{dataset_ref}`"
    if tool_id:
        return f"`{tool_id}`"
    if dataset_ref:
        return f"`{dataset_ref}`"
    return "the current request"


def _infer_neurodesk_markdown(
    prompt: str,
    tool_id: str | None,
    module_loads: list[str],
    params: Mapping[str, Any],
) -> str:
    request = prompt.strip() or "Run a Neurodesk module-backed neuroimaging workflow."
    lines = [
        "## Neurodesk execution scaffold",
        "",
        f"- Request: {request}",
    ]
    if tool_id:
        lines.append(f"- Canonical tool: `{tool_id}`")
    if params.get("dataset_name") or params.get("dataset_id"):
        lines.append(f"- Grounded dataset: {_selected_tool_label(None, params)}")
    if params.get("t1w_path"):
        lines.append(f"- Grounded anatomical input: `{params['t1w_path']}`")
    if module_loads:
        lines.append(f"- Requested modules: {', '.join(module_loads)}")
    lines.extend(
        [
            "- Review the scaffolded command on the right before real execution.",
            "- Dataset and output paths are grounded from query understanding when available.",
        ]
    )
    return "\n".join(lines)


def _infer_neurodesk_code(
    prompt: str,
    tool_id: str | None,
    params: Mapping[str, Any],
) -> str:
    module_loads = _infer_neurodesk_modules(prompt, tool_id)
    module_lines = "\n".join(f"module load {item}" for item in module_loads) or (
        "# module load <replace-with-required-neurodesk-module>"
    )
    t1w_path = (
        _coerce_text(params.get("t1w_path")) or "data/sub-01/anat/sub-01_T1w.nii.gz"
    )
    output_root = _coerce_text(params.get("output_root")) or "outputs/neurodesk"
    if tool_id == "fsl_bet":
        output_image = str(
            Path(output_root)
            / f"sub-{params.get('participant_label', '01')}_desc-brain_T1w.nii.gz"
        )
        placeholder_command = f"bet {t1w_path} {output_image} -R"
    elif tool_id == "spm12_vbm":
        placeholder_command = f'echo "Run CAT12/SPM12 VBM on {t1w_path} and write outputs to {output_root}"'
    else:
        placeholder_command = 'echo "Replace this line with the real CLI command."'
    return "\n".join(
        [
            "from textwrap import dedent",
            "",
            "# Review this bash scaffold before executing real neuroimaging commands.",
            "shell_script = dedent(",
            '    """',
            "    source /etc/profile.d/lmod.sh 2>/dev/null || \\",
            "      source /usr/share/lmod/lmod/init/bash 2>/dev/null || true",
            f"    {module_lines}",
            f"    mkdir -p {output_root}",
            f"    {placeholder_command}",
            '    """',
            ").strip()",
            "",
            "print(shell_script)",
        ]
    )


def _infer_fmri_qc_markdown(prompt: str, params: Mapping[str, Any]) -> str:
    request = prompt.strip() or "Inspect a BOLD run with confounds and a carpet plot."
    return "\n".join(
        [
            "## fMRI QC scaffold",
            "",
            f"- Request: {request}",
            f"- BIDS root: `{params.get('bids_root') or 'data/bids_root'}`",
            f"- BOLD run: `{params.get('bold_path') or 'data/sub-01/func/sub-01_task-rest_desc-preproc_bold.nii.gz'}`",
            f"- Confounds: `{params.get('confounds_path') or 'data/sub-01/func/sub-01_task-rest_desc-confounds_timeseries.tsv'}`",
            "- Run the code cell to inspect motion/confounds and render a carpet plot.",
        ]
    )


def _infer_fmri_qc_code(params: Mapping[str, Any]) -> str:
    bold_path = (
        _coerce_text(params.get("bold_path"))
        or "data/sub-01/func/sub-01_task-rest_desc-preproc_bold.nii.gz"
    )
    confounds_path = (
        _coerce_text(params.get("confounds_path"))
        or "data/sub-01/func/sub-01_task-rest_desc-confounds_timeseries.tsv"
    )
    return "\n".join(
        [
            "from pathlib import Path",
            "",
            "import pandas as pd",
            "from nilearn import image, plotting",
            "",
            f"bold_path = Path({json.dumps(bold_path)})",
            f"confounds_path = Path({json.dumps(confounds_path)})",
            "",
            "img = image.load_img(str(bold_path))",
            "confounds = pd.read_csv(confounds_path, sep='\\t')",
            "",
            "qc_columns = [",
            "    column",
            "    for column in [",
            "        'framewise_displacement',",
            "        'trans_x', 'trans_y', 'trans_z',",
            "        'rot_x', 'rot_y', 'rot_z',",
            "    ]",
            "    if column in confounds.columns",
            "]",
            "",
            "print({'shape': img.shape, 'n_confounds': len(confounds.columns)})",
            "if qc_columns:",
            "    display(confounds[qc_columns].head())",
            "else:",
            "    print('No standard QC columns were found in the confounds table.')",
            "",
            "plotting.plot_carpet(img, title=bold_path.name)",
        ]
    )


def _infer_glm_markdown(prompt: str, params: Mapping[str, Any]) -> str:
    request = prompt.strip() or "Fit a first-level GLM for a task fMRI run."
    return "\n".join(
        [
            "## First-level GLM scaffold",
            "",
            f"- Request: {request}",
            f"- BIDS root: `{params.get('bids_root') or 'data/bids_root'}`",
            f"- Preprocessed BOLD: `{params.get('bold_path') or 'data/sub-01/func/sub-01_task-motor_desc-preproc_bold.nii.gz'}`",
            f"- Events: `{params.get('events_path') or 'data/sub-01/func/sub-01_task-motor_events.tsv'}`",
            f"- Confounds: `{params.get('confounds_path') or 'data/sub-01/func/sub-01_task-motor_desc-confounds_timeseries.tsv'}`",
            "- Review the grounded paths and TR, then adapt the contrast definition to your task.",
        ]
    )


def _infer_glm_code(params: Mapping[str, Any]) -> str:
    bold_path = (
        _coerce_text(params.get("bold_path"))
        or "data/sub-01/func/sub-01_task-motor_desc-preproc_bold.nii.gz"
    )
    events_path = (
        _coerce_text(params.get("events_path"))
        or "data/sub-01/func/sub-01_task-motor_events.tsv"
    )
    confounds_path = (
        _coerce_text(params.get("confounds_path"))
        or "data/sub-01/func/sub-01_task-motor_desc-confounds_timeseries.tsv"
    )
    t_r = _coerce_float(params.get("t_r")) or 2.0
    return "\n".join(
        [
            "from pathlib import Path",
            "",
            "import pandas as pd",
            "from nilearn import image, plotting",
            "from nilearn.glm.first_level import FirstLevelModel",
            "",
            f"bold_path = Path({json.dumps(bold_path)})",
            f"events_path = Path({json.dumps(events_path)})",
            f"confounds_path = Path({json.dumps(confounds_path)})",
            f"t_r = {t_r}",
            "",
            "img = image.load_img(str(bold_path))",
            "events = pd.read_csv(events_path, sep='\\t')",
            "confounds = pd.read_csv(confounds_path, sep='\\t')",
            "",
            "candidate_confounds = [",
            "    column",
            "    for column in [",
            "        'trans_x', 'trans_y', 'trans_z',",
            "        'rot_x', 'rot_y', 'rot_z',",
            "        'framewise_displacement',",
            "    ]",
            "    if column in confounds.columns",
            "]",
            "model = FirstLevelModel(t_r=t_r, hrf_model='glover', noise_model='ar1')",
            "model = model.fit(",
            "    img,",
            "    events=events,",
            "    confounds=confounds[candidate_confounds].fillna(0) if candidate_confounds else None,",
            ")",
            "",
            "design_matrix = model.design_matrices_[0]",
            "display(design_matrix.head())",
            "plotting.plot_design_matrix(design_matrix)",
            "",
            "if 'trial_type' in events.columns:",
            "    print('Available trial types:', sorted(events['trial_type'].dropna().unique()))",
        ]
    )


def _infer_fitlins_markdown(
    prompt: str,
    tool_id: str,
    params: Mapping[str, Any],
) -> str:
    request = prompt.strip() or "Draft a FitLins GLM recipe."
    title = (
        "FitLins multiverse scaffold"
        if tool_id == "glm_multiverse"
        else "FitLins recipe scaffold"
    )
    return "\n".join(
        [
            f"## {title}",
            "",
            f"- Request: {request}",
            f"- BIDS root: `{params.get('bids_root') or 'data/openneuro/ds000XXX'}`",
            f"- Derivatives path: `{params.get('derivative_root') or params.get('derivatives', {}).get('fmriprep') or 'data/openneuro/ds000XXX/derivatives/fmriprep'}`",
            f"- Model name: `{params.get('model_name')}`",
            "- Use the generated payload as a grounded starting point for a real FitLins run.",
        ]
    )


def _infer_fitlins_code(tool_id: str, params: Mapping[str, Any]) -> str:
    task = _coerce_text(params.get("task")) or "motor"
    model_name = (
        f"multiverse_{task}" if tool_id == "glm_multiverse" else f"first_level_{task}"
    )
    bids_root = _coerce_text(params.get("bids_root")) or "data/openneuro/ds000XXX"
    derivatives_path = (
        _coerce_text(params.get("derivative_root"))
        or _coerce_text(_obj_get(params.get("derivatives"), "fmriprep"))
        or "data/openneuro/ds000XXX/derivatives/fmriprep"
    )
    space = _coerce_text(params.get("space")) or _DEFAULT_SPACE
    return "\n".join(
        [
            "from pathlib import Path",
            "import json",
            "",
            "payload = {",
            f"    'tool_id': {json.dumps(tool_id)},",
            f"    'bids_root': {json.dumps(bids_root)},",
            f"    'derivatives_path': {json.dumps(derivatives_path)},",
            f"    'model_name': {json.dumps(model_name)},",
            f"    'space': {json.dumps(space)},",
            "    'smoothing_fwhm': 6.0,",
            "    'contrasts': ['task>baseline'],",
            "}",
            "",
            "print(json.dumps(payload, indent=2))",
        ]
    )


def _infer_bids_app(prompt: str, defaults: Mapping[str, Any]) -> str:
    lowered = prompt.lower()
    for app in ("fmriprep", "qsiprep", "mriqc", "fitlins"):
        if app in lowered:
            return app
    return _coerce_text(defaults.get("app_name")) or "fmriprep"


def _infer_bids_app_markdown(
    prompt: str,
    app_name: str,
    params: Mapping[str, Any],
) -> str:
    request = prompt.strip() or f"Draft a {app_name} BIDS App run."
    return "\n".join(
        [
            f"## {app_name} BIDS App scaffold",
            "",
            f"- Request: {request}",
            f"- BIDS root: `{params.get('bids_root') or 'data/bids_root'}`",
            f"- Output directory: `{params.get('output_dir')}`",
            f"- Participant label: `sub-{params.get('participant_label') or '01'}`",
            "- The code cell prints the grounded command so you can validate it before running the real job.",
        ]
    )


def _infer_bids_app_code(app_name: str, params: Mapping[str, Any]) -> str:
    bids_root = _coerce_text(params.get("bids_root")) or "data/bids_root"
    output_dir = _coerce_text(params.get("output_dir")) or str(
        Path("outputs") / app_name
    )
    participant_label = (
        _normalize_subject_label(params.get("participant_label")) or "01"
    )
    return "\n".join(
        [
            "from pathlib import Path",
            "",
            f"app_name = {json.dumps(app_name)}",
            f"bids_root = Path({json.dumps(bids_root)})",
            f"output_dir = Path({json.dumps(output_dir)})",
            f"participant_label = {json.dumps(participant_label)}",
            "",
            "command = [",
            "    app_name,",
            "    str(bids_root),",
            "    str(output_dir),",
            "    'participant',",
            "    '--participant-label',",
            "    participant_label,",
            "]",
            "",
            "print(' '.join(command))",
        ]
    )


def _infer_connectivity_markdown(
    prompt: str,
    tool_id: str,
    params: Mapping[str, Any],
) -> str:
    request = prompt.strip() or "Draft a connectivity analysis notebook."
    title = (
        "Resting-state connectome scaffold"
        if tool_id == "workflow_rest_connectome_e2e"
        else "Connectivity matrix scaffold"
    )
    primary_input = (
        params.get("bold_path")
        or params.get("timeseries_path")
        or "data/timeseries.npy"
    )
    return "\n".join(
        [
            f"## {title}",
            "",
            f"- Request: {request}",
            f"- Grounded input: `{primary_input}`",
            f"- Atlas: `{params.get('atlas_path') or 'data/atlas/atlas_labels.nii.gz'}`",
            "- Run the code cell to compute and inspect the connectivity matrix.",
        ]
    )


def _infer_connectivity_code(tool_id: str, params: Mapping[str, Any]) -> str:
    bold_path = _coerce_text(params.get("bold_path"))
    atlas_path = (
        _coerce_text(params.get("atlas_path")) or "data/atlas/atlas_labels.nii.gz"
    )
    timeseries_path = _coerce_text(params.get("timeseries_path")) or str(
        Path(_coerce_text(params.get("output_root")) or "outputs/connectivity")
        / "timeseries.npy"
    )
    if tool_id == "workflow_rest_connectome_e2e" and bold_path:
        return "\n".join(
            [
                "from pathlib import Path",
                "",
                "import numpy as np",
                "from nilearn.connectome import ConnectivityMeasure",
                "from nilearn.input_data import NiftiLabelsMasker",
                "",
                f"bold_path = Path({json.dumps(bold_path)})",
                f"atlas_path = Path({json.dumps(atlas_path)})",
                "",
                "masker = NiftiLabelsMasker(labels_img=str(atlas_path), standardize=True)",
                "timeseries = masker.fit_transform(str(bold_path))",
                "measure = ConnectivityMeasure(kind='correlation')",
                "matrix = measure.fit_transform([timeseries])[0]",
                "",
                "print({'shape': matrix.shape, 'mean': float(np.mean(matrix))})",
                "matrix[:5, :5]",
            ]
        )
    return "\n".join(
        [
            "from pathlib import Path",
            "",
            "import numpy as np",
            "from nilearn.connectome import ConnectivityMeasure",
            "",
            f"timeseries_path = Path({json.dumps(timeseries_path)})",
            "timeseries = np.load(timeseries_path)",
            "if timeseries.ndim != 2:",
            "    raise ValueError(f'Expected a 2D time x roi matrix, got {timeseries.shape}')",
            "",
            "measure = ConnectivityMeasure(kind='correlation')",
            "matrix = measure.fit_transform([timeseries])[0]",
            "",
            "print({'shape': matrix.shape, 'mean': float(np.mean(matrix))})",
            "matrix[:5, :5]",
        ]
    )


def _generic_markdown(prompt: str) -> str:
    lowered = prompt.lower()
    if "research goal" in lowered or "研究目标" in prompt:
        return f"## Research goal\n\n{prompt.strip()}"
    if "hypothesis" in lowered or "假设" in prompt:
        return f"## Hypothesis\n\n{prompt.strip()}"
    if any(token in lowered for token in ["summary", "note", "markdown"]):
        return f"## Note\n\n{prompt.strip() or 'Summarize the next analysis step.'}"
    return f"## Assistant note\n\n{prompt.strip()}"


def _generic_code(prompt: str) -> str:
    lowered = prompt.lower()
    if "print hello" in lowered or "打印hello" in prompt or "打印 hello" in prompt:
        return 'print("hello")'
    if "plot" in lowered or "绘图" in prompt or "画图" in prompt:
        return "\n".join(
            [
                "import matplotlib.pyplot as plt",
                "",
                "fig, ax = plt.subplots()",
                "ax.plot([0, 1, 2], [0, 1, 4])",
                "ax.set_title('Assistant draft plot')",
                "plt.show()",
            ]
        )
    if any(token in lowered for token in ["load", "read", "csv"]) or "读取" in prompt:
        return "\n".join(
            [
                "from pathlib import Path",
                "import pandas as pd",
                "",
                "data_path = Path('data.csv')",
                "df = pd.read_csv(data_path)",
                "df.head()",
            ]
        )
    return "\n".join(
        [
            "# Assistant draft",
            f"request = {json.dumps(prompt.strip(), ensure_ascii=False)}",
            "print('Drafted from request:')",
            "print(request)",
        ]
    )


def _select_candidate_tool_id(
    prompt: str,
    tool_candidates: list[dict[str, Any]],
) -> str | None:
    registry = load_studio_scaffold_registry()
    allowed_ids = set(registry.get("tool_to_family") or {})
    candidate_ids = [
        str(item.get("tool_id") or "").strip()
        for item in tool_candidates
        if isinstance(item, Mapping) and str(item.get("tool_id") or "").strip()
    ]
    if not candidate_ids:
        return None

    lowered = prompt.lower()
    if "fitlins" in lowered:
        for tool_id in ("run_fitlins_recipe", "glm_multiverse", "glm_first_level"):
            if tool_id in candidate_ids:
                return tool_id
    if "connect" in lowered or "rest" in lowered:
        for tool_id in ("workflow_rest_connectome_e2e", "connectivity_matrix"):
            if tool_id in candidate_ids:
                return tool_id
    for tool_id in candidate_ids:
        if tool_id in allowed_ids:
            return tool_id
    return candidate_ids[0]


def _select_scaffold_family(prompt: str, tool_id: str | None) -> str | None:
    registry = load_studio_scaffold_registry()
    tool_to_family = registry.get("tool_to_family") or {}
    if tool_id and tool_id in tool_to_family:
        return tool_to_family[tool_id]
    if _prompt_mentions_neurodesk_module_execution(prompt):
        return "neurodesk"
    if _prompt_mentions_glm_scaffold(prompt):
        return "glm_first_level"
    if _prompt_mentions_fmri_qc(prompt):
        return "fmri_qc"
    return None


def build_studio_plan(
    *,
    prompt: str,
    notebook_context: Mapping[str, Any] | None,
    tool_candidates: list[dict[str, Any]] | None,
    query_understanding: Any = None,
    resolution_state: Mapping[str, Any] | None = None,
    tool_candidate_diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic assistant_message + notebook ops for Studio."""

    del tool_candidate_diagnostics

    normalized_prompt = str(prompt or "").strip()
    last_cell_id = _last_cell_id(notebook_context)
    selected_tool_id = _select_candidate_tool_id(
        normalized_prompt,
        list(tool_candidates or []),
    )
    registry = load_studio_scaffold_registry()
    family_name = _select_scaffold_family(normalized_prompt, selected_tool_id)
    family_spec = (registry.get("families") or {}).get(family_name or "", {})
    params = _extract_resolved_params(
        prompt=normalized_prompt,
        notebook_context=notebook_context,
        query_understanding=query_understanding,
        resolution_state=resolution_state,
        family_name=family_name or "generic",
        family_spec=family_spec if isinstance(family_spec, Mapping) else {},
        tool_id=selected_tool_id,
    )

    if family_name == "neurodesk":
        assistant_message = (
            "Drafted a Neurodesk execution scaffold grounded from the retrieved tool "
            f"candidate {_selected_tool_label(selected_tool_id, params)}."
        )
        ops = _append_markdown_and_code(
            markdown=_infer_neurodesk_markdown(
                normalized_prompt,
                selected_tool_id,
                _infer_neurodesk_modules(normalized_prompt, selected_tool_id),
                params,
            ),
            code=_infer_neurodesk_code(normalized_prompt, selected_tool_id, params),
            last_cell_id=last_cell_id,
            tool_id=selected_tool_id,
        )
        return {"assistant_message": assistant_message, "ops": ops}

    if family_name == "bids_app":
        app_name = _infer_bids_app(normalized_prompt, family_spec.get("defaults", {}))
        params = {
            **params,
            "app_name": app_name,
            "output_dir": (
                str(Path(params["bids_root"]) / "derivatives" / app_name)
                if params.get("bids_root")
                else str(Path(params["output_root"]) / app_name)
            ),
        }
        assistant_message = (
            f"Drafted a {app_name} BIDS App scaffold grounded from "
            f"{_selected_tool_label(selected_tool_id, params)}."
        )
        ops = _append_markdown_and_code(
            markdown=_infer_bids_app_markdown(normalized_prompt, app_name, params),
            code=_infer_bids_app_code(app_name, params),
            last_cell_id=last_cell_id,
            tool_id=selected_tool_id,
        )
        return {"assistant_message": assistant_message, "ops": ops}

    if family_name == "glm_first_level":
        assistant_message = (
            "Drafted a first-level GLM scaffold with grounded dataset and derivatives "
            "paths from query understanding."
        )
        ops = _append_markdown_and_code(
            markdown=_infer_glm_markdown(normalized_prompt, params),
            code=_infer_glm_code(params),
            last_cell_id=last_cell_id,
            tool_id=selected_tool_id or "glm_first_level",
        )
        return {"assistant_message": assistant_message, "ops": ops}

    if family_name == "fitlins" and selected_tool_id:
        assistant_message = (
            "Drafted a FitLins scaffold with grounded BIDS and derivatives paths "
            "from query understanding."
        )
        ops = _append_markdown_and_code(
            markdown=_infer_fitlins_markdown(
                normalized_prompt, selected_tool_id, params
            ),
            code=_infer_fitlins_code(selected_tool_id, params),
            last_cell_id=last_cell_id,
            tool_id=selected_tool_id,
        )
        return {"assistant_message": assistant_message, "ops": ops}

    if family_name == "connectivity" and selected_tool_id:
        assistant_message = "Drafted a connectivity scaffold with grounded inputs from query understanding."
        ops = _append_markdown_and_code(
            markdown=_infer_connectivity_markdown(
                normalized_prompt, selected_tool_id, params
            ),
            code=_infer_connectivity_code(selected_tool_id, params),
            last_cell_id=last_cell_id,
            tool_id=selected_tool_id,
        )
        return {"assistant_message": assistant_message, "ops": ops}

    if family_name == "fmri_qc":
        assistant_message = (
            "Drafted an fMRI QC scaffold with grounded BOLD and confounds paths."
        )
        ops = _append_markdown_and_code(
            markdown=_infer_fmri_qc_markdown(normalized_prompt, params),
            code=_infer_fmri_qc_code(params),
            last_cell_id=last_cell_id,
            tool_id=selected_tool_id,
        )
        return {"assistant_message": assistant_message, "ops": ops}

    lowered = normalized_prompt.lower()
    if any(token in lowered for token in _GENERIC_NOTE_HINTS) or any(
        token in lowered for token in ["hello", "plot", "csv", "load", "read"]
    ):
        ops = [
            {
                "type": "append",
                "cell_type": "markdown",
                "source": _generic_markdown(normalized_prompt),
                "after_cell_id": last_cell_id,
                "metadata": {"source": "studio_agent_deterministic"},
            }
        ]
        if any(token in lowered for token in ["hello", "plot", "csv", "load", "read"]):
            ops.append(
                {
                    "type": "append",
                    "cell_type": "code",
                    "source": _generic_code(normalized_prompt),
                    "metadata": {"source": "studio_agent_deterministic"},
                }
            )
        return {
            "assistant_message": "Drafted deterministic notebook cells from your request.",
            "ops": ops,
        }

    return {
        "assistant_message": "I did not find a confident deterministic scaffold for that request yet.",
        "ops": [],
    }


__all__ = ["build_studio_plan"]
