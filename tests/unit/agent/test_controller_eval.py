from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import brain_researcher.services.agent.controller_eval as controller_eval
from brain_researcher.services.agent.controller_eval import (
    apply_eval_case_overrides,
    filter_eval_cases,
    load_eval_cases,
    run_controller_evaluation,
    write_controller_case_result,
    write_controller_evaluation_report,
)
from brain_researcher.services.tools.tool_base import ToolResult


def _build_workflow_result(*, controller_mode: str, query: str) -> dict:
    legacy = controller_mode == "legacy"
    hypotheses = [
        {
            "rank": 1,
            "seed_kg_id": "node:seed",
            "candidate_kg_id": "node:candidate_a" if legacy else "node:candidate_b",
            "candidate_label": "Candidate A" if legacy else "Candidate B",
            "candidate_type": "Task",
            "statement": "Seed node may couple with the candidate under OOD settings.",
            "relation_hint": "ASSOCIATED_WITH" if legacy else "CO_ACTIVATES",
            "novelty_score": 0.81 if legacy else 0.76,
            "ood_score": 0.88 if legacy else 0.9,
            "coherence_score": 0.52 if legacy else 0.66,
            "feasibility_score": 0.48 if legacy else 0.63,
            "principle_score": None if legacy else 0.79,
            "principle_session_key": None if legacy else "pcs_demo",
            "selection_reason": None if legacy else "contradiction_triggered",
            "anomaly_flags": [] if legacy else ["contradiction"],
        },
        {
            "rank": 2,
            "seed_kg_id": "node:seed",
            "candidate_kg_id": "node:candidate_b" if legacy else "node:candidate_a",
            "candidate_label": "Candidate B" if legacy else "Candidate A",
            "candidate_type": "Task",
            "statement": "Second candidate.",
            "relation_hint": "RELATED_TO",
            "novelty_score": 0.73,
            "ood_score": 0.79,
            "coherence_score": 0.49,
            "feasibility_score": 0.51,
            "principle_score": None if legacy else 0.61,
            "principle_session_key": None if legacy else "pcs_demo",
            "selection_reason": None if legacy else "contradiction_triggered",
            "anomaly_flags": [] if legacy else ["contradiction"],
        },
    ]
    ood_result = {
        "hypotheses": hypotheses,
        "candidates_ordered": [
            {
                "candidate_kg_id": "node:candidate_a" if legacy else "node:candidate_b",
                "candidate_label": "Candidate A" if legacy else "Candidate B",
                "rank_before_rerank": 2 if legacy else 1,
                "rank_after_rerank": 1,
                "leverage_score": 0.88 if legacy else 0.9,
                "novelty_score": 0.81 if legacy else 0.76,
                "coherence_score": 0.52 if legacy else 0.66,
                "feasibility_score": 0.48 if legacy else 0.63,
                "domain_overlap_score": 0.41 if legacy else 0.57,
                "principle_score": None if legacy else 0.79,
                "verification_reason": "no_hard_veto",
                "verification_status": "unverified",
            },
            {
                "candidate_kg_id": "node:candidate_b" if legacy else "node:candidate_a",
                "candidate_label": "Candidate B" if legacy else "Candidate A",
                "rank_before_rerank": 1 if legacy else 2,
                "rank_after_rerank": 2,
                "leverage_score": 0.9 if legacy else 0.88,
                "novelty_score": 0.73,
                "coherence_score": 0.49,
                "feasibility_score": 0.51,
                "domain_overlap_score": 0.62,
                "principle_score": None if legacy else 0.61,
                "verification_reason": (
                    "gfs_paper_store_unconfigured" if legacy else "no_hard_veto"
                ),
                "verification_status": "unverified",
            },
        ],
        "summary": {
            "n_requested": 2,
            "n_hypotheses": 2,
            "n_returned": 2,
            "n_vetoed": 1 if legacy else 0,
        },
        "diagnostics": {
            "ood_verification": {
                "partial_return": False,
                "stop_reason": None,
                "gfs_calls_total": 4 if legacy else 2,
                "verification_reason_counts": {
                    "no_hard_veto": 1 if legacy else 2,
                    "gfs_paper_store_unconfigured": 1 if legacy else 0,
                },
            }
        },
    }
    if not legacy:
        ood_result.update(
            {
                "principle_session_key": "pcs_demo",
                "active_principle": {
                    "principle_id": "contradiction_resolving",
                    "label": "Contradiction-resolving search",
                },
                "principle_confidence": 0.67,
                "selection_reason": "contradiction_triggered",
                "anomaly_flags": ["contradiction"],
                "principle_posterior": {"contradiction_resolving": 0.67},
            }
        )

    principle_state_update = (
        {
            "controller_mode": "principle_v0",
            "enabled": True,
            "session_key": "pcs_demo",
            "active_principle_id": "contradiction_resolving",
            "active_principle": {
                "principle_id": "contradiction_resolving",
                "label": "Contradiction-resolving search",
            },
            "principle_confidence": 0.67,
            "posterior": {"contradiction_resolving": 0.67},
            "selection_reason": "contradiction_triggered",
            "anomaly_flags": ["contradiction"],
        }
        if not legacy
        else {
            "controller_mode": "legacy",
            "enabled": False,
            "session_key": "pcs_legacy",
            "selection_reason": "legacy_mode_disabled",
        }
    )

    return {
        "workflow": "workflow_hypothesis_candidate_cards",
        "query": query,
        "steps": {
            "leverage": {
                "data": {
                    "resolved_seed_kg_ids": ["node:seed"],
                    "result": {
                        "items": [
                            {
                                "kg_id": "node:candidate_a",
                                "label": "Candidate A",
                                "leverage_score": 0.88,
                            },
                            {
                                "kg_id": "node:candidate_b",
                                "label": "Candidate B",
                                "leverage_score": 0.9,
                            },
                        ]
                    },
                }
            },
            "principle_state_init": {"data": {"result": {"controller_mode": controller_mode}}},
            "ood_sampling": {"data": {"result": ood_result}},
            "verify_sampled_hypotheses": {
                "data": {
                    "result": {
                        "diagnostics": {
                            "total_duration_s": 1.24 if legacy else 0.88,
                            "phase_totals_s": {
                                "entity_resolution": 0.11,
                                "direct_evidence_collection": 0.44 if legacy else 0.31,
                                "typed_path_evidence_collection": 0.05,
                                "family_fallback_lookup": 0.02,
                                "family_fallback_evidence_collection": 0.03,
                                "aggregation": 0.08,
                                "total": 1.1 if legacy else 0.81,
                            },
                            "per_hypothesis": [
                                {
                                    "rank": 1,
                                    "candidate_kg_id": "node:candidate_a"
                                    if legacy
                                    else "node:candidate_b",
                                    "candidate_label": "Candidate A"
                                    if legacy
                                    else "Candidate B",
                                    "status": "success",
                                    "verdict": "supported",
                                    "wall_clock_s": 0.66 if legacy else 0.45,
                                    "timings_s": {
                                        "entity_resolution": 0.06,
                                        "direct_evidence_collection": 0.23,
                                        "aggregation": 0.04,
                                        "total": 0.51 if legacy else 0.37,
                                    },
                                },
                                {
                                    "rank": 2,
                                    "candidate_kg_id": "node:candidate_b"
                                    if legacy
                                    else "node:candidate_a",
                                    "candidate_label": "Candidate B"
                                    if legacy
                                    else "Candidate A",
                                    "status": "success",
                                    "verdict": "mixed",
                                    "wall_clock_s": 0.58 if legacy else 0.43,
                                    "timings_s": {
                                        "entity_resolution": 0.05,
                                        "direct_evidence_collection": 0.21,
                                        "aggregation": 0.04,
                                        "total": 0.59 if legacy else 0.44,
                                    },
                                },
                            ],
                        },
                        "summary": {
                            "mean_entity_hint_quality_score": 0.85 if legacy else 1.0,
                            "mean_evidence_item_count": 1.5 if legacy else 2.0,
                            "entity_hint_quality_counts": {
                                "exact_pair": 1,
                                "label_pair": 1 if legacy else 0,
                            },
                        }
                    }
                }
            },
            "contradiction_scan": {
                "data": {
                    "result": {
                        "motifs": [
                            {
                                "publication_label": "Example Contradiction Paper",
                                "support_count": 3,
                                "conflict_count": 2,
                                "motif_score": 0.71,
                                "contradiction_density": 0.4,
                            }
                        ]
                    }
                }
            },
            "topology_shift_scan": {
                "data": {
                    "result": {
                        "proposals": [{"delta": 0.2}] if not legacy else [],
                        "diagnostics": {
                            "total_duration_s": 0.42 if legacy else 0.57,
                            "phase_totals_s": {
                                "seed_derivation": 0.0,
                                "scan_query": 0.33 if legacy else 0.41,
                                "proposal_build": 0.09 if legacy else 0.16,
                                "apply_writes": 0.0,
                                "total": 0.42 if legacy else 0.57,
                            },
                            "per_proposal": [
                                {
                                    "source_id": "node:seed",
                                    "target_id": "node:candidate_b",
                                    "rel_type": "RELATED_TO",
                                    "delta": 0.2,
                                    "status": "proposal",
                                    "write_wall_clock_s": 0.0,
                                    "error": None,
                                }
                            ]
                            if not legacy
                            else [],
                        },
                    }
                }
            },
            "principle_state_update": {"data": {"result": principle_state_update}},
        },
    }


