from __future__ import annotations

from brain_researcher.services.neurokg import query_service


class FakeResult(list):
    def single(self):  # pragma: no cover - compatibility helper
        return self[0] if self else None


class FakeEmptyDB:
    def _run(self, _cypher, _params=None):
        return FakeResult([])


class FakeTopologyDB:
    def __init__(self):
        self.edges = {
            ("seed:a", "node:x", "ASSOCIATED_WITH"): {
                "taste_weight": 0.20,
                "novelty_score": 0.90,
                "contradiction_score": 0.60,
                "evidence_quality": 0.40,
            },
            ("seed:a", "node:y", "ASSOCIATED_WITH"): {
                "taste_weight": 0.80,
                "novelty_score": 0.10,
                "contradiction_score": 0.10,
                "evidence_quality": 0.90,
            },
        }
        self.applied_calls: list[dict[str, object]] = []

    def _run(self, cypher, params=None):
        params = params or {}
        if (
            "AS source_id" in cypher
            and "AS target_id" in cypher
            and "AS rel_type" in cypher
        ):
            seed_ids = params.get("seed_ids")
            rows = []
            for (src, dst, rel), props in self.edges.items():
                if seed_ids and src not in seed_ids and dst not in seed_ids:
                    continue
                rows.append(
                    {
                        "source_id": src,
                        "target_id": dst,
                        "rel_type": rel,
                        "taste_weight": props["taste_weight"],
                        "novelty_score": props["novelty_score"],
                        "contradiction_score": props["contradiction_score"],
                        "evidence_quality": props["evidence_quality"],
                    }
                )
            return FakeResult(rows)

        if "SET" in cypher and "taste_prev_weight" in cypher:
            key = (params["source_id"], params["target_id"], params["rel_type"])
            edge = self.edges.get(key)
            if edge is None:
                return FakeResult([])
            edge["taste_prev_weight"] = edge.get(
                "taste_weight", params["current_weight"]
            )
            edge["taste_weight"] = params["new_weight"]
            edge["taste_patch_id"] = params["patch_id"]
            edge["taste_updated_at"] = params["updated_at"]
            edge["taste_update_reason"] = params["update_reason"]
            self.applied_calls.append({"cypher": cypher, "params": dict(params)})
            return FakeResult([{"updated": 1}])

        return FakeResult([])


def test_empty_no_seed_handling_returns_structured_warning():
    out_leverage = query_service.find_structural_leverage([], db=FakeEmptyDB())
    assert out_leverage["ok"] is True
    assert out_leverage["items"] == []
    assert any("No seed_kg_ids" in w for w in out_leverage["warnings"])

    out_ood = query_service.sample_ood_hypothesis(None, db=FakeEmptyDB())
    assert out_ood["ok"] is True
    assert out_ood["hypotheses"] == []
    assert any("No seed_kg_ids" in w for w in out_ood["warnings"])


def test_novelty_first_ranking_is_deterministic(monkeypatch):
    def fake_neighbors(kg_id, **kwargs):
        del kwargs
        if kg_id != "seed:a":
            return []
        return [
            {
                "kg_id": "node:low_novelty",
                "label": "Low Novelty",
                "node_type": "Concept",
                "relation": "RELATED_TO",
                "score": 0.95,
            },
            {
                "kg_id": "node:high_novelty",
                "label": "High Novelty",
                "node_type": "Concept",
                "relation": "RELATED_TO",
                "score": 0.10,
            },
        ]

    monkeypatch.setattr(query_service, "neighbors", fake_neighbors)

    r1 = query_service.find_structural_leverage(["seed:a"], db=FakeEmptyDB())
    r2 = query_service.find_structural_leverage(["seed:a"], db=FakeEmptyDB())

    ids1 = [row["kg_id"] for row in r1["items"]]
    ids2 = [row["kg_id"] for row in r2["items"]]

    assert ids1 == ids2
    assert ids1[0] == "node:high_novelty"
    assert r1["taste"]["mode"] == "novelty_first"
    assert r1["taste"]["weights"]["novelty"] > r1["taste"]["weights"]["evidence"]


def test_detect_contradiction_motif_from_mocked_evidence():
    evidence = [
        {
            "publication": {"kg_id": "pmid:1", "label": "Paper A"},
            "polarity": "supports",
            "score": 0.80,
            "claim": {"text": "supports relation"},
        },
        {
            "publication": {"kg_id": "pmid:1", "label": "Paper A"},
            "polarity": "refutes",
            "score": 0.70,
            "claim": {"text": "refutes relation"},
        },
        {
            "publication": {"kg_id": "pmid:2", "label": "Paper B"},
            "polarity": "supports",
            "score": 0.90,
            "claim": {"text": "only support"},
        },
    ]

    out = query_service.detect_contradiction_motifs(evidence_items=evidence)

    assert out["ok"] is True
    assert out["summary"]["n_motifs"] == 1
    motif = out["motifs"][0]
    assert motif["motif_type"] == "publication_polarity_conflict"
    assert motif["publication_id"] == "pmid:1"
    assert motif["support_count"] == 1
    assert motif["conflict_count"] == 1


def test_find_contradiction_frontiers_groups_conflicts(monkeypatch):
    def fake_verify_hypothesis(*args, **kwargs):
        del args, kwargs
        return {
            "supporting_evidence": [
                {
                    "publication": {"kg_id": "pmid:1", "label": "Paper A"},
                    "polarity": "supports",
                    "score": 0.8,
                    "claim": {
                        "text": "structure predicts behavior",
                        "main_assumption_text": "weights are required",
                        "assumption_type": "sufficiency",
                        "defaultness_score": 0.7,
                        "challengeability_score": 0.8,
                    },
                }
            ],
            "conflicting_evidence": [
                {
                    "publication": {"kg_id": "pmid:2", "label": "Paper B"},
                    "polarity": "refutes",
                    "score": 0.7,
                    "claim": {
                        "text": "structure predicts behavior",
                        "main_assumption_text": "weights are required",
                        "assumption_type": "sufficiency",
                        "defaultness_score": 0.7,
                        "challengeability_score": 0.8,
                    },
                }
            ],
        }

    monkeypatch.setattr(query_service, "verify_hypothesis", fake_verify_hypothesis)

    out = query_service.find_contradiction_frontiers(
        query="structural prior",
        seed_kg_ids=["concept:structural_prior"],
        db=FakeEmptyDB(),
    )

    assert out["ok"] is True
    assert out["summary"]["n_frontiers"] == 1
    frontier = out["frontiers"][0]
    assert frontier["broken_default_assumption"] == "weights are required"
    assert frontier["support_count"] == 1
    assert frontier["conflict_count"] == 1
    assert frontier["frontier_score"] > 0.0


def test_mine_assumption_cracks_from_frontiers():
    out = query_service.mine_assumption_cracks(
        contradiction_frontiers={
            "frontiers": [
                {
                    "frontier_label": "structure predicts behavior",
                    "broken_default_assumption": "weights are required",
                    "assumption_type": "sufficiency",
                    "defaultness_score": 0.8,
                    "challengeability_score": 0.7,
                    "frontier_score": 0.75,
                    "publication_count": 2,
                    "publication_labels": ["Paper A", "Paper B"],
                    "seed_kg_ids": ["concept:structural_prior"],
                    "contradiction_signature": "support/conflict=1/1; null=0; failed_replication=0",
                }
            ]
        },
        db=FakeEmptyDB(),
    )

    assert out["ok"] is True
    crack = out["cracks"][0]
    assert crack["assumption_text"] == "weights are required"
    assert crack["assumption_crack_score"] > 0.0
    assert "weights are required" in crack["minimal_falsification_test"].lower()


def test_find_analogy_transfers_detects_absent_family(monkeypatch):
    monkeypatch.setattr(
        query_service,
        "node_details",
        lambda kg_id, **kwargs: query_service.KGNodeSummary(
            kg_id=kg_id,
            label="connectomics",
            node_type="Concept",
            properties={},
        ),
    )
    monkeypatch.setattr(
        query_service,
        "neighbors",
        lambda kg_id, **kwargs: [],
    )

    def fake_search_nodes(
        query, *, node_types=None, limit=20, db=None, infer_types=True, timeout_s=None
    ):
        del node_types, limit, db, infer_types, timeout_s
        if "reinforcement learning" in query:
            return [
                query_service.KGNodeSummary(
                    kg_id="method:rl",
                    label="Reinforcement Learning Controller",
                    node_type="Method",
                    properties={},
                )
            ]
        return []

    monkeypatch.setattr(query_service, "search_nodes", fake_search_nodes)

    out = query_service.find_analogy_transfers(
        query="connectomics simulation",
        seed_kg_ids=["concept:connectomics"],
        db=FakeEmptyDB(),
    )

    assert out["ok"] is True
    assert out["transfers"]
    transfer = out["transfers"][0]
    assert transfer["method_family"] == "reinforcement_learning"
    assert transfer["transfer_score"] > 0.0


def test_synthesize_wow_candidate_cards_ranks_non_bridge_candidates():
    out = query_service.synthesize_wow_candidate_cards(
        query="structural prior",
        contradiction_frontiers={
            "frontiers": [
                {
                    "frontier_label": "structure predicts behavior",
                    "contradiction_signature": "support/conflict=1/1; null=0; failed_replication=0",
                    "frontier_score": 0.75,
                    "publication_count": 2,
                    "publication_labels": ["Paper A", "Paper B"],
                    "seed_kg_ids": ["concept:structural_prior"],
                }
            ]
        },
        assumption_cracks={
            "cracks": [
                {
                    "assumption_text": "weights are required",
                    "assumption_type": "sufficiency",
                    "defaultness_score": 0.8,
                    "challengeability_score": 0.7,
                    "assumption_crack_score": 0.78,
                    "publication_count": 2,
                    "supporting_nodes": [
                        {"node_type": "Publication", "label": "Paper A"}
                    ],
                    "touched_domains": ["connectomics", "simulation"],
                    "contradiction_signature": "support/conflict=1/1; null=0; failed_replication=0",
                    "minimal_falsification_test": "Relax the weights are required assumption and compare fit.",
                    "seed_kg_ids": ["concept:structural_prior"],
                }
            ]
        },
        limit=3,
    )

    assert out["ok"] is True
    assert out["candidate_cards"]
    card = out["candidate_cards"][0]
    assert card["wow_score"] > 0.0
    assert card["execution_gap_only"] is False


