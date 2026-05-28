"""Unit tests for the realtime two-photon microscope callback adapter."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from brain_researcher.services.tools.realtime_twophoton_microscope_adapter import (
    MicroscopeCallbackMapping,
    MicroscopeFrameAdapter,
    MicroscopeFrameAdapterConfig,
    resolve_payload_field,
)


@dataclass
class _FakePublisher:
    start_payloads: list[dict | None]
    frame_payloads: list[dict]
    end_payloads: list[dict | None]
    closed: bool = False

    def send_start(self, metadata=None) -> None:
        self.start_payloads.append(metadata)

    def send_frame(self, frame, *, frame_id, timestamp_s=None, metadata=None) -> None:
        self.frame_payloads.append(
            {
                "frame": np.asarray(frame),
                "frame_id": frame_id,
                "timestamp_s": timestamp_s,
                "metadata": metadata,
            }
        )

    def send_end(self, metadata=None) -> None:
        self.end_payloads.append(metadata)

    def close(self) -> None:
        self.closed = True


def _publisher() -> _FakePublisher:
    return _FakePublisher(start_payloads=[], frame_payloads=[], end_payloads=[])


def test_microscope_frame_adapter_auto_starts_and_tracks_frame_ids():
    publisher = _publisher()
    adapter = MicroscopeFrameAdapter(
        MicroscopeFrameAdapterConfig(
            session_id="session-1",
            source_name="scanimage",
            frame_metadata={"channel": "green"},
        ),
        publisher=publisher,  # type: ignore[arg-type]
    )

    first_id = adapter.publish_frame(np.ones((4, 4), dtype=np.float32))
    second_id = adapter.publish_frame(
        np.ones((4, 4), dtype=np.float32) * 2,
        metadata={"plane": 0},
    )
    adapter.end_session({"status": "complete"})

    assert first_id == 0
    assert second_id == 1
    assert publisher.start_payloads == [
        {"session_id": "session-1", "source_name": "scanimage"}
    ]
    assert publisher.frame_payloads[0]["frame_id"] == 0
    assert publisher.frame_payloads[0]["timestamp_s"] is not None
    assert publisher.frame_payloads[0]["metadata"] == {"channel": "green"}
    assert publisher.frame_payloads[1]["metadata"] == {"channel": "green", "plane": 0}
    assert publisher.end_payloads == [{"status": "complete"}]


def test_microscope_frame_adapter_payload_callback_uses_extractors():
    publisher = _publisher()
    adapter = MicroscopeFrameAdapter(
        MicroscopeFrameAdapterConfig(auto_timestamp=False),
        publisher=publisher,  # type: ignore[arg-type]
    )
    callback = adapter.make_payload_callback(
        frame_extractor=lambda payload: payload["frame"],
        timestamp_extractor=lambda payload: payload["timestamp_s"],
        frame_id_extractor=lambda payload: payload["index"],
        metadata_extractor=lambda payload: {"laser_power": payload["laser_power"]},
    )

    callback(
        {
            "frame": np.arange(9, dtype=np.float32).reshape(3, 3),
            "timestamp_s": 12.5,
            "index": 7,
            "laser_power": 23.0,
        }
    )

    assert publisher.start_payloads == [None]
    assert publisher.frame_payloads[0]["frame_id"] == 7
    assert publisher.frame_payloads[0]["timestamp_s"] == 12.5
    assert publisher.frame_payloads[0]["metadata"] == {"laser_power": 23.0}


def test_microscope_frame_adapter_requires_start_when_auto_start_disabled():
    publisher = _publisher()
    adapter = MicroscopeFrameAdapter(
        MicroscopeFrameAdapterConfig(auto_start=False),
        publisher=publisher,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="start_session"):
        adapter.publish_frame(np.ones((2, 2), dtype=np.float32))

    adapter.start_session({"session_id": "manual"})
    adapter.publish_frame(np.ones((2, 2), dtype=np.float32), frame_id=3, timestamp_s=1.0)
    adapter.close()

    assert publisher.start_payloads == [{"session_id": "manual"}]
    assert publisher.frame_payloads[0]["frame_id"] == 3
    assert publisher.closed is True


def test_resolve_payload_field_supports_dict_attrs_and_fallbacks():
    @dataclass
    class _Inner:
        value: int

    @dataclass
    class _Payload:
        frame: np.ndarray
        nested: _Inner

    payload = {
        "image": np.ones((2, 2), dtype=np.float32),
        "meta": {"plane": 3},
    }
    obj = _Payload(frame=np.zeros((2, 2), dtype=np.float32), nested=_Inner(value=9))

    assert np.array_equal(resolve_payload_field(payload, "image"), payload["image"])
    assert resolve_payload_field(payload, ("missing", "meta.plane")) == 3
    assert resolve_payload_field(obj, "nested.value") == 9


def test_microscope_frame_adapter_field_callback_maps_dict_payload():
    publisher = _publisher()
    adapter = MicroscopeFrameAdapter(
        MicroscopeFrameAdapterConfig(auto_timestamp=False),
        publisher=publisher,  # type: ignore[arg-type]
    )
    callback = adapter.make_field_callback(
        frame_field=("frame", "image"),
        timestamp_field=("timestamp_s", "timestamp"),
        frame_id_field=("frame_id", "index"),
        metadata_fields={"plane": "meta.plane"},
        optional_metadata_fields={"channel": ("meta.channel", "channel")},
    )

    callback(
        {
            "image": np.arange(16, dtype=np.float32).reshape(4, 4),
            "timestamp": 1.25,
            "index": 11,
            "meta": {"plane": 2},
        }
    )

    assert publisher.start_payloads == [None]
    assert publisher.frame_payloads[0]["frame_id"] == 11
    assert publisher.frame_payloads[0]["timestamp_s"] == 1.25
    assert publisher.frame_payloads[0]["metadata"] == {"plane": 2}


def test_microscope_frame_adapter_mapped_callback_maps_object_payload():
    @dataclass
    class _Meta:
        plane: int
        channel: str

    @dataclass
    class _FrameEvent:
        pixels: np.ndarray
        t: float
        index: int
        meta: _Meta

    publisher = _publisher()
    adapter = MicroscopeFrameAdapter(
        MicroscopeFrameAdapterConfig(auto_timestamp=False),
        publisher=publisher,  # type: ignore[arg-type]
    )
    callback = adapter.make_mapped_callback(
        MicroscopeCallbackMapping(
            frame="pixels",
            timestamp_s="t",
            frame_id="index",
            metadata_fields={"plane": "meta.plane"},
            optional_metadata_fields={"channel": "meta.channel"},
        )
    )

    callback(
        _FrameEvent(
            pixels=np.full((3, 3), 5, dtype=np.float32),
            t=7.0,
            index=4,
            meta=_Meta(plane=1, channel="green"),
        )
    )

    assert publisher.frame_payloads[0]["frame_id"] == 4
    assert publisher.frame_payloads[0]["timestamp_s"] == 7.0
    assert publisher.frame_payloads[0]["metadata"] == {
        "plane": 1,
        "channel": "green",
    }
