from brain_researcher.integrations.marimo.config import _default_ai_rules
from brain_researcher.services.orchestrator import (
    marimo_runtime_provisioner as provisioner,
)
from brain_researcher.services.orchestrator.marimo_runtime_provisioner import (
    MARIMO_RUNTIME_START_SCRIPT,
    MarimoRuntimeSpec,
    _build_marimo_launch_command,
    _ingress_route,
    _json_list_env,
    _marimo_runtime_env_values,
    _public_base_path,
    _runtime_extra_kubernetes_mounts,
    _runtime_health_probe_path,
    _runtime_mcp_token_ttl_seconds,
)


def test_ingress_route_uses_host_and_path_from_public_url() -> None:
    assert _ingress_route("https://brain-researcher.com/hub/br-marimo-demo") == (
        "brain-researcher.com",
        "/hub/br-marimo-demo",
    )


def test_public_base_path_ignores_scheme_and_host() -> None:
    assert _public_base_path("https://brain-researcher.com/hub/br-marimo-demo") == (
        "/hub/br-marimo-demo"
    )


def test_runtime_health_probe_path_uses_public_base_path() -> None:
    assert (
        _runtime_health_probe_path("https://brain-researcher.com/hub/br-marimo-demo")
        == "/hub/br-marimo-demo/health"
    )
    assert _runtime_health_probe_path(None) == "/health"


def test_runtime_mcp_token_ttl_defaults_to_seven_days(monkeypatch) -> None:
    monkeypatch.delenv("BR_MARIMO_RUNTIME_MCP_TOKEN_TTL_SECONDS", raising=False)

    assert _runtime_mcp_token_ttl_seconds() == 7 * 24 * 60 * 60


def test_marimo_launch_command_appends_base_url_when_public_url_present() -> None:
    command = _build_marimo_launch_command(
        notebook_abs="/home/br_user/work/notebooks/br_quickstart.py",
        template_source="/app/notebooks/templates/br_quickstart.py",
        marimo_port=2718,
        public_url="https://brain-researcher.com/hub/br-marimo-demo",
    )

    assert "marimo edit '/home/br_user/work/notebooks/br_quickstart.py'" in command
    assert "--host 0.0.0.0 --port 2718 --no-token" in command
    assert "--base-url '/hub/br-marimo-demo'" in command
    assert "--proxy 'brain-researcher.com:443'" in command


def test_marimo_runtime_uses_start_script_entrypoint() -> None:
    assert MARIMO_RUNTIME_START_SCRIPT == "/app/scripts/runtime/start_marimo_singleuser.sh"


def test_runtime_env_values_allow_forwarded_proxy_headers(monkeypatch) -> None:
    monkeypatch.setenv("BR_MARIMO_RUNTIME_FORWARDED_ALLOW_IPS", "*")
    monkeypatch.setenv("BR_MCP_HTTP_URL", "http://brain-researcher-mcp:7000/mcp")
    monkeypatch.setattr(
        provisioner,
        "_mint_runtime_mcp_bearer_token",
        lambda spec: "runtime-mcp-token",
    )
    spec = MarimoRuntimeSpec(
        owner_user_id="user_demo",
        project_id="proj_demo",
        runtime_session_id="rt_demo",
        runtime_profile_id="standard",
        marimo_port=2718,
        workspace_relative_root="projects/proj_demo",
        absolute_working_directory="/home/br_user/work/projects/proj_demo",
    )

    env = _marimo_runtime_env_values(spec)

    assert env["FORWARDED_ALLOW_IPS"] == "*"
    assert env["BR_MCP_HTTP_URL"] == "http://brain-researcher-mcp:7000/mcp"
    assert env["BR_MCP_BEARER_TOKEN"] == "runtime-mcp-token"
    assert env["BR_MARIMO_RUNTIME_SESSION_ID"] == "rt_demo"


