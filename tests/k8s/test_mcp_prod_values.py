#!/usr/bin/env python3
"""Regression checks for active MCP deployment paths and values files."""

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ".github/workflows/ci.yml"
HELM_CHART_DIR = "infrastructure/k8s/helm/brain-researcher"
HELM_VALUES = f"{HELM_CHART_DIR}/values.yaml"
HELM_README = f"{HELM_CHART_DIR}/README.md"
MCP_TEMPLATE = f"{HELM_CHART_DIR}/templates/mcp-deployment.yaml"
BR_KG_TEMPLATE = f"{HELM_CHART_DIR}/templates/br-kg-statefulset.yaml"
ORCHESTRATOR_TEMPLATE = f"{HELM_CHART_DIR}/templates/orchestrator-deployment.yaml"
RETIRED_CHART_PROD_VALUES = f"{HELM_CHART_DIR}/production-values.yaml"
GCE_K3S_VALUES = "infrastructure/deployment/gce_k3s/values.prod.yaml"
GCP_VALUES = "infrastructure/deployment/gcp/values.prod.yaml"

NO_CHART_LOCAL_PROD_VALUES_DOCS = (
    CI_WORKFLOW,
    "docs/DEPLOYMENT_GKE.md",
    HELM_README,
)

ACTIVE_DEPLOYMENT_ENTRYPOINTS: dict[str, tuple[str, ...]] = {
    CI_WORKFLOW: (
        "infrastructure/k8s/helm/brain-researcher",
        "infrastructure/deployment/gce_k3s/values.prod.yaml",
        "infrastructure/deployment/gcp/values.prod.yaml",
    ),
    "infrastructure/deploy-load-balanced.sh": (
        "infrastructure/k8s/manifests",
        "infrastructure/k8s/helm/brain-researcher",
    ),
    "infrastructure/istio/install_istio.sh": (
        "infrastructure/k8s/helm/brain-researcher-istio",
    ),
    "infrastructure/deployment/gce_k3s/QUICKSTART.md": (
        "infrastructure/k8s/helm/brain-researcher",
        "infrastructure/deployment/gce_k3s/values.prod.yaml",
    ),
    "infrastructure/deployment/gce_k3s/values.prod.yaml": (
        "infrastructure/k8s/helm/brain-researcher",
        "infrastructure/deployment/gce_k3s/values.prod.yaml",
    ),
    "infrastructure/deployment/gcp/GKE_QUICKSTART.md": (
        "infrastructure/k8s/helm/brain-researcher",
        "infrastructure/deployment/gcp/values.prod.yaml",
    ),
    "infrastructure/deployment/gcp/values.prod.yaml": (
        "infrastructure/k8s/helm/brain-researcher",
        "infrastructure/deployment/gcp/values.prod.yaml",
    ),
    "infrastructure/k8s/helm/brain-researcher/templates/NOTES.txt": (
        "infrastructure/k8s/helm/brain-researcher",
        "infrastructure/deployment/gcp/values.prod.yaml",
    ),
    "docs/DEPLOYMENT_GKE.md": (
        "infrastructure/k8s/helm/brain-researcher",
        "infrastructure/monitoring",
    ),
    HELM_README: (
        "infrastructure/k8s/helm/brain-researcher",
        "infrastructure/deployment/gcp/values.prod.yaml",
    ),
}

RETIRED_LAYOUT_PATTERNS = (
    re.compile(r"(?<!infrastructure/)k8s/manifests"),
    re.compile(r"(?<!infrastructure/)k8s/helm/brain-researcher(?:-istio)?"),
    re.compile(r"(?<!infrastructure/)deployment/(?:gce_k3s|gcp)/values\.prod\.yaml"),
)


def _load_text(relpath: str) -> str:
    path = REPO_ROOT / relpath
    assert path.exists(), f"Missing file: {path}"
    return path.read_text(encoding="utf-8")


def _load_values(relpath: str) -> dict:
    return yaml.safe_load(_load_text(relpath)) or {}


def _load_extra_env(relpath: str, section: str) -> dict[str, str]:
    values = _load_values(relpath)
    extra_env = (values.get(section) or {}).get("extraEnv") or []
    return {
        str(item.get("name")): str(item.get("value"))
        for item in extra_env
        if isinstance(item, dict) and item.get("name") and "value" in item
    }


def _parse_csv_env(raw: str) -> set[str]:
    return {chunk.strip() for chunk in str(raw or "").split(",") if chunk.strip()}


def _load_extra_volume_mounts(relpath: str, section: str) -> list[dict]:
    values = _load_values(relpath)
    mounts = (values.get(section) or {}).get("extraVolumeMounts") or []
    return [item for item in mounts if isinstance(item, dict)]


