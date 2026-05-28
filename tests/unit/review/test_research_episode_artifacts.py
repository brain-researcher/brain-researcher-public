from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.core.contracts import (
    CommitmentRecordV1,
    OptionSetV1,
    ResearchEpisodeV1,
)
from brain_researcher.services.review.bundle_builder import build_artifact_review_bundle
from brain_researcher.services.review.research_episode_artifacts import (
    build_commitments_from_plan_payload,
    build_option_set_from_plan_payload,
    build_research_episode_from_context,
)


def test_build_option_set_and_research_episode_from_plan_payload():
    plan_payload = {
        "plan_id": "plan-123",
        "query": "Should we run one more robustness check?",
        "chosen_tool": "embedding_autoresearch",
        "selection_reason": "Need a final sensitivity check.",
        "success_criteria": ["Choose a path", "Record the evidence gap"],
        "candidates": [
            {
                "tool_id": "embedding_autoresearch",
                "tool_name": "Embedding Autoresearch",
                "score": 0.91,
                "reason": "Best fit for the current evidence gap.",
                "preflight_ok": True,
            },
            {
                "tool_id": "workflow_preprocessing_qc",
                "tool_name": "Preprocessing QC",
                "score": 0.44,
                "reason": "Useful fallback if evidence remains weak.",
                "preflight_ok": False,
            },
        ],
        "mask_reasons": [{"code": "BUDGET_WARN", "message": "expensive"}],
    }

    option_set = build_option_set_from_plan_payload(plan_payload)
    assert isinstance(option_set, OptionSetV1)
    assert option_set.selected_option_id == "embedding_autoresearch"
    assert len(option_set.options) == 2
    assert option_set.options[1].risks == ["preflight not ok"]
    commitments = build_commitments_from_plan_payload(
        plan_payload,
        run_id="run-123",
        state="succeeded",
        option_set=option_set,
    )
    assert len(commitments) == 1
    assert isinstance(commitments[0], CommitmentRecordV1)
    assert commitments[0].option_id == "embedding_autoresearch"
    assert commitments[0].fulfilled is True

    episode = build_research_episode_from_context(
        run_id="run-123",
        session_id="session-123",
        state="running",
        plan_payload=plan_payload,
        session_snapshot={"goal": "Decide if the episode is ready to proceed"},
        option_set=option_set,
        commitments=commitments,
    )
    assert isinstance(episode, ResearchEpisodeV1)
    assert episode.episode_id == "episode:plan-123"
    assert episode.research_question == "Decide if the episode is ready to proceed"
    assert episode.status == "active"
    assert episode.option_set is not None
    assert episode.success_criteria == ["Choose a path", "Record the evidence gap"]
    assert episode.commitments[0].approval_level == "confirm"


def test_bundle_builder_surfaces_episode_artifacts(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "steps": [
                    {
                        "tool_id": "embedding_autoresearch",
                        "params": {"task": "theory of mind"},
                        "step_id": "s1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "research_episode.json").write_text(
        json.dumps(
            {
                "schema_version": "research-episode-v1",
                "episode_id": "episode:plan-123",
                "run_id": "run-123",
                "status": "active",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "option_set.json").write_text(
        json.dumps(
            {
                "schema_version": "option-set-v1",
                "options": [
                    {"option_id": "embedding_autoresearch", "label": "Embedding"}
                ],
                "selected_option_id": "embedding_autoresearch",
            }
        ),
        encoding="utf-8",
    )

    bundle = build_artifact_review_bundle("run-123", run_dir=run_dir)

    assert (
        bundle.observed_artifacts["research_episode"]["episode_id"]
        == "episode:plan-123"
    )
    assert bundle.observed_artifacts["option_set"]["selected_option_id"] == (
        "embedding_autoresearch"
    )
