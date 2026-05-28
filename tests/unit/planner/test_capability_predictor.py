from __future__ import annotations

import pytest

from brain_researcher.services.agent.planner.capability_predictor import (
    predict_capabilities,
    score_tool_capability_match,
)


class _Tool:
    def __init__(self, tool_id: str, capabilities: list[str], intents: list[str] | None = None) -> None:
        self.id = tool_id
        self.name = tool_id
        self.package = "python"
        self.capabilities = capabilities
        self.intents = intents or []


def test_predict_capabilities_uses_crosswalk_and_query_understanding():
    prediction = predict_capabilities(
        query="Run quality control workflow: MRIQC on all subjects and flag outliers",
        modality="fmri",
        query_understanding={"intent": ["quality_control"]},
    )

    assert prediction.predicted_capabilities
    lowered_caps = [x.lower() for x in prediction.predicted_capabilities]
    lowered_intents = [x.lower() for x in prediction.predicted_intents]
    assert "quality_check" in lowered_caps or "quality_control" in lowered_caps
    assert "quality_control" in lowered_intents
    assert prediction.confidence > 0.0


def test_score_tool_capability_match_prefers_capability_aligned_tool():
    prediction = predict_capabilities(
        query="Run MRIQC quality control and report outliers",
        modality="fmri",
    )
    qc_tool = _Tool("python.mriqc.run", ["quality_control", "mriqc_single"])
    viz_tool = _Tool("python.nilearn_viz.run", ["visualization"])

    qc_score, qc_labels = score_tool_capability_match(qc_tool, prediction)
    viz_score, _ = score_tool_capability_match(viz_tool, prediction)

    assert qc_score > viz_score
    assert qc_labels


pytestmark = pytest.mark.unit
