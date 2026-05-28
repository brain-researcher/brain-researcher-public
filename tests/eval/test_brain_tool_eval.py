"""BrainToolEval: Routing quality evaluation tests.

This module provides automated regression tests for tool routing quality.
It ensures that the get_candidate_tools() function returns appropriate tools
for various neuroimaging queries.

Level 1: Single tool selection (tool appears in top-k)
Level 2: Two-step chain detection (multiple related tools appear)
"""

import pytest
from typing import List

from brain_researcher.services.tools.registry import get_candidate_tools


# =============================================================================
# Level 1: Single Tool Selection
# =============================================================================
# Tests that the correct tool is ranked in the top-k for specific queries

LEVEL1_CASES = [
    {
        "id": "skull_stripping",
        "query": "skull strip T1 image",
        "expected": ["fsl.bet"],
        "acceptable": ["freesurfer_recon_all"],
        "k": 5,
    },
    {
        "id": "linear_registration",
        "query": "register brain to MNI space linear",
        "expected": ["fsl.flirt"],
        "acceptable": ["fsl.fnirt", "ants.antsRegistration"],
        "k": 5,
    },
    {
        "id": "nonlinear_registration",
        "query": "non-linear registration to template",
        "expected": ["fsl.fnirt"],
        "acceptable": ["ants.antsRegistration"],
        "k": 5,
    },
    {
        "id": "ica_analysis",
        "query": "run ICA on fMRI data",
        "expected": ["fsl.melodic"],
        "acceptable": [],
        "k": 5,
    },
    {
        "id": "first_level_fmri",
        "query": "first level fMRI analysis GLM",
        "expected": ["fsl.feat"],
        "acceptable": [],
        "k": 5,
    },
    {
        "id": "diffusion_tractography",
        "query": "estimate fiber orientations for tractography",
        "expected": ["fsl.bedpostx"],
        "acceptable": [],
        "k": 5,
    },
    {
        "id": "cluster_correction",
        "query": "multiple comparison correction cluster threshold",
        "expected": ["afni.3dClustSim"],
        "acceptable": ["fsl.palm"],
        "k": 5,
    },
    {
        "id": "knowledge_graph",
        "query": "search knowledge graph for motor cortex",
        "expected": ["neurokg.client", "graph_query", "find_related_concepts"],
        "acceptable": [],
        "k": 5,
    },
    {
        "id": "permutation_testing",
        "query": "permutation testing for statistical inference",
        "expected": ["fsl.palm"],
        "acceptable": [],
        "k": 5,
    },
    # New connectivity and GLM cases
    {
        "id": "connectivity_analysis",
        "query": "compute functional connectivity matrix",
        "expected": ["connectivity_matrix"],
        "acceptable": ["fmri.connectivity_client.light"],
        "k": 5,
    },
    {
        "id": "timeseries_extraction",
        "query": "extract ROI time series from fMRI",
        "expected": ["extract_timeseries"],
        "acceptable": [],
        "k": 5,
    },
    {
        "id": "seed_correlation",
        "query": "seed-based correlation analysis from motor cortex",
        "expected": ["seed_based_fc"],
        "acceptable": ["fmri.connectivity_client.light"],
        "k": 5,
    },
    {
        "id": "group_glm",
        "query": "run group level GLM analysis",
        "expected": ["glm_second_level"],
        "acceptable": ["fsl.palm"],
        "k": 5,
    },
    {
        "id": "atlas_fetch",
        "query": "fetch Schaefer atlas parcellation",
        "expected": ["fetch_atlas"],
        "acceptable": [],
        "k": 5,
    },
    {
        "id": "freesurfer_recon",
        "query": "run FreeSurfer cortical reconstruction",
        "expected": ["freesurfer_recon_all"],
        "acceptable": [],
        "k": 5,
    },
]


class TestLevel1SingleTool:
    """Level 1: Single tool selection accuracy."""

    @pytest.mark.parametrize("case", LEVEL1_CASES, ids=lambda c: c["id"])
    def test_routing_accuracy(self, case):
        """Test that expected tools appear in top-k candidates."""
        candidates = get_candidate_tools(case["query"], k=case["k"])
        tool_ids = [c.name for c in candidates]

        # Check if any expected tool is in top-k
        expected_found = any(t in tool_ids for t in case["expected"])
        acceptable_found = any(t in tool_ids for t in case.get("acceptable", []))

        assert expected_found or acceptable_found, (
            f"Routing failed for: {case['id']}\n"
            f"Query: {case['query']}\n"
            f"Expected one of: {case['expected']}\n"
            f"Acceptable: {case.get('acceptable', [])}\n"
            f"Got: {tool_ids}"
        )


# =============================================================================
# Level 2: Two-Step Chain Detection
# =============================================================================
# Tests that related tools for multi-step workflows appear together

