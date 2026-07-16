from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "README.md": (
        "PUBLIC_HOSTNAME=localhost docker compose --env-file .env config --quiet",
        "docker compose up -d --build --wait --wait-timeout 300",
        "docker compose ps --all",
        "bash scripts/smoke/health_smoke.sh",
        "docker compose down",
        "Inventory the empty Secret key contracts",
        "Secret` resources contain key contracts with empty values",
    ),
    "DEPLOYMENT.md": (
        "Support boundary: local development only.",
        "cp .env.example .env",
        "PUBLIC_HOSTNAME=localhost docker compose --env-file .env config --quiet",
        "docker compose up -d --build --wait --wait-timeout 300",
        "docker compose ps --all",
        "bash scripts/smoke/health_smoke.sh",
        "docker compose logs --tail=200",
        "docker compose down",
        "no verified production target",
        "d2d889a238b47d6b4409723223d6832693d298f6/DEPLOYMENT.md",
    ),
    "infrastructure/deployment/README.md": (
        "only **supported** deployment path",
        "every other deployment asset is experimental or historical",
        "**active**",
        "**experimental**",
        "**historical**",
        "**private-input-required**",
        "Local development only.",
        "Static Helm inspection",
        "do not install or apply resources",
    ),
    "infrastructure/deployment/gce_k3s/QUICKSTART.md": (
        "Status: experimental, render-only.",
        "helm lint infrastructure/k8s/helm/brain-researcher",
        "helm template brain-researcher infrastructure/k8s/helm/brain-researcher",
        "without applying it",
    ),
    "infrastructure/deployment/gcp/GKE_QUICKSTART.md": (
        "<!-- docs-status: historical -->",
        "Historical GKE quickstart tombstone",
        "not an active deployment guide",
    ),
    "docs/archive/deployment/README.md": (
        "<!-- docs-status: historical -->",
        "provenance, not an executable guide",
        "d2d889a238b47d6b4409723223d6832693d298f6",
        "Git history is the archive",
    ),
    "infrastructure/jupyterhub/values.mvp.yaml": (
        "Status: experimental static input only.",
        'tag: "0.1.0-oss-preview"',
    ),
    "scripts/services/restart_services_with_niclip.sh": (
        'NEO4J_DATA_ROOT="$PROJECT_ROOT/data/neo4j"',
        'COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"',
        'export BR_KG_API_URL="http://localhost:5000"',
        "brain-researcher-neo4j",
        "nohup br serve kg --host 0.0.0.0 --port 5000",
        "nohup br serve web --host 0.0.0.0 --port 3000",
        "http://localhost:5000/health",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "README.md": (
        "grep -RInE 'your-|<[^>]+>|bcrypt-hash'",
        "It contains placeholder credentials, TLS material, and basic-auth data",
    ),
    "DEPLOYMENT.md": (
        "scripts/deployment/",
        "docker-compose -f",
        "helm upgrade",
        "kubectl apply",
        "API Gateway: http://localhost:8080/health",
        "http://localhost:8080/services",
    ),
    "infrastructure/deployment/gce_k3s/QUICKSTART.md": (
        "values.prod",
        "gcloud compute",
        "helm install",
        "helm upgrade",
        "kubectl apply",
        "kubectl create",
    ),
    "infrastructure/deployment/gcp/GKE_QUICKSTART.md": (
        "values.prod",
        "gcloud compute",
        "helm install",
        "helm upgrade",
        "kubectl apply",
        "kubectl create",
    ),
    "infrastructure/jupyterhub/values.mvp.yaml": (
        "helm upgrade --install",
        'tag: "latest"',
        "CHANGE_ME_LONG_RANDOM_SECRET",
        "CHANGE_ME_OIDC",
    ),
    "scripts/services/restart_services_with_niclip.sh": (
        'NEO4J_COMPOSE_DIR="$PROJECT_ROOT/brain_researcher/services/br_kg"',
        'export BR_KG_API_URL="http://localhost:5001"',
        'export BR_KG_URL="http://localhost:5001"',
        'kill_service "Web UI" "services/web_ui"',
        "br_kg-neo4j",
        "nohup br serve kg --port 5001",
        "http://localhost:5001/health",
    ),
}

