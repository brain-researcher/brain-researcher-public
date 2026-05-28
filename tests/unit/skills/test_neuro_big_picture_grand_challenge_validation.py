from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "neuro-big-picture" / "scripts" / "score_insights.py"
SCHEMA = ROOT / "skills" / "neuro-big-picture" / "references" / "output_schemas.json"


def _run_scorer(payload: dict, mode: str, tmp_path: Path, gc_path: Path) -> dict:
    input_path = tmp_path / f"input-{mode}.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    cmd = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(input_path),
        "--mode",
        mode,
        "--grand-challenges",
        str(gc_path),
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def test_scorer_flags_unknown_and_invalid_gc_ids(tmp_path: Path) -> None:
    gc_catalog = {
        "version": "1.0",
        "last_updated": "2026-03-03",
        "grand_challenges": {
            "GC1": {"title": "A"},
            "GC2": {"title": "B"},
        },
    }
    gc_path = tmp_path / "grand_challenges.yaml"
    gc_path.write_text(yaml.safe_dump(gc_catalog), encoding="utf-8")

    payload = {
        "query_profile": {"idea_text": "test", "recency_days": 120},
        "sources": [
            {
                "source_id": "s1",
                "name": "Source 1",
                "tier": "A",
                "channel": "blog",
                "capture_method": "web",
                "authority_score": 0.9,
                "noise_risk": 0.1,
            }
        ],
        "insight_items": [
            {
                "item_id": "i1",
                "source_id": "s1",
                "title": "test item",
                "url": "https://example.org/1",
                "date": "2026-02-20",
                "summary": "summary",
                "stance": "supports",
                "mapped_topics": ["topic"],
                "mapped_grand_challenges": ["GC2", "GC99", "GCA", "GC_10", 123],
                "relevance": 0.9,
                "authority": 0.9,
                "freshness": 0.9,
                "signal_to_noise": 0.9,
                "capturability": 0.9,
                "novelty": 0.9,
                "noise_risk": 0.1,
                "evidence_count": 2,
            }
        ],
    }

    result = _run_scorer(payload=payload, mode="broad", tmp_path=tmp_path, gc_path=gc_path)

    assert result["summary"]["grand_challenge_catalog_loaded"] is True
    assert result["summary"]["recognized_grand_challenge_ids"] == ["GC2"]
    assert result["summary"]["unknown_grand_challenge_ids"] == ["GC99"]
    assert result["summary"]["invalid_grand_challenge_ids"] == ["123", "GCA", "GC_10"]


def test_schema_uses_extensible_gc_pattern_not_fixed_enum() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    gc_items = (
        payload["properties"]["consult_neuro_insights_result"]["properties"]["insight_items"]["items"][
            "properties"
        ]["mapped_grand_challenges"]["items"]
    )

    assert gc_items["pattern"] == "^GC[0-9]+$"
    assert "enum" not in gc_items
