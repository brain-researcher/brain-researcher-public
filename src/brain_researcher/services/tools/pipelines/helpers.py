"""Pipeline execution helpers with container-first approach.

These functions wrap pipeline parameter builders with container execution,
providing simple dict-based interfaces for tool execution.

Execution modes:
- Container (default): Uses Apptainer/Docker with proper bind mounts
- Wrapper (fallback): Direct host execution for dev/debug

Container images default to Neurodesk CVMFS paths but can be overridden
via environment variables (BR_FMRIPREP_IMAGE, BR_FITLINS_IMAGE, BR_QSIPREP_IMAGE).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from brain_researcher.services.tools.executors import (
    BindMount,
    ContainerExecutionError,
    ContainerRequest,
    run_container,
)
from brain_researcher.services.tools.pipelines.params import (  # FitLins; fMRIPrep; MRIQC; QSIPrep
    FitLinsParameters,
    FMRIPrepParameters,
    MRIQCParameters,
    QSIPrepParameters,
    build_fitlins_command,
    build_fitlins_env,
    build_fmriprep_command,
    build_fmriprep_env,
    build_mriqc_command,
    build_mriqc_env,
    build_qsiprep_command,
    build_qsiprep_env,
    fitlins_from_payload,
    fmriprep_from_payload,
    mriqc_from_payload,
    qsiprep_from_payload,
)

# Type alias for runtime
Runtime = Literal["docker", "apptainer", "wrapper"]

# Default container images with environment variable overrides
FMRIPREP_IMAGE = os.environ.get(
    "BR_FMRIPREP_IMAGE",
    "/cvmfs/neurodesk.ardc.edu.au/containers/fmriprep_24.0.0/fmriprep_24.0.0.sif",
)
FITLINS_IMAGE = os.environ.get(
    "BR_FITLINS_IMAGE",
    "/cvmfs/neurodesk.ardc.edu.au/containers/fitlins_0.11.0/fitlins_0.11.0.sif",
)
QSIPREP_IMAGE = os.environ.get(
    "BR_QSIPREP_IMAGE",
    "/cvmfs/neurodesk.ardc.edu.au/containers/qsiprep_0.21.4/qsiprep_0.21.4.sif",
)
MRIQC_IMAGE = os.environ.get(
    "BR_MRIQC_IMAGE",
    "/cvmfs/neurodesk.ardc.edu.au/containers/mriqc_24.0.0/mriqc_24.0.0.sif",
)


# ============================================================================
# Path remapping utilities
# ============================================================================


def _remap_command(cmd: list[str], path_map: dict[str, str]) -> list[str]:
    """Remap host paths to container paths in a command list.

    Args:
        cmd: Command list with host paths
        path_map: Mapping from host paths to container paths

    Returns:
        Command list with paths remapped to container paths
    """
    result = []
    for arg in cmd:
        # Check if this argument matches any host path
        remapped = path_map.get(arg)
        if remapped is not None:
            result.append(remapped)
        else:
            result.append(arg)
    return result


# ============================================================================
# fMRIPrep helpers
# ============================================================================


def run_fmriprep(
    params: FMRIPrepParameters,
    runtime: Runtime = "apptainer",
    image: str | None = None,
) -> dict[str, Any]:
    """Run fMRIPrep with the given parameters.

    Args:
        params: fMRIPrep parameters
        runtime: Execution mode - "apptainer", "docker", or "wrapper"
        image: Container image path (default: FMRIPREP_IMAGE)

    Returns:
        Dict with execution result including exit_code, stdout, stderr,
        command_host (host-path version), command_container (what actually ran)
    """
    # Validate paths
    Path(params.bids_dir).resolve(strict=True)
    Path(params.output_dir).parent.mkdir(parents=True, exist_ok=True)
    if params.work_dir:
        Path(params.work_dir).mkdir(parents=True, exist_ok=True)
    if params.fs_license_file:
        Path(params.fs_license_file).resolve(strict=True)
    if params.bids_filter_file:
        Path(params.bids_filter_file).resolve(strict=True)

    command = build_fmriprep_command(params)
    env = build_fmriprep_env(params)

    if runtime == "wrapper":
        # Direct host execution (dev/debug)
        request = ContainerRequest(
            runtime="wrapper",
            command=command,
            env=env,
        )
        result = run_container(request)
        result["command_host"] = command
        result["command_container"] = command
        result["command"] = command
        return result

    # Container execution with bind mounts
    mounts = [
        BindMount(host_path=params.bids_dir, container_path="/data", read_only=True),
        BindMount(host_path=params.output_dir, container_path="/out"),
    ]
    if params.work_dir:
        mounts.append(BindMount(host_path=params.work_dir, container_path="/work"))
    if params.fs_license_file:
        mounts.append(
            BindMount(
                host_path=params.fs_license_file,
                container_path="/opt/freesurfer/license.txt",
                read_only=True,
            )
        )
    if params.bids_filter_file:
        mounts.append(
            BindMount(
                host_path=params.bids_filter_file,
                container_path="/bids_filter.json",
                read_only=True,
            )
        )

    # Build container command with remapped paths using delegation pattern
    container_cmd = _build_fmriprep_container_cmd(params)

    container_env: dict[str, str] = {}
    if params.fs_license_file:
        container_env["FS_LICENSE"] = "/opt/freesurfer/license.txt"

    request = ContainerRequest(
        runtime=runtime,
        image=image or FMRIPREP_IMAGE,
        command=container_cmd,
        mounts=mounts,
        env=container_env,
    )

    result = run_container(request)
    result["command_host"] = command
    result["command_container"] = container_cmd
    result["command"] = container_cmd  # Default to what actually ran
    return result


def _build_fmriprep_container_cmd(params: FMRIPrepParameters) -> list[str]:
    """Build fMRIPrep command with container-remapped paths.

    Uses delegation pattern: gets full command from params.command() then
    remaps host paths to container paths. This ensures all parameters are
    included without manual duplication.
    """
    # Get full command with all parameters
    cmd = params.command(include_executable=True)

    # Build path mapping: host -> container
    path_map: dict[str, str] = {
        params.bids_dir: "/data",
        params.output_dir: "/out",
    }
    if params.work_dir:
        path_map[params.work_dir] = "/work"
    if params.fs_license_file:
        path_map[params.fs_license_file] = "/opt/freesurfer/license.txt"
    if params.bids_filter_file:
        path_map[params.bids_filter_file] = "/bids_filter.json"

    return _remap_command(cmd, path_map)


def run_fmriprep_from_dict(
    data: dict[str, object],
    runtime: Runtime = "apptainer",
) -> dict[str, Any]:
    """Run fMRIPrep from a dict payload.

    Args:
        data: Dict with fMRIPrep parameters (bids_dir, output_dir, etc.)
        runtime: Execution mode

    Returns:
        Dict with execution result
    """
    params = fmriprep_from_payload(data)
    return run_fmriprep(params, runtime=runtime)


# ============================================================================
# FitLins helpers
# ============================================================================


def _multiprocessing_semlock_available() -> bool:
    """Return True if multiprocessing SemLock primitives work in this environment."""
    try:
        import multiprocessing as mp

        mp.Lock()
        return True
    except Exception:
        return False


def _run_fitlins_linear(params: FitLinsParameters) -> dict[str, Any]:
    """Run FitLins in-process using Nipype's Linear plugin.

    Some environments disallow multiprocessing semaphore primitives (SemLock),
    causing FitLins' default MultiProc execution to fail. This runner avoids
    multiprocessing entirely and runs serially.
    """
    import json
    import os.path as op
    import re
    import time
    import warnings
    from copy import deepcopy
    from tempfile import mkdtemp

    import bids
    from bids.modeling import BIDSStatsModelsGraph
    from fitlins import __version__ as fitlins_version
    from fitlins.utils import bids as fub
    from fitlins.utils import config as fitlins_config
    from fitlins.viz.reports import build_report_dict, write_full_report
    from fitlins.workflows import init_fitlins_wf

    def _warn_redirect(message, category, filename, lineno, file=None, line=None):
        return None

    warnings.showwarning = _warn_redirect

    def _compile_patterns(values: tuple[str, ...]) -> list[object]:
        compiled: list[object] = []
        for item in values:
            if len(item) >= 2 and item[0] == "/" and item[-1] == "/":
                compiled.append(re.compile(item[1:-1]))
            else:
                compiled.append(item)
        return compiled

    bids_dir = str(Path(params.bids_dir).resolve(strict=True))
    output_dir = str(Path(params.output_dir).resolve())
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    model_path = params.model
    if model_path:
        candidate = Path(model_path)
        if not candidate.is_absolute():
            if candidate.exists():
                model_path = str(candidate.resolve())
            else:
                model_path = str((Path(params.bids_dir) / candidate).resolve())

    if not model_path or not op.exists(model_path):
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": f"Model spec not found: {model_path}",
            "fitlins_version": fitlins_version,
        }

    work_dir_path = (
        Path(mkdtemp()) if params.work_dir is None else Path(params.work_dir)
    )
    work_dir = str(work_dir_path.resolve())
    Path(work_dir).mkdir(parents=True, exist_ok=True)

    # Cache the BIDSLayout sqlite DB under work_dir/dbcache for reuse.
    database_path = Path(work_dir) / "dbcache"
    database_path.mkdir(parents=True, exist_ok=True)
    reset_database = not (database_path / "layout_index.sqlite").exists()

    ignore = _compile_patterns(params.ignore)
    force_index = _compile_patterns(params.force_index)
    drop_missing = "--drop-missing" in params.extra_args

    smoothing = params.smoothing
    if smoothing is not None and not isinstance(smoothing, str):
        smoothing = str(smoothing)

    derivatives = True
    if params.derivatives_dir:
        derivatives = [str(Path(params.derivatives_dir).resolve(strict=True))]

    indexer = bids.BIDSLayoutIndexer(ignore=ignore, force_index=force_index)
    layout = bids.BIDSLayout(
        bids_dir,
        derivatives=derivatives,
        database_path=database_path,
        reset_database=reset_database,
        indexer=indexer,
    )

    subject_list = None
    if params.participant_label:
        subject_list = fub.collect_participants(
            layout, participant_label=list(params.participant_label)
        )

    # Mirror FitLins' dataset_description.json behavior.
    fub.write_derivative_description(
        bids_dir,
        output_dir,
        {
            "bids_dir": bids_dir,
            "output_dir": output_dir,
            "analysis_level": params.analysis_level,
            "model": model_path,
            "derivatives": derivatives if derivatives is not True else None,
            "work_dir": work_dir,
            "space": params.space,
            "desc_label": params.desc,
            "smoothing": params.smoothing,
            "drift_model": params.drift_model,
            "estimator": params.estimator,
            "plugin": "Linear",
        },
    )

    with open(model_path) as fobj:
        model_dict = json.load(fobj)
    if not model_dict:
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": f"model_dict cannot be empty. Invalid model filepath {model_path}.",
            "fitlins_version": fitlins_version,
        }

    graph = BIDSStatsModelsGraph(layout, model_dict)

    fitlins_wf = init_fitlins_wf(
        str(database_path),
        output_dir,
        graph=graph,
        analysis_level=params.analysis_level,
        model=model_path,
        space=params.space,
        desc=params.desc,
        participants=subject_list,
        base_dir=work_dir,
        smoothing=smoothing,
        drop_missing=drop_missing,
        drift_model=params.drift_model,
        estimator=params.estimator or "nilearn",
        errorts=False,
    )
    fitlins_wf.config = deepcopy(fitlins_config.get_fitlins_config()._sections)
    fitlins_wf.config["execution"]["crashdump_dir"] = work_dir

    try:
        fitlins_wf.run(plugin="Linear")
    except Exception as exc:
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": f"FitLins failed (Linear): {exc}",
            "fitlins_version": fitlins_version,
        }

    # Write report (best-effort; shouldn't block success)
    try:
        run_context = {
            "version": fitlins_version,
            "command": "fitlins (Linear runner)",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        }
        selectors = {"desc": params.desc, "space": params.space}
        if subject_list is not None:
            selectors["subject"] = subject_list
        graph.load_collections(**selectors)
        report_dict = build_report_dict(params.output_dir, work_dir, graph)
        write_full_report(report_dict, run_context, params.output_dir)
    except Exception:
        pass

    return {
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "fitlins_version": fitlins_version,
    }


def _normalize_subject_label(value: str) -> str:
    text = str(value).strip()
    return text[4:] if text.startswith("sub-") else text


def _looks_like_confound_term(term: object) -> bool:
    if not isinstance(term, str):
        return False
    lowered = term.lower()
    prefixes = (
        "trans_",
        "rot_",
        "a_comp_cor",
        "t_comp_cor",
        "c_comp_cor",
        "w_comp_cor",
        "global_signal",
        "csf",
        "white_matter",
        "framewise_displacement",
        "dvars",
        "std_dvars",
        "cosine",
        "non_steady_state_outlier",
        "motion_outlier",
        "aroma_motion",
        "cardiac_signal_",
        "cardiac_retroicor_",
        "respiratory_signal_",
        "respiratory_retroicor_",
        "cardiorespiratory_sum_",
        "cardiorespiratory_diff_",
        "pupil_filtered_z",
        "pupil_derivative1_z",
        "pupil_tonic_z",
        "pupil_phasic_z",
        "pupil_blink_fraction",
    )
    return lowered.startswith(prefixes)


def _normalize_legacy_fitlins_model(model: dict[str, Any]) -> dict[str, Any]:
    if model.get("Nodes") or not model.get("Steps"):
        return model

    nodes: list[dict[str, Any]] = []
    for idx, step in enumerate(model.get("Steps", []), start=1):
        level = str(step.get("Level", "run")).title()
        model_block = dict(step.get("Model") or {})
        transformations = step.get("Transformations")
        if isinstance(transformations, list):
            transformations = {
                "Transformer": "pybids-transforms-v1",
                "Instructions": list(transformations),
            }
        elif transformations is None:
            transformations = {
                "Transformer": "pybids-transforms-v1",
                "Instructions": [],
            }
        else:
            transformations = dict(transformations)
            transformations.setdefault("Transformer", "pybids-transforms-v1")
            transformations.setdefault("Instructions", [])

        hrf_spec = model_block.pop("HRF", None)
        if isinstance(hrf_spec, dict):
            transformations.setdefault("Instructions", []).append(
                {
                    "Name": "Convolve",
                    "Model": hrf_spec.get("Model", "spm"),
                    "Input": hrf_spec.get("Variables") or ["trial_type.*"],
                    "Derivative": bool(hrf_spec.get("Derivative", False)),
                    "Dispersion": bool(hrf_spec.get("Dispersion", False)),
                }
            )

        node: dict[str, Any] = {
            "Level": level,
            "Name": step.get("Name") or f"{level.lower()}_{idx}",
            "Model": model_block or {"Type": "glm", "X": [1]},
        }
        if step.get("GroupBy") is not None:
            node["GroupBy"] = step.get("GroupBy")
        if transformations.get("Instructions"):
            node["Transformations"] = transformations
        if step.get("Contrasts") is not None:
            node["Contrasts"] = step.get("Contrasts")
        if step.get("DummyContrasts") is not None:
            node["DummyContrasts"] = step.get("DummyContrasts")
        nodes.append(node)

    normalized = dict(model)
    normalized.pop("Steps", None)
    normalized["BIDSModelVersion"] = normalized.get("BIDSModelVersion", "1.0.0")
    normalized["Nodes"] = nodes
    return normalized


def _ensure_fitlins_run_node(model: dict[str, Any]) -> dict[str, Any]:
    from brain_researcher.services.tools.fitlins_tool import _find_run_node

    run_node = _find_run_node(model)
    if run_node is None:
        raise ValueError("FitLins model missing run-level node")
    tx = run_node.setdefault(
        "Transformations", {"Transformer": "pybids-transforms-v1", "Instructions": []}
    )
    tx.setdefault("Transformer", "pybids-transforms-v1")
    tx.setdefault("Instructions", [])
    model_block = run_node.setdefault(
        "Model", {"Type": "glm", "X": [1, "trial_type.*"]}
    )
    model_block.setdefault("Type", "glm")
    x_terms = model_block.get("X")
    if not isinstance(x_terms, list):
        model_block["X"] = (
            [x_terms] if isinstance(x_terms, str) else [1, "trial_type.*"]
        )
    return run_node


def _prepare_fitlins_effective_model(params: FitLinsParameters) -> FitLinsParameters:
    if not params.model:
        return params
    if not any([params.hrf_model, params.include_confounds]):
        return params

    model_path = Path(params.model).resolve(strict=True)
    model = json.loads(model_path.read_text())
    model = _normalize_legacy_fitlins_model(model)
    run_node = _ensure_fitlins_run_node(model)

    from brain_researcher.services.tools.fitlins_tool import (
        _apply_hrf_variant,
        _find_convolve_idx,
        _validate_model,
    )

    instructions = run_node["Transformations"].setdefault("Instructions", [])
    convolve_idx = _find_convolve_idx(run_node)
    if convolve_idx is None:
        instructions.append(
            {
                "Name": "Convolve",
                "Model": "spm",
                "Input": ["trial_type.*"],
                "Derivative": False,
                "Dispersion": False,
            }
        )
        convolve_idx = len(instructions) - 1

    if params.hrf_model:
        if str(params.hrf_model).strip().lower() == "flobs":
            raise ValueError(
                "FLOBS is not supported in native FitLins execution; use the Nilearn path."
            )
        _apply_hrf_variant(run_node, convolve_idx, params.hrf_model)

    if params.include_confounds:
        model_block = run_node.setdefault(
            "Model", {"Type": "glm", "X": [1, "trial_type.*"]}
        )
        x_terms = model_block.get("X", [])
        if not isinstance(x_terms, list):
            x_terms = [x_terms] if isinstance(x_terms, str) else [1, "trial_type.*"]
        x_base = [term for term in x_terms if not _looks_like_confound_term(term)]
        model_block["X"] = x_base + list(dict.fromkeys(params.include_confounds))

    ok, message = _validate_model(model)
    if not ok:
        raise ValueError(f"Prepared FitLins model failed validation: {message}")

    staging_dir = Path(params.output_dir) / "_fitlins_native"
    staging_dir.mkdir(parents=True, exist_ok=True)
    effective_model_path = staging_dir / "effective_model.json"
    effective_model_path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    return replace(params, model=str(effective_model_path))


def _read_confounds_table(path: Path):
    import pandas as pd

    sep = "	" if path.suffix.lower() == ".tsv" else ","
    return pd.read_csv(path, sep=sep)


def _copytree_hardlink_or_copy(src: Path, dst: Path) -> None:
    def _link_or_copy(src_file: str, dst_file: str) -> None:
        try:
            os.link(src_file, dst_file)
        except OSError:
            shutil.copy2(src_file, dst_file)

    shutil.copytree(src, dst, copy_function=_link_or_copy, dirs_exist_ok=True)


def _candidate_native_confound_targets(
    derivatives_root: Path,
    participant_labels: tuple[str, ...],
) -> list[Path]:
    patterns = ["*_desc-confounds_timeseries.tsv", "*_desc-confounds_regressors.tsv"]
    candidates: list[Path] = []
    normalized_labels = {
        _normalize_subject_label(label) for label in participant_labels if label
    }
    for pattern in patterns:
        for candidate in derivatives_root.rglob(pattern):
            rel_parts = candidate.relative_to(derivatives_root).parts
            if normalized_labels:
                subjects_in_path = {
                    part[4:].split("_", 1)[0]
                    for part in rel_parts
                    if isinstance(part, str) and part.startswith("sub-")
                }
                if not subjects_in_path.intersection(normalized_labels):
                    continue
            candidates.append(candidate)
    return sorted(set(candidates))


def _resolve_native_confound_target(
    value: str,
    *,
    derivatives_root: Path,
) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve(strict=True)
    return (derivatives_root / candidate).resolve(strict=True)


def _infer_native_confound_target(
    *,
    derivatives_root: Path,
    participant_labels: tuple[str, ...],
    external_df,
) -> Path:
    candidates = _candidate_native_confound_targets(
        derivatives_root, participant_labels
    )
    if not candidates:
        raise ValueError(
            "No native derivative confounds TSVs were found for external confounds staging"
        )
    if len(candidates) == 1:
        return candidates[0]

    row_matched: list[Path] = []
    for candidate in candidates:
        candidate_df = _read_confounds_table(candidate)
        if len(candidate_df) == len(external_df):
            row_matched.append(candidate)
    if len(row_matched) == 1:
        return row_matched[0]

    raise ValueError(
        "confounds_file requires confounds_target_file unless native FitLins can infer a unique target confounds TSV"
    )


def _load_confounds_overlay_specs(
    confounds_map_file: Path,
    *,
    derivatives_root: Path,
) -> list[dict[str, Path]]:
    payload = json.loads(confounds_map_file.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "targets" in payload:
        raw_entries = payload["targets"]
    elif isinstance(payload, dict):
        raw_entries = [
            {"target": target, "confounds_file": source}
            for target, source in payload.items()
        ]
    elif isinstance(payload, list):
        raw_entries = payload
    else:
        raise ValueError("confounds_map_file must be a JSON object or list")

    specs: list[dict[str, Path]] = []
    for idx, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise ValueError(f"confounds_map_file entry {idx} must be an object")
        target_value = (
            entry.get("target")
            or entry.get("target_confounds_file")
            or entry.get("native_target")
        )
        source_value = (
            entry.get("confounds_file")
            or entry.get("source_confounds_file")
            or entry.get("external_confounds_file")
        )
        if not target_value or not source_value:
            raise ValueError(
                f"confounds_map_file entry {idx} must define target and confounds_file"
            )

        target_path = _resolve_native_confound_target(
            str(target_value),
            derivatives_root=derivatives_root,
        )
        source_path = Path(str(source_value))
        if source_path.is_absolute():
            source_path = source_path.resolve(strict=True)
        else:
            source_path = (confounds_map_file.parent / source_path).resolve(strict=True)
        specs.append({"target": target_path, "source": source_path})

    if not specs:
        raise ValueError("confounds_map_file did not define any overlays")

    target_keys = [str(spec["target"]) for spec in specs]
    if len(target_keys) != len(set(target_keys)):
        raise ValueError(
            "confounds_map_file must not contain duplicate target confounds files"
        )
    return specs


def _prepare_fitlins_external_confounds(params: FitLinsParameters) -> FitLinsParameters:
    if not params.confounds_file and not params.confounds_map_file:
        return params
    if params.confounds_file and params.confounds_map_file:
        raise ValueError(
            "Provide either confounds_file or confounds_map_file, not both"
        )
    if not params.derivatives_dir:
        raise ValueError(
            "confounds_file requires derivatives_dir for native FitLins execution"
        )

    derivatives_root = Path(params.derivatives_dir).resolve(strict=True)
    overlay_specs: list[dict[str, Path]] = []
    source_confounds_file: str | None = None
    source_confounds_map_file: str | None = None

    if params.confounds_map_file:
        confounds_map_path = Path(params.confounds_map_file).resolve(strict=True)
        overlay_specs = _load_confounds_overlay_specs(
            confounds_map_path,
            derivatives_root=derivatives_root,
        )
        source_confounds_map_file = str(confounds_map_path)
    else:
        confounds_path = Path(params.confounds_file).resolve(strict=True)
        external_df = _read_confounds_table(confounds_path)
        if params.confounds_target_file:
            target_path = _resolve_native_confound_target(
                params.confounds_target_file,
                derivatives_root=derivatives_root,
            )
        else:
            target_path = _infer_native_confound_target(
                derivatives_root=derivatives_root,
                participant_labels=tuple(params.participant_label),
                external_df=external_df,
            )
        overlay_specs = [{"target": target_path, "source": confounds_path}]
        source_confounds_file = str(confounds_path)

    overlay_root = Path(params.output_dir) / "_fitlins_native_derivatives"
    if overlay_root.exists():
        shutil.rmtree(overlay_root)
    overlay_root.mkdir(parents=True, exist_ok=True)

    dataset_description = derivatives_root / "dataset_description.json"
    if dataset_description.exists():
        shutil.copy2(dataset_description, overlay_root / "dataset_description.json")
    else:
        (overlay_root / "dataset_description.json").write_text(
            json.dumps(
                {
                    "Name": "fitlins-native-confounds-overlay",
                    "BIDSVersion": "1.4.0",
                    "DatasetType": "derivative",
                    "GeneratedBy": [{"Name": "brain_researcher"}],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    subjects_to_copy = {
        _normalize_subject_label(label) for label in params.participant_label if label
    }
    relative_targets: dict[Path, Path] = {}
    for spec in overlay_specs:
        try:
            relative_target = spec["target"].relative_to(derivatives_root)
        except ValueError as exc:
            raise ValueError(
                "confounds target file must live under derivatives_dir"
            ) from exc
        relative_targets[spec["target"]] = relative_target
        subjects_in_path = {
            part[4:].split("_", 1)[0]
            for part in relative_target.parts
            if isinstance(part, str) and part.startswith("sub-")
        }
        subjects_to_copy.update(subjects_in_path)

    if not subjects_to_copy:
        raise ValueError(
            "Unable to infer subject for confounds overlay; provide participant_label or confounds target files under subject directories"
        )

    for label in sorted(subjects_to_copy):
        src_dir = derivatives_root / f"sub-{label}"
        if not src_dir.exists():
            raise ValueError(
                f"Derivatives subject directory not found for native confounds staging: {src_dir}"
            )
        _copytree_hardlink_or_copy(src_dir, overlay_root / f"sub-{label}")

    overlay_entries: list[dict[str, Any]] = []
    for spec in overlay_specs:
        target_path = spec["target"]
        source_path = spec["source"]
        relative_target = relative_targets[target_path]
        original_df = _read_confounds_table(target_path)
        external_df = _read_confounds_table(source_path)
        if len(original_df) != len(external_df):
            raise ValueError(
                f"External confounds rows ({len(external_df)}) do not match native target rows ({len(original_df)}) for {target_path}"
            )

        overlay_target = overlay_root / relative_target
        overlay_target.parent.mkdir(parents=True, exist_ok=True)
        if overlay_target.exists():
            overlay_target.unlink()
        merged_df = original_df.copy()
        overwritten: list[str] = []
        added: list[str] = []
        for column in external_df.columns:
            if column in merged_df.columns:
                overwritten.append(column)
            else:
                added.append(column)
            merged_df[column] = external_df[column]
        merged_df.to_csv(overlay_target, sep="	", index=False)
        overlay_entries.append(
            {
                "source_confounds_file": str(source_path),
                "target_confounds_file": str(target_path),
                "overlay_confounds_file": str(overlay_target),
                "added_columns": added,
                "overwritten_columns": overwritten,
            }
        )

    metadata_path = overlay_root / "native_confounds_overlay.json"
    metadata_path.write_text(
        json.dumps(
            {
                "source_derivatives_dir": str(derivatives_root),
                "source_confounds_file": source_confounds_file,
                "source_confounds_map_file": source_confounds_map_file,
                "overlay_count": len(overlay_entries),
                "overlays": overlay_entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return replace(params, derivatives_dir=str(overlay_root))


def _prepare_fitlins_runtime_params(params: FitLinsParameters) -> FitLinsParameters:
    prepared = _prepare_fitlins_effective_model(params)
    prepared = _prepare_fitlins_external_confounds(prepared)
    return prepared


def run_fitlins(
    params: FitLinsParameters,
    runtime: Runtime = "apptainer",
    image: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run FitLins with the given parameters.

    Args:
        params: FitLins parameters
        runtime: Execution mode - "apptainer", "docker", or "wrapper"
        image: Container image path (default: FITLINS_IMAGE)
        dry_run: If True, validate inputs and return the command without executing.

    Returns:
        Dict with execution result including exit_code, stdout, stderr,
        command_host (host-path version), command_container (what actually ran)
    """
    Path(params.bids_dir).resolve(strict=True)
    Path(params.output_dir).mkdir(parents=True, exist_ok=True)
    if params.work_dir:
        Path(params.work_dir).mkdir(parents=True, exist_ok=True)

    prepared = _prepare_fitlins_runtime_params(params)
    Path(prepared.bids_dir).resolve(strict=True)
    Path(prepared.output_dir).mkdir(parents=True, exist_ok=True)
    if prepared.derivatives_dir:
        Path(prepared.derivatives_dir).resolve(strict=True)
    if prepared.work_dir:
        Path(prepared.work_dir).mkdir(parents=True, exist_ok=True)

    command = build_fitlins_command(prepared)
    env = build_fitlins_env(prepared)

    if dry_run:
        if runtime == "wrapper":
            return {
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "dry_run": True,
                "runtime": runtime,
                "image": image or FITLINS_IMAGE,
                "command_host": command,
                "command_container": command,
                "command": command,
            }

        mounts = [
            BindMount(
                host_path=prepared.bids_dir, container_path="/data", read_only=True
            ),
            BindMount(host_path=prepared.output_dir, container_path="/out"),
        ]
        if prepared.derivatives_dir:
            mounts.append(
                BindMount(
                    host_path=prepared.derivatives_dir,
                    container_path="/derivatives",
                    read_only=True,
                )
            )
        if prepared.work_dir:
            mounts.append(
                BindMount(host_path=prepared.work_dir, container_path="/work")
            )

        container_cmd = _build_fitlins_container_cmd(prepared)
        return {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "dry_run": True,
            "runtime": runtime,
            "image": image or FITLINS_IMAGE,
            "mounts": [
                {
                    "host_path": m.host_path,
                    "container_path": m.container_path,
                    "read_only": m.read_only,
                }
                for m in mounts
            ],
            "command_host": command,
            "command_container": container_cmd,
            "command": container_cmd,
        }

    if runtime == "wrapper":
        if not _multiprocessing_semlock_available():
            result = _run_fitlins_linear(prepared)
            result["command_host"] = command
            result["command_container"] = command
            result["command"] = command
            return result
        request = ContainerRequest(
            runtime="wrapper",
            command=command,
            env=env,
        )
        try:
            result = run_container(request)
        except (ContainerExecutionError, FileNotFoundError, OSError) as exc:
            fallback = _run_fitlins_linear(prepared)
            stderr_parts: list[str] = []
            if isinstance(exc, ContainerExecutionError):
                stderr_parts.extend([exc.stderr, exc.stdout])
            stderr_parts.append(str(exc))
            stderr_parts.append(str(fallback.get("stderr") or ""))
            stderr = "\n".join(part for part in stderr_parts if part)
            fallback["stderr"] = stderr
            fallback["command_host"] = command
            fallback["command_container"] = command
            fallback["command"] = command
            return fallback
        result["command_host"] = command
        result["command_container"] = command
        result["command"] = command
        return result

    mounts = [
        BindMount(host_path=prepared.bids_dir, container_path="/data", read_only=True),
        BindMount(host_path=prepared.output_dir, container_path="/out"),
    ]
    if prepared.derivatives_dir:
        mounts.append(
            BindMount(
                host_path=prepared.derivatives_dir,
                container_path="/derivatives",
                read_only=True,
            )
        )
    if prepared.work_dir:
        mounts.append(BindMount(host_path=prepared.work_dir, container_path="/work"))

    container_cmd = _build_fitlins_container_cmd(prepared)

    request = ContainerRequest(
        runtime=runtime,
        image=image or FITLINS_IMAGE,
        command=container_cmd,
        mounts=mounts,
        env=env,
    )

    result = run_container(request)
    result["command_host"] = command
    result["command_container"] = container_cmd
    result["command"] = container_cmd
    return result


