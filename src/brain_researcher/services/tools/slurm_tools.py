"""Generic SLURM helper logic for MCP-facing tools.

Covers sbatch script rendering, validation, patching, local Slurm queue
inspection, and failure diagnosis. The helpers are intentionally read-mostly:
they generate text, inspect local Slurm state, and diagnose failures, but
do not submit or mutate jobs.

Cluster profiles (partition / qos / account / module paths) are pluggable;
the default ships a Stanford Sherlock ``russpold`` profile for back-compat,
but any SLURM cluster can supply its own profile via ``CLUSTER_PROFILES`` or
(Phase B-2) a ``configs/slurm/profiles/*.yaml`` file.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

import yaml

GuideTopic = Literal[
    "login",
    "storage",
    "interactive",
    "batch",
    "transfer",
    "quota",
    "acl",
    "readonly",
    "logs",
    "debugging",
]

CommandIntent = Literal[
    "login",
    "interactive_cpu",
    "interactive_gpu",
    "batch_cpu",
    "submit_script",
    "cancel_job",
    "queue_status",
    "job_accounting",
    "log_tail",
    "quota_check",
    "rsync_to_oak",
    "sshfs_mount",
    "scontrol_show_job",
]

TemplateKind = Literal["cpu_single", "cpu_array", "gpu_single", "gpu_multinode"]
GuideAction = Literal["guide", "command"]
SlurmAction = Literal[
    "render_script",
    "validate_script",
    "patch_script",
    "inspect_job",
    "read_logs",
    "diagnose_failure",
]

SCRIPT_SOURCES = [
    "skills/sherlock-oak-workflow/SKILL.md",
    "skills/sherlock-oak-workflow/references/login-and-access.md",
    "skills/sherlock-oak-workflow/references/storage-and-paths.md",
    "skills/sherlock-oak-workflow/references/slurm-recipes.md",
    "skills/sherlock-oak-workflow/references/poldracklab-data-assets.md",
]

DEFAULT_PROFILE = os.environ.get("BR_SLURM_PROFILE", "sherlock_russpold")

# Inline fallback profile (used if configs/slurm/profiles/*.yaml not findable,
# e.g. when running from a wheel install without the configs/ tree). Mirrors
# configs/slurm/profiles/sherlock_russpold.yaml.
_FALLBACK_PROFILES: dict[str, dict[str, Any]] = {
    "sherlock_russpold": {
        "account": "russpold",
        "interactive_partition": "russpold",
        "interactive_qos": "russpold_interactive",
        "batch_partition": "russpold",
        "batch_qos": "russpold",
        "module_use": "${CLUSTER_PI_MODULES}/modules",
        "default_output": "slurm-%j.out",
        "default_error": "slurm-%j.err",
        "notes": [
            "Profile follows the checked-in sherlock-oak-workflow skill.",
            "Adjust partition/qos if your group uses a different Sherlock queue.",
        ],
    }
}


def _load_profiles_from_yaml() -> dict[str, dict[str, Any]]:
    """Load all configs/slurm/profiles/*.yaml into the CLUSTER_PROFILES dict.

    Falls back to ``_FALLBACK_PROFILES`` if the configs tree is unreachable
    (e.g. running from a wheel without bundled configs). Profile name is
    taken from the YAML ``name:`` field, defaulting to the file stem.
    """
    try:
        from brain_researcher.config.paths import get_config_root

        profiles_dir = get_config_root() / "slurm" / "profiles"
    except Exception:
        return dict(_FALLBACK_PROFILES)

    if not profiles_dir.is_dir():
        return dict(_FALLBACK_PROFILES)

    loaded: dict[str, dict[str, Any]] = {}
    for yaml_path in sorted(profiles_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        name = data.pop("name", None) or yaml_path.stem
        # Skip the generic template — it has REPLACE_ME values
        if name == "generic_slurm":
            continue
        loaded[name] = data

    # Always retain the inline fallback as a safety net
    for name, prof in _FALLBACK_PROFILES.items():
        loaded.setdefault(name, prof)
    return loaded


CLUSTER_PROFILES: dict[str, dict[str, Any]] = _load_profiles_from_yaml()

SBATCH_DIRECTIVE_RE = re.compile(
    r"^\s*#SBATCH\s+(?:--(?P<long>[A-Za-z0-9_-]+)|-(?P<short>[A-Za-z]))(?:[=\s]+(?P<value>.*?))?\s*$"
)
DIRECTIVE_ALIASES = {
    "J": "job-name",
    "p": "partition",
    "A": "account",
    "o": "output",
    "e": "error",
    "n": "ntasks",
}
ARRAY_RE = re.compile(r"^\d+(?:-\d+)?(?:%\d+)?$")


def _ok(**payload: Any) -> dict[str, Any]:
    return {"ok": True, **payload}


def _error(error: str, **payload: Any) -> dict[str, Any]:
    return {"ok": False, "error": error, **payload}


def _profile(name: str) -> dict[str, Any]:
    return CLUSTER_PROFILES.get(name, CLUSTER_PROFILES[DEFAULT_PROFILE])


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _run_local_command(args: list[str], timeout: int = 15) -> dict[str, Any]:
    if not args:
        return {"ok": False, "error": "empty_command"}
    if not _command_exists(args[0]):
        return {"ok": False, "error": f"command_not_found:{args[0]}"}
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout_after_{timeout}s"}
    payload = {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "command": args,
    }
    if proc.returncode != 0:
        payload["error"] = proc.stderr.strip() or f"returncode={proc.returncode}"
    return payload


def _tail_text(text: str, tail: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-tail:]) if tail > 0 else text


def _read_text_source(
    script_text: str | None, script_path: str | None
) -> tuple[str | None, str | None]:
    if script_text:
        return script_text, "inline"
    if script_path:
        path = Path(script_path).expanduser()
        try:
            return path.read_text(encoding="utf-8"), str(path)
        except Exception as exc:  # pragma: no cover - filesystem edge
            return None, f"read_failed:{exc}"
    return None, None


def _parse_sbatch_directives(script_text: str) -> dict[str, str]:
    directives: dict[str, str] = {}
    for line in script_text.splitlines():
        match = SBATCH_DIRECTIVE_RE.match(line)
        if not match:
            continue
        key = match.group("long") or DIRECTIVE_ALIASES.get(match.group("short") or "")
        if not key:
            continue
        directives[key] = (match.group("value") or "").strip()
    return directives


def _replace_or_add_directive(
    script_text: str,
    key: str,
    value: str | None,
) -> str:
    lines = script_text.splitlines()
    long_prefix = f"#SBATCH --{key}"
    found = False
    updated: list[str] = []
    for line in lines:
        match = SBATCH_DIRECTIVE_RE.match(line)
        if match:
            matched_key = match.group("long") or DIRECTIVE_ALIASES.get(
                match.group("short") or ""
            )
            if matched_key == key:
                found = True
                if value is None:
                    continue
                updated.append(f"{long_prefix}={value}")
                continue
        updated.append(line)
    if found or value is None:
        return "\n".join(updated) + ("\n" if script_text.endswith("\n") else "")

    insert_at = 0
    if updated and updated[0].startswith("#!"):
        insert_at = 1
    updated.insert(insert_at, f"{long_prefix}={value}")
    return "\n".join(updated) + ("\n" if script_text.endswith("\n") else "")


def _ensure_line_after_directives(script_text: str, line_to_add: str) -> str:
    if line_to_add in script_text:
        return script_text
    lines = script_text.splitlines()
    insert_at = 0
    for idx, line in enumerate(lines):
        if line.startswith("#SBATCH"):
            insert_at = idx + 1
    lines.insert(insert_at + 1, line_to_add)
    return "\n".join(lines) + ("\n" if script_text.endswith("\n") else "")


def _default_module_block(profile_name: str) -> list[str]:
    profile = _profile(profile_name)
    module_use = profile.get("module_use")
    if module_use:
        return [f"module use {module_use}", "module load singularity"]
    return ["module load singularity"]


def sherlock_get_guide(topic: GuideTopic, pi_group: str = "russpold") -> dict[str, Any]:
    profile = _profile(DEFAULT_PROFILE)
    if topic == "login":
        return _ok(
            topic=topic,
            summary="Login flow for Sherlock 2 with the current hostname and 2FA assumptions.",
            commands=[
                {
                    "label": "ssh_login",
                    "command": "ssh <sunet>@login.sherlock.stanford.edu",
                },
                {
                    "label": "ssh_alias",
                    "command": (
                        "Host sherlock\n"
                        "  HostName login.sherlock.stanford.edu\n"
                        "  User <sunet>\n"
                        "  ForwardX11 no"
                    ),
                },
            ],
            notes=[
                "Confirm Sherlock access, Duo/2FA, and PI filesystem permissions before debugging shell config.",
                "Do not run heavy computation on the login node.",
            ],
            warnings=[],
            sources=SCRIPT_SOURCES[:2],
        )
    if topic == "storage":
        return _ok(
            topic=topic,
            summary="Filesystem routing for code, scratch, durable datasets, and job-local scratch.",
            routes=[
                {
                    "filesystem": "$HOME",
                    "use_for": "small code, configs, personal tools",
                    "avoid_for": "large datasets",
                },
                {
                    "filesystem": "$PI_HOME",
                    "use_for": "shared non-purged project assets",
                    "avoid_for": "large temporary analysis outputs",
                },
                {
                    "filesystem": "$SCRATCH",
                    "use_for": "large temporary files",
                    "avoid_for": "durable storage",
                },
                {
                    "filesystem": "$PI_SCRATCH",
                    "use_for": "group temporary working area",
                    "avoid_for": "durable storage",
                },
                {
                    "filesystem": "$LOCAL_SCRATCH",
                    "use_for": "per-job temporary files",
                    "avoid_for": "anything to keep after the job",
                },
                {
                    "filesystem": "$OAK/data",
                    "use_for": "durable shared datasets",
                    "avoid_for": "ephemeral analysis scratch",
                },
            ],
            commands=[
                {"label": "home_usage", "command": "df -h $HOME"},
                {"label": "scratch_usage", "command": "df -h $SCRATCH"},
                {
                    "label": "user_quota",
                    "command": "lfs quota -u <sunetid> -h /scratch/",
                },
                {
                    "label": "group_quota",
                    "command": f"lfs quota -g {pi_group} -h /scratch/",
                },
            ],
            notes=[
                "Prefer environment variables over hardcoded absolute paths.",
                "Scratch filesystems are purgeable; move durable outputs to OAK or PI_HOME.",
            ],
            warnings=[],
            sources=[SCRIPT_SOURCES[0], SCRIPT_SOURCES[2], SCRIPT_SOURCES[4]],
        )
    if topic == "interactive":
        return _ok(
            topic=topic,
            summary="Interactive Slurm entry points for short debugging sessions.",
            commands=[
                {"label": "sdev", "command": "sdev"},
                {
                    "label": "interactive_bash",
                    "command": (
                        f"srun -A {pi_group} -p {profile['interactive_partition']} "
                        f"--qos={profile['interactive_qos']} --mem=32G --pty bash"
                    ),
                },
            ],
            notes=[
                "Use interactive allocations for debugging, not for long unattended production runs.",
                "Add --exclusive only when you explicitly need a whole node.",
            ],
            warnings=[],
            sources=[SCRIPT_SOURCES[0], SCRIPT_SOURCES[3]],
        )
    if topic == "batch":
        return _ok(
            topic=topic,
            summary="Batch submission pattern, queue inspection, and job-array template guidance.",
            commands=[
                {
                    "label": "submit",
                    "command": "sbatch -o out.%j -e err.%j yourScript.sh arg1 arg2",
                },
                {"label": "queue", "command": "squeue -u <sunetid>"},
                {"label": "accounting", "command": "sacct -j <jobid>"},
                {"label": "cancel", "command": "scancel <jobid>"},
            ],
            notes=[
                "For many independent jobs, prefer Slurm arrays with an explicit concurrency cap.",
                "Include partition and qos explicitly for group queues.",
            ],
            warnings=[],
            sources=[SCRIPT_SOURCES[0], SCRIPT_SOURCES[3]],
        )
    if topic == "transfer":
        return _ok(
            topic=topic,
            summary="Data movement patterns for pushing data to OAK or mounting Sherlock remotely.",
            commands=[
                {
                    "label": "rsync_to_oak",
                    "command": "rsync -avP <local_dir>/ <sunet>@login.sherlock.stanford.edu:$OAK/data/<dataset>/",
                },
                {
                    "label": "sshfs_mount",
                    "command": "sshfs <sunet>@login.sherlock.stanford.edu:$OAK/data/<dataset> ~/sherlock_oak_mount",
                },
                {
                    "label": "sshfs_unmount",
                    "command": "fusermount -u ~/sherlock_oak_mount",
                },
            ],
            notes=[
                "Prefer rsync for large transfers because it is resumable.",
                "When giving sshfs instructions, always include the unmount command.",
            ],
            warnings=[],
            sources=[SCRIPT_SOURCES[0]],
        )
    if topic == "quota":
        return _ok(
            topic=topic,
            summary="Quota and usage checks for home, scratch, and group scratch.",
            commands=[
                {"label": "home_usage", "command": "df -h $HOME"},
                {"label": "scratch_usage", "command": "df -h $SCRATCH"},
                {
                    "label": "user_quota",
                    "command": "lfs quota -u <sunetid> -h /scratch/",
                },
                {
                    "label": "group_quota",
                    "command": f"lfs quota -g {pi_group} -h /scratch/",
                },
            ],
            notes=[
                "Do not report concrete quota values unless you have current command output."
            ],
            warnings=[],
            sources=[SCRIPT_SOURCES[2]],
        )
    if topic == "acl":
        return _ok(
            topic=topic,
            summary="Restricted-dataset access control on OAK using ACLs.",
            commands=[
                {
                    "label": "acl_dry_run",
                    "command": (
                        "bash skills/sherlock-oak-workflow/scripts/restrict_acl.sh "
                        "--dir ${CLUSTER_GROUP_ROOT}/data/<dataset> "
                        "--user <sunetid> --group oak_russpold"
                    ),
                }
            ],
            notes=[
                "Preview first, then add --apply when PI/group policy is confirmed.",
                "Document access restrictions in the dataset README.",
            ],
            warnings=[],
            sources=[SCRIPT_SOURCES[0], SCRIPT_SOURCES[4]],
        )
    if topic == "readonly":
        return _ok(
            topic=topic,
            summary="Finalize a shared dataset as read-only once the canonical version is frozen.",
            commands=[
                {
                    "label": "readonly_dry_run",
                    "command": (
                        "bash skills/sherlock-oak-workflow/scripts/lock_dataset_readonly.sh "
                        "--dir ${CLUSTER_GROUP_ROOT}/data/<dataset>"
                    ),
                }
            ],
            notes=[
                "The helper script defaults to dry-run mode.",
                "Apply read-only only after derivative versions and README provenance are in place.",
            ],
            warnings=[],
            sources=[SCRIPT_SOURCES[0], SCRIPT_SOURCES[4]],
        )
    if topic == "logs":
        return _ok(
            topic=topic,
            summary="Queue, accounting, and log commands for a single job.",
            commands=[
                {"label": "queue", "command": "squeue -j <jobid>"},
                {
                    "label": "accounting",
                    "command": "sacct -j <jobid> --format=JobID,State,ExitCode,Elapsed,MaxRSS",
                },
                {"label": "show_job", "command": "scontrol show job <jobid>"},
                {"label": "tail_log", "command": "tail -n 200 slurm-<jobid>.out"},
            ],
            notes=["Use scontrol when you need the resolved StdOut/StdErr log paths."],
            warnings=[],
            sources=[SCRIPT_SOURCES[3]],
        )
    if topic == "debugging":
        return _ok(
            topic=topic,
            summary="Common failure triage for pending jobs, OOM, timeouts, and environment bootstrap errors.",
            commands=[
                {
                    "label": "queue_reason",
                    "command": "squeue -j <jobid> -o '%i %T %r %R'",
                },
                {
                    "label": "accounting",
                    "command": "sacct -j <jobid> --format=JobID,State,ExitCode,Elapsed,MaxRSS,NodeList",
                },
                {"label": "show_job", "command": "scontrol show job -o <jobid>"},
            ],
            notes=[
                "Most Sherlock debugging starts with the Slurm reason code, then stdout/stderr.",
                "OOM and timeout failures are often visible in both sacct state and job stderr.",
            ],
            warnings=[],
            sources=[SCRIPT_SOURCES[3]],
        )
    return _error(
        f"unsupported_topic:{topic}",
        supported_topics=list(GuideTopic.__args__),  # type: ignore[attr-defined]
        sources=SCRIPT_SOURCES,
    )


def sherlock_render_command(
    intent: CommandIntent,
    *,
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
    profile = _profile(DEFAULT_PROFILE)
    user = sunet or "<sunet>"
    queue_partition = partition or profile["batch_partition"]
    queue_qos = qos or profile["batch_qos"]
    interactive_partition = partition or profile["interactive_partition"]
    interactive_qos = qos or profile["interactive_qos"]
    walltime = time or "24:00:00"
    cpus_per_task = cpus or 8
    memory = mem or "32G"
    dataset_name = dataset or "<dataset>"

    commands: list[str]
    notes: list[str] = []

    if intent == "login":
        commands = [f"ssh {user}@login.sherlock.stanford.edu"]
    elif intent == "interactive_cpu":
        commands = [
            (
                f"srun -A {pi_group} -p {interactive_partition} "
                f"--qos={interactive_qos} --time={walltime} "
                f"--cpus-per-task={cpus_per_task} --mem={memory} --pty bash"
            )
        ]
    elif intent == "interactive_gpu":
        gpu_count = gpus or 1
        commands = [
            (
                f"srun -A {pi_group} -p {interactive_partition} "
                f"--qos={interactive_qos} --time={walltime} "
                f"--cpus-per-task={cpus_per_task} --mem={memory} "
                f"--gpus={gpu_count} --pty bash"
            )
        ]
        notes.append("Adjust --gpus and possibly partition/qos for your GPU queue.")
    elif intent == "batch_cpu":
        target_script = script_path or "job.sh"
        commands = [
            (
                f"sbatch -A {pi_group} -p {queue_partition} --qos={queue_qos} "
                f"--time={walltime} --cpus-per-task={cpus_per_task} --mem={memory} "
                f"{target_script}"
            )
        ]
    elif intent == "submit_script":
        target_script = script_path or "job.sh"
        commands = [f"sbatch {target_script}"]
    elif intent == "cancel_job":
        commands = [f"scancel {job_id or '<jobid>'}"]
    elif intent == "queue_status":
        commands = [f"squeue -u {user}", f"squeue --start -u {user}"]
    elif intent == "job_accounting":
        commands = [
            f"sacct -j {job_id or '<jobid>'} --format=JobID,State,ExitCode,Elapsed,MaxRSS,NodeList",
            f"scontrol show job -o {job_id or '<jobid>'}",
        ]
    elif intent == "log_tail":
        commands = [f"tail -n 200 {log_path or 'slurm-<jobid>.out'}"]
    elif intent == "quota_check":
        commands = [
            "df -h $HOME",
            "df -h $SCRATCH",
            f"lfs quota -u {user} -h /scratch/",
            f"lfs quota -g {pi_group} -h /scratch/",
        ]
    elif intent == "rsync_to_oak":
        commands = [
            f"rsync -avP <local_dir>/ {user}@login.sherlock.stanford.edu:$OAK/data/{dataset_name}/"
        ]
    elif intent == "sshfs_mount":
        mount_target = mount_path or "~/sherlock_oak_mount"
        commands = [
            f"mkdir -p {mount_target}",
            f"sshfs {user}@login.sherlock.stanford.edu:$OAK/data/{dataset_name} {mount_target}",
            f"fusermount -u {mount_target}",
        ]
    elif intent == "scontrol_show_job":
        commands = [f"scontrol show job -o {job_id or '<jobid>'}"]
    else:
        return _error(
            f"unsupported_intent:{intent}",
            supported_intents=list(CommandIntent.__args__),  # type: ignore[attr-defined]
            sources=SCRIPT_SOURCES,
        )

    return _ok(
        intent=intent,
        summary=f"Rendered Sherlock command sequence for {intent}.",
        commands=commands,
        notes=notes + profile.get("notes", []),
        warnings=[],
        sources=SCRIPT_SOURCES,
    )


def sherlock_render_sbatch_script(
    template_kind: TemplateKind,
    *,
    cluster_profile: str = DEFAULT_PROFILE,
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
    mail_type: str | None = None,
    workdir: str | None = None,
    module_lines: list[str] | None = None,
    env_lines: list[str] | None = None,
    command: str | None = None,
    task_file: str | None = None,
    launcher: str | None = None,
    include_export_none: bool = True,
) -> dict[str, Any]:
    profile = _profile(cluster_profile)
    resolved_account = account or profile.get("account")
    resolved_partition = partition or profile["batch_partition"]
    resolved_qos = qos or profile["batch_qos"]
    resolved_output = output or profile["default_output"]
    resolved_error = error or profile["default_error"]
    work_directory = workdir or "$PWD"
    module_block = module_lines or _default_module_block(cluster_profile)
    env_block = env_lines or []
    warnings: list[str] = []

    if template_kind == "cpu_array":
        array_spec = array or "1-10%2"
        if array_concurrency and "%" not in array_spec:
            array_spec = f"{array_spec}%{int(array_concurrency)}"
        if not ARRAY_RE.match(array_spec):
            return _error(
                f"invalid_array_spec:{array_spec}",
                supported_templates=list(TemplateKind.__args__),  # type: ignore[attr-defined]
                sources=SCRIPT_SOURCES,
            )
        task_file_path = task_file or "tasks_list.sh"
        body_command = (
            command or f'eval "$(sed -n "${{SLURM_ARRAY_TASK_ID}}p" {task_file_path})"'
        )
    elif template_kind == "gpu_multinode":
        nodes = max(nodes, 2)
        ntasks_per_node = ntasks_per_node or 1
        gpus_per_node = gpus_per_node or gpus or 1
        body_command = command or launcher or "srun python train.py"
    elif template_kind == "gpu_single":
        body_command = command or launcher or "python train.py"
        gpus = gpus or 1
    else:
        body_command = command or "python run_analysis.py"

    lines = ["#!/bin/bash"]
    lines.append(f"#SBATCH --job-name={job_name}")
    lines.append(f"#SBATCH --time={time}")
    lines.append(f"#SBATCH --partition={resolved_partition}")
    lines.append(f"#SBATCH --qos={resolved_qos}")
    if resolved_account:
        lines.append(f"#SBATCH --account={resolved_account}")
    lines.append(f"#SBATCH --cpus-per-task={cpus_per_task}")
    lines.append(f"#SBATCH --mem={mem}")
    lines.append(f"#SBATCH --output={resolved_output}")
    lines.append(f"#SBATCH --error={resolved_error}")

    if template_kind == "cpu_array":
        lines.append(f"#SBATCH --array={array_spec}")
    if nodes > 1:
        lines.append(f"#SBATCH --nodes={nodes}")
    if ntasks_per_node:
        lines.append(f"#SBATCH --ntasks-per-node={ntasks_per_node}")
    if template_kind == "gpu_single" and gpus:
        lines.append(f"#SBATCH --gpus={gpus}")
    if template_kind == "gpu_multinode" and gpus_per_node:
        lines.append(f"#SBATCH --gpus-per-node={gpus_per_node}")
    if include_export_none:
        lines.append("#SBATCH --export=NONE")
    if mail_user:
        lines.append(f"#SBATCH --mail-user={mail_user}")
    if mail_type:
        lines.append(f"#SBATCH --mail-type={mail_type}")

    lines.extend(["", f"cd {work_directory}", ""])
    lines.extend(module_block)
    if module_block:
        lines.append("")
    lines.extend(env_block)
    if env_block:
        lines.append("")
    lines.append(body_command)
    script_text = "\n".join(lines) + "\n"

    submit_command = "sbatch job.sh"
    test_command = "sbatch --test-only job.sh"

    if (
        template_kind.startswith("gpu")
        and "--gpus" not in script_text
        and "--gpus-per-node" not in script_text
    ):
        warnings.append("GPU template requested but no GPU directive was rendered.")

    return _ok(
        template_kind=template_kind,
        cluster_profile=cluster_profile,
        script_text=script_text,
        submit_command=submit_command,
        test_command=test_command,
        assumptions=[
            f"partition={resolved_partition}",
            f"qos={resolved_qos}",
            f"account={resolved_account}" if resolved_account else "account omitted",
        ],
        warnings=warnings,
        sources=[SCRIPT_SOURCES[0], SCRIPT_SOURCES[3]],
    )


def sherlock_validate_sbatch_script(
    *,
    script_text: str | None = None,
    script_path: str | None = None,
    cluster_profile: str = DEFAULT_PROFILE,
) -> dict[str, Any]:
    text, source = _read_text_source(script_text, script_path)
    if text is None:
        return _error("missing_script_text", source=source, sources=SCRIPT_SOURCES)

    directives = _parse_sbatch_directives(text)
    profile = _profile(cluster_profile)
    errors: list[str] = []
    warnings: list[str] = []
    suggested_fixes: list[str] = []

    if not text.startswith("#!/"):
        errors.append("Missing shebang at the top of the script.")
        suggested_fixes.append("Add '#!/bin/bash' as the first line.")
    if "partition" not in directives:
        warnings.append("Missing --partition directive.")
        suggested_fixes.append(
            f"Add '#SBATCH --partition={profile['batch_partition']}' if you intend to use the group queue."
        )
    if "qos" not in directives:
        warnings.append("Missing --qos directive.")
        suggested_fixes.append(
            f"Add '#SBATCH --qos={profile['batch_qos']}' for the default group batch profile."
        )
    if "job-name" not in directives:
        warnings.append("Missing --job-name directive.")
    if "time" not in directives:
        warnings.append("Missing --time directive.")
    if "output" not in directives:
        warnings.append("Missing --output directive.")
    if "error" not in directives:
        warnings.append("Missing --error directive.")
    if "array" in directives and not ARRAY_RE.match(directives["array"]):
        errors.append(f"Invalid array syntax: {directives['array']}")
    if directives.get("nodes"):
        try:
            if int(directives["nodes"]) > 1 and "ntasks-per-node" not in directives:
                warnings.append("Multinode job is missing --ntasks-per-node.")
        except ValueError:
            warnings.append(f"Could not parse nodes value: {directives['nodes']}")
    if (
        "gpus" in directives or "gpus-per-node" in directives
    ) and "partition" not in directives:
        warnings.append("GPU job should set an explicit partition.")
    if (
        "python " in text
        and "module load" not in text
        and "conda activate" not in text
        and "source " not in text
    ):
        warnings.append(
            "Python command found without an obvious module or environment activation block."
        )
    if (
        directives.get("output", "").startswith("/")
        and not Path(directives["output"]).expanduser().parent.exists()
    ):
        warnings.append("Stdout path parent does not exist locally.")
    if (
        directives.get("error", "").startswith("/")
        and not Path(directives["error"]).expanduser().parent.exists()
    ):
        warnings.append("Stderr path parent does not exist locally.")

    return _ok(
        source=source,
        cluster_profile=cluster_profile,
        directives=directives,
        errors=errors,
        warnings=warnings,
        suggested_fixes=suggested_fixes,
        sources=[SCRIPT_SOURCES[0], SCRIPT_SOURCES[3]],
    )


def sherlock_patch_sbatch_script(
    *,
    change_request: str,
    script_text: str | None = None,
    script_path: str | None = None,
    cluster_profile: str = DEFAULT_PROFILE,
) -> dict[str, Any]:
    original_text, source = _read_text_source(script_text, script_path)
    if original_text is None:
        return _error("missing_script_text", source=source, sources=SCRIPT_SOURCES)

    updated = original_text
    request = change_request.lower()
    change_summary: list[str] = []
    value_sep = r"(?:\s+to\s+|\s*=\s*|\s+)"

    def _extract(pattern: str) -> str | None:
        match = re.search(pattern, request)
        return match.group(1) if match else None

    if "qos" in request:
        qos_value = _extract(rf"qos{value_sep}([a-z0-9_.-]+)")
        if qos_value:
            updated = _replace_or_add_directive(updated, "qos", qos_value)
            change_summary.append(f"Set qos={qos_value}")
    if "partition" in request:
        partition_value = _extract(rf"partition{value_sep}([a-z0-9_.-]+)")
        if partition_value:
            updated = _replace_or_add_directive(updated, "partition", partition_value)
            change_summary.append(f"Set partition={partition_value}")
    if "account" in request:
        account_value = _extract(rf"account{value_sep}([a-z0-9_.-]+)")
        if account_value:
            updated = _replace_or_add_directive(updated, "account", account_value)
            change_summary.append(f"Set account={account_value}")
    mem_value = _extract(rf"(?:memory|mem){value_sep}(\d+[gmkt]?)")
    if mem_value:
        updated = _replace_or_add_directive(updated, "mem", mem_value.upper())
        change_summary.append(f"Set mem={mem_value.upper()}")
    cpu_value = _extract(rf"(?:cpus-per-task|cpus){value_sep}(\d+)")
    if cpu_value:
        updated = _replace_or_add_directive(updated, "cpus-per-task", cpu_value)
        change_summary.append(f"Set cpus-per-task={cpu_value}")
    time_value = _extract(rf"(?:time|walltime){value_sep}([0-9:.-]+)")
    if time_value:
        updated = _replace_or_add_directive(updated, "time", time_value)
        change_summary.append(f"Set time={time_value}")
    nodes_value = _extract(rf"(?:nodes?){value_sep}(\d+)")
    if nodes_value:
        updated = _replace_or_add_directive(updated, "nodes", nodes_value)
        change_summary.append(f"Set nodes={nodes_value}")
    ntasks_value = _extract(rf"(?:ntasks-per-node){value_sep}(\d+)")
    if ntasks_value:
        updated = _replace_or_add_directive(updated, "ntasks-per-node", ntasks_value)
        change_summary.append(f"Set ntasks-per-node={ntasks_value}")
    gpu_value = _extract(rf"(?:gpus|gpu){value_sep}(\d+)")
    if gpu_value:
        if "multinode" in request or "per-node" in request:
            updated = _replace_or_add_directive(updated, "gpus-per-node", gpu_value)
            change_summary.append(f"Set gpus-per-node={gpu_value}")
        else:
            updated = _replace_or_add_directive(updated, "gpus", gpu_value)
            change_summary.append(f"Set gpus={gpu_value}")
    array_value = _extract(rf"(?:array){value_sep}(\d+(?:-\d+)?(?:%\d+)?)")
    if array_value:
        updated = _replace_or_add_directive(updated, "array", array_value)
        change_summary.append(f"Set array={array_value}")
    if "convert to array" in request and "array" not in _parse_sbatch_directives(
        updated
    ):
        updated = _replace_or_add_directive(updated, "array", "1-10%2")
        updated = _ensure_line_after_directives(
            updated, 'eval "$(sed -n "${SLURM_ARRAY_TASK_ID}p" tasks_list.sh)"'
        )
        change_summary.append("Converted script to a basic Slurm array skeleton.")
    if "load singularity" in request:
        updated = _ensure_line_after_directives(updated, "module load singularity")
        change_summary.append("Added module load singularity.")
    if "module use" in request and "module use" not in updated:
        module_use = _profile(cluster_profile).get("module_use")
        if module_use:
            updated = _ensure_line_after_directives(updated, f"module use {module_use}")
            change_summary.append(f"Added module use {module_use}.")
    if "conda activate" in request:
        env_name = _extract(r"conda activate(?:\s+)([a-zA-Z0-9_.-]+)") or "myenv"
        updated = _ensure_line_after_directives(updated, f"conda activate {env_name}")
        change_summary.append(f"Added conda activate {env_name}.")

    if not change_summary:
        return _error(
            "no_edit_rule_matched",
            source=source,
            supported_examples=[
                "set qos to russpold",
                "increase memory to 64G",
                "set cpus-per-task to 16",
                "convert to array 1-100%10",
                "enable gpu 2",
                "set nodes to 2 and ntasks-per-node to 1",
            ],
            sources=SCRIPT_SOURCES,
        )

    diff = "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=source or "original",
            tofile=(source or "original") + ".patched",
        )
    )

    return _ok(
        source=source,
        change_request=change_request,
        patched_text=updated,
        unified_diff=diff,
        change_summary=change_summary,
        validation=sherlock_validate_sbatch_script(
            script_text=updated, cluster_profile=cluster_profile
        ),
        sources=[SCRIPT_SOURCES[0], SCRIPT_SOURCES[3]],
    )


def _parse_scontrol_keyvals(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in text.replace("\n", " ").split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        result[key] = value
    return result


def sherlock_job_inspect(
    job_id: str,
    *,
    include_squeue: bool = True,
    include_sacct: bool = True,
    include_scontrol: bool = True,
) -> dict[str, Any]:
    if not job_id:
        return _error("missing_job_id", sources=SCRIPT_SOURCES)

    result: dict[str, Any] = {
        "job_id": job_id,
        "squeue": None,
        "sacct": None,
        "scontrol": None,
        "warnings": [],
        "sources": [SCRIPT_SOURCES[3]],
    }

    if include_squeue:
        q = _run_local_command(
            ["squeue", "-h", "-j", job_id, "-o", "%i|%T|%r|%M|%l|%D|%R"]
        )
        if q["ok"] and q["stdout"].strip():
            fields = q["stdout"].strip().split("|")
            result["squeue"] = {
                "job_id": fields[0] if len(fields) > 0 else job_id,
                "state": fields[1] if len(fields) > 1 else "",
                "reason": fields[2] if len(fields) > 2 else "",
                "elapsed": fields[3] if len(fields) > 3 else "",
                "time_limit": fields[4] if len(fields) > 4 else "",
                "nodes": fields[5] if len(fields) > 5 else "",
                "node_or_reason": fields[6] if len(fields) > 6 else "",
            }
        elif not q["ok"]:
            result["warnings"].append(f"squeue unavailable: {q['error']}")

    if include_sacct:
        s = _run_local_command(
            [
                "sacct",
                "-P",
                "-j",
                job_id,
                "--format=JobID,JobName,Partition,State,ExitCode,Elapsed,MaxRSS,NodeList,AllocCPUS",
            ]
        )
        if s["ok"] and s["stdout"].strip():
            lines = [line for line in s["stdout"].splitlines() if line.strip()]
            if len(lines) >= 2:
                header = lines[0].split("|")
                rows = [
                    dict(zip(header, row.split("|"), strict=False)) for row in lines[1:]
                ]
                result["sacct"] = rows
        elif not s["ok"]:
            result["warnings"].append(f"sacct unavailable: {s['error']}")

    if include_scontrol:
        c = _run_local_command(["scontrol", "show", "job", "-o", job_id])
        if c["ok"] and c["stdout"].strip():
            parsed = _parse_scontrol_keyvals(c["stdout"])
            result["scontrol"] = parsed
            stdout_path = parsed.get("StdOut")
            stderr_path = parsed.get("StdErr")
            if stdout_path or stderr_path:
                result["log_paths"] = {"stdout": stdout_path, "stderr": stderr_path}
        elif not c["ok"]:
            result["warnings"].append(f"scontrol unavailable: {c['error']}")

    return _ok(**result)


def sherlock_job_logs(
    *,
    job_id: str | None = None,
    log_path: str | None = None,
    stream: Literal["stdout", "stderr", "both"] = "both",
    tail: int = 200,
    grep: str | None = None,
) -> dict[str, Any]:
    resolved_stdout: str | None = None
    resolved_stderr: str | None = None
    warnings: list[str] = []

    if job_id and not log_path:
        inspection = sherlock_job_inspect(
            job_id, include_squeue=False, include_sacct=False, include_scontrol=True
        )
        log_paths = inspection.get("log_paths") or {}
        resolved_stdout = log_paths.get("stdout")
        resolved_stderr = log_paths.get("stderr")
        warnings.extend(inspection.get("warnings", []))
    elif log_path:
        resolved_stdout = log_path

    if not any([resolved_stdout, resolved_stderr]):
        return _error(
            "no_log_source_found", warnings=warnings, sources=[SCRIPT_SOURCES[3]]
        )

    payload: dict[str, Any] = {
        "job_id": job_id,
        "warnings": warnings,
        "sources": [SCRIPT_SOURCES[3]],
    }
    selected_paths: dict[str, str] = {}

    def _read_log(path_str: str) -> str:
        path = Path(path_str).expanduser()
        if not path.exists():
            return f"[missing file] {path}"
        text = path.read_text(encoding="utf-8", errors="replace")
        if grep:
            filtered = [
                line for line in text.splitlines() if grep.lower() in line.lower()
            ]
            text = "\n".join(filtered)
        return _tail_text(text, tail)

    if stream in {"stdout", "both"} and resolved_stdout:
        selected_paths["stdout"] = resolved_stdout
        payload["stdout_text"] = _read_log(resolved_stdout)
    if stream in {"stderr", "both"}:
        stderr_candidate = resolved_stderr or (log_path if stream == "stderr" else None)
        if stderr_candidate:
            selected_paths["stderr"] = stderr_candidate
            payload["stderr_text"] = _read_log(stderr_candidate)

    payload["log_paths"] = selected_paths
    return _ok(**payload)


def sherlock_diagnose_job_failure(
    *,
    job_id: str | None = None,
    script_text: str | None = None,
    stdout_text: str | None = None,
    stderr_text: str | None = None,
    sacct_state: str | None = None,
) -> dict[str, Any]:
    state = (sacct_state or "").upper()
    evidence: list[str] = []
    next_steps: list[str] = []
    suggested_commands: list[str] = []
    confidence = "low"
    likely_cause = "unknown"

    if job_id and (stdout_text is None or stderr_text is None or not sacct_state):
        inspection = sherlock_job_inspect(job_id)
        if not sacct_state:
            sacct_rows = inspection.get("sacct") or []
            if sacct_rows:
                sacct_state = sacct_rows[0].get("State")
                state = (sacct_state or "").upper()
        if stdout_text is None or stderr_text is None:
            logs = sherlock_job_logs(job_id=job_id, stream="both", tail=200)
            stdout_text = stdout_text or logs.get("stdout_text")
            stderr_text = stderr_text or logs.get("stderr_text")

    combined = "\n".join(
        part
        for part in [stdout_text or "", stderr_text or "", script_text or ""]
        if part
    )
    lowered = combined.lower()

    if "invalid qos" in lowered or "invalid qos specification" in lowered:
        likely_cause = "invalid_qos"
        confidence = "high"
        evidence.append("Detected 'invalid qos' in job output.")
        next_steps.append(
            "Switch the job to a valid Sherlock qos for your partition/account."
        )
    elif "invalid partition" in lowered:
        likely_cause = "invalid_partition"
        confidence = "high"
        evidence.append("Detected 'invalid partition' in job output.")
        next_steps.append("Use a partition allowed for your account or PI group.")
    elif (
        "out of memory" in lowered
        or "oom" in lowered
        or "oom-kill" in lowered
        or state.startswith("OUT_OF_MEMORY")
    ):
        likely_cause = "oom"
        confidence = "high"
        evidence.append("Detected OOM wording or OUT_OF_MEMORY state.")
        next_steps.append("Increase --mem or reduce per-task memory use.")
    elif "time limit" in lowered or state.startswith("TIMEOUT"):
        likely_cause = "timeout"
        confidence = "high"
        evidence.append("Detected timeout wording or TIMEOUT state.")
        next_steps.append("Increase --time or reduce job workload.")
    elif "module" in lowered and "not found" in lowered:
        likely_cause = "module_not_found"
        confidence = "medium"
        evidence.append("Detected module load failure.")
        next_steps.append("Verify module use/module load lines on Sherlock.")
    elif "conda" in lowered and ("not found" in lowered or "activate" in lowered):
        likely_cause = "environment_bootstrap_failure"
        confidence = "medium"
        evidence.append("Detected conda activation failure.")
        next_steps.append("Load the correct shell/module setup before conda activate.")
    elif "permission denied" in lowered:
        likely_cause = "permission_denied"
        confidence = "medium"
        evidence.append("Detected permission denied in output.")
        next_steps.append(
            "Check file ownership, log destinations, and dataset permissions."
        )
    elif "no such file" in lowered or "not found" in lowered:
        likely_cause = "missing_input_or_path"
        confidence = "medium"
        evidence.append("Detected missing file/path wording.")
        next_steps.append("Verify all input paths and working-directory assumptions.")
    elif state.startswith("PENDING"):
        likely_cause = "pending_resources_or_account"
        confidence = "medium"
        evidence.append(f"Job still pending with state {state}.")
        next_steps.append("Inspect squeue reason code and cluster availability.")

    if not suggested_commands:
        suggested_commands.extend(
            [
                f"squeue -j {job_id or '<jobid>'} -o '%i %T %r %R'",
                f"sacct -j {job_id or '<jobid>'} --format=JobID,State,ExitCode,Elapsed,MaxRSS,NodeList",
                f"scontrol show job -o {job_id or '<jobid>'}",
            ]
        )

    if likely_cause == "unknown":
        next_steps.append(
            "Inspect stdout/stderr and Slurm reason codes before changing resources."
        )

    return _ok(
        job_id=job_id,
        sacct_state=sacct_state,
        likely_cause=likely_cause,
        confidence=confidence,
        evidence=evidence,
        next_steps=next_steps,
        suggested_commands=suggested_commands,
        sources=[SCRIPT_SOURCES[3]],
    )


def sherlock_guide(
    *,
    action: GuideAction = "guide",
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
    """Aggregate Sherlock guide/command entrypoint for MCP exposure."""

    if action == "guide":
        if not topic:
            return _error(
                "missing_topic",
                message="Provide topic when action='guide'.",
                supported_topics=list(GuideTopic.__args__),  # type: ignore[attr-defined]
                sources=SCRIPT_SOURCES,
            )
        return sherlock_get_guide(topic=topic, pi_group=pi_group)

    if action == "command":
        if not intent:
            return _error(
                "missing_intent",
                message="Provide intent when action='command'.",
                supported_intents=list(CommandIntent.__args__),  # type: ignore[attr-defined]
                sources=SCRIPT_SOURCES,
            )
        return sherlock_render_command(
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

    return _error(
        f"unsupported_action:{action}",
        supported_actions=list(GuideAction.__args__),  # type: ignore[attr-defined]
        sources=SCRIPT_SOURCES,
    )


def sherlock_slurm(
    *,
    action: SlurmAction,
    cluster_profile: str = DEFAULT_PROFILE,
    template_kind: str | None = None,
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
    mail_type: str | None = None,
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
    stream: str = "both",
    tail: int = 200,
    grep: str | None = None,
    stdout_text: str | None = None,
    stderr_text: str | None = None,
    sacct_state: str | None = None,
) -> dict[str, Any]:
    """Aggregate Slurm authoring/debugging entrypoint for MCP exposure."""

    if action == "render_script":
        if not template_kind:
            return _error(
                "missing_template_kind",
                message="Provide template_kind when action='render_script'.",
                supported_templates=list(TemplateKind.__args__),  # type: ignore[attr-defined]
                sources=SCRIPT_SOURCES,
            )
        return sherlock_render_sbatch_script(
            template_kind=template_kind,
            cluster_profile=cluster_profile,
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
        )

    if action == "validate_script":
        return sherlock_validate_sbatch_script(
            script_text=script_text,
            script_path=script_path,
            cluster_profile=cluster_profile,
        )

    if action == "patch_script":
        if not change_request:
            return _error(
                "missing_change_request",
                message="Provide change_request when action='patch_script'.",
                sources=SCRIPT_SOURCES,
            )
        return sherlock_patch_sbatch_script(
            change_request=change_request,
            script_text=script_text,
            script_path=script_path,
            cluster_profile=cluster_profile,
        )

    if action == "inspect_job":
        if not job_id:
            return _error(
                "missing_job_id",
                message="Provide job_id when action='inspect_job'.",
                sources=SCRIPT_SOURCES,
            )
        return sherlock_job_inspect(
            job_id=job_id,
            include_squeue=include_squeue,
            include_sacct=include_sacct,
            include_scontrol=include_scontrol,
        )

    if action == "read_logs":
        return sherlock_job_logs(
            job_id=job_id,
            log_path=log_path,
            stream=stream,
            tail=tail,
            grep=grep,
        )

    if action == "diagnose_failure":
        return sherlock_diagnose_job_failure(
            job_id=job_id,
            script_text=script_text,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            sacct_state=sacct_state,
        )

    return _error(
        f"unsupported_action:{action}",
        supported_actions=list(SlurmAction.__args__),  # type: ignore[attr-defined]
        sources=SCRIPT_SOURCES,
    )
