"""Tests for the replay-first realtime two-photon tool."""

from __future__ import annotations

import json
import queue
import socket
import threading
from pathlib import Path

import numpy as np
from websockets.sync.server import serve

from brain_researcher.services.tools import realtime_twophoton_runtime as runtime_module
from brain_researcher.services.tools.realtime_twophoton_calibration import (
    build_coarse_place_calibration_bundle_from_replay,
)
from brain_researcher.services.tools.realtime_twophoton_publisher import (
    publish_frames_to_raw_socket,
)
from brain_researcher.services.tools.realtime_twophoton_runtime import (
    build_simulated_bundle,
    save_replay_bundle,
)
from brain_researcher.services.tools.realtime_twophoton_tool import (
    RealtimeTwoPhotonTool,
)
from brain_researcher.services.tools.tool_registry import ToolRegistry


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _publish_raw_socket_frames(
    *,
    host: str,
    port: int,
    frames: np.ndarray,
    timestamps_s: np.ndarray | None = None,
) -> None:
    publish_frames_to_raw_socket(
        frames,
        host=host,
        port=port,
        timestamps_s=timestamps_s,
        connect_timeout_s=3.0,
        write_timeout_s=1.0,
        connect_retry_interval_s=0.05,
    )


def _run_tool_in_thread(result_queue: queue.Queue, **kwargs) -> threading.Thread:
    def _target() -> None:
        tool = RealtimeTwoPhotonTool()
        result_queue.put(tool._run(**kwargs))

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread


def test_registry_includes_realtime_twophoton_tool():
    registry = ToolRegistry(light_mode=True)
    assert registry.get_tool("realtime_twophoton") is not None


def test_realtime_twophoton_simulator_monitoring(tmp_path: Path):
    tool = RealtimeTwoPhotonTool()
    output_dir = tmp_path / "simulator_monitoring"

    result = tool._run(
        data_source="simulator",
        mode="monitoring",
        frame_rate_hz=20.0,
        frame_shape=[32, 32],
        simulation_frames=40,
        n_rois=10,
        n_state_bins=8,
        controller_backend="none",
        output_dir=str(output_dir),
    )

    assert result.status == "success"
    assert result.data is not None
    summary = result.data["summary"]
    assert summary["n_frames_processed"] == 40
    assert summary["n_rois"] == 10
    assert summary["motion_summary"]["mean_confidence"] >= 0.0
    assert result.metadata is not None
    summary_path = Path(result.metadata["output_files"]["summary"])
    assert summary_path.exists()
    saved_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert saved_summary["mode"] == "monitoring"


def test_realtime_twophoton_file_replay_shadow(tmp_path: Path):
    bundle = build_simulated_bundle(
        n_frames=96,
        frame_shape=(32, 32),
        n_rois=12,
        n_state_bins=8,
        noise=0.04,
        frame_rate_hz=20.0,
    )
    replay_path = save_replay_bundle(bundle, tmp_path / "replay_bundle.npz")
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=replay_path,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=4,
    )

    tool = RealtimeTwoPhotonTool()
    result = tool._run(
        data_source="file_replay",
        input_file=str(replay_path),
        mode="shadow",
        reference_template=calibration.reference_template,
        roi_manifest=calibration.roi_manifest,
        decoder_path=calibration.decoder_bundle,
        controller_backend="none",
        output_dir=str(tmp_path / "shadow_output"),
    )

    assert result.status == "success"
    summary = result.data["summary"]
    assert summary["state_space"] == "coarse_place_bin_8"
    assert summary["decode_summary"]["n_predictions"] > 0
    assert summary["decode_summary"]["accuracy"] is not None
    assert summary["decode_summary"]["accuracy"] > 0.3


