"""SpikeGLX / Kilosort helper utilities for IBL tool wrappers.

Pure helper functions and constants for probe-directory resolution,
SpikeGLX recording normalization, sorter materialization, and active-window
selection. Extracted from ibl_tools to keep that file tractable.

All public names are re-exported from ibl_tools for backward compatibility.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import numpy as np

_KILOSORT_DEPENDENCY_MODULES = ("spikeinterface.full",)
_SPIKEGLX_AP_BIN_GLOB = "*imec.ap*.cbin"
_SPIKEGLX_AP_META_GLOB = "*imec.ap*.meta"


def _infer_probe_label_from_dir(probe_dir: Path, probe_label: str | None) -> str:
    if probe_label:
        return probe_label
    if probe_dir.name.startswith("probe"):
        return probe_dir.name
    return "probe00"


def _resolve_probe_dir(data_dir: str | None, probe_label: str | None) -> Path | None:
    if not data_dir:
        return None
    root = Path(data_dir).expanduser()
    if not root.exists():
        return None
    if root.is_file():
        return root.parent
    if list(root.glob(_SPIKEGLX_AP_BIN_GLOB)) and list(
        root.glob(_SPIKEGLX_AP_META_GLOB)
    ):
        return root
    if probe_label:
        candidate = root / probe_label
        if candidate.exists():
            return candidate
    # Lazy import to avoid circular dependency with ibl_tools
    from brain_researcher.services.tools.ibl_tools import _sorted_child_dirs

    candidates = [
        child
        for child in _sorted_child_dirs(root)
        if list(child.glob(_SPIKEGLX_AP_BIN_GLOB))
        and list(child.glob(_SPIKEGLX_AP_META_GLOB))
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _build_spikeglx_normalized_view(
    probe_dir: Path, output_dir: Path
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cbin_candidates = sorted(probe_dir.glob(_SPIKEGLX_AP_BIN_GLOB))
    meta_candidates = sorted(probe_dir.glob(_SPIKEGLX_AP_META_GLOB))
    ch_candidates = sorted(probe_dir.glob("*imec.ap*.ch"))
    if not cbin_candidates or not meta_candidates or not ch_candidates:
        raise FileNotFoundError(f"Missing AP cbin/meta/ch files under {probe_dir}")

    normalized_base = "_spikeglx_ephysData_g0_t0.imec.ap"
    cbin_path = output_dir / f"{normalized_base}.cbin"
    meta_path = output_dir / f"{normalized_base}.meta"
    ch_path = output_dir / f"{normalized_base}.ch"

    for path in (cbin_path, meta_path, ch_path):
        if path.exists() or path.is_symlink():
            path.unlink()

    cbin_path.symlink_to(cbin_candidates[0])
    meta_path.symlink_to(meta_candidates[0])
    ch_path.symlink_to(ch_candidates[0])
    return {
        "normalized_input_dir": str(output_dir),
        "normalized_cbin_path": str(cbin_path),
        "normalized_meta_path": str(meta_path),
        "normalized_ch_path": str(ch_path),
        "source_cbin_path": str(cbin_candidates[0]),
        "source_meta_path": str(meta_candidates[0]),
        "source_ch_path": str(ch_candidates[0]),
    }


def _load_spikeglx_recording(
    probe_dir: Path,
    *,
    normalized_dir: Path,
):
    from unittest.mock import patch

    import probeinterface
    import spikeinterface.full as si

    normalized = _build_spikeglx_normalized_view(probe_dir, normalized_dir)
    original_read_spikeglx = probeinterface.read_spikeglx

    def _patched_read_spikeglx(meta_file):
        probe = original_read_spikeglx(meta_file)
        if "probe_type" not in probe.annotations:
            model_name = str(probe.annotations.get("model_name", ""))
            part_number = str(probe.annotations.get("part_number", ""))
            if "NP1" in part_number or "1.0" in model_name:
                probe.annotate(probe_type=0)
            else:
                probe.annotate(probe_type=21)
        return probe

    with patch.object(probeinterface, "read_spikeglx", _patched_read_spikeglx):
        recording = si.read_cbin_ibl(
            cbin_file_path=Path(normalized["normalized_cbin_path"]),
            stream_name="ap",
        )
    if hasattr(recording, "_kwargs") and isinstance(recording._kwargs, dict):
        recording._kwargs["folder_path"] = normalized["normalized_input_dir"]
        recording._kwargs["cbin_file_path"] = normalized["normalized_cbin_path"]
    original_duration_s = float(
        recording.get_num_frames() / recording.get_sampling_frequency()
    )
    return recording, normalized, original_duration_s


def _materialize_sorter_recording(recording: Any, *, output_dir: Path):
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    return recording.save(
        folder=output_dir,
        format="binary",
        overwrite=True,
        verbose=False,
        n_jobs=1,
        chunk_duration="1s",
        progress_bar=False,
    )


def _suggest_active_window_start(
    session_path: str | None,
    probe_label: str | None,
    max_duration_s: float | None,
    *,
    max_time_s: float | None = None,
) -> float | None:
    if not session_path or not probe_label or not max_duration_s or max_duration_s <= 0:
        return None
    probe_dir = Path(session_path) / "alf" / probe_label
    if not probe_dir.exists():
        return None
    spike_time_files = sorted(probe_dir.glob("spikes.times*.npy"))
    if not spike_time_files:
        return None
    spike_times = np.load(spike_time_files[0], allow_pickle=True)
    if len(spike_times) == 0:
        return None
    if max_time_s is not None:
        spike_times = np.asarray(spike_times, dtype=float)
        spike_times = spike_times[spike_times <= max_time_s]
        if len(spike_times) == 0:
            return None
    max_time = float(np.max(spike_times))
    bins = np.arange(0.0, max_time + max_duration_s, max_duration_s)
    if len(bins) < 2:
        return 0.0
    counts, edges = np.histogram(spike_times, bins=bins)
    if len(counts) == 0:
        return 0.0
    best_idx = int(np.argmax(counts))
    return float(edges[best_idx])