def _load_extra_volumes(relpath: str, section: str) -> list[dict]:
    values = _load_values(relpath)
    volumes = (values.get(section) or {}).get("extraVolumes") or []
    return [item for item in volumes if isinstance(item, dict)]


@pytest.mark.parametrize(
    "values_relpath",
    [
        GCE_K3S_VALUES,
        GCP_VALUES,
    ],
)
def test_prod_values_enable_mcp_stateless_http(values_relpath: str) -> None:
    env_vars = _load_extra_env(values_relpath, "mcp")
    assert env_vars.get("BR_MCP_STATELESS_HTTP") == "true"


def test_gce_k3s_mcp_image_tag_not_known_bad_tag() -> None:
    values = _load_values(GCE_K3S_VALUES)
    image_tag = ((values.get("mcp") or {}).get("imageTag") or "").strip()
    assert image_tag, "mcp.imageTag must be set in gce_k3s prod values"
    assert image_tag != "20260224-br_kg-evidencepaths1"


def test_gce_k3s_mcp_enables_latex_pdf_compile() -> None:
    env_vars = _load_extra_env(GCE_K3S_VALUES, "mcp")
    assert env_vars.get("BR_MCP_ENABLE_LATEX_COMPILE") == "1"


def test_gce_k3s_mcp_shares_api_usd_credits_db_with_agent_and_orchestrator() -> None:
    mcp_env = _load_extra_env(GCE_K3S_VALUES, "mcp")
    agent_env = _load_extra_env(GCE_K3S_VALUES, "agent")
    orchestrator_env = _load_extra_env(GCE_K3S_VALUES, "orchestrator")

    assert mcp_env.get("BR_SHARED_DATA_ROOT") == "/app/jobstore"
    assert mcp_env.get("BR_CREDITS_DB") == "/app/jobstore/credits.sqlite"
    assert mcp_env.get("BR_CREDITS_DB") == agent_env.get("BR_CREDITS_DB")
    assert mcp_env.get("BR_CREDITS_DB") == orchestrator_env.get("BR_CREDITS_DB")
    assert mcp_env.get("BR_MCP_PLATFORM_API_FEE_REQUIRED") == "1"
    assert "BR_ENABLE_CREDITS_GRANT_PROXY" not in _load_extra_env(
        GCE_K3S_VALUES, "webUi"
    )


def test_mcp_dockerfiles_ship_latex_report_toolchain() -> None:
    required_packages = (
        "latexmk",
        "texlive-latex-extra",
        "texlive-fonts-recommended",
        "texlive-pictures",
        "texlive-science",
    )
    for relpath in ("Dockerfile", "infrastructure/docker/Dockerfile.mcp"):
        text = _load_text(relpath)
        for package in required_packages:
            assert package in text, f"Missing {package} in {relpath}"


def test_gce_k3s_br_kg_uses_database_credentials_secret() -> None:
    values = _load_values(GCE_K3S_VALUES)
    neo4j_auth = (values.get("neo4j") or {}).get("auth") or {}

    assert neo4j_auth.get("existingSecret") == "brain-researcher-database-credentials"
    assert neo4j_auth.get("passwordKey") == "NEO4J_PASSWORD"


def test_gce_k3s_orchestrator_marimo_runtime_mount_envs_present() -> None:
    env_vars = _load_extra_env(GCE_K3S_VALUES, "orchestrator")

    assert "BR_MARIMO_RUNTIME_EXTRA_VOLUMES_JSON" in env_vars
    assert "BR_MARIMO_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON" in env_vars


