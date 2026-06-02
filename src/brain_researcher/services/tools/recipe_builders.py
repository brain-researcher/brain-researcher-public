"""Per-workflow execution-recipe / script builders for public MCP tools.

Carved out of ``mcp/execution_recipes.py``: the ``_build_*`` recipe and script
builders for the specific workflows (preprocessing-QC, task-GLM, dwi-connectome,
fMRIPrep/MRIQC/QSIPrep/sMRIPrep/QSIRecon/FastSurfer, external-repo BIDS, the
generic python/neurodesk/container/slurm recipes, …). The public
``build_execution_recipe`` dispatcher stays in ``execution_recipes`` and calls
these (re-exported back).

The shared lower-level helpers these builders use (``_minimal_*_payload`` /
``_render_shell_*`` / ``_default_*`` / ``_slugify`` / ``_json_text`` / …) stay in
``execution_recipes`` and are imported back lazily inside each builder, so the
dependency is one-way ``execution_recipes -> recipe_builders`` and cycle-free at
module load.
"""

from __future__ import annotations

import shlex
from textwrap import dedent
from typing import Any

from brain_researcher.services.tools.runtime_profiles import get_container_image
from brain_researcher.services.tools.slurm_tools import (
    DEFAULT_PROFILE as SHERLOCK_DEFAULT_PROFILE,
)
from brain_researcher.services.tools.slurm_tools import (
    sherlock_render_sbatch_script,
)
from brain_researcher.services.tools.spec import ToolSpec


def _build_direct_family_python_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _attach_python_pack_contract,
        _direct_python_script_for_family,
        _json_text,
        _slugify,
    )

    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    recipe_family = str(metadata.get("recipe_family") or "").strip()
    recipe = {
        "dependencies": {"python_packages": metadata["python_packages"]},
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": [
            "python -m venv .venv",
            ". .venv/bin/activate",
            "python -m pip install --upgrade pip",
            "pip install "
            + " ".join(shlex.quote(pkg) for pkg in metadata["python_packages"]),
        ],
        "run_command": f"python {script_name}",
        "params_json": _json_text(params),
        "files": {
            script_name: _direct_python_script_for_family(tool_id, recipe_family),
            "params.json": _json_text(params),
        },
    }
    recipe = _attach_python_pack_contract(
        recipe,
        tool_id=tool_id,
        params=params,
        metadata=metadata,
        spec=spec,
        workflow_entry=workflow_entry,
        execution_mode="embedded_python",
        script_name=script_name,
    )
    return recipe, "runnable"


def _build_rest_connectome_python_recipe(
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _attach_python_pack_contract,
        _json_text,
        _python_setup_commands,
        _rest_connectome_python_script,
    )

    script_name = "run_workflow_rest_connectome_e2e.py"
    setup_commands, extra_env_vars = _python_setup_commands(metadata["python_packages"])
    recipe = {
        "dependencies": {"python_packages": metadata["python_packages"]},
        "required_env_vars": metadata["required_env_vars"] + extra_env_vars,
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": f"python {script_name}",
        "params_json": _json_text(params),
        "files": {
            script_name: _rest_connectome_python_script(),
            "params.json": _json_text(params),
        },
    }
    recipe = _attach_python_pack_contract(
        recipe,
        tool_id="workflow_rest_connectome_e2e",
        params=params,
        metadata=metadata,
        spec=spec,
        workflow_entry=workflow_entry,
        execution_mode="embedded_python",
        script_name=script_name,
    )
    return recipe, "runnable"


def _build_generic_python_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    spec: ToolSpec | None = None,
    workflow_entry: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _attach_python_pack_contract,
        _default_runtime_script,
        _json_text,
        _python_setup_commands,
        _slugify,
    )

    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    setup_commands, extra_env_vars = _python_setup_commands(metadata["python_packages"])
    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
        },
        "required_env_vars": metadata["required_env_vars"] + extra_env_vars,
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": f"python {script_name}",
        "params_json": _json_text(params),
        "files": {
            script_name: _default_runtime_script(tool_id),
            "params.json": _json_text(params),
        },
    }
    recipe = _attach_python_pack_contract(
        recipe,
        tool_id=tool_id,
        params=params,
        metadata=metadata,
        spec=spec,
        workflow_entry=workflow_entry,
        execution_mode="local_tool",
    )
    return recipe, "runnable"


def _build_generic_neurodesk_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _default_runtime_script,
        _env_exports,
        _json_text,
        _slugify,
    )

    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    module_cmd = " && ".join(
        [f"module load {module}" for module in metadata["neurodesk_modules"]]
    )
    run_command = (
        f"{module_cmd} && python {script_name}"
        if module_cmd
        else f"python {script_name}"
    )
    setup_commands = [
        f"module load {module}" for module in metadata["neurodesk_modules"]
    ]
    setup_commands.extend(_env_exports(metadata["required_env_vars"]))
    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
            "neurodesk_modules": metadata["neurodesk_modules"],
        },
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(params),
        "files": {
            script_name: _default_runtime_script(tool_id),
            "params.json": _json_text(params),
        },
    }
    return recipe, "runnable"


def _build_generic_container_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _default_dockerfile,
        _default_runtime_script,
        _json_text,
        _slugify,
    )

    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    image_tag = f"brain-researcher-recipe-{slug}"
    dockerfile = _default_dockerfile(metadata["python_packages"], script_name)
    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
            "container_images": metadata["container_images"],
        },
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": [
            f"docker build -t {image_tag} -f Dockerfile .",
        ],
        "run_command": (
            f'docker run --rm -v "$PWD":/work -w /work {image_tag} python {script_name}'
        ),
        "params_json": _json_text(params),
        "files": {
            "Dockerfile": dockerfile,
            script_name: _default_runtime_script(tool_id),
            "params.json": _json_text(params),
        },
    }
    return recipe, "runnable"


