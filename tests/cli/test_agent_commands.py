"""
Tests for agent CLI commands (br agent).

Tests cover:
- br agent run: Job execution with planner
- br agent plan: Plan preview
- Parameter parsing
- Error handling
"""

from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from brain_researcher.cli.commands.agent_commands import app, parse_key_value_pairs
from brain_researcher.services.agent.autoresearch import (
    FailureMotifCard,
    FixCandidate,
    ValidationReport,
)
from brain_researcher.services.agent.harness_scaffolding import (
    HarnessScaffoldResult,
)

runner = CliRunner()


# ============================================================================
# Unit Tests for Helpers
# ============================================================================


class TestParseKeyValuePairs:
    """Test parameter parsing"""

    def test_single_param(self):
        result = parse_key_value_pairs(["infile=/data/brain.nii.gz"])
        assert result == {"infile": "/data/brain.nii.gz"}

    def test_multiple_params(self):
        result = parse_key_value_pairs(
            ["infile=/data/brain.nii.gz", "threshold=0.5", "verbose=true"]
        )
        assert result == {
            "infile": "/data/brain.nii.gz",
            "threshold": "0.5",
            "verbose": "true",
        }

    def test_param_with_equals_in_value(self):
        result = parse_key_value_pairs(["url=http://example.com?foo=bar"])
        assert result == {"url": "http://example.com?foo=bar"}

    def test_invalid_param_skipped(self):
        result = parse_key_value_pairs(["valid=123", "invalid_no_equals", "also=valid"])
        assert result == {"valid": "123", "also": "valid"}

    def test_empty_list(self):
        result = parse_key_value_pairs([])
        assert result == {}


# ============================================================================
# Integration Tests for Commands
# ============================================================================


class TestAgentRun:
    """Test br agent run command"""

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_basic_run_no_wait(self, mock_post):
        """Test basic run without waiting"""
        mock_post.return_value = {"job_id": "run_abc123"}

        result = runner.invoke(app, ["run", "skull strip", "--no-wait"])

        assert result.exit_code == 0
        assert "run_abc123" in result.stdout
        mock_post.assert_called_once()

        # Check payload
        call_args = mock_post.call_args
        assert call_args[0][0] == "/run"
        payload = call_args[1]["json_data"]
        assert payload["prompt"] == "skull strip"
        assert payload["parameters"] == {}

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_run_with_params(self, mock_post):
        """Test run with multiple parameters"""
        mock_post.return_value = {"job_id": "run_xyz789"}

        result = runner.invoke(
            app,
            [
                "run",
                "skull strip",
                "--param",
                "infile=/data/T1.nii.gz",
                "--param",
                "threshold=0.5",
                "--no-wait",
            ],
        )

        assert result.exit_code == 0

        # Check parameters were parsed
        call_args = mock_post.call_args
        payload = call_args[1]["json_data"]
        assert payload["parameters"] == {
            "infile": "/data/T1.nii.gz",
            "threshold": "0.5",
        }

    @patch("brain_researcher.cli.commands.agent_commands.api_get_sync")
    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_run_with_wait(self, mock_post, mock_get):
        """Test run with --wait flag"""
        mock_post.return_value = {"job_id": "run_wait123"}
        mock_get.return_value = {"job_id": "run_wait123", "state": "succeeded"}

        result = runner.invoke(app, ["run", "skull strip", "--wait"])

        assert result.exit_code == 0
        assert (
            "succeeded" in result.stdout.lower() or "completed" in result.stdout.lower()
        )

        # Should have polled at least once
        mock_get.assert_called()

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_run_with_tool_override(self, mock_post):
        """Test forcing specific tool"""
        mock_post.return_value = {"job_id": "run_tool123"}

        result = runner.invoke(
            app, ["run", "skull strip", "--tool", "fsl_bet", "--no-wait"]
        )

        assert result.exit_code == 0

        # Check tool was included in payload
        call_args = mock_post.call_args
        payload = call_args[1]["json_data"]
        assert payload["tool"] == "fsl_bet"

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_run_advisor_mode_confirmed(self, mock_post):
        """Test advisor mode with user confirmation"""
        # First call for plan preview, second for execution
        mock_post.side_effect = [
            {
                "intent": "skull strip",
                "candidates": [
                    {
                        "tool_id": "fsl_bet",
                        "tool_name": "bet",
                        "score": 0.85,
                        "preflight_ok": True,
                        "reason": "OK",
                    }
                ],
                "chosen": {"tool_id": "fsl_bet", "tool_name": "bet", "score": 0.85},
            },
            {"job_id": "run_advisor123"},
        ]

        result = runner.invoke(
            app,
            ["run", "skull strip", "--planner-mode", "advisor", "--no-wait"],
            input="y\n",
        )  # Confirm execution

        assert result.exit_code == 0
        assert "run_advisor123" in result.stdout

        # Should have called POST twice (plan + run)
        assert mock_post.call_count == 2

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_run_advisor_mode_declined(self, mock_post):
        """Test advisor mode with user declining"""
        mock_post.return_value = {
            "intent": "skull strip",
            "candidates": [],
            "chosen": None,
        }

        result = runner.invoke(
            app,
            ["run", "skull strip", "--planner-mode", "advisor", "--no-wait"],
            input="n\n",
        )  # Decline execution

        assert result.exit_code == 0
        assert "cancelled" in result.stdout.lower()

        # Should have called POST only once (plan, no execution)
        assert mock_post.call_count == 1

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_run_connection_error(self, mock_post):
        """Test error handling for connection errors"""
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection failed")

        result = runner.invoke(app, ["run", "skull strip", "--no-wait"])

        assert result.exit_code == 1


