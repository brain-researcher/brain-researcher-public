"""Tests for the agent planner contract endpoints."""

import importlib
import re
from collections.abc import Iterable
from typing import Any

import pytest

from brain_researcher.services.agent.web_service import app
from tests.unit.agent.job_store_test_utils import patched_job_store

_CANONICAL_RUNTIME_TOOL_ID_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def _assert_canonical_runtime_tool_id(tool_id: str) -> None:
    normalized = str(tool_id or "").strip()
    assert normalized
    assert ".run" not in normalized
    assert _CANONICAL_RUNTIME_TOOL_ID_RE.fullmatch(normalized), normalized


@pytest.fixture(autouse=True)
def _isolate_plan_contract_tests(monkeypatch):
    import brain_researcher.services.agent.web_service as ws

    monkeypatch.delenv("BR_USE_TOOL_RETRIEVER", raising=False)
    monkeypatch.setattr(ws, "_get_contract_tool_retriever", lambda: None)
    monkeypatch.setattr(ws, "_env_tool_allowlist", lambda: None)


def test_agent_plan_stub_response():
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "inputs": {"fmri_img": "bold.nii.gz", "atlas_name": "Schaefer2018_200"},
    }

    response = client.post("/agent/plan", json=payload)

    assert response.status_code == 200
    data = response.get_json()
    assert data["resolvable"] is True
    assert len(data["dag"]["steps"]) >= 2
    assert data["dag"]["steps"][0]["tool"] == "fetch_atlas"
    assert "por_token" in data
    assert data["handoff"]["schema_version"] == "br-plan-handoff-v1"
    assert data["handoff"]["plan_id"] == data["plan_id"]
    assert data["handoff"]["pipeline"] == "connectivity"
    assert data["handoff"]["inputs"]["atlas_name"] == "Schaefer2018_200"


def test_agent_plan_stub_response_eeg():
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["eeg"],
        "inputs": {
            "raw_eeg": "sub-01_task-rest_eeg.fif",
            "montage_name": "standard_1020",
        },
    }

    response = client.post("/agent/plan", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    steps = data["dag"]["steps"]
    assert steps[0]["tool"] == "resolve_montage"
    assert any(step["tool"] == "connectivity_measures" for step in steps)


def test_agent_plan_stub_response_meg_uses_meeg_tools_not_fmri():
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "query": "MEG connectivity analysis for sensor time series",
        "domain": "neuroimaging",
        "modality": ["meg"],
        "inputs": {"raw_meg": "sub-01_task-rest_meg.fif"},
    }

    response = client.post("/agent/plan", json=payload)

    assert response.status_code == 200
    data = response.get_json()
    steps = [step["tool"] for step in data["dag"]["steps"]]
    assert "connectivity_measures" in steps
    assert "nilearn_connectivity_matrix" not in steps
    assert "extract_timeseries" not in steps
    assert "fetch_atlas" not in steps


class _StubToolRetriever:
    def retrieve_tools(self, query, family_ids=None, top_k=10, filters=None):
        return [
            {"id": "python.fetch_atlas.run", "score": 0.91, "source": "br_kg"},
            {
                "id": "python.nilearn_connectivity_matrix.run",
                "score": 0.83,
                "source": "br_kg",
            },
        ]


_GOLDEN_PREPLIGHT_CASES = [
    {
        "pipeline": "connectivity",
        "query": (
            "Compute functional connectivity matrix for resting-state fMRI "
            "with Schaefer atlas"
        ),
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "inputs": {"fmri_img": "bold.nii.gz", "atlas_name": "Schaefer2018_200"},
    },
    {
        "pipeline": "connectivity",
        "query": "Estimate EEG connectivity using 10-20 montage",
        "domain": "neuroimaging",
        "modality": ["eeg"],
        "inputs": {
            "raw_eeg": "sub-01_task-rest_eeg.fif",
            "montage_name": "standard_1020",
        },
    },
    {
        "pipeline": "connectivity",
        "query": "Build a structural connectome from diffusion MRI streamlines",
        "domain": "neuroimaging",
        "modality": ["dmri"],
        "inputs": {
            "dwi_img": "sub-01_dwi.nii.gz",
            "bvecs": "sub-01.bvec",
            "bvals": "sub-01.bval",
        },
    },
    {
        "pipeline": "morphometry",
        "query": "Run sMRI morphometry to estimate cortical thickness",
        "domain": "neuroimaging",
        "modality": ["smri"],
        "inputs": {"t1w_image": "sub-01_T1w.nii.gz"},
    },
    {
        "pipeline": "meta_termmap",
        "query": "Meta-analysis term map for working memory",
        "domain": "literature",
        "modality": ["fmri"],
        "inputs": {"term": "working memory"},
    },
    {
        "pipeline": "pet",
        "query": "Compute SUVR from PET using cerebellum reference",
        "domain": "neuroimaging",
        "modality": ["pet"],
        "inputs": {"pet_img": "sub-01_pet.nii.gz", "reference_region": "cerebellum"},
    },
    {
        "pipeline": "kg_ingest_validate",
        "query": "Validate KG ingest for OpenNeuro dataset",
        "domain": "br_kg",
        "modality": ["fmri"],
        "inputs": {"dataset_id": "ds000030"},
    },
    {
        "pipeline": "demo_stub",
        "query": "Demo: quick preprocessing walkthrough",
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "inputs": {},
    },
]