def _build_generic_slurm_recipe(
    tool_id: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _default_runtime_script,
        _env_exports,
        _json_text,
        _slugify,
    )

    slug = _slugify(tool_id)
    script_name = f"run_{slug}.py"
    module_lines = [f"module load {module}" for module in metadata["neurodesk_modules"]]
    env_lines = _env_exports(metadata["required_env_vars"])
    command = f"python {script_name}"

    if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
        rendered = sherlock_render_sbatch_script(
            "cpu_single",
            cluster_profile=cluster_profile,
            job_name=f"br-{slug}",
            module_lines=module_lines or None,
            env_lines=env_lines or None,
            command=command,
        )
        script_text = str(rendered.get("script_text") or "")
    else:
        lines = [
            "#!/bin/bash",
            f"#SBATCH --job-name=br-{slug}",
            "#SBATCH --time=24:00:00",
            "#SBATCH --cpus-per-task=8",
            "#SBATCH --mem=16G",
            "#SBATCH --output=slurm-%j.out",
            "#SBATCH --error=slurm-%j.err",
            "",
            "set -euo pipefail",
            "",
        ]
        lines.extend(module_lines)
        if module_lines:
            lines.append("")
        lines.extend(env_lines)
        if env_lines:
            lines.append("")
        lines.append(command)
        script_text = "\n".join(lines) + "\n"

    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
            "neurodesk_modules": metadata["neurodesk_modules"],
        },
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": [],
        "run_command": "sbatch job.sbatch",
        "params_json": _json_text(params),
        "files": {
            "job.sbatch": script_text,
            script_name: _default_runtime_script(tool_id),
            "params.json": _json_text(params),
        },
    }
    return recipe, "runnable"


def _build_preprocessing_qc_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _env_exports,
        _external_repo_recipe_readme,
        _json_text,
        _minimal_fmriprep_payload,
        _minimal_mriqc_payload,
        _minimal_preprocessing_qc_payload,
        _preprocessing_post_qc_script,
    )

    payload = _minimal_preprocessing_qc_payload(params)
    fmriprep_payload = _minimal_fmriprep_payload(
        {
            "bids_dir": payload["bids_dir"],
            "output_dir": payload["fmriprep_output_dir"],
            "participant_label": payload["participant_label"],
            "work_dir": payload["fmriprep_work_dir"],
            "fs_license_file": payload["fs_license_file"],
            "output_spaces": payload["output_spaces"],
            "bids_filter_file": payload["bids_filter_file"],
            "n_cpus": payload["n_cpus"],
            "omp_nthreads": payload["omp_nthreads"],
            "mem_mb": payload["mem_mb"],
            "extra_args": payload["fmriprep_extra_args"],
        }
    )
    mriqc_payload = _minimal_mriqc_payload(
        {
            "bids_dir": payload["bids_dir"],
            "output_dir": payload["mriqc_output_dir"],
            "analysis_level": payload["analysis_level"],
            "participant_label": payload["participant_label"],
            "modalities": payload["modalities"],
            "work_dir": payload["mriqc_work_dir"],
            "bids_filter_file": payload["bids_filter_file"],
            "n_procs": payload["n_procs"],
            "mem_gb": payload["mem_gb"],
            "extra_args": payload["mriqc_extra_args"],
        }
    )

    script_name = "run_workflow_preprocessing_qc.sh"
    fmriprep_script_name = "run_fmriprep.sh"
    mriqc_script_name = "run_mriqc.sh"
    files = {
        "README.md": _external_repo_recipe_readme(
            "workflow_preprocessing_qc",
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=script_name,
            minimal_summary=(
                "single-subject fMRIPrep + MRIQC example with downstream QC "
                "aggregation (4 CPUs for fMRIPrep, 4 processes / 8 GB for MRIQC)"
            ),
        ),
        "params.json": _json_text(payload),
        "post_qc.py": _preprocessing_post_qc_script(),
        fmriprep_script_name: _build_fmriprep_script(
            "container" if target_runtime == "container" else "host",
            fmriprep_payload,
        ),
        mriqc_script_name: _build_mriqc_script(
            "container" if target_runtime == "container" else "host",
            mriqc_payload,
        ),
        script_name: "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                f"bash {fmriprep_script_name}",
                f"bash {mriqc_script_name}",
                "python post_qc.py",
                "",
            ]
        ),
    }

    dependency_block = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }
    setup_commands: list[str] = []
    run_command = f"bash {script_name}"
    warnings = [
        "This recipe runs a lightweight QC post-processing step after fMRIPrep and MRIQC complete.",
        "The generated shell scripts are intentionally single-subject and resource-limited.",
        "A valid FreeSurfer license file is required for the fMRIPrep portion of the workflow.",
    ]

    if target_runtime == "neurodesk":
        setup_commands.extend(
            f"module load {module}" for module in metadata["neurodesk_modules"]
        )
        setup_commands.extend(_env_exports(metadata["required_env_vars"]))
    elif target_runtime == "container":
        for image_name in ("fmriprep", "mriqc"):
            image = str(metadata["container_images"].get(image_name) or "")
            if image:
                setup_commands.append(f"docker pull {image}")
    else:
        module_lines = [
            f"module load {module}" for module in metadata["neurodesk_modules"]
        ]
        env_lines = _env_exports(metadata["required_env_vars"])
        if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
            rendered = sherlock_render_sbatch_script(
                "cpu_single",
                cluster_profile=cluster_profile,
                job_name="br-workflow-preprocessing-qc",
                module_lines=module_lines or None,
                env_lines=env_lines or None,
                command=f"bash {script_name}",
            )
            files["job.sbatch"] = str(rendered.get("script_text") or "")
        else:
            files["job.sbatch"] = "\n".join(
                [
                    "#!/bin/bash",
                    "#SBATCH --job-name=br-workflow-preprocessing-qc",
                    "#SBATCH --time=24:00:00",
                    "#SBATCH --cpus-per-task=8",
                    "#SBATCH --mem=32G",
                    "#SBATCH --output=slurm-%j.out",
                    "#SBATCH --error=slurm-%j.err",
                    "",
                    "set -euo pipefail",
                    "",
                    *module_lines,
                    *env_lines,
                    f"bash {script_name}",
                    "",
                ]
            )
        run_command = "sbatch job.sbatch"

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": warnings,
    }
    return recipe, "runnable"


