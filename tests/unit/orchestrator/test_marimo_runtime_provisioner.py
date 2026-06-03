import pytest

from brain_researcher.integrations.marimo.config import _default_ai_rules
from brain_researcher.services.orchestrator import (
    marimo_runtime_provisioner as provisioner,
)
from brain_researcher.services.orchestrator.marimo_runtime_provisioner import (
    MARIMO_RUNTIME_START_SCRIPT,
    KubernetesMarimoRuntimeProvisioner,
    MarimoRuntimeSpec,
    _build_marimo_launch_command,
    _ingress_route,
    _json_list_env,
    _marimo_ingress_annotations,
    _marimo_runtime_env_values,
    _public_base_path,
    _runtime_extra_kubernetes_mounts,
    _runtime_health_probe_path,
    _runtime_mcp_token_ttl_seconds,
)


def test_ingress_route_uses_host_and_path_from_public_url() -> None:
    assert _ingress_route("https://${PUBLIC_HOSTNAME}/hub/br-marimo-demo") == (
        "${PUBLIC_HOSTNAME}",
        "/hub/br-marimo-demo",
    )


def test_marimo_ingress_annotations_widen_nginx_ws_timeouts(monkeypatch) -> None:
    monkeypatch.delenv("BR_MARIMO_RUNTIME_INGRESS_WS_TIMEOUT", raising=False)
    monkeypatch.delenv("BR_MARIMO_RUNTIME_INGRESS_ANNOTATIONS_JSON", raising=False)
    annotations = _marimo_ingress_annotations("nginx")
    assert annotations == {
        "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
        "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
    }


def test_marimo_ingress_annotations_unset_class_defaults_to_nginx(monkeypatch) -> None:
    monkeypatch.delenv("BR_MARIMO_RUNTIME_INGRESS_WS_TIMEOUT", raising=False)
    monkeypatch.delenv("BR_MARIMO_RUNTIME_INGRESS_ANNOTATIONS_JSON", raising=False)
    assert "nginx.ingress.kubernetes.io/proxy-read-timeout" in (
        _marimo_ingress_annotations(None)
    )


def test_marimo_ingress_annotations_traefik_emits_no_nginx_annotations(
    monkeypatch,
) -> None:
    monkeypatch.delenv("BR_MARIMO_RUNTIME_INGRESS_ANNOTATIONS_JSON", raising=False)
    # Traefik ignores nginx annotations; we must not synthesize bogus ones, and
    # crucially must never emit X-Frame-Options that would block same-origin
    # iframe embedding of the marimo workspace.
    assert _marimo_ingress_annotations("traefik") == {}


def test_marimo_ingress_annotations_honor_env_override(monkeypatch) -> None:
    monkeypatch.setenv("BR_MARIMO_RUNTIME_INGRESS_WS_TIMEOUT", "7200")
    monkeypatch.setenv(
        "BR_MARIMO_RUNTIME_INGRESS_ANNOTATIONS_JSON",
        '{"traefik.ingress.kubernetes.io/router.middlewares": "core-ws@kubernetescrd"}',
    )
    annotations = _marimo_ingress_annotations("traefik")
    assert annotations == {
        "traefik.ingress.kubernetes.io/router.middlewares": "core-ws@kubernetescrd",
    }
    nginx_annotations = _marimo_ingress_annotations("nginx")
    assert nginx_annotations["nginx.ingress.kubernetes.io/proxy-read-timeout"] == "7200"
    assert (
        nginx_annotations["traefik.ingress.kubernetes.io/router.middlewares"]
        == "core-ws@kubernetescrd"
    )


def test_public_base_path_ignores_scheme_and_host() -> None:
    assert _public_base_path("https://${PUBLIC_HOSTNAME}/hub/br-marimo-demo") == (
        "/hub/br-marimo-demo"
    )