def _assert_no_legacy_run_ids(values: Iterable[str]) -> None:
    leaked = sorted(
        {
            str(value).strip()
            for value in values
            if str(value or "").strip().endswith(".run")
        }
    )
    assert not leaked, f"planner surface leaked legacy *.run tool ids: {leaked}"


@pytest.mark.parametrize("payload", _GOLDEN_PREPLIGHT_CASES)
def test_agent_plan_preflight_includes_tool_candidates(monkeypatch, payload):
    import brain_researcher.services.agent.web_service as ws

    monkeypatch.setattr(
        ws, "_get_contract_tool_retriever", lambda: _StubToolRetriever()
    )
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "1")

    client = app.test_client()
    response = client.post("/agent/plan", json=payload)
    assert response.status_code == 200
    data = response.get_json()

    context = data.get("context") or {}
    tool_candidates = context.get("tool_candidates") or []
    tool_candidate_diagnostics = context.get("tool_candidate_diagnostics") or {}
    assert tool_candidates, "expected tool candidates in plan context"
    assert tool_candidate_diagnostics.get("candidate_count") == len(tool_candidates)
    assert tool_candidate_diagnostics.get("surface") == "plan"
    assert "candidate_generation_latency_ms" in tool_candidate_diagnostics
    for cand in tool_candidates:
        assert "tool_id" in cand
        assert "tool_id_raw" in cand
        assert "source" in cand
        assert "available" in cand
        assert "registry_available" in cand
        assert "catalog_available" in cand

    query_understanding = context.get("query_understanding") or {}
    assert query_understanding.get("original_query") == payload["query"]

    planner_state = data.get("planner_state") or {}
    assert planner_state.get("tool_candidates") == tool_candidates
    assert planner_state.get("tool_candidate_diagnostics") == tool_candidate_diagnostics
    assert planner_state.get("query_understanding") == query_understanding
    routing_diagnostics = planner_state.get("routing_diagnostics") or {}
    assert routing_diagnostics.get("surface") == "plan"
    assert routing_diagnostics.get("preflight_candidate_count") == len(tool_candidates)
    assert routing_diagnostics.get("preflight_candidate_source_counts") == (
        tool_candidate_diagnostics.get("candidate_source_counts")
    )
    assert routing_diagnostics.get("candidate_count") == len(
        data.get("candidates") or []
    )
    assert routing_diagnostics.get(
        "planner_candidate_count"
    ) == routing_diagnostics.get("candidate_count")


@pytest.mark.parametrize("payload", _GOLDEN_PREPLIGHT_CASES)
def test_agent_plan_contract_emits_canonical_runtime_tool_ids(monkeypatch, payload):
    import brain_researcher.services.agent.web_service as ws

    monkeypatch.setattr(
        ws, "_get_contract_tool_retriever", lambda: _StubToolRetriever()
    )
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "1")

    client = app.test_client()
    response = client.post("/agent/plan", json=payload)
    assert response.status_code == 200

    data = response.get_json()
    routing_diagnostics = data.get("routing_diagnostics") or {}
    for step in data.get("dag", {}).get("steps") or []:
        _assert_canonical_runtime_tool_id(step["tool"])

    for candidate in data.get("context", {}).get("tool_candidates") or []:
        _assert_canonical_runtime_tool_id(candidate["tool_id"])
        raw_tool_id = str(candidate.get("tool_id_raw") or "").strip()
        if raw_tool_id.endswith(".run"):
            assert candidate["tool_id"] != raw_tool_id

    for candidate in data.get("candidates") or []:
        _assert_canonical_runtime_tool_id(candidate["tool_id"])

    chosen_tool = data.get("chosen_tool")
    if chosen_tool:
        _assert_canonical_runtime_tool_id(chosen_tool)
    assert "selected_tool_rank" in routing_diagnostics
    assert "selected_tool_in_top_5" in routing_diagnostics
    assert "selected_tool_in_top_10" in routing_diagnostics
    assert "routing_latency_ms" in routing_diagnostics


