import socket
from pathlib import Path

import pytest

from brain_researcher.services.tools.execution_policy import (
    ExecutionPolicyError,
    enforce_allowed_paths,
    filesystem_guard,
    network_guard,
    policy_check_tool,
    prepare_spec_for_network_policy,
)
from brain_researcher.services.tools.spec import ToolExecutionCapabilities, ToolSpec


@pytest.fixture(autouse=True)
def _enable_execution_policy(monkeypatch):
    # execution_policy.enforcement_enabled() defaults to False under pytest;
    # explicitly enable for this module.
    monkeypatch.setenv("BR_ENFORCE_EXECUTION_POLICY", "1")


def test_enforce_allowed_paths_blocks_outside_allowed_roots():
    spec = ToolSpec(name="test.tool", description="test")

    with pytest.raises(ExecutionPolicyError) as exc_info:
        enforce_allowed_paths(spec, {"img": "/etc/passwd"})

    issues = exc_info.value.issues
    assert any(i.get("code") == "path_outside_allowed_roots" for i in issues)


def test_enforce_allowed_paths_allows_relative_path_with_output_dir(tmp_path):
    spec = ToolSpec(name="test.tool", description="test")

    output_dir = tmp_path / "out"
    output_dir.mkdir(parents=True, exist_ok=True)

    enforce_allowed_paths(
        spec,
        {"output_dir": str(output_dir), "img": "input.nii.gz"},
        output_dir=str(output_dir),
    )


def test_enforce_allowed_paths_tool_specific_allowlist_blocks_other_paths(tmp_path):
    allow_dir = tmp_path / "allow"
    deny_dir = tmp_path / "deny"
    allow_dir.mkdir(parents=True, exist_ok=True)
    deny_dir.mkdir(parents=True, exist_ok=True)

    spec = ToolSpec(
        name="test.tool",
        description="test",
        execution_capabilities=ToolExecutionCapabilities(
            allowed_paths=[str(allow_dir)]
        ),
    )

    with pytest.raises(ExecutionPolicyError) as exc_info:
        enforce_allowed_paths(
            spec,
            {"img": str(deny_dir / "file.nii.gz")},
            output_dir=str(allow_dir),
        )

    issues = exc_info.value.issues
    assert any(i.get("code") == "path_not_in_tool_allowlist" for i in issues)


def test_enforce_allowed_paths_alias_remap_from_env(monkeypatch):
    spec = ToolSpec(name="test.tool", description="test")
    monkeypatch.setenv("BR_ALLOWED_ROOTS", "/app/data")
    monkeypatch.setenv("BR_PATH_ALIAS_MAP", "/host/repo/data=/app/data")

    enforce_allowed_paths(
        spec,
        {"img": "/host/repo/data/ds000157/sub-01_stat-z_statmap.nii.gz"},
    )


def test_enforce_allowed_paths_alias_remap_uses_default_repo_data_mapping(monkeypatch):
    import brain_researcher.services.tools.execution_policy as policy

    spec = ToolSpec(name="test.tool", description="test")
    monkeypatch.setenv("BR_ALLOWED_ROOTS", "/app/data")
    monkeypatch.delenv("BR_PATH_ALIAS_MAP", raising=False)

    host_repo_data = policy.REPO_ROOT / "data" / "openneuro" / "example.nii.gz"
    enforce_allowed_paths(spec, {"img": str(host_repo_data)})


def test_enforce_allowed_paths_treats_script_key_as_path_hint():
    spec = ToolSpec(name="test.tool", description="test")

    with pytest.raises(ExecutionPolicyError) as exc_info:
        enforce_allowed_paths(spec, {"script": "run_fitlins_multiverse_execute"})

    issues = exc_info.value.issues
    assert any(i.get("key") == "script" for i in issues)
    assert any(
        i.get("code") in {"relative_path_without_base", "path_outside_allowed_roots"}
        for i in issues
    )


def test_filesystem_guard_allows_runtime_read_via_alias_mapping(tmp_path, monkeypatch):
    spec = ToolSpec(name="test.tool", description="test")
    host_data = tmp_path / "host_data"
    host_data.mkdir(parents=True, exist_ok=True)
    host_file = host_data / "ok.txt"
    host_file.write_text("ok", encoding="utf-8")

    monkeypatch.setenv("BR_ALLOWED_ROOTS", "/app/data")
    monkeypatch.setenv("BR_PATH_ALIAS_MAP", f"{host_data}=/app/data")

    with filesystem_guard(spec):
        assert host_file.read_text(encoding="utf-8") == "ok"