def test_realtime_twophoton_closed_loop_websocket_and_save_frames(tmp_path: Path):
    bundle = build_simulated_bundle(
        n_frames=96,
        frame_shape=(32, 32),
        n_rois=12,
        n_state_bins=8,
        noise=0.04,
        frame_rate_hz=20.0,
    )
    replay_path = save_replay_bundle(bundle, tmp_path / "replay_bundle.npz")
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=replay_path,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=4,
    )

    port = _free_port()
    received: queue.Queue[str] = queue.Queue()
    ready = threading.Event()
    server_holder: dict[str, object] = {}

    def _serve() -> None:
        def _handler(connection) -> None:
            while True:
                try:
                    message = connection.recv()
                except Exception:
                    break
                if message is None:
                    break
                received.put(message)

        with serve(_handler, "127.0.0.1", port) as server:
            server_holder["server"] = server
            ready.set()
            server.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0)

    tool = RealtimeTwoPhotonTool()
    result = tool._run(
        data_source="file_replay",
        input_file=str(replay_path),
        mode="closed_loop",
        reference_template=calibration.reference_template,
        roi_manifest=calibration.roi_manifest,
        decoder_path=calibration.decoder_bundle,
        controller_backend="websocket",
        controller_target=f"ws://127.0.0.1:{port}",
        decoder_threshold=0.2,
        refractory_frames=1,
        save_frames=True,
        output_dir=str(tmp_path / "closed_loop_output"),
    )

    server_holder["server"].shutdown()  # type: ignore[union-attr]
    thread.join(timeout=2.0)

    assert result.status == "success"
    summary = result.data["summary"]
    assert summary["state_space"] == "coarse_place_bin_8"
    assert summary["controller_summary"]["backend"] == "websocket"
    assert summary["controller_summary"]["n_emitted_events"] > 0
    assert result.metadata is not None
    frames_path = Path(result.metadata["output_files"]["frames"])
    assert frames_path.exists()

    payload = json.loads(received.get_nowait())
    assert payload["state_name"] == "coarse_place_bin_8"


def test_realtime_twophoton_raw_socket_shadow(tmp_path: Path):
    bundle = build_simulated_bundle(
        n_frames=48,
        frame_shape=(32, 32),
        n_rois=12,
        n_state_bins=8,
        noise=0.04,
        frame_rate_hz=20.0,
    )
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=bundle,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=4,
    )

    port = _free_port()
    result_queue: queue.Queue = queue.Queue()
    thread = _run_tool_in_thread(
        result_queue,
        data_source="raw_socket",
        mode="shadow",
        stream_host="127.0.0.1",
        stream_port=port,
        frame_rate_hz=20.0,
        reference_template=calibration.reference_template,
        roi_manifest=calibration.roi_manifest,
        decoder_path=calibration.decoder_bundle,
        controller_backend="none",
        output_dir=str(tmp_path / "raw_socket_shadow_output"),
    )

    _publish_raw_socket_frames(
        host="127.0.0.1",
        port=port,
        frames=np.asarray(bundle["frames"], dtype=np.float32),
        timestamps_s=np.asarray(bundle["timestamps_s"], dtype=np.float32),
    )
    thread.join(timeout=5.0)

    assert not thread.is_alive()
    result = result_queue.get_nowait()
    assert result.status == "success"
    summary = result.data["summary"]
    assert summary["data_source"] == "raw_socket"
    assert summary["stream_config"]["stream_port"] == port
    assert summary["n_frames_processed"] == 48
    assert summary["decode_summary"]["n_predictions"] > 0
    assert summary["decode_summary"]["accuracy"] is None


def test_realtime_twophoton_raw_socket_closed_loop_websocket(tmp_path: Path):
    bundle = build_simulated_bundle(
        n_frames=64,
        frame_shape=(32, 32),
        n_rois=12,
        n_state_bins=8,
        noise=0.04,
        frame_rate_hz=20.0,
    )
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=bundle,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=4,
    )

    stream_port = _free_port()
    controller_port = _free_port()
    received: queue.Queue[str] = queue.Queue()
    ready = threading.Event()
    server_holder: dict[str, object] = {}

    def _serve() -> None:
        def _handler(connection) -> None:
            while True:
                try:
                    message = connection.recv()
                except Exception:
                    break
                if message is None:
                    break
                received.put(message)

        with serve(_handler, "127.0.0.1", controller_port) as server:
            server_holder["server"] = server
            ready.set()
            server.serve_forever()

    server_thread = threading.Thread(target=_serve, daemon=True)
    server_thread.start()
    assert ready.wait(timeout=2.0)

    result_queue: queue.Queue = queue.Queue()
    tool_thread = _run_tool_in_thread(
        result_queue,
        data_source="raw_socket",
        mode="closed_loop",
        stream_host="127.0.0.1",
        stream_port=stream_port,
        frame_rate_hz=20.0,
        reference_template=calibration.reference_template,
        roi_manifest=calibration.roi_manifest,
        decoder_path=calibration.decoder_bundle,
        controller_backend="websocket",
        controller_target=f"ws://127.0.0.1:{controller_port}",
        decoder_threshold=0.2,
        refractory_frames=1,
        output_dir=str(tmp_path / "raw_socket_closed_loop_output"),
    )

    _publish_raw_socket_frames(
        host="127.0.0.1",
        port=stream_port,
        frames=np.asarray(bundle["frames"], dtype=np.float32),
        timestamps_s=np.asarray(bundle["timestamps_s"], dtype=np.float32),
    )
    tool_thread.join(timeout=5.0)
    server_holder["server"].shutdown()  # type: ignore[union-attr]
    server_thread.join(timeout=2.0)

    assert not tool_thread.is_alive()
    result = result_queue.get_nowait()
    assert result.status == "success"
    summary = result.data["summary"]
    assert summary["data_source"] == "raw_socket"
    assert summary["controller_summary"]["backend"] == "websocket"
    assert summary["controller_summary"]["n_emitted_events"] > 0

    payload = json.loads(received.get_nowait())
    assert payload["state_name"] == "coarse_place_bin_8"


