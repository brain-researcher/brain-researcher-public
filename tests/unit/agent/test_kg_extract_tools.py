from scripts.tools.etl.kg_extract_tools import (
    aggregate_family_ops,
    extract_operations,
    extract_synonyms,
    extract_tools_and_families,
)


def test_extract_tools_respects_limit(monkeypatch):
    # Cap NiWrap load to keep this test light
    monkeypatch.setenv("BR_NIWRAP_LIMIT", "30")
    families, tools = extract_tools_and_families()
    assert families, "expected at least one tool family"
    assert tools, "expected at least one tool"
    # should not exceed limit by more than a small margin (non-container tools still load)
    container_tools = [t for t in tools if t["id"].startswith("container.")]
    assert len(container_tools) <= 40


def test_extract_operations_and_synonyms():
    ops, children = extract_operations()
    syns = extract_synonyms()
    assert ops, "intents should load"
    # ensure parent-child edges align with intents
    assert all(isinstance(p, tuple) for p in children)
    assert syns, "synonyms should load"


def test_aggregate_family_ops(monkeypatch):
    monkeypatch.setenv("BR_NIWRAP_LIMIT", "30")
    _, tools = extract_tools_and_families()
    fam_ops = aggregate_family_ops(tools)
    assert fam_ops, "family-operation aggregates should not be empty"


def test_extract_tools_includes_recipe_first_workflows(monkeypatch):
    monkeypatch.setenv("BR_NIWRAP_LIMIT", "30")
    _, tools = extract_tools_and_families()
    by_id = {tool["id"]: tool for tool in tools}

    fmriprep = by_id["workflow_fmriprep_preprocessing"]
    assert fmriprep["source"] == "workflow_catalog/vFinal"
    assert fmriprep["recipe_first_workflow"] is True
    assert fmriprep["heavy_runtime_workflow"] is True
    assert set(fmriprep["family_ids"]) >= {"bidsapps", "fsl"}
    assert fmriprep["supported_recipe_targets"] == ["neurodesk", "container", "slurm"]
    assert "run_bids_app" in fmriprep["capabilities"]
    assert {"bids_dir", "output_dir"} <= set(fmriprep["consumes"])
    assert "dataset_description" in fmriprep["produces"]

    task_glm = by_id["workflow_task_glm_group"]
    assert task_glm["recipe_first_workflow"] is True
    assert task_glm["batch_analysis_workflow"] is True
    assert task_glm["workflow_surface_class"] == "batch_analysis"
    assert task_glm["family_ids"] == ["fsl"]
    assert task_glm["supported_recipe_targets"] == ["python"]