def _build_fitlins_container_cmd(params: FitLinsParameters) -> list[str]:
    """Build FitLins command with container-remapped paths.

    Uses delegation pattern: gets full command from params.command() then
    remaps host paths to container paths. This ensures all parameters are
    included without manual duplication.
    """
    # Get full command with all parameters
    cmd = params.command(include_executable=True)

    # Build path mapping: host -> container
    path_map: dict[str, str] = {
        params.bids_dir: "/data",
        params.output_dir: "/out",
    }
    if params.derivatives_dir:
        path_map[params.derivatives_dir] = "/derivatives"
    if params.work_dir:
        path_map[params.work_dir] = "/work"

    return _remap_command(cmd, path_map)


def run_fitlins_from_dict(
    data: dict[str, Any],
    runtime: Runtime = "apptainer",
) -> dict[str, Any]:
    """Run FitLins from a dict payload.

    Args:
        data: Dict with FitLins parameters
        runtime: Execution mode

    Returns:
        Dict with execution result
    """
    params = fitlins_from_payload(data)
    return run_fitlins(
        params,
        runtime=runtime,
        image=data.get("image") or data.get("container_image") or None,
        dry_run=bool(data.get("dry_run", False)),
    )


# ============================================================================
# QSIPrep helpers
# ============================================================================