def test_detect_topology_shifts_proposal_and_apply():
    db = FakeTopologyDB()

    proposal = query_service.detect_topology_shifts(
        ["seed:a"],
        mode="proposal",
        db=db,
    )
    assert proposal["ok"] is True
    assert proposal["mode"] == "proposal"
    assert proposal["applied_count"] == 0
    assert proposal["summary"]["n_proposals"] == len(proposal["proposals"])
    assert proposal["proposals"]
    assert proposal["proposals"][0]["edge"]["target_id"] == "node:y"
    assert (
        proposal["diagnostics"]["scan_record_count"] == proposal["summary"]["n_scanned"]
    )
    assert proposal["diagnostics"]["phase_totals_s"]["scan_query"] >= 0.0
    assert proposal["diagnostics"]["phase_totals_s"]["proposal_build"] >= 0.0
    assert proposal["diagnostics"]["total_duration_s"] >= 0.0

    apply_out = query_service.detect_topology_shifts(
        ["seed:a"],
        mode="apply",
        patch_id="patch_unit_test",
        now_iso="2026-03-03T00:00:00Z",
        update_reason="unit_test_reason",
        db=db,
    )
    assert apply_out["ok"] is True
    assert apply_out["mode"] == "apply"
    assert apply_out["applied_count"] == len(apply_out["proposals"])
    assert apply_out["patch"]["patch_id"] == "patch_unit_test"
    assert apply_out["patch"]["updated_at"] == "2026-03-03T00:00:00Z"
    assert apply_out["diagnostics"]["phase_totals_s"]["apply_writes"] >= 0.0
    assert len(apply_out["diagnostics"]["per_proposal"]) == len(apply_out["proposals"])
    assert apply_out["diagnostics"]["per_proposal"][0]["status"] == "applied"
    assert db.applied_calls
    for call in db.applied_calls:
        cypher = str(call["cypher"]).upper()
        assert "SET" in cypher
        assert "TASTE_PREV_WEIGHT" in cypher
        assert "TASTE_WEIGHT" in cypher
        assert "TASTE_PATCH_ID" in cypher
        assert "TASTE_UPDATED_AT" in cypher
        assert "TASTE_UPDATE_REASON" in cypher
        assert "CREATE " not in cypher
        assert "DELETE " not in cypher


def test_publication_seed_normalizes_to_semantic_anchor_and_filters_noise(monkeypatch):
    publication_detail = query_service.KGNodeSummary(
        kg_id="pub:seed",
        label="",
        node_type="Publication",
        properties={"title": "Neural decoding of goal locations in spatial navigation"},
    )
    task_detail = query_service.KGNodeSummary(
        kg_id="task:nav",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id in {"doi:seed", "pub:seed"}:
            return publication_detail
        if kg_id == "task:nav":
            return task_detail
        return None

    def fake_neighbors(kg_id, **kwargs):
        del kwargs
        if kg_id == "pub:seed":
            return [
                {
                    "kg_id": "task:nav",
                    "label": "Spatial navigation",
                    "node_type": "Task",
                    "relation": "ABOUT",
                    "score": 0.85,
                }
            ]
        if kg_id == "task:nav":
            return [
                {
                    "kg_id": "term:better",
                    "label": "better",
                    "node_type": "Concept",
                    "relation": "HAS_TERM",
                    "score": 1.0,
                },
                {
                    "kg_id": "coord:1",
                    "label": "4:61f2a6e6-9289-4db3-a996-562b57f61fe1:181461",
                    "node_type": "Coordinate",
                    "relation": "HAS_COORDINATE",
                    "score": 1.0,
                },
                {
                    "kg_id": "task:memory",
                    "label": "Episodic memory retrieval",
                    "node_type": "Task",
                    "relation": "RELATED_TO",
                    "score": 0.48,
                },
            ]
        return []

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "neighbors", fake_neighbors)
    monkeypatch.setattr(
        query_service,
        "search_gfs",
        lambda *args, **kwargs: {"status": "empty", "hits": []},
    )

    leverage = query_service.find_structural_leverage(["doi:seed"], db=FakeEmptyDB())
    assert leverage["seed_kg_ids"] == ["task:nav"]
    assert leverage["semantic_seed_labels"] == {"task:nav": "Spatial navigation"}
    assert [item["kg_id"] for item in leverage["items"]] == ["task:memory"]
    assert leverage["items"][0]["candidate_type"] == "Task"
    assert leverage["rejections"]["generic_label"] >= 1
    assert leverage["rejections"]["relation_filtered"] >= 1
    assert leverage["rejections"]["node_type_filtered"] >= 1

    sampled = query_service.sample_ood_hypothesis(["doi:seed"], db=FakeEmptyDB())
    assert sampled["seed_kg_ids"] == ["task:nav"]
    assert sampled["summary"]["n_requested"] == 5
    assert sampled["summary"]["n_hypotheses"] == 1
    assert sampled["summary"]["n_returned"] == 1
    assert sampled["summary"]["n_vetoed"] == 0
    assert sampled["summary"]["n_rewrite_failed"] == 0
    row = sampled["hypotheses"][0]
    assert row["anchor_label"] == "Spatial navigation"
    assert row["anchor_type"] == "Task"
    assert row["candidate_kg_id"] == "task:memory"
    assert row["candidate_label"] == "Episodic memory retrieval"
    assert row["candidate_type"] == "Task"
    assert row["claim_type"] == "transfer"
    assert row["rewrite_mode"] == "heuristic"
    assert row["verification_status"] == "unverified"
    assert "out-of-distribution coupling" not in row["statement"]
    assert row["statement"].lower().startswith("if ")
    assert " then " in row["statement"].lower()
    assert row["hypothesis_sentence"] == row["statement"]
    assert row["mechanism"]
    assert row["independent_variable"]
    assert row["dependent_variable"]
    assert row["control_condition"]
    assert row["predicted_direction"]
    assert row["prediction"]
    assert row["minimal_test"]
    assert row["falsifier"]
    assert row["anchor_nodes"] == [
        {"kg_id": "task:nav", "label": "Spatial navigation"},
        {"kg_id": "task:memory", "label": "Episodic memory retrieval"},
    ]


def test_assess_ood_hypothesis_draft_rejects_generic_transfer_templates():
    ok, reasons = query_service._assess_ood_hypothesis_draft(
        {
            "claim_type": "transfer",
            "statement": (
                "Representations supporting decoding in Spatial navigation may "
                "partially transfer to Working Memory because both depend on a "
                "shared task-family demand profile."
            ),
            "hypothesis_sentence": (
                "Representations supporting decoding in Spatial navigation may "
                "partially transfer to Working Memory because both depend on a "
                "shared task-family demand profile."
            ),
            "mechanism": (
                "The proposed mechanism is a shared task-family demand profile "
                "linking Spatial navigation to Working Memory."
            ),
            "independent_variable": "conditions emphasizing Working Memory",
            "dependent_variable": "cross-condition transfer",
            "control_condition": "",
            "predicted_direction": (
                "should generalize above matched controls when evaluated on Working "
                "Memory"
            ),
            "prediction": (
                "should generalize above matched controls when evaluated on Working "
                "Memory"
            ),
            "minimal_test": (
                "Train on Spatial navigation and test on Working Memory against a "
                "baseline."
            ),
            "falsifier": (
                "Reject if cross-condition performance between Spatial navigation and "
                "Working Memory stays at control levels."
            ),
        },
        anchor_label="Spatial navigation",
        candidate_label="Working Memory",
    )

    assert ok is False
    assert "generic_mechanism" in reasons
    assert "generic_predicted_direction" in reasons
    assert "independent_variable_not_manipulable" in reasons
    assert "missing_control_condition" in reasons


def test_triage_ood_candidate_semantics_kills_self_anchor_echo():
    triage = query_service._triage_ood_candidate_semantics(
        anchor_id="region:dlpfc",
        candidate_id="region:dlpfc",
        anchor_label="Dorsolateral Prefrontal Cortex",
        candidate_label="Dorsolateral Prefrontal Cortex",
        anchor_type="BrainRegion",
        candidate_type="BrainRegion",
        claim_type="mechanism",
        mechanism="Dorsolateral Prefrontal Cortex may carry information required for the decoding effect.",
    )

    assert triage["decision"] == "kill"
    assert "self_anchor_echo" in triage["reasons"]


def test_triage_ood_candidate_semantics_downranks_same_family_variant():
    triage = query_service._triage_ood_candidate_semantics(
        anchor_id="task:fear",
        candidate_id="task:differential",
        anchor_label="Classical Fear Conditioning Task",
        candidate_label="Differential Classical Fear Conditioning",
        anchor_type="Task",
        candidate_type="Task",
        claim_type="transfer",
        mechanism=(
            "Classical Fear Conditioning Task and Differential Classical Fear "
            "Conditioning may rely on the same representation-carrying bottleneck "
            "rather than only sharing a task family."
        ),
    )

    assert triage["decision"] == "downrank"
    assert "same_family_variant" in triage["reasons"]


def test_triage_ood_candidate_semantics_kills_abstract_family_substitution():
    triage = query_service._triage_ood_candidate_semantics(
        anchor_id="task:fear",
        candidate_id="taskfamily:affective",
        anchor_label="Classical Fear Conditioning Task",
        candidate_label="Affective & Preference Tasks",
        anchor_type="Task",
        candidate_type="TaskFamily",
        claim_type="transfer",
        mechanism=(
            "Classical Fear Conditioning Task and Affective & Preference Tasks may "
            "rely on the same representation-carrying bottleneck rather than only "
            "sharing a task family."
        ),
    )

    assert triage["decision"] == "kill"
    assert "abstract_family_substitution" in triage["reasons"]


