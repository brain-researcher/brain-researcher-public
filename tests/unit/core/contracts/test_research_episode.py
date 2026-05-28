from __future__ import annotations

import pytest
from pydantic import ValidationError

from brain_researcher.core.contracts import (
    ClaimReportV1,
    ClaimUpdateV1,
    CommitmentRecordV1,
    EpisodeOptionV1,
    EvidenceGateVerdictV1,
    OptionSetV1,
    ResearchEpisodeV1,
)


def test_research_episode_roundtrip():
    option_a = EpisodeOptionV1(
        option_id="opt-a",
        label="Run a sensitivity sweep",
        rationale="Probe whether the result depends on model choice.",
        risks=["longer runtime"],
        confidence=0.7,
    )
    option_b = EpisodeOptionV1(option_id="opt-b", label="Ship the current result")
    episode = ResearchEpisodeV1(
        episode_id="episode-1",
        run_id="run-1",
        session_id="session-1",
        title="Scientific episode one",
        research_question="What is the next evidence-gated step?",
        objective="Decide the next evidence-gated step.",
        estimand="Whether the current result is robust enough to proceed",
        success_criteria=["Select a next step", "Record the evidence gap"],
        stop_conditions=["No direct evidence available"],
        status="active",
        option_set=OptionSetV1(
            options=[option_a, option_b],
            selected_option_id="opt-a",
            selection_rationale="Need one more check before committing.",
        ),
        evidence_gate=EvidenceGateVerdictV1(
            decision="collect_more",
            summary="Missing direct evidence for the selected path.",
            required_evidence_ids=["ev-1", "ev-2"],
            missing_evidence_ids=["ev-2"],
            blockers=["No replication evidence"],
            confidence=0.6,
        ),
        commitments=[
            CommitmentRecordV1(
                commitment_id="c-1",
                option_id="opt-a",
                commitment_text="Run the sensitivity sweep before finalizing.",
                approval_level="confirm",
                approved_by="agent",
                allowed_tools=["embedding_autoresearch"],
                stop_conditions=["If evidence gate returns stop"],
                fulfilled=False,
                owner="agent",
            )
        ],
        claim_report=ClaimReportV1(
            report_id="report-1",
            claims=[],
            summary="No claims finalized yet.",
            unresolved_questions=["Do we have replication evidence?"],
        ),
        claim_updates=[
            ClaimUpdateV1(
                claim_id="claim-1",
                canonical_claim_id="canonical:claim-1",
                action="support",
                claim_text="The effect remains stable under the current checks.",
                verdict="supported",
                confidence=0.9,
                evidence_ids=["ev-1"],
            )
        ],
        context={"domain": "neuroscience"},
    )

    dumped = episode.model_dump()
    restored = ResearchEpisodeV1.model_validate(dumped)

    assert restored.schema_version == "research-episode-v1"
    assert restored.option_set is not None
    assert restored.option_set.selected_option_id == "opt-a"
    assert restored.evidence_gate is not None
    assert restored.evidence_gate.decision == "collect_more"
    assert restored.commitments[0].commitment_id == "c-1"
    assert restored.commitments[0].approval_level == "confirm"
    assert restored.claim_report is not None
    assert restored.claim_report.report_id == "report-1"
    assert restored.claim_report.episode_id == "episode-1"
    assert restored.claim_updates[0].claim_id == "claim-1"
    assert restored.claim_updates[0].action == "support"
    assert restored.research_question == "What is the next evidence-gated step?"


def test_option_set_rejects_unknown_selection():
    with pytest.raises(ValidationError):
        OptionSetV1(
            options=[EpisodeOptionV1(option_id="opt-a", label="A")],
            selected_option_id="opt-b",
        )


def test_confidence_validation_applies_to_gate_and_update():
    with pytest.raises(ValidationError):
        EvidenceGateVerdictV1(decision="go", confidence=1.2)

    with pytest.raises(ValidationError):
        ClaimUpdateV1(claim_id="claim-1", confidence=-0.1)
