"""Unit tests for scripts/ops/run_prod_external_repo_certification.py."""

from __future__ import annotations

import base64
import inspect
import json
import subprocess
from pathlib import Path

from scripts.ops import run_prod_external_repo_certification as mod


def test_resolve_prod_mcp_token_prefers_local_token(monkeypatch) -> None:
    monkeypatch.setattr(mod, "resolve_mcp_token", lambda: "local-token")
    token = mod.resolve_prod_mcp_token(
        vm_name="brain-researcher-vm",
        zone="us-west1-b",
        project="<YOUR_GCP_PROJECT>",
        namespace="brain-researcher-core",
        secret_name="brain-researcher-mcp-auth",
        secret_key="BR_MCP_AUTH_TOKEN",
        timeout_s=5.0,
    )
    assert token == "local-token"


def test_resolve_prod_mcp_token_decodes_legacy_secret_when_local_missing(monkeypatch) -> None:
    monkeypatch.setattr(mod, "resolve_mcp_token", lambda: None)
    manifest = json.dumps(
        {"data": {"BR_MCP_AUTH_TOKEN": base64.b64encode(b"secret-token").decode("ascii")}}
    )
    monkeypatch.setattr(
        mod,
        "_run_subprocess",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=manifest, stderr=""
        ),
    )

    token = mod.resolve_prod_mcp_token(
        vm_name="brain-researcher-vm",
        zone="us-west1-b",
        project="<YOUR_GCP_PROJECT>",
        namespace="brain-researcher-core",
        secret_name="brain-researcher-mcp-auth",
        secret_key="BR_MCP_AUTH_TOKEN",
        timeout_s=5.0,
    )
    assert token == "secret-token"


def test_resolve_prod_mcp_token_rejects_keyed_token_secret(monkeypatch) -> None:
    monkeypatch.setattr(mod, "resolve_mcp_token", lambda: None)
    manifest = json.dumps(
        {
            "data": {
                "BR_MCP_AUTH_TOKENS_JSON": base64.b64encode(b'{"kid":{"token_hash":"abc"}}').decode("ascii"),
                "BR_MCP_TOKEN_PEPPER": base64.b64encode(b"pepper").decode("ascii"),
            }
        }
    )
    monkeypatch.setattr(
        mod,
        "_run_subprocess",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=manifest, stderr=""
        ),
    )

    try:
        mod.resolve_prod_mcp_token(
            vm_name="brain-researcher-vm",
            zone="us-west1-b",
            project="<YOUR_GCP_PROJECT>",
            namespace="brain-researcher-core",
            secret_name="brain-researcher-mcp-auth",
            secret_key="BR_MCP_AUTH_TOKEN",
            timeout_s=5.0,
        )
    except RuntimeError as exc:
        assert "keyed-token mode" in str(exc)
        assert "no plaintext bearer token" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected keyed-token secret to be rejected")


def test_resolve_local_fs_license_prefers_explicit_path(
    tmp_path: Path, monkeypatch
) -> None:
    explicit = tmp_path / "explicit_license.txt"
    explicit.write_text("license", encoding="utf-8")

    monkeypatch.delenv("FS_LICENSE", raising=False)
    monkeypatch.setattr(mod.Path, "home", lambda: tmp_path)

    resolved = mod.resolve_local_fs_license(str(explicit))
    assert resolved == explicit.resolve()


def test_resolve_local_fs_license_falls_back_to_home(
    monkeypatch, tmp_path: Path
) -> None:
    home_license = tmp_path / ".freesurfer_license.txt"
    home_license.write_text("license", encoding="utf-8")

    monkeypatch.delenv("FS_LICENSE", raising=False)
    monkeypatch.setattr(mod.Path, "home", lambda: tmp_path)

    resolved = mod.resolve_local_fs_license(None)
    assert resolved == home_license.resolve()


def test_override_recipe_files_updates_preprocessing_qc_params() -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/data/old",
                        "output_dir": "/out/old",
                        "participant_label": ["99"],
                        "fs_license_file": "",
                        "qc_tsv": "",
                    }
                )
            }
        }
    }

    files = mod.override_recipe_files(
        recipe_payload,
        workflow_id="workflow_preprocessing_qc",
        participant_label="01",
        bids_dir="/data/new",
        output_dir="/out/new",
        work_dir="/work/new",
        qc_tsv="/inputs/qc.tsv",
        fs_license_file="/inputs/license.txt",
    )
    params = json.loads(files["params.json"])
    assert params["bids_dir"] == "/data/new"
    assert params["participant_label"] == ["01"]
    assert params["fs_license_file"] == "/inputs/license.txt"
    assert params["qc_tsv"] == "/inputs/qc.tsv"
    assert params["fmriprep_output_dir"] == "/out/new/fmriprep"
    assert params["mriqc_output_dir"] == "/out/new/mriqc"
    assert params["fmriprep_work_dir"] == "/work/new/fmriprep"
    assert params["mriqc_work_dir"] == "/work/new/mriqc"


