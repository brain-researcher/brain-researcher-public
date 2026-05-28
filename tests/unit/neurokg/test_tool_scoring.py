from brain_researcher.services.neurokg.query_service import _weighted_tool_overlap_score


def test_weighted_tool_overlap_prefers_identifier_match_over_description():
    tokens = ["fast", "segmentation"]

    score_id, matched_id = _weighted_tool_overlap_score(
        tokens,
        tool_id="fsl.6.0.4.fast.run",
        method="segmentation",
        software="fsl",
        version="6.0.4",
        op="fast",
        op_key="fast",
        category="unknown",
        intents=["segmentation"],
        description="FSL FAST tissue segmentation tool.",
    )

    # This tool only matches "fast" in free-text; identifier does not contain it.
    score_desc, matched_desc = _weighted_tool_overlap_score(
        tokens,
        tool_id="freesurfer.7.4.1.make_average_subcort.run",
        method="segmentation",
        software="freesurfer",
        version="7.4.1",
        op="make_average_subcort",
        op_key="makeaveragesubcort",
        category="segmentation",
        intents=["segmentation"],
        description="A fast segmentation helper for subcortical structures.",
    )

    assert "fast" in matched_id and "segmentation" in matched_id
    assert "fast" in matched_desc and "segmentation" in matched_desc
    assert score_id > score_desc
