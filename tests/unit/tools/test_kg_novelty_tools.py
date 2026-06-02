from __future__ import annotations

from brain_researcher.services.tools import kg_novelty_tools as novelty


class _Node:
    def __init__(self, kg_id: str):
        self.kg_id = kg_id


def test_find_structural_leverage_resolves_query_to_seed_ids(monkeypatch):
    captured: dict[str, object] = {}

    def fake_search_nodes(query, limit=20, infer_types=True):
        del limit, infer_types
        assert query == "cognitive control"
        return [_Node("node:seed_a"), _Node("node:seed_b")]

    def fake_find_structural_leverage(
        seed_kg_ids,
        *,
        relation_types=None,
        direction="both",
        limit=25,
        taste=None,
    ):
        captured["seed_kg_ids"] = list(seed_kg_ids)
        captured["relation_types"] = relation_types
        captured["direction"] = direction
        captured["limit"] = limit
        captured["taste"] = taste
        return {"items": [{"kg_id": "n1"}], "count": 1}

    monkeypatch.setattr(
        novelty.query_service,
        "search_nodes",
        fake_search_nodes,
        raising=False,
    )
    monkeypatch.setattr(
        novelty.query_service,
        "find_structural_leverage",
        fake_find_structural_leverage,
        raising=False,
    )

    tool = novelty.FindStructuralLeverageTool()
    result = tool._run(
        query="cognitive control", limit=7, relation_types=["RELATED_TO"]
    )

    assert result.status == "success"
    assert result.data["result"] == {"items": [{"kg_id": "n1"}], "count": 1}
    assert result.data["resolved_seed_kg_ids"] == ["node:seed_a", "node:seed_b"]
    assert captured == {
        "seed_kg_ids": ["node:seed_a", "node:seed_b"],
        "relation_types": ["RELATED_TO"],
        "direction": "both",
        "limit": 7,
        "taste": {"mode": "novelty_first"},
    }
    assert [row["kg_id"] for row in result.data["resolved_anchor_bundle"]] == [
        "node:seed_a",
        "node:seed_b",
    ]


def test_resolve_seed_context_builds_anchor_bundle_from_free_text(monkeypatch):
    query_hits = {
        "fmri image decoding": [
            {
                "kg_id": "pub:fmri_decoding",
                "label": "Whole-Brain Task fMRI Decoding",
                "node_type": "Publication",
            }
        ],
        "image decoding": [
            {
                "kg_id": "task:image_decoding",
                "label": "Cross-decoding of natural scenes",
                "node_type": "Task",
            }
        ],
        "visual image reconstruction": [
            {
                "kg_id": "ds:visual_recon",
                "label": "Visual image reconstruction",
                "node_type": "Dataset",
            }
        ],
        "natural scenes decoding": [
            {
                "kg_id": "task:image_decoding",
                "label": "Cross-decoding of natural scenes",
                "node_type": "Task",
            }
        ],
        "mvpa decoding": [
            {
                "kg_id": "tool:mvpa",
                "label": "nilearn mvpa decoding run",
                "node_type": "Tool",
            }
        ],
    }

    def fake_search_nodes(query, limit=8, infer_types=True):
        del limit, infer_types
        return [type("_Result", (), item)() for item in query_hits.get(query, [])]

    monkeypatch.setattr(
        novelty.query_service,
        "search_nodes",
        fake_search_nodes,
        raising=False,
    )

    seeds, bundle = novelty._resolve_seed_context(
        seed_kg_ids=None,
        query="fmri-based image decoding",
        search_limit=4,
    )

    assert seeds[0] == "ds:visual_recon"
    assert set(seeds) == {
        "ds:visual_recon",
        "task:image_decoding",
        "pub:fmri_decoding",
        "tool:mvpa",
    }
    assert [row["kg_id"] for row in bundle] == seeds
    assert bundle[0]["kg_id"] == "ds:visual_recon"
    assert "visual image reconstruction" in bundle[0]["matched_queries"]
    assert any("domain_hits" in reason for reason in bundle[0]["match_reasons"])