def test_override_recipe_files_updates_mriqc_work_dir() -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/data/old",
                        "output_dir": "./out/old",
                        "work_dir": "./work/old",
                        "participant_label": ["99"],
                    }
                ),
                "run_workflow_mriqc.sh": "mriqc \\\n  /data/old \\\n  /out/old \\\n  participant\n",
            }
        }
    }

    files = mod.override_recipe_files(
        recipe_payload,
        workflow_id="workflow_mriqc",
        participant_label="01",
        bids_dir="/data/new",
        output_dir="/out/new",
        work_dir="/work/new",
        qc_tsv=None,
        fs_license_file=None,
    )
    params = json.loads(files["params.json"])
    assert params["bids_dir"] == "/data/new"
    assert params["output_dir"] == "/out/new"
    assert params["work_dir"] == "/work/new"
    assert params["mriqc_work_dir"] == "/work/new"
    assert "--no-sub" in files["run_workflow_mriqc.sh"]


def test_override_recipe_files_adds_fs_no_reconall_for_fmriprep() -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/data/old",
                        "output_dir": "/out/old",
                        "participant_label": ["99"],
                    }
                ),
                "run_workflow_fmriprep_preprocessing.sh": (
                    'fmriprep \\\n  "$BIDS_DIR" \\\n  "$OUTPUT_DIR" \\\n  participant\n'
                ),
            }
        }
    }

    files = mod.override_recipe_files(
        recipe_payload,
        workflow_id="workflow_fmriprep_preprocessing",
        participant_label="01",
        bids_dir="/data/new",
        output_dir="/out/new",
        work_dir="/work/new",
        qc_tsv=None,
        fs_license_file="/inputs/license.txt",
    )
    assert "--fs-no-reconall" in files["run_workflow_fmriprep_preprocessing.sh"]


def test_override_recipe_files_adds_fs_no_reconall_for_preprocessing_qc() -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/data/old",
                        "output_dir": "/out/old",
                        "participant_label": ["99"],
                    }
                ),
                "run_fmriprep.sh": (
                    'fmriprep \\\n  "$BIDS_DIR" \\\n  "$OUTPUT_DIR" \\\n  participant\n'
                ),
            }
        }
    }

    files = mod.override_recipe_files(
        recipe_payload,
        workflow_id="workflow_preprocessing_qc",
        participant_label="01",
        bids_dir="/data/new",
        output_dir="/out/new",
        work_dir="/work/new",
        qc_tsv="/inputs/qc.tsv",
        fs_license_file="/inputs/license.txt",
    )
    assert "--fs-no-reconall" in files["run_fmriprep.sh"]


def test_build_run_script_for_preprocessing_qc_separates_subdirs() -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/remote/bids",
                        "output_dir": "/remote/out/workflow_preprocessing_qc",
                        "fmriprep_output_dir": "/remote/out/workflow_preprocessing_qc/fmriprep",
                        "mriqc_output_dir": "/remote/out/workflow_preprocessing_qc/mriqc",
                        "fmriprep_work_dir": "/remote/work/workflow_preprocessing_qc/fmriprep",
                        "mriqc_work_dir": "/remote/work/workflow_preprocessing_qc/mriqc",
                    }
                )
            },
            "setup_commands": [
                "module load fmriprep/23.2.3",
                "export FS_LICENSE=/pod/license.txt",
            ],
            "run_command": "bash run_workflow_preprocessing_qc.sh",
        }
    }
    script = mod.build_run_script(
        workflow_id="workflow_preprocessing_qc",
        recipe_payload=recipe_payload,
        recipe_dir="/remote/recipe",
        fs_license_file="/remote/license.txt",
        executables={
            "fmriprep": "/cvmfs/neurodesk.ardc.edu.au/containers/fmriprep/bin/fmriprep"
        },
    )
    assert "bash run_fmriprep.sh" in script
    assert "bash run_mriqc.sh" in script
    assert "python post_qc.py" in script
    assert "/remote/out/workflow_preprocessing_qc/fmriprep" in script
    assert "/remote/out/workflow_preprocessing_qc/mriqc" in script
    assert "export FS_LICENSE=/remote/license.txt" in script
    assert "export PATH=" in script
    assert "mkdir -p /remote/out/workflow_preprocessing_qc" in script