REMOVED_UNSUPPORTED_ASSETS = (
    "deployment.env.example",
    "infrastructure/docker/Dockerfile.hpc",
    "infrastructure/docker/Singularity.def",
    "infrastructure/deploy-load-balanced.sh",
    "infrastructure/deployment/blue_green.sh",
    "infrastructure/deployment/gce_k3s/traefik-helmchartconfig.yaml",
    "infrastructure/deployment/gcp/values.prod.yaml",
    "infrastructure/deployment/gce_k3s/values.prod.yaml",
    "infrastructure/cloudflare/configure_cloudflare.py",
    "infrastructure/cloudflare/direct_setup.py",
    "infrastructure/cloudflare/setup.sh",
    "infrastructure/cloudflare/terraform/main.tf",
    "infrastructure/cloudflare/terraform/terraform.tfvars.example",
    "infrastructure/cloudflare/update_dns.py",
    "infrastructure/cloudflare/workers/edge-optimizer.js",
    "infrastructure/cloudflare/wrangler.toml",
    "infrastructure/istio/install_istio.sh",
    "infrastructure/istio/verify_installation.sh",
    "infrastructure/k8s/helm/brain-researcher-istio/Chart.yaml",
    "infrastructure/monitoring/service_stack/start_monitoring.sh",
    "infrastructure/nginx/brain-researcher.conf",
    "infrastructure/nginx/setup_nginx.sh",
    "infrastructure/autoscaling/autoscaler.py",
    "scripts/services/web_ui/deploy.sh",
    "scripts/services/web_ui/deploy-ssr.sh",
    "scripts/services/br-kg/deploy_to_railway.sh",
    "scripts/services/br-kg/deploy.sh",
    "scripts/services/br-kg/test_railway_deployment.sh",
    "tests/unit/br_kg/test_brain_researcher_deployment.py",
    "apps/web-ui/wrangler.toml",
)


def test_operator_docs_and_scripts_use_current_runtime_contracts() -> None:
    for relpath, expected_substrings in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        for needle in expected_substrings:
            assert " ".join(needle.split()) in normalized, (
                f"Missing expected text in {relpath}: {needle}"
            )


def test_operator_docs_and_scripts_do_not_reintroduce_stale_paths() -> None:
    for relpath, forbidden_substrings in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, f"Found stale text in {relpath}: {needle}"


def test_unsupported_deployment_assets_stay_out_of_the_active_tree() -> None:
    for relpath in REMOVED_UNSUPPORTED_ASSETS:
        assert not (REPO_ROOT / relpath).exists(), relpath

    assert (REPO_ROOT / ".env.example").is_file()
    assert "PUBLIC_HOSTNAME=localhost" in (REPO_ROOT / ".env.example").read_text(
        encoding="utf-8"
    )
    deployment = (REPO_ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "The root [`.env.example`](.env.example) is the only general" in deployment


def test_active_deployment_docs_do_not_name_unshipped_helpers_or_overlays() -> None:
    active_docs = (
        REPO_ROOT / "DEPLOYMENT.md",
        REPO_ROOT / "infrastructure" / "deployment" / "README.md",
        REPO_ROOT / "infrastructure" / "deployment" / "gce_k3s" / "QUICKSTART.md",
    )
    for path in active_docs:
        text = path.read_text(encoding="utf-8")
        assert "scripts/deployment/" not in text, path
        assert "values.prod" not in text, path


def test_public_env_template_does_not_ship_provider_credentials() -> None:
    assignments = {}
    for line in (REPO_ROOT / ".env.example").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            assignments[key] = value

    provider_keys = (
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "ZAI_API_KEY",
        "OPENROUTER_API_KEY",
    )
    for key in provider_keys:
        assert assignments[key] == "", f"{key} must stay empty in .env.example"