class TestAgentPlan:
    """Test br agent plan command"""

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_basic_plan(self, mock_post):
        """Test basic plan preview"""
        mock_post.return_value = {
            "intent": "skull strip",
            "candidates": [
                {
                    "tool_id": "fsl_bet",
                    "tool_name": "bet",
                    "score": 0.85,
                    "preflight_ok": True,
                    "reason": "All checks passed",
                },
                {
                    "tool_id": "afni.3dSkullStrip",
                    "tool_name": "3dSkullStrip",
                    "score": 0.79,
                    "preflight_ok": False,
                    "reason": "Image not found",
                },
            ],
            "chosen": {"tool_id": "fsl_bet", "tool_name": "bet", "score": 0.85},
            "plan_id": "plan_abc123",
        }

        result = runner.invoke(app, ["plan", "skull strip"])

        assert result.exit_code == 0
        assert "skull strip" in result.stdout
        assert "fsl_bet" in result.stdout
        assert "plan_abc123" in result.stdout

        # Check API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "/api/agent/plan"
        payload = call_args[1]["json_data"]
        assert payload["intent"] == "skull strip"

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_plan_with_params(self, mock_post):
        """Test plan with constraints"""
        mock_post.return_value = {
            "intent": "segment tissue",
            "candidates": [],
            "chosen": None,
        }

        result = runner.invoke(
            app,
            [
                "plan",
                "segment tissue",
                "--param",
                "infile=/data/T1.nii.gz",
                "--param",
                "classes=3",
            ],
        )

        assert result.exit_code == 0

        # Check constraints were passed
        call_args = mock_post.call_args
        payload = call_args[1]["json_data"]
        assert payload["constraints"] == {"infile": "/data/T1.nii.gz", "classes": "3"}

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_plan_error_handling(self, mock_post):
        """Test error handling in plan command"""
        import httpx

        mock_post.side_effect = httpx.HTTPStatusError(
            "501 Not Implemented",
            request=Mock(),
            response=Mock(status_code=501, json=lambda: {"detail": "Planner disabled"}),
        )

        result = runner.invoke(app, ["plan", "skull strip"])

        assert result.exit_code == 1


