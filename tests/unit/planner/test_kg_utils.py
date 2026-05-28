import pytest

from brain_researcher.services.agent.planner.kg_utils import (
    extract_dataset_from_context,
    extract_task_family,
    normalize_dataset_id,
    normalize_tool_id,
)


def test_normalize_tool_id_strips():
    assert normalize_tool_id("  fsl.bet.run ") == "fsl.bet.run"
    assert normalize_tool_id(None) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ds:openneuro:ds000001", "ds:openneuro:ds000001"),
        ("ds000001", "ds:openneuro:ds000001"),
        ("DS000123", "ds:openneuro:ds000123"),
        ("custom-ds", "custom-ds"),
        (None, None),
    ],
)
def test_normalize_dataset_id(raw, expected):
    assert normalize_dataset_id(raw) == expected


def test_extract_dataset_from_context_prefers_resolved():
    ctx = {
        "query_understanding": {
            "resolved_datasets": [{"dataset_id": "ds000001"}],
            "candidate_datasets": [{"dataset_id": "ds000999"}],
        }
    }
    assert extract_dataset_from_context(ctx) == "ds000001"


def test_extract_dataset_from_context_candidates():
    ctx = {
        "query_understanding": {
            "candidate_datasets": [{"id": "cand001"}],
        }
    }
    assert extract_dataset_from_context(ctx) == "cand001"


def test_extract_task_family_order():
    ctx = {"query_understanding": {"intent": ["glm", "qc"]}}
    assert extract_task_family(ctx, pipeline="fallback") == "glm"
    assert extract_task_family({}, pipeline="pipe") == "pipe"
    assert extract_task_family({}, pipeline=None) is None