def test_build_run_script_does_not_export_empty_fs_license() -> None:
    recipe_payload = {
        "recipe": {
            "files": {"params.json": json.dumps({"output_dir": "/remote/out"})},
            "setup_commands": [],
            "run_command": "bash run_workflow_fmriprep_preprocessing.sh",
        }
    }
    script = mod.build_run_script(
        workflow_id="workflow_fmriprep_preprocessing",
        recipe_payload=recipe_payload,
        recipe_dir="/remote/recipe",
        fs_license_file=None,
        executables={},
    )
    assert "export FS_LICENSE=" not in script
    assert "bash run_workflow_fmriprep_preprocessing.sh" in script


def test_build_supervised_wrapper_script_enforces_pod_side_timeout_and_heartbeat() -> (
    None
):
    script = mod.build_supervised_wrapper_script(
        run_script="echo hello",
        state_dir="/remote/state",
        log_dir="/remote/logs",
        remote_execute_timeout_s=321.0,
        heartbeat_interval_s=17.0,
    )
    assert "timeout --foreground --kill-after=30s 321s" in script
    assert "printf 'running\\n' > \"$STATE_FILE\"" in script
    assert "sleep 17" in script
    assert "printf 'timeout\\n' > \"$STATE_FILE\"" in script
    assert "printf 'oom\\n' > \"$STATE_FILE\"" in script


def test_candidate_fmriprep_deriv_roots_includes_both_namings() -> None:
    roots = mod._candidate_fmriprep_deriv_roots(
        "/app/data/OpenNeuroDerivatives/fmriprep/ds000114-fmriprep"
    )
    assert "/app/data/OpenNeuroDerivatives/fmriprep/ds000114-fmriprep" in roots
    assert "/app/data/OpenNeuroDerivatives/fmriprep/ds000114" in roots


def test_stage_minimal_bids_subset_uses_task_specific_top_level_json() -> None:
    source = inspect.getsource(mod.stage_minimal_bids_subset)
    assert "f'task-{task_name}_bold.json'" in source


def test_stage_precomputed_qc_table_filters_to_staged_session_and_task() -> None:
    source = inspect.getsource(mod.stage_precomputed_qc_table)
    assert "session_label: str" in source
    assert "task_name: str" in source
    assert (
        "{subject_dir}/{session_label}/func/*_task-{task_name}_desc-confounds_timeseries.tsv"
        in source
    )
    assert (
        "{subject_dir}/{session_label}/func/*_task-{task_name}_*_desc-confounds_timeseries.tsv"
        in source
    )