def test_runtime_env_values_include_managed_ai_settings(monkeypatch) -> None:
    monkeypatch.setenv("BR_MCP_HTTP_URL", "http://brain-researcher-mcp:7000/mcp")
    monkeypatch.setenv(
        "BR_MARIMO_RUNTIME_AI_BASE_URL",
        "https://llm.brain-researcher.com/v1",
    )
    monkeypatch.setenv("BR_MARIMO_RUNTIME_AI_API_KEY", "runtime-ai-token")
    monkeypatch.setenv("BR_MARIMO_RUNTIME_AI_PROVIDER_NAME", "brain-researcher")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
    monkeypatch.setenv("DEFAULT_CODING_MODEL", "gemini-3-flash-preview")
    monkeypatch.setenv("BR_MARIMO_RUNTIME_AI_INLINE_TOOLTIP", "true")
    monkeypatch.setattr(
        provisioner,
        "_mint_runtime_mcp_bearer_token",
        lambda spec: "runtime-mcp-token",
    )
    spec = MarimoRuntimeSpec(
        owner_user_id="user_demo",
        project_id="proj_demo",
        runtime_session_id="rt_demo",
        runtime_profile_id="standard",
        marimo_port=2718,
        workspace_relative_root="projects/proj_demo",
        absolute_working_directory="/home/br_user/work/projects/proj_demo",
    )

    env = _marimo_runtime_env_values(spec)

    assert env["BR_MARIMO_AI_PROVIDER_NAME"] == "brain-researcher"
    assert env["BR_MARIMO_AI_BASE_URL"] == "https://llm.brain-researcher.com/v1"
    assert env["BR_MARIMO_AI_API_KEY"] == "runtime-ai-token"
    assert env["BR_MARIMO_AI_MODE"] == "agent"
    assert env["BR_MARIMO_AI_CHAT_MODEL"] == "gemini-3-flash-preview"
    assert env["BR_MARIMO_AI_EDIT_MODEL"] == "gemini-3-flash-preview"
    assert env["BR_MARIMO_AI_AUTOCOMPLETE_MODEL"] == "gemini-3-flash-preview"
    assert env["BR_MARIMO_AI_RULES"] == _default_ai_rules()
    assert env["BR_MARIMO_AI_INLINE_TOOLTIP"] == "true"


def test_runtime_env_values_support_builtin_google_provider(monkeypatch) -> None:
    monkeypatch.setenv("BR_MCP_HTTP_URL", "http://brain-researcher-mcp:7000/mcp")
    monkeypatch.setenv("BR_MARIMO_RUNTIME_AI_PROVIDER_NAME", "google")
    monkeypatch.delenv("BR_MARIMO_RUNTIME_AI_BASE_URL", raising=False)
    monkeypatch.setenv("BR_MARIMO_RUNTIME_AI_API_KEY", "runtime-ai-token")
    monkeypatch.setenv("DEFAULT_LLM_MODEL", "gemini-3-flash-preview")
    monkeypatch.setenv("DEFAULT_CODING_MODEL", "gemini-3-flash-preview")
    monkeypatch.setattr(
        provisioner,
        "_mint_runtime_mcp_bearer_token",
        lambda spec: "runtime-mcp-token",
    )
    spec = MarimoRuntimeSpec(
        owner_user_id="user_demo",
        project_id="proj_demo",
        runtime_session_id="rt_demo",
        runtime_profile_id="standard",
        marimo_port=2718,
        workspace_relative_root="projects/proj_demo",
        absolute_working_directory="/home/br_user/work/projects/proj_demo",
    )

    env = _marimo_runtime_env_values(spec)

    assert env["BR_MARIMO_AI_PROVIDER_NAME"] == "google"
    assert "BR_MARIMO_AI_BASE_URL" not in env
    assert env["BR_MARIMO_AI_API_KEY"] == "runtime-ai-token"
    assert env["BR_MARIMO_AI_CHAT_MODEL"] == "gemini-3-flash-preview"