def _build_task_glm_group_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _default_runtime_script,
        _env_exports,
        _external_repo_recipe_readme,
        _json_text,
        _minimal_task_glm_group_payload,
        _task_glm_group_container_dockerfile,
    )

    payload = _minimal_task_glm_group_payload(params)
    script_name = "run_workflow_task_glm_group.py"
    files = {
        "README.md": _external_repo_recipe_readme(
            "workflow_task_glm_group",
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=script_name,
            minimal_summary=(
                "small group-level task GLM example that prefers "
                "bids_dir + fmriprep_dir + task inputs and can preview "
                "or execute the resolved first-level + second-level plan"
            ),
        ),
        script_name: _default_runtime_script("workflow_task_glm_group"),
        "params.json": _json_text(payload),
    }
    dependency_block: dict[str, Any] = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }
    setup_commands: list[str] = []
    run_command = f"python {script_name}"
    warnings = [
        "This workflow now prefers bids_dir + fmriprep_dir + task inputs; direct img/events remain available for compatibility.",
        "Set dry_run=true in params.json to preview subject resolution and planned second-level execution without running Nilearn GLMs.",
        "If contrast_name is empty, the runtime attempts to infer a common trial_type across subjects and otherwise falls back to the first available contrast per subject.",
    ]

    if target_runtime == "container":
        image_tag = "brain-researcher-recipe-workflow-task-glm-group"
        files["Dockerfile"] = _task_glm_group_container_dockerfile(
            metadata["python_packages"], script_name
        )
        setup_commands.append(f"docker build -t {image_tag} -f Dockerfile .")
        run_command = (
            f'docker run --rm -v "$PWD":/work -w /work {image_tag} python {script_name}'
        )
    elif target_runtime == "slurm":
        module_lines = [
            f"module load {module}" for module in metadata["neurodesk_modules"]
        ]
        env_lines = _env_exports(metadata["required_env_vars"])
        if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
            rendered = sherlock_render_sbatch_script(
                "cpu_single",
                cluster_profile=cluster_profile,
                job_name="br-workflow-task-glm-group",
                module_lines=module_lines or None,
                env_lines=env_lines or None,
                command=f"python {script_name}",
            )
            files["job.sbatch"] = str(rendered.get("script_text") or "")
        else:
            files["job.sbatch"] = "\n".join(
                [
                    "#!/bin/bash",
                    "#SBATCH --job-name=br-workflow-task-glm-group",
                    "#SBATCH --time=08:00:00",
                    "#SBATCH --cpus-per-task=4",
                    "#SBATCH --mem=12G",
                    "#SBATCH --output=slurm-%j.out",
                    "#SBATCH --error=slurm-%j.err",
                    "",
                    "set -euo pipefail",
                    "",
                    *module_lines,
                    *env_lines,
                    f"python {script_name}",
                    "",
                ]
            )
        run_command = "sbatch job.sbatch"
    else:
        setup_commands.extend(
            f"module load {module}" for module in metadata["neurodesk_modules"]
        )
        setup_commands.extend(_env_exports(metadata["required_env_vars"]))

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": warnings,
    }
    return recipe, "runnable"


def _build_dwi_connectome_postprocess_script() -> str:
    return (
        dedent(
            """
        import json
        import os
        import sys
        from pathlib import Path

        from brain_researcher.services.tools.dwi_connectome_workflow import (
            collect_qsirecon_derivatives,
            materialize_connectome_from_existing,
            materialize_connectome_from_tractogram,
            pick_primary_connectome,
            pick_primary_tractogram,
        )

        params = json.loads(Path("params.json").read_text(encoding="utf-8"))
        output_dir = Path(str(params["output_dir"])).expanduser().resolve()
        qsirecon_dir = Path(
            os.environ.get("RESOLVED_QSIRECON_DIR")
            or params.get("qsirecon_dir")
            or output_dir / "qsirecon"
        ).expanduser().resolve()
        derivatives = collect_qsirecon_derivatives(qsirecon_dir)
        tractogram = pick_primary_tractogram(derivatives)
        connectome = pick_primary_connectome(derivatives)
        atlas = str(params.get("atlas") or "").strip()
        sc_dir = output_dir / "sc"
        sc_dir.mkdir(parents=True, exist_ok=True)

        if tractogram and atlas:
            outputs, summary = materialize_connectome_from_tractogram(
                tractogram_path=tractogram,
                atlas_path=atlas,
                output_dir=sc_dir,
            )
        elif connectome:
            outputs, summary = materialize_connectome_from_existing(
                connectome_path=connectome,
                output_dir=sc_dir,
            )
        else:
            raise SystemExit(
                "No tractogram/connectome found under the resolved QSIRecon directory"
            )

        payload = {
            "outputs": {
                **outputs,
                "qsirecon_dir": str(qsirecon_dir),
                "tractogram": tractogram,
                "source_connectome": connectome,
            },
            "summary": {
                **summary,
                "route": "qsirecon_derivatives",
                "available_derivatives": derivatives,
            },
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        """
        ).strip()
        + "\n"
    )