def test_sample_ood_hypothesis_enriches_raw_publication_anchor_label(monkeypatch):
    publication_detail = query_service.KGNodeSummary(
        kg_id="doi:seed",
        label="",
        node_type="Publication",
        properties={
            "title": "Neural decoding of goal locations in spatial navigation in humans with fMRI"
        },
    )

    monkeypatch.setattr(
        query_service,
        "find_structural_leverage",
        lambda *args, **kwargs: {
            "ok": True,
            "seed_kg_ids": ["task:nav"],
            "semantic_seed_labels": {"task:nav": "Spatial navigation"},
            "semantic_seed_types": {"task:nav": "Task"},
            "summary": {"n_rejected": 0},
            "items": [
                {
                    "kg_id": "task:reorientation",
                    "label": "Boundary Geometry Reorientation",
                    "node_type": "Task",
                    "candidate_type": "Task",
                    "seeds_touched": ["doi:seed"],
                    "relations": ["RELATED_TO"],
                    "novelty_score": 0.41,
                    "leverage_score": 0.52,
                    "score_breakdown": {"domain_overlap_score": 0.61},
                }
            ],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        query_service, "node_details", lambda *_a, **_k: publication_detail
    )
    monkeypatch.setattr(
        query_service,
        "search_gfs",
        lambda *args, **kwargs: {"status": "empty", "hits": []},
    )

    out = query_service.sample_ood_hypothesis(["doi:seed"], db=FakeEmptyDB())

    assert out["summary"]["n_returned"] == 1
    row = out["hypotheses"][0]
    assert (
        row["anchor_label"]
        == "Neural decoding of goal locations in spatial navigation in humans with fMRI"
    )
    assert row["anchor_type"] == "Publication"
    assert row["candidate_label"] == "Boundary Geometry Reorientation"


def test_sample_ood_hypothesis_hard_vetoes_direct_prior_art(monkeypatch):
    seed_detail = query_service.KGNodeSummary(
        kg_id="task:seed",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:seed":
            return seed_detail
        return None

    def fake_neighbors(kg_id, **kwargs):
        del kwargs
        if kg_id != "task:seed":
            return []
        return [
            {
                "kg_id": "task:wm",
                "label": "Working memory updating",
                "node_type": "Task",
                "relation": "BELONGS_TO_FAMILY",
                "score": 0.41,
            },
            {
                "kg_id": "task:strategy",
                "label": "Navigational planning",
                "node_type": "Task",
                "relation": "RELATED_TO",
                "score": 0.52,
            },
        ]

    def fake_search_gfs(query, **kwargs):
        del kwargs
        lowered = str(query).lower()
        if "working memory" in lowered and "spatial" in lowered:
            return {
                "status": "ok",
                "hits": [
                    {
                        "title": "Decoding transfer between spatial navigation and working memory",
                        "snippet": "This study decodes spatial navigation and working memory with a shared classifier.",
                        "score": 0.92,
                        "doi": "10.1000/example",
                    }
                ],
            }
        if "navigational planning" in lowered:
            return {
                "status": "ok",
                "hits": [
                    {
                        "title": "Neural planning signals during navigation",
                        "snippet": "Navigation planning recruits canonical neuroscience task systems.",
                        "score": 0.67,
                    }
                ],
            }
        return {"status": "empty", "hits": []}

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "neighbors", fake_neighbors)
    monkeypatch.setattr(query_service, "search_gfs", fake_search_gfs)
    monkeypatch.setenv("BR_FILE_SEARCH_STORE_NAMES", "fileSearchStores/papers-a")

    out = query_service.sample_ood_hypothesis(["task:seed"], limit=10, db=FakeEmptyDB())

    assert [row["candidate_kg_id"] for row in out["hypotheses"]] == ["task:strategy"]
    assert out["summary"]["n_vetoed"] == 1
    assert out["vetoed_candidates"][0]["candidate_kg_id"] == "task:wm"
    assert out["vetoed_candidates"][0]["verification_reason"] == "direct_prior_art"


def test_sample_ood_hypothesis_hard_vetoes_no_shared_research_context(monkeypatch):
    seed_detail = query_service.KGNodeSummary(
        kg_id="pub:seed",
        label="",
        node_type="Publication",
        properties={"title": "Neural decoding of goal locations in spatial navigation"},
    )
    task_detail = query_service.KGNodeSummary(
        kg_id="task:nav",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id in {"pub:seed", "doi:seed"}:
            return seed_detail
        if kg_id == "task:nav":
            return task_detail
        return None

    def fake_neighbors(kg_id, **kwargs):
        del kwargs
        if kg_id == "pub:seed":
            return [
                {
                    "kg_id": "task:nav",
                    "label": "Spatial navigation",
                    "node_type": "Task",
                    "relation": "ABOUT",
                    "score": 0.88,
                }
            ]
        if kg_id == "task:nav":
            return [
                {
                    "kg_id": "concept:oa",
                    "label": "Osteoarthritis",
                    "node_type": "Concept",
                    "relation": "RELATED_TO",
                    "score": 0.18,
                }
            ]
        return []

    def fake_search_gfs(query, **kwargs):
        del kwargs
        lowered = str(query).lower()
        if "osteoarthritis" in lowered:
            return {"status": "empty", "hits": []}
        return {"status": "empty", "hits": []}

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "neighbors", fake_neighbors)
    monkeypatch.setattr(query_service, "search_gfs", fake_search_gfs)
    monkeypatch.setenv("BR_FILE_SEARCH_STORE_NAMES", "fileSearchStores/papers-a")

    out = query_service.sample_ood_hypothesis(["doi:seed"], limit=10, db=FakeEmptyDB())

    assert out["hypotheses"] == []
    assert out["summary"]["n_vetoed"] == 1
    assert out["vetoed_candidates"][0]["candidate_kg_id"] == "concept:oa"
    assert (
        out["vetoed_candidates"][0]["verification_reason"]
        == "no_shared_research_context"
    )


def test_sample_ood_hypothesis_uses_precomputed_leverage_items_and_principle_state(
    monkeypatch,
):
    seed_detail = query_service.KGNodeSummary(
        kg_id="task:seed",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fail_find_structural_leverage(*args, **kwargs):
        del args, kwargs
        raise AssertionError("find_structural_leverage should not be called")

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:seed":
            return seed_detail
        return None

    monkeypatch.setattr(
        query_service,
        "find_structural_leverage",
        fail_find_structural_leverage,
    )
    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_gfs",
        lambda *args, **kwargs: {"status": "empty", "hits": []},
    )

    leverage_items = [
        {
            "kg_id": "task:novelty",
            "label": "Novelty-weighted candidate",
            "node_type": "Task",
            "candidate_type": "Task",
            "seeds_touched": ["task:seed"],
            "relations": ["RELATED_TO"],
            "novelty_score": 0.91,
            "leverage_score": 0.55,
            "coherence_score": 0.42,
            "feasibility_score": 0.25,
            "score_breakdown": {
                "novelty_score": 0.91,
                "coherence_score": 0.42,
                "feasibility_score": 0.25,
                "bridge_score": 0.30,
            },
        },
        {
            "kg_id": "task:evidence",
            "label": "Evidence-weighted candidate",
            "node_type": "Task",
            "candidate_type": "Task",
            "seeds_touched": ["task:seed"],
            "relations": ["RELATED_TO"],
            "novelty_score": 0.51,
            "leverage_score": 0.61,
            "coherence_score": 0.84,
            "feasibility_score": 0.88,
            "score_breakdown": {
                "novelty_score": 0.51,
                "coherence_score": 0.84,
                "feasibility_score": 0.88,
                "bridge_score": 0.64,
            },
        },
    ]
    principle_state = {
        "controller_mode": "principle_v0",
        "session_key": "pcs_demo",
        "active_principle_id": "evidence_first",
        "active_principle": {
            "principle_id": "evidence_first",
            "label": "Evidence-first search",
            "kind": "base",
            "weights": {
                "feasibility_score": 0.45,
                "coherence_score": 0.30,
                "leverage_score": 0.15,
                "novelty_score": 0.10,
            },
        },
        "posterior": {"evidence_first": 0.9, "novelty_first": 0.1},
        "anomaly_flags": ["contradiction"],
    }

    out = query_service.sample_ood_hypothesis(
        ["task:seed"],
        limit=2,
        leverage_items=leverage_items,
        principle_state=principle_state,
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_returned"] == 2
    assert [row["candidate_kg_id"] for row in out["hypotheses"]] == [
        "task:evidence",
        "task:novelty",
    ]
    assert out["principle_session_key"] == "pcs_demo"
    assert out["active_principle"]["principle_id"] == "evidence_first"
    assert out["selection_reason"] == "evidence_first:weighted_rerank"
    assert out["anomaly_flags"] == ["contradiction"]
    assert (
        out["hypotheses"][0]["principle_score"]
        > out["hypotheses"][1]["principle_score"]
    )
    assert out["hypotheses"][0]["principle_session_key"] == "pcs_demo"
    assert out["hypotheses"][0]["anomaly_flags"] == ["contradiction"]
    assert [row["candidate_kg_id"] for row in out["candidates_ordered"]] == [
        "task:evidence",
        "task:novelty",
    ]
    assert out["candidates_ordered"][0]["rank_before_rerank"] == 2
    assert out["candidates_ordered"][0]["rank_after_rerank"] == 1
    assert (
        out["candidates_ordered"][0]["verification_reason"]
        == "gfs_paper_store_unconfigured"
    )
    assert out["candidates_ordered"][0]["principle_score"] is not None


def test_sample_ood_hypothesis_precomputed_context_preserves_semantic_seed_context(
    monkeypatch,
):
    monkeypatch.setattr(
        query_service,
        "find_structural_leverage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("find_structural_leverage should not be called")
        ),
    )

    node_calls: list[str] = []

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        node_calls.append(kg_id)
        if kg_id == "doi:seed":
            raise AssertionError(
                "raw input seed should not be reloaded when leverage_context is present"
            )
        if kg_id == "task:nav":
            return query_service.KGNodeSummary(
                kg_id="task:nav",
                label="Spatial navigation",
                node_type="Task",
                properties={"label": "Spatial navigation"},
            )
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "_maybe_llm_rewrite_ood_candidate",
        lambda draft: (draft, "rule_based"),
    )
    monkeypatch.setattr(
        query_service,
        "_verify_ood_candidate_with_gfs",
        lambda **_kwargs: {
            "verification_status": "survived",
            "verification_reason": "no_hard_veto",
            "verification_evidence": {},
        },
    )

    leverage_context = {
        "seed_kg_ids": ["task:nav"],
        "semantic_seed_labels": {"task:nav": "Spatial navigation"},
        "semantic_seed_types": {"task:nav": "Task"},
        "seed_provenance": {"task:nav": ["expanded_from:doi:seed:ABOUT"]},
        "summary": {"n_rejected": 2},
        "rejections": {"generic_label": 2},
    }

    out = query_service.sample_ood_hypothesis(
        ["doi:seed"],
        limit=1,
        leverage_items=[
            {
                "kg_id": "task:memory",
                "label": "Episodic memory retrieval",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:nav"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.61,
                "coherence_score": 0.74,
                "feasibility_score": 0.58,
                "leverage_score": 0.63,
                "score_breakdown": {
                    "novelty_score": 0.61,
                    "coherence_score": 0.74,
                    "feasibility_score": 0.58,
                    "bridge_score": 0.41,
                },
            }
        ],
        leverage_context=leverage_context,
        db=FakeEmptyDB(),
    )

    assert out["seed_kg_ids"] == ["task:nav"]
    assert out["semantic_seed_labels"] == {"task:nav": "Spatial navigation"}
    assert out["semantic_seed_types"] == {"task:nav": "Task"}
    assert out["seed_provenance"] == {"task:nav": ["expanded_from:doi:seed:ABOUT"]}
    assert out["summary"]["n_rejected_pre_synthesis"] == 2
    assert out["rejections"] == {"generic_label": 2}
    assert out["hypotheses"][0]["seed_kg_id"] == "task:nav"
    assert out["hypotheses"][0]["anchor_label"] == "Spatial navigation"
    assert out["hypotheses"][0]["anchor_type"] == "Task"
    assert out["hypotheses"][0]["anchor_nodes"][0] == {
        "kg_id": "task:nav",
        "label": "Spatial navigation",
    }
    assert "doi:seed" not in node_calls