def test_runtime_env_values_forward_agent_style_atlas_envs(monkeypatch) -> None:
    monkeypatch.setenv("BR_MCP_HTTP_URL", "http://brain-researcher-mcp:7000/mcp")
    monkeypatch.setenv("TEMPLATEFLOW_HOME", "/app/data/atlases/templateflow")
    monkeypatch.setenv("BR_ATLAS_OUTPUT_ROOT", "/app/data/atlases")
    monkeypatch.setenv(
        "BR_ATLAS_SEARCH_ROOTS",
        "/app/data/atlases/templateflow,/app/data/atlases,/app/data/openneuro",
    )
    monkeypatch.setattr(
        provisioner,
        "_mint_runtime_mcp_bearer_token",
        lambda spec: "runtime-mcp-token",
    )
    spec = MarimoRuntimeSpec(
        owner_user_id="user_demo",
        project_id="proj_demo",
        runtime_session_id="rt_demo",
        runtime_profile_id="standard",
        marimo_port=2718,
        workspace_relative_root="projects/proj_demo",
        absolute_working_directory="/home/br_user/work/projects/proj_demo",
    )

    env = _marimo_runtime_env_values(spec)

    assert env["TEMPLATEFLOW_HOME"] == "/app/data/atlases/templateflow"
    assert env["BR_ATLAS_OUTPUT_ROOT"] == "/app/data/atlases"
    assert (
        env["BR_ATLAS_SEARCH_ROOTS"]
        == "/app/data/atlases/templateflow,/app/data/atlases,/app/data/openneuro"
    )


def test_runtime_env_values_include_taskbeacon_seed_when_requested(monkeypatch) -> None:
    monkeypatch.setenv("BR_MCP_HTTP_URL", "http://brain-researcher-mcp:7000/mcp")
    monkeypatch.setattr(
        provisioner,
        "_mint_runtime_mcp_bearer_token",
        lambda spec: "runtime-mcp-token",
    )
    spec = MarimoRuntimeSpec(
        owner_user_id="user_demo",
        project_id="proj_demo",
        runtime_session_id="rt_demo",
        runtime_profile_id="standard",
        marimo_port=2718,
        workspace_relative_root="projects/proj_demo",
        absolute_working_directory="/home/br_user/work/projects/proj_demo",
        taskbeacon_repo="TaskBeacon/T000015-ant",
        taskbeacon_ref="main",
        taskbeacon_target_path="projects/proj_demo/taskbeacon/T000015-ant",
    )

    env = _marimo_runtime_env_values(spec)

    assert env["BR_MARIMO_RUNTIME_TASKBEACON_REPO"] == "TaskBeacon/T000015-ant"
    assert env["BR_MARIMO_RUNTIME_TASKBEACON_REF"] == "main"
    assert (
        env["BR_MARIMO_RUNTIME_TASKBEACON_TARGET_PATH"]
        == "projects/proj_demo/taskbeacon/T000015-ant"
    )


def test_json_list_env_ignores_invalid_payloads(monkeypatch) -> None:
    monkeypatch.setenv("BR_MARIMO_RUNTIME_EXTRA_VOLUMES_JSON", "{\"bad\":true}")

    assert _json_list_env("BR_MARIMO_RUNTIME_EXTRA_VOLUMES_JSON") == []


def test_runtime_extra_kubernetes_mounts_parse_hostpath_and_secret(monkeypatch) -> None:
    monkeypatch.setenv(
        "BR_MARIMO_RUNTIME_EXTRA_VOLUMES_JSON",
        (
            '[{"name":"cvmfs-neurodesk","hostPath":{"path":"/cvmfs/neurodesk.ardc.edu.au","type":"Directory"}},'
            '{"name":"freesurfer-license","secret":{"secretName":"brain-researcher-freesurfer-license","optional":true,'
            '"items":[{"key":"license.txt","path":"license.txt"}]}}]'
        ),
    )
    monkeypatch.setenv(
        "BR_MARIMO_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON",
        (
            '[{"name":"cvmfs-neurodesk","mountPath":"/cvmfs/neurodesk.ardc.edu.au","readOnly":true},'
            '{"name":"freesurfer-license","mountPath":"/app/data/licenses/freesurfer","readOnly":true}]'
        ),
    )

    volumes, mounts = _runtime_extra_kubernetes_mounts()

    assert [volume.name for volume in volumes] == [
        "cvmfs-neurodesk",
        "freesurfer-license",
    ]
    assert volumes[0].host_path.path == "/cvmfs/neurodesk.ardc.edu.au"
    assert volumes[1].secret.secret_name == "brain-researcher-freesurfer-license"
    assert [mount.name for mount in mounts] == [
        "cvmfs-neurodesk",
        "freesurfer-license",
    ]
    assert mounts[0].mount_path == "/cvmfs/neurodesk.ardc.edu.au"
    assert mounts[0].read_only is True
