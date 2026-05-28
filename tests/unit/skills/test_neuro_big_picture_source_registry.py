from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "skills" / "neuro-big-picture" / "references" / "source_registry.yaml"
SCRIPT = ROOT / "skills" / "neuro-big-picture" / "scripts" / "check_sources.py"

ALLOWED_TIERS = {"A", "B", "C"}
ALLOWED_CHANNELS = {
    "blog",
    "newsletter",
    "podcast",
    "community",
    "social",
    "journal_editorial",
}
ALLOWED_CAPTURE_METHODS = {"rss", "api", "web", "mirror", "manual"}


def test_source_registry_fields_and_ranges() -> None:
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))

    assert payload["version"] == "1.0"
    assert isinstance(payload["sources"], dict)
    assert len(payload["sources"]) >= 10

    for source_id, source in payload["sources"].items():
        assert isinstance(source_id, str) and source_id
        assert source["tier"] in ALLOWED_TIERS
        assert source["channel"] in ALLOWED_CHANNELS
        assert source["capture_method"] in ALLOWED_CAPTURE_METHODS

        assert isinstance(source["authority_score"], (int, float))
        assert 0 <= float(source["authority_score"]) <= 1
        assert isinstance(source["noise_risk"], (int, float))
        assert 0 <= float(source["noise_risk"]) <= 1

        urls = source["urls"]
        assert isinstance(urls, dict)
        assert any(isinstance(value, str) and value.startswith("http") for value in urls.values())


def test_check_sources_skip_network_success() -> None:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--registry",
        str(REGISTRY),
        "--skip-network",
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    result = json.loads(completed.stdout)

    assert result["summary"]["valid_registry"] is True
    assert result["summary"]["skip_network"] is True
    assert result["summary"]["source_count"] >= 10
    assert result["validation_errors"] == []