def _build_dwi_connectome_runner_script() -> str:
    return (
        dedent(
            """
        import subprocess

        completed = subprocess.run(["bash", "run_workflow_dwi_connectome.sh"], check=False)
        raise SystemExit(completed.returncode)
        """
        ).strip()
        + "\n"
    )


def _build_dwi_connectome_script(target_runtime: str, payload: dict[str, Any]) -> str:
    from brain_researcher.services.tools.execution_recipes import (
        _render_shell_command,
        _render_shell_default,
    )

    command_tokens = ["qsirecon" if target_runtime != "container" else "docker"]
    resolved_qsirecon_dir = '"${QSIRECON_DIR:-$OUTPUT_DIR/qsirecon}"'
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$QSIPREP_DIR:$QSIPREP_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
            ]
        )
        if payload["fs_license_file"]:
            command_tokens.extend(
                ["-v", '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"']
            )
        command_tokens.extend(
            [
                shlex.quote(
                    str(get_container_image("qsirecon") or "pennlinc/qsirecon:1.1.1")
                ),
                '"$QSIPREP_DIR"',
                resolved_qsirecon_dir,
                "participant",
            ]
        )
    else:
        command_tokens.extend(['"$QSIPREP_DIR"', resolved_qsirecon_dir, "participant"])
    command_tokens.extend(["--recon-spec", '"$RECON_SPEC"'])
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if payload["fs_license_file"]:
        if target_runtime == "container":
            command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
        else:
            command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("QSIPREP_DIR", str(payload["qsiprep_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default("ATLAS", str(payload["atlas"])),
        _render_shell_default("RECON_SPEC", str(payload["recon_spec"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
        _render_shell_default("QSIRECON_DIR", str(payload["qsirecon_dir"])),
    ]
    if payload["fs_license_file"]:
        lines.append(
            'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"'
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            'RESOLVED_QSIRECON_DIR="${QSIRECON_DIR:-$OUTPUT_DIR/qsirecon}"',
            'if [[ -n "${QSIRECON_DIR:-}" && -d "$QSIRECON_DIR" ]]; then',
            '  echo "Using existing QSIRecon derivatives at $QSIRECON_DIR"',
            "else",
            f"  {_render_shell_command(command_tokens)}",
            "fi",
            'export RESOLVED_QSIRECON_DIR="${RESOLVED_QSIRECON_DIR}"',
            "python postprocess_dwi_connectome.py",
            "",
        ]
    )
    return "\n".join(lines)


def _build_dwi_connectome_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _env_exports,
        _external_repo_recipe_readme,
        _json_text,
        _minimal_dwi_connectome_payload,
    )

    payload = _minimal_dwi_connectome_payload(params)
    shell_script_name = "run_workflow_dwi_connectome.sh"
    python_script_name = "run_workflow_dwi_connectome.py"
    script_text = _build_dwi_connectome_script(
        "container" if target_runtime == "container" else "host", payload
    )
    files = {
        "README.md": _external_repo_recipe_readme(
            "workflow_dwi_connectome",
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=python_script_name,
            minimal_summary=(
                "single-subject derivative-first DWI connectome example that prefers "
                "existing qsirecon_dir and otherwise runs QSIRecon before "
                "materializing a standardized connectome"
            ),
        ),
        python_script_name: _build_dwi_connectome_runner_script(),
        shell_script_name: script_text,
        "postprocess_dwi_connectome.py": _build_dwi_connectome_postprocess_script(),
        "params.json": _json_text(payload),
    }
    dependency_block: dict[str, Any] = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }
    setup_commands: list[str] = []
    run_command = f"python {python_script_name}"

    if target_runtime == "neurodesk":
        setup_commands.extend(
            f"module load {module}" for module in metadata["neurodesk_modules"]
        )
        setup_commands.extend(_env_exports(metadata["required_env_vars"]))
    elif target_runtime == "container":
        image = str(
            metadata["container_images"].get("qsirecon")
            or get_container_image("qsirecon")
            or "pennlinc/qsirecon:1.1.1"
        )
        setup_commands.append(f"docker pull {image}")
    else:
        module_lines = [
            f"module load {module}" for module in metadata["neurodesk_modules"]
        ]
        env_lines = _env_exports(metadata["required_env_vars"])
        if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
            rendered = sherlock_render_sbatch_script(
                "cpu_single",
                cluster_profile=cluster_profile,
                job_name="br-workflow_dwi_connectome",
                module_lines=module_lines or None,
                env_lines=env_lines or None,
                command=f"python {python_script_name}",
            )
            files["job.sbatch"] = str(rendered.get("script_text") or "")
        else:
            lines = [
                "#!/bin/bash",
                "#SBATCH --job-name=br-workflow_dwi_connectome",
                "#SBATCH --time=24:00:00",
                "#SBATCH --cpus-per-task=4",
                "#SBATCH --mem=16G",
                "#SBATCH --output=slurm-%j.out",
                "#SBATCH --error=slurm-%j.err",
                "",
                "set -euo pipefail",
                "",
                *module_lines,
                *env_lines,
                f"python {python_script_name}",
                "",
            ]
            files["job.sbatch"] = "\n".join(lines)
        run_command = "sbatch job.sbatch"

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": [
            "This minimal recipe prefers existing qsirecon_dir inputs; otherwise it runs QSIRecon against qsiprep_dir before post-processing.",
            "Provide an atlas aligned to the reconstruction space if you want a tractogram-derived connectome instead of normalizing an existing recon connectome.",
            "The legacy raw dwi/bvals/bvecs fallback path remains available in the runtime workflow but is intentionally not the primary MCP recipe.",
        ],
    }
    return recipe, "runnable"