def test_record_precondition_failure_writes_structured_result(tmp_path: Path) -> None:
    result = mod._record_precondition_failure(
        report_dir=tmp_path,
        workflow_id="workflow_preprocessing_qc",
        recipe_target="neurodesk",
        reason="missing_precomputed_qc",
        details={"participant_label": "01"},
    )
    assert result["classification"] == "failed_precondition"
    assert result["reason"] == "missing_precomputed_qc"
    payload = json.loads(
        (tmp_path / "workflow_preprocessing_qc" / "result.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["classification"] == "failed_precondition"
    assert payload["details"]["participant_label"] == "01"


def test_record_workflow_failure_writes_structured_result(tmp_path: Path) -> None:
    result = mod._record_workflow_failure(
        report_dir=tmp_path,
        workflow_id="workflow_fmriprep_preprocessing",
        recipe_target="neurodesk",
        classification="failed_timeout_local",
        reason="remote_launch_deadline_exceeded",
        output_dir="/remote/out",
        work_dir="/remote/work",
        state_dir="/remote/state",
        details={"timeout_seconds": 60.0},
    )
    assert result["classification"] == "failed_timeout_local"
    assert result["reason"] == "remote_launch_deadline_exceeded"
    payload = json.loads(
        (tmp_path / "workflow_fmriprep_preprocessing" / "result.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["state_dir"] == "/remote/state"
    assert payload["details"]["timeout_seconds"] == 60.0


def test_classify_remote_terminal_status_variants() -> None:
    assert mod._classify_remote_terminal_status(
        {"state": "timeout", "exit_code": "124"}
    ) == (
        "failed_timeout_remote",
        "remote_deadline_exceeded",
    )
    assert mod._classify_remote_terminal_status(
        {"state": "oom", "exit_code": "137"}
    ) == (
        "failed_oom",
        "remote_exit_code:137",
    )
    assert mod._classify_remote_terminal_status(
        {"state": "failed", "exit_code": "2"}
    ) == (
        "failed_code",
        "remote_recipe_exit_code:2",
    )


def test_remote_smoke_started_detects_supervisor_progress() -> None:
    assert mod._remote_smoke_started({"started_at": "2026-03-10T00:00:00Z"}) is True
    assert mod._remote_smoke_started({"heartbeat": "2026-03-10T00:00:10Z"}) is True
    assert mod._remote_smoke_started({"pid": "123"}) is True
    assert mod._remote_smoke_started({}) is False


def test_local_run_payload_falls_back_to_recipe_derivation() -> None:
    recipe_payload = {
        "resolved_tool_id": "workflow_fmriprep_preprocessing",
        "target_runtime": "container",
        "recipe": {
            "files": {"run_workflow_fmriprep_preprocessing.sh": "echo hi\n"},
            "setup_commands": ["docker pull nipreps/fmriprep:23.2.3"],
            "run_command": "bash run_workflow_fmriprep_preprocessing.sh",
            "required_env_vars": ["FS_LICENSE"],
        },
    }
    local_run = mod._local_run_payload(recipe_payload)
    assert local_run is not None
    assert local_run["workspace"].endswith(
        "workflow_fmriprep_preprocessing_container_recipe"
    )
    assert "docker pull nipreps/fmriprep:23.2.3" in local_run["commands"]
    assert local_run["required_env_vars"] == ["FS_LICENSE"]
    assert local_run["environment"]["required"][0]["name"] == "FS_LICENSE"
    assert "Docker or a compatible container runtime" in local_run["prerequisites"][
        "setup_once"
    ][0]


def test_build_handoff_bundle_patches_external_params(tmp_path: Path) -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/remote/bids",
                        "output_dir": "/remote/out/workflow_fmriprep_preprocessing",
                        "work_dir": "/remote/work/workflow_fmriprep_preprocessing",
                        "participant_label": ["01"],
                        "fs_license_file": "/remote/license.txt",
                    }
                ),
                "run_workflow_fmriprep_preprocessing.sh": "echo hi\n",
            }
        }
    }
    run_pack = {
        "workspace": "./workflow_fmriprep_preprocessing_container_recipe",
        "runtime": {"target": "container"},
    }

    payload = mod.build_handoff_bundle(
        report_dir=tmp_path,
        workflow_id="workflow_fmriprep_preprocessing",
        recipe_payload=recipe_payload,
        run_pack=run_pack,
        downloaded_artifacts=None,
    )
    assert payload["ok"] is True
    assert payload["missing_inputs"] == ["bids_dir"]
    params = json.loads(Path(payload["params_json"]).read_text(encoding="utf-8"))
    assert params["bids_dir"] == "<set-local-bids-root>"
    assert params["output_dir"] == "./outputs/out/workflow_fmriprep_preprocessing"
    assert params["work_dir"] == "./work/workflow_fmriprep_preprocessing"
    assert params["fs_license_file"] == "/path/to/freesurfer/license.txt"
    assert Path(payload["params_local_json"]).exists()


def test_build_handoff_bundle_copies_downloaded_artifacts(tmp_path: Path) -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/remote/bids",
                        "output_dir": "/remote/out/workflow_mriqc",
                        "work_dir": "/remote/work/workflow_mriqc",
                    }
                ),
                "run_workflow_mriqc.sh": "echo hi\n",
            }
        }
    }
    run_pack = {
        "workspace": "./workflow_mriqc_neurodesk_recipe",
        "runtime": {"target": "neurodesk"},
    }
    html = tmp_path / "subject_report_html.html"
    html.write_text("<html></html>", encoding="utf-8")
    downloaded_artifacts = {
        "artifacts": {
            "subject_report_html": {
                "downloaded": True,
                "kind": "file",
                "local_path": str(html),
                "path": "/remote/out/sub-01.html",
            }
        }
    }

    payload = mod.build_handoff_bundle(
        report_dir=tmp_path,
        workflow_id="workflow_mriqc",
        recipe_payload=recipe_payload,
        run_pack=run_pack,
        downloaded_artifacts=downloaded_artifacts,
    )
    assert payload["ok"] is True
    assert payload["bundled_artifacts"][0]["name"] == "subject_report_html"
    assert (
        Path(payload["workspace"]) / payload["bundled_artifacts"][0]["relative_path"]
    ).exists()


def test_artifact_output_filename_for_file_and_dir() -> None:
    assert (
        mod._artifact_output_filename(
            "subject_report_html", "/remote/sub-01.html", "file"
        )
        == "subject_report_html.html"
    )
    assert (
        mod._artifact_output_filename("derivatives_dir", "/remote/out", "dir")
        == "derivatives_dir.tar.gz"
    )


