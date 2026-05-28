"""Real-data smoke placeholder for workflow_hypothesis_candidate_cards.

This test is marked `realdata` (skipped by default) and uses deterministic
mocked novelty responses to keep runtime stable when executed locally.
"""

from __future__ import annotations

import pytest

from brain_researcher.services.tools.runner import execute_tool


@pytest.mark.realdata
@pytest.mark.timeout(90)
def test_workflow_hypothesis_candidate_cards_smoke(monkeypatch: pytest.MonkeyPatch):
    def _fake_find_structural_leverage(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "structural_leverage",
            "items": [
                {
                    "kg_id": "node:candidate_a",
                    "label": "Candidate A",
                    "leverage_score": 0.91,
                }
            ],
        }

    def _fake_sample_ood_hypothesis(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "ood_hypothesis_sampling",
            "hypotheses": [
                {
                    "rank": 1,
                    "seed_kg_id": "node:seed",
                    "candidate_kg_id": "node:candidate_a",
                    "statement": "Seed node may couple with candidate A under OOD settings.",
                    "relation_hint": "ASSOCIATED_WITH",
                    "novelty_score": 0.82,
                    "ood_score": 0.91,
                }
            ],
        }

    def _fake_detect_contradiction_motifs(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "contradiction_motifs",
            "motifs": [
                {
                    "publication_id": "pub:123",
                    "publication_label": "Example Contradiction Paper",
                    "support_count": 3,
                    "conflict_count": 2,
                    "motif_score": 0.71,
                    "contradiction_density": 0.4,
                }
            ],
        }

    def _fake_detect_topology_shifts(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "mode": "proposal",
            "proposals": [
                {
                    "edge": {
                        "source_id": "node:seed",
                        "target_id": "node:candidate_a",
                        "rel_type": "ASSOCIATED_WITH",
                    },
                    "delta": 0.22,
                    "target_weight": 0.83,
                }
            ],
        }

    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.find_structural_leverage",
        _fake_find_structural_leverage,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.sample_ood_hypothesis",
        _fake_sample_ood_hypothesis,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_contradiction_motifs",
        _fake_detect_contradiction_motifs,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.kg_novelty_tools.query_service.detect_topology_shifts",
        _fake_detect_topology_shifts,
    )

    res = execute_tool(
        "workflow_hypothesis_candidate_cards",
        {
            "query": "fmri based image decoding",
            "seed_kg_ids": ["node:seed"],
            "top_k": 10,
            "n_samples": 1,
            "taste_mode": "novelty_first",
        },
    )
    assert res.status == "success", res.error
    assert res.data and res.data.get("workflow") == "workflow_hypothesis_candidate_cards"
    assert "leverage" in res.data.get("steps", {})
    assert "ood_sampling" in res.data.get("steps", {})
    assert "contradiction_scan" in res.data.get("steps", {})
    assert "topology_shift_scan" in res.data.get("steps", {})
