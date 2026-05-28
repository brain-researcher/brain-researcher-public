from datetime import datetime

from brain_researcher.services.orchestrator.feedback_repository import FeedbackRepository, FeedbackRecord


def test_feedback_repository_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("FEEDBACK_DATA_DIR", str(tmp_path))
    repo = FeedbackRepository()

    record = FeedbackRecord(
        id="feedback_test",
        rating=4,
        category="ui-ux",
        title="Great flow",
        description="Loved the refreshed chat workspace",
        emoji_rating="happy",
        user_id="tester",
        session_id="session-123",
        user_agent="pytest",
        url="http://localhost/chat",
        screenshot_url=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        metadata={"context": {"route": "/chat"}},
    )

    repo.save_submission(record)

    stored = repo.get_submission(record.id)
    assert stored is not None
    assert stored.title == record.title
    assert stored.metadata["context"]["route"] == "/chat"

    screenshot_id = repo.save_screenshot(
        feedback_id=record.id,
        filename="test.png",
        content=b"fake-bytes",
        content_type="image/png",
    )
    resolved = repo.resolve_screenshot(screenshot_id)
    assert resolved is not None
    assert resolved["path"].exists()