def test_summarize_results_counts_dry_run() -> None:
    summary = mod.summarize_results(
        [
            {"workflow_id": "a", "classification": "verified"},
            {"workflow_id": "b", "classification": "verified_deferred"},
            {"workflow_id": "c", "classification": "dry_run"},
            {"workflow_id": "d", "classification": "failed_code"},
            {"workflow_id": "e", "classification": "failed_timeout_remote"},
            {"workflow_id": "f", "classification": "failed_timeout_local"},
            {"workflow_id": "g", "classification": "failed_oom"},
        ]
    )
    assert summary["total"] == 7
    assert summary["verified"] == 1
    assert summary["verified_deferred"] == 1
    assert summary["dry_run"] == 1
    assert summary["failed_code"] == 1
    assert summary["failed_timeout_remote"] == 1
    assert summary["failed_timeout_local"] == 1
    assert summary["failed_oom"] == 1


def test_certify_workflow_classifies_remote_timeout(
    monkeypatch, tmp_path: Path
) -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/data/old",
                        "output_dir": "/out/old",
                        "work_dir": "/work/old",
                        "participant_label": ["99"],
                    }
                )
            },
            "setup_commands": [],
            "run_command": "bash run_workflow_fmriprep_preprocessing.sh",
        },
        "local_run": {
            "workspace": "./workflow_fmriprep_preprocessing_container_recipe",
            "commands": ["docker pull nipreps/fmriprep:23.2.3"],
            "shell_snippet": "bash run_workflow_fmriprep_preprocessing.sh",
        },
    }

    monkeypatch.setattr(mod, "get_recipe", lambda *args, **kwargs: recipe_payload)
    monkeypatch.setattr(
        mod,
        "stage_recipe_files",
        lambda **kwargs: {
            "recipe_dir": kwargs["remote_dir"],
            "file_count": len(kwargs["files"]),
        },
    )
    monkeypatch.setattr(
        mod,
        "launch_remote_supervised_job",
        lambda **kwargs: {
            "launcher_pid": "1234",
            "state_dir": kwargs["remote_state_dir"],
        },
    )
    monkeypatch.setattr(
        mod,
        "wait_for_remote_supervised_job",
        lambda **kwargs: {
            "state": "timeout",
            "exit_code": "124",
            "started_at": "2026-03-10T00:00:00Z",
            "heartbeat": "2026-03-10T00:00:05Z",
        },
    )
    monkeypatch.setattr(
        mod,
        "build_handoff_bundle",
        lambda **kwargs: {
            "ok": True,
            "workspace": str(
                tmp_path
                / "workflow_fmriprep_preprocessing"
                / "handoff_bundle"
                / "workflow_fmriprep_preprocessing_container_recipe"
            ),
            "missing_inputs": ["bids_dir"],
        },
    )

    result = mod.certify_workflow(
        object(),
        workflow_id="workflow_fmriprep_preprocessing",
        recipe_target="neurodesk",
        report_dir=tmp_path,
        vm_name="vm",
        zone="zone",
        project="project",
        namespace="ns",
        pod="pod",
        participant_label="01",
        staged_bids_root="/remote/bids",
        staged_qc_tsv=None,
        staged_fs_license="/remote/license.txt",
        remote_input_root="/remote/input",
        remote_output_root="/remote/output",
        executables={},
        request_timeout_s=5.0,
        remote_execute_timeout_s=30.0,
        remote_launch_timeout_s=5.0,
        remote_timeout_grace_s=10.0,
        poll_interval_s=1.0,
        heartbeat_interval_s=2.0,
        artifact_download_timeout_s=10.0,
        dry_run=False,
    )

    assert result["classification"] == "verified_deferred"
    assert result["reason"] == "smoke_budget_exhausted_deferred_to_local"
    assert result["state_dir"] == "/remote/input/workflow_fmriprep_preprocessing/state"
    assert result["cert_budget_seconds"] == 30.0
    assert result["run_pack"]["runtime"]["target"] == "container"
    assert result["local_run"]["workspace"].endswith(
        "workflow_fmriprep_preprocessing_container_recipe"
    )
    assert result["handoff_bundle"]["ok"] is True
    assert result["handoff_bundle"]["missing_inputs"] == ["bids_dir"]


