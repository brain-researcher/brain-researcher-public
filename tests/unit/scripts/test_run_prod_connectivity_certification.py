"""Unit tests for scripts/ops/run_prod_connectivity_certification.py."""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

from scripts.ops import run_prod_connectivity_certification as mod


def test_resolve_prod_mcp_token_prefers_local_token(monkeypatch) -> None:
    monkeypatch.setattr(mod, "resolve_mcp_token", lambda: "local-token")
    token = mod.resolve_prod_mcp_token(
        vm_name="brain-researcher-vm",
        zone="us-west1-b",
        project="hai-gcp-dialogue-brain",
        namespace="brain-researcher-core",
        secret_name="brain-researcher-mcp-auth",
        secret_key="BR_MCP_AUTH_TOKEN",
        timeout_s=5.0,
    )
    assert token == "local-token"


def test_resolve_prod_mcp_token_decodes_secret_when_local_missing(monkeypatch) -> None:
    monkeypatch.setattr(mod, "resolve_mcp_token", lambda: None)
    encoded = base64.b64encode(b"secret-token").decode("ascii")
    manifest = json.dumps({"data": {"BR_MCP_AUTH_TOKEN": encoded}})
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
        project="hai-gcp-dialogue-brain",
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
                "BR_MCP_AUTH_TOKENS_JSON": base64.b64encode(
                    b'{"kid":{"token_hash":"abc"}}'
                ).decode("ascii"),
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
            project="hai-gcp-dialogue-brain",
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


def test_build_workflow_plans_uses_derivative_first_contract() -> None:
    plans = mod.build_workflow_plans(
        {
            "atlas_path": "/data/atlas.nii.gz",
            "single_subject_bold": "/data/sub-01_bold.nii.gz",
            "single_subject_confounds": "/data/sub-01_confounds.tsv",
            "single_subject_mask": "/data/sub-01_mask.nii.gz",
            "group_subject_bolds": [
                "/data/sub-01_bold.nii.gz",
                "/data/sub-02_bold.nii.gz",
            ],
            "group_labels": [0, 1],
        },
        remote_output_root="/remote/out",
        remote_work_root="/remote/work",
    )

    workflow_ids = [plan.workflow_id for plan in plans]
    assert set(workflow_ids) == set(mod.WORKFLOW_IDS)

    gradients = next(
        plan for plan in plans if plan.workflow_id == "workflow_connectivity_gradients"
    )
    gradient_steps = gradients.plan["steps"]
    assert gradient_steps[0]["tool"] == "extract_timeseries"
    assert (
        gradient_steps[1]["params"]["timeseries"]
        == "${steps.extract_ts.data.outputs.timeseries}"
    )

    nbs = next(
        plan
        for plan in plans
        if plan.workflow_id == "workflow_network_based_statistics"
    )
    nbs_steps = nbs.plan["steps"]
    assert nbs_steps[0]["tool"] == "workflow_group_ica"
    assert nbs_steps[0]["params"]["labels"] == [0, 1]
    assert nbs_steps[1]["params"]["timeseries"] == (
        "${steps.group_ica_seed.data.outputs.timecourses_file}"
    )


def test_classify_workflow_result_separates_preconditions_and_surface() -> None:
    classification, reason = mod.classify_workflow_result(
        validate_payload={
            "ok": False,
            "issues": [{"code": "params_missing_required", "message": "missing atlas"}],
        },
        execute_payload=None,
        run_payload=None,
    )
    assert classification == "failed_precondition"
    assert "missing atlas" in reason

    classification, reason = mod.classify_workflow_result(
        validate_payload=None,
        execute_payload=None,
        run_payload=None,
        surface_error="transport failed",
    )
    assert classification == "failed_surface"
    assert reason == "transport failed"