def test_sample_ood_hypothesis_adds_non_publication_support_seed_to_verification_hints(
    monkeypatch,
):
    publication_detail = query_service.KGNodeSummary(
        kg_id="10.1016/j.neuroimage.2015.07.054",
        label="A group ICA based framework for evaluating resting state",
        node_type="Publication",
        properties={
            "title": "A group ICA based framework for evaluating resting state"
        },
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "10.1016/j.neuroimage.2015.07.054":
            return publication_detail
        return None

    monkeypatch.setattr(
        query_service,
        "find_structural_leverage",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("find_structural_leverage should not be called")
        ),
    )
    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "_maybe_llm_rewrite_ood_candidate",
        lambda draft: (draft, "rule_based"),
    )
    monkeypatch.setattr(
        query_service,
        "_verify_ood_candidate_with_gfs",
        lambda **_kwargs: {
            "verification_status": "survived",
            "verification_reason": "no_hard_veto",
            "verification_evidence": {},
        },
    )

    leverage_context = {
        "seed_kg_ids": ["task:nav", "concept:fmri_decoding"],
        "semantic_seed_labels": {
            "task:nav": "Spatial navigation",
            "concept:fmri_decoding": "fMRI decoding",
        },
        "semantic_seed_types": {
            "task:nav": "Task",
            "concept:fmri_decoding": "Concept",
        },
        "summary": {"n_rejected": 0},
    }

    out = query_service.sample_ood_hypothesis(
        ["10.1016/j.neuroimage.2015.07.054"],
        limit=1,
        leverage_items=[
            {
                "kg_id": "neurostore_task:7CEgPb3CFbSU:behavioral:0",
                "label": "Brief Assessment of Cognition in Schizophrenia (BACS)",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["10.1016/j.neuroimage.2015.07.054", "12180"],
                "relations": ["SEARCH_EXPANDED"],
                "novelty_score": 0.61,
                "coherence_score": 0.74,
                "feasibility_score": 0.58,
                "leverage_score": 0.63,
                "score_breakdown": {
                    "novelty_score": 0.61,
                    "coherence_score": 0.74,
                    "feasibility_score": 0.58,
                    "bridge_score": 0.41,
                },
            }
        ],
        leverage_context=leverage_context,
        db=FakeEmptyDB(),
    )

    row = out["hypotheses"][0]
    assert row["seed_kg_id"] == "10.1016/j.neuroimage.2015.07.054"
    assert row["anchor_type"] == "Publication"
    assert row["verification_hints"]["quality"] == "exact_pair"
    assert row["verification_hints"]["entity_hints"] == [
        "neurostore_task:7CEgPb3CFbSU:behavioral:0",
        "concept:fmri_decoding",
    ]
    assert row["verification_hints"]["allowed_node_types"] == ["Task", "Concept"]


def test_select_ood_verification_support_seed_prefers_task_or_concept_over_dataset():
    support_seed = query_service._select_ood_verification_support_seed(
        touched_seeds=["ds:openneuro:ds002717", "concept:fmri_decoding"],
        fallback_seeds=["ds:openneuro:ds002717", "concept:fmri_decoding"],
        seed_types={
            "ds:openneuro:ds002717": "Dataset",
            "concept:fmri_decoding": "Concept",
        },
        seed_labels={
            "ds:openneuro:ds002717": "OpenNeuro ds002717",
            "concept:fmri_decoding": "fMRI decoding",
        },
        candidate_type="Task",
        exclude_ids={"neurostore_task:7CEgPb3CFbSU:behavioral:0"},
    )

    assert support_seed == "concept:fmri_decoding"


def test_build_hypothesis_testing_hint_bundle_prefers_support_pair_over_dataset_seed():
    bundle = query_service._build_hypothesis_testing_hint_bundle(
        {
            "seed_kg_id": "ds:openneuro:ds002717",
            "anchor_label": "OpenNeuro ds002717",
            "anchor_type": "Dataset",
            "candidate_kg_id": "neurostore_task:7CEgPb3CFbSU:behavioral:0",
            "candidate_label": "Brief Assessment of Cognition in Schizophrenia (BACS)",
            "candidate_type": "Task",
            "anchor_nodes": [
                {
                    "kg_id": "ds:openneuro:ds002717",
                    "label": "OpenNeuro ds002717",
                    "node_type": "Dataset",
                },
                {
                    "kg_id": "concept:fmri_decoding",
                    "label": "fMRI decoding",
                    "node_type": "Concept",
                },
                {
                    "kg_id": "neurostore_task:7CEgPb3CFbSU:behavioral:0",
                    "label": "Brief Assessment of Cognition in Schizophrenia (BACS)",
                    "node_type": "Task",
                },
            ],
        }
    )

    assert bundle["quality"] == "exact_pair"
    assert bundle["entity_hints"] == [
        "neurostore_task:7CEgPb3CFbSU:behavioral:0",
        "concept:fmri_decoding",
    ]
    assert bundle["allowed_node_types"] == ["Task", "Concept"]


def test_search_expanded_exact_anchor_ok_filters_dataset_and_focus_mismatch():
    allowed, reason = query_service._search_expanded_exact_anchor_ok(
        raw_seed_id="concept:attention",
        raw_seed_label="attention",
        raw_seed_type="Concept",
        candidate_id="ds:openneuro:ds000114",
        candidate_label="A test-retest fMRI dataset for spatial attention",
        candidate_type="Dataset",
        focus_terms=["attention"],
    )
    assert allowed is False
    assert reason == "dataset_search_expansion_rejected"

    allowed, reason = query_service._search_expanded_exact_anchor_ok(
        raw_seed_id="task:response_inhibition",
        raw_seed_label="response inhibition",
        raw_seed_type="Task",
        candidate_id="neurostore_task:carit",
        candidate_label="Conditioned Appetitive Response Inhibition Task",
        candidate_type="Task",
        focus_terms=["response", "inhibition"],
    )
    assert allowed is True
    assert reason == ""

    allowed, reason = query_service._search_expanded_exact_anchor_ok(
        raw_seed_id="task:response_inhibition",
        raw_seed_label="response inhibition",
        raw_seed_type="Task",
        candidate_id="neurostore_task:unrelated",
        candidate_label="Affective Decision Making in Aviation",
        candidate_type="Task",
        focus_terms=["response", "inhibition"],
    )
    assert allowed is False
    assert reason == "focus_overlap_missing"


def test_resolve_semantic_seed_context_skips_search_expansion_once_exact_neighbor_exists(
    monkeypatch,
):
    seed_detail = query_service.KGNodeSummary(
        kg_id="ds:seed",
        label="Response inhibition dataset",
        node_type="Dataset",
        properties={"label": "Response inhibition dataset"},
        score=1.0,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "ds:seed":
            return seed_detail
        return None

    search_calls = {"count": 0}

    def fake_neighbors(kg_id, **kwargs):
        del kwargs
        if kg_id == "ds:seed":
            return [
                {
                    "kg_id": "task:exact",
                    "label": "Response Inhibition Go/No-Go Task",
                    "node_type": "Task",
                    "relation": "BELONGS_TO_FAMILY",
                    "properties": {"label": "Response Inhibition Go/No-Go Task"},
                    "score": 0.81,
                }
            ]
        return []

    def fake_search_nodes(*args, **kwargs):
        search_calls["count"] += 1
        return []

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "neighbors", fake_neighbors)
    monkeypatch.setattr(query_service, "search_nodes", fake_search_nodes)

    out = query_service._resolve_semantic_seed_context(
        ["ds:seed"],
        db=FakeEmptyDB(),
        neighbor_limit=6,
    )

    assert "task:exact" in out["seed_kg_ids"]
    assert out["seed_provenance"]["task:exact"] == [
        "expanded_from:ds:seed:BELONGS_TO_FAMILY"
    ]
    assert search_calls["count"] == 0


