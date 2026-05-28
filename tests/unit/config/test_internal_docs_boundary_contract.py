from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {
    "docs/internal/AUTH_WIRING.md": (
        "Internal implementation note:",
        "internal wiring reference",
        "current split-service",
        "apps/web-ui/.env.local",
        "apps/web-ui/src/app/api/auth/[...nextauth]/route.ts",
        "apps/web-ui/src/app/api/chat/route.ts",
    ),
    "docs/internal/SUPABASE_CONTROL_PLANE.md": (
        "Internal design note:",
        "internal control-plane design/reference",
        "not the public setup",
        "production deployment",
    ),
    "docs/archive/LLM_B_HANDOFF_UI043.md": (
        "Historical handoff note:",
        "historical context",
        "do not treat it as the current source of truth",
    ),
}

FORBIDDEN_SUBSTRINGS = {
    "docs/internal/AUTH_WIRING.md": (
        "services/web_ui/.env.local",
        "services/web_ui/src/app/api/auth/[...nextauth]/route.ts",
        "services/web_ui/src/app/api/chat/route.ts",
    ),
}


def test_internal_and_historical_docs_are_explicitly_marked() -> None:
    for relpath, required in REQUIRED_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in required:
            assert (
                needle in text
            ), f"Missing expected boundary text in {relpath}: {needle}"


def test_internal_docs_do_not_reintroduce_retired_web_ui_paths() -> None:
    for relpath, forbidden in FORBIDDEN_SUBSTRINGS.items():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"Found retired path in {relpath}: {needle}"
