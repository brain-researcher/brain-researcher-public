from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_ROOT = REPO_ROOT / "apps" / "web-ui"


def _package_json() -> dict[str, object]:
    return json.loads((WEB_ROOT / "package.json").read_text(encoding="utf-8"))


def test_web_package_manager_and_lock_are_single_source() -> None:
    package = _package_json()
    lock = json.loads((WEB_ROOT / "package-lock.json").read_text(encoding="utf-8"))

    assert package["packageManager"] == "npm@10.8.2"
    assert package["engines"] == {"node": ">=20 <21", "npm": ">=10 <11"}
    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["engines"] == package["engines"]
    assert not (WEB_ROOT / "pnpm-lock.yaml").exists()

    for ignore_file in (WEB_ROOT / ".gitignore", WEB_ROOT / ".dockerignore"):
        ignore_rules = ignore_file.read_text(encoding="utf-8").casefold()
        assert ".pnp" not in ignore_rules
        assert "yarn-" not in ignore_rules
        assert "pnpm-" not in ignore_rules

    wiki_config = (REPO_ROOT / ".devin" / "wiki.json").read_text(encoding="utf-8")
    assert "pnpm-lock.yaml" not in wiki_config


def test_storybook_clean_build_inputs_are_reproducible() -> None:
    package = _package_json()
    lock = json.loads((WEB_ROOT / "package-lock.json").read_text(encoding="utf-8"))

    assert package["devDependencies"]["ajv"] == "8.17.1"
    assert lock["packages"]["node_modules/ajv"]["version"] == "8.17.1"
    assert lock["packages"]["node_modules/ajv-keywords"]["peerDependencies"] == {
        "ajv": "^8.8.2"
    }

    preview = (WEB_ROOT / ".storybook" / "preview.tsx").read_text(encoding="utf-8")
    assert "../src/app/globals.css" in preview
    assert "../src/app/[locale]/globals.css" not in preview
    assert "/storybook-static/" in (WEB_ROOT / ".gitignore").read_text(
        encoding="utf-8"
    )


def test_vitest_lock_excludes_the_critical_advisory_ranges() -> None:
    package = _package_json()
    lock = json.loads((WEB_ROOT / "package-lock.json").read_text(encoding="utf-8"))

    declared_version = package["devDependencies"]["vitest"]
    locked_version = lock["packages"]["node_modules/vitest"]["version"]
    assert declared_version == "3.2.7"
    assert locked_version == "3.2.7"
    version = tuple(map(int, locked_version.split(".")))
    assert (3, 2, 6) <= version < (4, 0, 0) or version >= (4, 1, 0)


def test_web_dockerfiles_use_node_20_and_lockfile_installs() -> None:
    root_dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    web_dockerfile = (WEB_ROOT / "Dockerfile").read_text(encoding="utf-8")

    for content in (root_dockerfile, web_dockerfile):
        node_majors = re.findall(r"^FROM node:(\d+)", content, flags=re.MULTILINE)
        assert node_majors
        assert set(node_majors) == {"20"}
        assert not re.search(r"\bnpm install(?! -g\b)", content)

    assert "npm ci --include=dev --ignore-scripts" in root_dockerfile
    assert "npm ci --omit=dev --ignore-scripts" in root_dockerfile
    assert "npm ci --include=dev --ignore-scripts" in web_dockerfile


def test_prod_compose_treats_env_local_as_optional() -> None:
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    services_with_env_files = {
        name: service["env_file"]
        for name, service in compose["services"].items()
        if "env_file" in service
    }

    assert services_with_env_files
    for service_name, env_files in services_with_env_files.items():
        assert ".env" in env_files, service_name
        assert {"path": ".env.local", "required": False} in env_files, service_name