def test_sample_ood_hypothesis_skips_gfs_without_paper_store(monkeypatch):
    seed_detail = query_service.KGNodeSummary(
        kg_id="task:seed",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:seed":
            return seed_detail
        return None

    def fail_search_gfs(*args, **kwargs):
        raise AssertionError("search_gfs should not be called without a paper store")

    monkeypatch.delenv("BR_FILE_SEARCH_STORE_NAMES", raising=False)
    monkeypatch.delenv("BR_FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("BR_GOOGLE_FILE_SEARCH_STORE", raising=False)
    monkeypatch.delenv("GOOGLE_FILE_SEARCH_STORE", raising=False)
    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_gfs", fail_search_gfs)

    out = query_service.sample_ood_hypothesis(
        ["task:seed"],
        limit=1,
        leverage_items=[
            {
                "kg_id": "task:wm",
                "label": "Working Memory",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.8,
                "leverage_score": 0.7,
                "coherence_score": 0.6,
                "feasibility_score": 0.5,
                "score_breakdown": {"domain_overlap_score": 0.5},
            }
        ],
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_returned"] == 1
    assert out["summary"]["gfs_calls_total"] == 0
    assert out["hypotheses"][0]["verification_reason"] == "gfs_paper_store_unconfigured"
    assert (
        out["summary"]["verification_reason_counts"]["gfs_paper_store_unconfigured"]
        == 1
    )


def test_sample_ood_hypothesis_returns_partial_results_when_budget_exhausts(
    monkeypatch,
):
    seed_detail = query_service.KGNodeSummary(
        kg_id="task:seed",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:seed":
            return seed_detail
        return None

    monotonic_values = iter([100.0, 100.0, 131.0])
    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service.time,
        "monotonic",
        lambda: next(monotonic_values),
    )

    out = query_service.sample_ood_hypothesis(
        ["task:seed"],
        limit=2,
        leverage_items=[
            {
                "kg_id": "task:first",
                "label": "First candidate",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.8,
                "leverage_score": 0.7,
                "coherence_score": 0.6,
                "feasibility_score": 0.5,
                "score_breakdown": {"domain_overlap_score": 0.5},
            },
            {
                "kg_id": "task:second",
                "label": "Second candidate",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.7,
                "leverage_score": 0.6,
                "coherence_score": 0.5,
                "feasibility_score": 0.4,
                "score_breakdown": {"domain_overlap_score": 0.5},
            },
        ],
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_returned"] == 1
    assert out["diagnostics"]["ood_verification"]["partial_return"] is True
    assert out["diagnostics"]["ood_verification"]["stop_reason"] == "budget_exhausted"
    assert out["hypotheses"][0]["candidate_kg_id"] == "task:first"
    assert [row["candidate_kg_id"] for row in out["candidates_ordered"]] == [
        "task:first",
        "task:second",
    ]
    assert out["candidates_ordered"][1]["verification_reason"] == "gfs_budget_exhausted"


def test_sample_ood_hypothesis_collapses_near_duplicate_candidates_before_verification(
    monkeypatch,
):
    seed_detail = query_service.KGNodeSummary(
        kg_id="task:seed",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:seed":
            return seed_detail
        return None

    monkeypatch.setenv("BR_FILE_SEARCH_STORE_NAMES", "fileSearchStores/papers-a")
    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_gfs",
        lambda *args, **kwargs: {"status": "empty", "hits": []},
    )

    out = query_service.sample_ood_hypothesis(
        ["task:seed"],
        limit=4,
        leverage_items=[
            {
                "kg_id": "task:bacs",
                "label": "Brief Assessment of Cognition in Schizophrenia (BACS)",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.8,
                "leverage_score": 0.7,
                "coherence_score": 0.6,
                "feasibility_score": 0.5,
                "score_breakdown": {"domain_overlap_score": 0.5},
            },
            {
                "kg_id": "task:bacs_j",
                "label": "Brief Assessment of Cognition in Schizophrenia (BACS-J)",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.79,
                "leverage_score": 0.69,
                "coherence_score": 0.59,
                "feasibility_score": 0.49,
                "score_breakdown": {"domain_overlap_score": 0.5},
            },
            {
                "kg_id": "task:bacssc",
                "label": "Brief Assessment of Cognition in Schizophrenia Symbol Coding Test (BACSSC)",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.78,
                "leverage_score": 0.68,
                "coherence_score": 0.58,
                "feasibility_score": 0.48,
                "score_breakdown": {"domain_overlap_score": 0.5},
            },
            {
                "kg_id": "task:wm",
                "label": "Working memory updating",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.7,
                "leverage_score": 0.6,
                "coherence_score": 0.55,
                "feasibility_score": 0.47,
                "score_breakdown": {"domain_overlap_score": 0.4},
            },
        ],
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_collapsed_duplicate_candidates"] == 2
    assert out["diagnostics"]["candidate_collapse"]["duplicates_removed"] == 2
    assert out["diagnostics"]["candidate_collapse"]["clusters_collapsed"] == 1
    assert [row["candidate_kg_id"] for row in out["hypotheses"]] == [
        "task:bacs",
        "task:wm",
    ]
    duplicate_rows = [
        row
        for row in out["candidates_ordered"]
        if row["verification_reason"] == "duplicate_cluster_filtered"
    ]
    assert [row["candidate_kg_id"] for row in duplicate_rows] == [
        "task:bacs_j",
        "task:bacssc",
    ]
    assert all(
        row["cluster_representative_kg_id"] == "task:bacs" for row in duplicate_rows
    )


def test_sample_ood_hypothesis_semantic_veto_filters_low_value_transfer_candidates(
    monkeypatch,
):
    seed_detail = query_service.KGNodeSummary(
        kg_id="task:seed",
        label="Classical Fear Conditioning Task",
        node_type="Task",
        properties={"label": "Classical Fear Conditioning Task"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:seed":
            return seed_detail
        return None

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "search_gfs",
        lambda *args, **kwargs: {"status": "empty", "hits": []},
    )

    out = query_service.sample_ood_hypothesis(
        ["task:seed"],
        limit=5,
        leverage_items=[
            {
                "kg_id": "task:family",
                "label": "Affective & Preference Tasks",
                "node_type": "TaskFamily",
                "candidate_type": "TaskFamily",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.83,
                "leverage_score": 0.72,
                "coherence_score": 0.63,
                "feasibility_score": 0.51,
                "score_breakdown": {"domain_overlap_score": 0.41},
            },
            {
                "kg_id": "task:near_dup",
                "label": "Aversive Classical Conditioning Paradigm",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.81,
                "leverage_score": 0.7,
                "coherence_score": 0.61,
                "feasibility_score": 0.5,
                "score_breakdown": {"domain_overlap_score": 0.39},
            },
            {
                "kg_id": "concept:echo",
                "label": "fear conditioning task",
                "node_type": "Concept",
                "candidate_type": "Concept",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.8,
                "leverage_score": 0.69,
                "coherence_score": 0.6,
                "feasibility_score": 0.5,
                "score_breakdown": {"domain_overlap_score": 0.4},
            },
            {
                "kg_id": "task:survivor",
                "label": "Boundary Geometry Reorientation",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.77,
                "leverage_score": 0.68,
                "coherence_score": 0.59,
                "feasibility_score": 0.49,
                "score_breakdown": {"domain_overlap_score": 0.33},
            },
        ],
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_returned"] == 2
    assert out["summary"]["n_rejected_post_synthesis"] == 2
    assert out["summary"]["n_semantic_downranked"] == 1
    assert [row["candidate_kg_id"] for row in out["hypotheses"]] == [
        "task:near_dup",
        "task:survivor",
    ]
    assert out["hypotheses"][0]["semantic_triage_decision"] == "downrank"
    assert "same_family_variant" in (
        out["hypotheses"][0]["semantic_triage_reasons"] or []
    )
    rejected_rows = [
        row
        for row in out["candidates_ordered"]
        if row["verification_reason"] == "pre_synthesis_semantic_veto"
    ]
    assert [row["candidate_kg_id"] for row in rejected_rows] == [
        "task:family",
        "concept:echo",
    ]


def test_sample_ood_hypothesis_timeout_does_not_veto_candidate(monkeypatch):
    seed_detail = query_service.KGNodeSummary(
        kg_id="task:seed",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:seed":
            return seed_detail
        return None

    def fake_search_gfs(query, **kwargs):
        del query, kwargs
        return {
            "status": "error",
            "error": "file_search timed out after 5ms",
            "stores_attempted": ["fileSearchStores/papers-a"],
            "stores_hit": [],
            "call_count": 1,
            "latency_ms": 5.0,
            "raw_hit_count": 0,
            "n_docs_hit": 0,
            "store_errors": [
                {
                    "store": "fileSearchStores/papers-a",
                    "error": "file_search timed out after 5ms",
                }
            ],
        }

    monkeypatch.setenv("BR_FILE_SEARCH_STORE_NAMES", "fileSearchStores/papers-a")
    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_gfs", fake_search_gfs)

    out = query_service.sample_ood_hypothesis(
        ["task:seed"],
        limit=1,
        leverage_items=[
            {
                "kg_id": "task:wm",
                "label": "Working Memory",
                "node_type": "Task",
                "candidate_type": "Task",
                "seeds_touched": ["task:seed"],
                "relations": ["RELATED_TO"],
                "novelty_score": 0.8,
                "leverage_score": 0.7,
                "coherence_score": 0.6,
                "feasibility_score": 0.5,
                "score_breakdown": {"domain_overlap_score": 0.5},
            }
        ],
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_returned"] == 1
    assert out["summary"]["n_vetoed"] == 0
    assert out["hypotheses"][0]["verification_reason"] == "gfs_timeout"


def test_sample_and_verify_hypotheses_uses_exact_id_entity_hints(monkeypatch):
    captured: dict[str, object] = {}

    def fake_sample_ood_hypothesis(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "seed_kg_ids": ["task:seed"],
            "hypotheses": [
                {
                    "rank": 1,
                    "seed_kg_id": "task:seed",
                    "anchor_label": "Spatial navigation",
                    "candidate_kg_id": "concept:memory",
                    "candidate_label": "Episodic Memory",
                    "candidate_type": "Concept",
                    "statement": "Episodic memory may bridge spatial navigation decoding.",
                    "anchor_nodes": [
                        {"kg_id": "task:seed", "label": "Spatial navigation"},
                        {"kg_id": "concept:memory", "label": "Episodic Memory"},
                    ],
                }
            ],
            "summary": {"n_hypotheses": 1},
            "warnings": [],
        }

    def fake_verify_hypothesis(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "supported",
            "confidence": 0.73,
            "evidence_source_scope": "direct",
            "summary": {"n_supporting": 2},
            "warnings": [],
        }

    monkeypatch.setattr(
        query_service, "sample_ood_hypothesis", fake_sample_ood_hypothesis
    )
    monkeypatch.setattr(query_service, "verify_hypothesis", fake_verify_hypothesis)

    out = query_service.sample_and_verify_hypotheses(
        ["task:seed"],
        sample_limit=3,
        verify_top_k=1,
        strictness="high_recall",
        candidate_lane_mode="strict",
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_sampled"] == 1
    assert out["summary"]["n_tested"] == 1
    assert out["summary"]["n_supported"] == 1
    assert captured["kwargs"]["hypothesis"] == (
        "Episodic memory may bridge spatial navigation decoding."
    )
    assert captured["kwargs"]["entity_hints"] == [
        "task:seed",
        "concept:memory",
    ]
    assert captured["kwargs"]["allowed_node_types"] == [
        "Task",
        "Concept",
    ]
    assert captured["kwargs"]["candidate_lane_mode"] == "strict"
    tested = out["tested_hypotheses"][0]
    assert tested["entity_hints_used"] == [
        "task:seed",
        "concept:memory",
    ]
    assert tested["entity_hint_quality"] == "exact_pair"
    assert tested["entity_hint_quality_score"] == 1.0
    assert tested["allowed_node_types_used"] == ["Task", "Concept"]
    assert tested["evidence_item_count"] == 0
    assert tested["kg_verification"]["verdict"] == "supported"
    assert tested["kg_verification"]["evidence_source_scope"] == "direct"
    assert tested["kg_verification"]["entity_hint_quality"] == "exact_pair"
    assert tested["kg_verification"]["evidence_item_count"] == 0


def test_verify_sampled_hypotheses_uses_exact_id_entity_hints(monkeypatch):
    captured: dict[str, object] = {}

    def fake_verify_hypothesis(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "supported",
            "confidence": 0.73,
            "evidence_source_scope": "direct",
            "summary": {"n_supporting": 2},
            "warnings": [],
        }

    monkeypatch.setattr(query_service, "verify_hypothesis", fake_verify_hypothesis)

    out = query_service.verify_sampled_hypotheses(
        [
            {
                "rank": 1,
                "seed_kg_id": "task:seed",
                "anchor_label": "Spatial navigation",
                "anchor_type": "Task",
                "candidate_kg_id": "concept:memory",
                "candidate_label": "Episodic Memory",
                "candidate_type": "Concept",
                "statement": "Episodic memory may bridge spatial navigation decoding.",
                "anchor_nodes": [
                    {"kg_id": "task:seed", "label": "Spatial navigation"},
                    {"kg_id": "concept:memory", "label": "Episodic Memory"},
                ],
            }
        ],
        seed_kg_ids=["task:seed"],
        verify_top_k=1,
        strictness="high_recall",
        candidate_lane_mode="strict",
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_input_hypotheses"] == 1
    assert out["summary"]["n_tested"] == 1
    assert out["summary"]["n_supported"] == 1
    assert captured["kwargs"]["hypothesis"] == (
        "Episodic memory may bridge spatial navigation decoding."
    )
    assert captured["kwargs"]["entity_hints"] == [
        "task:seed",
        "concept:memory",
    ]
    assert captured["kwargs"]["candidate_lane_mode"] == "strict"


def test_verify_sampled_hypotheses_broad_vs_strict_changes_aggregate_verdicts(
    monkeypatch,
):
    concept = query_service.KGNodeSummary(
        kg_id="concept:reward_learning",
        label="Reward learning",
        node_type="Concept",
        score=0.95,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == concept.kg_id:
            return concept
        return None

    def fake_collect(entity, *, limit, client):
        del entity, limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:77770000",
                    "label": "Candidate reward paper",
                    "node_type": "Publication",
                    "properties": {"pmid": "77770000"},
                },
                "matched_entity": query_service._node_summary_payload(concept),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.79,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": "claim:candidate_reward",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Reward learning is implicated by title-only evidence.",
                        "claim_polarity": "supports",
                        "claim_strength": 0.74,
                        "method_rigor": 0.0,
                        "candidate_lane_present": True,
                        "candidate_lane_bucket": "title_only_generic_concept",
                        "candidate_lane_policy": "candidate_only",
                        "candidate_lane_trigger_reason": "candidate_only_title_generic_reroute",
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.74,
                    "method_rigor": 0.0,
                    "candidate_lane_present": True,
                },
                "evidence_span": {
                    "kg_id": "evidence:candidate_reward",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "quote": "Reward learning appears in the title only.",
                        "evidence_quality_score": 0.52,
                        "provenance_completeness": 0.61,
                        "candidate_lane_present": True,
                    },
                },
                "support_edge_props": {
                    "evidence_quality_score": 0.52,
                    "candidate_lane_present": True,
                },
                "evidence_anchor_scope": "direct",
            }
        ]

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    sampled = [
        {
            "rank": 1,
            "candidate_kg_id": concept.kg_id,
            "candidate_label": concept.label,
            "candidate_type": "Concept",
            "statement": "Reward learning is implicated by the available evidence.",
            "verification_hints": {
                "entity_hints": [concept.kg_id],
                "allowed_node_types": ["Concept"],
                "quality": "exact_single",
                "quality_score": 0.8,
                "strategy": "single_exact_id",
            },
        }
    ]

    broad = query_service.verify_sampled_hypotheses(
        sampled,
        seed_kg_ids=[concept.kg_id],
        verify_top_k=1,
        strictness="high_recall",
        candidate_lane_mode="broad",
        db=FakeEmptyDB(),
    )
    strict = query_service.verify_sampled_hypotheses(
        sampled,
        seed_kg_ids=[concept.kg_id],
        verify_top_k=1,
        strictness="high_recall",
        candidate_lane_mode="strict",
        db=FakeEmptyDB(),
    )

    assert broad["candidate_lane_mode"] == "broad"
    assert broad["summary"]["n_supported"] == 1
    assert broad["tested_hypotheses"][0]["kg_verification"]["verdict"] == "supported"
    assert broad["tested_hypotheses"][0]["evidence_item_count"] == 1
    assert (
        broad["tested_hypotheses"][0]["kg_verification"]["summary"][
            "n_candidate_lane_supporting"
        ]
        == 1
    )
    assert (
        broad["tested_hypotheses"][0]["kg_verification"]["supporting_evidence"][0][
            "candidate_lane"
        ]["bucket"]
        == "title_only_generic_concept"
    )

    assert strict["candidate_lane_mode"] == "strict"
    assert strict["summary"]["n_insufficient_evidence"] == 1
    assert strict["tested_hypotheses"][0]["kg_verification"]["verdict"] == (
        "insufficient_evidence"
    )
    assert (
        strict["tested_hypotheses"][0]["kg_verification"]["summary"][
            "candidate_lane_filtered"
        ]
        == 1
    )
    assert (
        strict["tested_hypotheses"][0]["kg_verification"]["summary"][
            "n_candidate_lane_supporting"
        ]
        == 0
    )
    assert strict["tested_hypotheses"][0]["evidence_item_count"] == 0


def test_verify_hypothesis_uses_external_literature_when_kg_evidence_missing(
    monkeypatch,
):
    concept = query_service.KGNodeSummary(
        kg_id="concept:image_decoding",
        label="Image decoding",
        node_type="Concept",
        score=0.95,
    )

    monkeypatch.setattr(
        query_service,
        "_resolve_exact_hint_entity",
        lambda hint, *, client, allowed_node_types=None: concept
        if hint == concept.kg_id
        else None,
    )
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        lambda entity, *, limit, client: [],
    )
    monkeypatch.setattr(
        query_service,
        "deep_research_sync",
        lambda request: {
            "status": "ok",
            "idempotency_key": "lit:test",
            "result": {
                "status": "ok",
                "summary": "External literature reports fMRI-based image decoding evidence.",
                "documents": [
                    {
                        "doc_id": "doc_1",
                        "title": "Decoding visual images from fMRI activity",
                        "url": "https://pubmed.ncbi.nlm.nih.gov/12345/",
                        "source_host": "pubmed.ncbi.nlm.nih.gov",
                        "source_type": "paper",
                        "publisher": "NeuroImage",
                        "published_at": "2024",
                        "snippets": [
                            "Visual image content can be reconstructed from fMRI patterns."
                        ],
                    }
                ],
            },
        },
    )

    result = query_service.verify_hypothesis(
        "fmri-based image decoding may generalize across tasks",
        entity_hints=[concept.kg_id],
        use_external_literature=True,
        external_literature_query="fmri-based image decoding",
        strictness="balanced",
        db=FakeEmptyDB(),
    )

    assert result["verdict"] == "uncertain"
    assert result["evidence_source_scope"] == "external_literature"
    assert result["summary"]["n_external_literature_uncertain"] == 1
    assert result["summary"]["external_literature_requested"] is True
    assert result["uncertain_evidence"][0]["evidence_anchor_scope"] == (
        "external_literature"
    )
    assert result["uncertain_evidence"][0]["external_literature"]["query"].startswith(
        "fmri-based image decoding"
    )


def test_sample_and_verify_hypotheses_broad_vs_strict_changes_verified_results(
    monkeypatch,
):
    concept = query_service.KGNodeSummary(
        kg_id="concept:reward_learning",
        label="Reward learning",
        node_type="Concept",
        score=0.95,
    )

    def fake_sample_ood_hypothesis(*args, **kwargs):
        del args, kwargs
        return {
            "ok": True,
            "seed_kg_ids": [concept.kg_id],
            "hypotheses": [
                {
                    "rank": 1,
                    "candidate_kg_id": concept.kg_id,
                    "candidate_label": concept.label,
                    "candidate_type": "Concept",
                    "statement": "Reward learning is implicated by the available evidence.",
                    "verification_hints": {
                        "entity_hints": [concept.kg_id],
                        "allowed_node_types": ["Concept"],
                        "quality": "exact_single",
                        "quality_score": 0.8,
                        "strategy": "single_exact_id",
                    },
                }
            ],
            "summary": {"n_hypotheses": 1},
            "warnings": [],
        }

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == concept.kg_id:
            return concept
        return None

    def fake_collect(entity, *, limit, client):
        del entity, limit, client
        return [
            {
                "publication": {
                    "kg_id": "pmid:77770001",
                    "label": "Candidate reward paper",
                    "node_type": "Publication",
                    "properties": {"pmid": "77770001"},
                },
                "matched_entity": query_service._node_summary_payload(concept),
                "mention_type": "MENTIONS",
                "mention_props": {
                    "mention_strength": 0.8,
                    "evidence_quality": "medium",
                },
                "claim": {
                    "kg_id": "claim:candidate_reward_2",
                    "node_type": "Claim",
                    "properties": {
                        "text": "Reward learning is implicated by title-only evidence.",
                        "claim_polarity": "supports",
                        "claim_strength": 0.75,
                        "method_rigor": 0.0,
                        "candidate_lane_present": True,
                        "candidate_lane_bucket": "title_only_generic_concept",
                        "candidate_lane_policy": "candidate_only",
                        "candidate_lane_trigger_reason": "candidate_only_title_generic_reroute",
                    },
                },
                "claim_edge_props": {
                    "claim_polarity": "supports",
                    "claim_strength": 0.75,
                    "method_rigor": 0.0,
                    "candidate_lane_present": True,
                },
                "evidence_span": {
                    "kg_id": "evidence:candidate_reward_2",
                    "node_type": "EvidenceSpan",
                    "properties": {
                        "quote": "Reward learning appears in the title only.",
                        "evidence_quality_score": 0.53,
                        "provenance_completeness": 0.62,
                        "candidate_lane_present": True,
                    },
                },
                "support_edge_props": {
                    "evidence_quality_score": 0.53,
                    "candidate_lane_present": True,
                },
                "evidence_anchor_scope": "direct",
            }
        ]

    monkeypatch.setattr(
        query_service, "sample_ood_hypothesis", fake_sample_ood_hypothesis
    )
    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(
        query_service,
        "_collect_publication_evidence_for_entity",
        fake_collect,
    )

    broad = query_service.sample_and_verify_hypotheses(
        [concept.kg_id],
        sample_limit=1,
        verify_top_k=1,
        strictness="high_recall",
        candidate_lane_mode="broad",
        db=FakeEmptyDB(),
    )
    strict = query_service.sample_and_verify_hypotheses(
        [concept.kg_id],
        sample_limit=1,
        verify_top_k=1,
        strictness="high_recall",
        candidate_lane_mode="strict",
        db=FakeEmptyDB(),
    )

    assert broad["candidate_lane_mode"] == "broad"
    assert broad["summary"]["n_supported"] == 1
    assert broad["tested_hypotheses"][0]["kg_verification"]["verdict"] == "supported"
    assert (
        broad["tested_hypotheses"][0]["kg_verification"]["summary"][
            "n_candidate_lane_supporting"
        ]
        == 1
    )
    assert (
        broad["tested_hypotheses"][0]["kg_verification"]["supporting_evidence"][0][
            "candidate_lane"
        ]["trigger_reason"]
        == "candidate_only_title_generic_reroute"
    )

    assert strict["candidate_lane_mode"] == "strict"
    assert strict["summary"]["n_insufficient_evidence"] == 1
    assert strict["tested_hypotheses"][0]["kg_verification"]["verdict"] == (
        "insufficient_evidence"
    )
    assert (
        strict["tested_hypotheses"][0]["kg_verification"]["summary"][
            "candidate_lane_filtered"
        ]
        == 1
    )
    assert (
        strict["tested_hypotheses"][0]["kg_verification"]["summary"][
            "n_candidate_lane_supporting"
        ]
        == 0
    )


def test_verify_sampled_hypotheses_threads_external_literature_controls(
    monkeypatch,
):
    captured: dict[str, object] = {}

    def fake_verify_hypothesis(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "uncertain",
            "confidence": 0.42,
            "summary": {
                "n_uncertain": 1,
                "n_external_literature_uncertain": 1,
                "external_literature_requested": True,
            },
            "uncertain_evidence": [
                {
                    "publication": {"kg_id": "external_doc:1", "label": "Paper A"},
                    "polarity": "uncertain",
                    "score": 0.56,
                    "evidence_anchor_scope": "external_literature",
                }
            ],
            "supporting_evidence": [],
            "conflicting_evidence": [],
            "neutral_evidence": [],
            "warnings": [],
        }

    monkeypatch.setattr(query_service, "verify_hypothesis", fake_verify_hypothesis)

    out = query_service.verify_sampled_hypotheses(
        [
            {
                "rank": 1,
                "candidate_kg_id": "concept:image_decoding",
                "candidate_label": "Image decoding",
                "statement": "fMRI-based image decoding may generalize across tasks.",
                "verification_hints": {
                    "entity_hints": ["concept:image_decoding"],
                    "quality": "exact_single",
                    "quality_score": 0.8,
                    "strategy": "single_exact_id",
                },
            }
        ],
        query="fmri-based image decoding",
        seed_kg_ids=["concept:image_decoding"],
        verify_top_k=1,
        use_external_literature=True,
        external_literature_top_k=3,
        external_literature_recency_days=180,
        external_literature_exclude_domains=["example.com"],
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_uncertain"] == 1
    assert out["summary"]["external_literature_requested"] is True
    assert captured["kwargs"]["use_external_literature"] is True
    assert captured["kwargs"]["external_literature_query"] == (
        "fmri-based image decoding"
    )
    assert captured["kwargs"]["external_literature_top_k"] == 3
    assert captured["kwargs"]["external_literature_recency_days"] == 180
    assert captured["kwargs"]["external_literature_exclude_domains"] == ["example.com"]


def test_sample_and_verify_hypotheses_threads_external_literature_controls(
    monkeypatch,
):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        query_service,
        "sample_ood_hypothesis",
        lambda *args, **kwargs: {
            "ok": True,
            "seed_kg_ids": ["concept:image_decoding"],
            "hypotheses": [{"rank": 1, "statement": "H1"}],
            "summary": {"n_hypotheses": 1},
            "warnings": [],
        },
    )

    def fake_verify_sampled_hypotheses(sampled_hypotheses, **kwargs):
        captured["sampled_hypotheses"] = sampled_hypotheses
        captured["kwargs"] = kwargs
        return {
            "tested_hypotheses": [
                {"rank": 1, "kg_verification": {"verdict": "uncertain"}}
            ],
            "summary": {"n_tested": 1, "n_uncertain": 1},
            "warnings": [],
        }

    monkeypatch.setattr(
        query_service,
        "verify_sampled_hypotheses",
        fake_verify_sampled_hypotheses,
    )

    out = query_service.sample_and_verify_hypotheses(
        ["concept:image_decoding"],
        query="fmri-based image decoding",
        sample_limit=1,
        verify_top_k=1,
        use_external_literature=True,
        external_literature_top_k=4,
        external_literature_recency_days=90,
        external_literature_exclude_domains=["example.com"],
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_uncertain"] == 1
    assert captured["kwargs"]["query"] == "fmri-based image decoding"
    assert captured["kwargs"]["use_external_literature"] is True
    assert captured["kwargs"]["external_literature_top_k"] == 4
    assert captured["kwargs"]["external_literature_recency_days"] == 90
    assert captured["kwargs"]["external_literature_exclude_domains"] == ["example.com"]


def test_verify_sampled_hypotheses_falls_back_to_mixed_hints_without_exact_pair(
    monkeypatch,
):
    captured: dict[str, object] = {}

    def fake_verify_hypothesis(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "insufficient_evidence",
            "confidence": 0.0,
            "evidence_source_scope": "direct",
            "summary": {},
            "warnings": [],
        }

    monkeypatch.setattr(query_service, "verify_hypothesis", fake_verify_hypothesis)

    out = query_service.verify_sampled_hypotheses(
        [
            {
                "rank": 1,
                "anchor_label": "Spatial navigation",
                "candidate_label": "Episodic Memory",
                "statement": "Episodic memory may bridge spatial navigation decoding.",
                "anchor_nodes": [
                    {"label": "Spatial navigation"},
                    {"label": "Episodic Memory"},
                ],
            }
        ],
        seed_kg_ids=["task:seed"],
        verify_top_k=1,
        strictness="high_recall",
        db=FakeEmptyDB(),
    )

    assert captured["kwargs"]["entity_hints"] == [
        "Spatial navigation",
        "Episodic Memory",
    ]
    assert captured["kwargs"]["allowed_node_types"] is None
    assert out["tested_hypotheses"][0]["entity_hints_used"] == [
        "Spatial navigation",
        "Episodic Memory",
    ]
    assert out["tested_hypotheses"][0]["entity_hint_quality"] == "label_pair"


def test_verify_sampled_hypotheses_prefers_fast_path_exact_ids_over_publication_ids(
    monkeypatch,
):
    captured: dict[str, object] = {}

    def fake_verify_hypothesis(**kwargs):
        captured["kwargs"] = kwargs
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "insufficient_evidence",
            "confidence": 0.0,
            "evidence_source_scope": "direct",
            "summary": {},
            "warnings": [],
        }

    monkeypatch.setattr(query_service, "verify_hypothesis", fake_verify_hypothesis)

    out = query_service.verify_sampled_hypotheses(
        [
            {
                "rank": 1,
                "seed_kg_id": "10.1016/j.neuroimage.2015.07.054",
                "anchor_label": "A group ICA based framework for evaluating resting state",
                "anchor_type": "Publication",
                "candidate_kg_id": "neurostore_task:7CEgPb3CFbSU:behavioral:0",
                "candidate_label": "Brief Assessment of Cognition in Schizophrenia (BACS)",
                "candidate_type": "Task",
                "statement": "Resting-state decoding may partially transfer to BACS.",
                "anchor_nodes": [
                    {
                        "kg_id": "10.1016/j.neuroimage.2015.07.054",
                        "label": "A group ICA based framework for evaluating resting state",
                    },
                    {
                        "kg_id": "neurostore_task:7CEgPb3CFbSU:behavioral:0",
                        "label": "Brief Assessment of Cognition in Schizophrenia (BACS)",
                    },
                ],
            }
        ],
        seed_kg_ids=["10.1016/j.neuroimage.2015.07.054"],
        verify_top_k=1,
        strictness="high_recall",
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_tested"] == 1
    assert captured["kwargs"]["entity_hints"] == [
        "neurostore_task:7CEgPb3CFbSU:behavioral:0",
    ]
    assert captured["kwargs"]["allowed_node_types"] == ["Task"]
    assert out["tested_hypotheses"][0]["entity_hints_used"] == [
        "neurostore_task:7CEgPb3CFbSU:behavioral:0",
    ]
    assert out["tested_hypotheses"][0]["entity_hint_quality"] == "exact_single"


def test_verify_sampled_hypotheses_surfaces_aggregated_evidence_items(monkeypatch):
    def fake_verify_hypothesis(**kwargs):
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "mixed",
            "confidence": 0.41,
            "supporting_evidence": [
                {
                    "publication": {"kg_id": "pub:support", "label": "Support study"},
                    "polarity": "supports",
                    "score": 0.7,
                }
            ],
            "conflicting_evidence": [
                {
                    "publication": {"kg_id": "pub:conflict", "label": "Conflict study"},
                    "polarity": "refutes",
                    "score": 0.6,
                }
            ],
            "uncertain_evidence": [],
            "neutral_evidence": [],
            "warnings": [],
        }

    monkeypatch.setattr(query_service, "verify_hypothesis", fake_verify_hypothesis)

    out = query_service.verify_sampled_hypotheses(
        [
            {
                "rank": 1,
                "seed_kg_id": "task:seed",
                "anchor_label": "Spatial navigation",
                "anchor_type": "Task",
                "candidate_kg_id": "concept:memory",
                "candidate_label": "Episodic Memory",
                "candidate_type": "Concept",
                "statement": "Episodic memory may bridge spatial navigation decoding.",
                "anchor_nodes": [
                    {"kg_id": "task:seed", "label": "Spatial navigation"},
                    {"kg_id": "concept:memory", "label": "Episodic Memory"},
                ],
            }
        ],
        seed_kg_ids=["task:seed"],
        verify_top_k=1,
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_tested"] == 1
    assert out["summary"]["n_mixed"] == 1
    assert out["summary"]["entity_hint_quality_counts"] == {"exact_pair": 1}
    assert out["summary"]["mean_entity_hint_quality_score"] == 1.0
    assert out["summary"]["mean_evidence_item_count"] == 2.0
    assert out["evidence_items"] == [
        {
            "publication": {"kg_id": "pub:support", "label": "Support study"},
            "polarity": "supports",
            "score": 0.7,
        },
        {
            "publication": {"kg_id": "pub:conflict", "label": "Conflict study"},
            "polarity": "refutes",
            "score": 0.6,
        },
    ]
    tested = out["tested_hypotheses"][0]
    assert tested["entity_hint_quality"] == "exact_pair"
    assert tested["evidence_item_count"] == 2
    assert tested["kg_verification"]["summary"]["evidence_item_count"] == 2


def test_verify_sampled_hypotheses_records_per_hypothesis_cost_breakdown(monkeypatch):
    def fake_verify_hypothesis(**kwargs):
        return {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "supported",
            "confidence": 0.73,
            "summary": {
                "n_supporting": 2,
                "n_conflicting": 0,
                "n_uncertain": 0,
                "n_neutral": 0,
                "n_candidate_publications": 3,
            },
            "timings_s": {
                "entity_resolution": 0.12,
                "direct_evidence_collection": 0.45,
                "typed_path_evidence_collection": 0.05,
                "family_fallback_lookup": 0.01,
                "family_fallback_evidence_collection": 0.02,
                "aggregation": 0.08,
                "total": 0.73,
            },
            "supporting_evidence": [
                {
                    "publication": {"kg_id": "pub:support", "label": "Support study"},
                    "polarity": "supports",
                    "score": 0.7,
                }
            ],
            "conflicting_evidence": [],
            "uncertain_evidence": [],
            "neutral_evidence": [],
            "warnings": [],
        }

    monkeypatch.setattr(query_service, "verify_hypothesis", fake_verify_hypothesis)

    out = query_service.verify_sampled_hypotheses(
        [
            {
                "rank": 1,
                "seed_kg_id": "task:seed",
                "anchor_label": "Spatial navigation",
                "anchor_type": "Task",
                "candidate_kg_id": "concept:memory",
                "candidate_label": "Episodic Memory",
                "candidate_type": "Concept",
                "statement": "Episodic memory may bridge spatial navigation decoding.",
                "anchor_nodes": [
                    {"kg_id": "task:seed", "label": "Spatial navigation"},
                    {"kg_id": "concept:memory", "label": "Episodic Memory"},
                ],
            }
        ],
        seed_kg_ids=["task:seed"],
        verify_top_k=1,
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_tested"] == 1
    assert out["summary"]["verify_wall_clock_s"] >= 0.0
    assert out["diagnostics"]["total_duration_s"] >= 0.0
    assert out["diagnostics"]["phase_totals_s"]["direct_evidence_collection"] == 0.45
    breakdown = out["diagnostics"]["per_hypothesis"][0]
    assert breakdown["candidate_kg_id"] == "concept:memory"
    assert breakdown["verdict"] == "supported"
    assert breakdown["n_candidate_publications"] == 3
    assert breakdown["timings_s"]["total"] == 0.73
    assert breakdown["wall_clock_s"] >= 0.0


def test_sample_and_verify_hypotheses_counts_canonical_conflicting_verdict(
    monkeypatch,
):
    monkeypatch.setattr(
        query_service,
        "sample_ood_hypothesis",
        lambda *args, **kwargs: {
            "ok": True,
            "seed_kg_ids": ["task:seed"],
            "hypotheses": [
                {
                    "rank": 1,
                    "statement": "Conflict-monitoring evidence may not support ACC recruitment.",
                    "seed_kg_id": "task:seed",
                    "anchor_label": "Conflict monitoring",
                    "candidate_kg_id": "region:acc",
                    "candidate_label": "ACC",
                    "anchor_nodes": [
                        {"kg_id": "task:seed", "label": "Conflict monitoring"},
                        {"kg_id": "region:acc", "label": "ACC"},
                    ],
                }
            ],
            "summary": {"n_hypotheses": 1},
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        query_service,
        "verify_hypothesis",
        lambda **kwargs: {
            "hypothesis": kwargs["hypothesis"],
            "verdict": "conflicting",
            "confidence": 0.52,
            "evidence_mode": "shared",
            "evidence_source_scope": "direct",
            "summary": {"n_conflicting": 2, "evidence_scope": "shared"},
            "warnings": [],
        },
    )

    out = query_service.sample_and_verify_hypotheses(
        ["task:seed"],
        sample_limit=2,
        verify_top_k=1,
        db=FakeEmptyDB(),
    )

    assert out["summary"]["n_tested"] == 1
    assert out["summary"]["n_conflicting"] == 1
    assert out["tested_hypotheses"][0]["kg_verification"]["verdict"] == "conflicting"
    assert (
        out["tested_hypotheses"][0]["kg_verification"]["evidence_source_scope"]
        == "direct"
    )


def test_find_structural_leverage_warns_when_scores_collapse(monkeypatch):
    seed_detail = query_service.KGNodeSummary(
        kg_id="task:seed",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:seed":
            return seed_detail
        return None

    def fake_neighbors(kg_id, **kwargs):
        del kwargs
        if kg_id != "task:seed":
            return []
        return [
            {
                "kg_id": "task:a",
                "label": "Latent factor alpha",
                "node_type": "Task",
                "relation": "RELATED_TO",
                "score": 0.5,
            },
            {
                "kg_id": "task:b",
                "label": "Latent factor beta",
                "node_type": "Task",
                "relation": "RELATED_TO",
                "score": 0.5,
            },
        ]

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "neighbors", fake_neighbors)

    out = query_service.find_structural_leverage(["task:seed"], db=FakeEmptyDB())

    assert len(out["items"]) == 2
    assert out["summary"]["score_spread"] == 0.0
    assert any("near-identical" in warning for warning in out["warnings"])


def test_find_structural_leverage_filters_taxonomy_and_metadata_relations(monkeypatch):
    seed_detail = query_service.KGNodeSummary(
        kg_id="task:seed",
        label="Spatial navigation",
        node_type="Task",
        properties={"label": "Spatial navigation"},
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:seed":
            return seed_detail
        return None

    def fake_neighbors(kg_id, **kwargs):
        del kwargs
        if kg_id != "task:seed":
            return []
        return [
            {
                "kg_id": "concept:parent",
                "label": "Subcortical Regions",
                "node_type": "Concept",
                "relation": "CLASSIFIED_UNDER",
                "score": 0.55,
            },
            {
                "kg_id": "mod:fmri",
                "label": "fMRI",
                "node_type": "Modality",
                "relation": "HAS_MODALITY",
                "score": 0.9,
            },
            {
                "kg_id": "task:memory",
                "label": "Episodic memory retrieval",
                "node_type": "Task",
                "relation": "RELATED_TO",
                "score": 0.45,
            },
        ]

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "neighbors", fake_neighbors)

    out = query_service.find_structural_leverage(["task:seed"], db=FakeEmptyDB())

    assert [row["kg_id"] for row in out["items"]] == ["task:memory"]
    assert out["rejections"]["relation_filtered"] >= 2


def test_detect_topology_shifts_derives_seeds_from_update_reason_scope(monkeypatch):
    db = FakeTopologyDB()
    db.edges = {
        ("task:nav", "node:x", "ASSOCIATED_WITH"): {
            "taste_weight": 0.25,
            "novelty_score": 0.9,
            "contradiction_score": 0.5,
            "evidence_quality": 0.45,
        },
        ("task:other", "node:y", "ASSOCIATED_WITH"): {
            "taste_weight": 0.7,
            "novelty_score": 0.1,
            "contradiction_score": 0.1,
            "evidence_quality": 0.8,
        },
    }
    task_detail = query_service.KGNodeSummary(
        kg_id="task:nav",
        label="Spatial navigation",
        node_type="Task",
        score=1.0,
    )

    def fake_node_details(kg_id, **kwargs):
        del kwargs
        if kg_id == "task:nav":
            return task_detail
        return None

    def fake_search_nodes(query, **kwargs):
        del kwargs
        if query == "spatial navigation":
            return [task_detail]
        return []

    monkeypatch.setattr(query_service, "node_details", fake_node_details)
    monkeypatch.setattr(query_service, "search_nodes", fake_search_nodes)

    out = query_service.detect_topology_shifts(
        mode="proposal",
        update_reason="baseline=snapshot:v1;current=snapshot:v2;scope=spatial navigation",
        db=db,
    )

    assert out["seed_kg_ids"] == ["task:nav"]
    assert [row["edge"]["target_id"] for row in out["proposals"]] == ["node:x"]
    assert any("Derived 1 topology seed" in warning for warning in out["warnings"])