class TestAutoresearchCommands:
    """Test failure-mining autoresearch commands."""

    @patch("brain_researcher.cli.commands.agent_commands.mine_failure_motifs")
    def test_mine_failure_motifs_table(self, mock_mine):
        mock_mine.return_value = [
            FailureMotifCard(
                motif_id="tool_param_fill_failure",
                motif_family="tool_param_fill_failure",
                severity="high",
                frequency=4,
                affected_tools_workflows=["workflow_seed_based_connectivity"],
                representative_runs=["run_a", "run_b"],
                evidence_snippets=["Missing required params"],
                suspected_surface="tool_schema_and_param_fill",
                suggested_fix_surfaces=["tool_schema_and_param_fill"],
                recommended_benchmark_slice_id="tool_param_fill_failure",
                source_corpus_summary={"total_runs": 10},
            )
        ]

        result = runner.invoke(app, ["mine-failure-motifs"])

        assert result.exit_code == 0
        assert "Failure Motifs" in result.stdout
        assert "run_a" in result.stdout
        mock_mine.assert_called_once()

    @patch("brain_researcher.cli.commands.agent_commands.propose_fix_candidates")
    def test_propose_fix_candidates_json(self, mock_propose):
        mock_propose.return_value = [
            FixCandidate(
                candidate_id="cand_001",
                motif_id="tool_param_fill_failure",
                motif_family="tool_param_fill_failure",
                target_surface="tool_schema_and_param_fill",
                allowed_paths=["src/brain_researcher/services/mcp/server.py"],
                worktree_path="/tmp/cand_001",
                patch_rationale="Improve required-param validation",
                validation_slice_id="tool_param_fill_failure",
                local_check_commands=[
                    "pytest -q tests/unit/mcp/test_local_mcp_server.py"
                ],
                created_at="2026-03-10T10:00:00+00:00",
            )
        ]

        result = runner.invoke(
            app,
            ["propose-fix-candidates", "tool_param_fill_failure", "--format", "json"],
        )

        assert result.exit_code == 0
        assert '"candidate_id": "cand_001"' in result.stdout
        mock_propose.assert_called_once_with(
            "tool_param_fill_failure",
            max_candidates=3,
        )

    @patch("brain_researcher.cli.commands.agent_commands.validate_fix_candidate")
    def test_validate_fix_candidate_table(self, mock_validate):
        mock_validate.return_value = ValidationReport(
            candidate_id="cand_001",
            motif_id="tool_param_fill_failure",
            motif_family="tool_param_fill_failure",
            baseline_summary={
                "motif_slice": {
                    "success_rate": 0.5,
                    "blocker_count": 1,
                    "motif_blocker_count": 1,
                },
                "canary_slice": {
                    "success_rate": 1.0,
                    "blocker_count": 0,
                },
            },
            candidate_summary={
                "motif_slice": {
                    "success_rate": 1.0,
                    "blocker_count": 0,
                    "motif_blocker_count": 0,
                },
                "canary_slice": {
                    "success_rate": 1.0,
                    "blocker_count": 0,
                },
            },
            gate_verdict="passed",
            larger_benchmark_eligible=True,
            fixed_failures=["TASK-001"],
            patch_legibility={
                "score": 88.0,
                "band": "high",
                "files_touched": 1,
                "lines_added": 18,
                "lines_deleted": 4,
                "outside_allowlist_count": 0,
                "findings": [],
            },
            status_explanation="The candidate cleared the fail-fast gate.",
            recommended_action="Queue this candidate for the next larger benchmark tier.",
        )

        result = runner.invoke(app, ["validate-fix-candidate", "cand_001"])

        assert result.exit_code == 0
        assert "cand_001" in result.stdout
        assert "passed" in result.stdout
        assert "Patch Legibility:" in result.stdout
        assert "Status Summary:" in result.stdout
        assert "Recommended Action:" in result.stdout
        mock_validate.assert_called_once_with(
            "cand_001",
            loop_profile_id="external_coding_v1",
            timeout_s=600,
        )

    @patch("brain_researcher.cli.commands.agent_commands.generate_repo_repair_context")
    def test_repo_repair_context_table(self, mock_context):
        mock_context.return_value = {
            "ok": True,
            "repo_repair_context": {
                "generated_at": "2026-03-12T10:00:00Z",
                "summary": {
                    "failure_motif_count": 3,
                    "absorbed_upstream_candidate_count": 1,
                    "harness_task_count": 2,
                    "golden_principle_count": 4,
                },
                "recent_failure_motifs": [
                    {
                        "motif_family": "trace_or_bundle_corruption",
                        "frequency": 7,
                        "suspected_surface": "trace_bundle_integrity",
                    }
                ],
                "absorbed_upstream_candidates": [
                    {
                        "candidate_id": "cand_trace_001",
                        "motif_family": "trace_or_bundle_corruption",
                        "target_surface": "trace_bundle_integrity",
                        "patch_legibility_band": "high",
                    }
                ],
                "harness_coverage": {
                    "all_harness_tasks": ["HARNESS-001", "HARNESS-002"],
                    "motifs_without_native_harness": [
                        "workflow_discoverability_mismatch"
                    ],
                },
                "golden_principles": [
                    {"id": "terminal_run_invariant", "title": "Terminal Run Invariant"}
                ],
                "hot_surfaces": [{"surface": "trace_bundle_integrity", "weight": 8}],
            },
            "persisted_files": ["/tmp/repo_repair_context_latest.json"],
            "warnings": [],
        }

        result = runner.invoke(app, ["repo-repair-context"])

        assert result.exit_code == 0
        assert "Repo Repair Context" in result.stdout
        assert "trace_bundle_integrity" in result.stdout
        assert "HARNESS-001" in result.stdout
        mock_context.assert_called_once_with(top_n=8, persist=True)

    @patch("brain_researcher.cli.commands.agent_commands.scaffold_harness_task")
    def test_scaffold_harness_task_table(self, mock_scaffold):
        mock_scaffold.return_value = HarnessScaffoldResult(
            task_id="HARNESS-099",
            motif_family="wrong_tool_or_workflow_routing",
            title="TODO: Define wrong tool or workflow routing invariant",
            profile="harness_wrong_tool_or_workflow_routing_scaffold_v0",
            benchmark_root="/tmp/benchmark",
            task_root="/tmp/benchmark/harbor/HARNESS-099",
            activation_mode="draft",
            created_paths=["/tmp/benchmark/harbor/HARNESS-099/task.toml"],
            updated_paths=["/tmp/benchmark/configs/autoresearch/motif_slices.yaml"],
            warnings=["Scaffold was registered in draft fields only."],
        )

        result = runner.invoke(
            app,
            ["scaffold-harness-task", "wrong_tool_or_workflow_routing"],
        )

        assert result.exit_code == 0
        assert "HARNESS-099" in result.stdout
        assert "draft" in result.stdout
        mock_scaffold.assert_called_once_with(
            "wrong_tool_or_workflow_routing",
            task_id=None,
            title=None,
            activate=False,
        )