def run_qsiprep(
    params: QSIPrepParameters,
    runtime: Runtime = "apptainer",
    image: str | None = None,
) -> dict[str, Any]:
    """Run QSIPrep with the given parameters.

    Args:
        params: QSIPrep parameters
        runtime: Execution mode - "apptainer", "docker", or "wrapper"
        image: Container image path (default: QSIPREP_IMAGE)

    Returns:
        Dict with execution result including exit_code, stdout, stderr,
        command_host (host-path version), command_container (what actually ran)
    """
    # Validate paths
    Path(params.bids_dir).resolve(strict=True)
    Path(params.output_dir).parent.mkdir(parents=True, exist_ok=True)
    if params.work_dir:
        Path(params.work_dir).mkdir(parents=True, exist_ok=True)
    if params.fs_license_file:
        Path(params.fs_license_file).resolve(strict=True)
    if params.bids_filter_file:
        Path(params.bids_filter_file).resolve(strict=True)
    if params.eddy_config:
        Path(params.eddy_config).resolve(strict=True)

    command = build_qsiprep_command(params)
    env = build_qsiprep_env(params)

    if runtime == "wrapper":
        # Direct host execution (dev/debug)
        request = ContainerRequest(
            runtime="wrapper",
            command=command,
            env=env,
        )
        result = run_container(request)
        result["command_host"] = command
        result["command_container"] = command
        result["command"] = command
        return result

    # Container execution with bind mounts
    mounts = [
        BindMount(host_path=params.bids_dir, container_path="/data", read_only=True),
        BindMount(host_path=params.output_dir, container_path="/out"),
    ]
    if params.work_dir:
        mounts.append(BindMount(host_path=params.work_dir, container_path="/work"))
    if params.fs_license_file:
        mounts.append(
            BindMount(
                host_path=params.fs_license_file,
                container_path="/opt/freesurfer/license.txt",
                read_only=True,
            )
        )
    if params.bids_filter_file:
        mounts.append(
            BindMount(
                host_path=params.bids_filter_file,
                container_path="/bids_filter.json",
                read_only=True,
            )
        )
    if params.eddy_config:
        mounts.append(
            BindMount(
                host_path=params.eddy_config,
                container_path="/eddy_config.json",
                read_only=True,
            )
        )

    # Build container command with remapped paths using delegation pattern
    container_cmd = _build_qsiprep_container_cmd(params)

    container_env: dict[str, str] = {}
    if params.fs_license_file:
        container_env["FS_LICENSE"] = "/opt/freesurfer/license.txt"

    request = ContainerRequest(
        runtime=runtime,
        image=image or QSIPREP_IMAGE,
        command=container_cmd,
        mounts=mounts,
        env=container_env,
    )

    result = run_container(request)
    result["command_host"] = command
    result["command_container"] = container_cmd
    result["command"] = container_cmd  # Default to what actually ran
    return result


