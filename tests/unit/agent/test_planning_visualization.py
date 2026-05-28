import asyncio

from brain_researcher.services.agent.planning import PlanningEngine, QueryIntent, WorkflowStep


async def _gen(engine, query, context=None):
    intent = QueryIntent(
        primary_intent="visualize",
        domain="viz",
        entities={"modalities": ["fmri"]},
    )
    return await engine._generate_steps(query, intent, context or {}, None)


def test_generate_steps_visualization_fastpath(tmp_path):
    engine = PlanningEngine()
    stat_map = tmp_path / "stat.nii.gz"
    stat_map.write_text("dummy")

    steps = asyncio.run(_gen(engine, "visualize this stat map", {"stat_map": str(stat_map)}))

    assert len(steps) == 1
    step: WorkflowStep = steps[0]
    assert step.tool_name == "viz_stat_maps"
    assert step.tool_args.get("stat_map") == str(stat_map)


def test_generate_steps_visualization_respects_display_mode(tmp_path):
    engine = PlanningEngine()
    stat_map = tmp_path / "zmap.nii.gz"
    stat_map.write_text("dummy")

    steps = asyncio.run(_gen(engine, "plot overlay orthoview", {"stat_map": str(stat_map), "display_mode": "z"}))

    assert steps[0].tool_args.get("display_mode") == "z"