def test_wait_for_run_returns_terminal_payload(tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object],
            *,
            prime: bool,
            initialize: bool,
        ):
            assert tool_name == "run_get"
            self.calls += 1
            status = "running" if self.calls == 1 else "succeeded"
            return {
                "ok": True,
                "payload": {"ok": True, "run": {"status": status, "steps": []}},
            }

    poll = mod.wait_for_run(
        FakeClient(),  # type: ignore[arg-type]
        "run-123",
        timeout_s=1.0,
        poll_interval_s=0.0,
        report_dir=tmp_path,
        workflow_id="workflow_rest_connectome_e2e",
    )
    assert poll["ok"] is True
    assert poll["payload"]["run"]["status"] == "succeeded"
    assert poll["attempts"] == 2


def test_wait_for_run_stops_on_payload_error(tmp_path: Path) -> None:
    class FakeClient:
        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object],
            *,
            prime: bool,
            initialize: bool,
        ):
            assert tool_name == "run_get"
            return {
                "ok": True,
                "payload": {"ok": False, "error": "run not found"},
            }

    poll = mod.wait_for_run(
        FakeClient(),  # type: ignore[arg-type]
        "run-missing",
        timeout_s=1.0,
        poll_interval_s=0.0,
        report_dir=tmp_path,
        workflow_id="workflow_rest_connectome_e2e",
    )
    assert poll["ok"] is False
    assert poll["error"] == "run not found"


def test_wait_for_run_retries_transient_transport_error(tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object],
            *,
            prime: bool,
            initialize: bool,
        ):
            assert tool_name == "run_get"
            self.calls += 1
            if self.calls == 1:
                return {"ok": False, "http_status": 502}
            return {
                "ok": True,
                "payload": {"ok": True, "run": {"status": "succeeded", "steps": []}},
            }

    poll = mod.wait_for_run(
        FakeClient(),  # type: ignore[arg-type]
        "run-123",
        timeout_s=1.0,
        poll_interval_s=0.0,
        report_dir=tmp_path,
        workflow_id="workflow_rest_connectome_e2e",
    )
    assert poll["ok"] is True
    assert poll["attempts"] == 2


def test_summarize_results_counts_classifications() -> None:
    summary = mod.summarize_results(
        [
            {"workflow_id": "a", "classification": "verified"},
            {"workflow_id": "b", "classification": "failed_surface"},
            {"workflow_id": "c", "classification": "failed_precondition"},
        ]
    )
    assert summary["total"] == 3
    assert summary["verified"] == 1
    assert summary["failed_surface"] == 1
    assert summary["failed_precondition"] == 1


def test_probe_health_accepts_expected_mcp_auth_challenge(monkeypatch) -> None:
    responses = [
        subprocess.CompletedProcess(
            ["curl"],
            0,
            stdout='{"ok":false,"error":"missing_bearer_token"}\n401',
            stderr="",
        )
    ]
    monkeypatch.setattr(
        mod,
        "_health_candidates",
        lambda _: ["https://brain-researcher.com/mcp/healthz"],
    )
    monkeypatch.setattr(
        mod, "_run_subprocess", lambda *args, **kwargs: responses.pop(0)
    )
    health = mod.probe_health("https://brain-researcher.com/mcp", timeout_s=5.0)
    assert health["ok"] is True
    assert health["auth_challenge"] is True


def test_validate_remote_artifacts_for_rest_connectome_contract() -> None:
    inspected = {
        "output_dir": "/remote/out",
        "exists": True,
        "file_count": 5,
        "files": {
            "timeseries/timeseries.npy": {
                "path": "/remote/out/timeseries/timeseries.npy"
            },
            "timeseries/timeseries.csv": {
                "path": "/remote/out/timeseries/timeseries.csv"
            },
            "timeseries/timeseries_summary.json": {
                "path": "/remote/out/timeseries/timeseries_summary.json"
            },
            "atlas/schaefer_100.nii.gz": {
                "path": "/remote/out/atlas/schaefer_100.nii.gz"
            },
            "connectivity_matrix.npy": {"path": "/remote/out/connectivity_matrix.npy"},
        },
    }
    payload = mod.validate_remote_artifacts(
        workflow_id="workflow_rest_connectome_e2e",
        inspected=inspected,
    )
    assert payload["ok"] is True
    assert payload["missing_required"] == []
    assert payload["required_matches"]["connectivity_matrix.npy"] == [
        "connectivity_matrix.npy"
    ]


