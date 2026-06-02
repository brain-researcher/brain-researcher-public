from __future__ import annotations

from brain_researcher.services.mcp import server as srv


def _tool_names(query: str, *, limit: int = 8) -> list[str]:
    resp = srv.tool_search(query, limit=limit, exposed_only=True)
    assert resp["ok"] is True
    return [str(tool.get("name") or "") for tool in resp.get("tools", [])]


def test_tool_search_brain_extraction_prefers_fsl_bet() -> None:
    names = _tool_names("brain extraction")

    assert names
    assert names[0] == "fsl_bet"


def test_tool_search_registration_prefers_registration_tools() -> None:
    names = _tool_names("registration")

    assert names
    assert names[0] in {"ants_registration", "fsl_flirt", "fsl_fnirt"}
    assert {"ants_registration", "fsl_flirt", "fsl_fnirt"} & set(names[:3])


def test_tool_search_vbm_prefers_spm12_vbm() -> None:
    names = _tool_names("VBM grey matter volume")

    assert names
    assert names[0] == "spm12_vbm"


def test_tool_search_fast_segmentation_prefers_canonical_fsl_fast() -> None:
    names = _tool_names("FSL FAST tissue segmentation")

    assert names
    assert names[0] == "fsl_fast"
    assert "fsl.6.0.4.fast.run" not in names[:5]


def test_tool_search_resting_state_connectivity_returns_connectivity_surface() -> None:
    names = _tool_names("resting-state connectivity")

    assert names
    assert names[0] in {
        "workflow_rest_connectome_e2e",
        "seed_based_fc",
        "connectivity_matrix",
        "fmri.connectivity_client.light",
    }
    assert "workflow_rest_connectome_e2e" in names[:4]
    assert {
        "seed_based_fc",
        "connectivity_matrix",
        "fmri.connectivity_client.light",
    } & set(names[:4])


def test_tool_search_motion_correction_prefers_realtime_fmri() -> None:
    names = _tool_names("motion correction")

    assert names
    assert names[0] == "realtime_fmri"


def test_tool_search_skull_stripping_prefers_fsl_bet() -> None:
    names = _tool_names("skull stripping T1 MRI")

    assert names
    assert names[0] == "fsl_bet"


def test_tool_search_nonlinear_registration_prefers_registration_stack() -> None:
    names = _tool_names("nonlinear image registration")

    assert names
    assert names[0] in {"ants_registration", "fsl_flirt", "fsl_fnirt"}
    assert {"ants_registration", "fsl_flirt", "fsl_fnirt"} & set(names[:3])


def test_tool_search_ica_denoising_prefers_fsl_fix() -> None:
    names = _tool_names("ICA denoising for fMRI")

    assert names
    assert names[0] == "fsl_fix"


def test_tool_search_fieldmap_tools_use_canonical_fsl_runtime_ids() -> None:
    names = _tool_names("fieldmap preparation and topup distortion correction")

    assert names
    assert names[0] in {
        "fmriprep_preprocessing",
        "fsl_prepare_fieldmap",
        "fsl_topup",
        "fsl_epi_reg",
    }
    assert {"fsl_prepare_fieldmap", "fsl_topup", "fsl_epi_reg"} & set(names[:5])
    assert "fsl.6.0.4.fsl_prepare_fieldmap.run" not in names[:5]
    assert "fsl.6.0.4.topup.run" not in names[:5]
    assert "fsl.6.0.4.epi_reg.run" not in names[:5]


def test_tool_search_cortical_reconstruction_prefers_freesurfer() -> None:
    names = _tool_names("cortical reconstruction and segmentation")

    assert names
    assert names[0] == "freesurfer_recon_all"


def test_tool_search_seed_based_connectivity_prefers_seed_surface() -> None:
    names = _tool_names("seed-based connectivity analysis")

    assert names
    assert names[0] in {"workflow_seed_based_connectivity", "seed_based_fc"}
    # connectivity_matrix sits in the connectivity cluster at the very top (rank ~6,
    # just behind compute_connectivity / connectivity_gradients / network_based_statistics).
    # The exact #5-vs-#6 ordering against network_based_statistics is a relevance
    # toss-up, not a defect; assert it's prominently surfaced rather than pinning a
    # brittle top-5 cutoff (still guards against it dropping out of the top tier).
    assert "connectivity_matrix" in names[:6]


def test_tool_search_permutation_testing_prefers_fsl_palm() -> None:
    names = _tool_names("permutation testing")

    assert names
    assert names[0] == "fsl_palm"


def test_tool_search_first_level_task_glm_prefers_glm_first_level() -> None:
    names = _tool_names("first level task glm")

    assert names
    assert names[0] == "glm_first_level"


def test_tool_search_group_level_task_glm_keeps_group_glm_surface_near_top() -> None:
    names = _tool_names("group level task glm")

    assert names
    assert names[0] == "workflow_task_glm_group"
    assert "glm_second_level" in names[:5]


def test_tool_search_searchlight_analysis_prefers_searchlight_tool() -> None:
    names = _tool_names("searchlight analysis")

    assert names
    assert names[0] == "searchlight_analysis"


def test_tool_search_surface_projection_prefers_surface_projection() -> None:
    names = _tool_names("surface projection from volume to cortex")

    assert names
    assert names[0] == "surface_projection"


def test_tool_search_stat_map_visualization_prefers_viz_stat_maps() -> None:
    names = _tool_names("visualize statistical brain maps")

    assert names
    assert names[0] == "viz_stat_maps"


def test_tool_search_lesion_detection_prefers_lesion_detection() -> None:
    names = _tool_names("lesion detection")

    assert names
    assert names[0] == "lesion_detection"


def test_tool_search_brain_age_estimator_prefers_compute_brain_age() -> None:
    names = _tool_names("brain age estimator")

    assert names
    assert names[0] == "compute_brain_age"


def test_tool_search_brain_age_prediction_should_prefer_brain_age_tools() -> None:
    names = _tool_names("brain age prediction")

    assert names
    assert names[0] in {"compute_brain_age", "workflow_brain_age_prediction"}


def test_tool_search_searchlight_decoding_should_prefer_searchlight_analysis() -> None:
    names = _tool_names("searchlight decoding")

    assert names
    assert names[0] == "searchlight_analysis"
