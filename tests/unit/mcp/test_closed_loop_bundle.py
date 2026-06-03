from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

import pytest
from brain_researcher.services.mcp import runstore


@pytest.fixture(autouse=True)
def _stub_toolspec_registry(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    def fake_get_toolspec_with_schema(tool_id: str):
        if tool_id != "extract_timeseries":
            return None
        return ToolSpec(
            name="extract_timeseries",
            description="stub",
            backend="python",
            python_class="json:loads",
            required=["img", "atlas"],
        )

    monkeypatch.setattr(srv, "_get_toolspec_with_schema", fake_get_toolspec_with_schema)


def _wait_for_status(srv, run_id: str, *, timeout_s: float = 5.0) -> str:
    deadline = time.time() + timeout_s
    status = "unknown"
    while time.time() < deadline:
        run = srv.run_get(run_id)
        assert run["ok"] is True
        status = run["run"]["status"]
        if status in {"succeeded", "failed", "cancelled"}:
            return status
        time.sleep(0.05)
    return status


def _wait_for_files(paths: list[Path], *, timeout_s: float = 5.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if all(path.exists() for path in paths):
            return True
        time.sleep(0.05)
    return False


def test_tool_execute_writes_closed_loop_bundle(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"extract_timeseries"})
    srv._ensure_dirs()

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "ok.txt").write_text("ok", encoding="utf-8")
        return ToolResult(
            status="success", data={"stdout": "hello", "stderr": ""}, error=None
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    resp = srv.tool_execute("extract_timeseries", params={"img": "x", "atlas": "y"})
    assert resp["ok"] is True
    run_id = resp["run_id"]
    run_dir = tmp_path / "runs" / run_id
    assert _wait_for_files(
        [
            run_dir / "trace.jsonl",
            run_dir / "provenance.json",
            run_dir / "trajectory.json",
            run_dir / "observation.json",
            run_dir / "analysis_bundle.json",
        ]
    )

    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    assert bundle["run_id"] == run_id
    assert bundle["files"]["trace_jsonl"] == "trace.jsonl"


def test_tool_execute_schema_validation_blocks_missing_required(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"extract_timeseries"})
    srv._ensure_dirs()

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        return ToolResult(status="success", data={"tool_id": tool_id}, error=None)

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    resp = srv.tool_execute("extract_timeseries", params={"img": "x"})
    assert resp["ok"] is False
    assert resp["error"] == "params_invalid"
    assert any(
        i.get("code") == "params_missing_required" for i in resp.get("issues", [])
    )
    assert resp.get("run_id")
    run_dir = tmp_path / "runs" / resp["run_id"]
    assert (run_dir / "observation.json").exists()
    assert (run_dir / "analysis_bundle.json").exists()


