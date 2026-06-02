from __future__ import annotations

import json

from brain_researcher.services.br_kg.analytics.psych101_task_fmri_bridge_audit import (
    Psych101TaskFmriBridgeAuditConfig,
    run_psych101_task_fmri_bridge_audit,
    write_psych101_task_fmri_bridge_audit_artifacts,
)


class _FakeBridgeAuditDB:
    def execute_query(self, query, params=None):
        params = params or {}
        compact = " ".join(str(query).split())
        if "MATCH (d:Dataset) RETURN count(DISTINCT d) AS value" in compact:
            return [{"value": 10}]
        if (
            "MATCH (:Dataset)-[r:HAS_TASK|USES_TASK]->(:Task) RETURN count(r) AS value"
            in compact
        ):
            return [{"value": 20}]
        if "MATCH (ta:TaskAnalysis) RETURN count(DISTINCT ta) AS value" in compact:
            return [{"value": 5}]
        if "MATCH (c:Contrast) RETURN count(DISTINCT c) AS value" in compact:
            return [{"value": 12}]
        if "MATCH (m:StatsMap) RETURN count(DISTINCT m) AS value" in compact:
            return [{"value": 40}]
        if (
            "MATCH (:StatsMap)-[r:IN_REGION]->(:BrainRegion) RETURN count(r) AS value"
            in compact
        ):
            return [{"value": 200}]
        if "MATCH (e:Psych101Experiment) RETURN count(DISTINCT e) AS value" in compact:
            return [{"value": 3}]
        if (
            "MATCH (:Psych101Experiment)-[r:USES_TASK]->(:Task) RETURN count(r) AS value"
            in compact
        ):
            return [{"value": 4}]
        if (
            "MATCH (:Psych101Experiment)-[:USES_TASK]->(t:Task)<-[:HAS_TASK|USES_TASK]-(:Dataset)"
            in compact
        ):
            return [{"value": 0}]
        if (
            "MATCH (:Psych101Experiment)-[:USES_TASK]->(:Task)-[:MAPS_TO]->(t:Task)<-[:HAS_TASK|USES_TASK]-(:Dataset)"
            in compact
        ):
            return [{"value": 0}]
        if (
            "MATCH (:Psych101Experiment)-[:USES_TASK]->(:Task)-[:MAPS_TO]->(t:Task)<-[:MAPS_TO]-(ta:TaskAnalysis)"
            in compact
        ):
            return [{"value": 1}]
        if (
            "MATCH (:Psych101Experiment)-[:USES_TASK]->(:Task)-[:BELONGS_TO_FAMILY]->(:TaskFamily)"
            in compact
        ):
            return [{"value": 2}]
        if "RETURN e.id AS experiment_id" in compact:
            limit = int(params.get("limit") or 0)
            rows = [
                {
                    "experiment_id": "exp:1",
                    "experiment_name": "Experiment 1",
                    "local_task_ids": ["task:local1"],
                    "local_task_names": ["Local Task 1"],
                    "canonical_task_ids": ["task:canon1"],
                    "canonical_task_names": ["Canonical Task 1"],
                    "family_ids": ["tf:wm"],
                    "family_names": ["Working Memory"],
                    "canonical_task_analysis_hits": 1,
                    "canonical_contrast_hits": 2,
                    "canonical_brain_region_hits": 4,
                    "family_task_analysis_hits": 1,
                    "family_contrast_hits": 2,
                    "family_brain_region_hits": 4,
                },
                {
                    "experiment_id": "exp:2",
                    "experiment_name": "Experiment 2",
                    "local_task_ids": ["task:local2"],
                    "local_task_names": ["Local Task 2"],
                    "canonical_task_ids": [],
                    "canonical_task_names": [],
                    "family_ids": ["tf:decision"],
                    "family_names": ["Decision"],
                    "canonical_task_analysis_hits": 0,
                    "canonical_contrast_hits": 0,
                    "canonical_brain_region_hits": 0,
                    "family_task_analysis_hits": 2,
                    "family_contrast_hits": 3,
                    "family_brain_region_hits": 5,
                },
                {
                    "experiment_id": "exp:3",
                    "experiment_name": "Experiment 3",
                    "local_task_ids": ["task:local3"],
                    "local_task_names": ["Local Task 3"],
                    "canonical_task_ids": [],
                    "canonical_task_names": [],
                    "family_ids": [],
                    "family_names": [],
                    "canonical_task_analysis_hits": 0,
                    "canonical_contrast_hits": 0,
                    "canonical_brain_region_hits": 0,
                    "family_task_analysis_hits": 0,
                    "family_contrast_hits": 0,
                    "family_brain_region_hits": 0,
                },
            ]
            return rows[:limit]
        raise AssertionError(f"Unexpected query: {compact}")


def test_psych101_task_fmri_bridge_audit_summarizes_bridge_status(tmp_path):
    result = run_psych101_task_fmri_bridge_audit(
        _FakeBridgeAuditDB(),
        config=Psych101TaskFmriBridgeAuditConfig(experiment_limit=3),
    )

    summary = result["summary"]
    assert summary["dataset_count"] == 10
    assert summary["overlap"]["canonical_task_analysis_count"] == 1
    assert summary["overlap"]["family_task_analysis_count"] == 2
    assert summary["bridge_status_counts"] == {
        "canonical_bridge_ready": 1,
        "family_bridge_ready": 1,
        "local_only": 1,
    }

    artifact_paths = write_psych101_task_fmri_bridge_audit_artifacts(
        result,
        output_dir=tmp_path,
    )
    assert (tmp_path / "experiment_bridge_audit.tsv").exists()
    assert (
        json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))[
            "bridge_status_counts"
        ]["family_bridge_ready"]
        == 1
    )
    assert artifact_paths["summary_json"].endswith("summary.json")
