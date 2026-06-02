"""Marimo runtime provisioners for hosted /hub sessions.

This module isolates how a hosted Marimo runtime target is created and
reconciled. The default provisioner is a lightweight no-op target builder so
local development and unit tests keep working. When configured with
``BR_MARIMO_RUNTIME_PROVISIONER=kubernetes``, the provisioner will create a
per-session Pod + Service pair and return the connection target metadata that
``/hub`` can use for reconnect and UI handoff.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .auth_utils import create_access_token

try:
    import kubernetes
    from kubernetes.client.rest import ApiException

    KUBERNETES_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    kubernetes = None
    ApiException = Exception
    KUBERNETES_AVAILABLE = False

logger = logging.getLogger(__name__)

MARIMO_RUNTIME_START_SCRIPT = "/app/scripts/runtime/start_marimo_singleuser.sh"
MARIMO_RUNTIME_TOKEN_PATH = "/run/secrets/br_marimo_runtime_token"
MARIMO_RUNTIME_TOKEN_SECRET_VOLUME = "br-marimo-runtime-token"
MARIMO_RUNTIME_TOKEN_SECRET_KEY = "token"
# The runtime image runs marimo as a non-root user (NB_UID/NB_GID=1000). The
# auth token is mounted 0440 (owner+group read, NOT world-readable); fsGroup
# makes the projected token group-owned by this GID so the non-root process can
# read it via group membership without exposing it to other pod users.
MARIMO_RUNTIME_DEFAULT_FS_GROUP = 1000
_DEFAULT_RUNTIME_MCP_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60
_DEFAULT_RUNTIME_AI_MODE = "agent"
_RUNTIME_AI_BUILTIN_PROVIDERS = {
    "openai",
    "open_ai",
    "anthropic",
    "google",
    "bedrock",
    "azure",
    "ollama",
    "github",
    "openrouter",
    "wandb",
}


class MarimoRuntimeTarget(BaseModel):
    provisioner: str
    connection_mode: str = Field(default="pending", max_length=50)
    ready: bool = False
    public_url: str | None = Field(default=None, max_length=2000)
    websocket_url: str | None = Field(default=None, max_length=2000)
    internal_url: str | None = Field(default=None, max_length=2000)
    namespace: str | None = Field(default=None, max_length=200)
    pod_name: str | None = Field(default=None, max_length=200)
    service_name: str | None = Field(default=None, max_length=200)
    workspace_mount_path: str | None = Field(default=None, max_length=2000)
    workspace_volume_kind: str | None = Field(default=None, max_length=100)
    status_reason: str | None = Field(default=None, max_length=500)


@dataclass(slots=True)
class MarimoRuntimeSpec:
    owner_user_id: str
    project_id: str
    runtime_session_id: str
    runtime_profile_id: str
    marimo_port: int
    workspace_relative_root: str
    absolute_working_directory: str
    taskbeacon_repo: str | None = None
    taskbeacon_ref: str | None = None
    taskbeacon_target_path: str | None = None
    skew_protection_token: str | None = None


def generate_runtime_token() -> str:
    """Mint a per-pod runtime token used to authenticate against marimo."""
    return secrets.token_urlsafe(32)


class MarimoRuntimeProvisioner:
    name = "base"

    def ensure_target(
        self, spec: MarimoRuntimeSpec
    ) -> MarimoRuntimeTarget:  # pragma: no cover - interface
        raise NotImplementedError

    def destroy_target(
        self, target: MarimoRuntimeTarget
    ) -> None:  # pragma: no cover - interface
        return None

    def ensure_runtime_token(
        self,
        spec: MarimoRuntimeSpec,
        target: MarimoRuntimeTarget,
        *,
        existing_token: str | None = None,
    ) -> str | None:
        """Return a runtime token for the marimo pod.

        Base behavior: reuse the existing token if present, otherwise mint a
        fresh one. Subclasses (k8s) override to also push the token into a
        projected Secret.
        """
        if existing_token:
            return existing_token
        return generate_runtime_token()

    def destroy_runtime_token(
        self, target: MarimoRuntimeTarget
    ) -> None:  # pragma: no cover - default no-op
        return None


class NoopMarimoRuntimeProvisioner(MarimoRuntimeProvisioner):
    name = "noop"

    def ensure_target(self, spec: MarimoRuntimeSpec) -> MarimoRuntimeTarget:
        context = _template_context(spec)
        service_name = _render_template(
            os.getenv("BR_MARIMO_RUNTIME_SERVICE_NAME_TEMPLATE"),
            context,
        ) or _default_service_name(spec.runtime_session_id)
        pod_name = _render_template(
            os.getenv("BR_MARIMO_RUNTIME_POD_NAME_TEMPLATE"),
            context,
        ) or _default_pod_name(spec.runtime_session_id)
        public_url = _render_template(
            os.getenv("BR_MARIMO_RUNTIME_PUBLIC_URL_TEMPLATE"),
            {**context, "service_name": service_name, "pod_name": pod_name},
        )
        internal_url = _render_template(
            os.getenv("BR_MARIMO_RUNTIME_INTERNAL_URL_TEMPLATE")
            or "http://{service_name}:{marimo_port}",
            {**context, "service_name": service_name, "pod_name": pod_name},
        )
        connection_mode = os.getenv("BR_MARIMO_RUNTIME_CONNECTION_MODE") or (
            "iframe" if public_url else "pending"
        )
        return MarimoRuntimeTarget(
            provisioner=self.name,
            connection_mode=connection_mode,
            ready=True,
            public_url=public_url,
            websocket_url=_to_websocket_url(public_url),
            internal_url=internal_url,
            namespace=_normalize_optional_text(
                os.getenv("BR_MARIMO_RUNTIME_NAMESPACE")
            ),
            pod_name=pod_name,
            service_name=service_name,
            workspace_mount_path=_workspace_home(spec),
            workspace_volume_kind="unmanaged",
            status_reason=(
                "noop_provisioner_public_url_unset"
                if not public_url
                else "noop_provisioner"
            ),
        )


class KubernetesMarimoRuntimeProvisioner(MarimoRuntimeProvisioner):
    name = "kubernetes"

    def __init__(self) -> None:
        if not KUBERNETES_AVAILABLE:
            raise RuntimeError("kubernetes library is not installed")
        try:
            try:
                kubernetes.config.load_incluster_config()
            except kubernetes.config.ConfigException:
                kubernetes.config.load_kube_config()
            self._core_v1 = kubernetes.client.CoreV1Api()
            self._networking_v1 = kubernetes.client.NetworkingV1Api()
        except Exception as exc:  # pragma: no cover - environment specific
            raise RuntimeError(
                f"failed to initialize kubernetes client: {exc}"
            ) from exc

        self._namespace = os.getenv("BR_MARIMO_RUNTIME_NAMESPACE", "default")
        self._image = _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_IMAGE"))
        if not self._image:
            raise RuntimeError(
                "BR_MARIMO_RUNTIME_IMAGE is required for kubernetes Marimo provisioner"
            )
        self._image_pull_policy = os.getenv(
            "BR_MARIMO_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent"
        )
        self._service_account = _normalize_optional_text(
            os.getenv("BR_MARIMO_RUNTIME_SERVICE_ACCOUNT")
        )
        self._workspace_home = os.getenv(
            "BR_MARIMO_RUNTIME_WORKSPACE_HOME", "/home/br_user/work"
        )
        self._template_source = os.getenv(
            "BR_MARIMO_RUNTIME_TEMPLATE_SOURCE",
            "/app/notebooks/templates/br_quickstart.py",
        )
        self._notebook_relpath = os.getenv(
            "BR_MARIMO_RUNTIME_NOTEBOOK_PATH",
            "notebooks/br_quickstart.py",
        ).lstrip("/")
        self._workspace_pvc_template = _normalize_optional_text(
            os.getenv("BR_MARIMO_RUNTIME_WORKSPACE_PVC_TEMPLATE")
        )
        # When a PVC template is configured the workspace persists across pod
        # recreation; storage class defaults to the cluster default (local-path on
        # k3s) and size defaults to 2Gi. Unset template => emptyDir (no change).
        self._workspace_storage_class = _normalize_optional_text(
            os.getenv("BR_MARIMO_RUNTIME_WORKSPACE_STORAGE_CLASS")
        )
        self._workspace_storage_size = (
            _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_WORKSPACE_SIZE"))
            or "2Gi"
        )
        self._ingress_class_name = _normalize_optional_text(
            os.getenv("BR_MARIMO_RUNTIME_INGRESS_CLASS")
        )
        self._ingress_tls_secret = _normalize_optional_text(
            os.getenv("BR_MARIMO_RUNTIME_INGRESS_TLS_SECRET")
        )

    def ensure_target(self, spec: MarimoRuntimeSpec) -> MarimoRuntimeTarget:
        context = _template_context(spec)
        pod_name = _render_template(
            os.getenv("BR_MARIMO_RUNTIME_POD_NAME_TEMPLATE"),
            context,
        ) or _default_pod_name(spec.runtime_session_id)
        service_name = _render_template(
            os.getenv("BR_MARIMO_RUNTIME_SERVICE_NAME_TEMPLATE"),
            context,
        ) or _default_service_name(spec.runtime_session_id)
        namespace = (
            _render_template(
                os.getenv("BR_MARIMO_RUNTIME_NAMESPACE_TEMPLATE"),
                {**context, "namespace": self._namespace},
            )
            or self._namespace
        )
        mount_root = _workspace_home(spec)
        notebook_abs = f"{mount_root.rstrip('/')}/{self._notebook_relpath}"
        volume_kind = (
            "persistentVolumeClaim" if self._workspace_pvc_template else "emptyDir"
        )
        public_url = _render_template(
            os.getenv("BR_MARIMO_RUNTIME_PUBLIC_URL_TEMPLATE"),
            {
                **context,
                "namespace": namespace,
                "pod_name": pod_name,
                "service_name": service_name,
            },
        )

        self._ensure_service(
            namespace=namespace, service_name=service_name, pod_name=pod_name, spec=spec
        )
        self._ensure_ingress(
            namespace=namespace,
            service_name=service_name,
            spec=spec,
            public_url=public_url,
        )
        self._ensure_pod(
            namespace=namespace,
            pod_name=pod_name,
            service_name=service_name,
            spec=spec,
            mount_root=mount_root,
            notebook_abs=notebook_abs,
            volume_kind=volume_kind,
            public_url=public_url,
        )
        pod = self._core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        ready = _pod_is_ready(pod)
        internal_url = _render_template(
            os.getenv("BR_MARIMO_RUNTIME_INTERNAL_URL_TEMPLATE")
            or "http://{service_name}:{marimo_port}",
            {
                **context,
                "namespace": namespace,
                "pod_name": pod_name,
                "service_name": service_name,
            },
        )
        return MarimoRuntimeTarget(
            provisioner=self.name,
            connection_mode=("iframe" if public_url else "pending"),
            ready=ready,
            public_url=public_url,
            websocket_url=_to_websocket_url(public_url),
            internal_url=internal_url,
            namespace=namespace,
            pod_name=pod_name,
            service_name=service_name,
            workspace_mount_path=mount_root,
            workspace_volume_kind=volume_kind,
            status_reason=(
                getattr(getattr(pod, "status", None), "phase", None) or "unknown"
            ).lower(),
        )

    def destroy_target(self, target: MarimoRuntimeTarget) -> None:
        namespace = _normalize_optional_text(target.namespace) or self._namespace
        service_name = _normalize_optional_text(target.service_name)
        if service_name:
            _delete_kubernetes_resource(
                self._networking_v1.delete_namespaced_ingress,
                name=service_name,
                namespace=namespace,
            )
            _delete_kubernetes_resource(
                self._core_v1.delete_namespaced_service,
                name=service_name,
                namespace=namespace,
            )
        pod_name = _normalize_optional_text(target.pod_name)
        if pod_name:
            _delete_kubernetes_resource(
                self._core_v1.delete_namespaced_pod,
                name=pod_name,
                namespace=namespace,
            )
        self.destroy_runtime_token(target)

    def ensure_runtime_token(
        self,
        spec: MarimoRuntimeSpec,
        target: MarimoRuntimeTarget,
        *,
        existing_token: str | None = None,
    ) -> str | None:
        namespace = _normalize_optional_text(target.namespace) or self._namespace
        secret_name = _runtime_token_secret_name(spec.runtime_session_id)
        token = existing_token or generate_runtime_token()
        body = kubernetes.client.V1Secret(
            metadata=kubernetes.client.V1ObjectMeta(
                name=secret_name,
                namespace=namespace,
                labels=_runtime_labels(spec, pod_name=secret_name),
            ),
            type="Opaque",
            string_data={MARIMO_RUNTIME_TOKEN_SECRET_KEY: token},
        )
        try:
            self._core_v1.create_namespaced_secret(namespace=namespace, body=body)
        except ApiException as exc:
            if getattr(exc, "status", None) != 409:
                raise
            if not existing_token:
                logger.info(
                    "Marimo runtime token secret %s/%s already exists; reusing stored token",
                    namespace,
                    secret_name,
                )
        return token

    def destroy_runtime_token(self, target: MarimoRuntimeTarget) -> None:
        namespace = _normalize_optional_text(target.namespace) or self._namespace
        runtime_session_id: str | None = None
        pod_name = _normalize_optional_text(target.pod_name)
        service_name = _normalize_optional_text(target.service_name)
        for candidate in (pod_name, service_name):
            if candidate and candidate.startswith("br-marimo-"):
                runtime_session_id = candidate[len("br-marimo-") :]
                break
        if not runtime_session_id:
            return
        secret_name = _runtime_token_secret_name(runtime_session_id)
        _delete_kubernetes_resource(
            self._core_v1.delete_namespaced_secret,
            name=secret_name,
            namespace=namespace,
        )

    def _ensure_service(
        self,
        *,
        namespace: str,
        service_name: str,
        pod_name: str,
        spec: MarimoRuntimeSpec,
    ) -> None:
        try:
            self._core_v1.read_namespaced_service(
                name=service_name, namespace=namespace
            )
            return
        except ApiException as exc:
            if getattr(exc, "status", None) != 404:
                raise

        body = kubernetes.client.V1Service(
            metadata=kubernetes.client.V1ObjectMeta(
                name=service_name,
                namespace=namespace,
                labels=_runtime_labels(spec, pod_name=pod_name),
            ),
            spec=kubernetes.client.V1ServiceSpec(
                selector=_runtime_selector_labels(spec, pod_name=pod_name),
                ports=[
                    kubernetes.client.V1ServicePort(
                        name="http",
                        port=spec.marimo_port,
                        target_port=spec.marimo_port,
                    )
                ],
            ),
        )
        self._core_v1.create_namespaced_service(namespace=namespace, body=body)

    def _pod_matches_desired(self, pod) -> tuple[bool, str]:
        """Return ``(matches, drift_reason)`` for a reused Marimo runtime pod.

        A reused pod must run the currently desired image AND carry the
        env-pinned skew-protection token (``BR_MARIMO_SKEW_PROTECTION_TOKEN``).
        A pod created before the skew env-pin (older image, or missing the env
        var) runs marimo's stock ``SkewProtectionToken.random()`` so its live
        skew token never matches the orchestrator's persisted value; every
        server-to-server transaction (e.g. ``Runs -> Attach in notebook``) then
        fails marimo's skew middleware with 401 -> ``token_rejected``, and the
        stale pod is reused indefinitely. Such pods are recreated, not reused.
        """
        try:
            container = pod.spec.containers[0]
        except (AttributeError, IndexError, TypeError):
            return False, "no_container"
        if self._image and container.image != self._image:
            return False, f"image_drift({container.image} != {self._image})"
        env_names = {getattr(e, "name", None) for e in (container.env or [])}
        if "BR_MARIMO_SKEW_PROTECTION_TOKEN" not in env_names:
            return False, "missing_skew_env_pin"
        return True, ""

    def _ensure_pod(
        self,
        *,
        namespace: str,
        pod_name: str,
        service_name: str,
        spec: MarimoRuntimeSpec,
        mount_root: str,
        notebook_abs: str,
        volume_kind: str,
        public_url: str | None,
    ) -> None:
        try:
            existing = self._core_v1.read_namespaced_pod(
                name=pod_name, namespace=namespace
            )
            matches, drift_reason = self._pod_matches_desired(existing)
            if matches:
                return
            # Drifted pod: old image / missing skew env-pin -> attach calls fail
            # with token_rejected and never self-heal. Delete it (force, since the
            # notebook .py lives on the workspace volume and survives); the next
            # ensure_target poll sees 404 and recreates it on the current image.
            logger.warning(
                "Recreating drifted Marimo runtime pod %s/%s: %s",
                namespace,
                pod_name,
                drift_reason,
            )
            try:
                self._core_v1.delete_namespaced_pod(
                    name=pod_name,
                    namespace=namespace,
                    grace_period_seconds=0,
                )
            except ApiException as del_exc:
                if getattr(del_exc, "status", None) != 404:
                    raise
            return
        except ApiException as exc:
            if getattr(exc, "status", None) != 404:
                raise

        if self._workspace_pvc_template:
            self._ensure_workspace_pvc(
                namespace=namespace,
                claim_name=self._workspace_claim_name(spec),
            )
        volume, mount = self._workspace_volume(spec=spec, mount_root=mount_root)
        token_volume, token_mount = _runtime_token_volume_and_mount(
            spec.runtime_session_id
        )
        extra_volumes, extra_mounts = _runtime_extra_kubernetes_mounts()
        env = [
            kubernetes.client.V1EnvVar(name=name, value=value)
            for name, value in _marimo_runtime_env_values(spec).items()
        ]
        probe_path = _runtime_health_probe_path(public_url)
        command = _build_marimo_launch_command(
            notebook_abs=notebook_abs,
            template_source=self._template_source,
            marimo_port=spec.marimo_port,
            public_url=public_url,
        )
        container = kubernetes.client.V1Container(
            name="marimo",
            image=self._image,
            image_pull_policy=self._image_pull_policy,
            command=[MARIMO_RUNTIME_START_SCRIPT],
            args=["bash", "-lc", command],
            env=env,
            ports=[kubernetes.client.V1ContainerPort(container_port=spec.marimo_port)],
            readiness_probe=kubernetes.client.V1Probe(
                http_get=kubernetes.client.V1HTTPGetAction(
                    path=probe_path,
                    port=spec.marimo_port,
                ),
                period_seconds=2,
                timeout_seconds=1,
                failure_threshold=30,
            ),
            startup_probe=kubernetes.client.V1Probe(
                http_get=kubernetes.client.V1HTTPGetAction(
                    path=probe_path,
                    port=spec.marimo_port,
                ),
                period_seconds=2,
                timeout_seconds=1,
                failure_threshold=60,
            ),
            volume_mounts=[mount, token_mount, *extra_mounts],
        )
        pod_spec = kubernetes.client.V1PodSpec(
            restart_policy="Always",
            automount_service_account_token=False,
            security_context=kubernetes.client.V1PodSecurityContext(
                fs_group=_runtime_fs_group(),
            ),
            containers=[container],
            volumes=[volume, token_volume, *extra_volumes],
        )
        if self._service_account:
            pod_spec.service_account_name = self._service_account

        body = kubernetes.client.V1Pod(
            metadata=kubernetes.client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels=_runtime_labels(spec, pod_name=pod_name),
            ),
            spec=pod_spec,
        )
        self._core_v1.create_namespaced_pod(namespace=namespace, body=body)
        logger.info(
            "Provisioned Marimo runtime pod %s/%s service=%s volume_kind=%s",
            namespace,
            pod_name,
            service_name,
            volume_kind,
        )

    def _ensure_ingress(
        self,
        *,
        namespace: str,
        service_name: str,
        spec: MarimoRuntimeSpec,
        public_url: str | None,
    ) -> None:
        ingress_route = _ingress_route(public_url)
        if ingress_route is None:
            return

        host, path = ingress_route
        try:
            self._networking_v1.read_namespaced_ingress(
                name=service_name,
                namespace=namespace,
            )
            return
        except ApiException as exc:
            if getattr(exc, "status", None) != 404:
                raise

        tls = None
        if self._ingress_tls_secret:
            tls = [
                kubernetes.client.V1IngressTLS(
                    hosts=[host],
                    secret_name=self._ingress_tls_secret,
                )
            ]

        body = kubernetes.client.V1Ingress(
            metadata=kubernetes.client.V1ObjectMeta(
                name=service_name,
                namespace=namespace,
                labels=_runtime_labels(spec, pod_name=service_name),
                annotations=(
                    _marimo_ingress_annotations(self._ingress_class_name) or None
                ),
            ),
            spec=kubernetes.client.V1IngressSpec(
                ingress_class_name=self._ingress_class_name,
                tls=tls,
                rules=[
                    kubernetes.client.V1IngressRule(
                        host=host,
                        http=kubernetes.client.V1HTTPIngressRuleValue(
                            paths=[
                                kubernetes.client.V1HTTPIngressPath(
                                    path=path,
                                    path_type="Prefix",
                                    backend=kubernetes.client.V1IngressBackend(
                                        service=kubernetes.client.V1IngressServiceBackend(
                                            name=service_name,
                                            port=kubernetes.client.V1ServiceBackendPort(
                                                number=spec.marimo_port,
                                            ),
                                        )
                                    ),
                                )
                            ]
                        ),
                    )
                ],
            ),
        )
        self._networking_v1.create_namespaced_ingress(namespace=namespace, body=body)

    def _workspace_claim_name(self, spec: MarimoRuntimeSpec) -> str:
        """Render the per-(owner,project) workspace PVC name from the template."""
        return _render_template(
            self._workspace_pvc_template,
            _template_context(spec),
        )

    def _ensure_workspace_pvc(self, *, namespace: str, claim_name: str) -> None:
        """Idempotently create the workspace PVC so the marimo notebook survives
        pod recreation. No-op when it already exists. Only called when a workspace
        PVC template is configured (otherwise the workspace stays emptyDir)."""
        try:
            self._core_v1.read_namespaced_persistent_volume_claim(
                name=claim_name, namespace=namespace
            )
            return
        except ApiException as exc:
            if getattr(exc, "status", None) != 404:
                raise

        body = kubernetes.client.V1PersistentVolumeClaim(
            metadata=kubernetes.client.V1ObjectMeta(name=claim_name),
            spec=kubernetes.client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                resources=kubernetes.client.V1ResourceRequirements(
                    requests={"storage": self._workspace_storage_size},
                ),
                storage_class_name=self._workspace_storage_class,
            ),
        )
        try:
            self._core_v1.create_namespaced_persistent_volume_claim(
                namespace=namespace, body=body
            )
        except ApiException as exc:
            if getattr(exc, "status", None) != 409:
                raise
            logger.info(
                "Marimo workspace PVC %s/%s already exists; reusing",
                namespace,
                claim_name,
            )

    def _workspace_volume(
        self,
        *,
        spec: MarimoRuntimeSpec,
        mount_root: str,
    ) -> tuple[Any, Any]:
        volume_name = "workspace"
        if self._workspace_pvc_template:
            claim_name = self._workspace_claim_name(spec)
            volume = kubernetes.client.V1Volume(
                name=volume_name,
                persistent_volume_claim=kubernetes.client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=claim_name,
                ),
            )
        else:
            volume = kubernetes.client.V1Volume(
                name=volume_name,
                empty_dir=kubernetes.client.V1EmptyDirVolumeSource(),
            )
        mount = kubernetes.client.V1VolumeMount(
            name=volume_name,
            mount_path=mount_root,
        )
        return volume, mount


def build_marimo_runtime_provisioner_from_env() -> MarimoRuntimeProvisioner:
    kind = (os.getenv("BR_MARIMO_RUNTIME_PROVISIONER") or "noop").strip().lower()
    if kind in {"", "noop", "none", "stub"}:
        return NoopMarimoRuntimeProvisioner()
    if kind == "kubernetes":
        return KubernetesMarimoRuntimeProvisioner()
    raise RuntimeError(f"Unsupported BR_MARIMO_RUNTIME_PROVISIONER: {kind}")


def _normalize_optional_text(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _slug(value: str, *, prefix: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", value.lower().replace("_", "-"))
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    cleaned = cleaned or prefix
    return f"{prefix}-{cleaned}"[:63].rstrip("-")


def _default_pod_name(runtime_session_id: str) -> str:
    return _slug(runtime_session_id, prefix="br-marimo")


def _runtime_token_secret_name(runtime_session_id: str) -> str:
    return _slug(runtime_session_id, prefix="br-marimo-token")


def _runtime_fs_group() -> int:
    """Supplemental GID applied to the runtime pod so the non-root marimo user
    can read the 0440 auth token via group membership."""

    raw = _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_FS_GROUP"))
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            pass
    return MARIMO_RUNTIME_DEFAULT_FS_GROUP


def _runtime_token_volume_and_mount(runtime_session_id: str) -> tuple[Any, Any]:
    secret_name = _runtime_token_secret_name(runtime_session_id)
    volume = kubernetes.client.V1Volume(
        name=MARIMO_RUNTIME_TOKEN_SECRET_VOLUME,
        projected=kubernetes.client.V1ProjectedVolumeSource(
            default_mode=0o440,
            sources=[
                kubernetes.client.V1VolumeProjection(
                    secret=kubernetes.client.V1SecretProjection(
                        name=secret_name,
                        optional=False,
                        items=[
                            kubernetes.client.V1KeyToPath(
                                key=MARIMO_RUNTIME_TOKEN_SECRET_KEY,
                                path="br_marimo_runtime_token",
                                mode=0o440,
                            )
                        ],
                    ),
                )
            ],
        ),
    )
    mount = kubernetes.client.V1VolumeMount(
        name=MARIMO_RUNTIME_TOKEN_SECRET_VOLUME,
        mount_path="/run/secrets",
        read_only=True,
    )
    return volume, mount


def _default_service_name(runtime_session_id: str) -> str:
    return _slug(runtime_session_id, prefix="br-marimo")


def _workspace_home(spec: MarimoRuntimeSpec) -> str:
    configured = _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_WORKSPACE_HOME"))
    if configured:
        return configured.rstrip("/")
    root = _normalize_optional_text(os.getenv("BR_STUDIO_MARIMO_WORKDIR_ROOT"))
    if root:
        if root.endswith(f"/{spec.project_id}"):
            return root.rsplit(f"/{spec.project_id}", 1)[0]
        if root.endswith("/projects"):
            return root.rsplit("/projects", 1)[0]
    return "/home/br_user/work"


def _template_context(spec: MarimoRuntimeSpec) -> dict[str, str]:
    return {
        "owner_user_id": spec.owner_user_id,
        "project_id": spec.project_id,
        "runtime_session_id": spec.runtime_session_id,
        "runtime_profile_id": spec.runtime_profile_id,
        "marimo_port": str(spec.marimo_port),
        "workspace_relative_root": spec.workspace_relative_root,
        "absolute_working_directory": spec.absolute_working_directory,
    }


def _render_template(template: str | None, context: dict[str, str]) -> str | None:
    normalized = _normalize_optional_text(template)
    if not normalized:
        return None
    try:
        return normalized.format_map({k: str(v) for k, v in context.items()})
    except Exception:
        return normalized


def _to_websocket_url(public_url: str | None) -> str | None:
    if not public_url:
        return None
    return public_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)


def _runtime_health_probe_path(public_url: str | None) -> str:
    base_path = _public_base_path(public_url)
    if not base_path:
        return "/health"
    return f"{base_path.rstrip('/')}/health"


def _public_base_path(public_url: str | None) -> str | None:
    normalized = _normalize_optional_text(public_url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")
    return path or None


def _public_proxy_url(public_url: str | None) -> str | None:
    normalized = _normalize_optional_text(public_url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    hostname = parsed.hostname
    if not hostname:
        return None
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return f"{hostname}:{port}"


def _runtime_mcp_token_ttl_seconds() -> int:
    raw = _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_MCP_TOKEN_TTL_SECONDS"))
    if raw is None:
        return _DEFAULT_RUNTIME_MCP_TOKEN_TTL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid BR_MARIMO_RUNTIME_MCP_TOKEN_TTL_SECONDS=%r; using default %s",
            raw,
            _DEFAULT_RUNTIME_MCP_TOKEN_TTL_SECONDS,
        )
        return _DEFAULT_RUNTIME_MCP_TOKEN_TTL_SECONDS
    if value <= 0:
        logger.warning(
            "Non-positive BR_MARIMO_RUNTIME_MCP_TOKEN_TTL_SECONDS=%s; using default %s",
            value,
            _DEFAULT_RUNTIME_MCP_TOKEN_TTL_SECONDS,
        )
        return _DEFAULT_RUNTIME_MCP_TOKEN_TTL_SECONDS
    return value


def _mint_runtime_mcp_bearer_token(spec: MarimoRuntimeSpec) -> str | None:
    owner_user_id = _normalize_optional_text(spec.owner_user_id)
    if owner_user_id is None:
        return None
    expires_delta = timedelta(seconds=_runtime_mcp_token_ttl_seconds())
    return create_access_token(
        data={
            "sub": owner_user_id,
            "surface": "marimo_runtime",
            "runtime_session_id": spec.runtime_session_id,
            "project_id": spec.project_id,
        },
        expires_delta=expires_delta,
    )


def _marimo_runtime_env_values(spec: MarimoRuntimeSpec) -> dict[str, str]:
    forwarded_allow_ips = (
        _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_FORWARDED_ALLOW_IPS"))
        or "*"
    )
    env_values = {
        "BR_MARIMO_RUNTIME_SESSION_ID": spec.runtime_session_id,
        "BR_MARIMO_RUNTIME_PROJECT_ID": spec.project_id,
        "BR_MCP_HTTP_URL": os.getenv(
            "BR_MCP_HTTP_URL", "https://brain-researcher.com/mcp"
        ),
        "FORWARDED_ALLOW_IPS": forwarded_allow_ips,
    }
    mcp_bearer_token = _mint_runtime_mcp_bearer_token(spec)
    if mcp_bearer_token is not None:
        env_values["BR_MCP_BEARER_TOKEN"] = mcp_bearer_token
    env_values.update(_runtime_ai_env_values())
    for name in (
        "TEMPLATEFLOW_HOME",
        "BR_ATLAS_OUTPUT_ROOT",
        "BR_ATLAS_SEARCH_ROOTS",
        "OPENNEURO_ROOT",
        "OPENNEURO_MOUNT_ROOT",
        "OPENNEURO_DERIV_ROOT",
        "OPENNEURO_METADATA_ROOT",
        "PUBLIC_BUCKETS_ROOT",
        "PUBLIC_S3_ROOT",
        "NICLIP_DATA_PATH",
        "NICLIP_MODEL_DIR",
        "NICLIP_MODEL_PATH",
        "NICLIP_FAISS_INDEX_PATH",
    ):
        value = _normalize_optional_text(os.getenv(name))
        if value is not None:
            env_values[name] = value
    # Pin marimo's skew-protection token so server-side cell injection can present
    # a matching Marimo-Server-Token (see marimo_server_patch.patch_token_manager_source).
    if spec.skew_protection_token:
        env_values["BR_MARIMO_SKEW_PROTECTION_TOKEN"] = spec.skew_protection_token
    if spec.taskbeacon_repo and spec.taskbeacon_target_path:
        env_values["BR_MARIMO_RUNTIME_TASKBEACON_REPO"] = spec.taskbeacon_repo
        env_values["BR_MARIMO_RUNTIME_TASKBEACON_TARGET_PATH"] = (
            spec.taskbeacon_target_path
        )
        if spec.taskbeacon_ref:
            env_values["BR_MARIMO_RUNTIME_TASKBEACON_REF"] = spec.taskbeacon_ref
    return env_values


def _runtime_extra_kubernetes_mounts() -> tuple[list[Any], list[Any]]:
    if not KUBERNETES_AVAILABLE:
        return [], []

    volume_defs = _json_list_env("BR_MARIMO_RUNTIME_EXTRA_VOLUMES_JSON")
    mount_defs = _json_list_env("BR_MARIMO_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON")

    volumes: list[Any] = []
    mounts: list[Any] = []
    seen_volume_names: set[str] = set()
    seen_mount_keys: set[tuple[str, str]] = set()

    for definition in volume_defs:
        try:
            volume = _volume_from_definition(definition)
        except ValueError as exc:
            logger.warning(
                "Skipping invalid BR_MARIMO runtime volume definition: %s", exc
            )
            continue
        if volume.name in seen_volume_names:
            continue
        seen_volume_names.add(volume.name)
        volumes.append(volume)

    for definition in mount_defs:
        try:
            mount = _volume_mount_from_definition(definition)
        except ValueError as exc:
            logger.warning("Skipping invalid BR_MARIMO runtime volume mount: %s", exc)
            continue
        key = (mount.name, mount.mount_path)
        if key in seen_mount_keys:
            continue
        seen_mount_keys.add(key)
        mounts.append(mount)

    return volumes, mounts


def _marimo_ingress_annotations(ingress_class_name: str | None) -> dict[str, str]:
    """Build ingress annotations for a per-session marimo runtime.

    Marimo's editor and kernel run entirely over a long-lived websocket. The
    nginx ingress controller drops upstream connections after its default 60s
    ``proxy-read-timeout``, which surfaces as marimo "kernel not found" /
    reconnect churn, so on nginx we widen the read/send timeouts.

    Traefik (the k3s default) ignores ``nginx.ingress.kubernetes.io/*``
    annotations entirely; its long-lived/idle timeouts live on the entrypoint
    (``transport.respondingTimeouts``), which is static config outside this
    code path. We therefore emit no synthetic nginx annotations for Traefik and
    leave the timeout tuning to the entrypoint, while still honoring any
    operator-supplied annotations via env override.
    """
    annotations: dict[str, str] = {}
    cls = (ingress_class_name or "").strip().lower()
    timeout = (
        _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_INGRESS_WS_TIMEOUT"))
        or "3600"
    )
    if cls == "" or "nginx" in cls:
        # Unknown/unset class defaults to the nginx annotations: non-nginx
        # controllers ignore unrecognized annotations, so this is safe.
        annotations["nginx.ingress.kubernetes.io/proxy-read-timeout"] = timeout
        annotations["nginx.ingress.kubernetes.io/proxy-send-timeout"] = timeout
    annotations.update(_json_dict_env("BR_MARIMO_RUNTIME_INGRESS_ANNOTATIONS_JSON"))
    return annotations


def _json_dict_env(name: str) -> dict[str, str]:
    raw = _normalize_optional_text(os.getenv(name))
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid %s JSON: %s", name, exc)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("%s must decode to a JSON object", name)
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def _json_list_env(name: str) -> list[dict[str, Any]]:
    raw = _normalize_optional_text(os.getenv(name))
    if raw is None:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid %s JSON: %s", name, exc)
        return []
    if not isinstance(parsed, list):
        logger.warning("%s must decode to a JSON list", name)
        return []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(parsed):
        if isinstance(item, dict):
            items.append(item)
            continue
        logger.warning("%s[%s] is not an object; skipping", name, index)
    return items


def _volume_from_definition(definition: dict[str, Any]) -> Any:
    name = _normalize_optional_text(str(definition.get("name") or ""))
    if name is None:
        raise ValueError("volume definition missing name")

    host_path = definition.get("hostPath")
    if isinstance(host_path, dict):
        path = _normalize_optional_text(str(host_path.get("path") or ""))
        if path is None:
            raise ValueError(f"hostPath volume {name!r} missing path")
        return kubernetes.client.V1Volume(
            name=name,
            host_path=kubernetes.client.V1HostPathVolumeSource(
                path=path,
                type=_normalize_optional_text(str(host_path.get("type") or "")),
            ),
        )

    secret = definition.get("secret")
    if isinstance(secret, dict):
        secret_name = _normalize_optional_text(str(secret.get("secretName") or ""))
        if secret_name is None:
            raise ValueError(f"secret volume {name!r} missing secretName")
        items = []
        for item in secret.get("items") or []:
            if not isinstance(item, dict):
                continue
            key = _normalize_optional_text(str(item.get("key") or ""))
            path = _normalize_optional_text(str(item.get("path") or ""))
            if key is None or path is None:
                continue
            items.append(
                kubernetes.client.V1KeyToPath(
                    key=key,
                    path=path,
                    mode=item.get("mode"),
                )
            )
        return kubernetes.client.V1Volume(
            name=name,
            secret=kubernetes.client.V1SecretVolumeSource(
                secret_name=secret_name,
                optional=bool(secret.get("optional", False)),
                items=items or None,
            ),
        )

    raise ValueError(f"volume {name!r} must define hostPath or secret")


def _volume_mount_from_definition(definition: dict[str, Any]) -> Any:
    name = _normalize_optional_text(str(definition.get("name") or ""))
    mount_path = _normalize_optional_text(str(definition.get("mountPath") or ""))
    if name is None or mount_path is None:
        raise ValueError("volume mount definition missing name or mountPath")
    return kubernetes.client.V1VolumeMount(
        name=name,
        mount_path=mount_path,
        read_only=bool(definition.get("readOnly", False)),
        sub_path=_normalize_optional_text(str(definition.get("subPath") or "")),
    )


def _runtime_ai_env_values() -> dict[str, str]:
    from brain_researcher.integrations.marimo.config import _default_ai_rules

    provider_name = (
        _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_AI_PROVIDER_NAME"))
        or "brain-researcher"
    )
    base_url = _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_AI_BASE_URL"))
    api_key = _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_AI_API_KEY"))
    provider_lookup = provider_name.lower().replace("-", "_")
    requires_base_url = provider_lookup not in _RUNTIME_AI_BUILTIN_PROVIDERS
    if not api_key or (requires_base_url and not base_url):
        return {}

    default_chat_model = (
        _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_AI_CHAT_MODEL"))
        or _normalize_optional_text(os.getenv("DEFAULT_LLM_MODEL"))
        or "gemini-3-flash-preview"
    )
    default_edit_model = (
        _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_AI_EDIT_MODEL"))
        or default_chat_model
    )
    default_autocomplete_model = (
        _normalize_optional_text(os.getenv("BR_MARIMO_RUNTIME_AI_AUTOCOMPLETE_MODEL"))
        or _normalize_optional_text(os.getenv("DEFAULT_CODING_MODEL"))
        or _normalize_optional_text(os.getenv("DEFAULT_LLM_MODEL"))
        or "gemini-3-flash-preview"
    )

    env_values = {
        "BR_MARIMO_AI_PROVIDER_NAME": provider_name,
        "BR_MARIMO_AI_API_KEY": api_key,
        "BR_MARIMO_AI_MODE": _normalize_optional_text(
            os.getenv("BR_MARIMO_RUNTIME_AI_MODE")
        )
        or _DEFAULT_RUNTIME_AI_MODE,
        "BR_MARIMO_AI_CHAT_MODEL": default_chat_model,
        "BR_MARIMO_AI_EDIT_MODEL": default_edit_model,
        "BR_MARIMO_AI_AUTOCOMPLETE_MODEL": default_autocomplete_model,
    }
    if base_url is not None:
        env_values["BR_MARIMO_AI_BASE_URL"] = base_url
    for source_name, target_name in (
        ("BR_MARIMO_RUNTIME_AI_RULES", "BR_MARIMO_AI_RULES"),
        ("BR_MARIMO_RUNTIME_AI_MAX_TOKENS", "BR_MARIMO_AI_MAX_TOKENS"),
        (
            "BR_MARIMO_RUNTIME_AI_INLINE_TOOLTIP",
            "BR_MARIMO_AI_INLINE_TOOLTIP",
        ),
    ):
        value = _normalize_optional_text(os.getenv(source_name))
        if value is not None:
            env_values[target_name] = value
    env_values.setdefault("BR_MARIMO_AI_RULES", _default_ai_rules())
    return env_values


def _build_marimo_launch_command(
    *,
    notebook_abs: str,
    template_source: str,
    marimo_port: int,
    public_url: str | None,
) -> str:
    product_mode = (os.getenv("BR_PRODUCT_MODE") or "").strip().lower()
    if product_mode == "hosted-cloud":
        auth_fragment = (
            f"if [ -s '{MARIMO_RUNTIME_TOKEN_PATH}' ]; then "
            f'AUTH_ARGS="--token-password-file {MARIMO_RUNTIME_TOKEN_PATH}"; '
            f"else echo 'br-marimo-runtime: runtime token file missing' >&2; exit 78; fi"
        )
    else:
        auth_fragment = (
            f"if [ -s '{MARIMO_RUNTIME_TOKEN_PATH}' ]; then "
            f'AUTH_ARGS="--token-password-file {MARIMO_RUNTIME_TOKEN_PATH}"; '
            f"else AUTH_ARGS='--no-token'; fi"
        )
    command = (
        f"mkdir -p $(dirname '{notebook_abs}') && "
        f"if [ ! -f '{notebook_abs}' ] && [ -f '{template_source}' ]; then cp '{template_source}' '{notebook_abs}'; fi && "
        f"{auth_fragment} && "
        f"marimo edit '{notebook_abs}' --host 0.0.0.0 --port {marimo_port} ${{AUTH_ARGS}}"
    )
    base_path = _public_base_path(public_url)
    if base_path:
        command = f"{command} --base-url '{base_path}'"
    proxy_url = _public_proxy_url(public_url)
    if proxy_url:
        command = f"{command} --proxy '{proxy_url}'"
    return command


def _ingress_route(public_url: str | None) -> tuple[str, str] | None:
    normalized = _normalize_optional_text(public_url)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return None
    return parsed.netloc, path


def _runtime_labels(spec: MarimoRuntimeSpec, *, pod_name: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": "brain-researcher-marimo",
        "app.kubernetes.io/component": "marimo-runtime",
        "brain-researcher/runtime-session-id": spec.runtime_session_id,
        "brain-researcher/project-id": _slug(spec.project_id, prefix="proj"),
        "brain-researcher/pod-name": pod_name,
    }


def _runtime_selector_labels(
    spec: MarimoRuntimeSpec, *, pod_name: str
) -> dict[str, str]:
    return {
        "brain-researcher/runtime-session-id": spec.runtime_session_id,
        "brain-researcher/pod-name": pod_name,
    }


def _pod_is_ready(pod: Any) -> bool:
    status = getattr(pod, "status", None)
    if status is None:
        return False
    if getattr(status, "phase", "").lower() != "running":
        return False
    container_statuses = getattr(status, "container_statuses", None) or []
    if not container_statuses:
        return False
    return any(bool(getattr(item, "ready", False)) for item in container_statuses)


def _delete_kubernetes_resource(delete_fn: Any, *, name: str, namespace: str) -> None:
    try:
        delete_fn(name=name, namespace=namespace)
    except ApiException as exc:
        if getattr(exc, "status", None) != 404:
            raise