def test_pipeline_execute_writes_closed_loop_bundle(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    srv._ensure_dirs()

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "ok.txt").write_text("ok", encoding="utf-8")
        return ToolResult(
            status="success", data={"stdout": "", "stderr": ""}, error=None
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    resp = srv.pipeline_execute(
        {
            "steps": [
                {"tool": "extract_timeseries", "params": {"img": "x", "atlas": "y"}}
            ],
            "execution": {
                "schema_version": "br-plan-execution-v1",
                "allowed_tools": ["extract_timeseries"],
                "approval_level": "confirm",
                "run_mode_hint": "confirm_before_execute",
            },
        },
        approval_phrase=srv.PIPELINE_EXECUTE_CONFIRM_PHRASE,
    )
    assert resp["ok"] is True
    run_id = resp["run_id"]

    assert _wait_for_status(srv, run_id) == "succeeded"

    run_dir = tmp_path / "runs" / run_id
    assert _wait_for_files(
        [
            run_dir / "trace.jsonl",
            run_dir / "provenance.json",
            run_dir / "trajectory.json",
            run_dir / "observation.json",
            run_dir / "analysis_bundle.json",
        ]
    )

    obs = json.loads((run_dir / "observation.json").read_text(encoding="utf-8"))
    assert obs["run_id"] == run_id
    assert obs["files"]["trace_jsonl"] == "trace.jsonl"


def test_tool_execute_rm_logging_disabled_leaves_bundle_fields_unchanged(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"extract_timeseries"})
    monkeypatch.setattr(srv, "RM_LOGGING_ENABLED", False)
    monkeypatch.setattr(srv, "RM_LOGGING_POLICY", "redact_raw_vault")
    srv._ensure_dirs()

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "ok.txt").write_text("ok", encoding="utf-8")
        return ToolResult(
            status="success", data={"stdout": "hello", "stderr": ""}, error=None
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    resp = srv.tool_execute("extract_timeseries", params={"img": "x", "atlas": "y"})
    assert resp["ok"] is True
    run_dir = tmp_path / "runs" / resp["run_id"]

    obs = json.loads((run_dir / "observation.json").read_text(encoding="utf-8"))
    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    assert obs["files"]["trace_jsonl"] == "trace.jsonl"
    assert bundle["files"]["trace_jsonl"] == "trace.jsonl"
    assert not any(
        key.startswith(("rm_", "vault_")) for key in (obs.get("files") or {})
    )
    assert not any(
        key.startswith(("rm_", "vault_")) for key in (bundle.get("files") or {})
    )
    assert not any(
        str(item.get("role") or "").startswith(("rm_", "vault_"))
        for item in bundle.get("file_manifest", [])
        if isinstance(item, dict)
    )


def test_tool_execute_rm_logging_enabled_writes_and_references_files(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"extract_timeseries"})
    monkeypatch.setattr(srv, "RM_LOGGING_ENABLED", True)
    monkeypatch.setattr(srv, "RM_LOGGING_POLICY", "redact_raw_vault")
    srv._ensure_dirs()

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        if output_dir:
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "ok.txt").write_text("ok", encoding="utf-8")
        return ToolResult(
            status="success", data={"stdout": "hello", "stderr": ""}, error=None
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    def fake_generate_rm_logging_files(
        *,
        run_dir,
        run_id,
        policy,
        provenance,
        record,
        tool_calls,
        preflight_issues,
    ):
        del run_id, provenance, record, tool_calls, preflight_issues
        assert policy == "redact_raw_vault"
        base = run_dir / "artifacts" / "rm_logging"
        base.mkdir(parents=True, exist_ok=True)
        paths = {
            "pairwise_redacted": base / "pairwise.redacted.jsonl",
            "process_redacted": base / "process.redacted.jsonl",
            "pairwise_raw": base / "pairwise.raw.vault.jsonl",
            "process_raw": base / "process.raw.vault.jsonl",
        }
        for path in paths.values():
            path.write_text('{"ok": true}\n', encoding="utf-8")
        return {
            "status": "ok",
            "files": {key: str(value) for key, value in paths.items()},
        }

    monkeypatch.setitem(
        sys.modules,
        "brain_researcher.services.agent.rm_logging",
        types.SimpleNamespace(generate_rm_logging_files=fake_generate_rm_logging_files),
    )

    resp = srv.tool_execute("extract_timeseries", params={"img": "x", "atlas": "y"})
    assert resp["ok"] is True
    run_dir = tmp_path / "runs" / resp["run_id"]

    expected_files = {
        "rm_pairwise_redacted_json": "artifacts/rm_logging/pairwise.redacted.jsonl",
        "rm_process_redacted_json": "artifacts/rm_logging/process.redacted.jsonl",
        "rm_pairwise_raw_json": "artifacts/rm_logging/pairwise.raw.vault.jsonl",
        "rm_process_raw_json": "artifacts/rm_logging/process.raw.vault.jsonl",
    }
    for relpath in expected_files.values():
        assert (run_dir / relpath).exists()

    obs = json.loads((run_dir / "observation.json").read_text(encoding="utf-8"))
    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))

    for key, relpath in expected_files.items():
        assert obs["files"][key] == relpath
        assert bundle["files"][key] == relpath

    assert (
        obs["rm_pairwise"]["redacted_json"]
        == expected_files["rm_pairwise_redacted_json"]
    )
    assert obs["rm_pairwise"]["raw_json"] == expected_files["rm_pairwise_raw_json"]
    assert (
        obs["rm_process"]["redacted_json"] == expected_files["rm_process_redacted_json"]
    )
    assert obs["rm_process"]["raw_json"] == expected_files["rm_process_raw_json"]
    assert (
        bundle["rm_pairwise"]["redacted_json"]
        == expected_files["rm_pairwise_redacted_json"]
    )
    assert bundle["rm_process"]["raw_json"] == expected_files["rm_process_raw_json"]

    manifest_paths = {
        item.get("path")
        for item in bundle.get("file_manifest", [])
        if isinstance(item, dict)
    }
    assert set(expected_files.values()).issubset(manifest_paths)
    assert provenance["rm_logging"]["policy"] == "redact_raw_vault"
    assert provenance["rm_logging"]["status"] == "ok"
    assert (
        bundle["policy_snapshot"]["rm_logging"]["files"]["rm_pairwise_redacted_json"]
        == "artifacts/rm_logging/pairwise.redacted.jsonl"
    )