def test_sample_and_verify_hypotheses_surfaces_resolved_anchor_bundle(monkeypatch):
    def fake_search_nodes(query, limit=8, infer_types=True):
        del limit, infer_types
        if query == "visual image reconstruction":
            return [
                type(
                    "_Result",
                    (),
                    {
                        "kg_id": "ds:visual_recon",
                        "label": "Visual image reconstruction",
                        "node_type": "Dataset",
                    },
                )()
            ]
        return []

    def fake_sample_and_verify_hypotheses(
        *,
        seed_kg_ids,
        relation_types=None,
        sample_limit=5,
        verify_top_k=None,
        taste=None,
        strictness="balanced",
        candidate_lane_mode="broad",
        allowed_node_types=None,
        max_evidence=60,
        max_paths=3,
        min_evidence_score=None,
        include_subgraph=False,
        include_path_details=False,
        confidence_scoring_version="v2",
    ):
        del (
            relation_types,
            sample_limit,
            verify_top_k,
            taste,
            strictness,
            candidate_lane_mode,
            allowed_node_types,
            max_evidence,
            max_paths,
            min_evidence_score,
            include_subgraph,
            include_path_details,
            confidence_scoring_version,
        )
        return {"ok": True, "seed_kg_ids": list(seed_kg_ids), "tested_hypotheses": []}

    monkeypatch.setattr(
        novelty.query_service,
        "search_nodes",
        fake_search_nodes,
        raising=False,
    )
    monkeypatch.setattr(
        novelty.query_service,
        "sample_and_verify_hypotheses",
        fake_sample_and_verify_hypotheses,
        raising=False,
    )

    tool = novelty.SampleAndVerifyHypothesesTool()
    result = tool._run(query="visual image reconstruction", n_samples=2)

    assert result.status == "success"
    assert result.data["resolved_seed_kg_ids"] == ["ds:visual_recon"]
    bundle = result.data["resolved_anchor_bundle"]
    assert len(bundle) == 1
    assert bundle[0]["kg_id"] == "ds:visual_recon"
    assert bundle[0]["node_type"] == "Dataset"
    assert "visual image reconstruction" in bundle[0]["matched_queries"]


def test_detect_contradiction_motifs_requires_any_signal():
    tool = novelty.DetectContradictionMotifsTool()
    result = tool._run(max_evidence=5)

    assert result.status == "error"
    assert result.error == "Provide query, seed_kg_ids, or evidence_items"


def test_find_contradiction_frontiers_maps_to_query_service_signature(monkeypatch):
    captured: dict[str, object] = {}

    def fake_find_contradiction_frontiers(
        *,
        query=None,
        seed_kg_ids=None,
        relation_types=None,
        limit=10,
        max_evidence=80,
    ):
        captured.update(
            {
                "query": query,
                "seed_kg_ids": seed_kg_ids,
                "relation_types": relation_types,
                "limit": limit,
                "max_evidence": max_evidence,
            }
        )
        return {"frontiers": [{"frontier_label": "weights are required"}]}

    monkeypatch.setattr(
        novelty.query_service,
        "find_contradiction_frontiers",
        fake_find_contradiction_frontiers,
        raising=False,
    )

    tool = novelty.FindContradictionFrontiersTool()
    result = tool._run(
        query="structural prior",
        seed_kg_ids=["concept:structural_prior"],
        relation_types=["ASSOCIATED_WITH"],
        limit=7,
        max_evidence=12,
    )

    assert result.status == "success"
    assert (
        result.data["result"]["frontiers"][0]["frontier_label"]
        == "weights are required"
    )
    assert captured == {
        "query": "structural prior",
        "seed_kg_ids": ["concept:structural_prior"],
        "relation_types": ["ASSOCIATED_WITH"],
        "limit": 7,
        "max_evidence": 12,
    }


