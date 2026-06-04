from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "apps/web-ui/README-real-pipeline.md": ("cd apps/web-ui",),
    "apps/web-ui/INTEGRATION.md": (
        "`apps/web-ui/.env.local`",
        "cd apps/web-ui",
    ),
    "apps/web-ui/TESTING_3D_VIEWER.md": (
        "br serve agent",
        "br serve kg",
        "br serve web",
        "cd apps/web-ui",
        "http://localhost:3000/api/demo/peaks/",
        "http://localhost:3000/api/demo/real-evidence/",
    ),
    "apps/web-ui/CLOUDFLARE_DEPLOYMENT.md": ("Root directory: apps/web-ui",),
    "apps/web-ui/STORYBOOK_SETUP.md": ("apps/web-ui/",),
    "apps/web-ui/CHART_COMPONENTS_DEMO.md": (
        "cd apps/web-ui",
        "npm run dev -- --port 3002",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "apps/web-ui/README-real-pipeline.md": ("cd brain_researcher/services/web_ui",),
    "apps/web-ui/INTEGRATION.md": (
        "`services/web_ui/.env.local`",
        "cd brain_researcher/services/web_ui",
    ),
    "apps/web-ui/TESTING_3D_VIEWER.md": (
        "scripts/launch_services_clean.sh",
        "cd brain_researcher/services/web_ui",
        "http://localhost:3101/api/demo/peaks/",
        "http://localhost:3101/api/demo/real-evidence/",
    ),
    "apps/web-ui/CLOUDFLARE_DEPLOYMENT.md": (
        "Root directory: brain_researcher/services/web_ui",
    ),
    "apps/web-ui/STORYBOOK_SETUP.md": ("brain_researcher/services/web_ui/",),
    "apps/web-ui/CHART_COMPONENTS_DEMO.md": (
        "/app/brain_researcher/brain_researcher/services/web_ui",
    ),
}


def test_active_service_docs_use_canonical_paths() -> None:
    for relpath, expected_substrings in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in expected_substrings:
            assert needle in text, f"Missing expected text in {relpath}: {needle}"


def test_active_service_docs_do_not_reintroduce_legacy_paths() -> None:
    for relpath, forbidden_substrings in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            assert needle not in text, f"Found stale text in {relpath}: {needle}"
