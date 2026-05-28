from __future__ import annotations

import json
from pathlib import Path

from brain_researcher.services.orchestrator.job_store import JobRecord, JobState
from brain_researcher.services.orchestrator.observation import load_or_build_observation


def test_observation_persists_research_episode_artifacts(tmp_path: Path):
    run_dir = tmp_path
    payload = {
        "plan": {
            "plan_id": "plan-episode-1",
            "query": "Should the study proceed to execution?",
            "chosen_tool": "embedding_autoresearch",
            "selection_reason": "Need a final review-oriented analysis.",
            "success_criteria": ["Pick one next step"],
            "candidates": [
                {
                    "tool_id": "embedding_autoresearch",
                    "tool_name": "Embedding Autoresearch",
                    "score": 0.88,
                    "reason": "Best fit for the unresolved evidence gap.",
                }
            ],
        }
    }
    (run_dir / "session_snapshot.json").write_text(
        json.dumps({"goal": "Decide whether the episode is ready to proceed"}),
        encoding="utf-8",
    )

    record = JobRecord(
        job_id="job-episode-1",
        kind="plan",
        payload_json=json.dumps(payload),
        state=JobState.SUCCEEDED.value,
        run_dir=str(run_dir),
        run_id="run-episode-1",
        session_id="session-episode-1",
    )

    spec = load_or_build_observation(record)
    assert spec is not None
    assert (run_dir / "research_episode.json").exists()
    assert (run_dir / "option_set.json").exists()
    assert (run_dir / "commitment.json").exists()
    assert spec.files.research_episode_json == "research_episode.json"
    assert spec.files.option_set_json == "option_set.json"
    assert spec.files.commitment_json == "commitment.json"
    assert spec.run_card is not None
    assert spec.run_card.provenance["episode_artifacts"]["research_episode"] == (
        "research_episode.json"
    )
    assert (
        spec.run_card.provenance["episode_artifacts"]["commitment"] == "commitment.json"
    )

    episode = json.loads(
        (run_dir / "research_episode.json").read_text(encoding="utf-8")
    )
    assert (
        episode["research_question"] == "Decide whether the episode is ready to proceed"
    )
    assert episode["option_set"]["selected_option_id"] == "embedding_autoresearch"
    assert episode["commitments"][0]["option_id"] == "embedding_autoresearch"
