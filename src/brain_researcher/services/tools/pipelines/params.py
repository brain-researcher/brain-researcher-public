"""Unified pipeline parameters for neuroimaging workflows.

All BIDS-Apps pipeline configs live here with consistent patterns:
- Frozen dataclasses for immutability
- Tuple normalization for list fields
- Separate command builder functions
- Payload conversion helpers

This module consolidates parameters from:
- neurocore/fmriprep.py (FMRIPrepParameters)
- neurocore/qsiprep.py (QSIPrepParameters)
- services/tools/pipelines/helpers.py (FitLinsConfig -> FitLinsParameters)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# =============================================================================
# Utility Functions
# =============================================================================

def _as_tuple(values: Iterable[str] | str | None) -> Tuple[str, ...]:
    """Normalize list/string to tuple."""
    if values is None:
        return ()
    if isinstance(values, str):
        value = values.strip()
        return (value,) if value else ()
    return tuple(str(v) for v in values if v is not None and str(v) != "")


def _coerce_int(value: Any, *, default: int | None = None) -> int | None:
    """Coerce value to int or return default."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, *, default: float | None = None) -> float | None:
    """Coerce value to float or return default."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# =============================================================================
# FitLins Parameters (NEW - migrated from FitLinsConfig)
# =============================================================================

@dataclass(frozen=True)
class FitLinsParameters:
    """Immutable FitLins configuration.

    Migrated from FitLinsConfig dataclass to follow the frozen dataclass
    pattern used by FMRIPrepParameters and QSIPrepParameters.
    """
    bids_dir: str
    output_dir: str
    analysis_level: str = "dataset"
    model: str | None = None
    derivatives_dir: str | None = None
    participant_label: Tuple[str, ...] = field(default_factory=tuple)
    exclude_participant: Tuple[str, ...] = field(default_factory=tuple)
    work_dir: str | None = None
    space: str | None = None
    desc: str | None = None
    # FitLins supports rich smoothing specs like "5:run:iso", so preserve the raw string.
    smoothing: str | None = None
    hrf_model: str | None = None
    drift_model: str | None = None
    drift_order: int | None = None
    include_confounds: Tuple[str, ...] = field(default_factory=tuple)
    confound_strategy: str | None = None
    confounds_file: str | None = None
    confounds_target_file: str | None = None
    confounds_map_file: str | None = None
    n_compcor: int | None = None
    auto_contrasts: bool | None = None
    estimator: str | None = None
    reports_only: bool = False
    write_graph: bool = False
    ignore: Tuple[str, ...] = field(default_factory=tuple)
    force_index: Tuple[str, ...] = field(default_factory=tuple)
    extra_args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "participant_label", _as_tuple(self.participant_label))
        object.__setattr__(self, "exclude_participant", _as_tuple(self.exclude_participant))
        object.__setattr__(self, "include_confounds", _as_tuple(self.include_confounds))
        object.__setattr__(self, "ignore", _as_tuple(self.ignore))
        object.__setattr__(self, "force_index", _as_tuple(self.force_index))
        object.__setattr__(self, "extra_args", _as_tuple(self.extra_args))

    def command(self, include_executable: bool = True) -> List[str]:
        """Build FitLins CLI command."""
        cmd: List[str] = []
        if include_executable:
            cmd.append("fitlins")

        cmd.extend([self.bids_dir, self.output_dir, self.analysis_level])

        if self.model:
            cmd.extend(["--model", self.model])
        if self.derivatives_dir:
            cmd.extend(["--derivatives", self.derivatives_dir])
        if self.participant_label:
            cmd.append("--participant-label")
            cmd.extend(list(self.participant_label))
        if self.work_dir:
            cmd.extend(["-w", self.work_dir])
        if self.space:
            cmd.extend(["--space", self.space])
        if self.desc:
            cmd.extend(["--desc-label", self.desc])
        if self.smoothing is not None:
            cmd.extend(["--smoothing", str(self.smoothing)])
        if self.drift_model:
            cmd.extend(["--drift-model", self.drift_model])
        if self.estimator:
            cmd.extend(["--estimator", self.estimator])
        if self.reports_only:
            cmd.append("--reports-only")
        for item in self.ignore:
            cmd.extend(["--ignore", item])
        for item in self.force_index:
            cmd.extend(["--force-index", item])
        cmd.extend(self.extra_args)
        return cmd

    def env(self) -> Dict[str, str]:
        """Return environment variables for FitLins execution."""
        env: Dict[str, str] = {}
        if self.work_dir:
            env["FITLINS_WORK_DIR"] = self.work_dir
        return env


def build_fitlins_command(params: FitLinsParameters, *, include_executable: bool = True) -> List[str]:
    """Build fitlins CLI command from parameters."""
    return params.command(include_executable=include_executable)


def build_fitlins_env(params: FitLinsParameters) -> Dict[str, str]:
    """Build FitLins environment variables."""
    return params.env()


def fitlins_from_payload(payload: Mapping[str, Any]) -> FitLinsParameters:
    """Create FitLinsParameters from dict payload."""
    def _seq(name: str) -> Sequence[str]:
        value = payload.get(name)
        if value is None:
            return ()
        if isinstance(value, (list, tuple, set)):
            return tuple(str(v) for v in value)
        return (str(value),)

    smoothing_value = payload.get("smoothing")
    smoothing = str(smoothing_value).strip() if smoothing_value is not None else None
    if smoothing == "":
        smoothing = None

    return FitLinsParameters(
        bids_dir=str(payload["bids_dir"]),
        output_dir=str(payload["output_dir"]),
        analysis_level=str(payload.get("analysis_level", "dataset")),
        model=payload.get("model") or None,
        derivatives_dir=payload.get("derivatives_dir") or payload.get("derivatives") or None,
        participant_label=_as_tuple(_seq("participant_label")),
        exclude_participant=_as_tuple(_seq("exclude_participant")),
        work_dir=payload.get("work_dir") or None,
        space=payload.get("space") or None,
        desc=payload.get("desc") or None,
        smoothing=smoothing,
        hrf_model=payload.get("hrf_model") or None,
        drift_model=payload.get("drift_model") or None,
        drift_order=_coerce_int(payload.get("drift_order")),
        include_confounds=_as_tuple(_seq("include_confounds")),
        confound_strategy=payload.get("confound_strategy") or None,
        confounds_file=payload.get("confounds_file") or None,
        confounds_target_file=payload.get("confounds_target_file") or None,
        confounds_map_file=payload.get("confounds_map_file") or None,
        n_compcor=_coerce_int(payload.get("n_compcor")),
        auto_contrasts=payload.get("auto_contrasts"),
        estimator=payload.get("estimator") or None,
        reports_only=bool(payload.get("reports_only", False)),
        write_graph=bool(payload.get("write_graph", False)),
        ignore=_as_tuple(_seq("ignore")),
        force_index=_as_tuple(_seq("force_index")),
        extra_args=_as_tuple(_seq("extra_args")),
    )


# =============================================================================
# fMRIPrep Parameters (MOVED from neurocore/fmriprep.py)
# =============================================================================

@dataclass(frozen=True)
class FMRIPrepParameters:
    """Normalised configuration for fMRIPrep command construction.

    The dataclass only contains serialisable data so both the LangGraph tools and
    MCP ToolHub can share validation/command-building logic without importing
    heavy execution dependencies.
    """
    bids_dir: str
    output_dir: str
    analysis_level: str = "participant"
    participant_label: Tuple[str, ...] = field(default_factory=tuple)
    work_dir: str | None = None
    fs_license_file: str | None = None
    output_spaces: Tuple[str, ...] = field(default_factory=tuple)
    skip_bids_validation: bool = False
    use_aroma: bool = False
    cifti_output: str | bool | None = None
    n_cpus: int | None = None
    omp_nthreads: int | None = None
    mem_mb: int | None = None
    low_mem: bool = False
    stop_on_first_crash: bool = False
    notrack: bool = True
    longitudinal: bool = False
    bids_filter_file: str | None = None
    verbose: int = 1
    skull_strip_t1w: str = "auto"
    skull_strip_fixed_seed: bool = False
    bold2t1w_init: str = "register"
    bold2t1w_dof: int = 6
    fd_spike_threshold: float = 0.5
    dvars_spike_threshold: float = 1.5
    me_output_echos: bool = False
    medial_surface_nan: bool = False
    dummy_scans: int | None = None
    use_syn_sdc: str | bool | None = None
    force_syn: bool = False
    extra_args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "participant_label", list(_as_tuple(self.participant_label))
        )
        object.__setattr__(self, "output_spaces", _as_tuple(self.output_spaces))
        object.__setattr__(self, "extra_args", _as_tuple(self.extra_args))

    def command(self, include_executable: bool = True) -> List[str]:
        """Render the CLI invocation list for fMRIPrep."""
        cmd: List[str] = []

        if include_executable:
            cmd.append("fmriprep")

        cmd.extend([self.bids_dir, self.output_dir, self.analysis_level])

        if self.participant_label:
            cmd.append("--participant-label")
            cmd.extend(list(self.participant_label))

        if self.work_dir:
            cmd.extend(["-w", self.work_dir])

        if self.fs_license_file is not None:
            cmd.extend(["--fs-license-file", self.fs_license_file])

        if self.output_spaces:
            cmd.append("--output-spaces")
            cmd.extend(list(self.output_spaces))

        if self.skip_bids_validation:
            cmd.append("--skip-bids-validation")

        if self.use_aroma:
            cmd.append("--use-aroma")

        if self.cifti_output is not None:
            if isinstance(self.cifti_output, bool):
                if self.cifti_output:
                    cmd.append("--cifti-output")
            else:
                cmd.extend(["--cifti-output", str(self.cifti_output)])

        if self.n_cpus is not None:
            cmd.extend(["--n-cpus", str(self.n_cpus)])

        if self.omp_nthreads is not None:
            cmd.extend(["--omp-nthreads", str(self.omp_nthreads)])

        if self.mem_mb is not None:
            cmd.extend(["--mem-mb", str(self.mem_mb)])

        if self.low_mem:
            cmd.append("--low-mem")

        if self.stop_on_first_crash:
            cmd.append("--stop-on-first-crash")

        if self.notrack:
            cmd.append("--notrack")

        if self.longitudinal:
            cmd.append("--longitudinal")

        if self.bids_filter_file:
            cmd.extend(["--bids-filter-file", self.bids_filter_file])

        if self.verbose and int(self.verbose) > 0:
            verbosity = max(1, int(self.verbose))
            cmd.append("-" + "v" * verbosity)

        cmd.extend(["--skull-strip-t1w", self.skull_strip_t1w])

        if self.skull_strip_fixed_seed:
            cmd.append("--skull-strip-fixed-seed")

        cmd.extend(["--bold2t1w-init", self.bold2t1w_init])
        cmd.extend(["--bold2t1w-dof", str(self.bold2t1w_dof)])

        cmd.extend(["--fd-spike-threshold", str(self.fd_spike_threshold)])
        cmd.extend(["--dvars-spike-threshold", str(self.dvars_spike_threshold)])

        if self.me_output_echos:
            cmd.append("--me-output-echos")

        if self.medial_surface_nan:
            cmd.append("--medial-surface-nan")

        if self.dummy_scans is not None:
            cmd.extend(["--dummy-scans", str(self.dummy_scans)])

        if isinstance(self.use_syn_sdc, bool):
            if self.use_syn_sdc:
                cmd.append("--use-syn-sdc")
        elif isinstance(self.use_syn_sdc, str) and self.use_syn_sdc:
            cmd.extend(["--use-syn-sdc", self.use_syn_sdc])

        if self.force_syn:
            cmd.append("--force-syn")

        if self.extra_args:
            cmd.extend(self.extra_args)

        return cmd

    def to_command_args(self) -> List[str]:
        """Backward-compatible alias for command()."""
        return self.command(include_executable=True)

    def env(self) -> Dict[str, str]:
        """Return environment variables required for execution."""
        env: Dict[str, str] = {}
        if self.fs_license_file:
            env["FS_LICENSE"] = self.fs_license_file
        return env


def build_fmriprep_command(params: FMRIPrepParameters, *, include_executable: bool = True) -> List[str]:
    """Convenience wrapper for callers that only need the command."""
    return params.command(include_executable=include_executable)


def build_fmriprep_env(params: FMRIPrepParameters) -> Dict[str, str]:
    """Convenience wrapper for environment construction."""
    return params.env()


def fmriprep_from_payload(payload: Mapping[str, Any]) -> FMRIPrepParameters:
    """Create a parameter object from a loosely typed payload (dict-like).

    This helper sanitises optional fields (e.g. participant labels coming in as
    a single string) to keep the dataclass immutable and predictable.
    """
    def _get_sequence(name: str) -> Sequence[str]:
        value = payload.get(name)
        if value is None:
            return ()
        if isinstance(value, (list, tuple, set)):
            return tuple(str(v) for v in value)
        return (str(value),)

    extra_args = payload.get("extra_args") or ()
    if isinstance(extra_args, (list, tuple, set)):
        extra_args = tuple(str(v) for v in extra_args)
    else:
        extra_args = (str(extra_args),)

    raw_cifti = payload.get("cifti_output")
    if isinstance(raw_cifti, bool):
        cifti_output = raw_cifti
    elif raw_cifti is None:
        cifti_output = None
    else:
        text_cifti = str(raw_cifti).strip()
        cifti_output = text_cifti if text_cifti else None

    raw_use_syn = payload.get("use_syn_sdc")
    if isinstance(raw_use_syn, bool):
        use_syn_sdc = raw_use_syn
    elif raw_use_syn is None:
        use_syn_sdc = None
    else:
        text_syn = str(raw_use_syn).strip()
        use_syn_sdc = text_syn if text_syn else None

    return FMRIPrepParameters(
        bids_dir=str(payload["bids_dir"]),
        output_dir=str(payload["output_dir"]),
        analysis_level=str(payload.get("analysis_level", "participant")),
        participant_label=_as_tuple(_get_sequence("participant_label")),
        work_dir=payload.get("work_dir") or None,
        fs_license_file=payload.get("fs_license_file") or payload.get("fs_license"),
        output_spaces=_as_tuple(_get_sequence("output_spaces")),
        skip_bids_validation=bool(payload.get("skip_bids_validation", False)),
        use_aroma=bool(payload.get("use_aroma", False)),
        cifti_output=cifti_output,
        n_cpus=_coerce_int(payload.get("n_cpus")),
        omp_nthreads=_coerce_int(payload.get("omp_nthreads")),
        mem_mb=_coerce_int(payload.get("mem_mb")),
        low_mem=bool(payload.get("low_mem", False)),
        stop_on_first_crash=bool(payload.get("stop_on_first_crash", False)),
        notrack=bool(payload.get("notrack", True)),
        longitudinal=bool(payload.get("longitudinal", False)),
        bids_filter_file=payload.get("bids_filter_file") or None,
        verbose=_coerce_int(payload.get("verbose"), default=1) or 1,
        skull_strip_t1w=str(payload.get("skull_strip_t1w", "auto")),
        skull_strip_fixed_seed=bool(payload.get("skull_strip_fixed_seed", False)),
        bold2t1w_init=str(payload.get("bold2t1w_init", "register")),
        bold2t1w_dof=_coerce_int(payload.get("bold2t1w_dof"), default=6) or 6,
        fd_spike_threshold=_coerce_float(payload.get("fd_spike_threshold"), default=0.5) or 0.5,
        dvars_spike_threshold=_coerce_float(payload.get("dvars_spike_threshold"), default=1.5) or 1.5,
        me_output_echos=bool(payload.get("me_output_echos", False)),
        medial_surface_nan=bool(payload.get("medial_surface_nan", False)),
        dummy_scans=_coerce_int(payload.get("dummy_scans")),
        use_syn_sdc=use_syn_sdc,
        force_syn=bool(payload.get("force_syn", False)),
        extra_args=_as_tuple(extra_args),
    )


# =============================================================================
# QSIPrep Parameters (MOVED from neurocore/qsiprep.py)
# =============================================================================

@dataclass(frozen=True)
class QSIPrepParameters:
    """Normalised configuration for QSIPrep invocation."""
    bids_dir: str
    output_dir: str
    analysis_level: str = "participant"
    participant_label: Tuple[str, ...] = field(default_factory=tuple)
    work_dir: str | None = None
    fs_license_file: str | None = None
    bids_filter_file: str | None = None
    denoise_method: str | None = "patch2self"
    distortion_correction: Any | None = None
    use_syn_sdc: bool = False
    hmc_model: str | None = "3dSHORE"
    eddy_config: str | None = None
    b0_threshold: float | None = 100.0
    output_resolution: str | None = None
    skip_bids_validation: bool = False
    impute_slice_threshold: float = 0.0
    skull_strip_template: str | None = "OASIS"
    skull_strip_fixed_seed: bool = False
    force_spatial_normalization: bool = True
    shoreline_iters: int | None = 2
    write_graph: bool = False
    n_cpus: int | None = None
    omp_nthreads: int | None = None
    mem_mb: int | None = None
    low_mem: bool = False
    notrack: bool = True
    resource_monitor: bool = False
    verbose: int = 1
    extra_args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "participant_label", _as_tuple(self.participant_label))
        object.__setattr__(self, "extra_args", _as_tuple(self.extra_args))
        distortion = getattr(self, "distortion_correction", None)
        distortion_value = getattr(distortion, "value", distortion)
        if distortion_value is not None and str(distortion_value).lower() != "none":
            object.__setattr__(self, "use_syn_sdc", True)

    def command(self, include_executable: bool = True) -> List[str]:
        """Build QSIPrep CLI command."""
        cmd: List[str] = []
        if include_executable:
            cmd.append("qsiprep")

        cmd.extend([self.bids_dir, self.output_dir, self.analysis_level])

        if self.participant_label:
            cmd.extend(["--participant-label", *self.participant_label])
        if self.work_dir:
            cmd.extend(["-w", self.work_dir])
        if self.fs_license_file:
            cmd.extend(["--fs-license-file", self.fs_license_file])
        if self.bids_filter_file:
            cmd.extend(["--bids-filter-file", self.bids_filter_file])
        if self.denoise_method:
            cmd.extend(["--denoise-method", self.denoise_method])
        if self.use_syn_sdc:
            cmd.append("--use-syn-sdc")
        if self.hmc_model:
            cmd.extend(["--hmc-model", self.hmc_model])
        if self.eddy_config:
            cmd.extend(["--eddy-config", self.eddy_config])
        if self.b0_threshold is not None:
            cmd.extend(["--b0-threshold", str(self.b0_threshold)])
        if self.output_resolution:
            cmd.extend(["--output-resolution", self.output_resolution])
        if self.skip_bids_validation:
            cmd.append("--skip-bids-validation")
        if self.impute_slice_threshold and self.impute_slice_threshold > 0:
            cmd.extend(["--impute-slice-threshold", str(self.impute_slice_threshold)])
        if self.skull_strip_template:
            cmd.extend(["--skull-strip-template", self.skull_strip_template])
        if self.skull_strip_fixed_seed:
            cmd.append("--skull-strip-fixed-seed")
        if self.force_spatial_normalization:
            cmd.append("--force-spatial-normalization")
        if self.shoreline_iters is not None:
            cmd.extend(["--shoreline-iters", str(self.shoreline_iters)])
        if self.write_graph:
            cmd.append("--write-graph")
        if self.n_cpus is not None:
            cmd.extend(["--n_cpus", str(self.n_cpus)])
        if self.omp_nthreads is not None:
            cmd.extend(["--omp-nthreads", str(self.omp_nthreads)])
        if self.mem_mb is not None:
            cmd.extend(["--mem_mb", str(self.mem_mb)])
        if self.low_mem:
            cmd.append("--low-mem")
        if self.notrack:
            cmd.append("--notrack")
        if self.resource_monitor:
            cmd.append("--resource-monitor")
        if self.verbose and int(self.verbose) > 0:
            cmd.append("-" + "v" * max(1, int(self.verbose)))
        if self.extra_args:
            cmd.extend(self.extra_args)

        return cmd

    def env(self) -> Dict[str, str]:
        """Return environment variables for QSIPrep execution."""
        if self.fs_license_file:
            return {"FS_LICENSE": self.fs_license_file}
        return {}


def build_qsiprep_command(params: QSIPrepParameters, *, include_executable: bool = True) -> List[str]:
    """Build qsiprep CLI command from parameters."""
    return params.command(include_executable=include_executable)


def build_qsiprep_env(params: QSIPrepParameters) -> Dict[str, str]:
    """Build QSIPrep environment variables."""
    return params.env()


def qsiprep_from_payload(payload: Mapping[str, Any]) -> QSIPrepParameters:
    """Create QSIPrepParameters from dict payload."""
    def _seq(name: str) -> Sequence[str]:
        value = payload.get(name)
        if value is None:
            return ()
        if isinstance(value, (list, tuple, set)):
            return tuple(str(v) for v in value)
        return (str(value),)

    extra_args = payload.get("extra_args") or ()
    if isinstance(extra_args, (list, tuple, set)):
        extra_args_tuple = tuple(str(v) for v in extra_args)
    else:
        extra_args_tuple = (str(extra_args),)

    use_syn_sdc = bool(payload.get("use_syn_sdc", False))
    distortion = payload.get("distortion_correction")
    if isinstance(distortion, str) and distortion.lower() != "none":
        use_syn_sdc = True

    return QSIPrepParameters(
        bids_dir=str(payload["bids_dir"]),
        output_dir=str(payload["output_dir"]),
        analysis_level=str(payload.get("analysis_level", "participant")),
        participant_label=_seq("participant_label"),
        work_dir=payload.get("work_dir") or None,
        fs_license_file=payload.get("fs_license_file") or payload.get("fs_license"),
        bids_filter_file=payload.get("bids_filter_file") or None,
        denoise_method=str(payload.get("denoise_method", "patch2self")) if payload.get("denoise_method") is not None else None,
        distortion_correction=payload.get("distortion_correction"),
        use_syn_sdc=use_syn_sdc,
        hmc_model=payload.get("hmc_model", "3dSHORE"),
        eddy_config=payload.get("eddy_config") or None,
        b0_threshold=_coerce_float(payload.get("b0_threshold"), default=100.0),
        output_resolution=payload.get("output_resolution") or None,
        skip_bids_validation=bool(payload.get("skip_bids_validation", False)),
        impute_slice_threshold=_coerce_float(payload.get("impute_slice_threshold"), default=0.0) or 0.0,
        skull_strip_template=payload.get("skull_strip_template", "OASIS"),
        skull_strip_fixed_seed=bool(payload.get("skull_strip_fixed_seed", False)),
        force_spatial_normalization=bool(payload.get("force_spatial_normalization", True)),
        shoreline_iters=_coerce_int(payload.get("shoreline_iters"), default=2),
        write_graph=bool(payload.get("write_graph", False)),
        n_cpus=_coerce_int(payload.get("n_cpus")),
        omp_nthreads=_coerce_int(payload.get("omp_nthreads")),
        mem_mb=_coerce_int(payload.get("mem_mb")),
        low_mem=bool(payload.get("low_mem", False)),
        notrack=bool(payload.get("notrack", True)),
        resource_monitor=bool(payload.get("resource_monitor", False)),
        verbose=_coerce_int(payload.get("verbose"), default=1) or 1,
        extra_args=extra_args_tuple,
    )


# =============================================================================
# MRIQC Parameters (MOVED from neurocore/mriqc.py)
# =============================================================================

@dataclass(frozen=True)
class MRIQCParameters:
    """Normalised configuration for MRIQC CLI invocation."""

    bids_dir: str
    output_dir: str
    analysis_level: str = "participant"
    participant_label: Tuple[str, ...] = field(default_factory=tuple)
    session_id: Tuple[str, ...] = field(default_factory=tuple)
    run_id: Tuple[str, ...] = field(default_factory=tuple)
    modalities: Tuple[str, ...] = field(default_factory=tuple)
    work_dir: str | None = None
    bids_filter_file: str | None = None
    dsname: str | None = None
    n_procs: int | None = None
    mem_gb: float | None = None
    float32: bool = False
    clean_workdir: bool = False
    verbose_reports: bool = False
    no_sub: bool = False
    random_seed: int | None = None
    extra_args: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "participant_label", _as_tuple(self.participant_label))
        object.__setattr__(self, "session_id", _as_tuple(self.session_id))
        object.__setattr__(self, "run_id", _as_tuple(self.run_id))
        object.__setattr__(self, "modalities", _as_tuple(self.modalities))
        object.__setattr__(self, "extra_args", _as_tuple(self.extra_args))

    def command(self, include_executable: bool = True) -> List[str]:
        """Build MRIQC CLI command."""
        cmd: List[str] = []
        if include_executable:
            cmd.append("mriqc")

        cmd.extend([self.bids_dir, self.output_dir, self.analysis_level])

        if self.participant_label:
            cmd.extend(["--participant-label", *self.participant_label])
        if self.session_id:
            cmd.extend(["--session-id", *self.session_id])
        if self.run_id:
            cmd.extend(["--run-id", *self.run_id])
        if self.modalities:
            cmd.extend(["--modalities", *self.modalities])
        if self.work_dir:
            cmd.extend(["-w", self.work_dir])
        if self.bids_filter_file:
            cmd.extend(["--bids-filter-file", self.bids_filter_file])
        if self.dsname:
            cmd.extend(["--dsname", self.dsname])
        if self.n_procs is not None:
            cmd.extend(["--n_procs", str(self.n_procs)])
        if self.mem_gb is not None:
            cmd.extend(["--mem_gb", str(self.mem_gb)])
        if self.float32:
            cmd.append("--float32")
        if self.clean_workdir:
            cmd.append("--clean-workdir")
        if self.verbose_reports:
            cmd.append("--verbose-reports")
        if self.no_sub:
            cmd.append("--no-sub")
        if self.random_seed is not None:
            cmd.extend(["--random-seed", str(self.random_seed)])
        if self.extra_args:
            cmd.extend(self.extra_args)

        return cmd

    def env(self) -> Dict[str, str]:
        """Return environment variables for MRIQC execution."""
        return {}


def build_mriqc_command(params: MRIQCParameters, *, include_executable: bool = True) -> List[str]:
    """Build mriqc CLI command from parameters."""
    return params.command(include_executable=include_executable)


def build_mriqc_env(params: MRIQCParameters) -> Dict[str, str]:
    """Build MRIQC environment variables."""
    return params.env()


def mriqc_from_payload(payload: Mapping[str, Any]) -> MRIQCParameters:
    """Create MRIQCParameters from dict payload."""
    def _seq(name: str) -> Sequence[str]:
        value = payload.get(name)
        if value is None:
            return ()
        if isinstance(value, (list, tuple, set)):
            return tuple(str(v) for v in value)
        return (str(value),)

    extra_args = payload.get("extra_args") or ()
    if isinstance(extra_args, (list, tuple, set)):
        extra_args_tuple = tuple(str(v) for v in extra_args)
    else:
        extra_args_tuple = (str(extra_args),)

    return MRIQCParameters(
        bids_dir=str(payload["bids_dir"]),
        output_dir=str(payload["output_dir"]),
        analysis_level=str(payload.get("analysis_level", "participant")),
        participant_label=_seq("participant_label"),
        session_id=_seq("session_id"),
        run_id=_seq("run_id"),
        modalities=_seq("modalities"),
        work_dir=payload.get("work_dir") or None,
        bids_filter_file=payload.get("bids_filter_file") or None,
        dsname=payload.get("dsname") or None,
        n_procs=_coerce_int(payload.get("n_procs")),
        mem_gb=_coerce_float(payload.get("mem_gb")),
        float32=bool(payload.get("float32", False)),
        clean_workdir=bool(payload.get("clean_workdir", False)),
        verbose_reports=bool(payload.get("verbose_reports", False)),
        no_sub=bool(payload.get("no_sub", False)),
        random_seed=_coerce_int(payload.get("random_seed")),
        extra_args=extra_args_tuple,
    )


__all__ = [
    # FitLins
    "FitLinsParameters",
    "build_fitlins_command",
    "build_fitlins_env",
    "fitlins_from_payload",
    # fMRIPrep
    "FMRIPrepParameters",
    "build_fmriprep_command",
    "build_fmriprep_env",
    "fmriprep_from_payload",
    # QSIPrep
    "QSIPrepParameters",
    "build_qsiprep_command",
    "build_qsiprep_env",
    "qsiprep_from_payload",
    # MRIQC
    "MRIQCParameters",
    "build_mriqc_command",
    "build_mriqc_env",
    "mriqc_from_payload",
]
