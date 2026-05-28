"""Unit tests for realtime two-photon motion correction."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import shift as ndi_shift

from brain_researcher.services.tools.realtime_twophoton_motion import (
    PhaseCorrelationMotionCorrector,
)


def test_phase_correlation_corrector_reduces_alignment_error():
    reference = np.zeros((32, 32), dtype=np.float32)
    reference[8:24, 10:22] = 1.0
    shifted = ndi_shift(reference, shift=(3, -2), order=1, mode="nearest")

    corrector = PhaseCorrelationMotionCorrector(
        reference=reference,
        confidence_threshold=0.1,
        max_translation_px=10.0,
    )
    corrected, estimate = corrector.correct(shifted)

    original_error = np.mean(np.abs(reference - shifted))
    corrected_error = np.mean(np.abs(reference - corrected))

    assert corrected_error < original_error
    assert estimate.valid is True
    assert estimate.confidence > 0.0
