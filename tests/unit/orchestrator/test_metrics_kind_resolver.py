import importlib
from types import SimpleNamespace

import pytest

from brain_researcher.services.telemetry.metrics_kind_resolver import (
    resolve_job_kind,
    load_job_kind_mapping,
    reset_job_kind_cache,
)
from brain_researcher.services.telemetry.job_kind import JobKind


@pytest.fixture(autouse=True)
def reset_mapping_cache():
    """Ensure each test receives a fresh mapping."""
    reset_job_kind_cache()
    yield
    reset_job_kind_cache()


def test_resolve_job_kind_from_pipeline():
    request = SimpleNamespace(pipeline=SimpleNamespace(value="glm_first_level"))
    assert resolve_job_kind(request=request) == JobKind.GLM.value


def test_resolve_job_kind_prefix_match():
    request = SimpleNamespace(pipeline=SimpleNamespace(value="kg_ingest_subjects"))
    assert resolve_job_kind(request=request) == JobKind.KG_INGEST.value


def test_resolve_job_kind_from_tool_metadata():
    payload = {
        "metadata": {
            "parameters": {"tool": "niclip"}
        }
    }
    assert resolve_job_kind(payload=payload) == JobKind.EMBEDDING.value


def test_resolve_job_kind_agent_tool_fallback():
    payload = {
        "metadata": {
            "parameters": {"tool": "custom_tool_without_mapping"}
        }
    }
    assert resolve_job_kind(payload=payload) == JobKind.AGENT_TOOL.value


def test_resolve_job_kind_from_canonical_op():
    request = SimpleNamespace(pipeline=None, canonical_op={"name": "planner"})
    assert resolve_job_kind(request=request) == JobKind.PLANNER.value
