from __future__ import annotations

from brain_researcher.services.mcp import execution_recipes


def test_augment_module_summary_prefers_bids_app_module():
    resolved = execution_recipes._augment_module_summary_from_recipe(
        {},
        neurodesk_modules=["fmriprep/23.2.3", "freesurfer/8.1.0"],
        container_images={"fmriprep": "nipreps/fmriprep:23.2.3"},
    )

    # The BIDS-app module (matches a container image key) wins over freesurfer.
    assert resolved["neurodesk_recommended_version"] == "23.2.3"
    assert resolved["neurodesk_recommended_module"] == "fmriprep/23.2.3"
    assert resolved["neurodesk_module_name"] == "fmriprep"
    assert "fmriprep/23.2.3" in resolved["neurodesk_available_modules"]
    assert "freesurfer/8.1.0" in resolved["neurodesk_available_modules"]
    assert "23.2.3" in resolved["neurodesk_available_versions"]


def test_augment_module_summary_falls_back_to_container_tag():
    resolved = execution_recipes._augment_module_summary_from_recipe(
        {},
        neurodesk_modules=[],
        container_images={"fmriprep": "nipreps/fmriprep:23.2.3"},
    )

    assert resolved["neurodesk_recommended_version"] == "23.2.3"
    assert resolved["neurodesk_available_versions"] == ["23.2.3"]
    assert resolved["neurodesk_module_name"] == "fmriprep"


def test_augment_module_summary_respects_authoritative_profile():
    resolved = execution_recipes._augment_module_summary_from_recipe(
        {"neurodesk_recommended_version": "1.2.3", "neurodesk_module_name": "x"},
        neurodesk_modules=["fmriprep/23.2.3"],
        container_images={"fmriprep": "nipreps/fmriprep:99.9.9"},
    )

    # A populated package profile is left untouched.
    assert resolved["neurodesk_recommended_version"] == "1.2.3"
    assert resolved["neurodesk_module_name"] == "x"


def test_augment_module_summary_noop_without_modules_or_images():
    assert (
        execution_recipes._augment_module_summary_from_recipe(
            {}, neurodesk_modules=[], container_images={}
        )
        == {}
    )


def test_resolve_recipe_metadata_surfaces_pin_into_summary_fields(monkeypatch):
    """resolve_recipe_metadata must surface the recipe-dependency pin into the
    neurodesk_* summary fields even when the package profile is empty (the
    wrapper-backed workflow_fmriprep_preprocessing case)."""
    monkeypatch.setattr(
        execution_recipes, "get_tool_recipe_override", lambda _tool_id: {}
    )
    monkeypatch.setattr(
        execution_recipes, "_neurodesk_module_resolution", lambda _tool_id: {}
    )
    monkeypatch.setattr(
        execution_recipes,
        "_infer_neurodesk_modules",
        lambda *_args, **_kwargs: ["fmriprep/23.2.3", "freesurfer/8.1.0"],
    )

    metadata = execution_recipes.resolve_recipe_metadata(
        "workflow_fmriprep_preprocessing",
        workflow_entry={"id": "workflow_fmriprep_preprocessing"},
    )

    assert "slurm" in metadata["supported_recipe_targets"]
    assert metadata["neurodesk_modules"] == ["fmriprep/23.2.3", "freesurfer/8.1.0"]
    # Previously null/[]; now reflects the pin carried in recipe.dependencies.
    assert metadata["neurodesk_recommended_version"] == "23.2.3"
    assert metadata["neurodesk_recommended_module"] == "fmriprep/23.2.3"
    assert "fmriprep/23.2.3" in metadata["neurodesk_available_modules"]
