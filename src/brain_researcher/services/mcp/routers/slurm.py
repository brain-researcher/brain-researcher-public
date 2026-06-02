"""SLURM / Sherlock MCP tools.

Carved out of ``mcp/server.py`` as part of splitting that monolith into
per-domain router modules. Importing this module registers the ``slurm_guide``
/ ``sherlock_guide`` / ``slurm_submit`` / ``sherlock_slurm`` tools on the shared
FastMCP instance via the ``@mcp.tool()`` decorator (an import side effect), so
``server.py`` imports it for its effect.

These tools are thin wrappers: the real implementations live in
``brain_researcher.services.mcp.slurm_tools`` (imported here as
``_sherlock_guide`` / ``_sherlock_slurm``, the same aliases server used). The
two ``_slurm_*_required_param_error`` validators stay in ``server`` and are
imported back.
"""

from __future__ import annotations

from typing import Any

from brain_researcher.services.mcp.param_norm import (
    as_str_list,
    coerce_enum,
    enum_str,
    resolve_enum_or_error,
)
from brain_researcher.services.mcp.server import (
    _slurm_guide_required_param_error,
    _slurm_submit_required_param_error,
    mcp,
)
from brain_researcher.services.mcp.slurm_tools import (
    CLUSTER_PROFILES,
    DEFAULT_PROFILE,
)
from brain_researcher.services.mcp.slurm_tools import sherlock_guide as _sherlock_guide
from brain_researcher.services.mcp.slurm_tools import sherlock_slurm as _sherlock_slurm

# --- Categorical-arg contract: enum advertising + synonym coercion ----------
# Guide tools (slurm_guide / sherlock_guide) dispatch on {guide, command};
# slurm tools (slurm_submit / sherlock_slurm) on the six script/job actions.
# Both currently RAISE on an unknown action via slurm_tools; we route the value
# through resolve_enum_or_error so the rejection stays but lists allowed values
# and is one-shot discoverable. Synonyms keep lax hosts (e.g. Codex) succeeding.
_GUIDE_ACTION_ALIASES: dict[str, str] = {
    "guide": "guide",
    "guides": "guide",
    "help": "guide",
    "topic": "guide",
    "command": "command",
    "commands": "command",
    "cmd": "command",
    "render": "command",
    "render_command": "command",
}
_GUIDE_ACTIONS: tuple[str, ...] = ("guide", "command")

_SLURM_ACTION_ALIASES: dict[str, str] = {
    "render_script": "render_script",
    "render": "render_script",
    "render_sbatch": "render_script",
    "script": "render_script",
    "validate_script": "validate_script",
    "validate": "validate_script",
    "lint": "validate_script",
    "check": "validate_script",
    "patch_script": "patch_script",
    "patch": "patch_script",
    "edit": "patch_script",
    "edit_script": "patch_script",
    "inspect_job": "inspect_job",
    "inspect": "inspect_job",
    "status": "inspect_job",
    "job_status": "inspect_job",
    "read_logs": "read_logs",
    "logs": "read_logs",
    "log": "read_logs",
    "read_log": "read_logs",
    "tail_logs": "read_logs",
    "diagnose_failure": "diagnose_failure",
    "diagnose": "diagnose_failure",
    "diagnosis": "diagnose_failure",
    "triage": "diagnose_failure",
}
_SLURM_ACTIONS: tuple[str, ...] = (
    "render_script",
    "validate_script",
    "patch_script",
    "inspect_job",
    "read_logs",
    "diagnose_failure",
)

_TEMPLATE_KIND_ALIASES: dict[str, str] = {
    "cpu_single": "cpu_single",
    "cpu": "cpu_single",
    "single": "cpu_single",
    "cpu_array": "cpu_array",
    "array": "cpu_array",
    "cpu_arr": "cpu_array",
    "gpu_single": "gpu_single",
    "gpu": "gpu_single",
    "gpu_multinode": "gpu_multinode",
    "gpu_multi": "gpu_multinode",
    "multinode": "gpu_multinode",
}
_TEMPLATE_KINDS: tuple[str, ...] = (
    "cpu_single",
    "cpu_array",
    "gpu_single",
    "gpu_multinode",
)

_STREAM_ALIASES: dict[str, str] = {
    "stdout": "stdout",
    "out": "stdout",
    "stderr": "stderr",
    "err": "stderr",
    "both": "both",
    "all": "both",
}
_STREAMS: tuple[str, ...] = ("stdout", "stderr", "both")

