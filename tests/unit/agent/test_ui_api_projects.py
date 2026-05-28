"""Tests for project CRUD endpoints and run project validation in ui_api."""

import pytest


@pytest.fixture(autouse=True)
def enable_dev_mode(monkeypatch):
    """Enable dev auth bypass for API tests."""
    monkeypatch.setenv("DISABLE_AUTH_FOR_DEV", "1")


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset service singletons between tests to avoid shared state."""
    yield
    try:
        import brain_researcher.services.agent.job_service as js

        js._job_service = None
    except (ImportError, AttributeError):
        pass
    try:
        import brain_researcher.services.agent.ui_api as ui_api

        ui_api._file_storage = None
        ui_api._resumable_storage = None
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def app(monkeypatch):
    """Create Flask app with isolated in-memory JobStore."""
    from flask import Flask

    from brain_researcher.services.orchestrator.memory_job_store import MemoryJobStore
    import brain_researcher.services.orchestrator.job_store_factory as job_store_factory
    from brain_researcher.services.agent.ui_api import ui_api

    store = MemoryJobStore()
    monkeypatch.setattr(job_store_factory, "get_initialized_job_store", lambda: store)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(ui_api, url_prefix="/api")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_create_run_with_nonexistent_project_returns_400(client):
    response = client.post(
        "/api/runs",
        json={"plan": {"steps": []}, "project_id": "does-not-exist"},
        content_type="application/json",
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data["error"] == "invalid_project"
    assert "does not exist" in data["detail"]


def test_create_run_with_existing_project_succeeds(client):
    create_project = client.post(
        "/api/projects",
        json={"project_id": "proj-1", "name": "Project One"},
        content_type="application/json",
    )
    assert create_project.status_code == 201

    create_run = client.post(
        "/api/runs",
        json={"plan": {"steps": []}, "project_id": "proj-1"},
        content_type="application/json",
    )

    assert create_run.status_code == 200
    run = create_run.get_json()
    assert run["status"] == "queued"
    assert run["project_id"] == "proj-1"
    assert "run_id" in run


def test_projects_crud_endpoints(client):
    list_before = client.get("/api/projects")
    assert list_before.status_code == 200
    list_before_data = list_before.get_json()
    assert any(p["project_id"] == "default" for p in list_before_data["projects"])

    create_response = client.post(
        "/api/projects",
        json={
            "project_id": "proj-crud",
            "name": "CRUD Project",
            "description": "Initial description",
        },
        content_type="application/json",
    )
    assert create_response.status_code == 201
    created = create_response.get_json()
    assert created["project_id"] == "proj-crud"
    assert created["name"] == "CRUD Project"

    detail_response = client.get("/api/projects/proj-crud")
    assert detail_response.status_code == 200
    detail = detail_response.get_json()
    assert detail["project_id"] == "proj-crud"

    update_response = client.patch(
        "/api/projects/proj-crud",
        json={"name": "Renamed Project", "description": "Updated"},
        content_type="application/json",
    )
    assert update_response.status_code == 200
    updated = update_response.get_json()
    assert updated["name"] == "Renamed Project"
    assert updated["description"] == "Updated"

    delete_response = client.delete("/api/projects/proj-crud")
    assert delete_response.status_code == 200
    deleted = delete_response.get_json()
    assert deleted["ok"] is True

    detail_after_delete = client.get("/api/projects/proj-crud")
    assert detail_after_delete.status_code == 404