def test_tool_execute_rm_logging_enabled_real_helper_writes_redacted_and_raw(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"extract_timeseries"})
    monkeypatch.setattr(srv, "RM_LOGGING_ENABLED", True)
    monkeypatch.setattr(srv, "RM_LOGGING_POLICY", "redact_raw_vault")
    srv._ensure_dirs()

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        del tool_id, parameters, work_dir, output_dir, preview
        return ToolResult(
            status="success", data={"stdout": "hello", "stderr": ""}, error=None
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    resp = srv.tool_execute(
        "extract_timeseries",
        params={"img": "x", "atlas": "y", "note": "api_key=SECRET"},
    )
    assert resp["ok"] is True
    run_dir = tmp_path / "runs" / resp["run_id"]

    expected = {
        "rm_pairwise_redacted_json": "rm/pairwise.redacted.json",
        "rm_process_redacted_json": "rm/process.redacted.json",
        "rm_pairwise_raw_json": "vault/rm_pairwise.raw.json",
        "rm_process_raw_json": "vault/rm_process.raw.json",
    }
    for relpath in expected.values():
        assert (run_dir / relpath).exists()

    obs = json.loads((run_dir / "observation.json").read_text(encoding="utf-8"))
    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    for key, relpath in expected.items():
        assert obs["files"][key] == relpath
        assert bundle["files"][key] == relpath

    assert obs["rm_pairwise"]["schema_version"] == "rm-log-metadata-v1"
    assert obs["rm_process"]["schema_version"] == "rm-log-metadata-v1"
    assert str(obs["rm_pairwise"]["redacted_checksum"]).startswith("sha256:")
    assert str(obs["rm_process"]["raw_checksum"]).startswith("sha256:")
    assert (
        bundle["rm_pairwise"]["redacted_json"] == expected["rm_pairwise_redacted_json"]
    )
    assert bundle["rm_process"]["raw_json"] == expected["rm_process_raw_json"]

    redacted = (run_dir / expected["rm_pairwise_redacted_json"]).read_text(
        encoding="utf-8"
    )
    raw = (run_dir / expected["rm_pairwise_raw_json"]).read_text(encoding="utf-8")
    assert "api_key=***REDACTED***" in redacted
    assert "api_key=SECRET" in raw


def test_tool_execute_rm_logging_fail_open_on_helper_error(tmp_path, monkeypatch):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(runstore, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", {"extract_timeseries"})
    monkeypatch.setattr(srv, "RM_LOGGING_ENABLED", True)
    monkeypatch.setattr(srv, "RM_LOGGING_POLICY", "redact_raw_vault")
    srv._ensure_dirs()

    from brain_researcher.services.tools.result import ToolResult

    def fake_execute_tool(
        tool_id, parameters, work_dir=None, output_dir=None, preview=False
    ):
        return ToolResult(
            status="success", data={"stdout": "hello", "stderr": ""}, error=None
        )

    monkeypatch.setattr(srv, "execute_tool", fake_execute_tool)

    def raising_helper(**kwargs):
        del kwargs
        raise RuntimeError("rm logging failed")

    monkeypatch.setitem(
        sys.modules,
        "brain_researcher.services.agent.rm_logging",
        types.SimpleNamespace(generate_rm_logging_files=raising_helper),
    )

    resp = srv.tool_execute("extract_timeseries", params={"img": "x", "atlas": "y"})
    assert resp["ok"] is True
    run_dir = tmp_path / "runs" / resp["run_id"]
    assert (run_dir / "observation.json").exists()
    assert (run_dir / "analysis_bundle.json").exists()

    bundle = json.loads((run_dir / "analysis_bundle.json").read_text(encoding="utf-8"))
    assert bundle["policy_snapshot"]["rm_logging"]["status"] == "error"