def test_get_local_recipe_payload_for_direct_workflow(monkeypatch) -> None:
    class FakeClient:
        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object],
            *,
            prime: bool,
            initialize: bool,
        ):
            assert tool_name == "get_execution_recipe"
            assert arguments["tool_id"] == "workflow_rest_connectome_e2e"
            return {
                "ok": True,
                "payload": {
                    "ok": True,
                    "recipe": {
                        "files": {
                            "params.json": json.dumps({"img": "/data/img.nii.gz"}),
                            "run_workflow_rest_connectome_e2e.py": "print('ok')",
                        }
                    },
                },
            }

    workflow = mod.WorkflowPlan(
        workflow_id="workflow_rest_connectome_e2e",
        plan={
            "steps": [
                {
                    "tool": "workflow_rest_connectome_e2e",
                    "params": {"img": "/data/img.nii.gz", "output_dir": "/tmp/out"},
                }
            ]
        },
    )
    _response, payload = mod.get_local_recipe_payload(FakeClient(), workflow)  # type: ignore[arg-type]
    assert payload is not None
    assert payload["run_pack"]["runtime"]["target"] == "python"
    assert payload["local_run"]["workspace"].endswith(
        "workflow_rest_connectome_e2e_python_recipe"
    )


def test_get_handoff_recipe_payload_for_composite_workflow() -> None:
    class FakeClient:
        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object],
            *,
            prime: bool,
            initialize: bool,
        ):
            assert tool_name == "get_execution_recipe"
            assert arguments["tool_id"] == "workflow_connectivity_gradients"
            assert arguments["target_runtime"] == "python"
            return {
                "ok": True,
                "payload": {
                    "ok": True,
                    "recipe": {
                        "files": {
                            "params.json": "{}",
                            "run_workflow_connectivity_gradients.py": "print('ok')",
                        }
                    },
                },
            }

    workflow = mod.WorkflowPlan(
        workflow_id="workflow_connectivity_gradients",
        plan={
            "steps": [
                {"tool": "extract_timeseries"},
                {"tool": "workflow_connectivity_gradients"},
            ]
        },
    )
    _response, payload = mod.get_handoff_recipe_payload(FakeClient(), workflow)  # type: ignore[arg-type]
    assert payload is not None
    assert payload["run_pack"]["runtime"]["target"] == "python"
    assert payload["local_run"]["workspace"].endswith(
        "workflow_connectivity_gradients_python_recipe"
    )


def test_build_handoff_bundle_copies_atlas_and_patches_params(tmp_path: Path) -> None:
    extracted = (
        tmp_path
        / "downloaded_artifacts"
        / "output_dir"
        / "workflow_rest_connectome_e2e"
    )
    atlas_dir = extracted / "atlas"
    atlas_dir.mkdir(parents=True)
    atlas_file = (
        atlas_dir / "Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    atlas_file.write_bytes(b"atlas")

    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": "{}",
                "run_workflow_rest_connectome_e2e.py": "print('ok')",
            }
        }
    }
    run_pack = {
        "workspace": "./workflow_rest_connectome_e2e_python_recipe",
        "runtime": {"target": "python"},
    }

    payload = mod.build_handoff_bundle(
        report_dir=tmp_path,
        workflow_id="workflow_rest_connectome_e2e",
        recipe_payload=recipe_payload,
        run_pack=run_pack,
        downloaded_artifacts={
            "extracted_dir": str(tmp_path / "downloaded_artifacts" / "output_dir")
        },
        run_payload=None,
        vm_name="vm",
        zone="zone",
        project="project",
        namespace="ns",
        pod="pod",
        timeout_s=10.0,
    )
    assert payload["ok"] is True
    assert payload["missing_inputs"] == ["img"]
    workspace = Path(payload["workspace"])
    params = json.loads((workspace / "params.json").read_text(encoding="utf-8"))
    assert params["atlas_path"] == (
        "bundled_inputs/atlas/Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
    )
    assert params["img"] == "<set-local-bold.nii.gz>"
    assert (workspace / "params.recipe.json").exists()


