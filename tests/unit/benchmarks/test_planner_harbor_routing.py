from __future__ import annotations

from collections import Counter

from benchmarks.planner_harbor_routing import runner


def test_load_harbor_tasks_counts():
    tasks = runner.load_harbor_tasks()

    assert len(tasks) == 389
    counts = Counter(task.suite_alias for task in tasks)
    assert counts == {
        "qabench": 137,
        "qarubric": 94,
        "metaanalysis": 63,
        "codebench": 95,
    }


def test_load_harbor_task_keeps_haxby_as_fmri():
    tasks = runner.load_harbor_tasks(
        suite_aliases=["codebench"],
        task_ids=["OPENNEURO-ML-005"],
    )

    assert len(tasks) == 1
    assert tasks[0].modality == "fmri"


def test_evaluate_task_extracts_routing_and_benchmark_join():
    task = runner.HarborRoutingTask(
        suite_alias="qabench",
        suite_file="neuroimage-theory-bench.harbor.json",
        task_id="TASK-1",
        title="TASK-1",
        category="STATS",
        difficulty="easy",
        query="What is reverse inference?",
        domain="neuroimaging",
        modality="general",
        tags=[],
        source_path="/tmp/bench.json",
    )

    class _FakeResponse:
        status_code = 200

        def get_json(self):
            return {
                "resolvable": True,
                "chosen_tool": "python.reverse_inference.run",
                "planner_state": {
                    "routing_diagnostics": {
                        "candidate_count": 3,
                        "planner_candidate_count": 3,
                        "planner_candidate_source_counts": {"catalog": 2, "br_kg": 1},
                        "selected_tool_rank": 2,
                        "selected_tool_in_top_5": True,
                        "selected_tool_in_top_10": True,
                        "routing_latency_ms": 42.5,
                        "candidate_source_counts": {"catalog": 2, "br_kg": 1},
                    },
                    "tool_candidate_diagnostics": {
                        "candidate_generation_latency_ms": 9.5,
                        "candidate_count": 4,
                        "candidate_source_counts": {"catalog": 4},
                        "retrieval_path": "query_service",
                        "candidate_source": "mixed",
                    },
                },
            }

    class _FakeClient:
        def post(self, path, json):  # noqa: A002 - match Flask client signature
            assert path == "/agent/plan"
            assert json["pipeline"] == task.query
            assert json["domain"] == "neuroimaging"
            return _FakeResponse()

    row = runner.evaluate_task(
        _FakeClient(),
        task,
        external_results={
            "TASK-1": {
                "task_id": "TASK-1",
                "final_status": "success",
                "final_evaluation": {"score": 1.0},
            }
        },
    )

    assert row["chosen_tool"] == "python.reverse_inference.run"
    assert row["http_ok"] is True
    assert row["request_ok"] is True
    assert row["plan_resolved"] is True
    assert row["selected_tool_rank"] == 2
    assert row["selected_tool_in_top_5"] is True
    assert row["candidate_count"] == 3
    assert row["planner_candidate_count"] == 3
    assert row["preflight_candidate_count"] == 4
    assert row["candidate_generation_latency_ms"] == 9.5
    assert row["candidate_source_counts"] == {"catalog": 2, "br_kg": 1}
    assert row["preflight_candidate_source_counts"] == {"catalog": 4}
    assert row["preflight_retrieval_path"] == "query_service"
    assert row["benchmark_final_status"] == "success"
    assert row["benchmark_passed"] is True
    assert row["allowlist_mode"] == "curated"


def test_build_plan_payload_and_row_carry_allowlist_mode():
    task = runner.HarborRoutingTask(
        suite_alias="codebench",
        suite_file="neuroimage-code-bench.harbor.json",
        task_id="TASK-4",
        title="TASK-4",
        category="ML",
        difficulty="medium",
        query="Execution task",
        domain="neuroimaging",
        modality="fmri",
        tags=[],
        source_path="/tmp/bench.json",
    )

    payload = runner._build_plan_payload(task, allowlist_mode="diagnostic")
    assert payload["allowlist_mode"] == "diagnostic"

    class _FakeResponse:
        status_code = 200

        def get_json(self):
            return {
                "resolvable": True,
                "chosen_tool": "blocked.tool",
                "planner_state": {
                    "routing_diagnostics": {
                        "candidate_count": 1,
                        "planner_candidate_count": 1,
                        "selected_tool_rank": 1,
                        "selected_tool_in_top_5": True,
                        "selected_tool_in_top_10": True,
                        "routing_latency_ms": 1.0,
                    }
                },
            }

    class _FakeClient:
        def post(self, path, json):  # noqa: A002
            assert json["allowlist_mode"] == "diagnostic"
            return _FakeResponse()

    row = runner.evaluate_task(_FakeClient(), task, allowlist_mode="diagnostic")
    assert row["allowlist_mode"] == "diagnostic"