def test_gce_k3s_agent_and_marimo_runtime_share_reference_asset_mounts() -> None:
    required_assets = {
        "openneuro-metadata": (
            "/srv/datasets/openneuro_metadata",
            "/app/data/openneuro_metadata",
        ),
        "niclip-data": ("/srv/datasets/niclip", "/app/data/niclip"),
        "niclip-models": ("/srv/models/niclip", "/app/models/niclip"),
        "niclip-faiss": ("/srv/indexes/niclip", "/app/data/niclip_faiss"),
        "neurosynth-nimare": (
            "/srv/datasets/neurosynth_nimare",
            "/app/data/neurosynth_nimare",
        ),
        "scholarly-metadata": (
            "/srv/datasets/scholarly_metadata",
            "/app/data/scholarly_metadata",
        ),
        "neurosynth-maps": (
            "/srv/datasets/neurosynth_maps",
            "/app/data/neurosynth_maps",
        ),
        "datasets-root-compat": ("/srv/datasets", "/data"),
    }

    agent_env = _load_extra_env(GCE_K3S_VALUES, "agent")
    assert agent_env.get("OPENNEURO_METADATA_ROOT") == "/app/data/openneuro_metadata"
    assert agent_env.get("NICLIP_DATA_PATH") == "/app/data/niclip"
    assert agent_env.get("NICLIP_MODEL_DIR") == "/app/models/niclip"
    assert agent_env.get("NICLIP_FAISS_INDEX_PATH") == "/app/data/niclip_faiss"

    agent_volumes = {
        item.get("name"): ((item.get("hostPath") or {}).get("path"))
        for item in _load_extra_volumes(GCE_K3S_VALUES, "agent")
    }
    agent_mounts = {
        item.get("name"): item.get("mountPath")
        for item in _load_extra_volume_mounts(GCE_K3S_VALUES, "agent")
    }
    for name, (host_path, mount_path) in required_assets.items():
        assert agent_volumes.get(name) == host_path
        assert agent_mounts.get(name) == mount_path

    orchestrator_env = _load_extra_env(GCE_K3S_VALUES, "orchestrator")
    assert orchestrator_env.get("OPENNEURO_METADATA_ROOT") == (
        "/app/data/openneuro_metadata"
    )
    assert orchestrator_env.get("NICLIP_DATA_PATH") == "/app/data/niclip"
    assert orchestrator_env.get("NICLIP_MODEL_DIR") == "/app/models/niclip"
    assert orchestrator_env.get("NICLIP_FAISS_INDEX_PATH") == "/app/data/niclip_faiss"

    runtime_volumes = json.loads(
        orchestrator_env["BR_MARIMO_RUNTIME_EXTRA_VOLUMES_JSON"]
    )
    runtime_mounts = json.loads(
        orchestrator_env["BR_MARIMO_RUNTIME_EXTRA_VOLUME_MOUNTS_JSON"]
    )
    runtime_volume_paths = {
        item.get("name"): ((item.get("hostPath") or {}).get("path"))
        for item in runtime_volumes
    }
    runtime_mount_paths = {
        item.get("name"): item.get("mountPath") for item in runtime_mounts
    }
    for name, (host_path, mount_path) in required_assets.items():
        assert runtime_volume_paths.get(name) == host_path
        assert runtime_mount_paths.get(name) == mount_path


@pytest.mark.parametrize(
    "values_relpath",
    [
        HELM_VALUES,
        GCE_K3S_VALUES,
        GCP_VALUES,
    ],
)
def test_hypothesis_deep_research_waiting_envs_persisted(values_relpath: str) -> None:
    env_vars = _load_extra_env(values_relpath, "webUi")
    assert env_vars.get("HYPOTHESIS_DEEP_RESEARCH_UI_WAIT_SEC") == "300"
    assert env_vars.get("HYPOTHESIS_DEEP_RESEARCH_BACKGROUND_CAP_SEC") == "21600"


@pytest.mark.parametrize(
    "values_relpath",
    [
        GCE_K3S_VALUES,
        GCP_VALUES,
    ],
)
def test_hypothesis_template_diversity_envs_persisted(values_relpath: str) -> None:
    env_vars = _load_extra_env(values_relpath, "webUi")
    assert env_vars.get("HYPOTHESIS_CLAIM_EVIDENCE_OVERLAP_THRESHOLD") == "0.15"
    assert env_vars.get("HYPOTHESIS_TEMPLATE_DIVERSITY_ENABLED") == "1"
    assert env_vars.get("HYPOTHESIS_TEMPLATE_MAX_PATTERN_REUSE") == "1"
    assert env_vars.get("HYPOTHESIS_TEMPLATE_SIMILARITY_THRESHOLD") == "0.75"
    assert env_vars.get("HYPOTHESIS_TEMPLATE_MAX_RESAMPLE_PER_SLOT") == "3"


def test_mcp_template_loads_llm_api_keys_secret() -> None:
    text = _load_text(MCP_TEMPLATE)
    assert "-llm-api-keys" in text


@pytest.mark.parametrize(
    ("template_relpath", "expected_snippet"),
    [
        (MCP_TEMPLATE, "{{- tpl (toYaml .Values.mcp.extraEnv) $ | nindent 12 }}"),
        (
            BR_KG_TEMPLATE,
            "{{- tpl (toYaml $brKg.extraEnv) $ | nindent 12 }}",
        ),
        (
            BR_KG_TEMPLATE,
            "{{- tpl (toYaml $brKg.extraEnvFrom) $ | nindent 12 }}",
        ),
        (
            ORCHESTRATOR_TEMPLATE,
            "{{- tpl (toYaml .Values.orchestrator.extraEnv) $ | nindent 12 }}",
        ),
    ],
)
def test_service_templates_render_extra_env_with_tpl(
    template_relpath: str,
    expected_snippet: str,
) -> None:
    text = _load_text(template_relpath)
    assert expected_snippet in text


