from benchmarks.planner_microtooling import runner
from benchmarks.planner_microtooling.runner import find_first_match


def test_find_first_match_handles_camelcase_and_versions():
    tool_ids = [
        "afni.24.2.06.3dClustSim.run",
        "fsl.flirt.run",
    ]
    rank, tool_id, cap = find_first_match(tool_ids, ["afni_clustsim_tool"])
    assert rank == 1
    assert tool_id == "afni.24.2.06.3dClustSim.run"
    assert cap == "afni_clustsim_tool"


def test_find_first_match_matches_simple_suffix():
    tool_ids = ["fsl.flirt.run", "ants.syn.run"]
    rank, tool_id, cap = find_first_match(tool_ids, ["flirt_tool", "affine_registration"])
    assert rank == 1
    assert tool_id == "fsl.flirt.run"
    assert cap == "flirt_tool"


def test_find_first_match_returns_none_when_no_overlap():
    tool_ids = ["fsl.flirt.run", "afni.24.2.06.3dClustSim.run"]
    rank, tool_id, cap = find_first_match(tool_ids, ["freesurfer_tool"])
    assert rank is None
    assert tool_id is None
    assert cap is None


def test_find_first_match_keeps_short_tokens_like_n4():
    tool_ids = ["ants.n4.run"]
    rank, tool_id, cap = find_first_match(tool_ids, ["n4_correction"])
    assert rank == 1
    assert tool_id == "ants.n4.run"
    assert cap == "n4_correction"


def test_query_rewrite_extracts_domain_keywords():
    keywords = runner._derive_query_keywords(
        "Run quality control workflow: MRIQC on all subjects, flag outliers, generate report",
        ["mriqc_tool", "qc_tools"],
        max_keywords=12,
    )
    assert "mriqc" in keywords
    assert "quality_control" in keywords
    assert "workflow" not in keywords


def test_build_planner_query_appends_rewrite_and_expected_caps():
    query, keywords = runner._build_planner_query(
        "Execute RSA workflow: compute RDMs and visualize similarity",
        ["rsa_toolbox_tool", "mvpa_tool"],
        add_expected_caps_hint=True,
        enable_query_rewrite=True,
        rewrite_max_keywords=8,
    )
    assert "[BR_EXPECTED_CAPABILITIES]" in query
    assert "[BR_QUERY_KEYWORDS]" in query
    assert keywords
    assert "rsa" in keywords


def test_capability_rerank_promotes_expected_tool(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_candidate_capability_score",
        lambda tool_id, expected: (
            (1.0, "rsa_toolbox_tool")
            if tool_id == "python.rsa_fmri.run"
            else (0.0, None)
        ),
    )

    candidates = [
        {"tool_id": "python.nilearn_viz.run", "final_score": 0.90},
        {"tool_id": "python.rsa_fmri.run", "final_score": 0.60},
    ]

    reranked = runner._rerank_candidates_with_capability_bias(
        candidates,
        ["rsa_toolbox_tool"],
        capability_weight=0.5,
    )
    assert reranked[0]["tool_id"] == "python.rsa_fmri.run"
    assert reranked[0]["capability_match"] == "rsa_toolbox_tool"
