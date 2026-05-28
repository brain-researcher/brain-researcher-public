from __future__ import annotations

from brain_researcher.services.tools.grandmaster.loader import _lookup_path


def test_lookup_path_supports_explicit_step_fallback() -> None:
    root = {
        "steps": {
            "verify_sampled_hypotheses": {
                "data": {
                    "result": {},
                }
            }
        }
    }

    assert (
        _lookup_path(
            root,
            "steps.verify_sampled_hypotheses.data.result.evidence_items:-[]",
        )
        == []
    )


def test_lookup_path_keeps_existing_input_fallback_behavior() -> None:
    root = {"inputs": {}}

    assert _lookup_path(root, "inputs.top_k:-5") == 5