def _build_qsiprep_container_cmd(params: QSIPrepParameters) -> list[str]:
    """Build QSIPrep command with container-remapped paths.

    Uses delegation pattern: gets full command from params.command() then
    remaps host paths to container paths. This ensures all parameters are
    included without manual duplication.
    """
    # Get full command with all parameters
    cmd = params.command(include_executable=True)

    # Build path mapping: host -> container
    path_map: dict[str, str] = {
        params.bids_dir: "/data",
        params.output_dir: "/out",
    }
    if params.work_dir:
        path_map[params.work_dir] = "/work"
    if params.fs_license_file:
        path_map[params.fs_license_file] = "/opt/freesurfer/license.txt"
    if params.bids_filter_file:
        path_map[params.bids_filter_file] = "/bids_filter.json"
    if params.eddy_config:
        path_map[params.eddy_config] = "/eddy_config.json"

    return _remap_command(cmd, path_map)


def run_qsiprep_from_dict(
    data: dict[str, Any],
    runtime: Runtime = "apptainer",
) -> dict[str, Any]:
    """Run QSIPrep from a dict payload.

    Args:
        data: Dict with QSIPrep parameters
        runtime: Execution mode

    Returns:
        Dict with execution result
    """
    params = qsiprep_from_payload(data)
    return run_qsiprep(params, runtime=runtime)


