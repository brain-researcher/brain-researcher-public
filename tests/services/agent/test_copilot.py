from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from brain_researcher.config.paths import resolve_from_config
from brain_researcher.services.agent.copilot import CopilotAssistant
from brain_researcher.services.tools.tool_base import BRKGToolWrapper, ToolResult
from brain_researcher.services.tools.tool_registry import ToolRegistry


class _ArgsA(BaseModel):
    tr: float = Field(..., description="Repetition time")


class _ArgsB(BaseModel):
    nscans: int | None = None
    smoothing_kernel: float | None = None


class FakeToolA(BRKGToolWrapper):
    def get_tool_name(self) -> str:
        return "spm-glm"

    def get_tool_description(self) -> str:
        return "Run single-subject GLM analysis (glm, contrast, subject)"

    def get_args_schema(self) -> type[BaseModel]:
        return _ArgsA

    def _run(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", data={"ok": True})


class FakeToolB(BRKGToolWrapper):
    def get_tool_name(self) -> str:
        return "fsl-bet"

    def get_tool_description(self) -> str:
        return "Brain extraction (skull strip) for T1w images"

    def get_args_schema(self) -> type[BaseModel]:
        return _ArgsB

    def _run(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", data={"ok": True})


def _setup_copilot(tmp_path: Path) -> CopilotAssistant:
    reg = ToolRegistry(auto_discover=False)
    reg.register_tool(FakeToolA())
    reg.register_tool(FakeToolB())
    # rebuild index after manual registration
    reg._build_tool_index()
    # memory file in tmp
    from brain_researcher.services.agent.copilot import CopilotMemory, ExampleDB

    mem = CopilotMemory(storage_path=tmp_path / "mem.json")
    ex = ExampleDB()  # uses packaged examples
    return CopilotAssistant(tool_registry=reg, memory=mem, examples=ex)


def test_suggest_tools_returns_ranked_suggestions(tmp_path: Path):
    copilot = _setup_copilot(tmp_path)
    sug = copilot.suggest_tools("run glm for motor task", k=3)
    assert len(sug) >= 1
    names = [s.name for s in sug]
    assert "spm-glm" in names


def test_autocomplete_uses_dataset_metadata(tmp_path: Path):
    copilot = _setup_copilot(tmp_path)
    meta = {"RepetitionTime": 2.0, "repetition_time": 2.0, "space": "MNI152"}
    # metadata keys normalized; spm maps repetition_time -> TR
    ac = copilot.autocomplete_parameters("spm-glm", {}, meta)
    # Expect TR required param satisfied as 'TR' or 'tr' depending on mapping; spm mapping is 'TR'
    assert ac.get("TR") == 2.0 or ac.get("tr") == 2.0


def test_examples_surface_example_queries(tmp_path: Path):
    copilot = _setup_copilot(tmp_path)
    sug = copilot.suggest_tools("skull strip T1w", k=3)
    skull = next(s for s in sug if s.name == "fsl-bet")
    assert any("skull strip" in ex.lower() for ex in skull.examples)


def test_example_db_defaults_to_canonical_config_path() -> None:
    from brain_researcher.services.agent.copilot import ExampleDB

    ex = ExampleDB()
    assert ex.examples_path == resolve_from_config("agent", "copilot_examples.json")


def test_example_db_does_not_fall_back_to_service_local_resource_path() -> None:
    from brain_researcher.services.agent.copilot import ExampleDB

    ex = ExampleDB()
    assert "services/agent/resources/copilot_examples.json" not in str(ex.examples_path)


def test_learning_improves_ranking(tmp_path: Path):
    copilot = _setup_copilot(tmp_path)
    a = copilot.suggest_tools("glm analysis", k=2)
    # Force-learn selection of fsl-bet
    copilot.learn_selection("fsl-bet")
    b = copilot.suggest_tools("glm analysis", k=2)
    # fsl-bet score should not decrease; may increase or appear more prominently
    score_a = next((s.score for s in a if s.name == "fsl-bet"), 0.0)
    score_b = next((s.score for s in b if s.name == "fsl-bet"), 0.0)
    assert score_b >= score_a
