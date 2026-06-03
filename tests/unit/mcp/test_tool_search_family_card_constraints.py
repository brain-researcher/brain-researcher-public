from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from brain_researcher.services.mcp import server as srv


@contextmanager
def _routing_mode(mode: str) -> Iterator[None]:
    import os

    original = {
        "BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE": os.environ.get(
            "BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"
        ),
        "BR_TOOL_FAMILY_ROUTING_MODE": os.environ.get("BR_TOOL_FAMILY_ROUTING_MODE"),
    }
    try:
        os.environ["BR_MCP_TOOL_SEARCH_FAMILY_ROUTING_MODE"] = mode
        os.environ["BR_TOOL_FAMILY_ROUTING_MODE"] = mode
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _cards_mode() -> Iterator[None]:
    with _routing_mode("cards"):
        yield


def _tool_names(query: str, *, mode: str, limit: int = 8) -> list[str]:
    with _routing_mode(mode):
        resp = srv.tool_search(query=query, limit=limit, exposed_only=True)
    assert resp["ok"] is True
    return [str(tool.get("name") or "") for tool in resp.get("tools", [])]


def _cards_tool_names(query: str, *, limit: int = 8) -> list[str]:
    return _tool_names(query, mode="cards", limit=limit)


def test_family_cards_do_not_pull_fmri_ica_to_meeg_ica() -> None:
    names = _cards_tool_names("ICA denoising for fMRI")

    assert names[0] == "fsl_fix"
    assert "mne_ica" not in names[:3]


def test_family_cards_preserve_realtime_fmri_for_realtime_motion() -> None:
    names = _cards_tool_names(
        "Perform real-time motion correction and quality assessment"
    )

    assert names[0] == "realtime_fmri"


def test_family_cards_keep_resting_connectome_workflow_near_top() -> None:
    names = _cards_tool_names("resting-state connectivity")

    assert "workflow_rest_connectome_e2e" in names[:4]


def test_family_cards_do_not_replace_meg_connectivity_with_fmri_connectivity() -> None:
    names = _cards_tool_names(
        "Compute phase-locking value connectivity between MEG sensors"
    )

    assert names[0] == "mne_connectivity"
    assert {
        "connectivity_matrix",
        "compute_connectivity",
        "nilearn_connectivity_matrix",
    }.isdisjoint(names[:5])


def test_family_cards_do_not_treat_fmri_lag_as_meeg_connectivity() -> None:
    names = _cards_tool_names("fMRI lag connectivity analysis")

    assert names[0] == "connectivity_matrix"
    assert "mne_connectivity" not in names[:5]
    assert "connectivity_measures" not in names[:5]


def test_family_cards_preserve_harmonization_intent_over_meeg_family() -> None:
    names = _cards_tool_names(
        "Harmonize MEG sensor-level data using reference site method"
    )

    assert names[0] == "data_harmonization"
    assert "mne_source_localization" not in names[:3]


def test_family_cards_preserve_literature_coordinate_extraction() -> None:
    names = _cards_tool_names(
        "Extract coordinates from 100 PubMed fMRI abstracts automatically"
    )

    assert names[0] == "literature_mining"
    assert "workflow_group_ica" not in names[:3]


def test_family_cards_preserve_realtime_tensor_decomposition() -> None:
    names = _cards_tool_names("Implement real-time tensor decomposition for denoising")

    assert names[0] == "realtime_fmri"


def test_family_cards_preserve_realtime_navigator_motion() -> None:
    names = _cards_tool_names(
        "Implement prospective motion correction from navigator echoes"
    )

    assert names[0] == "realtime_fmri"


def test_family_cards_preserve_publication_figure_visualization() -> None:
    names = _cards_tool_names(
        "Generate publication-quality figure panel with multiple views"
    )

    assert names[0] == "viz_stat_maps"
    assert "multiple_comparison_correction" not in names[:3]