# ============================================================================
# MRIQC helpers
# ============================================================================


def run_mriqc(
    params: MRIQCParameters,
    runtime: Runtime = "apptainer",
    image: str | None = None,
) -> dict[str, Any]:
    """Run MRIQC with the given parameters.

    Args:
        params: MRIQC parameters
        runtime: Execution mode - "apptainer", "docker", or "wrapper"
        image: Container image path (default: MRIQC_IMAGE)

    Returns:
        Dict with execution result including exit_code, stdout, stderr,
        command_host (host-path version), command_container (what actually ran)
    """
    # Validate paths
    Path(params.bids_dir).resolve(strict=True)
    Path(params.output_dir).parent.mkdir(parents=True, exist_ok=True)
    if params.work_dir:
        Path(params.work_dir).mkdir(parents=True, exist_ok=True)
    if params.bids_filter_file:
        Path(params.bids_filter_file).resolve(strict=True)

    command = build_mriqc_command(params)
    env = build_mriqc_env(params)

    if runtime == "wrapper":
        # Direct host execution (dev/debug)
        request = ContainerRequest(
            runtime="wrapper",
            command=command,
            env=env,
        )
        result = run_container(request)
        result["command_host"] = command
        result["command_container"] = command
        result["command"] = command
        return result

    # Container execution with bind mounts
    mounts = [
        BindMount(host_path=params.bids_dir, container_path="/data", read_only=True),
        BindMount(host_path=params.output_dir, container_path="/out"),
    ]
    if params.work_dir:
        mounts.append(BindMount(host_path=params.work_dir, container_path="/work"))
    if params.bids_filter_file:
        mounts.append(
            BindMount(
                host_path=params.bids_filter_file,
                container_path="/bids_filter.json",
                read_only=True,
            )
        )

    # Build container command with remapped paths using delegation pattern
    container_cmd = _build_mriqc_container_cmd(params)

    request = ContainerRequest(
        runtime=runtime,
        image=image or MRIQC_IMAGE,
        command=container_cmd,
        mounts=mounts,
        env=env,
    )

    result = run_container(request)
    result["command_host"] = command
    result["command_container"] = container_cmd
    result["command"] = container_cmd  # Default to what actually ran
    return result