def test_build_env_overrides_enables_full_runtime_for_diagnostic_mode():
    overrides = runner._build_env_overrides(
        preset="baseline",
        env_overrides=[],
        allowlist_mode="diagnostic",
    )

    assert overrides["BR_AGENT_ALLOW_ALL_RUNTIME_TOOLS"] == "1"
    assert overrides["BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS"] == "1"


def test_evaluate_task_extracts_terminal_reason_and_denial_metadata():
    task = runner.HarborRoutingTask(
        suite_alias="codebench",
        suite_file="neuroimage-code-bench.harbor.json",
        task_id="TASK-2",
        title="TASK-2",
        category="ML",
        difficulty="hard",
        query="Execution task",
        domain="neuroimaging",
        modality="fmri",
        tags=[],
        source_path="/tmp/bench.json",
    )

    class _NoToolResponse:
        status_code = 200

        def get_json(self):
            return {
                "resolvable": False,
                "chosen_tool": None,
                "planner_state": {
                    "routing_diagnostics": {
                        "candidate_count": 2,
                        "planner_candidate_count": 2,
                        "planner_candidate_source_counts": {"catalog": 2},
                        "preflight_candidate_count": 5,
                        "preflight_candidate_source_counts": {"catalog": 5},
                        "selected_tool_rank": None,
                        "selected_tool_in_top_5": False,
                        "selected_tool_in_top_10": False,
                        "routing_terminal_reason": "plan_returned_without_tool_choice",
                        "routing_latency_ms": 51.0,
                        "candidate_source_counts": {"catalog": 2},
                    },
                    "tool_candidate_diagnostics": {
                        "candidate_generation_latency_ms": 8.0,
                        "retrieval_path": "query_service",
                    },
                },
            }

    class _DeniedResponse:
        status_code = 403

        def get_json(self):
            return {
                "error": "tool_not_allowed",
                "denied_tool_id": "fsl_bet",
                "denied_family": "fsl",
                "denial_stage": "post_plan_validation",
                "denial_reason_code": "selected_tool_not_permitted",
            }

    class _FakeClient:
        def __init__(self):
            self._calls = 0

        def post(self, path, json):  # noqa: A002 - match Flask client signature
            assert path == "/agent/plan"
            self._calls += 1
            return _NoToolResponse() if self._calls == 1 else _DeniedResponse()

    client = _FakeClient()
    row = runner.evaluate_task(client, task)
    assert row["http_ok"] is True
    assert row["request_ok"] is False
    assert row["plan_resolved"] is False
    assert row["routing_terminal_reason"] == "plan_returned_without_tool_choice"
    assert row["candidate_count"] == 2
    assert row["preflight_candidate_count"] == 5
    assert row["denied_tool_id"] is None
    assert row["denied_family"] is None
    assert row["denial_stage"] is None

    denied_row = runner.evaluate_task(client, task)
    assert denied_row["http_ok"] is False
    assert denied_row["request_ok"] is False
    assert denied_row["error"] == "tool_not_allowed"
    assert denied_row["denied_tool_id"] == "fsl_bet"
    assert denied_row["denied_family"] == "fsl"
    assert denied_row["denial_stage"] == "post_plan_validation"
    assert denied_row["denial_reason_code"] == "selected_tool_not_permitted"


def test_evaluate_task_uses_planner_candidates_not_preflight_candidates():
    task = runner.HarborRoutingTask(
        suite_alias="codebench",
        suite_file="neuroimage-code-bench.harbor.json",
        task_id="TASK-3",
        title="TASK-3",
        category="ML",
        difficulty="hard",
        query="Execution task",
        domain="neuroimaging",
        modality="fmri",
        tags=[],
        source_path="/tmp/bench.json",
    )

    class _NoPlannerCandidateResponse:
        status_code = 200

        def get_json(self):
            return {
                "resolvable": False,
                "chosen_tool": None,
                "candidates": [],
                "planner_state": {
                    "routing_diagnostics": {
                        "candidate_count": 0,
                        "planner_candidate_count": 0,
                        "planner_candidate_source_counts": {},
                        "preflight_candidate_count": 12,
                        "preflight_candidate_source_counts": {"br_kg": 12},
                        "routing_terminal_reason": "preflight_candidates_not_promoted_to_plan",
                        "routing_latency_ms": 88.0,
                    },
                    "tool_candidate_diagnostics": {
                        "candidate_count": 12,
                        "candidate_generation_latency_ms": 15.0,
                        "candidate_source_counts": {"br_kg": 12},
                        "candidate_source": "br_kg",
                        "retrieval_path": "query_service",
                    },
                },
            }

    class _FakeClient:
        def post(self, path, json):  # noqa: A002 - match Flask client signature
            assert path == "/agent/plan"
            return _NoPlannerCandidateResponse()

    row = runner.evaluate_task(_FakeClient(), task)

    assert row["http_ok"] is True
    assert row["request_ok"] is False
    assert row["plan_resolved"] is False
    assert row["candidate_count"] == 0
    assert row["planner_candidate_count"] == 0
    assert row["preflight_candidate_count"] == 12
    assert row["candidate_source_counts"] == {}
    assert row["preflight_candidate_source_counts"] == {"br_kg": 12}
    assert row["routing_terminal_reason"] == "preflight_candidates_not_promoted_to_plan"


