"""Neurodesk execution compiler and tool-executor bridge.

Compiles Brain Researcher WorkflowSteps into Neurodesk-style shell scripts
(analysis_NN_tool.sh) that can be submitted via sbatch and executed in any
environment where Neurodesk/Lmod is available (local CVMFS, HPC, cloud VM).

Architecture:
  NeurodeskCompiler      -- WorkflowStep → NeurodeskExecutionPack + .sh file
  NeurodeskDispatcher    -- dispatch compiled pack: handoff | k8s | local
  NeurodeskToolExecutor  -- run_tool() bridge: compile → dispatch → return
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brain_researcher.services.shared.r2toolsagent_backend_specs import (
    JobSpecification,
    ResourceRequirements,
)
from brain_researcher.services.shared.workflow_models import WorkflowStep
from brain_researcher.services.tools.runtime_profiles import (
    get_neurodesk_command_template,
    get_neurodesk_package_profile,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global artifact index (persists across dispatcher instances / processes)
# ---------------------------------------------------------------------------

_GLOBAL_INDEX_ENV = "BR_NEURODESK_ARTIFACTS_DIR"
_REPO_ROOT = Path(__file__).resolve().parents[5]


def _global_artifact_index_path() -> Path:
    base = Path(
        os.environ.get(
            _GLOBAL_INDEX_ENV, str(_REPO_ROOT / "artifacts" / "neurodesk_dispatch")
        )
    )
    base.mkdir(parents=True, exist_ok=True)
    return base / "index.json"


def _load_global_index() -> list[dict[str, Any]]:
    path = _global_artifact_index_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")) or []
    except Exception:
        return []


def _save_global_index(index: list[dict[str, Any]]) -> None:
    path = _global_artifact_index_path()
    path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _upsert_global_index(record: dict[str, Any]) -> None:
    """Insert or update a record by artifact_id."""
    index = _load_global_index()
    artifact_id = record["artifact_id"]
    for i, entry in enumerate(index):
        if entry.get("artifact_id") == artifact_id:
            index[i] = {**entry, **record}
            _save_global_index(index)
            return
    index.append(record)
    _save_global_index(index)


def _find_in_global_index(artifact_id: str) -> dict[str, Any] | None:
    for entry in _load_global_index():
        if entry.get("artifact_id") == artifact_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# Resource defaults keyed by (tool_family, command_hint)
# ---------------------------------------------------------------------------

_RESOURCE_DEFAULTS: dict[str, ResourceRequirements] = {
    "fsl_heavy": ResourceRequirements(cpu=8, memory_gb=32, walltime_minutes=240),
    "fsl": ResourceRequirements(cpu=4, memory_gb=16, walltime_minutes=60),
    "ants": ResourceRequirements(cpu=8, memory_gb=32, walltime_minutes=120),
    "freesurfer": ResourceRequirements(cpu=4, memory_gb=32, walltime_minutes=720),
    "fmriprep": ResourceRequirements(cpu=16, memory_gb=64, walltime_minutes=480),
    "mriqc": ResourceRequirements(cpu=8, memory_gb=32, walltime_minutes=120),
    "mrtrix3": ResourceRequirements(cpu=8, memory_gb=32, walltime_minutes=120),
    "dcm2niix": ResourceRequirements(cpu=2, memory_gb=8, walltime_minutes=30),
    "default": ResourceRequirements(cpu=4, memory_gb=16, walltime_minutes=60),
}

_FSL_HEAVY_COMMANDS = frozenset({"feat", "melodic", "palm", "randomise", "fsl_anat"})

# Map tool_name prefixes / substrings to resource key
_TOOL_RESOURCE_KEY: list[tuple[str, str]] = [
    ("fmriprep", "fmriprep"),
    ("mriqc", "mriqc"),
    ("freesurfer", "freesurfer"),
    ("recon-all", "freesurfer"),
    ("mrtrix", "mrtrix3"),
    ("ants", "ants"),
    ("dcm2niix", "dcm2niix"),
    ("fsl", "fsl"),  # catch-all for fsl_* tools
]

# Map tool_name to Neurodesk package name (used by get_neurodesk_package_profile)
_TOOL_TO_PACKAGE: dict[str, str] = {
    "fsl_bet": "fsl",
    "fsl_flirt": "fsl",
    "fsl_fnirt": "fsl",
    "fsl_feat": "fsl",
    "fsl_palm": "fsl",
    "fsl_fix": "fsl",
    "fsl_bedpostx": "fsl",
    "fsl_command": "fsl",
    "ants": "ants",
    "ants_registration": "ants",
    "freesurfer": "freesurfer",
    "fmriprep": "fmriprep",
    "mriqc": "mriqc",
    "mrtrix3": "mrtrix3",
    "mrtrix3_command": "mrtrix3",
    "dcm2niix": "dcm2niix",
    "afni": "afni",
    "spm12": "spm12",
    "neurodesk_command": "fsl",  # generic, caller should override via metadata
}


def _resolve_package(tool_name: str, step_metadata: dict[str, Any]) -> str:
    """Determine the Neurodesk package name for a given tool."""
    # Explicit override in step metadata takes precedence
    if step_metadata.get("neurodesk_package"):
        return str(step_metadata["neurodesk_package"])
    # Exact match
    if tool_name in _TOOL_TO_PACKAGE:
        return _TOOL_TO_PACKAGE[tool_name]
    # Prefix / substring match
    lower = tool_name.lower()
    for prefix, pkg in _TOOL_TO_PACKAGE.items():
        if lower.startswith(prefix):
            return pkg
    return lower  # best-effort: use tool_name itself


def _infer_resource_defaults(tool_name: str, command: str) -> ResourceRequirements:
    """Return sensible ResourceRequirements for a given tool + command."""
    lower_tool = tool_name.lower()
    lower_cmd = (command or "").lower()

    if "fsl" in lower_tool and any(c in lower_cmd for c in _FSL_HEAVY_COMMANDS):
        return _RESOURCE_DEFAULTS["fsl_heavy"]

    for fragment, key in _TOOL_RESOURCE_KEY:
        if fragment in lower_tool or fragment in lower_cmd:
            return _RESOURCE_DEFAULTS[key]

    return _RESOURCE_DEFAULTS["default"]


def _minutes_to_slurm(minutes: int) -> str:
    """Convert walltime minutes to SLURM HH:MM:SS."""
    h, m = divmod(int(minutes), 60)
    return f"{h:02d}:{m:02d}:00"


def _safe_slug(text: str) -> str:
    """Turn an arbitrary string into a safe filename slug."""
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", text)
    return slug[:40].strip("_")


def _render_command_template(template: str, params: dict[str, Any]) -> list[str]:
    """Render a CLI command template string with the given parameter dict.

    Template syntax:
    - ``{param}`` — required positional; substituted with str(params[param]).
      Left as-is (removed in cleanup pass) if *param* is absent.
    - ``{-flag param}`` or ``{--long-flag param}`` — optional flag+value pair;
      emitted as ``-flag value`` only when *param* is present in *params*.
    - ``{param}`` tokens that remain unresolved are silently dropped.
    """
    result = template

    # Pass 1: resolve required {param} tokens
    for key, value in params.items():
        result = result.replace(f"{{{key}}}", str(value))

    # Pass 2: resolve optional {-flag param_name} or {--flag param_name} tokens
    def _replace_optional_flag(m: re.Match) -> str:
        flag = m.group(1)  # e.g. "-f" or "--fs-license-file"
        param_name = m.group(2)  # e.g. "fractional_intensity"
        if param_name in params:
            return f"{flag} {params[param_name]}"
        return ""

    result = re.sub(r"\{(--?[\w-]+)\s+([\w]+)\}", _replace_optional_flag, result)

    # Pass 3: drop any remaining unresolved {token} placeholders
    result = re.sub(r"\{[^}]+\}", "", result)

    # Collapse extra whitespace and tokenise
    result = re.sub(r"\s+", " ", result).strip()
    return shlex.split(result) if result else []


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class NeurodeskExecutionPack:
    """Compiled artifact from NeurodeskCompiler.compile()."""

    step_id: str
    script_path: Path  # absolute path to the written .sh file
    script_text: str  # full text (for tests / logging)
    job_name: str
    module_spec: str  # e.g. "fsl/6.0.7.18"
    resources: ResourceRequirements
    expected_outputs: list[str] = field(default_factory=list)
    env_overrides: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class NeurodeskCompiler:
    """Compile a WorkflowStep into a Neurodesk-style sbatch shell script.

    Args:
        run_dir: Base directory; scripts go to run_dir/scripts/, logs to
                 run_dir/logs/, outputs to run_dir/outputs/.
        conda_env_name: Name of the conda env to activate for Python steps.
        cluster_config: Optional cluster-specific overrides (partition, account, qos).
        command_builder: Optional callable(step) → list[str].  When provided,
                         used instead of the default parameter-to-command mapping.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        conda_env_name: str = "brain_researcher",
        cluster_config: dict[str, Any] | None = None,
        command_builder: Callable[[WorkflowStep], list[str]] | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.conda_env_name = conda_env_name
        self.cluster_config: dict[str, Any] = cluster_config or {}
        self.command_builder = command_builder

        self.scripts_dir = self.run_dir / "scripts"
        self.logs_dir = self.run_dir / "logs"
        self.outputs_dir = self.run_dir / "outputs"

        for d in (self.scripts_dir, self.logs_dir, self.outputs_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(self, step: WorkflowStep, *, step_index: int) -> NeurodeskExecutionPack:
        """Compile *step* into a shell script and return its execution pack."""
        meta = step.metadata if isinstance(step.metadata, dict) else {}

        # --- Resolve Neurodesk package + module spec ----------------------
        package = _resolve_package(step.tool_name, meta)
        profile = get_neurodesk_package_profile(package) or {}
        mod_name = profile.get("module_name", package)
        version = profile.get("version", "")
        module_spec = f"{mod_name}/{version}" if version else mod_name
        env_overrides: dict[str, str] = dict(profile.get("env", {}))

        # Allow per-step overrides
        if meta.get("module_spec"):
            module_spec = str(meta["module_spec"])
        env_overrides.update(meta.get("env_overrides", {}))

        # --- Resource requirements -----------------------------------------
        cli_command = meta.get("cli_command", "")
        resources_raw = meta.get("resources")
        if isinstance(resources_raw, dict):
            resources = ResourceRequirements(**resources_raw)
        elif isinstance(resources_raw, ResourceRequirements):
            resources = resources_raw
        else:
            resources = _infer_resource_defaults(step.tool_name, cli_command)

        # --- Names & paths ------------------------------------------------
        tool_slug = _safe_slug(step.tool_name)
        job_name = f"br-{step_index:02d}-{tool_slug}"
        script_filename = f"analysis_{step_index:02d}_{tool_slug}.sh"
        script_path = self.scripts_dir / script_filename

        # --- Step kind: cli_tool or python_wrapper ------------------------
        runtime_kind = meta.get("runtime_kind", "neurodesk")
        step_kind = "python_wrapper" if runtime_kind == "python" else "cli_tool"

        # --- Build CLI / python command ------------------------------------
        if self.command_builder:
            command_tokens = self.command_builder(step)
        elif meta.get("cli_command"):
            command_tokens = shlex.split(str(meta["cli_command"]))
        else:
            command_tokens = self._default_command(step, step_kind)

        # --- Detect expected outputs --------------------------------------
        expected_outputs = self._detect_expected_outputs(step)

        # --- Assemble script ----------------------------------------------
        script_text = self._render_script(
            job_name=job_name,
            module_spec=module_spec,
            resources=resources,
            env_overrides=env_overrides,
            step_kind=step_kind,
            command_tokens=command_tokens,
            work_dir=str(self.run_dir / "work"),
        )

        # Write and make executable
        script_path.write_text(script_text)
        script_path.chmod(
            script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
        )

        logger.info(
            "NeurodeskCompiler: compiled step=%s → %s (module=%s)",
            step.step_id,
            script_path.name,
            module_spec,
        )

        return NeurodeskExecutionPack(
            step_id=step.step_id,
            script_path=script_path,
            script_text=script_text,
            job_name=job_name,
            module_spec=module_spec,
            resources=resources,
            expected_outputs=expected_outputs,
            env_overrides=env_overrides,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_script(
        self,
        *,
        job_name: str,
        module_spec: str,
        resources: ResourceRequirements,
        env_overrides: dict[str, str],
        step_kind: str,
        command_tokens: list[str],
        work_dir: str,
    ) -> str:
        lines: list[str] = []

        # Shebang
        lines.append("#!/bin/bash")

        # SBATCH header
        lines += self._build_sbatch_header(job_name, resources)
        lines.append("")

        # Working directory
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        lines.append(f"cd {shlex.quote(work_dir)}")
        lines.append("")

        # Lmod init (multiple fallback paths)
        lines.append("# Initialize Lmod module system")
        lines.append(
            "source /etc/profile.d/lmod.sh 2>/dev/null"
            " || source /usr/share/lmod/lmod/init/bash 2>/dev/null"
            " || true"
        )
        lines.append(f"module load {module_spec}")
        lines.append("")

        # Environment overrides
        if env_overrides:
            lines.append("# Tool-specific environment")
            for k, v in env_overrides.items():
                lines.append(f"export {k}={shlex.quote(str(v))}")
            lines.append("")

        # Conda activation for Python steps
        if step_kind == "python_wrapper":
            lines.append("# Activate Brain Researcher conda environment")
            lines.append(
                'source "$(conda info --base)/etc/profile.d/conda.sh" 2>/dev/null'
                ' || source "/app/mambaforge/etc/profile.d/conda.sh" 2>/dev/null'
                " || true"
            )
            lines.append(f"conda activate {shlex.quote(self.conda_env_name)}")
            lines.append("")

        # Main command
        lines.append("# Analysis command")
        if command_tokens:
            lines.append(" ".join(shlex.quote(t) for t in command_tokens))
        else:
            lines.append("echo 'WARNING: no command generated for this step'")
        lines.append("")

        # Exit-code capture
        lines.append(
            f"echo \"EXIT_CODE=$?\" >> {shlex.quote(str(self.logs_dir / (job_name + '_status.txt')))}"
        )

        return "\n".join(lines) + "\n"

    def _build_sbatch_header(
        self, job_name: str, resources: ResourceRequirements
    ) -> list[str]:
        lines = [
            f"#SBATCH --job-name={job_name}",
            f"#SBATCH --time={_minutes_to_slurm(resources.walltime_minutes)}",
            f"#SBATCH --cpus-per-task={int(resources.cpu)}",
            f"#SBATCH --mem={int(resources.memory_gb)}G",
            f"#SBATCH --output={self.logs_dir}/{job_name}_%j.out",
            f"#SBATCH --error={self.logs_dir}/{job_name}_%j.err",
        ]
        if self.cluster_config.get("partition"):
            lines.append(f"#SBATCH --partition={self.cluster_config['partition']}")
        if self.cluster_config.get("account"):
            lines.append(f"#SBATCH --account={self.cluster_config['account']}")
        if self.cluster_config.get("qos"):
            lines.append(f"#SBATCH --qos={self.cluster_config['qos']}")
        if resources.gpu > 0:
            lines.append(f"#SBATCH --gpus={resources.gpu}")
        return lines

    def _default_command(self, step: WorkflowStep, step_kind: str) -> list[str]:
        """Best-effort command construction from step.parameters.

        For CLI tools, looks up a command template from execution_recipes.yaml
        first.  Falls back to a bare positional command when no template is
        found — the planner can always set ``metadata["cli_command"]`` for full
        control.
        """
        params = step.parameters or {}
        meta = step.metadata if isinstance(step.metadata, dict) else {}

        if step_kind == "python_wrapper":
            module_path = params.get("python_module", "brain_researcher.__main__")
            extra = params.get("python_args", "")
            return ["python", "-m", str(module_path)] + (
                shlex.split(str(extra)) if extra else []
            )

        # Derive CLI command name: "fsl_bet" → "bet"
        tool_cmd = step.tool_name.split("_")[-1]

        # Try YAML-configured command template first
        package = _resolve_package(step.tool_name, meta)
        template = get_neurodesk_command_template(package, tool_cmd)
        if template:
            rendered = _render_command_template(template, dict(params))
            if rendered:
                return rendered

        # Bare fallback: positional input + output
        cmd = [tool_cmd]
        for k in ("input_file", "input", "in_file", "bids_dir"):
            if k in params:
                cmd.append(str(params[k]))
                break
        for k in ("output_file", "output", "out_file", "output_dir"):
            if k in params:
                cmd.append(str(params[k]))
                break
        return cmd

    def _detect_expected_outputs(self, step: WorkflowStep) -> list[str]:
        """Extract expected output paths from step parameters."""
        params = step.parameters or {}
        outputs = []
        for k in ("output_file", "output", "out_file", "output_dir", "out"):
            if k in params:
                outputs.append(str(params[k]))
        # Also check produces metadata
        produces = (step.metadata or {}).get("produces", {})
        for v in produces.values():
            if isinstance(v, str) and v not in outputs:
                outputs.append(v)
        return outputs


# ---------------------------------------------------------------------------
# Heavy tools that default to handoff dispatch mode
# ---------------------------------------------------------------------------

_HEAVY_TOOLS = frozenset(
    {
        "fmriprep",
        "freesurfer",
        "recon-all",
        "mriqc",
        "mrtrix3",
        "palm",
        "melodic",
        "qsiprep",
        "qsirecon",
    }
)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """Result returned by NeurodeskDispatcher.dispatch()."""

    mode: str  # "pending_dispatch" | "handoff" | "k8s" | "local"
    ref: str  # artifact_id / k8s_job_name / slurm_job_id
    script_path: str
    instructions: str  # human-readable next-step guidance
    script_content: str | None = None  # script text (populated for pending_dispatch)


class NeurodeskDispatcher:
    """Dispatch a compiled NeurodeskExecutionPack according to mode.

    Modes
    -----
    handoff  (default for heavy tools)
        Write script metadata to global index.  Return immediately —
        Brain Researcher does not own the execution lifecycle.

    k8s
        Submit as a Kubernetes Job (k3s cluster) with CVMFS hostPath mount.
        Requires ``kubernetes`` Python package.

    local
        Local ``sbatch`` submission.  Suitable for dev workstations or HPC.

    Args:
        mode: Default dispatch mode ("handoff" | "k8s" | "local").
        config: Backend config dict.
        confirm_before_dispatch: When True, ``dispatch()`` writes the artifact
            to the global index with status="pending" and returns
            ``mode="pending_dispatch"`` — the caller must call
            ``execute_dispatch(artifact_id, mode)`` after the user confirms
            where to run.  Default False (dispatch immediately).
    """

    def __init__(
        self,
        mode: str,
        config: dict[str, Any],
        *,
        confirm_before_dispatch: bool = False,
    ) -> None:
        self.mode = mode
        self.config = config or {}
        self.confirm_before_dispatch = confirm_before_dispatch

    def dispatch(self, pack: NeurodeskExecutionPack) -> DispatchResult:
        if self.confirm_before_dispatch:
            return self._stage_for_confirmation(pack)
        return self._execute_mode(pack, self.mode)

    def _execute_mode(self, pack: NeurodeskExecutionPack, mode: str) -> DispatchResult:
        if mode == "handoff":
            return self._dispatch_handoff(pack)
        if mode == "k8s":
            return self._dispatch_k8s(pack)
        if mode == "local":
            return self._dispatch_local(pack)
        raise ValueError(f"Unknown dispatch mode: {mode!r}")

    # ------------------------------------------------------------------
    # Confirm-before-dispatch (pending_dispatch mode)
    # ------------------------------------------------------------------

    def _stage_for_confirmation(self, pack: NeurodeskExecutionPack) -> DispatchResult:
        """Write artifact to global index with status=pending; return pending_dispatch."""
        artifact_id = f"nd-script-{uuid.uuid4().hex[:12]}"
        resources_dict = {
            "cpu": pack.resources.cpu,
            "memory_gb": pack.resources.memory_gb,
            "walltime_minutes": pack.resources.walltime_minutes,
            "gpu": pack.resources.gpu,
        }
        record: dict[str, Any] = {
            "artifact_id": artifact_id,
            "status": "pending",
            "step_id": pack.step_id,
            "job_name": pack.job_name,
            "script_path": str(pack.script_path),
            "script_text": pack.script_text,
            "module_spec": pack.module_spec,
            "resources": resources_dict,
            "env_overrides": pack.env_overrides,
            "expected_outputs": pack.expected_outputs,
        }
        _upsert_global_index(record)
        logger.info(
            "NeurodeskDispatcher: staged artifact_id=%s for confirmation", artifact_id
        )
        instructions = (
            f"Script compiled and ready for dispatch.\n\n"
            f"**Script path:** {pack.script_path}\n"
            f"**Module:** {pack.module_spec}\n"
            f"**Resources:** {int(pack.resources.cpu)} CPU, {int(pack.resources.memory_gb)} GB RAM, "
            f"{int(pack.resources.walltime_minutes)} min walltime\n\n"
            f"Where would you like to run this?\n"
            f"  • **local** — sbatch on this machine (requires SLURM)\n"
            f"  • **k8s**   — k3s cluster (Neurodesk containers, CVMFS mounted)\n"
            f"  • **handoff** — save script and run yourself in Neurodesk / HPC\n\n"
            f"Reply with your choice, then the job will be dispatched."
        )
        return DispatchResult(
            mode="pending_dispatch",
            ref=artifact_id,
            script_path=str(pack.script_path),
            script_content=pack.script_text,
            instructions=instructions,
        )

    def execute_dispatch(self, artifact_id: str, mode: str) -> DispatchResult:
        """Dispatch a previously staged artifact in the given mode.

        Called after the user has confirmed where to run the job.
        """
        record = _find_in_global_index(artifact_id)
        if record is None:
            raise ValueError(f"Artifact {artifact_id!r} not found in global index")
        if record.get("status") not in ("pending", "pending_dispatch"):
            raise ValueError(
                f"Artifact {artifact_id!r} is not in pending state (status={record.get('status')!r})"
            )

        # Reconstruct a minimal NeurodeskExecutionPack from the stored record
        res_d = record.get("resources") or {}
        resources = ResourceRequirements(
            cpu=res_d.get("cpu", 4),
            memory_gb=res_d.get("memory_gb", 16),
            walltime_minutes=res_d.get("walltime_minutes", 60),
            gpu=res_d.get("gpu", 0),
        )
        pack = NeurodeskExecutionPack(
            step_id=record.get("step_id", artifact_id),
            script_path=Path(record["script_path"]),
            script_text=record.get("script_text", ""),
            job_name=record.get("job_name", artifact_id),
            module_spec=record.get("module_spec", ""),
            resources=resources,
            expected_outputs=record.get("expected_outputs") or [],
            env_overrides=record.get("env_overrides") or {},
        )

        result = self._execute_mode(pack, mode)

        # Update global index
        _upsert_global_index(
            {
                "artifact_id": artifact_id,
                "status": "dispatched",
                "dispatch_mode": mode,
                "job_ref": result.ref,
            }
        )
        return result

    def register_completion(
        self,
        artifact_id: str,
        *,
        output_paths: list[str] | None = None,
        exit_code: int | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record that a dispatched job has completed (called by Neurodesk env or user).

        Updates the global artifact index entry with completion metadata.
        Returns the updated record.
        """
        record = _find_in_global_index(artifact_id)
        if record is None:
            raise ValueError(f"Artifact {artifact_id!r} not found in global index")
        status = "completed" if (exit_code is None or exit_code == 0) else "failed"
        update = {
            "artifact_id": artifact_id,
            "status": status,
            "exit_code": exit_code,
            "output_paths": output_paths or [],
            "notes": notes or "",
        }
        _upsert_global_index(update)
        logger.info(
            "NeurodeskDispatcher: register_completion artifact_id=%s status=%s outputs=%s",
            artifact_id,
            status,
            output_paths,
        )
        merged = {**record, **update}
        return merged

    # ------------------------------------------------------------------
    # Handoff mode
    # ------------------------------------------------------------------

    def _dispatch_handoff(self, pack: NeurodeskExecutionPack) -> DispatchResult:
        artifact_id = f"nd-script-{uuid.uuid4().hex[:12]}"
        record: dict[str, Any] = {
            "artifact_id": artifact_id,
            "status": "dispatched",
            "dispatch_mode": "handoff",
            "step_id": pack.step_id,
            "job_name": pack.job_name,
            "script_path": str(pack.script_path),
            "module_spec": pack.module_spec,
            "expected_outputs": pack.expected_outputs,
        }
        _upsert_global_index(record)

        instructions = (
            f"Script ready: {pack.script_path}\n"
            f"\nTo run in Neurodesk / HPC:\n"
            f"  sbatch {pack.script_path}\n"
            f"\nTo run locally:\n"
            f"  bash {pack.script_path}\n"
            f"\nModule: {pack.module_spec}\n"
            f"\nWhen done, register results via:\n"
            f"  POST /neurodesk/artifacts/{artifact_id}/complete"
        )
        logger.info(
            "NeurodeskDispatcher: handoff artifact_id=%s script=%s",
            artifact_id,
            pack.script_path,
        )
        return DispatchResult(
            mode="handoff",
            ref=artifact_id,
            script_path=str(pack.script_path),
            instructions=instructions,
        )

    # ------------------------------------------------------------------
    # Kubernetes (k3s) mode
    # ------------------------------------------------------------------

    def _dispatch_k8s(self, pack: NeurodeskExecutionPack) -> DispatchResult:
        try:
            from kubernetes import client as k8s_client
            from kubernetes import config as k8s_config
        except ImportError as exc:
            raise RuntimeError(
                "kubernetes Python package is required for k8s dispatch mode. "
                "Install it with: pip install kubernetes"
            ) from exc

        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()

        job_name = f"nd-{pack.job_name}-{uuid.uuid4().hex[:6]}"
        namespace = self.config.get("namespace", "default")
        image = self.config.get(
            "neurodesk_image",
            "ghcr.io/neurodesk/neurodesktop:latest",
        )

        res = pack.resources
        cvmfs_host_path = self.config.get("cvmfs_host_path", "/cvmfs")

        # CVMFS volume: mount the host /cvmfs into the container so Neurodesk
        # container images and neurocommand modules are available without
        # rebuilding the image.
        cvmfs_volume = k8s_client.V1Volume(
            name="cvmfs",
            host_path=k8s_client.V1HostPathVolumeSource(
                path=cvmfs_host_path,
                type="DirectoryOrCreate",
            ),
        )
        cvmfs_mount = k8s_client.V1VolumeMount(
            name="cvmfs",
            mount_path="/cvmfs",
            read_only=True,
        )

        job_body = k8s_client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=k8s_client.V1ObjectMeta(name=job_name, namespace=namespace),
            spec=k8s_client.V1JobSpec(
                template=k8s_client.V1PodTemplateSpec(
                    spec=k8s_client.V1PodSpec(
                        restart_policy="Never",
                        volumes=[cvmfs_volume],
                        containers=[
                            k8s_client.V1Container(
                                name="neurodesk",
                                image=image,
                                command=["bash", "-c", pack.script_text],
                                volume_mounts=[cvmfs_mount],
                                resources=k8s_client.V1ResourceRequirements(
                                    requests={
                                        "cpu": str(int(res.cpu)),
                                        "memory": f"{int(res.memory_gb)}Gi",
                                    },
                                    limits={
                                        "cpu": str(int(res.cpu)),
                                        "memory": f"{int(res.memory_gb)}Gi",
                                    },
                                ),
                            )
                        ],
                    )
                ),
                backoff_limit=0,
            ),
        )

        batch_v1 = k8s_client.BatchV1Api()
        batch_v1.create_namespaced_job(namespace, job_body)
        logger.info(
            "NeurodeskDispatcher: k8s job=%s submitted (cvmfs=%s)",
            job_name,
            cvmfs_host_path,
        )

        instructions = (
            f"Kubernetes Job submitted: {job_name}\n"
            f"  kubectl get job {job_name} -n {namespace}\n"
            f"  kubectl logs -l job-name={job_name} -n {namespace}"
        )
        return DispatchResult(
            mode="k8s",
            ref=job_name,
            script_path=str(pack.script_path),
            instructions=instructions,
        )

    # ------------------------------------------------------------------
    # Local sbatch mode
    # ------------------------------------------------------------------

    def _dispatch_local(self, pack: NeurodeskExecutionPack) -> DispatchResult:
        """Submit via sbatch using NeurodeskBackend (dev/HPC path)."""
        from brain_researcher.services.tools.neurodesk_backend import (
            NeurodeskBackend,
        )

        backend_config = dict(self.config)
        backend_config.setdefault("mode", "local")
        backend = NeurodeskBackend("neurodesk_local", backend_config)

        job_spec = JobSpecification(
            name=pack.job_name,
            command=f"bash {pack.script_path}",
            image="",
            environment=pack.env_overrides,
            resources=pack.resources,
        )
        loop = asyncio.new_event_loop()
        try:
            job_id = loop.run_until_complete(backend.submit_job(job_spec))
        finally:
            loop.close()

        logger.info("NeurodeskDispatcher: local sbatch job_id=%s", job_id)
        instructions = (
            f"SLURM job submitted: {job_id}\n"
            f"  squeue -j {job_id.removeprefix('nd-')}\n"
            f"  sacct -j {job_id.removeprefix('nd-')}"
        )
        return DispatchResult(
            mode="local",
            ref=job_id,
            script_path=str(pack.script_path),
            instructions=instructions,
        )


# ---------------------------------------------------------------------------
# Tool executor bridge
# ---------------------------------------------------------------------------


class NeurodeskToolExecutor:
    """Adapter so DAGExecutor can drive Neurodesk dispatch via run_tool() protocol.

    For steps with runtime_kind="python", delegates to *fallback_executor* when
    provided.  All other steps are compiled then dispatched via *dispatcher*.

    The default dispatch mode is ``"handoff"`` — Brain Researcher returns
    immediately with the compiled script artifact and instructions.  The
    Neurodesk environment (or user) decides where and how to execute it.

    Args:
        dispatcher: NeurodeskDispatcher instance controlling dispatch mode.
        compiler: NeurodeskCompiler to produce .sh scripts.
        fallback_executor: Optional ToolExecutor for Python steps.
    """

    def __init__(
        self,
        dispatcher: NeurodeskDispatcher,
        compiler: NeurodeskCompiler,
        *,
        fallback_executor: Any = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.compiler = compiler
        self.fallback_executor = fallback_executor
        self._step_counter = 0

    def run_tool(
        self,
        tool_name: str,
        *,
        _execution_context: dict[str, Any],
        **params: Any,
    ) -> dict[str, Any]:
        runtime_kind = _execution_context.get("runtime_kind", "neurodesk")

        if runtime_kind == "python" and self.fallback_executor is not None:
            return self.fallback_executor.run_tool(
                tool_name,
                _execution_context=_execution_context,
                **params,
            )

        self._step_counter += 1
        step_index = self._step_counter

        step = WorkflowStep(
            step_id=_execution_context.get("step_id", f"step-{step_index}"),
            tool_name=tool_name,
            parameters=dict(params),
            metadata={
                **(_execution_context.get("step_metadata") or {}),
                "runtime_kind": runtime_kind,
                "work_dir": _execution_context.get("work_dir", ""),
                "output_dir": _execution_context.get("output_dir", ""),
            },
        )

        pack = self.compiler.compile(step, step_index=step_index)
        result = self.dispatcher.dispatch(pack)

        if result.mode == "pending_dispatch":
            # Script compiled; waiting for user to choose dispatch target.
            # The agent should present this to the user and call
            # execute_dispatch(artifact_id, mode) after confirmation.
            return {
                "status": "pending_dispatch",
                "data": {
                    "artifact_id": result.ref,
                    "script_path": result.script_path,
                    "script_content": result.script_content,
                    "module_spec": pack.module_spec,
                    "expected_outputs": pack.expected_outputs,
                    "available_modes": ["local", "k8s", "handoff"],
                    "instructions": result.instructions,
                },
                "error": None,
            }

        if result.mode == "handoff":
            return {
                "status": "dispatched",
                "data": {
                    "mode": "handoff",
                    "artifact_id": result.ref,
                    "script_path": result.script_path,
                    "instructions": result.instructions,
                    "module_spec": pack.module_spec,
                    "expected_outputs": pack.expected_outputs,
                },
                "error": None,
            }

        # k8s / local: return job ref for caller to track separately
        return {
            "status": "submitted",
            "data": {
                "mode": result.mode,
                "job_ref": result.ref,
                "script_path": result.script_path,
                "instructions": result.instructions,
                "module_spec": pack.module_spec,
                "expected_outputs": pack.expected_outputs,
            },
            "error": None,
        }