def test_runtime_health_probe_path_uses_public_base_path() -> None:
    assert (
        _runtime_health_probe_path("https://${PUBLIC_HOSTNAME}/hub/br-marimo-demo")
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
        public_url="https://${PUBLIC_HOSTNAME}/hub/br-marimo-demo",
    )

    assert "marimo edit '/home/br_user/work/notebooks/br_quickstart.py'" in command
    # Auth is resolved at shell runtime via ${AUTH_ARGS}: the token-password-file
    # when present, else --no-token in the default (non hosted-cloud) mode.
    assert "--host 0.0.0.0 --port 2718 ${AUTH_ARGS}" in command
    assert "AUTH_ARGS='--no-token'" in command
    assert "--base-url '/hub/br-marimo-demo'" in command
    assert "--proxy '${PUBLIC_HOSTNAME}:443'" in command


def test_marimo_runtime_uses_start_script_entrypoint() -> None:
    assert MARIMO_RUNTIME_START_SCRIPT == "/app/scripts/runtime/start_marimo_singleuser.sh"


def test_kubernetes_runtime_pod_disables_service_account_token_automount(
    monkeypatch,
) -> None:
    if not provisioner.KUBERNETES_AVAILABLE:
        pytest.skip("kubernetes client is not installed")

    monkeypatch.delenv("BR_MARIMO_RUNTIME_EXTRA_VOLUMES_JSON", raising=False)
    monkeypatch.delenv("BR_MARIMO_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON", raising=False)
    monkeypatch.setattr(
        provisioner,
        "_mint_runtime_mcp_bearer_token",
        lambda spec: "runtime-mcp-token",
    )

    class _CoreV1:
        created = None

        def read_namespaced_pod(self, *, name, namespace):
            raise provisioner.ApiException(status=404)

        def create_namespaced_pod(self, *, namespace, body):
            self.created = body

    core_v1 = _CoreV1()
    runtime_provisioner = object.__new__(KubernetesMarimoRuntimeProvisioner)
    runtime_provisioner._core_v1 = core_v1
    runtime_provisioner._image = "docker.io/zjc062/marimo-singleuser:test"
    runtime_provisioner._image_pull_policy = "IfNotPresent"
    runtime_provisioner._service_account = "br-marimo-runtime"
    runtime_provisioner._workspace_pvc_template = None
    runtime_provisioner._template_source = "/app/notebooks/templates/br_quickstart.py"

    spec = MarimoRuntimeSpec(
        owner_user_id="user_demo",
        project_id="proj_demo",
        runtime_session_id="rt_demo",
        runtime_profile_id="standard",
        marimo_port=2718,
        workspace_relative_root="projects/proj_demo",
        absolute_working_directory="/home/br_user/work/projects/proj_demo",
    )

    runtime_provisioner._ensure_pod(
        namespace="brain-researcher-core",
        pod_name="br-marimo-rt-demo",
        service_name="br-marimo-rt-demo",
        spec=spec,
        mount_root="/home/br_user/work",
        notebook_abs="/home/br_user/work/notebooks/br_quickstart.py",
        volume_kind="emptyDir",
        public_url="https://${PUBLIC_HOSTNAME}/hub/br-marimo-rt-demo",
    )

    assert core_v1.created is not None
    assert core_v1.created.spec.service_account_name == "br-marimo-runtime"
    assert core_v1.created.spec.automount_service_account_token is False
    token_volume = next(
        volume
        for volume in core_v1.created.spec.volumes
        if volume.name == "br-marimo-runtime-token"
    )
    token_item = token_volume.projected.sources[0].secret.items[0]
    # Token is owner+group readable (0440), NOT world-readable; the pod's
    # fsGroup lets the non-root marimo user read it via group membership.
    assert token_volume.projected.default_mode == 0o440
    assert token_item.mode == 0o440
    assert core_v1.created.spec.security_context is not None
    assert core_v1.created.spec.security_context.fs_group == 1000


