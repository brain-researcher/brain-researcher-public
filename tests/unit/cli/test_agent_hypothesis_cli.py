from __future__ import annotations

from typer.testing import CliRunner

from brain_researcher.cli.main import app

runner = CliRunner()


def test_agent_hypothesis_json_includes_novelty_calibration(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_api_post_sync(path, *, json_data=None, timeout=30.0):
        assert path == "/run"
        assert json_data["tool"] == "workflow_hypothesis_candidate_cards"
        return {"job_id": "job_demo"}

    def fake_wait_for_job_completion(job_id: str, poll_interval: int = 2):
        assert job_id == "job_demo"
        assert poll_interval == 2
        return {
            "state": "succeeded",
            "result": {
                "candidate_cards": [
                    {
                        "card_id": "card_001",
                        "title": "Energy-limited regulation",
                        "hypothesis": "MDD network recovery reflects bioenergetic reserve.",
                        "minimal_discriminating_test": "Compare recovery slope by fatigue subtype.",
                        "falsifier_hint": "No subgroup-specific recovery deficit appears.",
                        "taste_axis": "controlled_ood_search",
                    }
                ],
                "novelty_calibration_questions": [
                    {
                        "id": "ncq_01",
                        "targets_card_id": "card_001",
                        "claim_surface": "mechanistic_framing",
                        "question": "Can you name a direct MDD fMRI precedent?",
                    }
                ],
                "novelty_calibration_meta": {
                    "total_questions": 1,
                    "dimensions_covered": ["mechanistic_framing"],
                    "source": "candidate_cards_v1",
                    "schema_version": "v1",
                },
            },
        }

    monkeypatch.setattr(
        "brain_researcher.cli.commands.agent_commands.api_post_sync",
        fake_api_post_sync,
    )
    monkeypatch.setattr(
        "brain_researcher.cli.commands.agent_commands.wait_for_job_completion",
        fake_wait_for_job_completion,
    )
    monkeypatch.setattr(
        "brain_researcher.cli.commands.agent_commands.console.print",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "brain_researcher.cli.commands.agent_commands.console.print_json",
        lambda *, data, **kwargs: captured.setdefault("data", data),
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "hypothesis",
            "demo novelty query",
            "--format",
            "json",
            "--top",
            "1",
        ],
    )

    assert result.exit_code == 0
    payload = captured["data"]
    assert payload["candidate_cards"][0]["card_id"] == "card_001"
    assert payload["novelty_calibration_questions"] == [
        {
            "id": "ncq_01",
            "targets_card_id": "card_001",
            "claim_surface": "mechanistic_framing",
            "question": "Can you name a direct MDD fMRI precedent?",
        }
    ]
    assert payload["novelty_calibration_meta"] == {
        "total_questions": 1,
        "dimensions_covered": ["mechanistic_framing"],
        "source": "candidate_cards_v1",
        "schema_version": "v1",
    }
