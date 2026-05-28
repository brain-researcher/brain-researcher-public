"""Tests for explicit neuroAI generalization-validity review checks."""

from __future__ import annotations

import json

import pytest

from brain_researcher.core.contracts.code_review import CodeReviewBundle


def _bundle(
    *,
    review_context: dict | None = None,
    observed_artifacts: dict | None = None,
    kg_context: dict | None = None,
) -> CodeReviewBundle:
    return CodeReviewBundle(
        plan_steps=[],
        declared_modalities=[],
        declared_spaces=[],
        review_context=review_context or {},
        observed_artifacts=observed_artifacts or {},
        kg_context=kg_context or {},
    )


@pytest.mark.unit
class TestNeuroAiSelectionOnTestCheck:
    def test_blocks_explicit_selection_on_test(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_selection_on_test_check,
        )

        bundle = _bundle(
            review_context={
                "selection": {
                    "selection_on_test": True,
                    "selection_scope": "heldout",
                    "best_model": "layer-12",
                }
            },
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_selection_on_test_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SELECTION_ON_TEST"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("selection_on_test=true" in item for item in finding.kg_evidence)

    def test_ignores_non_neuroai_context(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_selection_on_test_check,
        )

        bundle = _bundle(
            review_context={"selection": {"selection_on_test": True}},
            kg_context={"analysis_family": "glm"},
        )

        assert neuroai_selection_on_test_check(bundle) is None


@pytest.mark.unit
class TestNeuroAiSplitGroupingMismatchCheck:
    def test_blocks_random_tr_split_without_required_grouping(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_split_grouping_mismatch_check,
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "split_unit": "tr",
                    "split_strategy_detail": "random_tr_split",
                    "grouped_split_keys": ["subject"],
                    "required_group_keys": ["story", "session", "subject"],
                }
            },
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_split_grouping_mismatch_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SPLIT_GROUPING_MISMATCH"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("required_group_keys" in item for item in finding.kg_evidence)

    def test_allows_grouping_aware_split(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_split_grouping_mismatch_check,
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "split_unit": "tr",
                    "split_strategy_detail": "random_tr_split",
                    "grouped_split_keys": ["story", "session", "subject"],
                    "required_group_keys": ["story", "session", "subject"],
                }
            },
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_split_grouping_mismatch_check(bundle) is None

    def test_blocks_subject_manifest_coverage_gap(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_manifest_coverage_check,
        )

        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "participant_id\nu1\nu2\n",
            encoding="utf-8",
        )
        fold_manifest = tmp_path / "fold_manifest.json"
        fold_manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u3"},
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_manifest_path": "subject_manifest.tsv",
                    "fold_manifest_path": "fold_manifest.json",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_subject_manifest_coverage_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SUBJECT_MANIFEST_COVERAGE"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("missing_subject_ids" in item for item in finding.kg_evidence)

    def test_allows_subject_manifest_covering_split_subjects(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_manifest_coverage_check,
        )

        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "participant_id\nu1\nu2\nu3\n",
            encoding="utf-8",
        )
        fold_manifest = tmp_path / "fold_manifest.json"
        fold_manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u3"},
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_manifest_path": "subject_manifest.tsv",
                    "fold_manifest_path": "fold_manifest.json",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_subject_manifest_coverage_check(bundle) is None

    def test_blocks_subject_intersection_coverage_gap(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_intersection_coverage_check,
        )

        intersection_manifest = tmp_path / "subject_intersection.tsv"
        intersection_manifest.write_text(
            "participant_id\nu1\nu2\n",
            encoding="utf-8",
        )
        fold_manifest = tmp_path / "fold_manifest.json"
        fold_manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u3"},
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_intersection_manifest_path": "subject_intersection.tsv",
                    "fold_manifest_path": "fold_manifest.json",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_subject_intersection_coverage_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SUBJECT_INTERSECTION_COVERAGE"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("subject_intersection_manifest_path" in item for item in finding.kg_evidence)

    def test_allows_subject_intersection_covering_split_subjects(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_intersection_coverage_check,
        )

        intersection_manifest = tmp_path / "subject_intersection.tsv"
        intersection_manifest.write_text(
            "participant_id\nu1\nu2\nu3\n",
            encoding="utf-8",
        )
        fold_manifest = tmp_path / "fold_manifest.json"
        fold_manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u3"},
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_intersection_manifest_path": "subject_intersection.tsv",
                    "fold_manifest_path": "fold_manifest.json",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_subject_intersection_coverage_check(bundle) is None

    def test_blocks_subject_intersection_subset_conflict(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_intersection_subset_conflict_check,
        )

        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "participant_id\nu1\nu2\n",
            encoding="utf-8",
        )
        intersection_manifest = tmp_path / "subject_intersection.tsv"
        intersection_manifest.write_text(
            "participant_id\nu1\nu3\n",
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_manifest_path": "subject_manifest.tsv",
                    "subject_intersection_manifest_path": "subject_intersection.tsv",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_subject_intersection_subset_conflict_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SUBJECT_INTERSECTION_SUBSET_CONFLICT"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("subject_manifest_path" in item for item in finding.kg_evidence)

    def test_allows_subject_intersection_subset_of_subject_manifest(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_intersection_subset_conflict_check,
        )

        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "participant_id\nu1\nu2\nu3\n",
            encoding="utf-8",
        )
        intersection_manifest = tmp_path / "subject_intersection.tsv"
        intersection_manifest.write_text(
            "participant_id\nu1\nu3\n",
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_manifest_path": "subject_manifest.tsv",
                    "subject_intersection_manifest_path": "subject_intersection.tsv",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_subject_intersection_subset_conflict_check(bundle) is None

    def test_blocks_subject_selection_source_coverage_gap(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_selection_source_coverage_check,
        )

        selection_source = tmp_path / "subjects.txt"
        selection_source.write_text("u1\nu2\n", encoding="utf-8")
        fold_manifest = tmp_path / "fold_manifest.json"
        fold_manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u3"},
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_selection_source": "subjects.txt",
                    "fold_manifest_path": "fold_manifest.json",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_subject_selection_source_coverage_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SUBJECT_SELECTION_SOURCE_COVERAGE"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("subject_selection_source" in item for item in finding.kg_evidence)

    def test_allows_subject_selection_source_covering_split_subjects(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_selection_source_coverage_check,
        )

        selection_source = tmp_path / "subjects.txt"
        selection_source.write_text("u1\nu2\nu3\n", encoding="utf-8")
        fold_manifest = tmp_path / "fold_manifest.json"
        fold_manifest.write_text(
            json.dumps(
                [
                    {"fold_id": 0, "partition": "train", "subject": "u1"},
                    {"fold_id": 0, "partition": "test", "subject": "u3"},
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_selection_source": "subjects.txt",
                    "fold_manifest_path": "fold_manifest.json",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_subject_selection_source_coverage_check(bundle) is None

    def test_blocks_subject_manifest_selection_source_subset_conflict(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_manifest_selection_source_subset_conflict_check,
        )

        selection_source = tmp_path / "subjects.txt"
        selection_source.write_text("u1\nu2\n", encoding="utf-8")
        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "participant_id\nu1\nu3\n",
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_selection_source": "subjects.txt",
                    "subject_manifest_path": "subject_manifest.tsv",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_subject_manifest_selection_source_subset_conflict_check(bundle)
        assert finding is not None
        assert (
            finding.rule_id
            == "REVIEW_NEUROAI_SUBJECT_MANIFEST_SELECTION_SOURCE_CONFLICT"
        )
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("subject_manifest_path" in item for item in finding.kg_evidence)

    def test_blocks_subject_intersection_selection_source_subset_conflict(
        self, tmp_path
    ):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_subject_intersection_selection_source_subset_conflict_check,
        )

        selection_source = tmp_path / "subjects.txt"
        selection_source.write_text("u1\nu2\n", encoding="utf-8")
        subject_intersection = tmp_path / "subject_intersection.tsv"
        subject_intersection.write_text(
            "participant_id\nu1\nu3\n",
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_selection_source": "subjects.txt",
                    "subject_intersection_manifest_path": "subject_intersection.tsv",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = (
            neuroai_subject_intersection_selection_source_subset_conflict_check(bundle)
        )
        assert finding is not None
        assert (
            finding.rule_id
            == "REVIEW_NEUROAI_SUBJECT_INTERSECTION_SELECTION_SOURCE_CONFLICT"
        )
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any(
            "subject_intersection_manifest_path" in item for item in finding.kg_evidence
        )

    def test_blocks_declared_subject_set_missing_subject_column(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_declared_subject_set_missing_subject_column_check,
        )

        subject_manifest = tmp_path / "subject_manifest.tsv"
        subject_manifest.write_text(
            "sample_id\nu1\nu2\n",
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_manifest_path": "subject_manifest.tsv",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_declared_subject_set_missing_subject_column_check(bundle)
        assert finding is not None
        assert (
            finding.rule_id
            == "REVIEW_NEUROAI_DECLARED_SUBJECT_SET_MISSING_SUBJECT_COLUMN"
        )
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("expected_subject_keys" in item for item in finding.kg_evidence)

    def test_allows_plaintext_subject_selection_source_without_subject_column(
        self, tmp_path
    ):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_declared_subject_set_missing_subject_column_check,
        )

        selection_source = tmp_path / "subjects.txt"
        selection_source.write_text("u1\nu2\n", encoding="utf-8")

        bundle = _bundle(
            review_context={
                "split": {
                    "subject_selection_source": "subjects.txt",
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_declared_subject_set_missing_subject_column_check(bundle) is None

    def test_blocks_manifest_missing_required_group_keys(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_split_manifest_missing_group_keys_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "subject": "u1",
                    },
                    {
                        "fold_id": 0,
                        "partition": "test",
                        "story": "s2",
                        "subject": "u2",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_split_manifest_missing_group_keys_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SPLIT_MANIFEST_MISSING_GROUP_KEYS"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("manifest_keys" in item for item in finding.kg_evidence)

    def test_allows_manifest_with_all_required_group_keys(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_split_manifest_missing_group_keys_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "fold_id": 0,
                        "partition": "test",
                        "story": "s2",
                        "session": "b",
                        "subject": "u2",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_split_manifest_missing_group_keys_check(bundle) is None

    def test_blocks_manifest_partition_conflict_within_fold_scope(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_split_manifest_partition_conflict_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "fold_id": 0,
                        "partition": "test",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_split_manifest_partition_conflict_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SPLIT_MANIFEST_PARTITION_CONFLICT"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("manifest_path=" in item for item in finding.kg_evidence)

    def test_allows_same_group_tuple_across_different_fold_scopes(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_split_manifest_partition_conflict_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "fold_id": 1,
                        "partition": "test",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                }
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_split_manifest_partition_conflict_check(bundle) is None

    def test_blocks_nested_cv_outer_holdout_conflict(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_nested_cv_outer_holdout_conflict_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "outer_fold": 0,
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "outer_fold": 0,
                        "fold_id": 1,
                        "partition": "test",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                },
                "selection": {"nested_cv": True},
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_nested_cv_outer_holdout_conflict_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_NESTED_CV_OUTER_HOLDOUT_CONFLICT"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("outer_fold=" in item for item in finding.kg_evidence)

    def test_allows_nested_cv_without_outer_holdout_conflict(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_nested_cv_outer_holdout_conflict_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "outer_fold": 0,
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "outer_fold": 0,
                        "fold_id": 1,
                        "partition": "validation",
                        "story": "s2",
                        "session": "a",
                        "subject": "u2",
                    },
                    {
                        "outer_fold": 0,
                        "fold_id": 2,
                        "partition": "test",
                        "story": "s3",
                        "session": "a",
                        "subject": "u3",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                },
                "selection": {"nested_cv": True},
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_nested_cv_outer_holdout_conflict_check(bundle) is None

    def test_blocks_nested_cv_schema_missing_fold_keys(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_nested_cv_schema_missing_fold_keys_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "fold_id": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "fold_id": 0,
                        "partition": "test",
                        "story": "s2",
                        "session": "a",
                        "subject": "u2",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                },
                "selection": {"nested_cv": True},
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_nested_cv_schema_missing_fold_keys_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_NESTED_CV_SCHEMA_MISSING_FOLD_KEYS"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("missing_nested_cv_keys" in item for item in finding.kg_evidence)

    def test_blocks_nested_cv_outer_partition_gap(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_nested_cv_outer_partition_gap_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "outer_fold": 0,
                        "inner_fold": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "outer_fold": 0,
                        "inner_fold": 0,
                        "partition": "validation",
                        "story": "s2",
                        "session": "a",
                        "subject": "u2",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                },
                "selection": {"nested_cv": True},
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_nested_cv_outer_partition_gap_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_NESTED_CV_OUTER_PARTITION_GAP"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("observed_partitions" in item for item in finding.kg_evidence)

    def test_blocks_nested_cv_inner_partition_gap(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_nested_cv_inner_partition_gap_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "outer_fold": 0,
                        "inner_fold": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "outer_fold": 0,
                        "partition": "test",
                        "story": "s3",
                        "session": "a",
                        "subject": "u3",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                },
                "selection": {"nested_cv": True},
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_nested_cv_inner_partition_gap_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_NESTED_CV_INNER_PARTITION_GAP"
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("inner_fold=" in item for item in finding.kg_evidence)

    def test_allows_well_formed_nested_cv_manifest(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_nested_cv_inner_partition_gap_check,
            neuroai_nested_cv_outer_missing_inner_resampling_check,
            neuroai_nested_cv_outer_partition_gap_check,
            neuroai_nested_cv_schema_missing_fold_keys_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "outer_fold": 0,
                        "inner_fold": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "outer_fold": 0,
                        "inner_fold": 0,
                        "partition": "validation",
                        "story": "s2",
                        "session": "a",
                        "subject": "u2",
                    },
                    {
                        "outer_fold": 0,
                        "partition": "test",
                        "story": "s3",
                        "session": "a",
                        "subject": "u3",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                },
                "selection": {"nested_cv": True},
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_nested_cv_schema_missing_fold_keys_check(bundle) is None
        assert neuroai_nested_cv_outer_partition_gap_check(bundle) is None
        assert neuroai_nested_cv_outer_missing_inner_resampling_check(bundle) is None
        assert neuroai_nested_cv_inner_partition_gap_check(bundle) is None

    def test_blocks_nested_cv_outer_missing_inner_resampling(self, tmp_path):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_nested_cv_outer_missing_inner_resampling_check,
        )

        manifest = tmp_path / "fold_manifest.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "outer_fold": 0,
                        "partition": "train",
                        "story": "s1",
                        "session": "a",
                        "subject": "u1",
                    },
                    {
                        "outer_fold": 0,
                        "partition": "validation",
                        "story": "s2",
                        "session": "a",
                        "subject": "u2",
                    },
                    {
                        "outer_fold": 0,
                        "partition": "test",
                        "inner_fold": 0,
                        "story": "s3",
                        "session": "a",
                        "subject": "u3",
                    },
                ]
            ),
            encoding="utf-8",
        )

        bundle = _bundle(
            review_context={
                "split": {
                    "fold_manifest_path": "fold_manifest.json",
                    "required_group_keys": ["story", "session", "subject"],
                },
                "selection": {"nested_cv": True},
            },
            observed_artifacts={"analysis_bundle": {"run_dir": str(tmp_path)}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_nested_cv_outer_missing_inner_resampling_check(bundle)
        assert finding is not None
        assert (
            finding.rule_id
            == "REVIEW_NEUROAI_NESTED_CV_OUTER_MISSING_INNER_RESAMPLING"
        )
        assert finding.action == "block"
        assert finding.severity == "error"
        assert finding.reason_tags == ["leakage", "generalization"]
        assert any("training_side_partitions" in item for item in finding.kg_evidence)


@pytest.mark.unit
class TestNeuroAiSelectionMultiplicityAccountingCheck:
    def test_warns_when_winner_lacks_multiplicity_accounting(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_selection_multiplicity_accounting_check,
        )

        bundle = _bundle(
            review_context={
                "selection": {"best_model": "layer-12"},
                "model_candidates": ["m1", "m2", "m3", "m4"],
                "layer_candidates": ["layer-1", "layer-2", "layer-3"],
                "roi_candidates": ["tpj", "mpfc"],
            },
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_selection_multiplicity_accounting_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SELECTION_MULTIPLICITY_ACCOUNTING"
        assert finding.action == "warn"
        assert finding.severity == "warn"
        assert finding.reason_tags == ["generalization"]
        assert any("candidate_counts" in item for item in finding.kg_evidence)

    def test_allows_when_accounting_is_recorded(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_selection_multiplicity_accounting_check,
        )

        bundle = _bundle(
            review_context={
                "selection": {"best_model": "layer-12"},
                "model_candidates": ["m1", "m2", "m3", "m4"],
                "layer_candidates": ["layer-1", "layer-2", "layer-3"],
                "selection_accounting": {
                    "nested_cv": True,
                    "multiple_comparison_correction": "fdr",
                },
            },
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_selection_multiplicity_accounting_check(bundle) is None


@pytest.mark.unit
class TestNeuroAiWinnerWithoutCandidateSetCheck:
    def test_warns_when_winner_is_declared_without_candidate_set(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_winner_without_candidate_set_check,
        )

        bundle = _bundle(
            review_context={"selection": {"best_model": "llm-large"}},
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_winner_without_candidate_set_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_WINNER_WITHOUT_CANDIDATE_SET"
        assert finding.action == "warn"
        assert finding.severity == "warn"
        assert finding.reason_tags == ["generalization"]
        assert any("winner_fields" in item for item in finding.kg_evidence)

    def test_allows_when_candidate_set_is_present(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_winner_without_candidate_set_check,
        )

        bundle = _bundle(
            review_context={
                "selection": {
                    "best_model": "llm-large",
                    "model_candidates": ["llm-small", "llm-large"],
                }
            },
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_winner_without_candidate_set_check(bundle) is None


@pytest.mark.unit
class TestNeuroAiSelectionValidationGapCheck:
    def test_warns_when_multi_candidate_winner_lacks_validation_metadata(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_selection_validation_gap_check,
        )

        bundle = _bundle(
            review_context={
                "selection": {
                    "best_layer": "layer-12",
                    "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                }
            },
            kg_context={"analysis_family": "embedding_analysis"},
        )

        finding = neuroai_selection_validation_gap_check(bundle)
        assert finding is not None
        assert finding.rule_id == "REVIEW_NEUROAI_SELECTION_VALIDATION_GAP"
        assert finding.action == "warn"
        assert finding.severity == "warn"
        assert finding.reason_tags == ["generalization"]
        assert any("candidate_counts" in item for item in finding.kg_evidence)

    def test_allows_when_nested_validation_is_recorded(self):
        from brain_researcher.services.review.checks.neuroai_validity import (
            neuroai_selection_validation_gap_check,
        )

        bundle = _bundle(
            review_context={
                "selection": {
                    "best_layer": "layer-12",
                    "layer_candidates": ["layer-4", "layer-8", "layer-12"],
                    "nested_cv": True,
                }
            },
            kg_context={"analysis_family": "embedding_analysis"},
        )

        assert neuroai_selection_validation_gap_check(bundle) is None
