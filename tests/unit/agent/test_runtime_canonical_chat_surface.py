from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from brain_researcher.services.agent.tool_allowlist_loader import (
    load_chat_tools_allowlist,
    resolve_runtime_tool_allowlist,
)


def test_chat_allowlist_includes_spm12_vbm_runtime_canonical_id(monkeypatch):
    monkeypatch.delenv("CHAT_TOOLS_PATH", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST", raising=False)
    monkeypatch.delenv("AGENT_TOOL_ALLOWLIST_STRICT", raising=False)
    monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)

    allowset = set(load_chat_tools_allowlist())

    assert "spm12_vbm" in allowset


def test_runtime_allowlist_preserves_spm12_vbm_runtime_id(monkeypatch):
    monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)

    resolved = resolve_runtime_tool_allowlist(["spm12_vbm"], strict=True)

    assert resolved == ["spm12_vbm"]


# ---------------------------------------------------------------------------
# /agent/studio/plan endpoint tests
# ---------------------------------------------------------------------------


def _make_flask_test_client():
    """Return a Flask test client for the agent web_service app."""
    from brain_researcher.services.agent.web_service import app

    app.config["TESTING"] = True
    return app.test_client()


def _fake_bundle(
    *,
    tool_candidates,
    query_understanding=None,
    resolution_state=None,
    tool_candidate_diagnostics=None,
):
    return SimpleNamespace(
        tool_candidates=tool_candidates,
        query_understanding=query_understanding,
        resolution_state=resolution_state or {},
        tool_candidate_diagnostics=tool_candidate_diagnostics or {},
    )

