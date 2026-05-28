from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs" / "planning" / "active_tracks.yaml"
ROADMAP = ROOT / "docs" / "planning" / "roadmap.md"

TRACK_ID_RX = re.compile(r"^[a-z][a-z0-9_]*$")
ALLOWED_PRIORITIES = {"P0", "P1", "P2"}
ALLOWED_STATUSES = {"active", "at_risk", "blocked"}
REQUIRED_TRACK_KEYS = {
    "track_id",
    "title",
    "area",
    "priority",
    "status",
    "owner",
    "target_date",
    "summary",
    "next_milestone",
    "dependencies",
    "deliverables",
    "exit_criteria",
}


def _load_registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}


def test_active_tracks_registry_structure() -> None:
    payload = _load_registry()

    assert payload["version"] == "1.0"
    assert payload["program"] == "brain_researcher"
    assert payload["source_doc"] == "docs/planning/roadmap.md"
    assert payload["review_cadence"] == "weekly"

    as_of = date.fromisoformat(payload["as_of"])
    assert REGISTRY.exists()
    assert ROADMAP.exists()

    tracks = payload["active_tracks"]
    assert isinstance(tracks, list)
    assert len(tracks) >= 3

    track_ids: list[str] = []
    for track in tracks:
        assert REQUIRED_TRACK_KEYS.issubset(track)

        track_id = track["track_id"]
        assert isinstance(track_id, str) and TRACK_ID_RX.fullmatch(track_id)
        assert track_id not in track_ids
        track_ids.append(track_id)

        assert isinstance(track["title"], str) and track["title"].strip()
        assert isinstance(track["area"], str) and track["area"].strip()
        assert track["priority"] in ALLOWED_PRIORITIES
        assert track["status"] in ALLOWED_STATUSES
        assert isinstance(track["owner"], str) and track["owner"].strip()
        assert isinstance(track["summary"], str) and track["summary"].strip()
        assert (
            isinstance(track["next_milestone"], str) and track["next_milestone"].strip()
        )

        target_date = date.fromisoformat(track["target_date"])
        assert target_date >= as_of

        dependencies = track["dependencies"]
        assert isinstance(dependencies, list)
        assert all(isinstance(dep, str) and dep.strip() for dep in dependencies)

        deliverables = track["deliverables"]
        assert isinstance(deliverables, list) and deliverables
        assert all(isinstance(item, str) and item.strip() for item in deliverables)

        exit_criteria = track["exit_criteria"]
        assert isinstance(exit_criteria, list) and exit_criteria
        assert all(isinstance(item, str) and item.strip() for item in exit_criteria)

    track_id_set = set(track_ids)
    for track in tracks:
        dependencies = set(track["dependencies"])
        assert track["track_id"] not in dependencies
        assert dependencies <= track_id_set

    assert tracks[0]["track_id"] == "hypothesis_quality"
    assert tracks[0]["priority"] == "P0"
    novelty_track = next(
        track for track in tracks if track["track_id"] == "novelty_architecture"
    )
    assert novelty_track["status"] == "blocked"
    assert novelty_track["dependencies"] == ["hypothesis_quality"]


def test_roadmap_mentions_registry_tracks() -> None:
    payload = _load_registry()
    roadmap_text = ROADMAP.read_text(encoding="utf-8")

    assert "As of March 10, 2026." in roadmap_text
    assert "configs/planning/active_tracks.yaml" in roadmap_text

    for track in payload["active_tracks"]:
        assert track["track_id"] in roadmap_text
        assert track["title"] in roadmap_text
