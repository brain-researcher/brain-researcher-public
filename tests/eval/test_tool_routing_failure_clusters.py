import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "eval" / "analyze_tool_routing_failure_clusters.py"
SPEC = importlib.util.spec_from_file_location(
    "analyze_tool_routing_failure_clusters", SCRIPT_PATH
)
assert SPEC is not None
assert SPEC.loader is not None
analyzer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyzer)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_analyze_failure_clusters_separates_label_and_retriever_buckets(
    tmp_path: Path,
) -> None:
    labels = tmp_path / "labels.jsonl"
    predictions = tmp_path / "predictions.json"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "T-hit",
                "category": "Connectivity",
                "query": "connectivity",
                "exact_labels": {
                    "expected_tool_ids": ["conn_tool"],
                    "expected_family_ids": ["conn.family"],
                },
            },
            {
                "task_id": "T-family-wrong",
                "category": "Connectivity",
                "query": "wrong within family",
                "exact_labels": {
                    "expected_tool_ids": ["conn_tool"],
                    "expected_family_ids": ["conn.family"],
                },
            },
            {
                "task_id": "T-invalid",
                "category": "Statistics",
                "query": "invalid label",
                "exact_labels": {
                    "expected_tool_ids": ["missing_tool"],
                    "expected_family_ids": ["stats.family"],
                },
            },
            {
                "task_id": "T-missing-pred",
                "category": "Preprocessing",
                "query": "no prediction row",
                "exact_labels": {
                    "expected_tool_ids": ["preproc_tool"],
                    "expected_family_ids": ["preproc.family"],
                },
            },
            {
                "task_id": "T-absent",
                "category": "Statistics",
                "query": "expected absent from candidates",
                "exact_labels": {
                    "expected_tool_ids": ["stats_tool"],
                    "expected_family_ids": ["stats.family"],
                },
            },
            {
                "task_id": "T-no-label",
                "category": "Preprocessing",
                "query": "missing exact labels",
                "exact_labels": {"expected_tool_ids": []},
            },
        ],
    )
    predictions.write_text(
        json.dumps(
            [
                {
                    "task_id": "T-hit",
                    "mode": "legacy",
                    "top_tool_ids": ["wrong_tool"],
                },
                {
                    "task_id": "T-hit",
                    "mode": "cards",
                    "top_tool_ids": ["conn_tool", "other_conn"],
                },
                {
                    "task_id": "T-family-wrong",
                    "mode": "cards",
                    "top_tool_ids": ["other_conn", "conn_tool"],
                },
                {
                    "task_id": "T-invalid",
                    "mode": "cards",
                    "top_tool_ids": ["stats_tool"],
                },
                {
                    "task_id": "T-absent",
                    "mode": "cards",
                    "top_tool_ids": ["wrong_tool"],
                },
                {
                    "task_id": "T-no-label",
                    "mode": "cards",
                    "top_tool_ids": ["preproc_tool"],
                },
            ]
        ),
        encoding="utf-8",
    )

    payload = analyzer.analyze(
        labels_jsonl=labels,
        predictions_path=predictions,
        mode="auto",
        catalog_tool_ids={
            "conn_tool",
            "other_conn",
            "stats_tool",
            "preproc_tool",
            "wrong_tool",
        },
        known_family_ids={
            "conn.family",
            "stats.family",
            "preproc.family",
            "wrong.family",
        },
        tool_to_family={
            "conn_tool": "conn.family",
            "other_conn": "conn.family",
            "stats_tool": "stats.family",
            "preproc_tool": "preproc.family",
            "wrong_tool": "wrong.family",
        },
    )

    summary = payload["summary"]
    assert summary["task_count"] == 6
    assert summary["valid_exact_task_count"] == 5
    assert summary["top1_recall"] == 0.2
    assert summary["provided_candidate_availability_rate"] == 0.4
    assert summary["bucket_counts"] == {
        "hit": 1,
        "family_correct_tool_wrong": 1,
        "invalid_label_expected_tool_not_exposed": 1,
        "missing_prediction": 1,
        "retriever_candidate_absent": 1,
        "missing_exact_label": 1,
    }

    missing_expected = {
        row["tool_id"]: row for row in payload["missing_expected_tools"]
    }
    assert missing_expected["missing_tool"]["count"] == 1

    absent_expected = {
        row["tool_id"]: row for row in payload["candidate_absent_expected_tools"]
    }
    assert absent_expected["stats_tool"]["example_task_ids"] == ["T-absent"]

    category_clusters = {
        row["cluster"]: row for row in payload["clusters"]["by_category"]
    }
    assert category_clusters["Connectivity"]["task_count"] == 2
    assert category_clusters["Connectivity"]["top1_recall"] == 0.5

    assert payload["top_tool_confusions"][0]["expected_tool_id"] == "conn_tool"
    assert payload["top_tool_confusions"][0]["predicted_top1"] == "other_conn"


def test_analyze_accepts_jsonl_predictions_and_writes_outputs(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    predictions = tmp_path / "predictions.jsonl"
    out = tmp_path / "out"
    _write_jsonl(
        labels,
        [
            {
                "task_id": "T1",
                "category": "QC",
                "exact_labels": {
                    "expected_tool_ids": ["qc_tool"],
                    "acceptable_tool_ids": ["qc_alt"],
                    "expected_family_ids": ["qc.family"],
                },
            }
        ],
    )
    _write_jsonl(
        predictions,
        [{"task_id": "T1", "top_tool_ids": ["qc_alt"], "candidate_count": 1}],
    )

    payload = analyzer.analyze(
        labels_jsonl=labels,
        predictions_path=predictions,
        mode=None,
        catalog_tool_ids={"qc_tool", "qc_alt"},
        known_family_ids={"qc.family"},
        tool_to_family={"qc_tool": "qc.family", "qc_alt": "qc.family"},
    )
    analyzer.write_outputs(payload, out)

    assert payload["summary"]["top1_recall"] == 1.0
    assert (
        json.loads((out / "failure_clusters.json").read_text(encoding="utf-8"))[
            "summary"
        ]["task_count"]
        == 1
    )
    assert (out / "task_failures.jsonl").read_text(encoding="utf-8") == ""
    assert "Tool Routing Failure Clusters" in (out / "failure_clusters.md").read_text(
        encoding="utf-8"
    )
