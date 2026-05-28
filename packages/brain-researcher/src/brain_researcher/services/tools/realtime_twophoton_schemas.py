"""Schemas for replay-first realtime two-photon processing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RealtimeTwoPhotonArgs(BaseModel):
    """Arguments for replay-first realtime two-photon processing."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data_source: str = Field(
        default="simulator",
        description="Data source: 'simulator', 'file_replay', or 'raw_socket'",
    )
    input_file: str | None = Field(
        default=None, description="Path to replay .npz bundle for file_replay mode"
    )
    stream_host: str = Field(
        default="127.0.0.1",
        description="Host/interface to bind for raw_socket streaming input",
    )
    stream_port: int = Field(
        default=7788, description="TCP port to bind for raw_socket streaming input"
    )
    stream_timeout_s: float = Field(
        default=5.0,
        description="Timeout in seconds for raw_socket accept/read operations",
    )
    stream_max_frames: int | None = Field(
        default=None,
        description="Optional maximum number of raw_socket frames to consume before stopping",
    )
    mode: str = Field(
        default="monitoring",
        description="Mode: 'monitoring', 'shadow', or 'closed_loop'",
    )

    frame_rate_hz: float = Field(default=30.0, description="Frame rate in Hz")
    frame_shape: list[int] = Field(
        default=[64, 64], description="Frame shape [height, width] for simulator mode"
    )
    simulation_frames: int = Field(
        default=120, description="Number of frames to generate in simulator mode"
    )
    n_rois: int = Field(default=16, description="Number of ROIs for simulator mode")
    n_state_bins: int = Field(default=8, description="Number of coarse place bins")
    simulation_noise: float = Field(
        default=0.08, description="Observation noise for simulator mode"
    )

    reference_template: str | None = Field(
        default=None, description="Path to .npy reference template"
    )
    roi_manifest: str | None = Field(
        default=None, description="Path to .npz ROI manifest with masks"
    )
    decoder_path: str | None = Field(
        default=None, description="Path to trained decoder bundle"
    )
    calibration_meta: str | None = Field(
        default=None,
        description="Optional calibration metadata JSON for state-space resolution",
    )
    state_space: str | None = Field(
        default=None, description="Optional decoder state-space override"
    )

    motion_correction: bool = Field(default=True, description="Apply motion correction")
    motion_backend: str = Field(
        default="auto",
        description="Motion backend: 'auto', 'phase_correlation', or 'caiman'",
    )
    motion_confidence_threshold: float = Field(
        default=0.65, description="Confidence threshold for a valid registered frame"
    )
    max_translation_px: float = Field(
        default=12.0, description="Maximum allowed translation magnitude in pixels"
    )
    drop_on_low_confidence: bool = Field(
        default=True, description="Freeze feedback when motion confidence is low"
    )

    baseline_window_frames: int = Field(
        default=30, description="Window size for causal fluorescence baseline"
    )
    neuropil_correction: bool = Field(
        default=False,
        description="Apply neuropil subtraction when ROI manifest includes neuropil masks",
    )
    decode_window_frames: int = Field(
        default=4, description="Number of recent frames used for causal decoding"
    )
    decoder_threshold: float = Field(
        default=0.5, description="Confidence threshold for emitting a decoder state"
    )
    decoder_release_threshold: float = Field(
        default=0.35,
        description="Lower confidence threshold for keeping an already active state latched",
    )
    state_hold_frames: int = Field(
        default=2,
        description="Consecutive frames required to arm or switch states, and grace frames for holding an active state",
    )

    controller_backend: str = Field(
        default="udp", description="Controller backend: 'udp', 'websocket', or 'none'"
    )
    controller_host: str = Field(default="127.0.0.1", description="UDP controller host")
    controller_port: int = Field(default=7777, description="UDP controller port")
    controller_target: str | None = Field(
        default=None,
        description="WebSocket controller target URL for controller_backend='websocket'",
    )
    refractory_frames: int = Field(
        default=2, description="Minimum frames between emitted commands"
    )

    output_dir: str = Field(
        default="realtime_twophoton_output", description="Output directory"
    )
    save_artifacts: bool = Field(
        default=True, description="Save runtime artifacts to disk"
    )
    save_frames: bool = Field(
        default=False,
        description="Save registered frames as an artifact when supported by the runtime",
    )


@dataclass
class FramePacket:
    """One incoming frame and timestamp."""

    frame_id: int
    timestamp_s: float
    image: Any


@dataclass
class TracePacket:
    """Per-frame extracted fluorescence and dF/F values."""

    frame_id: int
    timestamp_s: float
    fluorescence: Any
    df_f: Any
    valid: bool


@dataclass
class DecoderOutput:
    """Per-frame decoder state."""

    frame_id: int
    timestamp_s: float
    state_name: str
    state_value: int
    confidence: float
    valid: bool


@dataclass
class ControlCommand:
    """Outgoing control command."""

    frame_id: int
    timestamp_s: float
    command_type: str
    payload: dict[str, Any]
    gated: bool
    reason: str | None = None