def test_web_docs_and_scripts_use_the_npm_contract() -> None:
    package = _package_json()
    scripts = package["scripts"]
    assert isinstance(scripts, dict)
    assert scripts["e2e:list"] == "node scripts/run-playwright.mjs test --list"
    assert scripts["e2e:smoke"] == (
        "node scripts/run-playwright.mjs test "
        "tests/e2e/health.endpoint.spec.ts --reporter=line"
    )
    assert "export" not in scripts
    assert "deploy:ssr" not in scripts

    active_docs = (
        WEB_ROOT / "README.md",
        WEB_ROOT / "CONFIG.md",
        WEB_ROOT / "CLOUDFLARE_DEPLOYMENT.md",
        WEB_ROOT / "INTEGRATION.md",
        WEB_ROOT / "STORYBOOK_SETUP.md",
        WEB_ROOT / "src" / "docs" / "quickstart_coding_agent.md",
    )
    for path in active_docs:
        content = path.read_text(encoding="utf-8").casefold()
        assert "pnpm" not in content, path
        assert "yarn" not in content, path
        assert not re.search(r"^npm run\b", content, flags=re.MULTILINE), path

    cloudflare = (WEB_ROOT / "CLOUDFLARE_DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "use Node 20" in cloudflare
    assert "Status: experimental and not verified." in cloudflare
    assert "wrangler pages deploy" not in cloudflare

    storybook = (WEB_ROOT / "STORYBOOK_SETUP.md").read_text(encoding="utf-8")
    assert "Build a local static preview" in storybook
    assert "Automated deployment via GitHub Actions" not in storybook
    assert "## Production Deployment" not in storybook

    config = (WEB_ROOT / "CONFIG.md").read_text(encoding="utf-8")
    compatibility = config.split("### Compatibility Variables", maxsplit=1)[1]
    compatibility = compatibility.split("## Troubleshooting", maxsplit=1)[0]
    for current_name in (
        "BR_KG_URL",
        "NEXT_PUBLIC_BR_KG_API",
        "BR_KG_HOST",
        "BR_KG_PORT",
    ):
        assert f"`{current_name}`" not in compatibility

    readme = (WEB_ROOT / "README.md").read_text(encoding="utf-8")
    for command in (
        "npm --prefix apps/web-ui ci",
        "npm --prefix apps/web-ui run dev",
        "npm --prefix apps/web-ui test",
        "npm --prefix apps/web-ui run build",
        "npm --prefix apps/web-ui run e2e:list",
        "npm --prefix apps/web-ui run e2e:smoke",
    ):
        assert command in readme


def test_default_playwright_smoke_matches_the_isolated_server() -> None:
    config = (WEB_ROOT / "playwright.config.ts").read_text(encoding="utf-8")
    smoke = (WEB_ROOT / "tests" / "e2e" / "health.endpoint.spec.ts").read_text(
        encoding="utf-8"
    )

    assert "const localBaseUrl = 'http://localhost:3002'" in config
    assert "NEXTAUTH_SECRET=br-playwright-local-secret" in config
    assert "JWT_SECRET_KEY=br-playwright-local-secret" in config
    assert "NEXTAUTH_URL=http://localhost:3002" in config
    assert "resolveE2EBaseUrl" in smoke
    assert "storageState: { cookies: [], origins: [] }" in smoke
    assert "/health" in smoke
    assert "content-type" in smoke
    assert "landing-page" in smoke
    assert "Brain Researcher" in smoke

    default_e2e_files = (WEB_ROOT / "tests" / "e2e").glob("*.ts")
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in default_e2e_files
        if "http://localhost:3000" in path.read_text(encoding="utf-8")
    ]
    assert not offenders


def test_web_env_example_is_the_only_general_web_template() -> None:
    example = (WEB_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "optional" in example.casefold()
    assert "NEXT_PUBLIC_USE_API_PROXY=true" in example
    assert "NEXT_PUBLIC_ORCHESTRATOR_URL=http://localhost:3001" in example
    assert "NEXT_PUBLIC_API_URL" not in example
    assert not (WEB_ROOT / ".env.local.example").exists()
    assert (WEB_ROOT / ".env.test.template").exists()