def _build_mriqc_container_cmd(params: MRIQCParameters) -> list[str]:
    """Build MRIQC command with container-remapped paths.

    Uses delegation pattern: gets full command from params.command() then
    remaps host paths to container paths. This ensures all parameters are
    included without manual duplication.
    """
    # Get full command with all parameters
    cmd = params.command(include_executable=True)

    # Build path mapping: host -> container
    path_map: dict[str, str] = {
        params.bids_dir: "/data",
        params.output_dir: "/out",
    }
    if params.work_dir:
        path_map[params.work_dir] = "/work"
    if params.bids_filter_file:
        path_map[params.bids_filter_file] = "/bids_filter.json"

    return _remap_command(cmd, path_map)


def run_mriqc_from_dict(
    data: dict[str, Any],
    runtime: Runtime = "apptainer",
) -> dict[str, Any]:
    """Run MRIQC from a dict payload.

    Args:
        data: Dict with MRIQC parameters
        runtime: Execution mode

    Returns:
        Dict with execution result
    """
    params = mriqc_from_payload(data)
    return run_mriqc(params, runtime=runtime)


__all__ = [
    # fMRIPrep
    "run_fmriprep",
    "run_fmriprep_from_dict",
    # FitLins
    "run_fitlins",
    "run_fitlins_from_dict",
    # QSIPrep
    "run_qsiprep",
    "run_qsiprep_from_dict",
    # MRIQC
    "run_mriqc",
    "run_mriqc_from_dict",
    # Container images
    "FMRIPREP_IMAGE",
    "FITLINS_IMAGE",
    "QSIPREP_IMAGE",
    "MRIQC_IMAGE",
]
