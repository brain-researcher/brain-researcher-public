from __future__ import annotations

from pathlib import Path

import numpy as np
from brain_researcher.services.mcp import runstore


def _configure_tool_execute_env(
    monkeypatch,
    tmp_path: Path,
    *,
    allowlist: set[str],
    run_root: Path | None = None,
    use_real_toolspec_lookup: bool = False,
) -> None:
    from brain_researcher.services.mcp import server as srv

    allowed_root = tmp_path.resolve()
    run_root_path = (run_root or tmp_path).resolve()

    monkeypatch.setenv("BR_ALLOWED_ROOTS", str(allowed_root))
    monkeypatch.setenv("BR_MCP_ALLOWED_ROOTS", str(allowed_root))
    monkeypatch.setattr(runstore, "RUN_ROOT", run_root_path)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [allowed_root])
    monkeypatch.setattr(srv, "ENABLE_TOOL_EXECUTE", True)
    monkeypatch.setattr(srv, "TOOL_EXECUTE_ALLOWLIST", set(allowlist))
    monkeypatch.setattr(srv, "ALLOW_NETWORK", False)
    monkeypatch.setattr(srv, "AGENT_MULTIAGENT_ENABLED", False)
    monkeypatch.setattr(srv, "AGENT_CRITIC_TOOL_GATE", False)

    if use_real_toolspec_lookup:

        def _real_toolspec_with_schema(tool_id: str):
            spec = srv._get_registry().get_toolspec_by_name(tool_id)
            if spec is None:
                return None
            return srv._enrich_toolspec_schema(spec.model_copy(deep=True))

        monkeypatch.setattr(srv, "_get_toolspec_with_schema", _real_toolspec_with_schema)


def test_tool_execute_promotes_execution_pack_to_top_level_response(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.result import ToolResult
    from brain_researcher.services.tools.spec import ToolSpec

    _configure_tool_execute_env(
        monkeypatch,
        tmp_path,
        allowlist={"python.test_pack.run"},
    )
    monkeypatch.setattr(
        srv,
        "_call_preflight_tool_call",
        lambda tool_id, params, allowlist=None, step_id=None, allow_remap=False: (
            ToolSpec(name=tool_id, description="stub", backend="python"),
            [],
        ),
    )

    pack_info = {
        "workspace": str(tmp_path / "artifacts" / "step-01-s1" / "execution_pack"),
        "pack_manifest": str(
            tmp_path
            / "artifacts"
            / "step-01-s1"
            / "execution_pack"
            / "pack_manifest.json"
        ),
        "run_pack": str(
            tmp_path / "artifacts" / "step-01-s1" / "execution_pack" / "run_pack.py"
        ),
        "run_pack_command": "python run_pack.py",
    }

    monkeypatch.setattr(
        srv,
        "_execute_tool_with_timeout",
        lambda **kwargs: ToolResult(
            status="success",
            data={"ok": True},
            metadata={
                "backend": "python",
                "execution_mode": "direct",
                "execution_pack": pack_info,
            },
        ),
    )

    resp = srv.tool_execute("python.test_pack.run", params={"x": 1})

    assert resp["ok"] is True
    assert resp["execution_pack"] == pack_info
    assert resp["result"]["metadata"]["execution_pack"] == pack_info


def test_tool_execute_real_connectivity_execution_returns_execution_pack(
    tmp_path, monkeypatch
):
    from brain_researcher.services.mcp import server as srv

    run_root = tmp_path / "runs"
    work_dir = tmp_path / "work"
    output_dir = tmp_path / "artifacts"
    ts_path = tmp_path / "timeseries.npy"
    out_file = output_dir / "connectivity_matrix_fisherz.npy"

    run_root.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(0)
    np.save(ts_path, rng.normal(size=(60, 8)))

    _configure_tool_execute_env(
        monkeypatch,
        tmp_path,
        allowlist={"connectivity_matrix"},
        run_root=run_root,
        use_real_toolspec_lookup=True,
    )

    resp = srv.tool_execute(
        "connectivity_matrix",
        params={
            "timeseries": str(ts_path),
            "kind": "correlation",
            "fisher_z": True,
            "output_file": str(out_file),
        },
        work_dir=str(work_dir),
        output_dir=str(output_dir),
    )

    assert resp["ok"] is True, resp
    pack = resp.get("execution_pack")
    assert isinstance(pack, dict)
    assert resp["result"]["metadata"]["execution_pack"] == pack

    pack_workspace = output_dir / "execution_pack"
    assert pack["workspace"] == str(pack_workspace)
    assert pack["pack_manifest"] == str(pack_workspace / "pack_manifest.json")
    assert pack["run_pack"] == str(pack_workspace / "run_pack.py")
    assert Path(pack["pack_manifest"]).is_file()
    assert Path(pack["run_pack"]).is_file()
    assert (pack_workspace / "params.json").is_file()
    assert (pack_workspace / "run_connectivity_matrix.py").is_file()
    assert out_file.is_file()
