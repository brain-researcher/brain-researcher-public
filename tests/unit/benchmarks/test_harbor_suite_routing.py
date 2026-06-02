from __future__ import annotations

import json
from pathlib import Path

import pytest
from benchmarks.harbor_suite_routing.runner import (
    HarborRoutingEvaluator,
    HarborRoutingSuiteSpec,
    default_suite_specs,
    load_benchmark_join_index,
    load_harbor_suite_tasks,
)


def test_default_suite_specs_cover_four_harbor_suites():
    specs = default_suite_specs()
    assert [spec.suite_key for spec in specs] == [
        "qabench",
        "qarubric",
        "meta-analysis",
        "codebench",
    ]

    counts = {spec.suite_key: len(load_harbor_suite_tasks(spec)) for spec in specs}
    assert counts == {
        "qabench": 137,
        "qarubric": 94,
        "meta-analysis": 63,
        "codebench": 95,
    }


class _FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def get_json(self):
        return self._payload


class _FakePlanClient:
    def __init__(self):
        self.requests: list[dict[str, object]] = []

    def post(self, endpoint: str, json: dict[str, object] | None = None):
        payload = dict(json or {})
        self.requests.append({"endpoint": endpoint, "json": payload})
        suite_key = str(payload.get("benchmark_suite") or "")
        if suite_key == "qabench":
            diagnostics = {
                "candidate_count": 6,
                "selected_tool_rank": 3,
                "selected_tool_in_top_5": True,
                "selected_tool_in_top_10": True,
                "routing_latency_ms": 13.5,
                "candidate_source_counts": {"br_kg": 6},
                "candidate_source": "br_kg",
            }
        elif suite_key == "qarubric":
            diagnostics = {
                "candidate_count": 4,
                "selected_tool_rank": 7,
                "selected_tool_in_top_5": False,
                "selected_tool_in_top_10": True,
                "routing_latency_ms": 21.5,
                "candidate_source_counts": {"catalog": 4},
                "candidate_source": "catalog",
            }
        elif suite_key == "meta-analysis":
            diagnostics = {
                "candidate_count": 5,
                "selected_tool_rank": 8,
                "selected_tool_in_top_5": False,
                "selected_tool_in_top_10": True,
                "routing_latency_ms": 17.25,
                "candidate_source_counts": {"mixed": 5},
                "candidate_source": "mixed",
            }
        else:
            diagnostics = {
                "candidate_count": 7,
                "selected_tool_rank": 1,
                "selected_tool_in_top_5": True,
                "selected_tool_in_top_10": True,
                "routing_latency_ms": 9.0,
                "candidate_source_counts": {"catalog": 3, "br_kg": 4},
                "candidate_source": "mixed",
            }

        tool_candidates = [
            {
                "tool_id": f"{suite_key}.tool.{idx}",
                "source": "catalog" if idx % 2 == 0 else "br_kg",
            }
            for idx in range(1, diagnostics["candidate_count"] + 1)
        ]
        response = {
            "plan_id": f"plan-{suite_key or 'unknown'}",
            "chosen_tool": tool_candidates[0]["tool_id"],
            "candidates": tool_candidates,
            "routing_diagnostics": diagnostics,
            "planner_state": {
                "tool_candidates": tool_candidates,
                "tool_candidate_diagnostics": {
                    "candidate_count": diagnostics["candidate_count"],
                    "candidate_source_counts": diagnostics["candidate_source_counts"],
                    "candidate_generation_latency_ms": diagnostics[
                        "routing_latency_ms"
                    ],
                    "routing_latency_ms": diagnostics["routing_latency_ms"],
                },
                "routing_diagnostics": diagnostics,
            },
            "context": {
                "tool_candidates": tool_candidates,
                "tool_candidate_diagnostics": {
                    "candidate_count": diagnostics["candidate_count"],
                    "candidate_source_counts": diagnostics["candidate_source_counts"],
                    "candidate_generation_latency_ms": diagnostics[
                        "routing_latency_ms"
                    ],
                    "routing_latency_ms": diagnostics["routing_latency_ms"],
                },
            },
        }
        return _FakeResponse(response)


def test_harbor_routing_evaluator_emits_suite_rows_and_joins(tmp_path):
    join_path = tmp_path / "benchmark_results.json"
    join_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "task_id": "NK-E-001",
                        "final_status": "passed",
                        "completed_in_n_attempts": 1,
                        "total_attempts": 1,
                        "final_evaluation": {"score": 1.0},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    join_index = load_benchmark_join_index(join_path)
    client = _FakePlanClient()
    evaluator = HarborRoutingEvaluator(
        plan_client=client,
        variant_label="no_failure_prior",
        env_overrides={"BR_PLANNER_USE_FAILURE_PRIOR": "0"},
        benchmark_join_index=join_index,
    )

    report = evaluator.evaluate(
        suite_keys=["qabench", "qarubric", "meta-analysis", "codebench"],
        task_limit=1,
    )

    assert report.variant_label == "no_failure_prior"
    assert report.summary["suite_count"] == 4
    assert report.summary["overall"]["task_count"] == 4
    assert len(report.rows) == 4

    qabench_row = next(row for row in report.rows if row["suite_key"] == "qabench")
    meta_row = next(row for row in report.rows if row["suite_key"] == "meta-analysis")
    code_row = next(row for row in report.rows if row["suite_key"] == "codebench")

    assert qabench_row["candidate_count"] == 6
    assert qabench_row["selected_tool_rank"] == 3
    assert qabench_row["selected_tool_in_top_5"] is True
    assert qabench_row["benchmark_suite"] == "qabench"
    assert qabench_row["env_overrides_json"] == json.dumps(
        {"BR_PLANNER_USE_FAILURE_PRIOR": "0"},
        sort_keys=True,
    )
    assert qabench_row["benchmark_final_status"] == "passed"

    assert meta_row["selected_tool_rank"] == 8
    assert meta_row["selected_tool_in_top_5"] is False
    assert meta_row["candidate_source"] == "mixed"
    assert code_row["selected_tool_rank"] == 1

    assert report.summary["overall"]["hit_at_5"] == pytest.approx(0.5)
    assert report.summary["overall"]["hit_at_10"] == pytest.approx(1.0)
    assert report.suites[0]["suite_key"] == "qabench"
    assert report.suites[1]["task_count"] == 1


def test_main_writes_json_and_csv(tmp_path, monkeypatch):
    from benchmarks.harbor_suite_routing import runner as module

    fake_client = _FakePlanClient()
    monkeypatch.setattr(module, "_make_test_client", lambda: fake_client)
    out_json = tmp_path / "report.json"
    out_csv = tmp_path / "rows.csv"

    report = module.main(
        [
            "--suite",
            "qabench",
            "--task-limit",
            "1",
            "--variant-label",
            "baseline",
            "--env",
            "BR_PLANNER_USE_FAILURE_PRIOR=0",
            "--output-json",
            str(out_json),
            "--output-csv",
            str(out_csv),
        ]
    )

    assert out_json.exists()
    assert out_csv.exists()
    loaded = json.loads(out_json.read_text(encoding="utf-8"))
    assert loaded["variant_label"] == "baseline"
    assert loaded["summary"]["overall"]["task_count"] == 1
    assert report.rows[0]["suite_key"] == "qabench"