def _build_fmriprep_script(target_runtime: str, payload: dict[str, Any]) -> str:
    from brain_researcher.services.tools.execution_recipes import (
        _render_shell_command,
        _render_shell_default,
    )

    command_tokens = [
        "fmriprep" if target_runtime != "container" else "docker",
    ]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
                "-v",
                '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
                shlex.quote(
                    str(get_container_image("fmriprep") or "nipreps/fmriprep:23.2.3")
                ),
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                "participant",
            ]
        )
    else:
        command_tokens.extend(['"$BIDS_DIR"', '"$OUTPUT_DIR"', "participant"])

    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if target_runtime == "container":
        command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
    else:
        command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    if payload["output_spaces"]:
        command_tokens.append("--output-spaces")
        command_tokens.extend(
            shlex.quote(str(space)) for space in payload["output_spaces"]
        )
    command_tokens.extend(["--n-cpus", str(payload["n_cpus"])])
    command_tokens.extend(["--omp-nthreads", str(payload["omp_nthreads"])])
    command_tokens.extend(["--mem-mb", str(payload["mem_mb"])])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
        'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"',
        "",
        'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
        "",
        _render_shell_command(command_tokens),
        "",
    ]
    return "\n".join(lines)


def _build_mriqc_script(target_runtime: str, payload: dict[str, Any]) -> str:
    from brain_researcher.services.tools.execution_recipes import (
        _render_shell_command,
        _render_shell_default,
    )

    command_tokens = ["mriqc" if target_runtime != "container" else "docker"]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
                shlex.quote(
                    str(get_container_image("mriqc") or "nipreps/mriqc:24.0.2")
                ),
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                shlex.quote(str(payload["analysis_level"])),
            ]
        )
    else:
        command_tokens.extend(
            [
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                shlex.quote(str(payload["analysis_level"])),
            ]
        )
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    if payload["modalities"]:
        command_tokens.append("--modalities")
        command_tokens.extend(
            shlex.quote(str(modality)) for modality in payload["modalities"]
        )
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    command_tokens.extend(["--n_procs", str(payload["n_procs"])])
    command_tokens.extend(["--mem", f"{int(round(float(payload['mem_gb'])))}G"])
    if payload["bids_filter_file"]:
        command_tokens.extend(["--bids-filter-file", '"$BIDS_FILTER_FILE"'])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
    ]
    if payload["bids_filter_file"]:
        lines.append(
            _render_shell_default("BIDS_FILTER_FILE", str(payload["bids_filter_file"]))
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    return "\n".join(lines)


def _build_qsiprep_script(target_runtime: str, payload: dict[str, Any]) -> str:
    from brain_researcher.services.tools.execution_recipes import (
        _render_shell_command,
        _render_shell_default,
    )

    command_tokens = ["qsiprep" if target_runtime != "container" else "docker"]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
                "-v",
                '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
            ]
        )
        if payload["bids_filter_file"]:
            command_tokens.extend(["-v", '"$BIDS_FILTER_FILE:$BIDS_FILTER_FILE:ro"'])
        command_tokens.extend(
            [
                shlex.quote(
                    str(get_container_image("qsiprep") or "pennbbl/qsiprep:latest")
                ),
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                shlex.quote(str(payload["analysis_level"])),
            ]
        )
    else:
        command_tokens.extend(
            [
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                shlex.quote(str(payload["analysis_level"])),
            ]
        )
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if target_runtime == "container":
        command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
    else:
        command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    if payload["bids_filter_file"]:
        command_tokens.extend(["--bids-filter-file", '"$BIDS_FILTER_FILE"'])
    command_tokens.extend(["--n_cpus", str(payload["n_cpus"])])
    command_tokens.extend(["--omp-nthreads", str(payload["omp_nthreads"])])
    command_tokens.extend(["--mem_mb", str(payload["mem_mb"])])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
        'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"',
    ]
    if payload["bids_filter_file"]:
        lines.append(
            _render_shell_default("BIDS_FILTER_FILE", str(payload["bids_filter_file"]))
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    return "\n".join(lines)


def _build_smriprep_script(target_runtime: str, payload: dict[str, Any]) -> str:
    from brain_researcher.services.tools.execution_recipes import (
        _render_shell_command,
        _render_shell_default,
    )

    command_tokens = ["smriprep" if target_runtime != "container" else "docker"]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
                "-v",
                '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
            ]
        )
        if payload["bids_filter_file"]:
            command_tokens.extend(["-v", '"$BIDS_FILTER_FILE:$BIDS_FILTER_FILE:ro"'])
        command_tokens.extend(
            [
                shlex.quote(
                    str(get_container_image("smriprep") or "nipreps/smriprep:0.19.1")
                ),
                '"$BIDS_DIR"',
                '"$OUTPUT_DIR"',
                "participant",
            ]
        )
    else:
        command_tokens.extend(['"$BIDS_DIR"', '"$OUTPUT_DIR"', "participant"])
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if target_runtime == "container":
        command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
    else:
        command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    if payload["bids_filter_file"]:
        command_tokens.extend(["--bids-filter-file", '"$BIDS_FILTER_FILE"'])
    command_tokens.extend(["--n-cpus", str(payload["n_cpus"])])
    command_tokens.extend(["--omp-nthreads", str(payload["omp_nthreads"])])
    command_tokens.extend(["--mem-mb", str(payload["mem_mb"])])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
        'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"',
    ]
    if payload["bids_filter_file"]:
        lines.append(
            _render_shell_default("BIDS_FILTER_FILE", str(payload["bids_filter_file"]))
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    return "\n".join(lines)


def _build_qsirecon_script(target_runtime: str, payload: dict[str, Any]) -> str:
    from brain_researcher.services.tools.execution_recipes import (
        _render_shell_command,
        _render_shell_default,
    )

    command_tokens = ["qsirecon" if target_runtime != "container" else "docker"]
    if target_runtime == "container":
        command_tokens.extend(
            [
                "run",
                "--rm",
                "-v",
                '"$QSIPREP_DIR:$QSIPREP_DIR:ro"',
                "-v",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "-v",
                '"$WORK_DIR:$WORK_DIR:rw"',
            ]
        )
        if payload["fs_license_file"]:
            command_tokens.extend(
                ["-v", '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"']
            )
        command_tokens.extend(
            [
                shlex.quote(
                    str(get_container_image("qsirecon") or "pennlinc/qsirecon:1.1.1")
                ),
                '"$QSIPREP_DIR"',
                '"$OUTPUT_DIR"',
                "participant",
            ]
        )
    else:
        command_tokens.extend(['"$QSIPREP_DIR"', '"$OUTPUT_DIR"', "participant"])
    command_tokens.extend(["--recon-spec", '"$RECON_SPEC"'])
    command_tokens.extend(["--participant-label", '"$PARTICIPANT_LABEL"'])
    command_tokens.extend(["-w", '"$WORK_DIR"'])
    if payload["fs_license_file"]:
        if target_runtime == "container":
            command_tokens.extend(["--fs-license-file", "/opt/freesurfer/license.txt"])
        else:
            command_tokens.extend(["--fs-license-file", '"$FS_LICENSE_FILE"'])
    command_tokens.extend(["--nthreads", str(payload["n_cpus"])])
    command_tokens.extend(["--omp-nthreads", str(payload["omp_nthreads"])])
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        _render_shell_default("QSIPREP_DIR", str(payload["qsiprep_dir"])),
        _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
        _render_shell_default("WORK_DIR", str(payload["work_dir"])),
        _render_shell_default("RECON_SPEC", str(payload["recon_spec"])),
        _render_shell_default(
            "PARTICIPANT_LABEL", str(payload["participant_label"][0])
        ),
    ]
    if payload["fs_license_file"]:
        lines.append(
            'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"'
        )
    lines.extend(
        [
            "",
            'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    return "\n".join(lines)


def _build_external_repo_bids_recipe(
    tool_id: str,
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _env_exports,
        _external_repo_recipe_readme,
        _json_text,
        _minimal_fmriprep_payload,
        _minimal_mriqc_payload,
        _minimal_qsiprep_payload,
        _minimal_smriprep_payload,
        _render_shell_command,
        _render_shell_default,
        _slugify,
    )

    if tool_id == "workflow_fmriprep_preprocessing":
        payload = _minimal_fmriprep_payload(params)
        script_name = "run_workflow_fmriprep_preprocessing.sh"
        script_text = _build_fmriprep_script(
            "container" if target_runtime == "container" else "host", payload
        )
        summary = "single-subject fMRIPrep example with 4 CPUs / 16 GB RAM"
        image_name = "fmriprep"
        warnings = [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile.",
            "A valid FreeSurfer license file is required.",
        ]
    elif tool_id == "workflow_qsiprep":
        payload = _minimal_qsiprep_payload(params)
        script_name = "run_workflow_qsiprep.sh"
        script_text = _build_qsiprep_script(
            "container" if target_runtime == "container" else "host", payload
        )
        summary = "single-subject QSIPrep example with 4 CPUs / 16 GB RAM"
        image_name = "qsiprep"
        warnings = [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile.",
            "A valid FreeSurfer license file is required.",
            "The generated example assumes a diffusion-capable BIDS dataset with DWI inputs.",
        ]
    elif tool_id == "workflow_smriprep":
        payload = _minimal_smriprep_payload(params)
        script_name = "run_workflow_smriprep.sh"
        script_text = _build_smriprep_script("container", payload)
        summary = "single-subject sMRIPrep example with 4 CPUs / 16 GB RAM"
        image_name = "smriprep"
        warnings = [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile.",
            "A valid FreeSurfer license file is required.",
            "The generated local script uses Docker; the Slurm recipe uses Apptainer directly in job.sbatch.",
        ]
    else:
        payload = _minimal_mriqc_payload(params)
        script_name = "run_workflow_mriqc.sh"
        script_text = _build_mriqc_script(
            "container" if target_runtime == "container" else "host", payload
        )
        summary = "single-subject MRIQC example with 4 processes / 8 GB RAM"
        image_name = "mriqc"
        warnings = [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile."
        ]

    files = {
        "README.md": _external_repo_recipe_readme(
            tool_id,
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=script_name,
            minimal_summary=summary,
        ),
        script_name: script_text,
        "params.json": _json_text(payload),
    }

    setup_commands: list[str] = []
    run_command = f"bash {script_name}"
    dependency_block: dict[str, Any] = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }

    if target_runtime == "neurodesk":
        setup_commands.extend(
            f"module load {module}" for module in metadata["neurodesk_modules"]
        )
        setup_commands.extend(_env_exports(metadata["required_env_vars"]))
    elif target_runtime == "container":
        image = str(metadata["container_images"].get(image_name) or "")
        if image:
            setup_commands.append(f"docker pull {image}")
    else:
        if tool_id == "workflow_smriprep":
            image = str(
                metadata["container_images"].get("smriprep")
                or get_container_image("smriprep")
                or "nipreps/smriprep:0.19.1"
            )
            job_tokens = [
                "apptainer",
                "exec",
                "--bind",
                '"$BIDS_DIR:$BIDS_DIR:ro"',
                "--bind",
                '"$OUTPUT_DIR:$OUTPUT_DIR:rw"',
                "--bind",
                '"$WORK_DIR:$WORK_DIR:rw"',
                "--bind",
                '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
            ]
            if payload["bids_filter_file"]:
                job_tokens.extend(
                    ["--bind", '"$BIDS_FILTER_FILE:$BIDS_FILTER_FILE:ro"']
                )
            job_tokens.extend(
                [
                    f"docker://{image}",
                    "smriprep",
                    '"$BIDS_DIR"',
                    '"$OUTPUT_DIR"',
                    "participant",
                    "--participant-label",
                    '"$PARTICIPANT_LABEL"',
                    "-w",
                    '"$WORK_DIR"',
                    "--fs-license-file",
                    "/opt/freesurfer/license.txt",
                    "--n-cpus",
                    str(payload["n_cpus"]),
                    "--omp-nthreads",
                    str(payload["omp_nthreads"]),
                    "--mem-mb",
                    str(payload["mem_mb"]),
                ]
            )
            if payload["bids_filter_file"]:
                job_tokens.extend(["--bids-filter-file", '"$BIDS_FILTER_FILE"'])
            job_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])
            job_lines = [
                "#!/bin/bash",
                f"#SBATCH --job-name=br-{_slugify(tool_id)}",
                "#SBATCH --time=24:00:00",
                "#SBATCH --cpus-per-task=4",
                "#SBATCH --mem=16G",
                "#SBATCH --output=slurm-%j.out",
                "#SBATCH --error=slurm-%j.err",
                "",
                "set -euo pipefail",
                "",
                _render_shell_default("BIDS_DIR", str(payload["bids_dir"])),
                _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
                _render_shell_default("WORK_DIR", str(payload["work_dir"])),
                _render_shell_default(
                    "PARTICIPANT_LABEL", str(payload["participant_label"][0])
                ),
                'FS_LICENSE_FILE="${FS_LICENSE:-'
                + str(payload["fs_license_file"])
                + '}"',
            ]
            if payload["bids_filter_file"]:
                job_lines.append(
                    _render_shell_default(
                        "BIDS_FILTER_FILE", str(payload["bids_filter_file"])
                    )
                )
            job_lines.extend(
                [
                    "",
                    'mkdir -p "$OUTPUT_DIR" "$WORK_DIR"',
                    "",
                    _render_shell_command(job_tokens),
                    "",
                ]
            )
            files["job.sbatch"] = "\n".join(job_lines)
        else:
            module_lines = [
                f"module load {module}" for module in metadata["neurodesk_modules"]
            ]
            env_lines = _env_exports(metadata["required_env_vars"])
            if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
                rendered = sherlock_render_sbatch_script(
                    "cpu_single",
                    cluster_profile=cluster_profile,
                    job_name=f"br-{_slugify(tool_id)}",
                    module_lines=module_lines or None,
                    env_lines=env_lines or None,
                    command=f"bash {script_name}",
                )
                files["job.sbatch"] = str(rendered.get("script_text") or "")
            else:
                lines = [
                    "#!/bin/bash",
                    f"#SBATCH --job-name=br-{_slugify(tool_id)}",
                    "#SBATCH --time=24:00:00",
                    "#SBATCH --cpus-per-task=4",
                    "#SBATCH --mem=16G",
                    "#SBATCH --output=slurm-%j.out",
                    "#SBATCH --error=slurm-%j.err",
                    "",
                    "set -euo pipefail",
                    "",
                    *module_lines,
                    *env_lines,
                    f"bash {script_name}",
                    "",
                ]
                files["job.sbatch"] = "\n".join(lines)
        run_command = "sbatch job.sbatch"

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": warnings,
    }
    return recipe, "runnable"


