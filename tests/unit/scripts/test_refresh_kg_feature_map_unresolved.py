"""Unit tests for refresh_kg_feature_map_unresolved helpers."""

from __future__ import annotations

from scripts.analysis.refresh_kg_feature_map_unresolved import (
    extract_nested_onvoc_ids,
    is_unresolved_item,
    summarize_items,
)


def test_is_unresolved_item_handles_missing_or_empty_features() -> None:
    assert is_unresolved_item(None) is True

    empty_item = {
        "task_raw": "x",
        "contrast": "aVb",
        "kg_feature_ids": [],
        "onvoc_ids": [],
        "quality": {"task_resolved": False, "n_features": 0},
    }
    assert is_unresolved_item(empty_item) is True

    resolved_item = {
        "task_raw": "x",
        "contrast": "aVb",
        "kg_feature_ids": ["tsk_123", "cnt_456"],
        "onvoc_ids": ["ONVOC_0000001"],
        "quality": {"task_resolved": True, "n_features": 3},
    }
    assert is_unresolved_item(resolved_item) is False


def test_extract_nested_onvoc_ids_collects_deep_values() -> None:
    payload = {
        "data": {
            "onvoc_primary_id": "ONVOC_0000100",
            "nested": [{"onvoc_id": "ONVOC_0000200"}, {"x": "y"}],
        },
        "meta": {"onvoc_ids": ["ONVOC_0000300", "NOT_ONVOC"]},
    }
    out: set[str] = set()
    extract_nested_onvoc_ids(payload, out)

    assert out == {"ONVOC_0000100", "ONVOC_0000200", "ONVOC_0000300"}


def test_summarize_items_reports_resolution_rates() -> None:
    items = [
        {
            "quality": {
                "task_resolved": True,
                "contrast_resolved": True,
                "n_features": 2,
            }
        },
        {
            "quality": {
                "task_resolved": False,
                "contrast_resolved": True,
                "n_features": 0,
            }
        },
    ]

    s = summarize_items(items)
    assert s["n_items"] == 2
    assert s["task_resolution_rate"] == 0.5
    assert s["contrast_resolution_rate"] == 1.0
    assert s["feature_nonempty_rate"] == 0.5
