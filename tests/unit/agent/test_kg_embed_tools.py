from scripts.tools.etl.kg_embed_tools import build_tool_text


def test_build_tool_text_includes_recipe_first_workflow_metadata():
    tool = {
        "id": "workflow_fmriprep_preprocessing",
        "name": "workflow_fmriprep_preprocessing",
        "description": "Run fMRIPrep preprocessing via external runtime.",
        "capabilities": ["run_bids_app"],
        "package": "bids_app_preprocessing",
        "consumes": ["bids_dir", "output_dir"],
        "produces": ["dataset_description", "derivatives_dir"],
        "stage": "preprocessing",
        "cost_tier": "expensive",
        "lifecycle": "candidate_pack",
        "recipe_family": "bids_app_preprocessing",
        "supported_recipe_targets": ["neurodesk", "container", "slurm"],
        "primary_target": "neurodesk",
        "execution_story_kind": "composite_workflow",
        "mcp_execution_posture": "recipe_first",
        "workflow_surface_class": "heavy_runtime",
        "recipe_first_workflow": True,
        "heavy_runtime_workflow": True,
        "recommended_mcp_entrypoint": "get_execution_recipe",
        "execution_guidance": "Generate an execution recipe and run it externally.",
        "artifact_required_outputs": ["dataset_description", "derivatives_dir"],
        "reference_assets": ["bids.dataset"],
        "source_repo": "https://github.com/nipreps/fmriprep",
    }

    text = build_tool_text(tool)

    assert "Recipe-first workflow" in text
    assert "Heavy runtime workflow" in text
    assert "Workflow surface class: heavy_runtime" in text
    assert "Supported recipe targets: neurodesk, container, slurm" in text
    assert "Recommended MCP entrypoint: get_execution_recipe" in text
    assert "Generate an execution recipe and run it externally." in text
    assert "Source repo: https://github.com/nipreps/fmriprep" in text