def test_studio_plan_returns_ops_grounded_in_tool_candidates(monkeypatch):
    """Endpoint returns ops whose metadata.tool_id matches a candidate from retrieval."""
    fake_candidates = [
        {
            "tool_id": "cat12",
            "source": "br_kg",
            "score": 0.92,
            "description": "CAT12 VBM",
        },
        {
            "tool_id": "tool_execute",
            "source": "runtime",
            "score": 0.75,
            "description": "Disallowed runtime executor",
        },
    ]
    fake_bundle = _fake_bundle(tool_candidates=fake_candidates)

    with patch(
        "brain_researcher.services.agent.web_service.generate_tool_candidates",
        return_value=fake_bundle,
    ):
        client = _make_flask_test_client()
        resp = client.post(
            "/agent/studio/plan",
            json={"prompt": "run CAT12 VBM", "notebook_context": {}},
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert "Neurodesk execution scaffold" in data["assistant_message"]
    assert len(data["ops"]) == 2
    assert all(op["metadata"]["tool_id"] == "spm12_vbm" for op in data["ops"])
    assert any("module load cat12" in op["source"] for op in data["ops"])
    # Candidates should be returned for transparency
    assert [c["tool_id"] for c in data["tool_candidates"]] == ["spm12_vbm"]


def test_studio_plan_builds_generic_markdown_without_candidates(monkeypatch):
    fake_bundle = _fake_bundle(tool_candidates=[])

    with patch(
        "brain_researcher.services.agent.web_service.generate_tool_candidates",
        return_value=fake_bundle,
    ):
        client = _make_flask_test_client()
        resp = client.post(
            "/agent/studio/plan",
            json={"prompt": "add a markdown cell", "notebook_context": {}},
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["assistant_message"] == "Drafted deterministic notebook cells from your request."
    assert len(data["ops"]) == 1
    assert data["ops"][0]["cell_type"] == "markdown"
    assert "## Note" in data["ops"][0]["source"]


def test_studio_plan_requires_prompt():
    client = _make_flask_test_client()
    resp = client.post(
        "/agent/studio/plan",
        json={"notebook_context": {}},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_prompt"


def test_studio_plan_builds_glm_scaffold_from_candidate(monkeypatch):
    fake_bundle = _fake_bundle(tool_candidates=[
        {
            "tool_id": "glm_first_level",
            "source": "catalog",
            "score": 0.93,
            "description": "First-level GLM",
        }
    ])

    with patch(
        "brain_researcher.services.agent.web_service.generate_tool_candidates",
        return_value=fake_bundle,
    ):
        client = _make_flask_test_client()
        resp = client.post(
            "/agent/studio/plan",
            json={"prompt": "build a first-level GLM for an OpenNeuro task run", "notebook_context": {}},
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert "first-level GLM scaffold" in data["assistant_message"]
    assert any("FirstLevelModel" in op["source"] for op in data["ops"])
    assert any("plot_design_matrix" in op["source"] for op in data["ops"])


def test_studio_plan_filters_disallowed_candidates_and_canonicalizes_tool_ids(
    monkeypatch,
):
    monkeypatch.delenv("BR_AGENT_ALLOW_ALL_RUNTIME_TOOLS", raising=False)
    monkeypatch.delenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", raising=False)

    fake_bundle = _fake_bundle(tool_candidates=[
        {
            "tool_id": "cat12",
            "source": "br_kg",
            "score": 0.91,
            "description": "CAT12 VBM",
        },
        {
            "tool_id": "tool_execute",
            "source": "runtime",
            "score": 0.99,
            "description": "Disallowed runtime executor",
        },
    ])

    with patch(
        "brain_researcher.services.agent.web_service.generate_tool_candidates",
        return_value=fake_bundle,
    ):
        client = _make_flask_test_client()
        resp = client.post(
            "/agent/studio/plan",
            json={"prompt": "run CAT12 VBM", "notebook_context": {}},
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert [c["tool_id"] for c in data["tool_candidates"]] == ["spm12_vbm"]
    assert all(op["metadata"]["tool_id"] == "spm12_vbm" for op in data["ops"])


def test_studio_plan_builds_bids_app_scaffold_from_candidate(monkeypatch):
    fake_bundle = _fake_bundle(tool_candidates=[
        {
            "tool_id": "run_bids_app",
            "source": "catalog",
            "score": 0.88,
            "description": "Run a BIDS App",
        }
    ])

    with patch(
        "brain_researcher.services.agent.web_service.generate_tool_candidates",
        return_value=fake_bundle,
    ):
        client = _make_flask_test_client()
        resp = client.post(
            "/agent/studio/plan",
            json={
                "prompt": "run fmriprep on my BIDS dataset",
                "notebook_context": {},
                "allowlist_mode": "diagnostic",
            },
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert "fmriprep BIDS App scaffold" in data["ops"][0]["source"]
    assert all(op["metadata"]["tool_id"] == "run_bids_app" for op in data["ops"])
    assert any("app_name = \"fmriprep\"" in op["source"] for op in data["ops"])


def test_studio_plan_grounds_glm_paths_from_query_understanding(tmp_path):
    bids_root = tmp_path / "ds000001"
    deriv_root = bids_root / "derivatives" / "fmriprep"
    raw_func = bids_root / "sub-01" / "func"
    deriv_func = deriv_root / "sub-01" / "func"
    raw_func.mkdir(parents=True)
    deriv_func.mkdir(parents=True)

    events_path = raw_func / "sub-01_task-motor_events.tsv"
    bold_path = (
        deriv_func
        / "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
    )
    confounds_path = (
        deriv_func / "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-confounds_timeseries.tsv"
    )
    events_path.write_text("onset\tduration\ttrial_type\n0\t1\tleft\n", encoding="utf-8")
    bold_path.write_text("", encoding="utf-8")
    confounds_path.write_text("framewise_displacement\n0.0\n", encoding="utf-8")

    fake_bundle = _fake_bundle(
        tool_candidates=[
            {
                "tool_id": "glm_first_level",
                "source": "catalog",
                "score": 0.95,
                "description": "First-level GLM",
            }
        ],
        query_understanding={
            "entities": [
                {
                    "entity_type": "task",
                    "normalized_form": "motor",
                    "text": "motor",
                }
            ],
            "resolved_datasets": [
                {
                    "dataset_id": "ds000001",
                    "name": "Motor dataset",
                    "source_repo": "openneuro",
                    "bids_path": str(bids_root),
                    "resources": {
                        "bids_path": str(bids_root),
                        "derivatives": {"fmriprep": str(deriv_root)},
                        "available_derivatives": ["fmriprep"],
                        "analysis_goal": "fmri-glm",
                        "dataset_metadata": {"tasks": ["motor"]},
                    },
                }
            ],
            "existing_derivatives": [],
        },
    )

    with patch(
        "brain_researcher.services.agent.web_service.generate_tool_candidates",
        return_value=fake_bundle,
    ):
        client = _make_flask_test_client()
        resp = client.post(
            "/agent/studio/plan",
            json={
                "prompt": "build a first-level GLM for the motor task",
                "notebook_context": {},
            },
            content_type="application/json",
        )

    assert resp.status_code == 200
    data = resp.get_json()
    code_sources = [op["source"] for op in data["ops"] if op["cell_type"] == "code"]
    assert len(code_sources) == 1
    code = code_sources[0]
    assert str(bold_path) in code
    assert str(events_path) in code
    assert str(confounds_path) in code
    assert "data/sub-01/func/sub-01_task-motor_desc-preproc_bold.nii.gz" not in code


def test_studio_scaffold_registry_loads_expected_family_bindings():
    from brain_researcher.services.agent.studio_scaffold_registry import (
        load_studio_scaffold_registry,
    )

    registry = load_studio_scaffold_registry()

    assert registry["tool_to_family"]["glm_multiverse"] == "fitlins"
    assert registry["tool_to_family"]["spm12_vbm"] == "neurodesk"
    assert registry["tool_to_family"]["fsl_bet"] == "neurodesk"


# ---------------------------------------------------------------------------
# _build_notebook_context_dict helper tests
# ---------------------------------------------------------------------------


def test_build_notebook_context_dict_limits_cells_and_messages():
    from brain_researcher.services.orchestrator.studio_assistant_runtime import (
        _build_notebook_context_dict,
    )

    notebook = MagicMock()
    # 8 cells — helper should return last 5
    notebook.id = "nb_abc"
    notebook.path = "/home/user/analysis.ipynb"
    cell_mock = MagicMock()
    cell_mock.id = "c1"
    cell_mock.type.value = "code"
    cell_mock.source = "import nilearn"
    cell_mock.status.value = "idle"
    notebook.cells = [cell_mock] * 8

    msg = MagicMock()
    msg.role = "user"
    msg.content = "hello"
    msg.metadata = {}
    bootstrap_msg = MagicMock()
    bootstrap_msg.role = "assistant"
    bootstrap_msg.content = "intro"
    bootstrap_msg.metadata = {"source": "studio_bootstrap"}
    conversation = [bootstrap_msg] + [msg] * 6

    ctx = _build_notebook_context_dict(notebook, conversation)

    assert len(ctx["cells"]) == 5
    # bootstrap message excluded; last 3 user messages included
    assert len(ctx["recent_messages"]) == 3
    assert all(m["role"] == "user" for m in ctx["recent_messages"])