def test_mine_assumption_cracks_maps_to_query_service_signature(monkeypatch):
    captured: dict[str, object] = {}
    frontier_payload = {
        "frontiers": [{"frontier_label": "structure predicts behavior"}]
    }

    def fake_mine_assumption_cracks(
        *,
        query=None,
        seed_kg_ids=None,
        contradiction_frontiers=None,
        limit=10,
    ):
        captured.update(
            {
                "query": query,
                "seed_kg_ids": seed_kg_ids,
                "contradiction_frontiers": contradiction_frontiers,
                "limit": limit,
            }
        )
        return {"cracks": [{"assumption_text": "weights are required"}]}

    monkeypatch.setattr(
        novelty.query_service,
        "mine_assumption_cracks",
        fake_mine_assumption_cracks,
        raising=False,
    )

    tool = novelty.MineAssumptionCracksTool()
    result = tool._run(
        query="structural prior",
        seed_kg_ids=["concept:structural_prior"],
        contradiction_frontiers=frontier_payload,
        limit=6,
    )

    assert result.status == "success"
    assert (
        result.data["result"]["cracks"][0]["assumption_text"] == "weights are required"
    )
    assert captured == {
        "query": "structural prior",
        "seed_kg_ids": ["concept:structural_prior"],
        "contradiction_frontiers": frontier_payload,
        "limit": 6,
    }


def test_find_analogy_transfers_maps_to_query_service_signature(monkeypatch):
    captured: dict[str, object] = {}

    def fake_find_analogy_transfers(
        *,
        query=None,
        seed_kg_ids=None,
        relation_types=None,
        limit=10,
    ):
        captured.update(
            {
                "query": query,
                "seed_kg_ids": seed_kg_ids,
                "relation_types": relation_types,
                "limit": limit,
            }
        )
        return {"transfers": [{"method_family": "reinforcement_learning"}]}

    monkeypatch.setattr(
        novelty.query_service,
        "find_analogy_transfers",
        fake_find_analogy_transfers,
        raising=False,
    )

    tool = novelty.FindAnalogyTransfersTool()
    result = tool._run(
        query="connectomics simulation",
        seed_kg_ids=["concept:connectomics"],
        relation_types=["USES_METHOD"],
        limit=4,
    )

    assert result.status == "success"
    assert (
        result.data["result"]["transfers"][0]["method_family"]
        == "reinforcement_learning"
    )
    assert captured == {
        "query": "connectomics simulation",
        "seed_kg_ids": ["concept:connectomics"],
        "relation_types": ["USES_METHOD"],
        "limit": 4,
    }


def test_sample_ood_hypothesis_maps_to_query_service_signature(monkeypatch):
    captured: dict[str, object] = {}
    leverage_items = [{"kg_id": "node:candidate", "leverage_score": 0.7}]
    leverage_context = {
        "seed_kg_ids": ["node:seed", "node:semantic_seed"],
        "semantic_seed_labels": {"node:semantic_seed": "Semantic Seed"},
    }
    principle_state = {"controller_mode": "principle_v0", "session_key": "pcs_demo"}

    def fake_sample_ood_hypothesis(
        seed_kg_ids,
        *,
        relation_types=None,
        limit=5,
        taste=None,
        leverage_items=None,
        leverage_context=None,
        principle_state=None,
    ):
        captured["seed_kg_ids"] = list(seed_kg_ids)
        captured["relation_types"] = relation_types
        captured["limit"] = limit
        captured["taste"] = taste
        captured["leverage_items"] = leverage_items
        captured["leverage_context"] = leverage_context
        captured["principle_state"] = principle_state
        return {"hypotheses": [{"statement": "H1"}]}

    monkeypatch.setattr(
        novelty.query_service,
        "sample_ood_hypothesis",
        fake_sample_ood_hypothesis,
        raising=False,
    )

    tool = novelty.SampleOODHypothesisTool()
    result = tool._run(
        seed_kg_ids=["node:seed"],
        n_samples=3,
        taste_mode="balanced",
        controller_mode="principle_v0",
        leverage_items=leverage_items,
        leverage_context=leverage_context,
        principle_state=principle_state,
    )

    assert result.status == "success"
    assert result.data["result"] == {"hypotheses": [{"statement": "H1"}]}
    assert result.data["resolved_seed_kg_ids"] == ["node:seed"]
    assert captured == {
        "seed_kg_ids": ["node:seed"],
        "relation_types": None,
        "limit": 3,
        "taste": {"mode": "balanced"},
        "leverage_items": leverage_items,
        "leverage_context": leverage_context,
        "principle_state": principle_state,
    }