LEVEL2_CASES = [
    {
        "id": "t1_preproc_chain",
        "query": "preprocess T1 to MNI with skull stripping",
        "must_contain": ["bet", "fnirt"],  # partial match OK
        "k": 10,
    },
    {
        "id": "fmri_denoise_chain",
        "query": "ICA denoising with FIX classifier",
        "must_contain": ["melodic"],  # FIX might not appear without more context
        "k": 10,
    },
    {
        "id": "registration_chain",
        "query": "linear then non-linear registration to standard space",
        "must_contain": ["flirt", "fnirt"],
        "k": 10,
    },
    # New chain detection cases
    {
        "id": "roi_connectivity_chain",
        "query": "extract ROI signals and compute connectivity",
        "must_contain": ["timeseries", "connectivity"],
        "k": 10,
    },
    {
        "id": "group_fmri_chain",
        "query": "first level GLM then group analysis",
        "must_contain": ["first", "second"],  # glm_first_level, glm_second_level
        "k": 10,
    },
    {
        "id": "parcellation_chain",
        "query": "fetch atlas and extract parcel signals",
        "must_contain": ["atlas", "timeseries"],
        "k": 10,
    },
]


class TestLevel2TwoStepChains:
    """Level 2: Two-step chain detection."""

    @pytest.mark.parametrize("case", LEVEL2_CASES, ids=lambda c: c["id"])
    def test_chain_components(self, case):
        """Test that multiple related tools appear for chain queries."""
        candidates = get_candidate_tools(case["query"], k=case["k"])
        tool_ids = [c.name.lower() for c in candidates]
        all_text = " ".join(tool_ids)

        missing = []
        for required in case["must_contain"]:
            if required.lower() not in all_text:
                missing.append(required)

        assert not missing, (
            f"Chain detection failed for: {case['id']}\n"
            f"Query: {case['query']}\n"
            f"Missing: {missing}\n"
            f"Got: {tool_ids}"
        )


# =============================================================================
# Modality Filtering Tests
# =============================================================================

MODALITY_CASES = [
    {
        "id": "fmri_filter",
        "query": "analyze brain connectivity",
        "modalities": ["fmri"],
        "k": 10,
    },
    {
        "id": "smri_filter",
        "query": "brain extraction",
        "modalities": ["smri"],
        "k": 10,
    },
    {
        "id": "dmri_filter",
        "query": "tractography",
        "modalities": ["dmri"],
        "k": 10,
    },
]


class TestModalityFiltering:
    """Test that modality filtering works correctly."""

    @pytest.mark.parametrize("case", MODALITY_CASES, ids=lambda c: c["id"])
    def test_modality_filter(self, case):
        """Test that filtered results respect modality constraints."""
        candidates = get_candidate_tools(
            case["query"],
            modalities=case["modalities"],
            k=case["k"],
        )

        for candidate in candidates:
            # Tool should either have matching modality or no modality constraint
            if candidate.modalities:
                assert any(
                    m in case["modalities"] for m in candidate.modalities
                ), (
                    f"Modality mismatch for: {case['id']}\n"
                    f"Tool {candidate.name} has modalities {candidate.modalities}\n"
                    f"but filter was {case['modalities']}"
                )


# =============================================================================
# Coverage Metrics
# =============================================================================

def test_exposed_tools_have_descriptions():
    """Ensure all exposed tools have meaningful descriptions."""
    candidates = get_candidate_tools("any query", k=100)

    missing_descriptions = []
    for c in candidates:
        if not c.description or c.description.startswith("Tool:"):
            missing_descriptions.append(c.name)

    # Allow some tools to have auto-generated descriptions
    # but fail if more than 50% are missing
    assert len(missing_descriptions) < len(candidates) * 0.5, (
        f"{len(missing_descriptions)}/{len(candidates)} tools missing descriptions:\n"
        f"{missing_descriptions[:10]}..."
    )


def test_imaging_tools_have_modalities():
    """Ensure imaging tools have modality metadata."""
    candidates = get_candidate_tools("imaging preprocessing", k=50)

    imaging_tools = [c for c in candidates if c.backend == "niwrap"]
    missing_modalities = [t.name for t in imaging_tools if not t.modalities]

    # Not all tools need modalities, but check coverage
    if imaging_tools:
        coverage = 1 - len(missing_modalities) / len(imaging_tools)
        assert coverage >= 0.5, (
            f"Low modality coverage: {coverage:.0%}\n"
            f"Tools missing modalities: {missing_modalities}"
        )


# =============================================================================
# Run as script for quick evaluation
# =============================================================================

if __name__ == "__main__":
    print("Running BrainToolEval quick check...")
    print()

    # Level 1 summary
    print("Level 1: Single Tool Selection")
    print("-" * 40)
    for case in LEVEL1_CASES[:5]:
        candidates = get_candidate_tools(case["query"], k=5)
        tool_ids = [c.name for c in candidates]
        expected_found = any(t in tool_ids for t in case["expected"])
        status = "✓" if expected_found else "✗"
        print(f"  {status} {case['id']}: {tool_ids[:3]}")

    print()
    print("Level 2: Chain Detection")
    print("-" * 40)
    for case in LEVEL2_CASES:
        candidates = get_candidate_tools(case["query"], k=10)
        tool_ids = [c.name for c in candidates]
        status = "✓"
        for required in case["must_contain"]:
            if required.lower() not in " ".join(t.lower() for t in tool_ids):
                status = "✗"
                break
        print(f"  {status} {case['id']}: {tool_ids[:5]}")

    print()
    print("Run with pytest for full coverage:")
    print("  pytest tests/eval/test_brain_tool_eval.py -v")
