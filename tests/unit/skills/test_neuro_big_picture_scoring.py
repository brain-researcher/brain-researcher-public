from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "skills" / "neuro-big-picture" / "scripts" / "score_insights.py"


def _run_scorer(payload: dict, mode: str, tmp_path: Path, gc_path: Path | None = None) -> dict:
    input_path = tmp_path / f"input-{mode}.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    cmd = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(input_path),
        "--mode",
        mode,
    ]
    if gc_path is not None:
        cmd.extend(["--grand-challenges", str(gc_path)])
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def test_scoring_populates_breakdown_and_orders_results(tmp_path: Path) -> None:
    payload = {
        "query_profile": {
            "idea_text": "cross-subject fMRI alignment with contrastive objective",
            "recency_days": 120,
            "perspectives": ["neuroai_alignment", "method_rigor"],
        },
        "sources": [
            {
                "source_id": "transmitter",
                "name": "The Transmitter",
                "tier": "A",
                "channel": "newsletter",
                "capture_method": "web",
                "authority_score": 0.92,
                "noise_risk": 0.12,
            },
            {
                "source_id": "x_expert_stream",
                "name": "Expert X Stream",
                "tier": "C",
                "channel": "social",
                "capture_method": "manual",
                "authority_score": 0.65,
                "noise_risk": 0.8,
            },
        ],
        "insight_items": [
            {
                "item_id": "i1",
                "source_id": "transmitter",
                "title": "Cross-subject scaling discussion",
                "url": "https://example.org/t1",
                "date": "2026-02-20",
                "summary": "Editorial perspective on transfer and scanner shift.",
                "stance": "supports",
                "mapped_topics": ["cross-subject", "domain shift"],
                "mapped_grand_challenges": ["GC1"],
                "relevance": 0.9,
                "authority": 0.9,
                "freshness": 0.9,
                "signal_to_noise": 0.85,
                "capturability": 0.8,
                "novelty": 0.7,
                "noise_risk": 0.15,
                "evidence_count": 2,
            },
            {
                "item_id": "i2",
                "source_id": "x_expert_stream",
                "title": "Speculative take",
                "url": "https://example.org/t2",
                "date": "2026-02-28",
                "summary": "Community speculation without full validation.",
                "stance": "mixed",
                "mapped_topics": ["contrastive learning"],
                "mapped_grand_challenges": ["GC1", "GC10"],
                "relevance": 0.7,
                "authority": 0.5,
                "freshness": 0.95,
                "signal_to_noise": 0.3,
                "capturability": 0.4,
                "novelty": 0.9,
                "noise_risk": 0.85,
                "evidence_count": 1,
            },
        ],
    }

    result = _run_scorer(payload=payload, mode="broad", tmp_path=tmp_path)

    assert result["summary"]["mode"] == "broad"
    assert len(result["insight_items"]) == 2
    assert len(result["sources"]) == 2

    top_item = result["insight_items"][0]
    second_item = result["insight_items"][1]

    assert top_item["item_score"] >= second_item["item_score"]
    assert "score_breakdown" in top_item
    assert "exploration_bonus" in second_item["score_breakdown"]
    assert "recognized_grand_challenge_ids" in result["summary"]
    assert "GC10" in result["summary"]["recognized_grand_challenge_ids"]
    assert result["summary"]["unknown_grand_challenge_ids"] == []
    assert result["summary"]["invalid_grand_challenge_ids"] == []


def test_strict_mode_penalizes_noisy_items_more_than_broad(tmp_path: Path) -> None:
    payload = {
        "query_profile": {"idea_text": "latent alignment", "recency_days": 120},
        "sources": [
            {
                "source_id": "x_expert_stream",
                "name": "Expert X Stream",
                "tier": "C",
                "channel": "social",
                "capture_method": "manual",
                "authority_score": 0.65,
                "noise_risk": 0.9,
            }
        ],
        "insight_items": [
            {
                "item_id": "noisy",
                "source_id": "x_expert_stream",
                "title": "High-noise speculative claim",
                "url": "https://example.org/noisy",
                "date": "2026-02-25",
                "summary": "Unverified but trending claim.",
                "stance": "mixed",
                "mapped_topics": ["alignment"],
                "mapped_grand_challenges": ["GC2"],
                "relevance": 0.8,
                "authority": 0.5,
                "freshness": 0.9,
                "signal_to_noise": 0.2,
                "capturability": 0.3,
                "novelty": 0.95,
                "noise_risk": 0.9,
                "evidence_count": 1,
            }
        ],
    }

    broad = _run_scorer(payload=payload, mode="broad", tmp_path=tmp_path)
    strict = _run_scorer(payload=payload, mode="strict", tmp_path=tmp_path)

    broad_score = broad["insight_items"][0]["item_score"]
    strict_score = strict["insight_items"][0]["item_score"]

    assert strict_score < broad_score