def test_principle_state_init_maps_to_controller_signature(monkeypatch):
    captured: dict[str, object] = {}

    def fake_initialize_principle_state(**kwargs):
        captured.update(kwargs)
        return {"session_key": "pcs_demo", "controller_mode": "principle_v0"}

    monkeypatch.setattr(
        novelty,
        "initialize_principle_state",
        fake_initialize_principle_state,
    )

    tool = novelty.PrincipleStateInitTool()
    result = tool._run(
        query="fmri based image decoding",
        seed_kg_ids=["node:seed"],
        relation_types=["ASSOCIATED_WITH"],
        taste_mode="balanced",
        controller_mode="principle_v0",
        leverage_items=[{"kg_id": "node:candidate"}],
    )

    assert result.status == "success"
    assert result.data["result"]["session_key"] == "pcs_demo"
    assert captured == {
        "query": "fmri based image decoding",
        "seed_kg_ids": ["node:seed"],
        "relation_types": ["ASSOCIATED_WITH"],
        "taste_mode": "balanced",
        "controller_mode": "principle_v0",
        "leverage_items": [{"kg_id": "node:candidate"}],
    }


def test_principle_state_update_maps_to_controller_signature(monkeypatch):
    captured: dict[str, object] = {}
    principle_state = {"session_key": "pcs_demo"}
    ood_result = {"summary": {"n_returned": 1}}
    contradiction_result = {"motifs": [{"motif_score": 0.3}]}
    topology_result = {"proposals": [{"delta": 0.2}]}

    def fake_update_principle_state(**kwargs):
        captured.update(kwargs)
        return {
            "session_key": "pcs_demo",
            "selection_reason": "contradiction_triggered",
        }

    monkeypatch.setattr(
        novelty,
        "update_principle_state",
        fake_update_principle_state,
    )

    tool = novelty.PrincipleStateUpdateTool()
    result = tool._run(
        query="fmri based image decoding",
        seed_kg_ids=["node:seed"],
        relation_types=["ASSOCIATED_WITH"],
        taste_mode="balanced",
        controller_mode="principle_v0",
        principle_state=principle_state,
        ood_result=ood_result,
        contradiction_result=contradiction_result,
        topology_result=topology_result,
    )

    assert result.status == "success"
    assert result.data["result"]["selection_reason"] == "contradiction_triggered"
    assert captured == {
        "query": "fmri based image decoding",
        "seed_kg_ids": ["node:seed"],
        "relation_types": ["ASSOCIATED_WITH"],
        "taste_mode": "balanced",
        "controller_mode": "principle_v0",
        "principle_state": principle_state,
        "ood_result": ood_result,
        "contradiction_result": contradiction_result,
        "topology_result": topology_result,
    }


