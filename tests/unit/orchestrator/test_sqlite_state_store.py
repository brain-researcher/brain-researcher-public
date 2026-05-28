from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from brain_researcher.services.orchestrator.sqlite_state_store import SqliteStateStore


@pytest.mark.asyncio
async def test_sqlite_state_store_threads_and_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(db_path=db_path)
    await store.initialize()

    now = datetime.utcnow()
    thread_id = "thread_test"
    thread = {
        "thread_id": thread_id,
        "title": "Test thread",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "message_count": 0,
        "context": {},
        "metadata": {},
        "scenario_id": None,
    }
    await store.upsert_thread(thread_id=thread_id, thread=thread)

    msg1 = {
        "id": "msg_1",
        "thread_id": thread_id,
        "role": "user",
        "content": "hi",
        "timestamp": now.isoformat(),
        "attachments": [],
        "metadata": {},
    }
    await store.append_message(thread_id=thread_id, message_id=msg1["id"], message=msg1)

    msg2_ts = now + timedelta(seconds=1)
    msg2 = {
        "id": "msg_2",
        "thread_id": thread_id,
        "role": "assistant",
        "content": "hello",
        "timestamp": msg2_ts.isoformat(),
        "attachments": [],
        "metadata": {},
    }
    await store.append_message(thread_id=thread_id, message_id=msg2["id"], message=msg2)

    stored_thread = await store.get_thread(thread_id)
    assert stored_thread is not None
    assert stored_thread["title"] == "Test thread"

    messages = await store.list_messages(thread_id=thread_id, limit=10)
    assert [m["id"] for m in messages] == ["msg_1", "msg_2"]

    messages_before = await store.list_messages(
        thread_id=thread_id, limit=10, before_message_id="msg_2"
    )
    assert [m["id"] for m in messages_before] == ["msg_1"]


@pytest.mark.asyncio
async def test_sqlite_state_store_notifications(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(db_path=db_path)
    await store.initialize()

    now = datetime.utcnow()
    notif = {
        "id": "notif_1",
        "user_id": "user_a",
        "type": "job_complete",
        "priority": "normal",
        "title": "Done",
        "message": "Job finished",
        "data": {},
        "read": False,
        "created_at": now.isoformat(),
        "read_at": None,
        "expires_at": None,
        "action_url": None,
        "action_text": None,
    }
    await store.upsert_notification(notif)

    assert await store.count_notifications("user_a") == 1
    assert await store.count_unread_notifications("user_a") == 1

    listed = await store.list_notifications(user_id="user_a", limit=10)
    assert [n["id"] for n in listed] == ["notif_1"]

    updated = await store.mark_notifications_read("user_a", ["notif_1"])
    assert updated == 1
    assert await store.count_unread_notifications("user_a") == 0

    unread = await store.list_notifications(user_id="user_a", limit=10, unread_only=True)
    assert unread == []


@pytest.mark.asyncio
async def test_sqlite_state_store_demo_share_tokens(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(db_path=db_path)
    await store.initialize()

    token = "share_tok_test"
    expires_at = datetime.utcnow() + timedelta(hours=1)
    await store.store_demo_share(
        share_token=token,
        demo_id="glm_motor",
        is_public=True,
        expires_at=expires_at,
        created_by="user_demo",
    )

    resolved = await store.resolve_demo_share(share_token=token)
    assert resolved is not None
    assert resolved["demo_id"] == "glm_motor"
    assert resolved["is_public"] is True

    expired = await store.resolve_demo_share(
        share_token=token, now=expires_at + timedelta(seconds=1)
    )
    assert expired is None


@pytest.mark.asyncio
async def test_sqlite_state_store_analysis_share_tokens(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(db_path=db_path)
    await store.initialize()

    token = "analysis_share_tok_test"
    expires_at = datetime.utcnow() + timedelta(hours=1)
    await store.store_analysis_share(
        share_token=token,
        analysis_id="job_abc123",
        share_level="summary",
        expires_at=expires_at,
        created_by="user_a",
    )

    resolved = await store.resolve_analysis_share(share_token=token)
    assert resolved is not None
    assert resolved["analysis_id"] == "job_abc123"
    assert resolved["share_level"] == "summary"
    assert resolved["created_by"] == "user_a"

    revoked = await store.revoke_analysis_share(share_token=token)
    assert revoked is True
    assert await store.resolve_analysis_share(share_token=token) is None

    expired = await store.resolve_analysis_share(
        share_token=token, now=expires_at + timedelta(seconds=1)
    )
    assert expired is None


@pytest.mark.asyncio
async def test_sqlite_state_store_monitors_events_and_chat_bridges(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite"
    store = SqliteStateStore(db_path=db_path)
    await store.initialize()

    now = datetime.utcnow()
    monitor = {
        "id": "mon_test123",
        "owner_user_id": "user_demo",
        "thread_id": "thread_demo",
        "source_type": "local_process",
        "source_ref": "12345",
        "display_name": "demo process",
        "status": "running",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "log_sources": {"stdout": "/tmp/demo.log"},
        "control_capabilities": ["status", "tail_logs", "cancel"],
        "delivery_targets": [],
        "chat_bindings": [],
        "audit_policy": {},
        "metadata": {},
    }
    await store.upsert_monitor(monitor)

    loaded_monitor = await store.get_monitor("mon_test123")
    assert loaded_monitor is not None
    assert loaded_monitor["display_name"] == "demo process"

    listed_monitors = await store.list_monitors(owner_user_id="user_demo", limit=10)
    assert [item["id"] for item in listed_monitors] == ["mon_test123"]

    event_id = await store.append_monitor_event(
        monitor_id="mon_test123",
        event_type="monitor.created",
        event={"detail": "created"},
    )
    assert event_id >= 1

    events = await store.list_monitor_events(monitor_id="mon_test123", limit=10)
    assert len(events) == 1
    assert events[0]["event_type"] == "monitor.created"
    assert events[0]["payload"]["detail"] == "created"

    bridge = {
        "id": "bridge_test123",
        "thread_id": "thread_demo",
        "platform": "slack",
        "bridge_key": "channel:C123:thread:1710000000.000100",
        "monitor_id": "mon_test123",
        "config": {"channel_id": "C123", "thread_ts": "1710000000.000100"},
        "metadata": {},
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    await store.upsert_chat_bridge(bridge)

    loaded_bridge = await store.get_chat_bridge("bridge_test123")
    assert loaded_bridge is not None
    assert loaded_bridge["platform"] == "slack"

    external_bridge = await store.get_chat_bridge_by_external(
        platform="slack",
        bridge_key="channel:C123:thread:1710000000.000100",
    )
    assert external_bridge is not None
    assert external_bridge["id"] == "bridge_test123"

    listed_bridges = await store.list_chat_bridges(thread_id="thread_demo", limit=10)
    assert [item["id"] for item in listed_bridges] == ["bridge_test123"]