def test_family_cards_split_kg_construction_from_lookup() -> None:
    names = _cards_tool_names(
        "Build gene-brain-behavior knowledge graph from OASIS and genetic data"
    )

    assert names[0] == "graph_query"
    assert "br_kg.search_nodes" not in names[:3]


def test_family_cards_keep_kg_lookup_on_search_nodes() -> None:
    names = _cards_tool_names("Search BR-KG nodes for hippocampus related concepts")

    assert names[0] == "br_kg.search_nodes"


def test_family_cards_preserve_subfield_segmentation() -> None:
    names = _cards_tool_names(
        "Perform hippocampus subfield segmentation on ABIDE structural scans"
    )

    assert names[0] in {"freesurfer_recon_all", "workflow_fastsurfer"}
    assert "fsl_fast" not in names[:3]
    assert "spm12_vbm" not in names[:3]


def test_family_cards_route_brain_simulation_queries() -> None:
    names = _cards_tool_names(
        "Simulate BOLD timeseries using Jansen-Rit neural mass model"
    )

    assert names[0] == "brain_simulation"
    assert "workflow_brain_simulation" in names[:3]


def test_family_cards_route_cortical_reconstruction_queries() -> None:
    names = _cards_tool_names(
        "Run complete FreeSurfer recon-all on T1-weighted anatomical scan"
    )

    assert names[0] == "freesurfer_recon_all"
    assert "workflow_fastsurfer" in names[:5]


def test_family_cards_route_surface_processing_queries() -> None:
    names = _cards_tool_names(
        "Create CIFTI dscalar files combining cortical and subcortical data"
    )

    assert names[0] == "surface_projection"
    assert "mne_ica" not in names[:1]


def test_family_cards_route_graph_theory_without_kg_lookup() -> None:
    names = _cards_tool_names(
        "Compute graph theory metrics clustering path length from structural connectome"
    )

    assert names[0] == "workflow_dwi_connectome"
    assert "br_kg.search_nodes" not in names[:5]


def test_family_cards_route_diffusion_model_queries() -> None:
    names = _cards_tool_names("Fit diffusion tensor model and compute FA MD RD AD maps")

    assert names[0] == "diffusion_tractography"
    assert "mne_connectivity" not in names[:5]


def test_family_cards_route_tractography_kg_construction_to_graph_query() -> None:
    names = _cards_tool_names(
        "Build tractography-based structural knowledge graph from diffusion data"
    )

    assert names[0] == "graph_query"
    assert "br_kg.search_nodes" not in names[:3]


def test_family_cards_preserve_frequency_band_connectivity() -> None:
    names = _cards_tool_names(
        "Build multi-layer networks with different frequency bands on ADHD data"
    )

    assert names[0] == "mne_timefreq"
    assert "data_harmonization" not in names[:1]


def test_family_cards_preserve_diffusion_harmonization() -> None:
    names = _cards_tool_names(
        "Harmonize diffusion metrics across QSIPrep pipeline versions"
    )

    assert names[0] == "data_harmonization"
    assert "diffusion_tractography" not in names[:1]


def test_family_cards_route_interactive_activation_overlay_to_visualization() -> None:
    names = _cards_tool_names(
        "Create interactive 3D brain with activation overlay from Haxby"
    )

    assert names[0] == "viz_stat_maps"
    assert "brain_simulation" not in names[:1]


@pytest.mark.parametrize("mode", ["legacy", "cards"])
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("ICA denoising for fMRI", "fsl_fix"),
        (
            "Compute phase-locking value connectivity between MEG sensors",
            "mne_connectivity",
        ),
        (
            "Generate publication-quality figure panel with multiple views",
            "viz_stat_maps",
        ),
    ],
)
def test_core_tool_search_invariants_hold_in_both_modes(
    mode: str, query: str, expected: str
) -> None:
    names = _tool_names(query, mode=mode)

    assert names[0] == expected