def test_closed_loop_holds_active_state_on_short_confidence_drop(
    tmp_path: Path, monkeypatch
):
    bundle = build_simulated_bundle(
        n_frames=8,
        frame_shape=(24, 24),
        n_rois=8,
        n_state_bins=8,
        noise=0.02,
        frame_rate_hz=20.0,
    )
    replay_path = save_replay_bundle(bundle, tmp_path / "replay_bundle.npz")
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=replay_path,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=1,
    )

    sequence = [
        (1, 0.92),
        (1, 0.88),
        (1, 0.45),
        (1, 0.34),
        (1, 0.83),
        (1, 0.86),
        (1, 0.82),
        (1, 0.81),
    ]

    def _fake_predict(_decoder_bundle, traces):
        predictions = np.zeros(len(traces), dtype=int)
        confidence = np.zeros(len(traces), dtype=np.float32)
        for idx in range(len(traces)):
            state_value, conf = sequence[min(idx, len(sequence) - 1)]
            predictions[idx] = state_value
            confidence[idx] = conf
        return predictions, confidence

    monkeypatch.setattr(runtime_module, "predict_decoder_bundle", _fake_predict)

    tool = RealtimeTwoPhotonTool()
    result = tool._run(
        data_source="file_replay",
        input_file=str(replay_path),
        mode="closed_loop",
        reference_template=calibration.reference_template,
        roi_manifest=calibration.roi_manifest,
        decoder_path=calibration.decoder_bundle,
        controller_backend="none",
        motion_correction=False,
        decoder_threshold=0.7,
        decoder_release_threshold=0.4,
        state_hold_frames=2,
        refractory_frames=1,
        output_dir=str(tmp_path / "closed_loop_hold_output"),
    )

    assert result.status == "success"
    assert result.metadata is not None
    summary = result.data["summary"]
    assert summary["controller_summary"]["n_emitted_events"] == 1

    controller_records = [
        json.loads(line)
        for line in Path(result.metadata["output_files"]["controller"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    reasons = {record["reason"] for record in controller_records if record["gated"]}
    assert "arming_state" in reasons
    assert "holding_state" in reasons


def test_closed_loop_switch_requires_consecutive_frames(tmp_path: Path, monkeypatch):
    bundle = build_simulated_bundle(
        n_frames=8,
        frame_shape=(24, 24),
        n_rois=8,
        n_state_bins=8,
        noise=0.02,
        frame_rate_hz=20.0,
    )
    replay_path = save_replay_bundle(bundle, tmp_path / "replay_bundle.npz")
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=replay_path,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=1,
    )

    sequence = [
        (1, 0.91),
        (1, 0.89),
        (2, 0.93),
        (1, 0.87),
        (2, 0.94),
        (2, 0.95),
        (2, 0.96),
        (2, 0.96),
    ]

    def _fake_predict(_decoder_bundle, traces):
        predictions = np.zeros(len(traces), dtype=int)
        confidence = np.zeros(len(traces), dtype=np.float32)
        for idx in range(len(traces)):
            state_value, conf = sequence[min(idx, len(sequence) - 1)]
            predictions[idx] = state_value
            confidence[idx] = conf
        return predictions, confidence

    monkeypatch.setattr(runtime_module, "predict_decoder_bundle", _fake_predict)

    tool = RealtimeTwoPhotonTool()
    result = tool._run(
        data_source="file_replay",
        input_file=str(replay_path),
        mode="closed_loop",
        reference_template=calibration.reference_template,
        roi_manifest=calibration.roi_manifest,
        decoder_path=calibration.decoder_bundle,
        controller_backend="none",
        motion_correction=False,
        decoder_threshold=0.7,
        decoder_release_threshold=0.4,
        state_hold_frames=2,
        refractory_frames=1,
        output_dir=str(tmp_path / "closed_loop_switch_output"),
    )

    assert result.status == "success"
    assert result.metadata is not None
    controller_records = [
        json.loads(line)
        for line in Path(result.metadata["output_files"]["controller"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    emitted = [record for record in controller_records if not record["gated"]]
    emitted_states = [record["payload"]["state_value"] for record in emitted]
    reasons = {record["reason"] for record in controller_records if record["gated"]}

    assert emitted_states == [1, 2]
    assert "switch_hysteresis" in reasons


def test_closed_loop_stress_low_motion_confidence_blocks_emission(
    tmp_path: Path, monkeypatch
):
    bundle = build_simulated_bundle(
        n_frames=10,
        frame_shape=(24, 24),
        n_rois=8,
        n_state_bins=8,
        noise=0.02,
        frame_rate_hz=20.0,
    )
    replay_path = save_replay_bundle(bundle, tmp_path / "replay_bundle.npz")
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=replay_path,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=1,
    )

    def _fake_predict(_decoder_bundle, traces):
        predictions = np.full(len(traces), 3, dtype=int)
        confidence = np.full(len(traces), 0.95, dtype=np.float32)
        return predictions, confidence

    class _AlwaysInvalidMotion:
        def correct(self, image):
            return image, runtime_module.MotionEstimate(0.0, 0.0, 0.1, False, 0.0)

    monkeypatch.setattr(runtime_module, "predict_decoder_bundle", _fake_predict)
    monkeypatch.setattr(
        runtime_module,
        "build_motion_corrector",
        lambda **_kwargs: _AlwaysInvalidMotion(),
    )

    tool = RealtimeTwoPhotonTool()
    result = tool._run(
        data_source="file_replay",
        input_file=str(replay_path),
        mode="closed_loop",
        reference_template=calibration.reference_template,
        roi_manifest=calibration.roi_manifest,
        decoder_path=calibration.decoder_bundle,
        controller_backend="none",
        motion_correction=True,
        decoder_threshold=0.7,
        decoder_release_threshold=0.4,
        state_hold_frames=2,
        refractory_frames=1,
        output_dir=str(tmp_path / "closed_loop_low_motion_output"),
    )

    assert result.status == "success"
    summary = result.data["summary"]
    assert summary["controller_summary"]["n_emitted_events"] == 0
    assert summary["controller_summary"]["n_gated_frames"] == 10
    assert (
        summary["controller_summary"]["gated_reason_histogram"]["low_motion_confidence"]
        == 10
    )


def test_closed_loop_stress_noisy_decoder_reports_reason_mix(
    tmp_path: Path, monkeypatch
):
    bundle = build_simulated_bundle(
        n_frames=10,
        frame_shape=(24, 24),
        n_rois=8,
        n_state_bins=8,
        noise=0.02,
        frame_rate_hz=20.0,
    )
    replay_path = save_replay_bundle(bundle, tmp_path / "replay_bundle.npz")
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=replay_path,
        output_dir=tmp_path / "calibration_bundle",
        decode_window_frames=1,
    )

    sequence = [
        (1, 0.92),
        (1, 0.93),
        (2, 0.86),
        (1, 0.25),
        (2, 0.87),
        (3, 0.86),
        (2, 0.88),
        (2, 0.89),
        (3, 0.72),
        (2, 0.68),
    ]

    def _fake_predict(_decoder_bundle, traces):
        predictions = np.zeros(len(traces), dtype=int)
        confidence = np.zeros(len(traces), dtype=np.float32)
        for idx in range(len(traces)):
            state_value, conf = sequence[min(idx, len(sequence) - 1)]
            predictions[idx] = state_value
            confidence[idx] = conf
        return predictions, confidence

    monkeypatch.setattr(runtime_module, "predict_decoder_bundle", _fake_predict)

    tool = RealtimeTwoPhotonTool()
    result = tool._run(
        data_source="file_replay",
        input_file=str(replay_path),
        mode="closed_loop",
        reference_template=calibration.reference_template,
        roi_manifest=calibration.roi_manifest,
        decoder_path=calibration.decoder_bundle,
        controller_backend="none",
        motion_correction=False,
        decoder_threshold=0.7,
        decoder_release_threshold=0.4,
        state_hold_frames=2,
        refractory_frames=1,
        output_dir=str(tmp_path / "closed_loop_noisy_decoder_output"),
    )

    assert result.status == "success"
    summary = result.data["summary"]
    controller_summary = summary["controller_summary"]
    assert controller_summary["n_emitted_events"] == 2
    assert controller_summary["emitted_state_histogram"] == {1: 1, 2: 1}
    assert controller_summary["gated_reason_histogram"]["switch_hysteresis"] >= 3
    assert controller_summary["gated_reason_histogram"]["holding_state"] >= 1