def test_detect_topology_shifts_mode_alias_and_passthrough(monkeypatch):
    captured: dict[str, object] = {}

    def fake_detect_topology_shifts(
        seed_kg_ids=None,
        *,
        limit=50,
        taste=None,
        mode="proposal",
        patch_id=None,
        update_reason=None,
        now_iso=None,
    ):
        captured["seed_kg_ids"] = seed_kg_ids
        captured["limit"] = limit
        captured["taste"] = taste
        captured["mode"] = mode
        captured["patch_id"] = patch_id
        captured["update_reason"] = update_reason
        captured["now_iso"] = now_iso
        return {"ok": True, "mode": mode}

    monkeypatch.setattr(
        novelty.query_service,
        "detect_topology_shifts",
        fake_detect_topology_shifts,
        raising=False,
    )

    tool = novelty.DetectTopologyShiftsTool()
    result = tool._run(
        seed_kg_ids=["node:x"],
        mode="detect",
        limit=12,
        taste_mode="evidence_first",
    )

    assert result.status == "success"
    assert result.data["result"] == {"ok": True, "mode": "proposal"}
    assert captured == {
        "seed_kg_ids": ["node:x"],
        "limit": 12,
        "taste": {"mode": "evidence_first"},
        "mode": "proposal",
        "patch_id": None,
        "update_reason": None,
        "now_iso": None,
    }


def test_sample_and_verify_hypotheses_maps_to_query_service_signature(monkeypatch):
    captured: dict[str, object] = {}

    def fake_sample_and_verify_hypotheses(
        seed_kg_ids,
        *,
        query=None,
        relation_types=None,
        sample_limit=5,
        verify_top_k=None,
        taste=None,
        strictness="high_recall",
        candidate_lane_mode="broad",
        use_external_literature=False,
        external_literature_top_k=5,
        external_literature_recency_days=365,
        external_literature_exclude_domains=None,
        allowed_node_types=None,
        max_evidence=60,
        max_paths=60,
        min_evidence_score=None,
        include_subgraph=False,
        include_path_details=False,
        confidence_scoring_version="v2",
    ):
        captured["seed_kg_ids"] = list(seed_kg_ids)
        captured["query"] = query
        captured["relation_types"] = relation_types
        captured["sample_limit"] = sample_limit
        captured["verify_top_k"] = verify_top_k
        captured["taste"] = taste
        captured["strictness"] = strictness
        captured["candidate_lane_mode"] = candidate_lane_mode
        captured["use_external_literature"] = use_external_literature
        captured["external_literature_top_k"] = external_literature_top_k
        captured["external_literature_recency_days"] = external_literature_recency_days
        captured["external_literature_exclude_domains"] = (
            external_literature_exclude_domains
        )
        captured["allowed_node_types"] = allowed_node_types
        captured["max_evidence"] = max_evidence
        captured["max_paths"] = max_paths
        captured["min_evidence_score"] = min_evidence_score
        captured["include_subgraph"] = include_subgraph
        captured["include_path_details"] = include_path_details
        captured["confidence_scoring_version"] = confidence_scoring_version
        return {
            "sampled_hypotheses": [{"rank": 1, "statement": "H1"}],
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "statement": "H1",
                    "kg_verification": {
                        "verdict": "insufficient_evidence",
                        "confidence": 0.4,
                        "evidence_mode": "union",
                        "evidence_source_scope": "expanded_family",
                        "summary": {
                            "evidence_scope": "union",
                            "evidence_source_scope": "expanded_family",
                        },
                    },
                }
            ],
            "summary": {"n_tested": 1, "n_insufficient_evidence": 1},
        }

    monkeypatch.setattr(
        novelty.query_service,
        "sample_and_verify_hypotheses",
        fake_sample_and_verify_hypotheses,
        raising=False,
    )

    tool = novelty.SampleAndVerifyHypothesesTool()
    result = tool._run(
        seed_kg_ids=["node:seed"],
        n_samples=4,
        verify_top_k=2,
        taste_mode="balanced",
        strictness="conservative",
        candidate_lane_mode="strict",
        allowed_node_types=["Task"],
        include_subgraph=True,
    )

    assert result.status == "success"
    assert result.data["result"]["sampled_hypotheses"] == [
        {"rank": 1, "statement": "H1"}
    ]
    assert result.data["result"]["tested_hypotheses"][0]["kg_verification"] == {
        "verdict": "insufficient_evidence",
        "confidence": 0.4,
        "evidence_mode": "union",
        "evidence_source_scope": "expanded_family",
        "summary": {
            "evidence_scope": "union",
            "evidence_source_scope": "expanded_family",
        },
    }
    assert result.data["resolved_seed_kg_ids"] == ["node:seed"]
    assert captured == {
        "seed_kg_ids": ["node:seed"],
        "query": None,
        "relation_types": None,
        "sample_limit": 4,
        "verify_top_k": 2,
        "taste": {"mode": "balanced"},
        "strictness": "conservative",
        "candidate_lane_mode": "strict",
        "use_external_literature": False,
        "external_literature_top_k": 5,
        "external_literature_recency_days": 365,
        "external_literature_exclude_domains": None,
        "allowed_node_types": ["Task"],
        "max_evidence": 60,
        "max_paths": 60,
        "min_evidence_score": None,
        "include_subgraph": True,
        "include_path_details": False,
        "confidence_scoring_version": "v2",
    }


