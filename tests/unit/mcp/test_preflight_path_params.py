from __future__ import annotations

import pytest


@pytest.fixture
def _stub_tool_preflight(monkeypatch):
    from brain_researcher.services.mcp import server as srv
    from brain_researcher.services.tools.spec import ToolSpec

    monkeypatch.setattr(
        srv,
        "_get_toolspec_with_schema",
        lambda tool_id: ToolSpec(
            name=tool_id,
            description="stub",
            json_schema={"type": "object"},
        ),
    )
    monkeypatch.setattr(
        srv,
        "_prepare_spec_for_network_policy",
        lambda spec, patch_catalog=True: spec,
    )
    monkeypatch.setattr(srv, "_policy_check_tool", lambda _spec: [])
    monkeypatch.setattr(srv, "AGENT_MULTIAGENT_ENABLED", False)
    monkeypatch.setattr(srv, "AGENT_CRITIC_TOOL_GATE", False)


def _issue_codes(issues):
    return {str(item.get("code")) for item in issues if isinstance(item, dict)}


def test_preflight_path_param_reports_missing_input_but_not_missing_output(
    tmp_path,
    monkeypatch,
    _stub_tool_preflight,
):
    from brain_researcher.services.mcp import server as srv

    allowed = tmp_path / "allowed"
    allowed.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [allowed.resolve()])

    _spec, issues = srv._preflight_tool_call(
        "demo.tool",
        params={
            "input_file": str(allowed / "missing_input.txt"),
            "output_file": str(allowed / "future_output.txt"),
        },
    )

    codes = _issue_codes(issues)
    assert "input_not_found" in codes
    assert "path_not_allowed" not in codes
    assert "invalid_path_value" not in codes


def test_preflight_path_param_rejects_disallowed_local_paths(
    tmp_path,
    monkeypatch,
    _stub_tool_preflight,
):
    from brain_researcher.services.mcp import server as srv

    allowed = tmp_path / "allowed"
    allowed.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [allowed.resolve()])

    outside = tmp_path / "outside" / "input.nii.gz"
    _spec, issues = srv._preflight_tool_call(
        "demo.tool",
        params={"input_path": str(outside)},
    )

    codes = _issue_codes(issues)
    assert "path_not_allowed" in codes
    assert "input_not_found" not in codes


def test_preflight_path_param_ignores_urls_and_s3_uris(
    monkeypatch,
    _stub_tool_preflight,
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [srv.PROJECT_ROOT.resolve()])

    _spec, issues = srv._preflight_tool_call(
        "demo.tool",
        params={
            "input_file": "https://example.org/data.nii.gz",
            "model_path": "s3://bucket/key/model.bin",
        },
    )

    codes = _issue_codes(issues)
    assert "input_not_found" not in codes
    assert "path_not_allowed" not in codes
    assert "invalid_path_value" not in codes


def test_preflight_path_param_reports_invalid_blank_values(
    monkeypatch,
    _stub_tool_preflight,
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [srv.PROJECT_ROOT.resolve()])

    _spec, issues = srv._preflight_tool_call(
        "demo.tool",
        params={"config_path": "   "},
    )

    assert "invalid_path_value" in _issue_codes(issues)


def test_preflight_path_param_keeps_nonanchored_relative_file_names(
    monkeypatch,
    _stub_tool_preflight,
):
    from brain_researcher.services.mcp import server as srv

    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [srv.PROJECT_ROOT.resolve()])

    _spec, issues = srv._preflight_tool_call(
        "demo.tool",
        params={"input_file": "subject01_bold.nii.gz"},
    )

    codes = _issue_codes(issues)
    assert "input_not_found" not in codes
    assert "path_not_allowed" not in codes
    assert "invalid_path_value" not in codes


def test_preflight_path_param_issue_is_bound_to_step_id(
    tmp_path,
    monkeypatch,
    _stub_tool_preflight,
):
    from brain_researcher.services.mcp import server as srv

    allowed = tmp_path / "allowed"
    allowed.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(srv, "ALLOWED_ROOTS", [allowed.resolve()])

    _spec, issues = srv._preflight_tool_call(
        "demo.tool",
        params={"input_file": str(allowed / "missing_input.txt")},
        step_id="s42",
    )

    input_issue = next(
        item for item in issues if item.get("code") == "input_not_found"
    )
    assert input_issue.get("step_id") == "s42"