def _fake_marimo_pod(*, image: str, env_names):
    import types

    container = types.SimpleNamespace(
        image=image,
        env=[types.SimpleNamespace(name=n) for n in env_names],
    )
    return types.SimpleNamespace(spec=types.SimpleNamespace(containers=[container]))


def _bare_ensure_pod_provisioner(core_v1):
    p = object.__new__(KubernetesMarimoRuntimeProvisioner)
    p._core_v1 = core_v1
    p._image = "docker.io/zjc062/marimo-singleuser:desired"
    p._image_pull_policy = "IfNotPresent"
    p._service_account = "br-marimo-runtime"
    p._workspace_pvc_template = None
    p._template_source = "/app/notebooks/templates/br_quickstart.py"
    return p


def _ensure_pod_demo_spec() -> MarimoRuntimeSpec:
    return MarimoRuntimeSpec(
        owner_user_id="user_demo",
        project_id="proj_demo",
        runtime_session_id="rt_demo",
        runtime_profile_id="standard",
        marimo_port=2718,
        workspace_relative_root="projects/proj_demo",
        absolute_working_directory="/home/br_user/work/projects/proj_demo",
    )


@pytest.mark.parametrize(
    "image,env_names",
    [
        # old image (predates the skew env-pin) -> stale random skew token
        ("docker.io/zjc062/marimo-singleuser:OLD", ["BR_MARIMO_SKEW_PROTECTION_TOKEN"]),
        # desired image but missing the skew env-pin
        ("docker.io/zjc062/marimo-singleuser:desired", []),
    ],
)
def test_ensure_pod_recreates_drifted_pod(image, env_names) -> None:
    if not provisioner.KUBERNETES_AVAILABLE:
        pytest.skip("kubernetes client is not installed")

    class _CoreV1:
        def __init__(self) -> None:
            self.deleted: list[str] = []
            self.created = None

        def read_namespaced_pod(self, *, name, namespace):
            return _fake_marimo_pod(image=image, env_names=env_names)

        def delete_namespaced_pod(self, *, name, namespace, grace_period_seconds=None):
            self.deleted.append(name)

        def create_namespaced_pod(self, *, namespace, body):
            self.created = body

    core_v1 = _CoreV1()
    p = _bare_ensure_pod_provisioner(core_v1)

    p._ensure_pod(
        namespace="brain-researcher-core",
        pod_name="br-marimo-rt-demo",
        service_name="br-marimo-rt-demo",
        spec=_ensure_pod_demo_spec(),
        mount_root="/home/br_user/work",
        notebook_abs="/home/br_user/work/notebooks/br_quickstart.py",
        volume_kind="emptyDir",
        public_url="https://${PUBLIC_HOSTNAME}/hub/br-marimo-rt-demo",
    )

    # Drifted pod is deleted (next ensure_target poll recreates it fresh) and
    # NOT recreated in-place (avoids a terminating/creating race).
    assert core_v1.deleted == ["br-marimo-rt-demo"]
    assert core_v1.created is None


def test_ensure_pod_reuses_matching_pod() -> None:
    if not provisioner.KUBERNETES_AVAILABLE:
        pytest.skip("kubernetes client is not installed")

    class _CoreV1:
        def __init__(self) -> None:
            self.deleted: list[str] = []
            self.created = None

        def read_namespaced_pod(self, *, name, namespace):
            return _fake_marimo_pod(
                image="docker.io/zjc062/marimo-singleuser:desired",
                env_names=["BR_MARIMO_SKEW_PROTECTION_TOKEN"],
            )

        def delete_namespaced_pod(self, *, name, namespace, grace_period_seconds=None):
            self.deleted.append(name)

        def create_namespaced_pod(self, *, namespace, body):
            self.created = body

    core_v1 = _CoreV1()
    p = _bare_ensure_pod_provisioner(core_v1)

    p._ensure_pod(
        namespace="brain-researcher-core",
        pod_name="br-marimo-rt-demo",
        service_name="br-marimo-rt-demo",
        spec=_ensure_pod_demo_spec(),
        mount_root="/home/br_user/work",
        notebook_abs="/home/br_user/work/notebooks/br_quickstart.py",
        volume_kind="emptyDir",
        public_url="https://${PUBLIC_HOSTNAME}/hub/br-marimo-rt-demo",
    )

    # A pod on the desired image carrying the skew env-pin is reused as-is.
    assert core_v1.deleted == []
    assert core_v1.created is None


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