def test_verify_sampled_hypotheses_maps_to_query_service_signature(monkeypatch):
    captured: dict[str, object] = {}

    def fake_verify_sampled_hypotheses(
        sampled_hypotheses,
        *,
        query=None,
        seed_kg_ids=None,
        verify_top_k=None,
        strictness="high_recall",
        candidate_lane_mode="broad",
        use_external_literature=False,
        external_literature_top_k=5,
        external_literature_recency_days=365,
        external_literature_exclude_domains=None,
        allowed_node_types=None,
        max_evidence=60,
        max_paths=60,
        min_evidence_score=None,
        include_subgraph=False,
        include_path_details=False,
        confidence_scoring_version="v2",
    ):
        captured["sampled_hypotheses"] = sampled_hypotheses
        captured["query"] = query
        captured["seed_kg_ids"] = seed_kg_ids
        captured["verify_top_k"] = verify_top_k
        captured["strictness"] = strictness
        captured["candidate_lane_mode"] = candidate_lane_mode
        captured["use_external_literature"] = use_external_literature
        captured["external_literature_top_k"] = external_literature_top_k
        captured["external_literature_recency_days"] = external_literature_recency_days
        captured["external_literature_exclude_domains"] = (
            external_literature_exclude_domains
        )
        captured["allowed_node_types"] = allowed_node_types
        captured["max_evidence"] = max_evidence
        captured["max_paths"] = max_paths
        captured["min_evidence_score"] = min_evidence_score
        captured["include_subgraph"] = include_subgraph
        captured["include_path_details"] = include_path_details
        captured["confidence_scoring_version"] = confidence_scoring_version
        return {
            "tested_hypotheses": [
                {
                    "rank": 1,
                    "candidate_kg_id": "node:candidate",
                    "kg_verification": {
                        "verdict": "supported",
                        "confidence": 0.61,
                        "evidence_mode": "shared",
                        "evidence_source_scope": "direct",
                    },
                }
            ],
            "summary": {"n_tested": 1, "n_supported": 1},
        }

    monkeypatch.setattr(
        novelty.query_service,
        "verify_sampled_hypotheses",
        fake_verify_sampled_hypotheses,
        raising=False,
    )

    tool = novelty.VerifySampledHypothesesTool()
    result = tool._run(
        sampled_hypotheses=[{"rank": 1, "statement": "H1"}],
        seed_kg_ids=["node:seed"],
        verify_top_k=1,
        strictness="conservative",
        candidate_lane_mode="strict",
        allowed_node_types=["Task"],
        include_subgraph=True,
    )

    assert result.status == "success"
    assert result.data["result"]["summary"] == {"n_tested": 1, "n_supported": 1}
    assert result.data["resolved_seed_kg_ids"] == ["node:seed"]
    assert captured == {
        "sampled_hypotheses": [{"rank": 1, "statement": "H1"}],
        "query": None,
        "seed_kg_ids": ["node:seed"],
        "verify_top_k": 1,
        "strictness": "conservative",
        "candidate_lane_mode": "strict",
        "use_external_literature": False,
        "external_literature_top_k": 5,
        "external_literature_recency_days": 365,
        "external_literature_exclude_domains": None,
        "allowed_node_types": ["Task"],
        "max_evidence": 60,
        "max_paths": 60,
        "min_evidence_score": None,
        "include_subgraph": True,
        "include_path_details": False,
        "confidence_scoring_version": "v2",
    }


