from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REQUIRED_SUBSTRINGS = {}

FORBIDDEN_SUBSTRINGS = {}


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