def test_controller_eval_report_round_trip(tmp_path: Path):
    config_path = tmp_path / "controller_eval.yaml"
    config_path.write_text(
        "\n".join(
            [
                "defaults:",
                "  top_k: 8",
                "  n_samples: 2",
                "  taste_mode: balanced",
                "cases:",
                "  - id: case_a",
                '    query: "fmri based image decoding"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    defaults, cases = load_eval_cases(config_path)
    assert defaults["top_k"] == 8
    assert cases[0]["taste_mode"] == "balanced"

    def fake_execute_tool(tool_id: str, params: dict) -> ToolResult:
        assert tool_id == "workflow_hypothesis_candidate_cards"
        return ToolResult(
            status="success",
            data=_build_workflow_result(
                controller_mode=str(params["controller_mode"]),
                query=str(params["query"]),
            ),
        )

    report = run_controller_evaluation(cases, execute_tool_fn=fake_execute_tool)
    assert report["overall_summary"]["cases_total"] == 1
    assert report["overall_summary"]["cases_with_top_candidate_change"] == 1
    case_report = report["cases"][0]
    assert case_report["comparison"]["top_candidate_changed"] is True
    assert case_report["comparison"]["active_principle_id"] == "contradiction_resolving"
    assert (
        case_report["runs"]["principle_v0"]["metrics"]["principle_metadata_coverage"]
        == 1.0
    )
    assert case_report["runs"]["legacy"]["metrics"]["ood_gfs_calls_total"] == 4
    assert case_report["runs"]["legacy"]["metrics"]["ood_partial_return"] is False
    assert (
        case_report["runs"]["legacy"]["metrics"]["mean_entity_hint_quality_score"]
        == 0.85
    )
    assert case_report["runs"]["legacy"]["metrics"]["mean_evidence_item_count"] == 1.5
    assert case_report["runs"]["legacy"]["metrics"]["entity_hint_quality_counts"] == {
        "exact_pair": 1,
        "label_pair": 1,
    }
    assert (
        case_report["runs"]["legacy"]["metrics"]["ood_verification_reason_counts"][
            "gfs_paper_store_unconfigured"
        ]
        == 1
    )
    assert case_report["runs"]["legacy"]["metrics"]["candidates_ordered"][0][
        "candidate_kg_id"
    ] == "node:candidate_a"
    assert case_report["runs"]["principle_v0"]["metrics"]["candidates_ordered"][0][
        "verification_reason"
    ] == "no_hard_veto"
    assert case_report["runs"]["legacy"]["metrics"]["verify_total_duration_s"] == 1.24
    assert case_report["runs"]["principle_v0"]["metrics"]["verify_phase_totals_s"][
        "direct_evidence_collection"
    ] == 0.31
    assert case_report["runs"]["principle_v0"]["metrics"]["verify_hypothesis_breakdown"][0][
        "verify_total_s"
    ] == 0.37
    assert case_report["runs"]["principle_v0"]["metrics"]["topology_total_duration_s"] == 0.57
    assert case_report["runs"]["principle_v0"]["metrics"]["topology_phase_totals_s"][
        "scan_query"
    ] == 0.41
    assert case_report["runs"]["principle_v0"]["metrics"]["topology_proposal_breakdown"][0][
        "status"
    ] == "proposal"

    output_dir = tmp_path / "out"
    paths = write_controller_evaluation_report(report, output_dir=output_dir)
    assert Path(paths["json_path"]).exists()
    assert Path(paths["markdown_path"]).exists()
    assert Path(paths["raw_dir"]).exists()

    stored = json.loads(Path(paths["json_path"]).read_text(encoding="utf-8"))
    stored_case = stored["cases"][0]
    assert stored_case["runs"]["legacy"]["workflow_result_path"].endswith(
        "case_a__legacy.json"
    )
    assert stored_case["runs"]["principle_v0"]["workflow_result_path"].endswith(
        "case_a__principle_v0.json"
    )
    markdown = Path(paths["markdown_path"]).read_text(encoding="utf-8")
    assert "Hypothesis Controller Evaluation" in markdown
    assert "contradiction_resolving" in markdown
    assert "ordered candidates:" in markdown
    assert "verify breakdown:" in markdown
    assert "topology breakdown:" in markdown


def test_filter_eval_cases_selects_requested_ids_in_config_order():
    cases = [
        {"id": "case_a", "query": "a"},
        {"id": "case_b", "query": "b"},
        {"id": "case_c", "query": "c"},
    ]

    filtered = filter_eval_cases(cases, ["case_c", "case_a"])

    assert [case["id"] for case in filtered] == ["case_a", "case_c"]


def test_apply_eval_case_overrides_updates_selected_fields():
    cases = [
        {"id": "case_a", "query": "a", "top_k": 12, "n_samples": 5},
        {"id": "case_b", "query": "b", "top_k": 10, "n_samples": 3},
    ]

    overridden = apply_eval_case_overrides(cases, top_k=4, n_samples=2)

    assert [case["top_k"] for case in overridden] == [4, 4]
    assert [case["n_samples"] for case in overridden] == [2, 2]
    assert [case["id"] for case in overridden] == ["case_a", "case_b"]


def test_filter_eval_cases_rejects_unknown_ids():
    cases = [{"id": "case_a", "query": "a"}]

    try:
        filter_eval_cases(cases, ["case_a", "missing_case"])
    except ValueError as exc:
        assert "missing_case" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected ValueError for unknown controller eval case id")


def test_controller_eval_flushes_per_case(tmp_path: Path):
    cases = [
        {
            "id": "case_a",
            "query": "fmri based image decoding",
            "n_samples": 2,
            "taste_mode": "balanced",
        }
    ]

    def fake_execute_tool(tool_id: str, params: dict) -> ToolResult:
        return ToolResult(
            status="success",
            data=_build_workflow_result(
                controller_mode=str(params["controller_mode"]),
                query=str(params["query"]),
            ),
        )

    flushed_paths: list[Path] = []

    def on_case_complete(case_report: dict) -> None:
        paths = write_controller_case_result(case_report, output_dir=tmp_path)
        flushed_paths.append(Path(paths["case_json_path"]))

    report = run_controller_evaluation(
        cases,
        execute_tool_fn=fake_execute_tool,
        on_case_complete=on_case_complete,
    )

    assert report["cases"][0]["case_id"] == "case_a"
    assert flushed_paths
    stored_case = json.loads(flushed_paths[0].read_text(encoding="utf-8"))
    assert stored_case["case_id"] == "case_a"
    assert stored_case["runs"]["legacy"]["workflow_result_path"].endswith(
        "case_a__legacy.json"
    )


def test_controller_eval_marks_timeout_and_continues():
    cases = [
        {
            "id": "slow_case",
            "query": "fmri based image decoding",
            "n_samples": 2,
        }
    ]

    def slow_execute_tool(tool_id: str, params: dict) -> ToolResult:
        time.sleep(0.2)
        return ToolResult(status="success", data={})

    report = run_controller_evaluation(
        cases,
        case_timeout_seconds=0.01,
        execute_tool_fn=slow_execute_tool,
    )

    case_report = report["cases"][0]
    assert case_report["runs"]["legacy"]["status"] == "timeout"
    assert case_report["runs"]["legacy"]["timed_out"] is True
    assert case_report["runs"]["principle_v0"]["status"] == "timeout"
    assert report["overall_summary"]["modes"]["legacy"]["successful_cases"] == 0
    assert report["overall_summary"]["modes"]["principle_v0"]["successful_cases"] == 0


def test_controller_eval_logs_case_and_mode_progress(caplog):
    cases = [
        {
            "id": "case_a",
            "query": "fmri based image decoding",
            "n_samples": 2,
        }
    ]

    def fake_execute_tool(tool_id: str, params: dict) -> ToolResult:
        return ToolResult(
            status="success",
            data=_build_workflow_result(
                controller_mode=str(params["controller_mode"]),
                query=str(params["query"]),
            ),
        )

    caplog.set_level("INFO", logger="brain_researcher.services.agent.controller_eval")

    run_controller_evaluation(cases, execute_tool_fn=fake_execute_tool, trace_steps=True)

    assert "controller_eval.case.start case=case_a" in caplog.text
    assert "controller_eval.mode.start case=case_a mode=legacy" in caplog.text
    assert "controller_eval.mode.finish case=case_a mode=principle_v0 status=success" in caplog.text
    assert "controller_eval.case.finish case=case_a" in caplog.text


def test_controller_eval_timeout_worker_prefers_fork(monkeypatch):
    calls: dict[str, object] = {}

    class DummyWriter:
        def close(self) -> None:
            calls["writer_closed"] = True

    class DummyReader:
        def close(self) -> None:
            calls["reader_closed"] = True

    class DummyProcess:
        pid = 12345

        def start(self) -> None:
            calls["started"] = True

    class DummyContext:
        def Pipe(self, duplex: bool = False):
            calls["duplex"] = duplex
            return DummyReader(), DummyWriter()

        def Process(self, target=None, kwargs=None):
            calls["target"] = target
            calls["kwargs"] = kwargs
            return DummyProcess()

    def fake_get_context(method: str | None = None):
        calls["context_method"] = method
        return DummyContext()

    monkeypatch.setattr(
        controller_eval.mp,
        "get_all_start_methods",
        lambda: ["spawn", "fork"],
    )
    monkeypatch.setattr(controller_eval.mp, "get_context", fake_get_context)

    proc, reader = controller_eval._spawn_eval_timeout_worker(
        workflow_id="workflow_hypothesis_candidate_cards",
        params={"query": "fmri based image decoding"},
    )

    assert isinstance(proc, DummyProcess)
    assert isinstance(reader, DummyReader)
    assert calls["context_method"] == "fork"
    assert calls["target"] is controller_eval._controller_eval_timeout_worker
    worker_kwargs = calls["kwargs"]
    assert worker_kwargs["workflow_id"] == "workflow_hypothesis_candidate_cards"
    assert worker_kwargs["params"] == {"query": "fmri based image decoding"}
    assert worker_kwargs["trace_steps"] is False
    assert worker_kwargs["trace_label"] is None
    assert calls["started"] is True
    assert calls["writer_closed"] is True


def test_controller_eval_process_isolation_uses_module_execute_tool(monkeypatch):
    if os.name != "posix" or "fork" not in controller_eval.mp.get_all_start_methods():
        return

    cases = [
        {
            "id": "case_a",
            "query": "fmri based image decoding",
            "n_samples": 2,
            "taste_mode": "balanced",
        }
    ]

    def fake_execute_tool(tool_id: str, params: dict) -> ToolResult:
        assert tool_id == "workflow_hypothesis_candidate_cards"
        return ToolResult(
            status="success",
            data=_build_workflow_result(
                controller_mode=str(params["controller_mode"]),
                query=str(params["query"]),
            ),
        )

    monkeypatch.setattr(controller_eval, "execute_tool", fake_execute_tool)
    report = run_controller_evaluation(
        cases,
        case_timeout_seconds=1.0,
        execute_tool_fn=controller_eval.execute_tool,
    )

    case_report = report["cases"][0]
    assert case_report["runs"]["legacy"]["status"] == "success"
    assert case_report["runs"]["principle_v0"]["status"] == "success"
    assert report["overall_summary"]["modes"]["legacy"]["successful_cases"] == 1
    assert report["overall_summary"]["modes"]["principle_v0"]["successful_cases"] == 1


def test_controller_eval_process_isolation_handles_large_payload(monkeypatch):
    if os.name != "posix" or "fork" not in controller_eval.mp.get_all_start_methods():
        return

    cases = [
        {
            "id": "case_large",
            "query": "fmri based image decoding",
            "n_samples": 1,
            "taste_mode": "balanced",
        }
    ]
    large_blob = "x" * (2 * 1024 * 1024)

    def fake_execute_tool(tool_id: str, params: dict) -> ToolResult:
        assert tool_id == "workflow_hypothesis_candidate_cards"
        payload = _build_workflow_result(
            controller_mode=str(params["controller_mode"]),
            query=str(params["query"]),
        )
        payload["large_blob"] = large_blob
        return ToolResult(status="success", data=payload)

    monkeypatch.setattr(controller_eval, "execute_tool", fake_execute_tool)
    report = run_controller_evaluation(
        cases,
        case_timeout_seconds=5.0,
        execute_tool_fn=controller_eval.execute_tool,
    )

    case_report = report["cases"][0]
    assert case_report["runs"]["legacy"]["status"] == "success"
    assert case_report["runs"]["principle_v0"]["status"] == "success"
    isolation_meta = case_report["runs"]["legacy"]["isolation"]
    assert isolation_meta["transport"] == "spill_file"
    assert isolation_meta["result_bytes"] > 1024


def test_controller_eval_inline_python_supports_timeout_path():
    if os.name != "posix" or "fork" not in controller_eval.mp.get_all_start_methods():
        return

    repo_root = Path(__file__).resolve().parents[3]
    script = textwrap.dedent(
        """
        import json
        import brain_researcher.services.agent.controller_eval as controller_eval
        from brain_researcher.services.tools.tool_base import ToolResult

        def _build(controller_mode: str, query: str) -> dict:
            legacy = controller_mode == "legacy"
            ood_result = {
                "hypotheses": [],
                "summary": {"n_requested": 1, "n_hypotheses": 0, "n_returned": 0, "n_vetoed": 0},
            }
            if not legacy:
                ood_result.update(
                    {
                        "principle_session_key": "pcs_demo",
                        "active_principle": {"principle_id": "balanced", "label": "Balanced"},
                        "principle_confidence": 0.5,
                        "selection_reason": "balanced:weighted_rerank",
                    }
                )
            return {
                "workflow": "workflow_hypothesis_candidate_cards",
                "query": query,
                "steps": {
                    "leverage": {"data": {"resolved_seed_kg_ids": ["node:seed"], "result": {"items": []}}},
                    "principle_state_init": {"data": {"result": {"controller_mode": controller_mode}}},
                    "ood_sampling": {"data": {"result": ood_result}},
                    "contradiction_scan": {"data": {"result": {"motifs": []}}},
                    "topology_shift_scan": {"data": {"result": {"proposals": []}}},
                    "principle_state_update": {
                        "data": {
                            "result": {
                                "controller_mode": controller_mode,
                                "active_principle_id": "balanced" if not legacy else None,
                                "active_principle": (
                                    {"principle_id": "balanced", "label": "Balanced"} if not legacy else None
                                ),
                            }
                        }
                    },
                },
            }

        def fake_execute_tool(tool_id: str, params: dict) -> ToolResult:
            return ToolResult(
                status="success",
                data=_build(str(params["controller_mode"]), str(params["query"])),
            )

        controller_eval.execute_tool = fake_execute_tool
        report = controller_eval.run_controller_evaluation(
            [{"id": "case_inline", "query": "fmri based image decoding", "n_samples": 1}],
            case_timeout_seconds=1.0,
            execute_tool_fn=controller_eval.execute_tool,
        )
        print(
            json.dumps(
                {
                    "legacy": report["cases"][0]["runs"]["legacy"]["status"],
                    "principle_v0": report["cases"][0]["runs"]["principle_v0"]["status"],
                },
                sort_keys=True,
            )
        )
        """
    )
    env = dict(os.environ)
    pythonpath_parts = [str(repo_root / "src")]
    if env.get("PYTHONPATH"):
        pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {"legacy": "success", "principle_v0": "success"}
