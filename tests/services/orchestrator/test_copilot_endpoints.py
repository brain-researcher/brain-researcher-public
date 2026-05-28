import pytest
from fastapi.testclient import TestClient

from brain_researcher.services.orchestrator import copilot_endpoints
from brain_researcher.services.orchestrator.copilot_endpoints import router


@pytest.fixture
def client():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_copilot_suggest_respects_function_filter(client: TestClient):
    # Query matches both GLM and connectivity heuristics, but we set function=glm
    payload = {
        "query": "run glm connectivity",
        "function": "glm",
        "domain": "fmri",
        "k": 5,
    }
    res = client.post("/copilot/suggest", json=payload)
    assert res.status_code == 200
    data = res.json()
    names = [s["name"] for s in data.get("suggestions", [])]
    methods = data.get("methods", [])
    # GLM suggestions should remain
    assert any("hrf" in n or "smoothing" in n for n in names)
    # Connectivity suggestion should be filtered out
    assert not any("parcellation" in n for n in names)
    # Methods are intent-catalog based and should prefer GLM intents
    assert any("glm" in m.get("intent_id", "") for m in methods)
    assert not any("connectivity" in m.get("intent_id", "") for m in methods)


def test_copilot_suggest_allows_connectivity_when_function_matches(client: TestClient):
    payload = {
        "query": "resting-state connectivity",
        "function": "connectivity",
        "domain": "fmri",
        "k": 5,
    }
    res = client.post("/copilot/suggest", json=payload)
    assert res.status_code == 200
    data = res.json()
    names = [s["name"] for s in data.get("suggestions", [])]
    methods = data.get("methods", [])
    assert any("parcellation" in n for n in names)
    assert any("connectivity" in m.get("intent_id", "") for m in methods)


def test_copilot_autocomplete_uses_orchestrator_owned_assistant(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    class StubAssistant:
        def autocomplete_parameters(self, tool_name, partial_params, dataset_metadata):
            assert tool_name == "spm-glm"
            assert partial_params == {"threshold": 0.001}
            assert dataset_metadata == {"repetition_time": 2.0}
            return {"threshold": 0.001, "TR": 2.0}

    monkeypatch.setattr(copilot_endpoints, "_get_copilot_assistant", lambda: StubAssistant())

    res = client.post(
        "/copilot/autocomplete",
        json={
            "tool": "spm-glm",
            "params": {"threshold": 0.001},
            "metadata": {"repetition_time": 2.0},
        },
    )
    assert res.status_code == 200
    assert res.json() == {
        "tool": "spm-glm",
        "completed": {"threshold": 0.001, "TR": 2.0},
    }


def test_copilot_learn_uses_orchestrator_owned_assistant(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    recorded: dict[str, object] = {}

    class StubAssistant:
        def learn_selection(self, tool_name, accepted_params=None):
            recorded["tool"] = tool_name
            recorded["params"] = accepted_params

    monkeypatch.setattr(copilot_endpoints, "_get_copilot_assistant", lambda: StubAssistant())

    res = client.post(
        "/copilot/learn",
        json={"tool": "spm-glm", "params": {"TR": 2.0}},
    )
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "tool": "spm-glm"}
    assert recorded == {"tool": "spm-glm", "params": {"TR": 2.0}}
