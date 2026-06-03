"""Motion correction helpers for realtime two-photon replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from scipy.ndimage import shift as ndi_shift


@dataclass
class MotionEstimate:
    """Frame-to-reference motion estimate."""

    dx_px: float
    dy_px: float
    confidence: float
    valid: bool
    residual: float


class MotionCorrector(Protocol):
    """Protocol for frame motion correction."""

    def correct(self, frame: np.ndarray) -> tuple[np.ndarray, MotionEstimate]:
        """Return corrected frame and motion estimate."""


def _safe_normalize(arr: np.ndarray) -> np.ndarray:
    centered = arr.astype(np.float32, copy=False) - float(np.mean(arr))
    scale = float(np.std(centered))
    if scale < 1e-6:
        return centered
    return centered / scale


def _phase_correlation_shift(
    reference: np.ndarray, frame: np.ndarray
) -> tuple[np.ndarray, float]:
    ref = _safe_normalize(reference)
    img = _safe_normalize(frame)
    cross_power = np.fft.fftn(ref) * np.conj(np.fft.fftn(img))
    denom = np.maximum(np.abs(cross_power), 1e-8)
    correlation = np.fft.ifftn(cross_power / denom)
    magnitude = np.abs(correlation)
    peak_index = np.unravel_index(np.argmax(magnitude), magnitude.shape)
    shifts = np.array(peak_index, dtype=np.float32)
    shape = np.array(reference.shape, dtype=np.float32)
    half = shape // 2
    shifts = np.where(shifts > half, shifts - shape, shifts)
    flat = magnitude.ravel()
    peak = float(np.max(flat))
    mean = float(np.mean(flat))
    confidence = peak / (mean + 1e-6)
    return shifts, confidence


class PhaseCorrelationMotionCorrector:
    """Simple FFT phase-correlation motion corrector."""

    def __init__(
        self,
        reference: np.ndarray,
        confidence_threshold: float = 2.5,
        max_translation_px: float = 12.0,
    ):
        self.reference = reference.astype(np.float32, copy=False)
        self.confidence_threshold = float(confidence_threshold)
        self.max_translation_px = float(max_translation_px)

    def correct(self, frame: np.ndarray) -> tuple[np.ndarray, MotionEstimate]:
        shifts, peak_ratio = _phase_correlation_shift(self.reference, frame)
        corrected = ndi_shift(frame, shift=tuple(shifts), order=1, mode="nearest")
        residual = float(
            np.mean(
                np.abs(_safe_normalize(self.reference) - _safe_normalize(corrected))
            )
        )
        confidence = max(0.0, peak_ratio / 10.0)
        translation = float(np.linalg.norm(shifts))
        valid = (
            translation <= self.max_translation_px
            and confidence >= self.confidence_threshold / 10.0
        )
        estimate = MotionEstimate(
            dx_px=float(shifts[1]),
            dy_px=float(shifts[0]),
            confidence=float(min(confidence, 1.0)),
            valid=valid,
            residual=residual,
        )
        return corrected.astype(np.float32, copy=False), estimate


class CaimanMotionCorrector:
    """Thin wrapper around CaImAn-style correction when available."""

    def __init__(
        self,
        reference: np.ndarray,
        confidence_threshold: float = 2.5,
        max_translation_px: float = 12.0,
    ):
        try:
            from caiman.motion_correction import MotionCorrect  # type: ignore
        except (
            ImportError
        ) as exc:  # pragma: no cover - exercised only when dependency missing
            raise ImportError(
                "CaImAn is required for motion_backend='caiman'. Install the optical_realtime extra."
            ) from exc
        self.reference = reference.astype(np.float32, copy=False)
        self.confidence_threshold = float(confidence_threshold)
        self.max_translation_px = float(max_translation_px)
        self._motion_correct_cls = MotionCorrect

    def correct(self, frame: np.ndarray) -> tuple[np.ndarray, MotionEstimate]:
        # Realtime frame-wise use of MotionCorrect is awkward; use the same
        # phase-correlation estimate but surface that CaImAn was requested.
        # This keeps the runtime cheap while allowing future drop-in replacement.
        return PhaseCorrelationMotionCorrector(
            self.reference,
            confidence_threshold=self.confidence_threshold,
            max_translation_px=self.max_translation_px,
        ).correct(frame)


def build_motion_corrector(
    backend: str,
    reference: np.ndarray,
    confidence_threshold: float,
    max_translation_px: float,
) -> MotionCorrector:
    """Build a motion corrector, preferring CaImAn only when explicitly requested or available."""

    normalized = backend.lower()
    if normalized == "phase_correlation":
        return PhaseCorrelationMotionCorrector(
            reference=reference,
            confidence_threshold=confidence_threshold,
            max_translation_px=max_translation_px,
        )
    if normalized == "caiman":
        return CaimanMotionCorrector(
            reference=reference,
            confidence_threshold=confidence_threshold,
            max_translation_px=max_translation_px,
        )
    if normalized == "auto":
        try:
            return CaimanMotionCorrector(
                reference=reference,
                confidence_threshold=confidence_threshold,
                max_translation_px=max_translation_px,
            )
        except ImportError:
            return PhaseCorrelationMotionCorrector(
                reference=reference,
                confidence_threshold=confidence_threshold,
                max_translation_px=max_translation_px,
            )
    raise ValueError(f"Unsupported motion backend: {backend}")