def _build_qsirecon_minimal_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
    *,
    cluster_profile: str,
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _env_exports,
        _external_repo_recipe_readme,
        _json_text,
        _minimal_qsirecon_payload,
    )

    payload = _minimal_qsirecon_payload(params)
    script_name = "run_workflow_qsirecon.sh"
    script_text = _build_qsirecon_script(
        "container" if target_runtime == "container" else "host", payload
    )
    files = {
        "README.md": _external_repo_recipe_readme(
            "workflow_qsirecon",
            target_runtime=target_runtime,
            metadata=metadata,
            script_name=script_name,
            minimal_summary="single-subject QSIRecon example with 4 CPUs / 16 GB RAM",
        ),
        script_name: script_text,
        "params.json": _json_text(payload),
    }
    dependency_block: dict[str, Any] = {
        "python_packages": metadata["python_packages"],
        "neurodesk_modules": metadata["neurodesk_modules"],
        "container_images": metadata["container_images"],
    }
    setup_commands: list[str] = []
    run_command = f"bash {script_name}"
    if target_runtime == "container":
        image = str(
            metadata["container_images"].get("qsirecon")
            or get_container_image("qsirecon")
            or "pennlinc/qsirecon:1.1.1"
        )
        setup_commands.append(f"docker pull {image}")
    else:
        module_lines = [
            f"module load {module}" for module in metadata["neurodesk_modules"]
        ]
        env_lines = _env_exports(metadata["required_env_vars"])
        if cluster_profile == SHERLOCK_DEFAULT_PROFILE:
            rendered = sherlock_render_sbatch_script(
                "cpu_single",
                cluster_profile=cluster_profile,
                job_name="br-workflow_qsirecon",
                module_lines=module_lines or None,
                env_lines=env_lines or None,
                command=f"bash {script_name}",
            )
            files["job.sbatch"] = str(rendered.get("script_text") or "")
        else:
            lines = [
                "#!/bin/bash",
                "#SBATCH --job-name=br-workflow_qsirecon",
                "#SBATCH --time=24:00:00",
                "#SBATCH --cpus-per-task=4",
                "#SBATCH --mem=16G",
                "#SBATCH --output=slurm-%j.out",
                "#SBATCH --error=slurm-%j.err",
                "",
                "set -euo pipefail",
                "",
                *module_lines,
                *env_lines,
                f"bash {script_name}",
                "",
            ]
            files["job.sbatch"] = "\n".join(lines)
        run_command = "sbatch job.sbatch"

    recipe = {
        "dependencies": dependency_block,
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": setup_commands,
        "run_command": run_command,
        "params_json": _json_text(payload),
        "files": files,
        "warnings": [
            "This is a minimal single-subject example intended for execute-gate validation, not a production-scale batch profile.",
            "Provide a QSIPrep derivative root produced by workflow_qsiprep or an equivalent official QSIPrep run.",
            "Keep recon_spec on a known preset when promoting recipes to stable workflow packs.",
        ],
    }
    return recipe, "runnable"


