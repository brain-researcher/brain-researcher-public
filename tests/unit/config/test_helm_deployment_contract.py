from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CHART = REPO_ROOT / "infrastructure" / "k8s" / "helm" / "brain-researcher"
HELM = shutil.which("helm")

pytestmark = pytest.mark.skipif(HELM is None, reason="helm executable is not installed")


def _helm(*args: str) -> str:
    result = subprocess.run(
        [HELM, *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _render(*args: str) -> list[dict[str, Any]]:
    rendered = _helm("template", "contract", str(CHART), *args)
    return [document for document in yaml.safe_load_all(rendered) if document]


def _workload_containers(
    documents: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    containers = []
    for document in documents:
        if document.get("kind") not in {"Deployment", "StatefulSet", "DaemonSet"}:
            continue
        pod_spec = document["spec"]["template"]["spec"]
        containers.extend(
            (document, container) for container in pod_spec.get("containers", [])
        )
    return containers


def _container(
    documents: list[dict[str, Any]], workload_suffix: str, container_name: str
) -> dict[str, Any]:
    for document, container in _workload_containers(documents):
        if (
            document["metadata"]["name"].endswith(workload_suffix)
            and container["name"] == container_name
        ):
            return container
    raise AssertionError(f"missing {workload_suffix}/{container_name}")


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_chart_lints_strictly_and_renders_all_application_images() -> None:
    _helm("lint", "--strict", str(CHART))
    documents = _render("--set", "mcp.enabled=true")

    expected = {
        ("-agent", "agent"): "brain-researcher/agent:0.3.0-oss-preview",
        ("-br-kg", "br-kg"): "brain-researcher/br-kg:0.3.0-oss-preview",
        ("-mcp", "mcp"): "brain-researcher/mcp:0.3.0-oss-preview",
        ("-orchestrator", "orchestrator"): (
            "brain-researcher/orchestrator:0.3.0-oss-preview"
        ),
        ("-web-ui", "web-ui"): "brain-researcher/web-ui:0.3.0-oss-preview",
        ("-postgres", "metrics"): ("prometheuscommunity/postgres-exporter:v0.15.0"),
        ("-redis", "metrics"): "oliver006/redis_exporter:v1.62.0",
    }
    for (workload, container), image in expected.items():
        assert _container(documents, workload, container)["image"] == image

    all_images = [
        container["image"] for _, container in _workload_containers(documents)
    ]
    assert all(not image.startswith("/") for image in all_images)
    assert all(not image.endswith(":latest") for image in all_images)

    orchestrator = _container(documents, "-orchestrator", "orchestrator")
    env = {entry["name"]: entry.get("value") for entry in orchestrator["env"]}
    assert (
        env["BR_MARIMO_RUNTIME_IMAGE"]
        == "brain-researcher/marimo-singleuser:0.3.0-oss-preview"
    )


def test_registry_repository_tag_and_pull_policy_overrides_reach_rendered_pods() -> (
    None
):
    documents = _render(
        "--set",
        "mcp.enabled=true",
        "--set-string",
        "global.imageRegistry=registry.example/team",
        "--set-string",
        "global.imagePullPolicy=Always",
        "--set-string",
        "agent.image.repository=custom/agent",
        "--set-string",
        "agent.image.tag=9.8.7",
        "--set-string",
        "agent.image.pullPolicy=Never",
        "--set-string",
        "mcp.image.repository=custom/mcp",
        "--set-string",
        "mcp.image.tag=2.3.4",
        "--set-string",
        "orchestrator.marimoRuntime.imageRepository=custom/marimo",
        "--set-string",
        "orchestrator.marimoRuntime.imageTag=5.6.7",
    )

    agent = _container(documents, "-agent", "agent")
    assert agent["image"] == "registry.example/team/custom/agent:9.8.7"
    assert agent["imagePullPolicy"] == "Never"
    for workload, container in (
        ("-br-kg", "br-kg"),
        ("-mcp", "mcp"),
        ("-orchestrator", "orchestrator"),
        ("-web-ui", "web-ui"),
    ):
        assert _container(documents, workload, container)["imagePullPolicy"] == "Always"
    assert (
        _container(documents, "-mcp", "mcp")["image"]
        == "registry.example/team/custom/mcp:2.3.4"
    )

    orchestrator = _container(documents, "-orchestrator", "orchestrator")
    env = {entry["name"]: entry.get("value") for entry in orchestrator["env"]}
    assert env["BR_MARIMO_RUNTIME_IMAGE"] == "registry.example/team/custom/marimo:5.6.7"
    assert env["BR_MARIMO_RUNTIME_IMAGE_PULL_POLICY"] == "Always"

    legacy = _render("--set-string", "agent.imageTag=legacy-override")
    assert (
        _container(legacy, "-agent", "agent")["image"]
        == "brain-researcher/agent:legacy-override"
    )

    global_override = _render(
        "--set", "mcp.enabled=true", "--set-string", "global.imageTag=global-override"
    )
    for workload, container in (
        ("-agent", "agent"),
        ("-br-kg", "br-kg"),
        ("-mcp", "mcp"),
        ("-orchestrator", "orchestrator"),
        ("-web-ui", "web-ui"),
    ):
        assert _container(global_override, workload, container)["image"].endswith(
            ":global-override"
        )
    global_orchestrator = _container(global_override, "-orchestrator", "orchestrator")
    global_env = {
        entry["name"]: entry.get("value") for entry in global_orchestrator["env"]
    }
    assert global_env["BR_MARIMO_RUNTIME_IMAGE"].endswith(":global-override")

    combined = _render(
        "--set-string",
        "global.imageTag=global-override",
        "--set-string",
        "agent.imageTag=legacy-override",
    )
    assert (
        _container(combined, "-agent", "agent")["image"]
        == "brain-researcher/agent:legacy-override"
    )
    assert (
        _container(combined, "-br-kg", "br-kg")["image"]
        == "brain-researcher/br-kg:global-override"
    )


def test_render_uses_only_explicit_pre_created_secret_contracts() -> None:
    documents = _render("--set", "mcp.enabled=true")
    assert all(document.get("kind") != "Secret" for document in documents)

    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert "backup" not in values
    for mapping in _walk(values):
        assert "accessKeyId" not in mapping
        assert "secretAccessKey" not in mapping

    secret_values = values["secrets"]
    assert all(
        "create" not in contract and "data" not in contract
        for contract in secret_values.values()
    )

    database_contract = secret_values["databaseCredentials"]
    assert database_contract == {
        "existingSecret": "br-database-credentials-k8s",
        "keys": {
            "postgresPassword": "POSTGRES_PASSWORD",
            "postgresUrl": "POSTGRES_URL",
        },
        "requiredKeys": ["POSTGRES_PASSWORD", "POSTGRES_URL"],
    }
    assert list(database_contract["keys"].values()) == database_contract["requiredKeys"]
    postgres = _container(documents, "-postgres", "postgres")
    postgres_refs = [
        entry["valueFrom"]["secretKeyRef"]
        for entry in postgres["env"]
        if "valueFrom" in entry
    ]
    assert postgres_refs == [
        {
            "name": database_contract["existingSecret"],
            "key": database_contract["keys"]["postgresPassword"],
        }
    ]
    exporter = _container(documents, "-postgres", "metrics")
    assert exporter["env"][0]["valueFrom"]["secretKeyRef"] == {
        "name": database_contract["existingSecret"],
        "key": database_contract["keys"]["postgresUrl"],
    }

    web_ui = _container(documents, "-web-ui", "web-ui")
    hypothesis_database_ref = next(
        entry["valueFrom"]["secretKeyRef"]
        for entry in web_ui["env"]
        if entry["name"] == "HYPOTHESIS_STORE_POSTGRES_URL"
    )
    assert hypothesis_database_ref == {
        "name": secret_values["externalServices"]["existingSecret"],
        "key": secret_values["externalServices"]["keys"]["hypothesisStorePostgresUrl"],
        "optional": True,
    }
    external_contract = secret_values["externalServices"]
    assert list(external_contract["keys"].values()) == external_contract["optionalKeys"]

    mcp = _container(documents, "-mcp", "mcp")
    jwt_ref = next(
        entry["valueFrom"]["secretKeyRef"]
        for entry in mcp["env"]
        if entry["name"] == "JWT_SECRET_KEY"
    )
    assert jwt_ref == {
        "name": external_contract["existingSecret"],
        "key": external_contract["keys"]["nextauthSecret"],
        "optional": True,
    }

    overridden = _render(
        "--set-string",
        "secrets.externalServices.existingSecret=custom-external-services",
        "--set-string",
        "secrets.tlsCertificates.existingSecret=custom-ingress-tls",
    )
    overridden_web_ui = _container(overridden, "-web-ui", "web-ui")
    overridden_hypothesis_ref = next(
        entry["valueFrom"]["secretKeyRef"]
        for entry in overridden_web_ui["env"]
        if entry["name"] == "HYPOTHESIS_STORE_POSTGRES_URL"
    )
    assert overridden_hypothesis_ref["name"] == "custom-external-services"
    overridden_ingress = next(
        document for document in overridden if document.get("kind") == "Ingress"
    )
    assert overridden_ingress["spec"]["tls"][0]["secretName"] == "custom-ingress-tls"

    neo4j_contract = values["neo4j"]["auth"]
    assert neo4j_contract["requiredKeys"] == [neo4j_contract["passwordKey"]]
    br_kg = _container(documents, "-br-kg", "br-kg")
    neo4j_password_ref = next(
        entry["valueFrom"]["secretKeyRef"]
        for entry in br_kg["env"]
        if entry["name"] == "NEO4J_PASSWORD"
    )
    assert neo4j_password_ref == {
        "name": neo4j_contract["existingSecret"],
        "key": neo4j_contract["passwordKey"],
    }
    neo4j = next(
        document
        for document in documents
        if document.get("kind") == "StatefulSet"
        and document["metadata"]["name"].endswith("-neo4j")
    )
    assert neo4j["spec"]["template"]["spec"]["volumes"][0]["secret"] == {
        "secretName": neo4j_contract["existingSecret"]
    }

    allowed_secret_names = {
        contract["existingSecret"]
        for contract in secret_values.values()
        if contract["existingSecret"]
    } | {neo4j_contract["existingSecret"]}
    rendered_secret_names = set()
    for mapping in _walk(documents):
        if "secretKeyRef" in mapping:
            rendered_secret_names.add(mapping["secretKeyRef"]["name"])
        if "secretRef" in mapping:
            rendered_secret_names.add(mapping["secretRef"]["name"])
        if "secretName" in mapping:
            rendered_secret_names.add(mapping["secretName"])
    assert rendered_secret_names <= allowed_secret_names


def test_chart_copy_states_static_only_boundary_without_mutation_recipes() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(CHART.rglob("*"))
        if path.is_file()
    )
    normalized = " ".join(combined.split())

    assert "experimental static-rendering scaffold" in combined.lower()
    assert "not a supported installation or production deployment target" in normalized
    assert (
        "renders no Secret resources" in combined
        or "emits no Secret resources" in combined
    )
    assert "${PUBLIC_HOSTNAME}" not in combined
    for forbidden in (
        "values.prod",
        "helm install",
        "helm upgrade",
        "kubectl apply",
        "kubectl create",
        "Successfully Deployed",
    ):
        assert forbidden not in combined