@pytest.mark.parametrize(
    "values_relpath",
    [
        GCE_K3S_VALUES,
        GCP_VALUES,
    ],
)
def test_agent_allowlist_includes_rest_connectome_workflow_ids(
    values_relpath: str,
) -> None:
    env_vars = _load_extra_env(values_relpath, "agent")
    allowset = _parse_csv_env(env_vars.get("AGENT_TOOL_ALLOWLIST", ""))
    required = {
        "workflow_rest_connectome_e2e",
        "fetch_atlas",
        "extract_timeseries",
        "compute_connectivity",
    }
    missing = sorted(required - allowset)
    assert not missing, f"Missing allowlist IDs in {values_relpath}: {missing}"


def test_gce_k3s_values_configure_mcp_run_root_aliases_and_openneuro_mounts() -> None:
    values = _load_values(GCE_K3S_VALUES)
    mcp_values = values.get("mcp") or {}

    assert mcp_values.get("runRootAliases") == (
        "/app/artifacts/mcp_runs,/app/data/runs/mcp_runs"
    )

    openneuro_mounts = mcp_values.get("openneuroMounts") or {}
    assert openneuro_mounts.get("enabled") is True
    assert ((openneuro_mounts.get("root") or {}).get("mountPath")) == (
        "/app/data/openneuro"
    )
    assert ((openneuro_mounts.get("derivatives") or {}).get("mountRootPath")) == (
        "/app/data/OpenNeuroDerivatives"
    )


@pytest.mark.parametrize(
    "values_relpath",
    [
        GCE_K3S_VALUES,
        GCP_VALUES,
    ],
)
def test_prod_values_configure_writable_shared_atlas_home(values_relpath: str) -> None:
    env_vars = _load_extra_env(values_relpath, "mcp")
    assert env_vars.get("BR_ATLAS_OUTPUT_ROOT") == "/app/data/atlases"

    atlas_mount = next(
        (
            item
            for item in _load_extra_volume_mounts(values_relpath, "mcp")
            if item.get("mountPath") == "/app/data/atlases"
        ),
        None,
    )
    assert atlas_mount is not None, f"Missing atlas mount in {values_relpath}"
    assert atlas_mount.get("readOnly") is False


def test_mcp_template_supports_run_root_aliases_and_openneuro_envs() -> None:
    text = _load_text(MCP_TEMPLATE)
    for token in (
        "BR_MCP_RUN_ROOT_ALIASES",
        "OPENNEURO_MOUNT_ROOT",
        "OPENNEURO_ROOT",
        "OPENNEURO_DERIV_ROOT",
    ):
        assert token in text


@pytest.mark.parametrize("relpath", NO_CHART_LOCAL_PROD_VALUES_DOCS)
def test_active_docs_and_ci_do_not_use_chart_local_production_values(
    relpath: str,
) -> None:
    text = _load_text(relpath)
    assert "production-values.yaml" not in text


def test_retired_chart_local_production_values_file_is_absent() -> None:
    assert not (REPO_ROOT / RETIRED_CHART_PROD_VALUES).exists()


def test_deployment_gke_cicd_example_uses_canonical_prod_overlay() -> None:
    text = _load_text("docs/DEPLOYMENT_GKE.md")
    assert (
        "helm upgrade --install brain-researcher infrastructure/k8s/helm/brain-researcher \\"
        in text
    )
    assert "  -f infrastructure/deployment/gcp/values.prod.yaml \\" in text
    assert "  --set global.imageRegistry=gcr.io/$PROJECT_ID \\" in text


@pytest.mark.parametrize(
    ("relpath", "required_snippets"),
    sorted(ACTIVE_DEPLOYMENT_ENTRYPOINTS.items()),
)
def test_active_deployment_entrypoints_use_canonical_infrastructure_paths(
    relpath: str,
    required_snippets: tuple[str, ...],
) -> None:
    text = _load_text(relpath)

    for snippet in required_snippets:
        assert snippet in text, f"Expected canonical path in {relpath}: {snippet}"

    for pattern in RETIRED_LAYOUT_PATTERNS:
        assert (
            pattern.search(text) is None
        ), f"Found retired layout reference in {relpath}: {pattern.pattern}"
