from __future__ import annotations

from brain_researcher.services.agent.wow_principle_controller import (
    rank_wow_candidates,
    score_wow_candidate,
)


def test_score_wow_candidate_derives_non_bridge_explanation_from_assumption():
    scored = score_wow_candidate(
        {
            "title": "Structure is sufficient prior",
            "main_assumption_text": "Precise weights are required before meaningful simulation",
            "contradiction_score": 0.75,
            "challengeability_score": 0.80,
            "minimal_test": "Fit two models with and without weight learning.",
            "falsifier": "Reject if the topology-only model fails.",
            "publication_count": 4,
            "supporting_nodes": [{"node_type": "Publication"}, {"node_type": "Dataset"}],
            "touched_domains": ["connectomics", "simulation"],
        }
    )

    assert scored["vetoed"] is False
    assert scored["wow_score"] > 0.0
    assert (
        scored["why_this_is_not_just_a_bridge"]
        == "This challenges the field default assumption: Precise weights are required before meaningful simulation."
    )


def test_score_wow_candidate_vetoes_execution_gap_only_bridge():
    scored = score_wow_candidate(
        {
            "title": "Bridge-only idea",
            "bridge_score": 0.92,
            "minimal_test": "Run the pipeline once.",
            "publication_count": 1,
        }
    )

    assert scored["execution_gap_only"] is True
    assert scored["vetoed"] is True
    assert scored["wow_score"] == 0.0


def test_rank_wow_candidates_places_non_vetoed_before_bridge_candidate():
    ranked = rank_wow_candidates(
        [
            {
                "title": "Bridge-only idea",
                "bridge_score": 0.88,
                "minimal_test": "Run the pipeline once.",
            },
            {
                "title": "Assumption crack",
                "contradiction_score": 0.72,
                "challengeability_score": 0.81,
                "transfer_score": 0.55,
                "minimal_test": "Run the decisive comparison.",
                "falsifier": "Reject if the intervention shows no change.",
                "publication_count": 5,
                "dataset_count": 2,
                "supporting_nodes": [
                    {"node_type": "Publication"},
                    {"node_type": "Dataset"},
                    {"node_type": "Method"},
                ],
                "touched_domains": ["imaging", "simulation", "theory"],
                "contradiction_signature": "support-vs-refutation cluster around the same claim",
            },
        ]
    )

    assert ranked[0]["title"] == "Assumption crack"
    assert ranked[1]["title"] == "Bridge-only idea"
    assert ranked[0]["rank"] == 1
    assert ranked[1]["rank"] == 2
