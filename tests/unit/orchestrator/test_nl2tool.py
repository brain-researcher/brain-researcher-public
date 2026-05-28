import pytest

from brain_researcher.services.orchestrator.nl2tool import select_tool
from brain_researcher.services.orchestrator.models import PipelineType


@pytest.mark.parametrize(
    ("prompt", "expected_pipeline", "expected_tool"),
    [
        ("Run a first-level GLM on ds000114 motor task", PipelineType.GLM, "glm"),
        ("Summarize resting-state functional connectivity in PCC", PipelineType.CONNECTIVITY, "connectivity"),
        ("Perform meta-analysis with NiMARE", PipelineType.CUSTOM, "meta_analysis"),
        ("静息态功能连接矩阵分析", PipelineType.CONNECTIVITY, "connectivity"),
        ("Please ingest OpenNeuro ds003097", PipelineType.PIPELINE_BUILDER, "ingest"),
    ],
)
def test_select_tool_rules(prompt, expected_pipeline, expected_tool):
    decision = select_tool(prompt)
    assert decision.pipeline == expected_pipeline
    assert decision.tool == expected_tool
    assert decision.confidence >= 0.5


def test_select_tool_attachment_overrides():
    prompt = "Answer questions based on the attached PDF report."
    decision = select_tool(prompt, attachments=["analysis.pdf"])
    assert decision.tool == "file_qa"
    assert decision.pipeline == PipelineType.CUSTOM
    assert decision.confidence >= 0.7


def test_select_tool_dataset_extraction():
    prompt = "Run GLM contrasts for OpenNeuro dataset ds000114."
    decision = select_tool(prompt)
    assert decision.pipeline == PipelineType.GLM
    assert decision.parameters.get("dataset_id") == "ds000114"
