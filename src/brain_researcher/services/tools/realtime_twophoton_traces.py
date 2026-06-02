"""Causal trace processing for ROI time series."""

from __future__ import annotations

from collections import deque

import numpy as np


class TraceProcessor:
    """Maintain causal baseline and dF/F estimates for ROI traces."""

    def __init__(self, n_rois: int, baseline_window_frames: int = 60):
        self.n_rois = int(n_rois)
        self.baseline_window_frames = int(max(baseline_window_frames, 5))
        self._buffer: deque[np.ndarray] = deque(maxlen=self.baseline_window_frames)

    def update(self, roi_values: np.ndarray, valid: bool = True) -> np.ndarray:
        values = np.asarray(roi_values, dtype=np.float32)
        if values.shape != (self.n_rois,):
            raise ValueError(
                f"Expected roi_values shape {(self.n_rois,)}, got {values.shape}"
            )
        if valid:
            self._buffer.append(values)
        elif not self._buffer:
            self._buffer.append(values)

        baseline_stack = np.stack(list(self._buffer), axis=0)
        baseline = np.percentile(baseline_stack, 20, axis=0)
        denominator = np.where(np.abs(baseline) < 1e-4, 1e-4, np.abs(baseline))
        return ((values - baseline) / denominator).astype(np.float32)
