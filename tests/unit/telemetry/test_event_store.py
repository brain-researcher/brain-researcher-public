import asyncio
from datetime import datetime, timedelta

import pytest

from brain_researcher.services.telemetry.models import EventType, ServiceType, PrivacyLevel, TelemetryEvent
from brain_researcher.services.telemetry.storage import TelemetryEventStore


def _make_event(event_id: str, ts: datetime) -> TelemetryEvent:
    return TelemetryEvent(
        id=event_id,
        event_type=EventType.FEATURE_INTERACTION,
        service=ServiceType.WEB_UI,
        timestamp=ts,
        feature_name="feedback_widget",
        action="submit",
        context={},
        parameters={},
        metadata={},
        privacy_level=PrivacyLevel.AGGREGATE_ONLY,
    )


@pytest.mark.asyncio
async def test_event_store_persists_and_filters(tmp_path):
    store = TelemetryEventStore(base_dir=tmp_path, retention_days=1)
    recent = _make_event("evt_recent", datetime.utcnow())
    stale = _make_event("evt_stale", datetime.utcnow() - timedelta(days=10))

    await store.append_events([stale, recent])

    loaded = store.load_recent_events()
    assert {evt.id for evt in loaded} == {"evt_recent"}

    recent_only = store.load_recent_events(max_age_days=1)
    assert [evt.id for evt in recent_only] == ["evt_recent"]

    # Appending another event should keep the file pruned to retention
    newest = _make_event("evt_new", datetime.utcnow())
    await store.append_events([newest])
    pruned = store.load_recent_events(max_age_days=1)
    assert set(evt.id for evt in pruned) == {"evt_recent", "evt_new"}