def test_certify_workflow_dry_run_includes_local_run(
    monkeypatch, tmp_path: Path
) -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/data/old",
                        "output_dir": "/out/old",
                        "work_dir": "/work/old",
                        "participant_label": ["99"],
                    }
                )
            },
            "setup_commands": [],
            "run_command": "bash run_workflow_fmriprep_preprocessing.sh",
        },
        "local_run": {
            "workspace": "./workflow_fmriprep_preprocessing_container_recipe",
            "commands": ["docker pull nipreps/fmriprep:23.2.3"],
        },
    }

    monkeypatch.setattr(mod, "get_recipe", lambda *args, **kwargs: recipe_payload)
    monkeypatch.setattr(
        mod,
        "stage_recipe_files",
        lambda **kwargs: {
            "recipe_dir": kwargs["remote_dir"],
            "file_count": len(kwargs["files"]),
        },
    )
    monkeypatch.setattr(
        mod,
        "build_handoff_bundle",
        lambda **kwargs: {
            "ok": True,
            "workspace": str(
                tmp_path
                / "workflow_fmriprep_preprocessing"
                / "handoff_bundle"
                / "workflow_fmriprep_preprocessing_container_recipe"
            ),
            "missing_inputs": ["bids_dir"],
        },
    )

    result = mod.certify_workflow(
        object(),
        workflow_id="workflow_fmriprep_preprocessing",
        recipe_target="neurodesk",
        report_dir=tmp_path,
        vm_name="vm",
        zone="zone",
        project="project",
        namespace="ns",
        pod="pod",
        participant_label="01",
        staged_bids_root="/remote/bids",
        staged_qc_tsv=None,
        staged_fs_license="/remote/license.txt",
        remote_input_root="/remote/input",
        remote_output_root="/remote/output",
        executables={},
        request_timeout_s=5.0,
        remote_execute_timeout_s=30.0,
        remote_launch_timeout_s=5.0,
        remote_timeout_grace_s=10.0,
        poll_interval_s=1.0,
        heartbeat_interval_s=2.0,
        artifact_download_timeout_s=10.0,
        dry_run=True,
    )

    assert result["classification"] == "dry_run"
    assert result["run_pack"]["runtime"]["target"] == "container"
    assert result["local_run"]["workspace"].endswith(
        "workflow_fmriprep_preprocessing_container_recipe"
    )
    assert result["handoff_bundle"]["ok"] is True


def test_certify_workflow_verified_attaches_handoff_bundle(
    monkeypatch, tmp_path: Path
) -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/remote/bids",
                        "output_dir": "/remote/out/workflow_mriqc",
                        "work_dir": "/remote/work/workflow_mriqc",
                        "participant_label": ["01"],
                    }
                ),
                "run_workflow_mriqc.sh": "echo hi\n",
            },
            "setup_commands": [],
            "run_command": "bash run_workflow_mriqc.sh",
        },
        "local_run": {
            "workspace": "./workflow_mriqc_neurodesk_recipe",
            "commands": ["module load mriqc/24.0.2"],
        },
    }
    monkeypatch.setattr(mod, "get_recipe", lambda *args, **kwargs: recipe_payload)
    monkeypatch.setattr(
        mod,
        "stage_recipe_files",
        lambda **kwargs: {"recipe_dir": kwargs["remote_dir"], "file_count": len(kwargs["files"])},
    )
    monkeypatch.setattr(
        mod,
        "launch_remote_supervised_job",
        lambda **kwargs: {"launcher_pid": "1234", "state_dir": kwargs["remote_state_dir"]},
    )
    monkeypatch.setattr(
        mod,
        "wait_for_remote_supervised_job",
        lambda **kwargs: {"state": "succeeded", "exit_code": "0"},
    )
    monkeypatch.setattr(
        mod,
        "validate_remote_artifacts",
        lambda **kwargs: {
            "ok": True,
            "artifacts": {
                "subject_report_html": {"path": "/remote/out/sub-01.html", "exists": True}
            },
        },
    )
    monkeypatch.setattr(
        mod,
        "download_remote_artifacts",
        lambda **kwargs: {
            "ok": True,
            "artifacts": {
                "subject_report_html": {
                    "downloaded": True,
                    "kind": "file",
                    "local_path": str(tmp_path / "sub-01.html"),
                    "path": "/remote/out/sub-01.html",
                }
            },
        },
    )
    monkeypatch.setattr(
        mod,
        "build_handoff_bundle",
        lambda **kwargs: {
            "ok": True,
            "workspace": str(
                tmp_path / "workflow_mriqc" / "handoff_bundle" / "workflow_mriqc_neurodesk_recipe"
            ),
            "bundled_artifacts": [{"name": "subject_report_html"}],
            "missing_inputs": ["bids_dir"],
        },
    )
    (tmp_path / "sub-01.html").write_text("<html></html>", encoding="utf-8")

    result = mod.certify_workflow(
        object(),
        workflow_id="workflow_mriqc",
        recipe_target="neurodesk",
        report_dir=tmp_path,
        vm_name="vm",
        zone="zone",
        project="project",
        namespace="ns",
        pod="pod",
        participant_label="01",
        staged_bids_root="/remote/bids",
        staged_qc_tsv=None,
        staged_fs_license=None,
        remote_input_root="/remote/input",
        remote_output_root="/remote/output",
        executables={},
        request_timeout_s=5.0,
        remote_execute_timeout_s=30.0,
        remote_launch_timeout_s=5.0,
        remote_timeout_grace_s=10.0,
        poll_interval_s=1.0,
        heartbeat_interval_s=2.0,
        artifact_download_timeout_s=10.0,
        dry_run=False,
    )
    assert result["classification"] == "verified"
    assert result["handoff_bundle"]["ok"] is True
    assert result["handoff_bundle"]["bundled_artifacts"][0]["name"] == "subject_report_html"