def test_build_handoff_bundle_downloads_remote_atlas_when_needed(
    monkeypatch, tmp_path: Path
) -> None:
    downloaded: list[Path] = []

    def fake_download_remote_file(**kwargs):
        destination = kwargs["destination"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"atlas")
        downloaded.append(destination)
        return {"ok": True, "local_path": str(destination)}

    monkeypatch.setattr(mod, "download_remote_file", fake_download_remote_file)
    recipe_payload = {
        "recipe": {
            "files": {
                "params.json": "{}",
                "run_workflow_rest_connectome_e2e.py": "print('ok')",
            }
        }
    }
    run_pack = {
        "workspace": "./workflow_rest_connectome_e2e_python_recipe",
        "runtime": {"target": "python"},
    }
    run_payload = {
        "run": {
            "steps": [
                {
                    "params": {
                        "atlas": "/app/data/atlases/schaefer_2018/Schaefer2018_100Parcels_7Networks_order_FSLMNI152_2mm.nii.gz"
                    }
                }
            ]
        }
    }

    payload = mod.build_handoff_bundle(
        report_dir=tmp_path,
        workflow_id="workflow_rest_connectome_e2e",
        recipe_payload=recipe_payload,
        run_pack=run_pack,
        downloaded_artifacts=None,
        run_payload=run_payload,
        vm_name="vm",
        zone="zone",
        project="project",
        namespace="ns",
        pod="pod",
        timeout_s=10.0,
    )
    assert payload["ok"] is True
    assert downloaded
    params = json.loads(Path(payload["params_json"]).read_text(encoding="utf-8"))
    assert params["atlas_path"].startswith("bundled_inputs/atlas/")