def test_summarize_rows_and_write_csv(tmp_path):
    rows = [
        {
            "variant": "baseline",
            "suite_alias": "qabench",
            "suite_file": "a.json",
            "task_id": "TASK-1",
            "title": "TASK-1",
            "category": "STATS",
            "difficulty": "easy",
            "domain": "neuroimaging",
            "modality": "general",
            "http_ok": True,
            "request_ok": True,
            "plan_resolved": True,
            "resolvable": True,
            "status_code": 200,
            "chosen_tool": "tool.a",
            "candidate_count": 3,
            "planner_candidate_count": 3,
            "preflight_candidate_count": 4,
            "selected_tool_rank": 1,
            "selected_tool_in_top_5": True,
            "selected_tool_in_top_10": True,
            "routing_terminal_reason": None,
            "candidate_generation_latency_ms": 10.0,
            "routing_latency_ms": 30.0,
            "candidate_source": "catalog",
            "planner_candidate_source": "catalog",
            "preflight_candidate_source": "catalog",
            "preflight_retrieval_path": "query_service",
            "denied_tool_id": None,
            "denied_family": None,
            "denial_stage": None,
            "denial_reason_code": None,
            "benchmark_final_status": "success",
            "benchmark_passed": True,
            "env_overrides_json": '{"BR_PLANNER_USE_EVIDENCE_PRIOR":"0"}',
            "candidate_source_counts": {"catalog": 3},
            "planner_candidate_source_counts": {"catalog": 3},
            "preflight_candidate_source_counts": {"catalog": 4},
        },
        {
            "variant": "baseline",
            "suite_alias": "qabench",
            "suite_file": "a.json",
            "task_id": "TASK-2",
            "title": "TASK-2",
            "category": "STATS",
            "difficulty": "medium",
            "domain": "neuroimaging",
            "modality": "general",
            "http_ok": True,
            "request_ok": False,
            "plan_resolved": False,
            "resolvable": False,
            "status_code": 200,
            "chosen_tool": None,
            "candidate_count": 0,
            "planner_candidate_count": 0,
            "preflight_candidate_count": 5,
            "selected_tool_rank": None,
            "selected_tool_in_top_5": False,
            "selected_tool_in_top_10": False,
            "routing_terminal_reason": "preflight_candidates_not_promoted_to_plan",
            "candidate_generation_latency_ms": 20.0,
            "routing_latency_ms": 40.0,
            "candidate_source": None,
            "planner_candidate_source": None,
            "preflight_candidate_source": "mixed",
            "preflight_retrieval_path": "embedding",
            "denied_tool_id": None,
            "denied_family": None,
            "denial_stage": None,
            "denial_reason_code": None,
            "benchmark_final_status": "failed",
            "benchmark_passed": False,
            "env_overrides_json": '{"BR_PLANNER_USE_EVIDENCE_PRIOR":"0"}',
            "candidate_source_counts": {},
            "planner_candidate_source_counts": {},
            "preflight_candidate_source_counts": {"catalog": 2, "br_kg": 3},
        },
    ]

    summary = runner.summarize_rows(rows)
    assert summary["overall"]["task_count"] == 2
    assert summary["overall"]["selected_tool_in_top_5_rate"] == 0.5
    assert summary["overall"]["http_ok_rate"] == 1.0
    assert summary["overall"]["benchmark_pass_rate"] == 0.5
    assert summary["overall"]["benchmark_pass_rate_when_top_5"] == 1.0
    assert summary["overall"]["request_ok_rate"] == 0.5
    assert summary["overall"]["mean_preflight_candidate_count"] == 4.5
    assert summary["overall"]["candidate_source_mix"] == {"catalog": 3}
    assert summary["overall"]["preflight_candidate_source_mix"] == {
        "catalog": 6,
        "br_kg": 3,
    }

    out_csv = tmp_path / "routing.csv"
    runner.write_csv_report(out_csv, rows)
    csv_text = out_csv.read_text(encoding="utf-8")
    assert "variant" in csv_text.splitlines()[0]
    assert "env_overrides_json" in csv_text.splitlines()[0]
    assert "TASK-1" in csv_text