def test_runtime_env_values_forward_dataset_asset_roots(monkeypatch) -> None:
    monkeypatch.setenv("OPENNEURO_METADATA_ROOT", "/app/data/openneuro_metadata")
    monkeypatch.setenv("NICLIP_DATA_PATH", "/app/data/niclip")
    monkeypatch.setenv("NICLIP_MODEL_DIR", "/app/models/niclip")
    monkeypatch.setenv("NICLIP_FAISS_INDEX_PATH", "/app/data/niclip_faiss")
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

    assert env["OPENNEURO_METADATA_ROOT"] == "/app/data/openneuro_metadata"
    assert env["NICLIP_DATA_PATH"] == "/app/data/niclip"
    assert env["NICLIP_MODEL_DIR"] == "/app/models/niclip"
    assert env["NICLIP_FAISS_INDEX_PATH"] == "/app/data/niclip_faiss"


def test_runtime_env_values_pin_skew_protection_token(monkeypatch) -> None:
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
        skew_protection_token="skew-abc123",
    )

    env = _marimo_runtime_env_values(spec)
    assert env["BR_MARIMO_SKEW_PROTECTION_TOKEN"] == "skew-abc123"

    # Absent when not pinned.
    spec_no_skew = MarimoRuntimeSpec(
        owner_user_id="user_demo",
        project_id="proj_demo",
        runtime_session_id="rt_demo",
        runtime_profile_id="standard",
        marimo_port=2718,
        workspace_relative_root="projects/proj_demo",
        absolute_working_directory="/home/br_user/work/projects/proj_demo",
    )
    assert "BR_MARIMO_SKEW_PROTECTION_TOKEN" not in _marimo_runtime_env_values(
        spec_no_skew
    )