def test_certify_workflow_downloads_artifacts_on_verified(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeClient:
        def call_tool(
            self,
            tool_name: str,
            arguments: dict[str, object],
            *,
            prime: bool,
            initialize: bool,
        ):
            if tool_name == "get_execution_recipe":
                return {
                    "ok": True,
                    "payload": {
                        "ok": True,
                        "hosted_via_br_mcp_service": False,
                        "target_runtime": "python",
                        "recipe": {
                            "files": {
                                "params.json": json.dumps(
                                    arguments.get("params") or {}
                                ),
                                "run_workflow_rest_connectome_e2e.py": "print('ok')",
                            },
                            "setup_commands": [],
                            "run_command": "python run_workflow_rest_connectome_e2e.py",
                        },
                    },
                }
            raise AssertionError(tool_name)

    monkeypatch.setattr(
        mod,
        "stage_recipe_files",
        lambda **kwargs: {
            "ok": True,
            "recipe_dir": kwargs["remote_dir"],
            "file_count": 2,
        },
    )
    monkeypatch.setattr(
        mod,
        "execute_remote_recipe",
        lambda **kwargs: {
            "ok": True,
            "returncode": 0,
            "recipe_dir": kwargs["recipe_dir"],
        },
    )
    monkeypatch.setattr(
        mod,
        "inspect_remote_output_dir",
        lambda **kwargs: {
            "output_dir": kwargs["output_dir"],
            "exists": True,
            "file_count": 4,
            "files": {
                "timeseries/timeseries.npy": {
                    "path": "/remote/out/timeseries/timeseries.npy"
                },
                "timeseries/timeseries.csv": {
                    "path": "/remote/out/timeseries/timeseries.csv"
                },
                "timeseries/timeseries_summary.json": {
                    "path": "/remote/out/timeseries/timeseries_summary.json"
                },
                "connectivity_matrix.npy": {
                    "path": "/remote/out/connectivity_matrix.npy"
                },
            },
        },
    )
    monkeypatch.setattr(
        mod,
        "download_remote_output_dir",
        lambda **kwargs: {
            "ok": True,
            "download_dir": str(
                tmp_path / "workflow_rest_connectome_e2e" / "downloaded_artifacts"
            ),
            "archive": {"local_path": str(tmp_path / "artifact.tar.gz")},
            "extracted_dir": str(
                tmp_path / "workflow_rest_connectome_e2e" / "extracted"
            ),
            "file_count": 4,
        },
    )
    monkeypatch.setattr(
        mod,
        "build_handoff_bundle",
        lambda **kwargs: {
            "ok": True,
            "bundle_dir": str(
                tmp_path / "workflow_rest_connectome_e2e" / "handoff_bundle"
            ),
            "workspace": str(
                tmp_path
                / "workflow_rest_connectome_e2e"
                / "handoff_bundle"
                / "workflow_rest_connectome_e2e_python_recipe"
            ),
            "bundled_inputs": [],
            "missing_inputs": ["img"],
        },
    )

    workflow = mod.WorkflowPlan(
        workflow_id="workflow_rest_connectome_e2e",
        plan={
            "steps": [
                {
                    "tool": "workflow_rest_connectome_e2e",
                    "output_dir": "/remote/out",
                    "params": {
                        "img": "/data/img.nii.gz",
                        "atlas_name": "Schaefer2018_100",
                        "output_dir": "/remote/out",
                    },
                }
            ]
        },
    )
    result = mod.certify_workflow(
        FakeClient(),  # type: ignore[arg-type]
        workflow,
        dry_run=False,
        poll_timeout_s=1.0,
        poll_interval_s=0.0,
        report_dir=tmp_path,
        vm_name="vm",
        zone="zone",
        project="project",
        namespace="brain-researcher-core",
        artifact_pod="brain-researcher-mcp-abc",
        agent_pod="brain-researcher-agent-0",
        artifact_download_timeout_s=10.0,
    )
    assert result["classification"] == "verified"
    assert result["downloaded_artifacts"]["ok"] is True
    assert result["agent_pod"] == "brain-researcher-agent-0"
    assert result["execution_mode"] == "local_recipe_on_agent"
    assert result["run_pack"]["runtime"]["target"] == "python"
    assert result["local_run"]["workspace"].endswith(
        "workflow_rest_connectome_e2e_python_recipe"
    )
    assert result["handoff_bundle"]["ok"] is True
    assert result["handoff_bundle"]["missing_inputs"] == ["img"]


def test_run_certification_marks_path_discovery_surface_errors(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mod, "resolve_mcp_token", lambda: "local-token")
    monkeypatch.setattr(mod, "probe_health", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(mod, "verify_mcp_smoke", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(
        mod,
        "discover_prod_inputs",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            mod.SurfaceError("transport failed")
        ),
    )

    args = mod.build_arg_parser().parse_args(
        [
            "--output-root",
            str(tmp_path),
            "--workflow-id",
            "workflow_rest_connectome_e2e",
        ]
    )
    exit_code, report_dir, report = mod.run_certification(args)
    assert exit_code == 1
    assert report["summary"]["failed_surface"] == 1
    assert report["path_discovery"]["error"] == "transport failed"
    assert report_dir.exists()


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
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout="ok", stderr=""
        ),
    )

    mod.emit_progress(tmp_path, "[start] test progress", stage="setup")
    proc = mod._run_subprocess(["docker", "ps"], timeout_s=1.0)

    assert proc.returncode == 0
    assert logger.progress == [("[start] test progress", {"stage": "setup"})]
    assert logger.commands[0]["cmd"] == ["docker", "ps"]
    assert logger.commands[0]["returncode"] == 0
