"""Offline calibration and training helpers for realtime two-photon replay."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .realtime_twophoton_decoder import save_decoder_bundle, train_decoder_bundle
from .realtime_twophoton_runtime import load_replay_bundle


@dataclass(frozen=True)
class CalibrationBundlePaths:
    """Paths to runtime calibration artifacts produced offline."""

    roi_manifest: str
    reference_template: str
    decoder_bundle: str
    calibration_meta: str

    def to_dict(self) -> dict[str, str]:
        """Return calibration artifact paths as a plain dictionary."""

        return asdict(self)


def _compute_centroids(roi_masks: np.ndarray) -> np.ndarray:
    centroids = np.zeros((roi_masks.shape[0], 2), dtype=np.float32)
    for idx, mask in enumerate(roi_masks):
        ypix, xpix = np.nonzero(mask)
        if len(ypix) == 0:
            continue
        centroids[idx] = [float(np.mean(ypix)), float(np.mean(xpix))]
    return centroids


def _validate_training_inputs(
    traces: np.ndarray,
    labels: np.ndarray,
    roi_masks: np.ndarray,
    reference_template: np.ndarray,
    neuropil_masks: np.ndarray | None,
    expected_state_bins: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    traces = np.asarray(traces, dtype=np.float32)
    labels = np.asarray(labels, dtype=np.int32)
    roi_masks = np.asarray(roi_masks, dtype=bool)
    reference_template = np.asarray(reference_template, dtype=np.float32)

    if traces.ndim != 2:
        raise ValueError("traces must have shape [n_frames, n_rois]")
    if labels.ndim != 1:
        raise ValueError("labels must have shape [n_frames]")
    if roi_masks.ndim != 3:
        raise ValueError("roi_masks must have shape [n_rois, height, width]")
    if reference_template.ndim != 2:
        raise ValueError("reference_template must have shape [height, width]")
    if traces.shape[0] != labels.shape[0]:
        raise ValueError("traces and labels must have the same number of frames")
    if traces.shape[1] != roi_masks.shape[0]:
        raise ValueError("trace feature count must match number of ROI masks")
    if roi_masks.shape[1:] != reference_template.shape:
        raise ValueError("ROI mask image shape must match reference_template shape")

    if neuropil_masks is None:
        neuropil_masks = np.zeros_like(roi_masks, dtype=bool)
    else:
        neuropil_masks = np.asarray(neuropil_masks, dtype=bool)
        if neuropil_masks.shape != roi_masks.shape:
            raise ValueError("neuropil_masks must match roi_masks shape")

    unique_labels = np.unique(labels)
    if len(unique_labels) == 0:
        raise ValueError("labels must contain at least one class")
    if int(unique_labels.min()) < 0:
        raise ValueError("labels must be non-negative")
    if int(unique_labels.max()) >= expected_state_bins:
        raise ValueError(
            f"labels exceed expected coarse place bins: max={int(unique_labels.max())}, "
            f"expected_state_bins={expected_state_bins}"
        )

    return traces, labels, roi_masks, reference_template, neuropil_masks


def build_coarse_place_calibration_bundle(
    *,
    traces: np.ndarray,
    labels: np.ndarray,
    roi_masks: np.ndarray,
    reference_template: np.ndarray,
    output_dir: str | Path,
    neuropil_masks: np.ndarray | None = None,
    decode_window_frames: int = 4,
    decoder_type: str = "ridge",
    expected_state_bins: int = 8,
    state_name: str = "coarse_place_bin_8",
    source_name: str | None = None,
) -> CalibrationBundlePaths:
    """Build runtime calibration artifacts for coarse-place-bin decoding."""

    (
        traces,
        labels,
        roi_masks,
        reference_template,
        neuropil_masks,
    ) = _validate_training_inputs(
        traces=traces,
        labels=labels,
        roi_masks=roi_masks,
        reference_template=reference_template,
        neuropil_masks=neuropil_masks,
        expected_state_bins=expected_state_bins,
    )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    roi_manifest_path = out_dir / "roi_manifest.npz"
    reference_path = out_dir / "reference_template.npy"
    decoder_path = out_dir / "decoder.joblib"
    meta_path = out_dir / "calibration_meta.json"

    roi_ids = np.arange(roi_masks.shape[0], dtype=np.int32)
    centroids = _compute_centroids(roi_masks)
    np.savez_compressed(
        roi_manifest_path,
        roi_masks=roi_masks,
        neuropil_masks=neuropil_masks,
        roi_ids=roi_ids,
        centroids=centroids,
    )
    np.save(reference_path, reference_template.astype(np.float32))

    decoder_bundle = train_decoder_bundle(
        traces=traces,
        labels=labels,
        decode_window_frames=decode_window_frames,
        decoder_type=decoder_type,
    )
    save_decoder_bundle(decoder_bundle, decoder_path)

    unique_labels, label_counts = np.unique(labels, return_counts=True)
    label_histogram = {
        str(int(label)): int(count)
        for label, count in zip(unique_labels, label_counts, strict=True)
    }
    meta = {
        "schema_version": "realtime-twophoton-calibration-v1",
        "state_name": state_name,
        "decoder_type": decoder_type,
        "decode_window_frames": int(decode_window_frames),
        "n_state_bins": int(expected_state_bins),
        "n_frames": int(traces.shape[0]),
        "n_rois": int(roi_masks.shape[0]),
        "label_histogram": label_histogram,
        "source_name": source_name,
        "trace_source": "offline_calibration",
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return CalibrationBundlePaths(
        roi_manifest=str(roi_manifest_path),
        reference_template=str(reference_path),
        decoder_bundle=str(decoder_path),
        calibration_meta=str(meta_path),
    )


def build_coarse_place_calibration_bundle_from_replay(
    replay_source: str | Path | dict[str, Any],
    output_dir: str | Path,
    *,
    traces_key: str | None = None,
    labels_key: str = "labels",
    roi_masks_key: str = "roi_masks",
    reference_key: str = "reference_template",
    neuropil_key: str = "neuropil_masks",
    decode_window_frames: int = 4,
    decoder_type: str = "ridge",
    expected_state_bins: int = 8,
    state_name: str = "coarse_place_bin_8",
) -> CalibrationBundlePaths:
    """Build calibration artifacts from a replay bundle or saved `.npz` replay file."""

    if isinstance(replay_source, str | Path):
        bundle = load_replay_bundle(replay_source)
        source_name = str(replay_source)
    else:
        bundle = replay_source
        source_name = None

    if traces_key is None:
        for candidate in ("true_traces", "latent_traces", "traces", "df_f"):
            if candidate in bundle:
                traces_key = candidate
                break
    if traces_key is None or traces_key not in bundle:
        raise ValueError(
            "Replay bundle must provide training traces via one of "
            "'true_traces', 'latent_traces', 'traces', or 'df_f'"
        )
    if labels_key not in bundle:
        raise ValueError(f"Replay bundle is missing labels key: {labels_key}")
    if roi_masks_key not in bundle:
        raise ValueError(f"Replay bundle is missing ROI masks key: {roi_masks_key}")
    if reference_key not in bundle:
        raise ValueError(f"Replay bundle is missing reference key: {reference_key}")

    return build_coarse_place_calibration_bundle(
        traces=np.asarray(bundle[traces_key], dtype=np.float32),
        labels=np.asarray(bundle[labels_key], dtype=np.int32),
        roi_masks=np.asarray(bundle[roi_masks_key], dtype=bool),
        reference_template=np.asarray(bundle[reference_key], dtype=np.float32),
        neuropil_masks=(
            np.asarray(bundle[neuropil_key], dtype=bool)
            if neuropil_key in bundle
            else None
        ),
        output_dir=output_dir,
        decode_window_frames=decode_window_frames,
        decoder_type=decoder_type,
        expected_state_bins=expected_state_bins,
        state_name=state_name,
        source_name=source_name,
    )