# SLURM mail types and sacct states are passed through (uppercased) — optional,
# advertised so clients pick valid tokens, never hard-failed on an unknown token.
_MAIL_TYPES: tuple[str, ...] = (
    "NONE",
    "BEGIN",
    "END",
    "FAIL",
    "REQUEUE",
    "ALL",
    "STAGE_OUT",
    "TIME_LIMIT",
    "ARRAY_TASKS",
)
_SACCT_STATES: tuple[str, ...] = (
    "COMPLETED",
    "FAILED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "CANCELLED",
    "RUNNING",
    "PENDING",
    "NODE_FAIL",
    "PREEMPTED",
)

# cluster_profile enum reflects whatever profiles are loaded at import time;
# unknown values coerce to DEFAULT_PROFILE (silent fallback preserved).
_CLUSTER_PROFILE_KEYS: tuple[str, ...] = tuple(sorted(CLUSTER_PROFILES.keys()))
_CLUSTER_PROFILE_ALIASES: dict[str, str] = {
    key.strip().lower().replace("-", "_").replace(" ", "_"): key
    for key in CLUSTER_PROFILES
}


def _normalize_mail_type(value: str | None) -> str | None:
    """Uppercase-normalize a (possibly comma-separated) mail_type; pass unknown tokens through."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return value
    return ",".join(tok.strip().upper() for tok in text.split(",") if tok.strip())


@mcp.tool()
def slurm_guide(
    action: enum_str(
        _GUIDE_ACTIONS, "what to return: a workflow guide or a rendered command"
    ) = "guide",
    topic: str | None = None,
    intent: str | None = None,
    sunet: str | None = None,
    pi_group: str = "russpold",
    partition: str | None = None,
    qos: str | None = None,
    time: str | None = None,
    cpus: int | None = None,
    mem: str | None = None,
    gpus: int | None = None,
    dataset: str | None = None,
    script_path: str | None = None,
    job_id: str | None = None,
    log_path: str | None = None,
    mount_path: str | None = None,
) -> dict[str, Any]:
    """SLURM workflow guide and command renderer (any SLURM cluster via profile).

    Profile selected by ``pi_group`` (legacy) or ``BR_SLURM_PROFILE`` env var.
    Ships with ``sherlock_russpold`` profile; add your own at
    ``configs/slurm/profiles/<name>.yaml`` (see docs/hpc.md).
    """
    action, action_err = resolve_enum_or_error(
        action, _GUIDE_ACTION_ALIASES, field="action"
    )
    if action_err is not None:
        return action_err
    required_param_error = _slurm_guide_required_param_error(
        action=action,
        topic=topic,
        intent=intent,
    )
    if required_param_error is not None:
        return required_param_error
    return _sherlock_guide(
        action=action,
        topic=topic,
        intent=intent,
        sunet=sunet,
        pi_group=pi_group,
        partition=partition,
        qos=qos,
        time=time,
        cpus=cpus,
        mem=mem,
        gpus=gpus,
        dataset=dataset,
        script_path=script_path,
        job_id=job_id,
        log_path=log_path,
        mount_path=mount_path,
    )


@mcp.tool()
def sherlock_guide(
    action: enum_str(
        _GUIDE_ACTIONS, "what to return: a workflow guide or a rendered command"
    ) = "guide",
    topic: str | None = None,
    intent: str | None = None,
    sunet: str | None = None,
    pi_group: str = "russpold",
    partition: str | None = None,
    qos: str | None = None,
    time: str | None = None,
    cpus: int | None = None,
    mem: str | None = None,
    gpus: int | None = None,
    dataset: str | None = None,
    script_path: str | None = None,
    job_id: str | None = None,
    log_path: str | None = None,
    mount_path: str | None = None,
) -> dict[str, Any]:
    """[DEPRECATED — use ``slurm_guide``] Sherlock-specific alias kept for back-compat."""
    action, action_err = resolve_enum_or_error(
        action, _GUIDE_ACTION_ALIASES, field="action"
    )
    if action_err is not None:
        return action_err
    return _sherlock_guide(
        action=action,
        topic=topic,
        intent=intent,
        sunet=sunet,
        pi_group=pi_group,
        partition=partition,
        qos=qos,
        time=time,
        cpus=cpus,
        mem=mem,
        gpus=gpus,
        dataset=dataset,
        script_path=script_path,
        job_id=job_id,
        log_path=log_path,
        mount_path=mount_path,
    )


@mcp.tool()
def slurm_submit(
    action: enum_str(
        _SLURM_ACTIONS, "which sbatch authoring / job-debugging operation to run"
    ),
    cluster_profile: enum_str(
        _CLUSTER_PROFILE_KEYS, "SLURM cluster profile (partition/qos/account/modules)"
    ) = "sherlock_russpold",
    template_kind: enum_str(
        _TEMPLATE_KINDS, "sbatch template to render (required for render_script)"
    ) = None,
    job_name: str = "brain-researcher-job",
    time: str = "24:00:00",
    partition: str | None = None,
    qos: str | None = None,
    account: str | None = None,
    cpus_per_task: int = 8,
    mem: str = "32G",
    nodes: int = 1,
    ntasks_per_node: int | None = None,
    gpus: int | None = None,
    gpus_per_node: int | None = None,
    array: str | None = None,
    array_concurrency: int | None = None,
    output: str | None = None,
    error: str | None = None,
    mail_user: str | None = None,
    mail_type: enum_str(
        _MAIL_TYPES, "SLURM --mail-type (comma-separated allowed)"
    ) = None,
    workdir: str | None = None,
    module_lines: list[str] | None = None,
    env_lines: list[str] | None = None,
    command: str | None = None,
    task_file: str | None = None,
    launcher: str | None = None,
    include_export_none: bool = True,
    change_request: str | None = None,
    script_text: str | None = None,
    script_path: str | None = None,
    job_id: str | None = None,
    include_squeue: bool = True,
    include_sacct: bool = True,
    include_scontrol: bool = True,
    log_path: str | None = None,
    stream: enum_str(_STREAMS, "which log stream to read (read_logs)") = "both",
    tail: int = 200,
    grep: str | None = None,
    stdout_text: str | None = None,
    stderr_text: str | None = None,
    sacct_state: enum_str(
        _SACCT_STATES, "SLURM job state hint for diagnose_failure"
    ) = None,
) -> dict[str, Any]:
    """Render / validate / patch sbatch scripts, inspect jobs, read logs, and diagnose failures.

    Despite the name, this tool does NOT submit jobs — it is read-mostly and
    helps you author a correct sbatch script. Run ``sbatch`` yourself after
    reviewing the rendered text. Profile selected via ``cluster_profile``
    parameter or ``BR_SLURM_PROFILE`` env var.
    """
    action, action_err = resolve_enum_or_error(
        action, _SLURM_ACTION_ALIASES, field="action"
    )
    if action_err is not None:
        return action_err
    cluster_profile = coerce_enum(
        cluster_profile, _CLUSTER_PROFILE_ALIASES, DEFAULT_PROFILE
    )
    if template_kind is not None and str(template_kind).strip():
        template_kind = coerce_enum(template_kind, _TEMPLATE_KIND_ALIASES, "cpu_single")
    stream = coerce_enum(stream, _STREAM_ALIASES, "both")
    mail_type = _normalize_mail_type(mail_type)
    if sacct_state is not None and str(sacct_state).strip():
        sacct_state = str(sacct_state).strip().upper()
    module_lines = as_str_list(module_lines) or None
    env_lines = as_str_list(env_lines) or None
    required_param_error = _slurm_submit_required_param_error(
        action=action,
        template_kind=template_kind,
        change_request=change_request,
        script_text=script_text,
        script_path=script_path,
        job_id=job_id,
        log_path=log_path,
    )
    if required_param_error is not None:
        return required_param_error
    return _sherlock_slurm(
        action=action,
        cluster_profile=cluster_profile,
        template_kind=template_kind,
        job_name=job_name,
        time=time,
        partition=partition,
        qos=qos,
        account=account,
        cpus_per_task=cpus_per_task,
        mem=mem,
        nodes=nodes,
        ntasks_per_node=ntasks_per_node,
        gpus=gpus,
        gpus_per_node=gpus_per_node,
        array=array,
        array_concurrency=array_concurrency,
        output=output,
        error=error,
        mail_user=mail_user,
        mail_type=mail_type,
        workdir=workdir,
        module_lines=module_lines,
        env_lines=env_lines,
        command=command,
        task_file=task_file,
        launcher=launcher,
        include_export_none=include_export_none,
        change_request=change_request,
        script_text=script_text,
        script_path=script_path,
        job_id=job_id,
        include_squeue=include_squeue,
        include_sacct=include_sacct,
        include_scontrol=include_scontrol,
        log_path=log_path,
        stream=stream,
        tail=tail,
        grep=grep,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        sacct_state=sacct_state,
    )


@mcp.tool()
def sherlock_slurm(
    action: enum_str(
        _SLURM_ACTIONS, "which sbatch authoring / job-debugging operation to run"
    ),
    cluster_profile: enum_str(
        _CLUSTER_PROFILE_KEYS, "SLURM cluster profile (partition/qos/account/modules)"
    ) = "sherlock_russpold",
    template_kind: enum_str(
        _TEMPLATE_KINDS, "sbatch template to render (required for render_script)"
    ) = None,
    job_name: str = "brain-researcher-job",
    time: str = "24:00:00",
    partition: str | None = None,
    qos: str | None = None,
    account: str | None = None,
    cpus_per_task: int = 8,
    mem: str = "32G",
    nodes: int = 1,
    ntasks_per_node: int | None = None,
    gpus: int | None = None,
    gpus_per_node: int | None = None,
    array: str | None = None,
    array_concurrency: int | None = None,
    output: str | None = None,
    error: str | None = None,
    mail_user: str | None = None,
    mail_type: enum_str(
        _MAIL_TYPES, "SLURM --mail-type (comma-separated allowed)"
    ) = None,
    workdir: str | None = None,
    module_lines: list[str] | None = None,
    env_lines: list[str] | None = None,
    command: str | None = None,
    task_file: str | None = None,
    launcher: str | None = None,
    include_export_none: bool = True,
    change_request: str | None = None,
    script_text: str | None = None,
    script_path: str | None = None,
    job_id: str | None = None,
    include_squeue: bool = True,
    include_sacct: bool = True,
    include_scontrol: bool = True,
    log_path: str | None = None,
    stream: enum_str(_STREAMS, "which log stream to read (read_logs)") = "both",
    tail: int = 200,
    grep: str | None = None,
    stdout_text: str | None = None,
    stderr_text: str | None = None,
    sacct_state: enum_str(
        _SACCT_STATES, "SLURM job state hint for diagnose_failure"
    ) = None,
) -> dict[str, Any]:
    """[DEPRECATED — use ``slurm_submit``] Sherlock-specific alias kept for back-compat."""
    action, action_err = resolve_enum_or_error(
        action, _SLURM_ACTION_ALIASES, field="action"
    )
    if action_err is not None:
        return action_err
    cluster_profile = coerce_enum(
        cluster_profile, _CLUSTER_PROFILE_ALIASES, DEFAULT_PROFILE
    )
    if template_kind is not None and str(template_kind).strip():
        template_kind = coerce_enum(template_kind, _TEMPLATE_KIND_ALIASES, "cpu_single")
    stream = coerce_enum(stream, _STREAM_ALIASES, "both")
    mail_type = _normalize_mail_type(mail_type)
    if sacct_state is not None and str(sacct_state).strip():
        sacct_state = str(sacct_state).strip().upper()
    module_lines = as_str_list(module_lines) or None
    env_lines = as_str_list(env_lines) or None
    return _sherlock_slurm(
        action=action,
        cluster_profile=cluster_profile,
        template_kind=template_kind,
        job_name=job_name,
        time=time,
        partition=partition,
        qos=qos,
        account=account,
        cpus_per_task=cpus_per_task,
        mem=mem,
        nodes=nodes,
        ntasks_per_node=ntasks_per_node,
        gpus=gpus,
        gpus_per_node=gpus_per_node,
        array=array,
        array_concurrency=array_concurrency,
        output=output,
        error=error,
        mail_user=mail_user,
        mail_type=mail_type,
        workdir=workdir,
        module_lines=module_lines,
        env_lines=env_lines,
        command=command,
        task_file=task_file,
        launcher=launcher,
        include_export_none=include_export_none,
        change_request=change_request,
        script_text=script_text,
        script_path=script_path,
        job_id=job_id,
        include_squeue=include_squeue,
        include_sacct=include_sacct,
        include_scontrol=include_scontrol,
        log_path=log_path,
        stream=stream,
        tail=tail,
        grep=grep,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        sacct_state=sacct_state,
    )
