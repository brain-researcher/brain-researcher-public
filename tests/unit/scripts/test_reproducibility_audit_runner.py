from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

from scripts.reproducibility_audit.run_reproducibility_audit_examples import (
    _has_provider_or_account_limit,
    canonical_validation_blocking,
    canonical_validation_tier,
    count_tool_events,
    episode_env,
    extract_last_message,
    extract_retrieval_provenance,
    has_error_event,
    main,
    run_command_to_files,
    score_contract_response,
    score_grounded_recommendation_response,
    write_run_metrics,
)


def _write_case_root(root: Path) -> None:
    case = {
        "case_id": "repro_case_test_gsr",
        "title": "Test GSR recommendation",
        "suite": "reproducibility_audit",
        "task_shape": "grounded_recommendation",
        "canonical_task": {
            "description": "Recommend whether to apply GSR.",
            "study_context": {"design": "case-control rsfMRI"},
            "required_evidence_families": ["Murphy 2009", "Saad 2012", "Power 2014"],
        },
        "output_contract": {
            "required_fields": [
                "answer",
                "key_points",
                "risks_or_failure_modes",
                "recommended_actions",
                "evidence_needed",
                "evidence_basis",
                "confidence",
            ]
        },
        "prompt_variants": [
            {
                "variant_id": "v01",
                "variant_type": "expert",
                "prompt": "Should I use GSR for case-control rsFC?",
            },
            {
                "variant_id": "v02",
                "variant_type": "junior",
                "prompt": "GSR yes or no?",
            },
        ],
        "scoring_axes": [
            {"axis": "intent", "canonical_expectation": "Recognize case-control rsfMRI."},
            {"axis": "recommendation", "canonical_expectation": "Conditional recommendation."},
            {"axis": "tradeoff_coverage", "canonical_expectation": "Cover tradeoffs."},
            {"axis": "evidence_anchors", "canonical_expectation": "Valid anchors."},
            {"axis": "caveat_presence", "canonical_expectation": "With and without GSR."},
            {"axis": "scope_hygiene", "canonical_expectation": "Do not overgeneralize."},
        ],
    }
    (root / "case_index.json").write_text(
        json.dumps(
            {
                "version": "0.1",
                "cases": [
                    {
                        "case_id": "repro_case_test_gsr",
                        "title": "Test GSR recommendation",
                        "priority": "expand_first",
                        "task_shape": "grounded_recommendation",
                        "file": "case_test.json",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "case_test.json").write_text(json.dumps(case) + "\n", encoding="utf-8")


def test_dry_run_materializes_selected_episode(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    out_root = tmp_path / "runs"
    cases_root.mkdir()
    _write_case_root(cases_root)

    rc = main(
        [
            "--cases-root",
            str(cases_root),
            "--case",
            "repro_case_test_gsr",
            "--variant",
            "v01",
            "--condition",
            "codex_with_br_gated",
            "--out-root",
            str(out_root),
            "--run-name",
            "smoke",
            "--dry-run",
        ]
    )

    assert rc == 0
    run_dir = out_root / "smoke"
    episode_dir = run_dir / "cases" / "repro_case_test_gsr" / "v01__codex_with_br_gated"
    assert (episode_dir / "prompt.txt").exists()
    assert (episode_dir / "prompt.json").exists()
    record = json.loads((episode_dir / "record.json").read_text(encoding="utf-8"))
    assert record["status"] == "materialized"
    assert record["token_cost_usd"] is None
    assert record["tool_call_count"] == 0

    prompt = (episode_dir / "prompt.txt").read_text(encoding="utf-8")
    assert "Brain Researcher MCP is enabled" in prompt
    assert "Do not call brain-researcher-prod/kg_probe" in prompt
    assert "retrieved_evidence_used mapping" in prompt
    assert '"retrieved_evidence_used"' in prompt
    assert '"diagnostic_family_mapping"' not in prompt
    assert "Return one JSON object only" in prompt
    assert "not a pointer to a file you wrote" in prompt

    episodes = (run_dir / "episodes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(episodes) == 1
    assert json.loads(episodes[0])["condition"] == "codex_with_br_gated"


def test_episode_manifest_runs_exact_rows_without_cartesian_expansion(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    out_root = tmp_path / "runs"
    manifest_path = tmp_path / "rerun_manifest.csv"
    cases_root.mkdir()
    _write_case_root(cases_root)
    with manifest_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["case_id", "variant_id", "condition", "status", "source_run"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "repro_case_test_gsr",
                "variant_id": "v01",
                "condition": "codex_with_br_gated",
                "status": "timed_out",
                "source_run": "old_run",
            }
        )
        writer.writerow(
            {
                "case_id": "repro_case_test_gsr",
                "variant_id": "v02",
                "condition": "codex_without_br",
                "status": "failed",
                "source_run": "old_run",
            }
        )

    rc = main(
        [
            "--cases-root",
            str(cases_root),
            "--episode-manifest",
            str(manifest_path),
            "--condition",
            "codex_with_br_gated",
            "--out-root",
            str(out_root),
            "--run-name",
            "manifest-smoke",
            "--dry-run",
        ]
    )

    assert rc == 0
    run_dir = out_root / "manifest-smoke"
    episodes = [
        json.loads(line)
        for line in (run_dir / "episodes.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [(row["variant_id"], row["condition"]) for row in episodes] == [
        ("v01", "codex_with_br_gated")
    ]
    assert not (
        run_dir / "cases" / "repro_case_test_gsr" / "v02__codex_with_br_gated"
    ).exists()
    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["episode_manifest_exact"] is True
    assert run_manifest["episode_manifest_rows"] == 1


def test_diagnostic_contract_is_opt_in_and_warns_against_hidden_targets(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    out_root = tmp_path / "runs"
    cases_root.mkdir()
    _write_case_root(cases_root)

    rc = main(
        [
            "--cases-root",
            str(cases_root),
            "--case",
            "repro_case_test_gsr",
            "--variant",
            "v01",
            "--condition",
            "codex_with_br_gated",
            "--out-root",
            str(out_root),
            "--run-name",
            "diagnostic-smoke",
            "--dry-run",
            "--diagnostic-contract",
        ]
    )

    assert rc == 0
    run_dir = out_root / "diagnostic-smoke"
    prompt = (
        run_dir
        / "cases"
        / "repro_case_test_gsr"
        / "v01__codex_with_br_gated"
        / "prompt.txt"
    ).read_text(encoding="utf-8")
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["diagnostic_contract"] is True
    assert '"diagnostic_family_mapping"' in prompt
    assert '"evidence_family"' in prompt
    assert '"required_family"' not in prompt
    assert "not a hidden benchmark key" in prompt
    assert "Do not invent benchmark" in prompt


def test_canonical_validation_tier_normalizes_draft_reviewed_locked() -> None:
    assert canonical_validation_tier({}) == "draft"
    assert canonical_validation_blocking({}) is True
    assert canonical_validation_tier({"canonical_validation": {"tier": "reviewed"}}) == "reviewed"
    assert canonical_validation_tier({"canonical_validation": {"status": "passed"}}) == "locked"
    assert canonical_validation_blocking(
        {"canonical_validation": {"status": "passed", "blocking": False}}
    ) is False


def test_execute_runs_non_grounded_task_shape_with_contract_scoring(
    tmp_path: Path, monkeypatch
) -> None:
    cases_root = tmp_path / "cases"
    out_root = tmp_path / "runs"
    cases_root.mkdir()
    _write_case_root(cases_root)
    case_path = cases_root / "case_test.json"
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case["task_shape"] = "executable_pipeline"
    case["output_contract"]["required_fields"] = ["answer", "artifacts", "validation"]
    case_path.write_text(json.dumps(case) + "\n", encoding="utf-8")

    def fake_run_agent_episode(**kwargs):
        episode_dir = Path(kwargs["episode_dir"])
        output_path = episode_dir / "last_message.txt"
        events_path = episode_dir / "events.jsonl"
        stderr_path = episode_dir / "stderr.txt"
        output_path.write_text(
            json.dumps(
                {
                    "answer": "Pipeline drafted.",
                    "artifacts": [{"path": "artifacts/pipeline.py", "type": "pipeline"}],
                    "validation": {"status": "not_run", "reason": "unit test fake runner"},
                    "evidence_basis": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        events_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return {
            "status": "succeeded",
            "returncode": 0,
            "timed_out": False,
            "early_stop_reason": None,
            "json_error_event": False,
            "wall_time_s": 0.1,
            "token_cost_usd": None,
            "tool_call_count": 0,
            "tools_used": [],
            "retry_count": 0,
            "model": "test-model",
            "runner": "codex_cli",
            "br_mode": None,
            "paths": {
                "last_message": str(output_path),
                "events": str(events_path),
                "stderr": str(stderr_path),
            },
        }

    monkeypatch.setattr(
        "scripts.reproducibility_audit.run_reproducibility_audit_examples.run_agent_episode",
        fake_run_agent_episode,
    )

    rc = main(
        [
            "--cases-root",
            str(cases_root),
            "--case",
            "repro_case_test_gsr",
            "--variant",
            "v01",
            "--condition",
            "codex_without_br",
            "--out-root",
            str(out_root),
            "--run-name",
            "smoke",
            "--execute",
        ]
    )

    assert rc == 0
    episode_dir = out_root / "smoke" / "cases" / "repro_case_test_gsr" / "v01__codex_without_br"
    record = json.loads((episode_dir / "record.json").read_text(encoding="utf-8"))
    assert record["status"] == "succeeded"
    assert record["task_shape"] == "executable_pipeline"
    assert record["paths"]["last_message"].endswith("last_message.txt")
    prompt = (episode_dir / "prompt.txt").read_text(encoding="utf-8")
    assert "Episode workspace:" in prompt
    assert "artifact_dir:" in prompt
    assert "This is an executable benchmark episode" in prompt
    metrics = json.loads((out_root / "smoke" / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["episodes_scored"] == 1
    episode_metrics = [
        json.loads(line)
        for line in (out_root / "smoke" / "episode_metrics.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert episode_metrics[0]["metric_scope"] == "contract_only"
    assert episode_metrics[0]["canonical_metric_available"] is False
    assert episode_metrics[0]["valid_json"] is True
    assert episode_metrics[0]["required_field_coverage"] == 1.0


def test_contract_response_scores_json_shape_without_canonical_claims() -> None:
    case = {
        "task_shape": "artifact_report",
        "output_contract": {"required_fields": ["answer", "artifacts"]},
        "scoring_axes": [{"axis": "artifact_presence", "canonical_expectation": "Report artifacts."}],
    }

    metrics = score_contract_response(
        case,
        json.dumps(
            {
                "answer": "Created a report.",
                "artifacts": [{"path": "artifacts/report.md"}],
                "evidence_basis": [
                    {
                        "claim": "The report summarizes available inputs.",
                        "basis_type": "specific_citation",
                        "reference": "doi:10.1000/test",
                        "support_span": "fixture",
                        "verifiable": True,
                    }
                ],
            }
        ),
    )

    assert metrics["metric_scope"] == "contract_only"
    assert metrics["canonical_metric_available"] is False
    assert metrics["valid_json"] is True
    assert metrics["required_field_coverage"] == 1.0
    assert metrics["rubric_axis_scores"]["artifact_presence"]["score"] is None
    assert metrics["canonical_convergence_score"] is None


def test_tool_event_counter_counts_unique_mcp_calls(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    event_rows = [
        {
            "type": "item.started",
            "item": {
                "id": "item_0",
                "type": "mcp_tool_call",
                "server": "brain-researcher-prod",
                "tool": "google_file_search",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "mcp_tool_call",
                "server": "brain-researcher-prod",
                "tool": "google_file_search",
            },
        },
    ]
    events_path.write_text("\n".join(json.dumps(row) for row in event_rows) + "\n")

    count, tools = count_tool_events(events_path)

    assert count == 1
    assert tools == ["brain-researcher-prod.google_file_search"]


def test_all_coding_agents_dry_run_uses_condition_file(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    out_root = tmp_path / "runs"
    conditions_path = tmp_path / "agent_conditions.jsonl"
    cases_root.mkdir()
    _write_case_root(cases_root)
    condition_rows = [
        {
            "record_type": "metadata",
            "schema_version": 1,
        },
        {
            "record_type": "condition",
            "condition_id": "codex_cli_gpt55_without_br",
            "runner": "codex_cli",
            "model_target": "gpt-5.5",
            "model_source": "test",
            "execution_mode": "coding_agent",
            "br_mode": "without_br",
        },
        {
            "record_type": "condition",
            "condition_id": "opencode_glm51_with_br",
            "runner": "opencode",
            "model_target": "zai-coding-plan/glm-5.1",
            "model_source": "test",
            "execution_mode": "coding_agent",
            "br_mode": "with_br_mcp",
        },
        {
            "record_type": "condition",
            "condition_id": "opencode_glm51_with_br_required",
            "runner": "opencode",
            "model_target": "zai-coding-plan/glm-5.1",
            "model_source": "test",
            "execution_mode": "coding_agent",
            "br_mode": "with_br_required",
        },
    ]
    conditions_path.write_text(
        "\n".join(json.dumps(row) for row in condition_rows) + "\n",
        encoding="utf-8",
    )

    rc = main(
        [
            "--cases-root",
            str(cases_root),
            "--case",
            "repro_case_test_gsr",
            "--variant",
            "v01",
            "--out-root",
            str(out_root),
            "--run-name",
            "agent-smoke",
            "--agent-conditions-path",
            str(conditions_path),
            "--all-coding-agents",
            "--env-file",
            str(tmp_path / "missing.env"),
            "--dry-run",
        ]
    )

    assert rc == 0
    run_dir = out_root / "agent-smoke"
    episodes = [
        json.loads(line)
        for line in (run_dir / "episodes.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [episode["condition"] for episode in episodes] == [
        "codex_cli_gpt55_without_br",
        "opencode_glm51_with_br",
        "opencode_glm51_with_br_required",
    ]
    prompt = (
        run_dir
        / "cases"
        / "repro_case_test_gsr"
        / "v01__opencode_glm51_with_br"
        / "prompt.txt"
    ).read_text(encoding="utf-8")
    assert "Coding-agent condition:" in prompt
    assert "runner: opencode" in prompt
    assert "Brain Researcher MCP/tools are enabled" in prompt
    assert "Do not call Brain Researcher research logging" in prompt
    required_prompt = (
        run_dir
        / "cases"
        / "repro_case_test_gsr"
        / "v01__opencode_glm51_with_br_required"
        / "prompt.txt"
    ).read_text(encoding="utf-8")
    assert "Brain Researcher MCP/tools are enabled" in required_prompt
    assert "You must make one fast Brain Researcher retrieval call" in required_prompt
    assert "OPENCODE_DISABLE_PROJECT_CONFIG" not in episode_env(condition_rows[2])
    assert "OPENCODE_DISABLE_PROJECT_CONFIG" not in episode_env(condition_rows[3])
    assert (
        episode_env({"runner": "opencode", "br_mode": "without_br"})[
            "OPENCODE_DISABLE_PROJECT_CONFIG"
        ]
        == "1"
    )


def test_extract_last_message_and_error_event_for_opencode_json(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
                json.dumps({"type": "text", "part": {"type": "text", "text": "final answer"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert extract_last_message(events_path) == "final answer"
    assert has_error_event(events_path) is False

    error_path = tmp_path / "error.jsonl"
    error_path.write_text(
        json.dumps({"type": "error", "error": {"message": "provider rejected output"}})
        + "\n",
        encoding="utf-8",
    )
    assert has_error_event(error_path) is True


def test_opencode_mcp_tool_events_count_for_br_retrieval(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "step_start", "part": {"type": "step-start"}}),
                json.dumps(
                    {
                        "type": "tool_use",
                        "part": {
                            "type": "tool",
                            "tool": "brain-researcher-local_google_file_search",
                            "callID": "call_1",
                            "state": {
                                "status": "completed",
                                "input": {
                                    "operation": "query",
                                    "top_k": 3,
                                },
                                "output": (
                                    "Murphy DOI 10.1016/j.neuroimage.2008.09.036 "
                                    "PMID 18976716"
                                ),
                            },
                        },
                    }
                ),
                json.dumps({"type": "text", "part": {"type": "text", "text": "final answer"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    count, tools = count_tool_events(events_path)
    provenance = extract_retrieval_provenance(events_path)

    assert count == 1
    assert tools == ["brain-researcher-local.google_file_search"]
    assert provenance["retrieval_tool_call_count"] == 1
    assert provenance["retrieval_success_count"] == 1
    assert provenance["retrieval_error_count"] == 0
    assert provenance["retrieved_anchor_count"] == 2


def test_run_command_to_files_stops_on_provider_limit(tmp_path: Path) -> None:
    script_path = tmp_path / "provider_limit.py"
    script_path.write_text(
        "import sys, time\n"
        "sys.stderr.write('SubscriptionUsageLimitError: Subscription quota exceeded\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("prompt\n", encoding="utf-8")
    started = time.monotonic()

    returncode, timed_out, early_stop_reason = run_command_to_files(
        command=[sys.executable, str(script_path)],
        prompt_path=prompt_path,
        prompt_on_stdin=False,
        events_path=tmp_path / "events.jsonl",
        stderr_path=tmp_path / "stderr.txt",
        timeout_s=10,
        env=os.environ.copy(),
    )

    assert time.monotonic() - started < 5
    assert returncode is not None
    assert timed_out is False
    assert early_stop_reason == "provider_or_account_limit"


def test_allowed_claude_rate_limit_event_is_not_provider_limit() -> None:
    allowed_event = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed",
                "resetsAt": 1778785800,
                "rateLimitType": "five_hour",
                "overageStatus": "rejected",
                "overageDisabledReason": "org_level_disabled_until",
                "isUsingOverage": False,
            },
        }
    )
    blocked_event = json.dumps(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "blocked", "rateLimitType": "five_hour"},
        }
    )

    assert not _has_provider_or_account_limit(allowed_event)
    assert _has_provider_or_account_limit(blocked_event)


def test_provider_limit_detection_ignores_tool_output_and_assistant_text() -> None:
    tool_event_with_historical_error = json.dumps(
        {
            "type": "tool_use",
            "part": {
                "type": "tool",
                "tool": "bash",
                "state": {
                    "output": (
                        "Historical trace contained CreditsError: insufficient balance "
                        "from an unrelated run."
                    )
                },
            },
        }
    )
    text_event_discussing_billing = json.dumps(
        {
            "type": "text",
            "part": {
                "type": "text",
                "text": "Token and provider billing fields are missing in this audit table.",
            },
        }
    )
    top_level_provider_error = json.dumps(
        {
            "type": "error",
            "error": {
                "name": "APIError",
                "data": {"message": "Insufficient balance. Manage billing."},
            },
        }
    )

    assert not _has_provider_or_account_limit(tool_event_with_historical_error)
    assert not _has_provider_or_account_limit(text_event_discussing_billing)
    assert _has_provider_or_account_limit(top_level_provider_error)


def test_write_run_metrics_classifies_provider_limit_from_events(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    run_dir = tmp_path / "run"
    episode_dir = run_dir / "cases" / "repro_case_test_gsr" / "v01__opencode_kimi"
    cases_root.mkdir()
    episode_dir.mkdir(parents=True)
    _write_case_root(cases_root)
    (episode_dir / "prompt.json").write_text(
        json.dumps({"case_path": str(cases_root / "case_test.json")}) + "\n",
        encoding="utf-8",
    )
    events_path = episode_dir / "events.jsonl"
    stderr_path = episode_dir / "stderr.txt"
    events_path.write_text(
        json.dumps(
            {
                "type": "error",
                "error": {
                    "message": "SubscriptionUsageLimitError: Subscription quota exceeded"
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stderr_path.write_text("", encoding="utf-8")
    row = {
        "case_id": "repro_case_test_gsr",
        "variant_id": "v01",
        "variant_type": "expert",
        "condition": "opencode_kimi",
        "runner": "opencode",
        "model": "opencode/kimi-k2.5",
        "status": "failed_provider_or_account_limit",
        "execute_requested": True,
        "task_shape": "grounded_recommendation",
        "episode_dir": str(episode_dir),
        "wall_time_s": 2.0,
        "tool_call_count": 0,
        "tools_used": [],
        "paths": {"events": str(events_path), "stderr": str(stderr_path)},
    }
    (run_dir / "episodes.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    metrics = write_run_metrics(run_dir, cases_root)

    assert metrics["status_summary"]["availability_counts"] == {
        "provider_or_account_limit": 1
    }


def _response_with_families(families: list[str]) -> dict[str, object]:
    family_refs = {
        "Murphy": {
            "claim": "GSR can alter anti-correlations in resting-state functional connectivity.",
            "basis_type": "specific_citation",
            "reference": "doi:10.1016/j.neuroimage.2008.09.036|pmid:18976716",
            "support_span": "Murphy et al. describe GSR effects on anti-correlations.",
            "verifiable": True,
        },
        "Saad": {
            "claim": "GSR can redistribute correlation structure in case-control analyses.",
            "basis_type": "specific_citation",
            "reference": "doi:10.1016/j.neuroimage.2012.01.052|pmid:22357320",
            "support_span": "Saad et al. evaluate GSR-related correlation changes.",
            "verifiable": True,
        },
        "Power": {
            "claim": "Motion can confound resting-state connectivity estimates.",
            "basis_type": "specific_citation",
            "reference": "doi:10.1016/j.neuroimage.2013.08.048|pmid:23994314",
            "support_span": "Power et al. discuss motion artifacts and scrubbing.",
            "verifiable": True,
        },
    }
    return {
        "answer": (
            "For a clinical case-control rsfMRI FC study, use GSR conditionally as a "
            "prespecified sensitivity analysis, not as the sole default pipeline."
        ),
        "key_points": [
            "Report with and without GSR.",
            "Check motion and physiology differences between patients and controls.",
            "Interpret anti-correlations cautiously.",
        ],
        "risks_or_failure_modes": ["Group-by-motion confounding and anti-correlation artifacts."],
        "recommended_actions": ["Compare CompCor, ICA-AROMA, and scrubbing/censoring alternatives."],
        "evidence_needed": ["Framewise displacement, physiology, and retained frames by group."],
        "evidence_basis": [family_refs[name] for name in families],
        "confidence": "medium",
    }


def test_grounded_recommendation_metrics_score_case_axes(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    cases_root.mkdir()
    _write_case_root(cases_root)
    case = json.loads((cases_root / "case_test.json").read_text(encoding="utf-8"))

    metrics = score_grounded_recommendation_response(
        case,
        json.dumps(_response_with_families(["Murphy", "Saad", "Power"])),
    )

    assert metrics["valid_json"] is True
    assert metrics["required_field_coverage"] == 1.0
    assert metrics["rubric_axis_score"] == 1.0
    assert metrics["required_family_recall"] == 1.0
    assert metrics["required_family_precision"] == 1.0
    assert metrics["required_family_f1"] == 1.0
    assert metrics["decision_field_macro_f1"] is not None
    assert metrics["required_action_f1"] is not None
    assert metrics["canonical_convergence_score"] is not None
    assert metrics["valid_anchor_count"] == 6
    assert metrics["invalid_anchor_count"] == 0
    assert metrics["citation_like_count"] == 6
    assert metrics["invalid_citation_like_count"] == 0
    assert metrics["claim_support_precision"] == 1.0


def test_evidence_family_aliases_accept_confirmed_doi_pmids(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    cases_root.mkdir()
    _write_case_root(cases_root)
    case = json.loads((cases_root / "case_test.json").read_text(encoding="utf-8"))
    case["canonical_task"]["required_evidence_families"] = [
        "Yang 2014",
        "Esteban 2019",
        "Behzadi 2007",
        "Ciric 2017",
        "Parkes 2018",
    ]
    response = _response_with_families([])
    response["evidence_basis"] = [
        {
            "claim": "Yang et al. support treating global signal as clinically meaningful.",
            "basis_type": "specific_citation",
            "reference": "doi:10.1073/pnas.1405289111|pmid:24799682",
            "support_span": "Yang et al. report altered global brain signal in schizophrenia.",
            "verifiable": True,
        },
        {
            "claim": "Esteban et al. define the fMRIPrep preprocessing workflow.",
            "basis_type": "specific_citation",
            "reference": "doi:10.1038/s41592-018-0235-4|pmid:30532080",
            "support_span": "fMRIPrep is a robust preprocessing pipeline for functional MRI.",
            "verifiable": True,
        },
        {
            "claim": "Behzadi et al. define aCompCor.",
            "basis_type": "specific_citation",
            "reference": "doi:10.1016/j.neuroimage.2007.04.042|pmid:17560126",
            "support_span": "CompCor is a component-based noise correction method.",
            "verifiable": True,
        },
        {
            "claim": "Ciric et al. benchmark confound regression strategies.",
            "basis_type": "specific_citation",
            "reference": "doi:10.1016/j.neuroimage.2017.03.020|pmid:28302591",
            "support_span": "Benchmarking participant-level confound regression strategies.",
            "verifiable": True,
        },
        {
            "claim": "Parkes et al. evaluate motion correction strategies.",
            "basis_type": "specific_citation",
            "reference": "doi:10.1016/j.neuroimage.2017.12.073|pmid:29278773",
            "support_span": "Evaluation of motion correction strategy efficacy and reliability.",
            "verifiable": True,
        },
    ]

    metrics = score_grounded_recommendation_response(case, json.dumps(response))

    assert metrics["required_family_recall"] == 1.0
    assert set(metrics["required_family_hits"]) == set(case["canonical_task"]["required_evidence_families"])


def test_bilingual_caveat_and_retrieval_provenance_are_scored(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    cases_root.mkdir()
    _write_case_root(cases_root)
    case = json.loads((cases_root / "case_test.json").read_text(encoding="utf-8"))
    response = _response_with_families(["Murphy", "Saad"])
    response["answer"] = (
        "建议不要把 GSR 作为唯一默认步骤；应报告 使用 GSR 和 不使用 GSR 的敏感性分析，"
        "并检查病例对照 resting-state functional connectivity 的 motion 和 physiology 差异。"
    )
    response["retrieved_evidence_used"] = [
        {
            "retrieved_family": "Murphy 2009",
            "anchor": "doi:10.1016/j.neuroimage.2008.09.036",
            "final_claim": "GSR can alter anti-correlations in resting-state FC.",
            "used_in_evidence_basis": True,
            "omitted_reason": "",
        },
        {
            "retrieved_family": "Saad 2012",
            "anchor": "pmid:22357320",
            "final_claim": "GSR can redistribute correlation structure.",
            "used_in_evidence_basis": True,
            "omitted_reason": "",
        },
    ]
    response["diagnostic_family_mapping"] = [
        {
            "evidence_family": "Murphy 2009",
            "retrieved": True,
            "used_in_evidence_basis": True,
            "anchor": "doi:10.1016/j.neuroimage.2008.09.036",
            "evidence_basis_index": 0,
            "omitted_reason": "",
        },
        {
            "evidence_family": "Saad 2012",
            "retrieved": True,
            "used_in_evidence_basis": True,
            "anchor": "pmid:22357320",
            "evidence_basis_index": 1,
            "omitted_reason": "",
        },
    ]
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {
                            "id": "item_0",
                            "type": "mcp_tool_call",
                            "server": "brain-researcher-prod",
                            "tool": "google_file_search",
                            "arguments": {"operation": "query"},
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_0",
                            "type": "mcp_tool_call",
                            "server": "brain-researcher-prod",
                            "tool": "google_file_search",
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Murphy DOI 10.1016/j.neuroimage.2008.09.036 PMID 18976716; Saad DOI 10.1016/j.neuroimage.2012.01.052 PMID 22357320",
                                    }
                                ],
                                "structured_content": {"ok": True, "result": {"status": "success"}},
                            },
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    provenance = extract_retrieval_provenance(events_path)
    metrics = score_grounded_recommendation_response(case, json.dumps(response), provenance)

    assert provenance["retrieval_success_count"] == 1
    assert provenance["retrieval_error_count"] == 0
    assert provenance["retrieved_anchor_count"] == 4
    assert metrics["rubric_axis_scores"]["caveat_presence"]["score"] == 1
    assert metrics["retrieved_required_family_recall"] == 2 / 3
    assert metrics["retrieved_to_final_required_family_utilization"] == 1.0
    assert metrics["retrieved_evidence_used_count"] == 2
    assert metrics["retrieved_evidence_used_required_family_recall"] == 2 / 3
    assert metrics["retrieved_evidence_used_anchor_from_retrieval_rate"] == 1.0
    assert metrics["diagnostic_family_mapping_count"] == 2
    assert metrics["diagnostic_family_mapping_required_family_recall"] == 2 / 3
    assert metrics["diagnostic_family_mapping_anchor_from_retrieval_rate"] == 1.0
    assert metrics["final_anchor_from_retrieval_rate"] == 1.0
    assert metrics["retrieved_anchor_utilization_rate"] == 1.0


def test_write_run_metrics_materializes_aggregate_and_pairwise_delta(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    run_dir = tmp_path / "runs" / "metric-smoke"
    case_dir = run_dir / "cases" / "repro_case_test_gsr"
    cases_root.mkdir()
    _write_case_root(cases_root)
    rows = []
    for condition, families, tool_count in [
        ("codex_cli_gpt55_without_br", ["Murphy", "Power"], 0),
        ("codex_cli_gpt55_with_br", ["Murphy", "Saad", "Power"], 1),
    ]:
        episode_dir = case_dir / f"v01__{condition}"
        episode_dir.mkdir(parents=True)
        output_path = episode_dir / "last_message.txt"
        output_path.write_text(json.dumps(_response_with_families(families)) + "\n", encoding="utf-8")
        (episode_dir / "prompt.txt").write_text(
            "User prompt variant:\nGSR yes/no?\n\nCanonical task description:\nRecommend GSR.\n",
            encoding="utf-8",
        )
        (episode_dir / "prompt.json").write_text(
            json.dumps({"case_path": str(cases_root / "case_test.json")}) + "\n",
            encoding="utf-8",
        )
        rows.append(
            {
                "case_id": "repro_case_test_gsr",
                "variant_id": "v01",
                "variant_type": "expert",
                "condition": condition,
                "runner": "codex_cli",
                "model": "gpt-5.5",
                "status": "succeeded",
                "task_shape": "grounded_recommendation",
                "episode_dir": str(episode_dir),
                "wall_time_s": 10.0 + tool_count,
                "tool_call_count": tool_count,
                "tools_used": ["brain-researcher-prod.google_file_search"] if tool_count else [],
                "paths": {"last_message": str(output_path)},
            }
        )
    (run_dir / "episodes.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"episodes": 2, "status_counts": {"succeeded": 2}}) + "\n",
        encoding="utf-8",
    )

    metrics = write_run_metrics(run_dir, cases_root)

    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "episode_metrics.jsonl").exists()
    assert metrics["evidence_policy"] == "single_run_attempts"
    assert metrics["episodes_scored"] == 2
    without = metrics["by_condition"]["codex_cli_gpt55_without_br"]
    with_br = metrics["by_condition"]["codex_cli_gpt55_with_br"]
    assert without["mean_required_family_recall"] == 2 / 3
    assert with_br["mean_required_family_recall"] == 1.0
    assert without["br_condition"] == "without_br"
    assert with_br["br_condition"] == "with_br"
    assert with_br["br_tool_called_scored"] == 1
    assert with_br["br_tool_call_count_scored"] == 1
    comparison = metrics["condition_comparisons"][0]
    assert comparison["paired_scored_count"] == 1
    assert abs(comparison["required_family_recall_delta"] - (1 / 3)) < 1e-12
    assert comparison["br_tool_call_overhead"] == 1.0
    assert comparison["tool_efficiency"]["grounding_quality_delta_per_tool_call"] > 0
    report_tables = metrics["report_tables"]
    for key in [
        "episode_results",
        "availability_by_condition",
        "quality_by_condition",
        "paired_br_delta",
        "prompt_stability_by_case_condition",
        "br_loss_diagnostics",
        "variant_robustness",
        "error_taxonomy",
    ]:
        assert Path(report_tables[key]).exists()
    episode_rows = list(csv.DictReader(Path(report_tables["episode_results"]).open(encoding="utf-8")))
    assert len(episode_rows) == 2
    assert episode_rows[0]["input"] == "GSR yes/no?"
    assert {
        "input",
        "prompt",
        "output",
        "br_tool_called",
        "br_condition",
        "canonical_convergence_score",
        "required_action_f1",
        "required_family_f1",
        "retrieved_evidence_used_required_family_recall",
        "diagnostic_family_mapping_required_family_recall",
        "canonical_validation_tier",
    } <= set(episode_rows[0])
    quality_rows = list(csv.DictReader(Path(report_tables["quality_by_condition"]).open(encoding="utf-8")))
    quality_by_condition = {row["condition"]: row for row in quality_rows}
    assert quality_by_condition["codex_cli_gpt55_with_br"]["denominator"] == "scored_valid_json_succeeded_rows"
    assert quality_by_condition["codex_cli_gpt55_with_br"]["br_tool_call_count_scored"] == "1"
    assert "mean_retrieved_evidence_used_required_family_recall" in quality_by_condition[
        "codex_cli_gpt55_with_br"
    ]
    assert "mean_diagnostic_family_mapping_required_family_recall" in quality_by_condition[
        "codex_cli_gpt55_with_br"
    ]
    availability_rows = list(csv.DictReader(Path(report_tables["availability_by_condition"]).open(encoding="utf-8")))
    assert availability_rows[0]["denominator"] == "attempted_rows"
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["episodes_scored"] == 2
    assert summary["metrics"]["evidence_policy"] == "single_run_attempts"
    assert summary["metrics"]["status_summary"]["attempted"] == 2
    assert summary["metrics"]["status_summary"]["benchmark_grade_claim_eligible"] is False
    assert summary["metrics"]["metrics_json"].endswith("metrics.json")
    assert summary["metrics"]["report_tables"]["episode_results"].endswith("episode_results.csv")
    assert (run_dir / "METRICS_REPORT.md").exists()


def test_write_run_metrics_pairs_without_br_with_required_br(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    run_dir = tmp_path / "runs" / "required-br-pair"
    case_dir = run_dir / "cases" / "repro_case_test_gsr"
    cases_root.mkdir()
    _write_case_root(cases_root)
    rows = []
    for condition, families, tool_count in [
        ("opencode_glm51_without_br", ["Murphy", "Power"], 0),
        ("opencode_glm51_with_br_required", ["Murphy", "Saad", "Power"], 1),
    ]:
        episode_dir = case_dir / f"v01__{condition}"
        episode_dir.mkdir(parents=True)
        output_path = episode_dir / "last_message.txt"
        output_path.write_text(json.dumps(_response_with_families(families)) + "\n", encoding="utf-8")
        (episode_dir / "prompt.txt").write_text(
            "User prompt variant:\nGSR yes/no?\n\nCanonical task description:\nRecommend GSR.\n",
            encoding="utf-8",
        )
        (episode_dir / "prompt.json").write_text(
            json.dumps({"case_path": str(cases_root / "case_test.json")}) + "\n",
            encoding="utf-8",
        )
        rows.append(
            {
                "case_id": "repro_case_test_gsr",
                "variant_id": "v01",
                "variant_type": "expert",
                "condition": condition,
                "runner": "opencode",
                "model": "glm-5.1",
                "br_mode": "with_br_required" if tool_count else "without_br",
                "status": "succeeded",
                "task_shape": "grounded_recommendation",
                "episode_dir": str(episode_dir),
                "wall_time_s": 10.0 + tool_count,
                "tool_call_count": tool_count,
                "tools_used": ["brain-researcher-local.google_file_search"] if tool_count else [],
                "paths": {"last_message": str(output_path)},
            }
        )
    (run_dir / "episodes.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"episodes": 2, "status_counts": {"succeeded": 2}}) + "\n",
        encoding="utf-8",
    )

    metrics = write_run_metrics(run_dir, cases_root)

    comparison = metrics["condition_comparisons"][0]
    assert comparison["baseline_condition"] == "opencode_glm51_without_br"
    assert comparison["treatment_condition"] == "opencode_glm51_with_br_required"
    assert comparison["paired_scored_count"] == 1
    assert comparison["treatment_br_tool_called_rate_scored"] == 1.0
    paired_rows = list(csv.DictReader(Path(metrics["report_tables"]["paired_br_delta"]).open(encoding="utf-8")))
    assert len(paired_rows) == 1
    assert paired_rows[0]["treatment_condition"] == "opencode_glm51_with_br_required"


def test_write_run_metrics_classifies_br_loss_rows(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    run_dir = tmp_path / "runs" / "br-loss"
    case_dir = run_dir / "cases" / "repro_case_test_gsr"
    cases_root.mkdir()
    _write_case_root(cases_root)
    rows = []
    for condition, families, tool_count in [
        ("opencode_glm51_without_br", ["Murphy", "Saad", "Power"], 0),
        ("opencode_glm51_with_br_required", ["Murphy"], 1),
    ]:
        episode_dir = case_dir / f"v01__{condition}"
        episode_dir.mkdir(parents=True)
        output_path = episode_dir / "last_message.txt"
        output_path.write_text(json.dumps(_response_with_families(families)) + "\n", encoding="utf-8")
        (episode_dir / "prompt.txt").write_text(
            "User prompt variant:\nGSR yes/no?\n\nCanonical task description:\nRecommend GSR.\n",
            encoding="utf-8",
        )
        (episode_dir / "prompt.json").write_text(
            json.dumps({"case_path": str(cases_root / "case_test.json")}) + "\n",
            encoding="utf-8",
        )
        rows.append(
            {
                "case_id": "repro_case_test_gsr",
                "variant_id": "v01",
                "variant_type": "expert",
                "condition": condition,
                "runner": "opencode",
                "model": "glm-5.1",
                "br_mode": "with_br_required" if tool_count else "without_br",
                "status": "succeeded",
                "task_shape": "grounded_recommendation",
                "episode_dir": str(episode_dir),
                "wall_time_s": 10.0 + tool_count,
                "tool_call_count": tool_count,
                "tools_used": ["brain-researcher-local.google_file_search"] if tool_count else [],
                "paths": {"last_message": str(output_path)},
            }
        )
    (run_dir / "episodes.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps({"episodes": 2, "status_counts": {"succeeded": 2}}) + "\n",
        encoding="utf-8",
    )

    metrics = write_run_metrics(run_dir, cases_root)

    diagnostic_rows = list(
        csv.DictReader(Path(metrics["report_tables"]["br_loss_diagnostics"]).open(encoding="utf-8"))
    )
    assert len(diagnostic_rows) == 1
    assert diagnostic_rows[0]["classification"] == "retrieval_missed_canonical_anchors"
    assert diagnostic_rows[0]["primary_mechanism"] == "retrieval_miss"
    assert float(diagnostic_rows[0]["canonical_convergence_delta"]) < 0


def test_write_run_metrics_separates_availability_from_quality(tmp_path: Path) -> None:
    cases_root = tmp_path / "cases"
    run_dir = tmp_path / "runs" / "metric-smoke"
    case_dir = run_dir / "cases" / "repro_case_test_gsr"
    cases_root.mkdir()
    _write_case_root(cases_root)
    rows = []

    def add_row(
        *,
        condition: str,
        variant_id: str,
        status: str,
        response: dict[str, object] | str | None,
        tool_count: int = 0,
    ) -> None:
        episode_dir = case_dir / f"{variant_id}__{condition}"
        episode_dir.mkdir(parents=True)
        output_path = episode_dir / "last_message.txt"
        if response is not None:
            output_path.write_text(
                (json.dumps(response) if isinstance(response, dict) else response) + "\n",
                encoding="utf-8",
            )
        (episode_dir / "prompt.json").write_text(
            json.dumps({"case_path": str(cases_root / "case_test.json")}) + "\n",
            encoding="utf-8",
        )
        (episode_dir / "stderr.txt").write_text(
            "out of extra usage\n" if status == "failed" else "",
            encoding="utf-8",
        )
        paths = {"stderr": str(episode_dir / "stderr.txt")}
        if response is not None:
            paths["last_message"] = str(output_path)
        rows.append(
            {
                "case_id": "repro_case_test_gsr",
                "variant_id": variant_id,
                "variant_type": "expert",
                "condition": condition,
                "runner": "codex_cli",
                "model": "gpt-5.5",
                "status": status,
                "execute_requested": status != "materialized",
                "task_shape": "grounded_recommendation",
                "episode_dir": str(episode_dir),
                "wall_time_s": 10.0,
                "tool_call_count": tool_count,
                "tools_used": ["brain-researcher-prod.google_file_search"] if tool_count else [],
                "paths": paths,
            }
        )

    add_row(
        condition="codex_cli_gpt55_without_br",
        variant_id="v01",
        status="succeeded",
        response=_response_with_families(["Murphy", "Power"]),
    )
    add_row(
        condition="codex_cli_gpt55_with_br",
        variant_id="v01",
        status="succeeded",
        response=_response_with_families(["Murphy", "Saad", "Power"]),
        tool_count=1,
    )
    add_row(
        condition="codex_cli_gpt55_without_br",
        variant_id="v02",
        status="timed_out",
        response=None,
    )
    add_row(
        condition="codex_cli_gpt55_with_br",
        variant_id="v02",
        status="succeeded",
        response="not json",
        tool_count=1,
    )
    add_row(
        condition="codex_cli_gpt55_without_br",
        variant_id="v03",
        status="materialized",
        response=None,
    )
    add_row(
        condition="codex_cli_gpt55_with_br",
        variant_id="v03",
        status="failed",
        response=None,
    )
    (run_dir / "episodes.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    metrics = write_run_metrics(run_dir, cases_root)

    status = metrics["status_summary"]
    assert status["total_episodes"] == 6
    assert status["attempted"] == 5
    assert status["succeeded"] == 3
    assert status["scored"] == 2
    assert status["valid_json"] == 2
    assert status["timed_out"] == 1
    assert status["failed"] == 1
    assert status["materialized"] == 1
    assert status["availability_counts"]["provider_or_account_limit"] == 1
    assert status["availability_denominator"] == "attempted_rows"
    assert status["quality_denominator"] == "scored_valid_json_succeeded_rows"

    without = metrics["by_condition"]["codex_cli_gpt55_without_br"]
    with_br = metrics["by_condition"]["codex_cli_gpt55_with_br"]
    assert without["total_episodes"] == 3
    assert without["attempted"] == 2
    assert without["scored"] == 1
    assert without["materialized"] == 1
    assert without["mean_required_family_recall"] == 2 / 3
    assert with_br["total_episodes"] == 3
    assert with_br["attempted"] == 3
    assert with_br["succeeded"] == 2
    assert with_br["valid_json"] == 1
    assert with_br["scored"] == 1
    assert with_br["valid_json_rate_succeeded"] == 0.5

    comparison = metrics["condition_comparisons"][0]
    assert comparison["available_pair_count"] == 3
    assert comparison["paired_scored_count"] == 1
    assert comparison["unscored_or_unavailable_pair_count"] == 2
    assert abs(comparison["required_family_recall_delta"] - (1 / 3)) < 1e-12