def test_agent_plan_surface_emits_canonical_tool_ids_only(monkeypatch):
    import brain_researcher.services.agent.web_service as ws

    monkeypatch.setattr(
        ws, "_get_contract_tool_retriever", lambda: _StubToolRetriever()
    )
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "1")

    client = app.test_client()
    response = client.post(
        "/agent/plan",
        json={
            "pipeline": "searchlight",
            "query": "Run searchlight decoding and brain extraction",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {
                "fmri_img": "bold.nii.gz",
                "structural_img": "sub-01_T1w.nii.gz",
            },
        },
    )

    assert response.status_code == 200
    data = response.get_json()

    step_tool_ids = [
        str(step.get("tool") or "").strip()
        for step in (data.get("dag", {}).get("steps") or [])
    ]
    candidate_tool_ids = [
        str(cand.get("tool_id") or "").strip()
        for cand in ((data.get("context") or {}).get("tool_candidates") or [])
    ]
    planner_candidate_ids: list[str] = []
    for cand in data.get("candidates") or []:
        if isinstance(cand, dict):
            tool_id = str(
                cand.get("tool_id") or cand.get("tool") or cand.get("id") or ""
            ).strip()
            if tool_id:
                planner_candidate_ids.append(tool_id)

    assert candidate_tool_ids
    _assert_no_legacy_run_ids(step_tool_ids)
    _assert_no_legacy_run_ids(candidate_tool_ids)
    _assert_no_legacy_run_ids(planner_candidate_ids)
    _assert_no_legacy_run_ids([str(data.get("chosen_tool") or "").strip()])


def test_agent_plan_reports_plan_step_allowlist_denial_metadata(monkeypatch):
    import brain_researcher.services.agent.web_service as ws

    monkeypatch.setattr(ws, "_plan_surface_tool_allowlist", lambda mode: ["tool.safe"])
    monkeypatch.setattr(ws, "_infer_tool_family", lambda tool_id: "unit.family")

    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "query": "Compute functional connectivity matrix for resting-state fMRI",
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "inputs": {"fmri_img": "bold.nii.gz", "atlas_name": "Schaefer2018_200"},
    }

    response = client.post("/agent/plan", json=payload)

    assert response.status_code == 403
    data = response.get_json()
    assert data["error"] == "tool_not_allowed"
    assert data["denied_tool_id"] is not None
    assert data["denied_family"] == "unit.family"
    assert data["denial_stage"] == "plan_step_allowlist_check"
    assert data["denial_reason_code"] == "plan_contains_disallowed_tools"


