"""Replay-first realtime two-photon runtime."""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .realtime_twophoton_acquisition import (
    generate_synthetic_replay_bundle,
    iter_bundle_frame_packets,
    iter_raw_socket_frame_packets,
)
from .realtime_twophoton_acquisition import (
    load_replay_bundle as acquisition_load_replay_bundle,
)
from .realtime_twophoton_acquisition import (
    save_replay_bundle as acquisition_save_replay_bundle,
)
from .realtime_twophoton_controller import build_controller
from .realtime_twophoton_decoder import (
    DecoderBundle,
    load_decoder_bundle,
    predict_decoder_bundle,
)
from .realtime_twophoton_motion import MotionEstimate, build_motion_corrector
from .realtime_twophoton_recorder import write_array, write_json, write_jsonl
from .realtime_twophoton_roi import extract_roi_values
from .realtime_twophoton_roi import load_roi_manifest as roi_load_roi_manifest
from .realtime_twophoton_schemas import ControlCommand, DecoderOutput, TracePacket
from .realtime_twophoton_traces import TraceProcessor


def _disk_masks_to_list(masks: np.ndarray) -> list[np.ndarray]:
    if masks.ndim != 3:
        raise ValueError("ROI masks must have shape [n_rois, height, width]")
    return [mask.astype(bool) for mask in masks]


def load_roi_manifest(path: str | Path) -> list[np.ndarray]:
    """Backward-compatible ROI manifest loader returning only ROI masks."""

    manifest = roi_load_roi_manifest(path)
    return _disk_masks_to_list(np.asarray(manifest["roi_masks"], dtype=bool))


def save_replay_bundle(bundle: dict[str, Any], output_path: str | Path) -> Path:
    """Backward-compatible replay bundle writer."""

    normalized = {key: np.asarray(value) for key, value in bundle.items()}
    return acquisition_save_replay_bundle(normalized, output_path)


def load_replay_bundle(path: str | Path) -> dict[str, Any]:
    """Backward-compatible replay bundle loader."""

    return acquisition_load_replay_bundle(path)


def build_simulated_bundle(
    n_frames: int = 120,
    frame_shape: tuple[int, int] = (64, 64),
    n_rois: int = 16,
    n_state_bins: int = 8,
    noise: float = 0.08,
    frame_rate_hz: float = 30.0,
) -> dict[str, Any]:
    """Generate a deterministic replay bundle for simulator mode."""

    synthetic = generate_synthetic_replay_bundle(
        n_frames=n_frames,
        image_shape=frame_shape,
        n_rois=n_rois,
        n_bins=n_state_bins,
        frame_rate_hz=frame_rate_hz,
        noise_std=noise,
        seed=7,
    )
    return {
        "frames": synthetic.frames.astype(np.float32),
        "labels": synthetic.labels.astype(np.int32),
        "roi_masks": synthetic.roi_masks.astype(bool),
        "neuropil_masks": synthetic.neuropil_masks.astype(bool),
        "reference_template": synthetic.reference_template.astype(np.float32),
        "timestamps_s": synthetic.timestamps_s.astype(np.float32),
        "latent_traces": synthetic.latent_traces.astype(np.float32),
        "true_traces": synthetic.latent_traces.astype(np.float32),
        "motion_shifts": np.zeros((n_frames, 2), dtype=np.float32),
    }


def _coerce_roi_bundle_from_replay(bundle: dict[str, Any]) -> dict[str, np.ndarray]:
    if "roi_masks" not in bundle:
        raise ValueError("ROI masks are required via roi_manifest or replay bundle.")
    roi_masks = np.asarray(bundle["roi_masks"], dtype=bool)
    neuropil_masks = np.asarray(
        bundle.get("neuropil_masks", np.zeros_like(roi_masks, dtype=bool)),
        dtype=bool,
    )
    return {
        "roi_masks": roi_masks,
        "neuropil_masks": neuropil_masks,
    }