def test_certify_workflow_classifies_launch_timeout(
    monkeypatch, tmp_path: Path
) -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/data/old",
                        "output_dir": "/out/old",
                        "work_dir": "/work/old",
                        "participant_label": ["99"],
                    }
                )
            },
            "setup_commands": [],
            "run_command": "bash run_workflow_fmriprep_preprocessing.sh",
        }
    }

    monkeypatch.setattr(mod, "get_recipe", lambda *args, **kwargs: recipe_payload)
    monkeypatch.setattr(
        mod,
        "stage_recipe_files",
        lambda **kwargs: {
            "recipe_dir": kwargs["remote_dir"],
            "file_count": len(kwargs["files"]),
        },
    )

    def raise_timeout(**kwargs):
        raise mod.subprocess.TimeoutExpired(cmd="launch", timeout=5.0)

    monkeypatch.setattr(mod, "launch_remote_supervised_job", raise_timeout)

    result = mod.certify_workflow(
        object(),
        workflow_id="workflow_fmriprep_preprocessing",
        recipe_target="neurodesk",
        report_dir=tmp_path,
        vm_name="vm",
        zone="zone",
        project="project",
        namespace="ns",
        pod="pod",
        participant_label="01",
        staged_bids_root="/remote/bids",
        staged_qc_tsv=None,
        staged_fs_license="/remote/license.txt",
        remote_input_root="/remote/input",
        remote_output_root="/remote/output",
        executables={},
        request_timeout_s=5.0,
        remote_execute_timeout_s=30.0,
        remote_launch_timeout_s=5.0,
        remote_timeout_grace_s=10.0,
        poll_interval_s=1.0,
        heartbeat_interval_s=2.0,
        artifact_download_timeout_s=10.0,
        dry_run=False,
    )

    assert result["classification"] == "failed_timeout_local"
    assert result["reason"] == "remote_launch_deadline_exceeded"


def test_certify_workflow_verified_downloads_artifacts(
    monkeypatch, tmp_path: Path
) -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/data/old",
                        "output_dir": "/out/old",
                        "work_dir": "/work/old",
                        "participant_label": ["99"],
                    }
                )
            },
            "setup_commands": [],
            "run_command": "bash run_workflow_mriqc.sh",
        },
        "local_run": {
            "workspace": "./workflow_mriqc_neurodesk_recipe",
            "commands": ["bash run_workflow_mriqc.sh"],
        },
    }
    artifacts = {
        "ok": True,
        "artifacts": {
            "dataset_description.json": {
                "path": "/remote/out/dataset_description.json",
                "exists": True,
            }
        },
    }
    downloaded = {
        "ok": True,
        "download_dir": str(tmp_path / "workflow_mriqc" / "downloaded_artifacts"),
        "artifacts": {
            "dataset_description.json": {
                "downloaded": True,
                "local_path": str(
                    tmp_path
                    / "workflow_mriqc"
                    / "downloaded_artifacts"
                    / "dataset_description_json.json"
                ),
            }
        },
    }

    monkeypatch.setattr(mod, "get_recipe", lambda *args, **kwargs: recipe_payload)
    monkeypatch.setattr(
        mod,
        "stage_recipe_files",
        lambda **kwargs: {
            "recipe_dir": kwargs["remote_dir"],
            "file_count": len(kwargs["files"]),
        },
    )
    monkeypatch.setattr(
        mod,
        "launch_remote_supervised_job",
        lambda **kwargs: {
            "launcher_pid": "1234",
            "state_dir": kwargs["remote_state_dir"],
        },
    )
    monkeypatch.setattr(
        mod,
        "wait_for_remote_supervised_job",
        lambda **kwargs: {
            "state": "succeeded",
            "exit_code": "0",
            "started_at": "2026-03-10T00:00:00Z",
            "finished_at": "2026-03-10T00:01:00Z",
        },
    )
    monkeypatch.setattr(mod, "validate_remote_artifacts", lambda **kwargs: artifacts)
    monkeypatch.setattr(mod, "download_remote_artifacts", lambda **kwargs: downloaded)

    result = mod.certify_workflow(
        object(),
        workflow_id="workflow_mriqc",
        recipe_target="neurodesk",
        report_dir=tmp_path,
        vm_name="vm",
        zone="zone",
        project="project",
        namespace="ns",
        pod="pod",
        participant_label="01",
        staged_bids_root="/remote/bids",
        staged_qc_tsv=None,
        staged_fs_license=None,
        remote_input_root="/remote/input",
        remote_output_root="/remote/output",
        executables={},
        request_timeout_s=5.0,
        remote_execute_timeout_s=30.0,
        remote_launch_timeout_s=5.0,
        remote_timeout_grace_s=10.0,
        poll_interval_s=1.0,
        heartbeat_interval_s=2.0,
        artifact_download_timeout_s=10.0,
        dry_run=False,
    )

    assert result["classification"] == "verified"
    assert result["downloaded_artifacts"]["ok"] is True
    assert result["local_run"]["workspace"].endswith("workflow_mriqc_neurodesk_recipe")