def test_agent_plan_diagnostic_allowlist_mode_bypasses_chat_surface(monkeypatch):
    from types import SimpleNamespace

    import brain_researcher.services.agent.web_service as ws

    class _FakePlanner:
        def plan(self, **kwargs):
            return SimpleNamespace(
                candidates=[
                    {
                        "tool_id": "blocked.tool",
                        "tool_name": "Blocked Tool",
                        "final_score": 0.99,
                        "source": "catalog",
                        "available": True,
                    }
                ],
                scores={"blocked.tool": 0.99},
                chosen_tool_id="blocked.tool",
                selection_reasons=[],
                mask_reasons=[],
                intent=[],
                predicted_capabilities=[],
                predicted_intents=[],
                capability_prediction={},
                cross_stage_context={},
                loop_signals=[],
                routing_diagnostics={"candidate_count": 1, "routing_latency_ms": 1.0},
                confidence_score=0.9,
            )

    monkeypatch.setattr(
        ws,
        "_plan_surface_tool_allowlist",
        lambda mode: (
            ["tool.safe"] if mode == "curated" else ["blocked.tool", "tool.safe"]
        ),
    )
    monkeypatch.setattr(
        ws,
        "_build_plan_for_request",
        lambda plan_request: (_ for _ in ()).throw(ValueError()),
    )
    monkeypatch.setattr(
        "brain_researcher.services.agent.planner.unified_planner.get_default_unified_planner",
        lambda tool_retriever=None: _FakePlanner(),
    )

    client = app.test_client()
    response = client.post(
        "/agent/plan",
        json={
            "pipeline": "diagnostic routing",
            "query": "diagnostic routing",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "allowlist_mode": "diagnostic",
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["allowlist_mode"] == "diagnostic"
    assert data["chosen_tool"] == "blocked.tool"
    assert data["routing_diagnostics"]["allowlist_mode"] == "diagnostic"


def test_agent_plan_contract_skips_agent_runtime_init_in_soft_mode(monkeypatch):
    import brain_researcher.services.agent.web_service as ws
    from brain_researcher.services.agent.tool_candidate_service import (
        ToolCandidateBundle,
    )
    from brain_researcher.services.shared.planner.models import Plan, PlanDAG, StepSpec

    monkeypatch.delenv("BR_STRICT_PLAN_TOOL_VALIDATION", raising=False)
    monkeypatch.setattr(
        ws,
        "generate_tool_candidates",
        lambda *args, **kwargs: ToolCandidateBundle(
            ctx={"runtime_surface": "plan"},
            query_understanding={"original_query": "extract roi timeseries"},
            tool_candidates=[],
            tool_candidate_diagnostics={},
            resolution_state={},
        ),
    )
    monkeypatch.setattr(
        ws,
        "_build_plan_for_request",
        lambda plan_request: Plan(
            plan_id="plan-soft-no-agent",
            domain=plan_request.domain,
            modality=plan_request.modality,
            resolvable=True,
            dag=PlanDAG(
                steps=[
                    StepSpec(
                        id="001-main",
                        tool="extract_timeseries",
                        params=dict(plan_request.inputs or {}),
                        runtime_kind="python",
                    )
                ]
            ),
            chosen_tool="extract_timeseries",
            mode="catalog",
            allowlist_mode=plan_request.allowlist_mode,
        ),
    )
    monkeypatch.setattr(
        ws,
        "get_agent",
        lambda: (_ for _ in ()).throw(
            AssertionError("get_agent should not run in soft contract planning")
        ),
    )

    client = app.test_client()
    response = client.post(
        "/agent/plan",
        json={
            "pipeline": "connectivity",
            "query": "extract roi timeseries",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {"dataset_ref": "ds000114", "atlas": "aal"},
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["chosen_tool"] == "extract_timeseries"


def test_tool_candidates_canonicalize_to_registry_ids():
    from brain_researcher.services.agent.preflight import ensure_tool_candidates

    class StubRegistry:
        def __init__(self, tool_names):
            self._tools = {name: object() for name in tool_names}

        def get_tool(self, name):
            return self._tools.get(name)

    class StubRetriever:
        def retrieve_tools(self, query, family_ids=None, top_k=10, filters=None):
            return [
                {"id": "python.fetch_atlas.run", "score": 0.9, "source": "br_kg"},
                {"id": "fsl.bet.run", "score": 0.8, "source": "br_kg"},
                {"id": "fsl.fslFixText", "score": 0.79, "source": "br_kg"},
                {"id": "ants.antsRegistration.run", "score": 0.78, "source": "br_kg"},
                {"id": "bidsapp.fmriprep.run", "score": 0.7, "source": "br_kg"},
                {"id": "fmriprep", "score": 0.69, "source": "br_kg"},
            ]

    registry = StubRegistry(
        [
            "fetch_atlas",
            "fsl_bet",
            "fsl_fix",
            "ants_registration",
            "fmriprep_preprocessing",
        ]
    )
    ctx = {}
    candidates = ensure_tool_candidates(
        "test query",
        ctx,
        tool_retriever=StubRetriever(),
        registry=registry,
    )

    tool_ids = {c["tool_id"] for c in candidates}
    assert "fetch_atlas" in tool_ids
    assert "fsl_bet" in tool_ids
    assert "fsl_fix" in tool_ids
    assert "ants_registration" in tool_ids
    assert "fmriprep_preprocessing" in tool_ids
    diagnostics = ctx.get("tool_candidate_diagnostics") or {}
    assert diagnostics.get("candidate_count") == len(candidates)
    assert diagnostics.get("candidate_source_counts", {}).get("br_kg") == len(
        candidates
    )
    assert "surface" in diagnostics
    assert "candidate_generation_latency_ms" in diagnostics
    assert "routing_latency_ms" in diagnostics
    _assert_no_legacy_run_ids(c["tool_id"] for c in candidates)


def test_agent_plan_surfaces_resolution_memory_state(monkeypatch):
    import brain_researcher.services.agent.web_service as ws

    class EmptyRetriever:
        def retrieve_tools(self, query, family_ids=None, top_k=10, filters=None):
            return []

    runtime_surface = "unit-plan-resolution-state"
    monkeypatch.setattr(ws, "_get_contract_tool_retriever", lambda: EmptyRetriever())
    monkeypatch.setenv("BR_USE_TOOL_RETRIEVER", "1")

    client = app.test_client()
    response = client.post(
        "/agent/plan",
        json={
            "pipeline": "tool search",
            "query": "masker labels time series nilearn",
            "domain": "neuroimaging",
            "modality": ["fmri"],
            "inputs": {},
            "mode": "catalog",
            "thread_id": "planner-resolution-thread",
            "runtime_surface": runtime_surface,
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    planner_state = data.get("planner_state") or {}
    assert "resolution_cache_stats" in planner_state
    assert planner_state.get("step_statuses", {}).get("tool_candidates", {}).get(
        "status"
    ) in {"needs_verification", "unresolved", "confirmed"}
    assert isinstance(planner_state.get("pending_decisions"), list)


def test_agent_run_plan_streams_events(monkeypatch):
    client = app.test_client()
    plan_payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["fmri"],
    }
    plan_response = client.post("/agent/plan", json=plan_payload)
    data = plan_response.get_json()

    run_request = {
        "plan_id": data["plan_id"],
        "version": data.get("version", 1),
        "por_token": data["por_token"],
    }

    with patched_job_store(monkeypatch) as store:
        response = client.post("/agent/run_plan", json=run_request)

    assert response.status_code == 202
    body = response.get_json()
    assert body["plan_id"] == run_request["plan_id"]
    assert "job_id" in body

    stream_suffix = f"/jobs/{body['job_id']}/stream"
    assert body["stream_url"].endswith(stream_suffix)
    assert body["status_url"].endswith(body["job_id"])
    assert store.enqueued_jobs


# ===== Helper Functions for Comprehensive Contract Tests =====


def _flatten(obj: Any) -> Iterable[Any]:
    """Recursively flatten nested dict/list structures into all primitive values."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _flatten(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _flatten(v)
    else:
        yield obj


def _extract_step_names(plan_json: dict) -> list[str]:
    """
    Collect likely step tool names from a variety of common schema shapes:
    - plan['steps'][i]['tool'] or ['tool_id'] or ['name']
    - plan['dag']['nodes'][i]['tool'] ...
    Fallback: scan all dicts for keys that look like identifiers.
    """
    names: list[str] = []

    # Obvious places first
    candidates = []
    if isinstance(plan_json.get("steps"), list):
        candidates.extend(plan_json["steps"])
    if isinstance(plan_json.get("dag"), dict) and isinstance(
        plan_json["dag"].get("steps"), list
    ):
        candidates.extend(plan_json["dag"]["steps"])
    if isinstance(plan_json.get("dag"), dict) and isinstance(
        plan_json["dag"].get("nodes"), list
    ):
        candidates.extend(plan_json["dag"]["nodes"])

    def pick(d: dict) -> str | None:
        for k in ("tool", "tool_id", "name", "id"):
            v = d.get(k)
            if isinstance(v, str) and "_" in v:
                return v
        return None

    for d in candidates:
        if isinstance(d, dict):
            n = pick(d)
            if n:
                names.append(n)

    # Fallback: deep scan
    if not names:
        for item in _flatten(plan_json):
            if isinstance(item, dict):
                n = pick(item)
                if n:
                    names.append(n)

    return names


def _assert_subsequence_in_order(haystack: list[str], subseq: list[str]) -> None:
    """Assert that subseq appears in haystack in the given order (not necessarily consecutive)."""
    it = iter(haystack)
    for target in subseq:
        for h in it:
            if h.endswith(target) or h == target:
                break
        else:
            raise AssertionError(
                f"Expected step '{target}' not found in order. Got: {haystack}"
            )


# ===== Comprehensive Contract Tests for iEEG and dMRI =====


def test_plan_ieeg_connectivity_contains_expected_steps():
    """Test that iEEG connectivity plan contains the expected steps in order."""
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["ieeg"],
        # minimal plausible inputs; planner should validate/accept
        "inputs": {"bids_root": "/tmp/ds-ieeg", "subject": "01"},
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200, r.text
    plan = r.get_json()
    step_names = _extract_step_names(plan)

    expected = [
        "ieeg_electrode_localize",
        "ieeg_preprocess",
        "ieeg_epoch_features",
        "ieeg_connectivity",
    ]
    _assert_subsequence_in_order(step_names, expected)


def test_plan_dmri_connectome_contains_expected_steps():
    """Test that dMRI connectome plan contains the expected steps in order."""
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["dmri"],  # Use dmri as the valid modality
        "inputs": {"bids_root": "/tmp/ds-dmri", "subject": "01"},
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200, r.text
    plan = r.get_json()
    step_names = _extract_step_names(plan)

    # Keep the requirement minimal: these three must appear in order.
    expected = [
        "dmri_resolve_dwi_triplet",
        "dmri_fit_model",
        "dmri_parcellate_connectome",
    ]
    _assert_subsequence_in_order(step_names, expected)


def test_plan_dmri_with_dmri_modality():
    """Test that dMRI connectome plan also works with 'dmri' modality string."""
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["dmri"],  # Test the dmri alias
        "inputs": {"bids_root": "/tmp/ds-dmri", "subject": "01"},
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200, r.text
    plan = r.get_json()
    step_names = _extract_step_names(plan)

    expected = [
        "dmri_resolve_dwi_triplet",
        "dmri_fit_model",
        "dmri_parcellate_connectome",
    ]
    _assert_subsequence_in_order(step_names, expected)


def test_plan_ieeg_rejects_when_modality_missing():
    """Test that plan request without modality is rejected or returns resolvable=False."""
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        # no modality field
        "inputs": {"bids_root": "/tmp/ds-ieeg", "subject": "01"},
    }
    r = client.post("/agent/plan", json=payload)
    # Accept either 400/422 or a resolvable=False contract; assert one of them.
    if r.status_code == 200:
        body = r.get_json()
        assert body.get("resolvable") is False or body.get("error") is not None
    else:
        assert r.status_code in (400, 422)


def test_registry_has_new_modalities():
    """Verify that all new ieeg/dmri tools are registered in tools.auto._MODULE_PATHS."""
    auto = importlib.import_module("brain_researcher.services.tools.auto")
    # Minimal existence checks against the lazy loader map
    for key in (
        "ieeg_preprocess_tool",
        "ieeg_electrode_localize_tool",
        "ieeg_epoch_features_tool",
        "ieeg_connectivity_tool",
        "dmri_resolve_dwi_triplet_tool",
        "dmri_fit_model_tool",
        "dmri_parcellate_connectome_tool",
        "smri_recon_tool",
        "smri_parcellation_stats_tool",
        "smri_surface_export_tool",
    ):
        assert key in getattr(
            auto, "_MODULE_PATHS", {}
        ), f"{key} missing from tools.auto._MODULE_PATHS"


def test_plan_ieeg_includes_coregistration():
    """Verify iEEG plan includes coregistration when CT and MRI provided."""
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["ieeg"],
        "inputs": {
            "ct_image": "/data/sub-01_ct.nii.gz",
            "mri_image": "/data/sub-01_T1w.nii.gz",
        },
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200
    plan = r.get_json()
    step_names = _extract_step_names(plan)

    # Verify coreg_register appears before electrode_localize
    assert "coreg_register" in step_names
    coreg_idx = step_names.index("coreg_register")
    localize_idx = next(
        i for i, s in enumerate(step_names) if "electrode_localize" in s
    )
    assert coreg_idx < localize_idx


def test_plan_dmri_includes_parcellation_fetch():
    """Verify dMRI plan fetches parcellation when atlas_name provided."""
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",
        "domain": "neuroimaging",
        "modality": ["dmri"],
        "inputs": {
            "bids_root": "/data/ds-dmri",
            "subject": "01",
            "atlas_name": "Schaefer2018_200",
        },
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200
    plan = r.get_json()
    step_names = _extract_step_names(plan)

    assert "parcellation_fetch" in step_names
    fetch_idx = step_names.index("parcellation_fetch")
    connectome_idx = next(
        i for i, s in enumerate(step_names) if "parcellate_connectome" in s
    )
    assert fetch_idx < connectome_idx


def test_resolve_bids_tool_in_registry():
    """Verify new resolver tools are registered."""
    auto = importlib.import_module("brain_researcher.services.tools.auto")
    for key in (
        "coreg_register_tool",
        "coreg_apply_xfm_tool",
        "parcellation_fetch_tool",
        "label_transfer_tool",
        "resolve_bids_tool",
        "resolve_space_tool",
        "smri_recon_tool",
        "smri_parcellation_stats_tool",
        "smri_surface_export_tool",
    ):
        assert key in getattr(
            auto, "_MODULE_PATHS", {}
        ), f"{key} missing from tools.auto._MODULE_PATHS"


def test_plan_smri_morphometry_contains_expected_steps():
    """Test that sMRI morphometry plan contains the expected steps in order."""
    client = app.test_client()
    payload = {
        "pipeline": "morphometry",
        "domain": "neuroimaging",
        "modality": ["smri"],
        "inputs": {"t1w_image": "/data/sub-01_T1w.nii.gz"},
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200
    plan = r.get_json()
    step_names = _extract_step_names(plan)

    expected = ["smri_recon", "smri_parcellation_stats", "smri_surface_export"]
    _assert_subsequence_in_order(step_names, expected)


def test_plan_smri_with_bids_includes_resolver():
    """Verify sMRI morphometry plan prepends resolve_bids when BIDS inputs provided."""
    client = app.test_client()
    payload = {
        "pipeline": "morphometry",
        "domain": "neuroimaging",
        "modality": ["smri"],
        "inputs": {"bids_root": "/data/ds001", "subject_id": "01"},
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200
    plan = r.get_json()
    step_names = _extract_step_names(plan)

    assert "resolve_bids" in step_names
    assert "smri_recon" in step_names
    assert step_names.index("resolve_bids") < step_names.index("smri_recon")


def test_plan_pet_suvr_contains_expected_steps():
    """Test that PET SUVR plan contains the expected steps in order."""
    client = app.test_client()
    payload = {
        "pipeline": "metabolism",
        "domain": "neuroimaging",
        "modality": ["pet"],
        "inputs": {
            "pet_image": "/data/sub-01_pet.nii.gz",
            "t1w_image": "/data/sub-01_T1w.nii.gz",
            "atlas_name": "Schaefer2018_200",
        },
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200
    plan = r.get_json()
    step_names = _extract_step_names(plan)

    expected = ["pet_coreg", "pet_suvr", "pet_parcellate"]
    _assert_subsequence_in_order(step_names, expected)


def test_plan_pet_with_bids_includes_resolver():
    """Verify PET plan prepends resolve_bids when BIDS inputs provided."""
    client = app.test_client()
    payload = {
        "pipeline": "pet",
        "domain": "neuroimaging",
        "modality": ["pet"],
        "inputs": {
            "bids_root": "/data/ds001",
            "subject_id": "01",
            "atlas_name": "Schaefer2018_200",
        },
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200
    plan = r.get_json()
    step_names = _extract_step_names(plan)

    # Should have resolve_bids, parcellation_fetch, and PET steps
    assert "resolve_bids" in step_names
    assert "pet_coreg" in step_names
    # resolve_bids should come before PET processing
    if "resolve_bids" in step_names:
        assert step_names.index("resolve_bids") < step_names.index("pet_coreg")


def test_registry_has_pet_tools():
    """Verify PET tools are registered in tools.auto._MODULE_PATHS."""
    auto = importlib.import_module("brain_researcher.services.tools.auto")
    for key in ("pet_coreg_tool", "pet_suvr_tool", "pet_parcellate_tool"):
        assert key in getattr(
            auto, "_MODULE_PATHS", {}
        ), f"{key} missing from tools.auto._MODULE_PATHS"


def test_plan_meta_termmap_contains_expected_steps():
    """Verify meta-analysis plan contains brainmap → align → combine steps."""
    client = app.test_client()
    payload = {
        "pipeline": "meta_termmap",
        "domain": "literature",
        "modality": [],
        "inputs": {"term": "attention", "target_space": "MNI152NLin6Asym"},
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200
    step_names = _extract_step_names(r.get_json())
    _assert_subsequence_in_order(
        step_names, ["meta_brainmap", "meta_align", "meta_combine"]
    )


def test_plan_kg_ingest_validate_contains_expected_steps():
    """Verify KG ingestion/validation plan includes required steps."""
    client = app.test_client()
    payload = {
        "pipeline": "kg_ingest_validate",
        "domain": "br_kg",
        "modality": [],
        "inputs": {"nodes_file": "nodes.csv", "edges_file": "edges.csv"},
    }
    r = client.post("/agent/plan", json=payload)
    assert r.status_code == 200
    step_names = _extract_step_names(r.get_json())
    _assert_subsequence_in_order(step_names, ["kg_ingest", "kg_shacl_validate"])


def test_registry_has_meta_kg_tools():
    """Verify meta-analysis and KG tools are registered."""
    auto = importlib.import_module("brain_researcher.services.tools.auto")
    for key in (
        "meta_brainmap_tool",
        "meta_align_tool",
        "meta_combine_tool",
        "kg_ingest_tool",
        "kg_shacl_validate_tool",
        "kg_multihop_qa_tool",
    ):
        assert key in getattr(
            auto, "_MODULE_PATHS", {}
        ), f"{key} missing from tools.auto._MODULE_PATHS"


# ============================================================================
# P0-1: Selection Reasoning Tests
# ============================================================================


def test_agent_plan_includes_selection_reasoning():
    """
    Test /agent/plan includes P0-1 selection reasoning fields.

    Verifies that the catalog-driven planner returns:
    - intent: Extracted intent operators
    - candidates: Ranked candidate tools with scores (if tools found)
    - chosen_tool: Selected tool ID (if resolvable)
    - selection_reason: Human-readable explanation (if resolvable)
    """
    client = app.test_client()
    payload = {
        "pipeline": "connectivity",  # Use a query that might match existing catalog
        "domain": "neuroimaging",
        "modality": ["fmri"],
        "inputs": {},
    }

    response = client.post("/agent/plan", json=payload)
    assert response.status_code == 200

    plan = response.get_json()

    # P0-1: Check selection reasoning fields exist (may be empty if no tools found)
    assert "intent" in plan, "Plan should include intent field"
    assert isinstance(plan.get("intent"), list | type(None))

    assert "candidates" in plan, "Plan should include candidates field"
    assert isinstance(plan.get("candidates"), list | type(None))

    # Timestamp may be None if fallback to template planner
    assert "timestamp" in plan, "Plan should include timestamp field"
    if plan.get("timestamp") is not None:
        assert isinstance(plan["timestamp"], int)

    # If plan is resolvable and has candidates, verify detailed fields
    candidates = plan.get("candidates") or []
    if plan.get("resolvable") and len(candidates) > 0:
        # Check candidate structure
        candidate = plan["candidates"][0]
        assert "tool_id" in candidate
        assert "final_score" in candidate
        assert "explanation" in candidate
        assert "preflight_passed" in candidate
        assert "intent_match_score" in candidate
        assert "description_score" in candidate
        assert "metadata_score" in candidate
        assert "resource_fit_score" in candidate

        assert "chosen_tool" in plan, "Resolvable plan should include chosen tool"
        assert (
            plan["chosen_tool"] == candidate["tool_id"]
        ), "Top candidate should be chosen"

        assert "selection_reason" in plan, "Resolvable plan should explain selection"
        assert (
            len(plan["selection_reason"]) > 10
        ), "Selection reason should be non-trivial"


def test_agent_plan_unresolvable_returns_empty_candidates():
    """Test that unresolvable queries return empty candidates with warnings."""
    client = app.test_client()
    payload = {
        "pipeline": "xyzabc nonsense query that matches nothing",
        "domain": "neuroimaging",
        "modality": [],
        "inputs": {},
    }

    response = client.post("/agent/plan", json=payload)
    assert response.status_code == 200

    plan = response.get_json()

    # Should be unresolvable
    assert plan.get("resolvable") is False

    # Should have empty/no candidates
    assert len(plan.get("candidates", [])) == 0

    # Should have warnings
    assert len(plan.get("warnings", [])) > 0

    # Should not have chosen_tool
    assert plan.get("chosen_tool") is None


def test_build_plan_routing_diagnostics_marks_missing_tool_choice():
    import brain_researcher.services.agent.web_service as ws

    diagnostics = ws._build_plan_routing_diagnostics(
        candidate_rows=[
            {"tool_id": "tool.a", "source": "catalog"},
            {"tool_id": "tool.b", "source": "catalog"},
        ],
        chosen_tool=None,
        preflight_tool_candidate_diagnostics={
            "candidate_count": 2,
            "candidate_source_counts": {"catalog": 2},
        },
        routing_latency_ms=12.5,
    )

    assert diagnostics["candidate_count"] == 2
    assert diagnostics["preflight_candidate_count"] == 2
    assert diagnostics["planner_candidate_count"] == 2
    assert diagnostics["selected_tool_rank"] is None
    assert diagnostics["routing_terminal_reason"] == "plan_returned_without_tool_choice"


def test_build_plan_routing_diagnostics_splits_preflight_from_planner():
    import brain_researcher.services.agent.web_service as ws

    diagnostics = ws._build_plan_routing_diagnostics(
        candidate_rows=[],
        chosen_tool=None,
        preflight_tool_candidate_diagnostics={
            "candidate_count": 12,
            "candidate_source_counts": {"br_kg": 12},
            "candidate_source": "br_kg",
        },
        routing_latency_ms=33.0,
    )

    assert diagnostics["candidate_count"] == 0
    assert diagnostics["planner_candidate_count"] == 0
    assert diagnostics["candidate_source_counts"] == {}
    assert diagnostics["preflight_candidate_count"] == 12
    assert diagnostics["preflight_candidate_source_counts"] == {"br_kg": 12}
    assert (
        diagnostics["routing_terminal_reason"]
        == "preflight_candidates_not_promoted_to_plan"
    )