def _build_fastsurfer_minimal_recipe(
    target_runtime: str,
    params: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    from brain_researcher.services.tools.execution_recipes import (
        _external_repo_recipe_readme,
        _json_text,
        _minimal_fastsurfer_payload,
        _render_shell_command,
        _render_shell_default,
    )

    payload = _minimal_fastsurfer_payload(params)
    script_name = "run_workflow_fastsurfer.sh"
    image = str(
        payload["container_image"]
        or metadata["container_images"].get("fastsurfer")
        or "deepmi/fastsurfer:latest"
    )
    device = "cuda" if payload["use_gpu"] else "cpu"
    command_tokens = [
        "docker",
        "run",
        "--rm",
        "-v",
        '"$T1W_IMAGE:/input/t1w.nii.gz:ro"',
        "-v",
        '"$OUTPUT_DIR:/out:rw"',
        "-v",
        '"$FS_LICENSE_FILE:/opt/freesurfer/license.txt:ro"',
        shlex.quote(image),
        "run_fastsurfer.sh",
        "--sid",
        '"$SUBJECT_ID"',
        "--sd",
        "/out",
        "--t1",
        "/input/t1w.nii.gz",
        "--threads",
        '"$N_THREADS"',
        "--device",
        device,
        "--fs_license",
        "/opt/freesurfer/license.txt",
    ]
    command_tokens.extend(shlex.quote(str(arg)) for arg in payload["extra_args"])

    script_text = "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
            _render_shell_default("T1W_IMAGE", str(payload["t1w_image"])),
            _render_shell_default("SUBJECT_ID", str(payload["subject_id"])),
            _render_shell_default("OUTPUT_DIR", str(payload["output_dir"])),
            _render_shell_default("N_THREADS", str(payload["n_threads"])),
            'FS_LICENSE_FILE="${FS_LICENSE:-' + str(payload["fs_license_file"]) + '}"',
            "",
            'mkdir -p "$OUTPUT_DIR"',
            "",
            _render_shell_command(command_tokens),
            "",
        ]
    )
    recipe = {
        "dependencies": {
            "python_packages": metadata["python_packages"],
            "container_images": metadata["container_images"],
        },
        "required_env_vars": metadata["required_env_vars"],
        "resource_profile": metadata["resource_profile"],
        "setup_commands": [f"docker pull {image}"],
        "run_command": f"bash {script_name}",
        "params_json": _json_text(payload),
        "files": {
            "README.md": _external_repo_recipe_readme(
                "workflow_fastsurfer",
                target_runtime=target_runtime,
                metadata=metadata,
                script_name=script_name,
                minimal_summary="single-subject FastSurfer example with 1 CPU thread",
            ),
            script_name: script_text,
            "params.json": _json_text(payload),
        },
        "warnings": [
            "The generated FastSurfer recipe uses Docker for the minimal execution path even though the BR workflow default runtime is apptainer.",
            "A valid FreeSurfer license file is required.",
        ],
    }
    return recipe, "runnable"
