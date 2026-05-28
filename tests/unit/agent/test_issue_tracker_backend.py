from brain_researcher.services.agent.issue_tracker import (
    LinearIssueTrackerBackend,
    create_issue_tracker_backend,
)


def test_create_issue_tracker_backend_disabled(monkeypatch):
    monkeypatch.setenv("BR_PLAN_TRACKER_PROVIDER", "none")
    monkeypatch.delenv("BR_PLAN_TRACKER_LINEAR_TEAM_ID", raising=False)
    monkeypatch.delenv("BR_PLAN_TRACKER_LINEAR_API_KEY", raising=False)
    monkeypatch.delenv("LINEAR_TEAM_ID", raising=False)
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)

    backend = create_issue_tracker_backend()
    assert backend is None


def test_create_issue_tracker_backend_auto_legacy_linear_env(monkeypatch):
    monkeypatch.setenv("BR_PLAN_TRACKER_PROVIDER", "auto")
    monkeypatch.delenv("BR_PLAN_TRACKER_LINEAR_TEAM_ID", raising=False)
    monkeypatch.delenv("BR_PLAN_TRACKER_LINEAR_API_KEY", raising=False)
    monkeypatch.setenv("LINEAR_TEAM_ID", "team_123")
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_key_1234567890")

    backend = create_issue_tracker_backend()
    assert isinstance(backend, LinearIssueTrackerBackend)
    assert backend.provider == "linear"
    assert backend.available is True


def test_create_issue_tracker_backend_linear_requires_api_key(monkeypatch):
    monkeypatch.setenv("BR_PLAN_TRACKER_PROVIDER", "linear")
    monkeypatch.setenv("BR_PLAN_TRACKER_LINEAR_TEAM_ID", "team_abc")
    monkeypatch.delenv("BR_PLAN_TRACKER_LINEAR_API_KEY", raising=False)
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)

    backend = create_issue_tracker_backend()
    assert backend is None
