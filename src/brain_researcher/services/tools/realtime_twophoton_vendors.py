"""Best-effort vendor callback presets for realtime two-photon acquisition.

These presets are intended as starting points for common microscope SDK payload
shapes. They are deliberately labeled ``*_LIKE`` because the exact field names
depend on the acquisition wrapper used in a given lab.
"""

from __future__ import annotations

from dataclasses import dataclass

from .realtime_twophoton_microscope_adapter import (
    MicroscopeCallbackMapping,
    MicroscopeFrameAdapter,
)


@dataclass(frozen=True)
class VendorShimPreset:
    """Declarative preset for building a microscope callback."""

    name: str
    mapping: MicroscopeCallbackMapping
    notes: str = ""


GENERIC_FRAME_PAYLOAD_PRESET = VendorShimPreset(
    name="generic_frame_payload",
    mapping=MicroscopeCallbackMapping(
        frame=("frame", "image", "pixels"),
        timestamp_s=("timestamp_s", "timestamp", "frame_timestamp", "time_s"),
        frame_id=("frame_id", "index", "frame_index", "frame_number"),
        optional_metadata_fields={
            "plane": ("plane", "plane_index", "z_index"),
            "channel": ("channel", "channel_name", "channel_index"),
        },
    ),
    notes="Fallback preset for generic dict/object frame callbacks.",
)


SCANIMAGE_LIKE_PRESET = VendorShimPreset(
    name="scanimage_like",
    mapping=MicroscopeCallbackMapping(
        frame=("frame", "image", "pixels", "data.image"),
        timestamp_s=("timestamp_s", "timestamp", "frame_timestamp_s", "epoch_time_s"),
        frame_id=("frame_id", "frameNumber", "frame_number", "frame_index"),
        optional_metadata_fields={
            "plane": ("plane", "z", "z_index"),
            "channel": ("channel", "channel_name", "channelSave"),
        },
    ),
    notes="Best-effort starting point for ScanImage-style callback payloads.",
)


PRAIRIE_VIEW_LIKE_PRESET = VendorShimPreset(
    name="prairie_view_like",
    mapping=MicroscopeCallbackMapping(
        frame=("image", "frame", "pixels", "frame.image"),
        timestamp_s=("timestamp_s", "timestamp", "frame_time_s"),
        frame_id=("frame_id", "frame_index", "frameIndex"),
        optional_metadata_fields={
            "plane": ("plane", "plane_index", "current_plane"),
            "channel": ("channel", "channel_index", "channel_name"),
        },
    ),
    notes="Best-effort starting point for Prairie View-style payloads.",
)


THORIMAGE_LIKE_PRESET = VendorShimPreset(
    name="thorimage_like",
    mapping=MicroscopeCallbackMapping(
        frame=("frame", "image", "pixels", "buffer"),
        timestamp_s=("timestamp_s", "timestamp", "hardware_timestamp_s"),
        frame_id=("frame_id", "frameNumber", "frame_number", "index"),
        optional_metadata_fields={
            "plane": ("plane", "z_index", "plane_index"),
            "channel": ("channel", "channel_name", "channel"),
        },
    ),
    notes="Best-effort starting point for ThorImage-style payloads.",
)


def available_vendor_presets() -> dict[str, VendorShimPreset]:
    """Return all built-in vendor shim presets keyed by name."""

    presets = (
        GENERIC_FRAME_PAYLOAD_PRESET,
        SCANIMAGE_LIKE_PRESET,
        PRAIRIE_VIEW_LIKE_PRESET,
        THORIMAGE_LIKE_PRESET,
    )
    return {preset.name: preset for preset in presets}


def build_vendor_callback(
    adapter: MicroscopeFrameAdapter,
    preset: VendorShimPreset | str,
):
    """Build a callback from a built-in vendor preset."""

    if isinstance(preset, str):
        presets = available_vendor_presets()
        if preset not in presets:
            raise KeyError(
                f"Unknown vendor preset: {preset!r}. "
                f"Available presets: {sorted(presets)}"
            )
        preset = presets[preset]
    return adapter.make_mapped_callback(preset.mapping)