def test_certify_workflow_download_failure_is_failed_surface(
    monkeypatch, tmp_path: Path
) -> None:
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": json.dumps(
                    {
                        "bids_dir": "/data/old",
                        "output_dir": "/out/old",
                        "work_dir": "/work/old",
                        "participant_label": ["99"],
                    }
                )
            },
            "setup_commands": [],
            "run_command": "bash run_workflow_mriqc.sh",
        }
    }
    artifacts = {
        "ok": True,
        "artifacts": {
            "dataset_description.json": {
                "path": "/remote/out/dataset_description.json",
                "exists": True,
            }
        },
    }

    monkeypatch.setattr(mod, "get_recipe", lambda *args, **kwargs: recipe_payload)
    monkeypatch.setattr(
        mod,
        "stage_recipe_files",
        lambda **kwargs: {
            "recipe_dir": kwargs["remote_dir"],
            "file_count": len(kwargs["files"]),
        },
    )
    monkeypatch.setattr(
        mod,
        "launch_remote_supervised_job",
        lambda **kwargs: {
            "launcher_pid": "1234",
            "state_dir": kwargs["remote_state_dir"],
        },
    )
    monkeypatch.setattr(
        mod,
        "wait_for_remote_supervised_job",
        lambda **kwargs: {
            "state": "succeeded",
            "exit_code": "0",
            "started_at": "2026-03-10T00:00:00Z",
            "finished_at": "2026-03-10T00:01:00Z",
        },
    )
    monkeypatch.setattr(mod, "validate_remote_artifacts", lambda **kwargs: artifacts)

    def raise_download(**kwargs):
        raise RuntimeError("scp failed")

    monkeypatch.setattr(mod, "download_remote_artifacts", raise_download)

    result = mod.certify_workflow(
        object(),
        workflow_id="workflow_mriqc",
        recipe_target="neurodesk",
        report_dir=tmp_path,
        vm_name="vm",
        zone="zone",
        project="project",
        namespace="ns",
        pod="pod",
        participant_label="01",
        staged_bids_root="/remote/bids",
        staged_qc_tsv=None,
        staged_fs_license=None,
        remote_input_root="/remote/input",
        remote_output_root="/remote/output",
        executables={},
        request_timeout_s=5.0,
        remote_execute_timeout_s=30.0,
        remote_launch_timeout_s=5.0,
        remote_timeout_grace_s=10.0,
        poll_interval_s=1.0,
        heartbeat_interval_s=2.0,
        artifact_download_timeout_s=10.0,
        dry_run=False,
    )

    assert result["classification"] == "failed_surface"
    assert result["reason"] == "artifact_download_failed"


def test_emit_progress_and_subprocess_forward_to_active_research_logger(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeLogger:
        def __init__(self) -> None:
            self.progress: list[tuple[str, dict[str, object]]] = []
            self.commands: list[dict[str, object]] = []

        def record_progress(self, message: str, **metadata: object) -> None:
            self.progress.append((message, metadata))

        def record_external_command(self, cmd: list[str], **kwargs: object) -> None:
            self.commands.append({"cmd": list(cmd), **kwargs})

    logger = FakeLogger()
    monkeypatch.setattr(mod, "_ACTIVE_RESEARCH_LOGGER", logger)
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *args, **kwargs: mod.subprocess.CompletedProcess(
            args[0], 0, stdout="ok", stderr=""
        ),
    )

    mod.emit_progress(tmp_path, "[auth] test progress", stage="auth")
    proc = mod._run_subprocess(["gcloud", "auth", "list"], timeout_s=1.0)

    assert proc.returncode == 0
    assert logger.progress == [("[auth] test progress", {"stage": "auth"})]
    assert logger.commands[0]["cmd"] == ["gcloud", "auth", "list"]
    assert logger.commands[0]["returncode"] == 0