def test_detect_topology_shifts_rejects_invalid_mode():
    tool = novelty.DetectTopologyShiftsTool()
    result = tool._run(mode="invalid")

    assert result.status == "error"
    assert result.error == "mode must be one of: proposal, detect, apply"


def test_factory_returns_all_novelty_tools():
    tool_names = [tool.get_tool_name() for tool in novelty.get_all_tools()]
    assert tool_names == [
        "br_kg.find_structural_leverage",
        "br_kg.detect_contradiction_motifs",
        "br_kg.find_contradiction_frontiers",
        "br_kg.mine_assumption_cracks",
        "br_kg.find_analogy_transfers",
        "br_kg.synthesize_wow_candidate_cards",
        "br_kg.principle_state_init",
        "br_kg.sample_ood_hypothesis",
        "br_kg.verify_sampled_hypotheses",
        "br_kg.sample_and_verify_hypotheses",
        "br_kg.detect_topology_shifts",
        "br_kg.principle_state_update",
    ]


def test_find_structural_leverage_fail_open_on_kg_unavailable(monkeypatch):
    def fake_search_nodes(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("network_blocked_by_policy")

    monkeypatch.setattr(
        novelty.query_service,
        "search_nodes",
        fake_search_nodes,
        raising=False,
    )

    tool = novelty.FindStructuralLeverageTool()
    result = tool._run(query="fmri image decoding", limit=3)

    assert result.status == "success"
    assert result.data["resolved_seed_kg_ids"]
    payload = result.data["result"]
    assert payload.get("mode") == "structural_leverage_fallback"
    assert len(payload.get("items", [])) == 3


def test_sample_ood_hypothesis_fail_open_on_kg_unavailable(monkeypatch):
    def fake_search_nodes(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("unable to connect to neo4j: network_blocked_by_policy")

    monkeypatch.setattr(
        novelty.query_service,
        "search_nodes",
        fake_search_nodes,
        raising=False,
    )

    tool = novelty.SampleOODHypothesisTool()
    result = tool._run(query="fmri image decoding", n_samples=2)

    assert result.status == "success"
    assert result.data["resolved_seed_kg_ids"]
    payload = result.data["result"]
    assert payload.get("mode") == "ood_hypothesis_sampling_fallback"
    assert len(payload.get("hypotheses", [])) == 2


def test_sample_and_verify_hypotheses_fail_open_on_kg_unavailable(monkeypatch):
    def fake_search_nodes(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("unable to connect to neo4j: network_blocked_by_policy")

    monkeypatch.setattr(
        novelty.query_service,
        "search_nodes",
        fake_search_nodes,
        raising=False,
    )

    tool = novelty.SampleAndVerifyHypothesesTool()
    result = tool._run(query="fmri image decoding", n_samples=2)

    assert result.status == "success"
    assert result.data["resolved_seed_kg_ids"]
    payload = result.data["result"]
    assert payload.get("mode") == "hypothesis_testing_fallback"
    assert payload.get("summary", {}).get("n_tested") == 0


def test_detect_topology_shifts_fail_open_only_for_non_apply(monkeypatch):
    def fake_detect_topology_shifts(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("network_blocked_by_policy")

    monkeypatch.setattr(
        novelty.query_service,
        "detect_topology_shifts",
        fake_detect_topology_shifts,
        raising=False,
    )

    tool = novelty.DetectTopologyShiftsTool()

    proposal_result = tool._run(seed_kg_ids=["node:x"], mode="proposal")
    assert proposal_result.status == "success"
    assert (
        proposal_result.data["result"].get("mode") == "topology_shift_proposal_fallback"
    )

    apply_result = tool._run(seed_kg_ids=["node:x"], mode="apply")
    assert apply_result.status == "error"
