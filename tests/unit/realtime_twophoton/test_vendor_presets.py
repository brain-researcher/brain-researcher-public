"""Tests for realtime two-photon vendor callback presets."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from brain_researcher.services.tools.realtime_twophoton_microscope_adapter import (
    MicroscopeFrameAdapter,
    MicroscopeFrameAdapterConfig,
)
from brain_researcher.services.tools.realtime_twophoton_vendors import (
    SCANIMAGE_LIKE_PRESET,
    available_vendor_presets,
    build_vendor_callback,
)


@dataclass
class _FakePublisher:
    start_payloads: list[dict | None]
    frame_payloads: list[dict]
    end_payloads: list[dict | None]

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
        return None


def _publisher() -> _FakePublisher:
    return _FakePublisher(start_payloads=[], frame_payloads=[], end_payloads=[])


def test_available_vendor_presets_contains_expected_names():
    presets = available_vendor_presets()
    assert "generic_frame_payload" in presets
    assert "scanimage_like" in presets
    assert "prairie_view_like" in presets
    assert "thorimage_like" in presets


def test_build_vendor_callback_uses_scanimage_like_preset():
    publisher = _publisher()
    adapter = MicroscopeFrameAdapter(
        MicroscopeFrameAdapterConfig(auto_timestamp=False),
        publisher=publisher,  # type: ignore[arg-type]
    )
    callback = build_vendor_callback(adapter, SCANIMAGE_LIKE_PRESET)

    callback(
        {
            "image": np.ones((4, 4), dtype=np.float32),
            "frameNumber": 9,
            "timestamp": 2.5,
            "channel_name": "green",
            "z": 0,
        }
    )

    assert publisher.frame_payloads[0]["frame_id"] == 9
    assert publisher.frame_payloads[0]["timestamp_s"] == 2.5
    assert publisher.frame_payloads[0]["metadata"] == {
        "plane": 0,
        "channel": "green",
    }
