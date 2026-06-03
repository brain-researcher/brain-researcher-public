from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_TRACKED_WEB_PATTERNS = (
    "apps/web-ui/.vercel/",
    "apps/web-ui/out/",
    "apps/web-ui/test-results/",
    "apps/web-ui/test-artifacts/",
)
FORBIDDEN_TRACKED_WEB_PATHS = {
    "apps/web-ui/index.html",
}
FORBIDDEN_TRACKED_WEB_BASENAMES = {
    "tsconfig.tsbuildinfo",
    ".env.local",
    "br_kg_performance.db",
    "login-before.png",
    "playwright-pipeline-dev.png",
    "playwright-pipeline.png",
}
FORBIDDEN_TRACKED_WEB_PREFIXES = (
    "client_secret_",
)


def test_tracked_web_test_results_artifact_is_absent() -> None:
    artifact = REPO_ROOT / "apps/web-ui/test-results/html/index.html"
    assert not artifact.exists(), (
        "Generated web test-results artifacts must not be tracked in the repo: "
        f"{artifact.relative_to(REPO_ROOT)}"
    )


def test_web_generated_artifacts_and_local_secrets_are_not_tracked() -> None:
    result = subprocess.run(
        ["git", "ls-files", "apps/web-ui"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    offenders = [
        relpath
        for relpath in tracked
        if relpath in FORBIDDEN_TRACKED_WEB_PATHS
        or any(relpath.startswith(pattern) for pattern in FORBIDDEN_TRACKED_WEB_PATTERNS)
        or Path(relpath).name in FORBIDDEN_TRACKED_WEB_BASENAMES
        or any(Path(relpath).name.startswith(prefix) for prefix in FORBIDDEN_TRACKED_WEB_PREFIXES)
    ]
    assert not offenders, (
        "Generated web artifacts and local-secret files must not be tracked: "
        f"{offenders}"
    )



def test_legacy_web_build_adapter_index_is_absent() -> None:
    stub = REPO_ROOT / "apps/web-ui/index.html"
    assert not stub.exists(), (
        "Legacy web build-adapter stub must not remain in the tracked app root: "
        f"{stub.relative_to(REPO_ROOT)}"
    )
