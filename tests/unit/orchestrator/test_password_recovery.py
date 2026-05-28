import json

from brain_researcher.services.orchestrator.password_recovery import (
    repair_missing_password_hashes,
)


class _FakeRedis:
    def __init__(self, data):
        self._data = dict(data)

    def scan_iter(self, match=None):
        for key in sorted(self._data):
            if match is None or key.startswith(match.replace("*", "")):
                yield key

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value


def test_repair_restores_seed_user_with_missing_provider(monkeypatch):
    user = {
        "id": "user_demo",
        "username": "demo",
        "email": "demo@brain-researcher.ai",
        "auth_provider": None,
        "hashed_password": None,
        "preferences": {},
    }
    fake = _FakeRedis({"user:user_demo": json.dumps(user)})
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.password_recovery.redis.Redis.from_url",
        lambda *args, **kwargs: fake,
    )

    report = repair_missing_password_hashes(
        "redis://unused",
        dry_run=False,
        mark_reset_required=True,
        restore_seed_users=True,
    )

    repaired = json.loads(fake.get("user:user_demo"))
    assert report["normalized_provider"] == 1
    assert report["restored_seed_users"] == 1
    assert repaired["auth_provider"] == "password"
    assert repaired["hashed_password"]


def test_repair_normalizes_provider_without_changing_existing_hash(monkeypatch):
    user = {
        "id": "user_demo",
        "username": "demo",
        "email": "demo@brain-researcher.ai",
        "auth_provider": None,
        "hashed_password": "$2b$12$existinghashplaceholder",
        "preferences": {},
    }
    fake = _FakeRedis({"user:user_demo": json.dumps(user)})
    monkeypatch.setattr(
        "brain_researcher.services.orchestrator.password_recovery.redis.Redis.from_url",
        lambda *args, **kwargs: fake,
    )

    report = repair_missing_password_hashes(
        "redis://unused",
        dry_run=False,
        mark_reset_required=False,
        restore_seed_users=False,
    )

    repaired = json.loads(fake.get("user:user_demo"))
    assert report["normalized_provider"] == 1
    assert report["missing_hash"] == 0
    assert repaired["auth_provider"] == "password"
    assert repaired["hashed_password"] == "$2b$12$existinghashplaceholder"