def _load_calibration_meta(
    calibration_meta_path: str | None,
    decoder_path: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    resolved_path: Path | None = None
    if calibration_meta_path:
        resolved_path = Path(calibration_meta_path)
        if not resolved_path.exists():
            raise FileNotFoundError(f"Calibration metadata not found: {resolved_path}")
    elif decoder_path:
        candidate = Path(decoder_path).with_name("calibration_meta.json")
        if candidate.exists():
            resolved_path = candidate

    if resolved_path is None:
        return None, None
    return json.loads(resolved_path.read_text(encoding="utf-8")), str(resolved_path)


def _resolve_state_name(
    calibration_meta: dict[str, Any] | None,
    state_space: str | None,
) -> str:
    if calibration_meta and calibration_meta.get("state_name"):
        return str(calibration_meta["state_name"])
    if state_space:
        return str(state_space)
    return "coarse_place_bin"


class _ClosedLoopPolicy:
    """Stateful hysteresis and hold policy for closed-loop control."""

    def __init__(
        self,
        activation_threshold: float,
        release_threshold: float,
        hold_frames: int,
    ):
        self.activation_threshold = float(activation_threshold)
        self.release_threshold = min(
            float(release_threshold), float(activation_threshold)
        )
        self.hold_frames = max(0, int(hold_frames))
        self.active_state: int | None = None
        self.pending_state: int | None = None
        self.pending_count = 0
        self.unsupported_count = 0

    def _clear_pending(self) -> None:
        self.pending_state = None
        self.pending_count = 0

    def _arm_state(self, state_value: int) -> None:
        if self.pending_state == state_value:
            self.pending_count += 1
        else:
            self.pending_state = state_value
            self.pending_count = 1

    def _hold_limit(self) -> int:
        return 1 if self.hold_frames <= 0 else self.hold_frames

    def evaluate(
        self, decoder_output: DecoderOutput | None, motion_valid: bool
    ) -> dict[str, Any]:
        if decoder_output is None:
            if self.active_state is not None:
                self.unsupported_count += 1
                if self.unsupported_count <= self.hold_frames:
                    return {"emit": False, "reason": "holding_state"}
                self.active_state = None
                self.unsupported_count = 0
                self._clear_pending()
                return {"emit": False, "reason": "state_released"}
            return {"emit": False, "reason": "insufficient_history"}

        if not motion_valid:
            if self.active_state is not None:
                self.unsupported_count += 1
                if self.unsupported_count <= self.hold_frames:
                    return {"emit": False, "reason": "holding_state"}
                self.active_state = None
                self.unsupported_count = 0
                self._clear_pending()
            return {"emit": False, "reason": "low_motion_confidence"}

        state_value = int(decoder_output.state_value)
        confidence = float(decoder_output.confidence)
        hold_limit = self._hold_limit()

        if self.active_state is None:
            if confidence < self.activation_threshold:
                self._clear_pending()
                return {"emit": False, "reason": "decoder_threshold"}
            self._arm_state(state_value)
            if self.pending_count >= hold_limit:
                self.active_state = state_value
                self.unsupported_count = 0
                self._clear_pending()
                return {"emit": True, "reason": None}
            return {"emit": False, "reason": "arming_state"}

        if state_value == self.active_state:
            self._clear_pending()
            if confidence >= self.release_threshold:
                self.unsupported_count = 0
                return {"emit": False, "reason": "active_state_stable"}
            self.unsupported_count += 1
            if self.unsupported_count <= self.hold_frames:
                return {"emit": False, "reason": "holding_state"}
            self.active_state = None
            self.unsupported_count = 0
            return {"emit": False, "reason": "state_released"}

        if confidence < self.activation_threshold:
            self._clear_pending()
            self.unsupported_count += 1
            if self.unsupported_count <= self.hold_frames:
                return {"emit": False, "reason": "holding_state"}
            self.active_state = None
            self.unsupported_count = 0
            return {"emit": False, "reason": "decoder_threshold"}

        self._arm_state(state_value)
        self.unsupported_count += 1
        if self.pending_count >= hold_limit:
            self.active_state = state_value
            self.unsupported_count = 0
            self._clear_pending()
            return {"emit": True, "reason": None}
        return {"emit": False, "reason": "switch_hysteresis"}


class RealtimeTwoPhotonRunner:
    """Execute a replay-first realtime two-photon session."""

    def __init__(self, args):
        self.args = args

    def _load_inputs(self) -> dict[str, Any]:
        if self.args.data_source == "simulator":
            return build_simulated_bundle(
                n_frames=self.args.simulation_frames,
                frame_shape=tuple(self.args.frame_shape),
                n_rois=self.args.n_rois,
                n_state_bins=self.args.n_state_bins,
                noise=self.args.simulation_noise,
                frame_rate_hz=self.args.frame_rate_hz,
            )
        if self.args.data_source == "file_replay":
            if not self.args.input_file:
                raise ValueError(
                    "input_file is required when data_source='file_replay'"
                )
            return acquisition_load_replay_bundle(self.args.input_file)
        if self.args.data_source == "raw_socket":
            return {}
        raise ValueError(f"Unsupported data_source: {self.args.data_source}")

    def _load_reference_and_rois(
        self, bundle: dict[str, Any]
    ) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        if self.args.reference_template:
            reference = np.load(self.args.reference_template).astype(np.float32)
        elif "reference_template" in bundle:
            reference = np.asarray(bundle["reference_template"], dtype=np.float32)
        elif self.args.data_source == "raw_socket":
            raise ValueError(
                "reference_template is required when data_source='raw_socket'"
            )
        else:
            reference = np.asarray(bundle["frames"][0], dtype=np.float32)

        if self.args.roi_manifest:
            roi_bundle = roi_load_roi_manifest(self.args.roi_manifest)
        elif self.args.data_source == "raw_socket":
            raise ValueError("roi_manifest is required when data_source='raw_socket'")
        else:
            roi_bundle = _coerce_roi_bundle_from_replay(bundle)
        return reference, roi_bundle

    def _iter_packets(self, bundle: dict[str, Any]):
        if self.args.data_source == "raw_socket":
            return iter_raw_socket_frame_packets(
                host=self.args.stream_host,
                port=self.args.stream_port,
                timeout_s=self.args.stream_timeout_s,
                frame_rate_hz=self.args.frame_rate_hz,
                max_frames=self.args.stream_max_frames,
            )
        return iter_bundle_frame_packets(bundle, frame_rate_hz=self.args.frame_rate_hz)

    def run(self) -> tuple[dict[str, Any], dict[str, str]]:
        output_dir = Path(self.args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        bundle = self._load_inputs()
        reference, roi_bundle = self._load_reference_and_rois(bundle)
        roi_masks = np.asarray(roi_bundle["roi_masks"], dtype=bool)
        neuropil_masks = np.asarray(
            roi_bundle.get("neuropil_masks", np.zeros_like(roi_masks, dtype=bool)),
            dtype=bool,
        )
        labels = (
            np.asarray(bundle["labels"], dtype=np.int32) if "labels" in bundle else None
        )
        packet_iterator = self._iter_packets(bundle)
        calibration_meta, calibration_meta_path = _load_calibration_meta(
            calibration_meta_path=self.args.calibration_meta,
            decoder_path=self.args.decoder_path,
        )
        state_name = _resolve_state_name(calibration_meta, self.args.state_space)

        motion_corrector = build_motion_corrector(
            backend=self.args.motion_backend,
            reference=reference,
            confidence_threshold=self.args.motion_confidence_threshold * 10.0,
            max_translation_px=self.args.max_translation_px,
        )
        controller = build_controller(
            backend=self.args.controller_backend,
            host=self.args.controller_host,
            port=self.args.controller_port,
            target=self.args.controller_target,
        )
        trace_processor = TraceProcessor(
            n_rois=int(roi_masks.shape[0]),
            baseline_window_frames=self.args.baseline_window_frames,
        )
        closed_loop_policy = _ClosedLoopPolicy(
            activation_threshold=self.args.decoder_threshold,
            release_threshold=self.args.decoder_release_threshold,
            hold_frames=self.args.state_hold_frames,
        )
        decoder_bundle: DecoderBundle | None = None
        if self.args.mode in {"shadow", "closed_loop"}:
            if not self.args.decoder_path:
                raise ValueError(
                    "decoder_path is required for shadow and closed_loop modes"
                )
            decoder_bundle = load_decoder_bundle(self.args.decoder_path)

        trace_history: list[np.ndarray] = []
        motion_history: list[dict[str, float | bool]] = []
        trace_packets: list[dict[str, Any]] = []
        decoder_packets: list[dict[str, Any]] = []
        controller_packets: list[dict[str, Any]] = []
        frame_metrics: list[dict[str, float]] = []
        predictions: list[int] = []
        prediction_conf: list[float] = []
        observed_labels: list[int] = []
        gated_frames = 0
        last_emit_frame = -999999
        registered_frames: list[np.ndarray] | None = (
            [] if self.args.save_frames else None
        )

        try:
            for frame_index, packet in enumerate(packet_iterator):
                stage_start = time.perf_counter()
                frame_id = int(packet.frame_id)
                if packet.image.shape != reference.shape:
                    raise ValueError(
                        "Incoming frame shape does not match reference_template: "
                        f"{packet.image.shape} != {reference.shape}"
                    )
                predictions.append(-1)
                prediction_conf.append(0.0)
                if labels is not None:
                    observed_labels.append(
                        int(labels[frame_index]) if frame_index < len(labels) else -1
                    )
                if self.args.motion_correction:
                    corrected, motion = motion_corrector.correct(packet.image)
                else:
                    corrected = packet.image
                    motion = MotionEstimate(0.0, 0.0, 1.0, True, 0.0)

                valid = bool(motion.valid or not self.args.drop_on_low_confidence)
                neuropil_for_frame = (
                    neuropil_masks if self.args.neuropil_correction else None
                )
                fluorescence = extract_roi_values(
                    corrected,
                    roi_masks=roi_masks,
                    neuropil_masks=neuropil_for_frame,
                )
                df_f = trace_processor.update(fluorescence, valid=valid)
                trace_history.append(df_f)
                if registered_frames is not None:
                    registered_frames.append(np.asarray(corrected, dtype=np.float32))

                trace_packet = TracePacket(
                    frame_id=frame_id,
                    timestamp_s=float(packet.timestamp_s),
                    fluorescence=fluorescence.tolist(),
                    df_f=df_f.tolist(),
                    valid=valid,
                )
                trace_packets.append(asdict(trace_packet))
                motion_history.append(asdict(motion))

                decoder_output = None
                if (
                    decoder_bundle is not None
                    and len(trace_history) >= decoder_bundle.decode_window_frames
                ):
                    history = np.asarray(trace_history, dtype=np.float32)
                    predicted, confidence = predict_decoder_bundle(
                        decoder_bundle, history
                    )
                    predictions[-1] = int(predicted[-1])
                    prediction_conf[-1] = float(confidence[-1])
                    decoder_output = DecoderOutput(
                        frame_id=frame_id,
                        timestamp_s=float(packet.timestamp_s),
                        state_name=state_name,
                        state_value=int(predicted[-1]),
                        confidence=float(confidence[-1]),
                        valid=valid,
                    )
                    decoder_packets.append(asdict(decoder_output))

                if self.args.mode == "closed_loop":
                    decision = closed_loop_policy.evaluate(
                        decoder_output=decoder_output,
                        motion_valid=valid,
                    )
                    if decision["emit"]:
                        if frame_id - last_emit_frame < self.args.refractory_frames:
                            gated_frames += 1
                            controller_packets.append(
                                asdict(
                                    ControlCommand(
                                        frame_id=frame_id,
                                        timestamp_s=float(packet.timestamp_s),
                                        command_type="state_update",
                                        payload={},
                                        gated=True,
                                        reason="refractory",
                                    )
                                )
                            )
                        else:
                            assert decoder_output is not None
                            payload = {
                                "frame_id": frame_id,
                                "timestamp_s": float(packet.timestamp_s),
                                "state_name": decoder_output.state_name,
                                "state_value": decoder_output.state_value,
                                "confidence": decoder_output.confidence,
                            }
                            event = controller.emit(payload)
                            controller_packets.append(
                                asdict(
                                    ControlCommand(
                                        frame_id=frame_id,
                                        timestamp_s=float(packet.timestamp_s),
                                        command_type="state_update",
                                        payload=payload,
                                        gated=False,
                                        reason=None,
                                    )
                                )
                            )
                            if event.emitted:
                                last_emit_frame = frame_id
                    else:
                        gated_frames += 1
                        controller_packets.append(
                            asdict(
                                ControlCommand(
                                    frame_id=frame_id,
                                    timestamp_s=float(packet.timestamp_s),
                                    command_type="state_update",
                                    payload={},
                                    gated=True,
                                    reason=str(decision["reason"]),
                                )
                            )
                        )

                frame_metrics.append(
                    {
                        "frame_id": float(frame_id),
                        "processing_ms": float(
                            (time.perf_counter() - stage_start) * 1000.0
                        ),
                    }
                )
        finally:
            controller.close()

        predictions_array = np.asarray(predictions, dtype=int)
        prediction_conf_array = np.asarray(prediction_conf, dtype=np.float32)
        labels_array = (
            np.asarray(observed_labels, dtype=np.int32) if observed_labels else None
        )
        valid_predictions = predictions_array >= 0
        accuracy = None
        if labels_array is not None and np.any(valid_predictions):
            accuracy = float(
                np.mean(
                    predictions_array[valid_predictions]
                    == labels_array[valid_predictions]
                )
            )

        motion_conf = np.asarray(
            [item["confidence"] for item in motion_history], dtype=np.float32
        )
        abs_shift = np.asarray(
            [
                np.hypot(float(item["dx_px"]), float(item["dy_px"]))
                for item in motion_history
            ],
            dtype=np.float32,
        )
        gated_reason_histogram = dict(
            Counter(
                item["reason"]
                for item in controller_packets
                if item.get("gated") and item.get("reason")
            )
        )
        emitted_state_histogram = dict(
            Counter(
                item["payload"].get("state_value")
                for item in controller_packets
                if not item.get("gated") and item.get("payload")
            )
        )
        summary = {
            "mode": self.args.mode,
            "data_source": self.args.data_source,
            "motion_backend_requested": self.args.motion_backend,
            "state_space": state_name,
            "calibration_meta_path": calibration_meta_path,
            "neuropil_correction": bool(self.args.neuropil_correction),
            "closed_loop_policy": {
                "decoder_threshold": float(self.args.decoder_threshold),
                "decoder_release_threshold": float(self.args.decoder_release_threshold),
                "state_hold_frames": int(self.args.state_hold_frames),
                "refractory_frames": int(self.args.refractory_frames),
            },
            "stream_config": (
                {
                    "stream_host": self.args.stream_host,
                    "stream_port": int(self.args.stream_port),
                    "stream_timeout_s": float(self.args.stream_timeout_s),
                    "stream_max_frames": (
                        int(self.args.stream_max_frames)
                        if self.args.stream_max_frames is not None
                        else None
                    ),
                }
                if self.args.data_source == "raw_socket"
                else None
            ),
            "n_frames_processed": int(len(trace_history)),
            "n_rois": int(roi_masks.shape[0]),
            "decode_window_frames": int(self.args.decode_window_frames),
            "motion_summary": {
                "mean_confidence": (
                    float(np.mean(motion_conf)) if len(motion_conf) else 0.0
                ),
                "min_confidence": (
                    float(np.min(motion_conf)) if len(motion_conf) else 0.0
                ),
                "low_confidence_frames": int(
                    np.sum(motion_conf < self.args.motion_confidence_threshold)
                ),
                "mean_abs_shift_px": (
                    float(np.mean(abs_shift)) if len(abs_shift) else 0.0
                ),
            },
            "decode_summary": {
                "state_name": state_name,
                "n_predictions": int(np.sum(valid_predictions)),
                "mean_confidence": (
                    float(np.mean(prediction_conf_array[valid_predictions]))
                    if np.any(valid_predictions)
                    else 0.0
                ),
                "accuracy": accuracy,
                "state_histogram": (
                    dict(Counter(predictions_array[valid_predictions].tolist()))
                    if np.any(valid_predictions)
                    else {}
                ),
            },
            "controller_summary": {
                "backend": self.args.controller_backend,
                "n_events_recorded": int(len(controller_packets)),
                "n_gated_frames": int(gated_frames),
                "n_emitted_events": int(
                    sum(1 for item in controller_packets if not item["gated"])
                ),
                "gated_reason_histogram": gated_reason_histogram,
                "emitted_state_histogram": emitted_state_histogram,
            },
            "latency_summary": {
                "mean_processing_ms": (
                    float(np.mean([m["processing_ms"] for m in frame_metrics]))
                    if frame_metrics
                    else 0.0
                ),
                "max_processing_ms": (
                    float(np.max([m["processing_ms"] for m in frame_metrics]))
                    if frame_metrics
                    else 0.0
                ),
            },
        }

        outputs: dict[str, str] = {}
        if self.args.save_artifacts:
            outputs["summary"] = write_json(output_dir / "summary.json", summary)
            outputs["motion"] = write_jsonl(output_dir / "motion.jsonl", motion_history)
            outputs["decoder"] = write_jsonl(
                output_dir / "decoder.jsonl", decoder_packets
            )
            outputs["controller"] = write_jsonl(
                output_dir / "controller.jsonl", controller_packets
            )
            outputs["traces"] = write_array(
                output_dir / "trace_df_f.npy",
                np.asarray(trace_history, dtype=np.float32),
            )
            outputs["timing"] = write_jsonl(output_dir / "timing.jsonl", frame_metrics)
            if registered_frames is not None:
                outputs["frames"] = write_array(
                    output_dir / "registered_frames.npy",
                    np.asarray(registered_frames, dtype=np.float32),
                )

        return summary, outputs