class TestAgentHypothesis:
    """Test br agent hypothesis command"""

    @patch("brain_researcher.cli.commands.agent_commands.api_get_sync")
    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_hypothesis_wait_table(self, mock_post, mock_get):
        mock_post.return_value = {"job_id": "run_hyp001"}
        mock_get.return_value = {
            "job_id": "run_hyp001",
            "state": "succeeded",
            "result": {
                "workflow": "workflow_hypothesis_candidate_cards",
                "steps": {
                    "leverage": {
                        "status": "success",
                        "data": {
                            "resolved_seed_kg_ids": ["node:seed"],
                            "result": {
                                "items": [
                                    {
                                        "kg_id": "node:candidate1",
                                        "label": "Candidate Node 1",
                                        "leverage_score": 0.8,
                                    }
                                ]
                            },
                        },
                    },
                    "ood_sampling": {
                        "status": "success",
                        "data": {
                            "result": {
                                "hypotheses": [
                                    {
                                        "seed_kg_id": "node:seed",
                                        "candidate_kg_id": "node:candidate1",
                                        "statement": "Seed may couple with candidate 1.",
                                        "relation_hint": "ASSOCIATED_WITH",
                                        "novelty_score": 0.7,
                                        "ood_score": 0.75,
                                    }
                                ]
                            }
                        },
                    },
                },
            },
        }

        result = runner.invoke(
            app,
            ["hypothesis", "fmri based image decoding", "--wait", "--format", "json"],
        )
        assert result.exit_code == 0
        assert "candidate_cards" in result.stdout
        assert "Seed may couple with candidate 1." in result.stdout

    @patch("brain_researcher.cli.commands.agent_commands.api_get_sync")
    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_hypothesis_no_wait(self, mock_post, mock_get):
        mock_post.return_value = {"job_id": "run_hyp_nowait"}

        result = runner.invoke(
            app,
            ["hypothesis", "fmri based image decoding", "--no-wait"],
        )

        assert result.exit_code == 0
        assert "run_hyp_nowait" in result.stdout
        mock_get.assert_not_called()
        payload = mock_post.call_args[1]["json_data"]
        assert payload["parameters"]["controller_mode"] == "legacy"

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_hypothesis_controller_mode_passthrough(self, mock_post):
        mock_post.return_value = {"job_id": "run_hyp_principle"}

        result = runner.invoke(
            app,
            [
                "hypothesis",
                "fmri based image decoding",
                "--controller-mode",
                "principle_v0",
                "--no-wait",
            ],
        )

        assert result.exit_code == 0
        payload = mock_post.call_args[1]["json_data"]
        assert payload["parameters"]["controller_mode"] == "principle_v0"

    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_hypothesis_candidate_lane_mode_passthrough(self, mock_post):
        mock_post.return_value = {"job_id": "run_hyp_strict"}

        result = runner.invoke(
            app,
            [
                "hypothesis",
                "fmri based image decoding",
                "--candidate-lane-mode",
                "strict",
                "--no-wait",
            ],
        )

        assert result.exit_code == 0
        payload = mock_post.call_args[1]["json_data"]
        assert payload["parameters"]["candidate_lane_mode"] == "strict"

    @patch("brain_researcher.cli.commands.agent_commands.api_get_sync")
    @patch("brain_researcher.cli.commands.agent_commands.api_post_sync")
    def test_hypothesis_with_research_json(self, mock_post, mock_get):
        mock_post.side_effect = [
            {"job_id": "run_hyp_research"},
            {"job_id": "run_deep_research"},
        ]
        mock_get.side_effect = [
            {
                "job_id": "run_hyp_research",
                "state": "succeeded",
                "result": {
                    "workflow": "workflow_hypothesis_candidate_cards",
                    "steps": {
                        "leverage": {
                            "status": "success",
                            "data": {
                                "resolved_seed_kg_ids": ["node:seed"],
                                "result": {
                                    "items": [
                                        {
                                            "kg_id": "node:candidate1",
                                            "label": "Candidate Node 1",
                                            "leverage_score": 0.8,
                                        }
                                    ]
                                },
                            },
                        },
                        "ood_sampling": {
                            "status": "success",
                            "data": {
                                "result": {
                                    "hypotheses": [
                                        {
                                            "seed_kg_id": "node:seed",
                                            "candidate_kg_id": "node:candidate1",
                                            "statement": "Seed may couple with candidate 1.",
                                            "relation_hint": "ASSOCIATED_WITH",
                                            "novelty_score": 0.7,
                                            "ood_score": 0.75,
                                        }
                                    ]
                                }
                            },
                        },
                    },
                },
            },
            {
                "job_id": "run_deep_research",
                "state": "succeeded",
                "result": {"summary": "Deep research summary text."},
            },
        ]

        result = runner.invoke(
            app,
            [
                "hypothesis",
                "fmri based image decoding",
                "--with-research",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert "candidate_cards" in result.stdout
        assert "minimal_discriminating_test" in result.stdout
        assert "grounding_status" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