def test_runtime_env_values_include_managed_ai_settings(monkeypatch) -> None:
    monkeypatch.setenv("BR_MCP_HTTP_URL", "http://brain-researcher-mcp:7000/mcp")
    monkeypatch.setenv(
        "BR_MARIMO_RUNTIME_AI_BASE_URL",
        "https://llm.${PUBLIC_HOSTNAME}/v1",
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
    assert env["BR_MARIMO_AI_BASE_URL"] == "https://llm.${PUBLIC_HOSTNAME}/v1"
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


def _bare_k8s_provisioner(core_v1, *, pvc_template):
    p = object.__new__(KubernetesMarimoRuntimeProvisioner)
    p._core_v1 = core_v1
    p._image = "docker.io/zjc062/marimo-singleuser:test"
    p._image_pull_policy = "IfNotPresent"
    p._service_account = None
    p._workspace_pvc_template = pvc_template
    p._workspace_storage_class = "local-path"
    p._workspace_storage_size = "5Gi"
    p._template_source = "/app/notebooks/templates/br_quickstart.py"
    return p


def _demo_spec():
    return MarimoRuntimeSpec(
        owner_user_id="user_demo",
        project_id="proj_demo",
        runtime_session_id="rt_demo",
        runtime_profile_id="standard",
        marimo_port=2718,
        workspace_relative_root="projects/proj_demo",
        absolute_working_directory="/home/br_user/work/projects/proj_demo",
    )


def test_kubernetes_runtime_creates_workspace_pvc_when_template_set(monkeypatch) -> None:
    if not provisioner.KUBERNETES_AVAILABLE:
        pytest.skip("kubernetes client is not installed")
    monkeypatch.delenv("BR_MARIMO_RUNTIME_EXTRA_VOLUMES_JSON", raising=False)
    monkeypatch.delenv("BR_MARIMO_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON", raising=False)
    monkeypatch.setattr(
        provisioner, "_mint_runtime_mcp_bearer_token", lambda spec: "tok"
    )

    class _CoreV1:
        def __init__(self):
            self.created_pod = None
            self.created_pvcs = []

        def read_namespaced_pod(self, *, name, namespace):
            raise provisioner.ApiException(status=404)

        def read_namespaced_persistent_volume_claim(self, *, name, namespace):
            raise provisioner.ApiException(status=404)

        def create_namespaced_persistent_volume_claim(self, *, namespace, body):
            self.created_pvcs.append(body)

        def create_namespaced_pod(self, *, namespace, body):
            self.created_pod = body

    core = _CoreV1()
    p = _bare_k8s_provisioner(core, pvc_template="br-marimo-ws-{project_id}")
    spec = _demo_spec()
    expected_claim = provisioner._render_template(
        "br-marimo-ws-{project_id}", provisioner._template_context(spec)
    )

    p._ensure_pod(
        namespace="brain-researcher-core",
        pod_name="br-marimo-rt-demo",
        service_name="br-marimo-rt-demo",
        spec=spec,
        mount_root="/home/br_user/work",
        notebook_abs="/home/br_user/work/notebooks/br_quickstart.py",
        volume_kind="persistentVolumeClaim",
        public_url=None,
    )

    assert len(core.created_pvcs) == 1
    pvc = core.created_pvcs[0]
    assert pvc.metadata.name == expected_claim
    assert pvc.spec.access_modes == ["ReadWriteOnce"]
    assert pvc.spec.resources.requests["storage"] == "5Gi"
    assert pvc.spec.storage_class_name == "local-path"
    ws_vol = next(
        v for v in core.created_pod.spec.volumes if v.name == "workspace"
    )
    assert ws_vol.persistent_volume_claim is not None
    assert ws_vol.persistent_volume_claim.claim_name == expected_claim
    assert ws_vol.empty_dir is None


def test_kubernetes_runtime_uses_emptydir_when_no_pvc_template(monkeypatch) -> None:
    if not provisioner.KUBERNETES_AVAILABLE:
        pytest.skip("kubernetes client is not installed")
    monkeypatch.delenv("BR_MARIMO_RUNTIME_EXTRA_VOLUMES_JSON", raising=False)
    monkeypatch.delenv("BR_MARIMO_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON", raising=False)
    monkeypatch.setattr(
        provisioner, "_mint_runtime_mcp_bearer_token", lambda spec: "tok"
    )

    class _CoreV1:
        def __init__(self):
            self.created_pod = None
            self.pvc_calls = 0

        def read_namespaced_pod(self, *, name, namespace):
            raise provisioner.ApiException(status=404)

        def create_namespaced_persistent_volume_claim(self, *, namespace, body):
            self.pvc_calls += 1

        def create_namespaced_pod(self, *, namespace, body):
            self.created_pod = body

    core = _CoreV1()
    p = _bare_k8s_provisioner(core, pvc_template=None)

    p._ensure_pod(
        namespace="brain-researcher-core",
        pod_name="br-marimo-rt-demo",
        service_name="br-marimo-rt-demo",
        spec=_demo_spec(),
        mount_root="/home/br_user/work",
        notebook_abs="/home/br_user/work/notebooks/br_quickstart.py",
        volume_kind="emptyDir",
        public_url=None,
    )

    assert core.pvc_calls == 0
    ws_vol = next(
        v for v in core.created_pod.spec.volumes if v.name == "workspace"
    )
    assert ws_vol.empty_dir is not None
    assert ws_vol.persistent_volume_claim is None