def test_network_guard_blocks_when_needs_network_false(monkeypatch):
    import brain_researcher.services.tools.execution_policy as policy

    # Ensure the socket guard is freshly installed for this test.
    monkeypatch.setattr(policy, "_SOCKET_GUARD_INSTALLED", False)
    monkeypatch.setattr(socket, "getaddrinfo", policy._ORIGINAL_GETADDRINFO)

    def _should_not_resolve(*_args, **_kwargs):
        raise AssertionError("unexpected DNS resolution")

    monkeypatch.setattr(policy, "_ORIGINAL_GETADDRINFO", _should_not_resolve)

    spec = ToolSpec(
        name="test.tool",
        description="test",
        execution_capabilities=ToolExecutionCapabilities(needs_network=False),
    )

    with network_guard(spec):
        with pytest.raises(socket.gaierror) as exc_info:
            socket.getaddrinfo("example.com", 443)
        assert "network_blocked_by_policy" in str(exc_info.value)


def test_network_guard_blocks_by_default_without_declared_capabilities(monkeypatch):
    import brain_researcher.services.tools.execution_policy as policy

    # Ensure the socket guard is freshly installed for this test.
    monkeypatch.setattr(policy, "_SOCKET_GUARD_INSTALLED", False)
    monkeypatch.setattr(socket, "getaddrinfo", policy._ORIGINAL_GETADDRINFO)

    def _should_not_resolve(*_args, **_kwargs):
        raise AssertionError("unexpected DNS resolution")

    monkeypatch.setattr(policy, "_ORIGINAL_GETADDRINFO", _should_not_resolve)

    spec = ToolSpec(name="test.tool", description="test")

    with network_guard(spec):
        with pytest.raises(socket.gaierror) as exc_info:
            socket.getaddrinfo("example.com", 443)
        assert "network_blocked_by_policy" in str(exc_info.value)


def test_network_guard_allows_only_allowed_domains(monkeypatch):
    import brain_researcher.services.tools.execution_policy as policy

    # Ensure the socket guard is freshly installed for this test.
    monkeypatch.setattr(policy, "_SOCKET_GUARD_INSTALLED", False)
    monkeypatch.setattr(socket, "getaddrinfo", policy._ORIGINAL_GETADDRINFO)

    calls: list[str] = []

    def _fake_getaddrinfo(host, port, *_args, **_kwargs):
        calls.append(f"{host}:{port}")
        return [("AF_INET", "SOCK_STREAM", 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(policy, "_ORIGINAL_GETADDRINFO", _fake_getaddrinfo)

    spec = ToolSpec(
        name="test.tool",
        description="test",
        execution_capabilities=ToolExecutionCapabilities(
            allowed_domains=["example.com"]
        ),
    )

    with network_guard(spec):
        res = socket.getaddrinfo("example.com", 443)
        assert res
        with pytest.raises(socket.gaierror) as exc_info:
            socket.getaddrinfo("openai.com", 443)
        assert "domain_not_allowed" in str(exc_info.value)

    assert calls == ["example.com:443"]


def test_filesystem_guard_blocks_paths_outside_allowed_roots(tmp_path):
    spec = ToolSpec(name="test.tool", description="test")

    allowed = tmp_path / "ok.txt"
    allowed.write_text("ok", encoding="utf-8")

    with filesystem_guard(spec):
        assert allowed.read_text(encoding="utf-8") == "ok"
        with pytest.raises(ExecutionPolicyError):
            Path("/etc/passwd").read_text(encoding="utf-8")

        with pytest.raises(ExecutionPolicyError):
            with open("/etc/should_not_write.txt", "w", encoding="utf-8") as fh:
                fh.write("nope")


def test_policy_check_tool_allows_loopback_when_network_disabled():
    spec = ToolSpec(
        name="local.loopback.tool",
        description="loopback only",
        backend="python",
        execution_capabilities=ToolExecutionCapabilities(
            needs_network=True,
            allowed_domains=["localhost", "127.0.0.1", "::1"],
        ),
    )

    issues = policy_check_tool(
        spec,
        allow_network=False,
        allow_dangerous=False,
    )

    assert not any(i.get("code") == "network_blocked" for i in issues)


def test_policy_check_tool_blocks_external_domain_when_network_disabled():
    spec = ToolSpec(
        name="external.net.tool",
        description="external domain",
        backend="python",
        execution_capabilities=ToolExecutionCapabilities(
            needs_network=True,
            allowed_domains=["api.openai.com"],
        ),
    )

    issues = policy_check_tool(
        spec,
        allow_network=False,
        allow_dangerous=False,
    )

    assert any(i.get("code") == "network_blocked" for i in issues)


def test_prepare_spec_for_network_policy_marks_local_runtime_loopback():
    spec = ToolSpec(
        name="neo4j.local_runtime.lookup",
        description="local runtime marker",
        backend="python",
        tags=["local_runtime"],
        side_effects=["network"],
    )

    prepared = prepare_spec_for_network_policy(spec, patch_catalog=False)

    caps = prepared.execution_capabilities
    assert caps is not None
    assert caps.needs_network is True
    assert {"localhost", "127.0.0.1", "::1"}.issubset(set(caps.allowed_domains))
