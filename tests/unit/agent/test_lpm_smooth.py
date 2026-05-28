"""
Unit tests for LPM smooth operation.

Tests cover:
- Parameter validation and conversion
- AFNI backend compilation
- FSL backend compilation
- Backend selection logic
- Error handling
"""

import pytest
from unittest.mock import patch

from brain_researcher.services.agent.lpm.specs import SmoothParams, CompiledOp
from brain_researcher.services.agent.lpm.adapters import (
    compile_smooth_afni,
    compile_smooth_fsl,
    compile_smooth_fsl_masked,
)
from brain_researcher.services.agent.lpm.compiler import compile_op


# ============================================================================
# SmoothParams Tests
# ============================================================================


def test_smooth_params_fwhm_only():
    """Test SmoothParams with FWHM only."""
    params = SmoothParams(
        fwhm_mm=6.0,
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    assert params.fwhm_mm == 6.0
    assert params.sigma_mm is None
    assert params.to_fwhm() == 6.0


def test_smooth_params_sigma_only():
    """Test SmoothParams with sigma only."""
    params = SmoothParams(
        sigma_mm=2.5,
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    assert params.sigma_mm == 2.5
    assert params.fwhm_mm is None
    assert params.to_sigma() == 2.5


def test_smooth_params_fwhm_to_sigma_conversion():
    """Test FWHM to sigma conversion."""
    params = SmoothParams(
        fwhm_mm=6.0,
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    sigma = params.to_sigma()
    # sigma = fwhm / 2.3548 (where 2.3548 = sqrt(8*ln(2)))
    expected_sigma = 6.0 / 2.3548
    assert abs(sigma - expected_sigma) < 0.001


def test_smooth_params_sigma_to_fwhm_conversion():
    """Test sigma to FWHM conversion."""
    params = SmoothParams(
        sigma_mm=2.5,
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    fwhm = params.to_fwhm()
    # fwhm = sigma * 2.3548
    expected_fwhm = 2.5 * 2.3548
    assert abs(fwhm - expected_fwhm) < 0.001


def test_smooth_params_roundtrip():
    """Test that FWHM -> sigma -> FWHM roundtrips correctly."""
    original_fwhm = 6.0
    params = SmoothParams(
        fwhm_mm=original_fwhm,
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    sigma = params.to_sigma()
    roundtrip_fwhm = sigma * 2.3548

    assert abs(roundtrip_fwhm - original_fwhm) < 0.001


def test_smooth_params_missing_both():
    """Test that providing neither FWHM nor sigma raises error."""
    with pytest.raises(ValueError, match="Must provide either fwhm_mm or sigma_mm"):
        SmoothParams(
            input="/data/input.nii.gz",
            output="/data/output.nii.gz",
        )


def test_smooth_params_with_mask():
    """Test SmoothParams with mask."""
    params = SmoothParams(
        fwhm_mm=6.0,
        mask="/data/mask.nii.gz",
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    assert params.mask == "/data/mask.nii.gz"


def test_smooth_params_negative_fwhm():
    """Test that negative FWHM raises validation error."""
    with pytest.raises(ValueError):
        SmoothParams(
            fwhm_mm=-1.0,
            input="/data/input.nii.gz",
            output="/data/output.nii.gz",
        )


def test_smooth_params_zero_fwhm():
    """Test that zero FWHM raises validation error."""
    with pytest.raises(ValueError):
        SmoothParams(
            fwhm_mm=0.0,
            input="/data/input.nii.gz",
            output="/data/output.nii.gz",
        )


# ============================================================================
# AFNI Adapter Tests
# ============================================================================


def test_compile_smooth_afni_basic():
    """Test basic AFNI compilation without mask."""
    params = SmoothParams(
        fwhm_mm=6.0,
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    result = compile_smooth_afni(params)

    assert result["executable"] == "3dBlurInMask"
    assert "-FWHM" in result["args"]
    assert "6.0000" in result["args"]
    assert "-input" in result["args"]
    assert "/data/input.nii.gz" in result["args"]
    assert "-prefix" in result["args"]
    assert "/data/output.nii.gz" in result["args"]


def test_compile_smooth_afni_with_mask():
    """Test AFNI compilation with mask."""
    params = SmoothParams(
        fwhm_mm=6.0,
        mask="/data/mask.nii.gz",
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    result = compile_smooth_afni(params)

    assert "-mask" in result["args"]
    assert "/data/mask.nii.gz" in result["args"]
    assert result["params"]["mask"] == "/data/mask.nii.gz"


def test_compile_smooth_afni_uses_fwhm():
    """Test that AFNI adapter uses FWHM directly."""
    params = SmoothParams(
        sigma_mm=2.5,  # Provide sigma
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    result = compile_smooth_afni(params)

    # Should convert to FWHM
    expected_fwhm = 2.5 * 2.3548
    fwhm_idx = result["args"].index("-FWHM") + 1
    actual_fwhm = float(result["args"][fwhm_idx])

    assert abs(actual_fwhm - expected_fwhm) < 0.01


# ============================================================================
# FSL Adapter Tests
# ============================================================================


def test_compile_smooth_fsl_basic():
    """Test basic FSL compilation without mask."""
    params = SmoothParams(
        fwhm_mm=6.0,
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    result = compile_smooth_fsl(params)

    assert result["executable"] == "fslmaths"
    assert "/data/input.nii.gz" in result["args"]
    assert "-s" in result["args"]
    assert "/data/output.nii.gz" in result["args"]


def test_compile_smooth_fsl_uses_sigma():
    """Test that FSL adapter uses sigma (not FWHM)."""
    params = SmoothParams(
        fwhm_mm=6.0,  # Provide FWHM
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    result = compile_smooth_fsl(params)

    # Should convert to sigma
    expected_sigma = 6.0 / 2.3548
    sigma_idx = result["args"].index("-s") + 1
    actual_sigma = float(result["args"][sigma_idx])

    assert abs(actual_sigma - expected_sigma) < 0.01


def test_compile_smooth_fsl_with_mask_note():
    """Test that FSL compilation notes mask limitation."""
    params = SmoothParams(
        fwhm_mm=6.0,
        mask="/data/mask.nii.gz",
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    result = compile_smooth_fsl(params)

    # Should include note about mask limitation
    assert "_note" in result["params"]
    assert "doesn't support masking" in result["params"]["_note"]


def test_compile_smooth_fsl_masked():
    """Test FSL masked compilation (two-step)."""
    params = SmoothParams(
        fwhm_mm=6.0,
        mask="/data/mask.nii.gz",
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    result = compile_smooth_fsl_masked(params)

    assert result["multi_step"] is True
    assert len(result["steps"]) == 2

    # Check first step (masking)
    step1 = result["steps"][0]
    assert step1["name"] == "apply_mask"
    assert "-mas" in step1["args"]

    # Check second step (smoothing)
    step2 = result["steps"][1]
    assert step2["name"] == "smooth"
    assert "-s" in step2["args"]


def test_compile_smooth_fsl_masked_requires_mask():
    """Test that masked FSL compilation requires mask."""
    params = SmoothParams(
        fwhm_mm=6.0,
        input="/data/input.nii.gz",
        output="/data/output.nii.gz",
    )

    with pytest.raises(ValueError, match="requires a mask"):
        compile_smooth_fsl_masked(params)


# ============================================================================
# Compiler Tests
# ============================================================================


@patch("brain_researcher.services.agent.lpm.compiler.load_niwrap_containers")
def test_compile_op_smooth_afni_available(mock_load):
    """Test compile_op selects AFNI when available."""
    mock_load.return_value = {
        "afni": {"image": "/cvmfs/afni.simg"},
        "fsl": {"image": "/cvmfs/fsl.simg"},
    }

    compiled = compile_op(
        "smooth",
        {
            "fwhm_mm": 6.0,
            "input": "/data/input.nii.gz",
            "output": "/data/output.nii.gz",
        },
    )

    assert compiled.backend == "afni"
    assert compiled.tool == "afni.3dBlurInMask"
    assert compiled.container_image == "/cvmfs/afni.simg"


@patch("brain_researcher.services.agent.lpm.compiler.load_niwrap_containers")
def test_compile_op_smooth_fsl_fallback(mock_load):
    """Test compile_op falls back to FSL when AFNI unavailable."""
    mock_load.return_value = {
        "fsl": {"image": "/cvmfs/fsl.simg"},
        # AFNI not available
    }

    compiled = compile_op(
        "smooth",
        {
            "fwhm_mm": 6.0,
            "input": "/data/input.nii.gz",
            "output": "/data/output.nii.gz",
        },
    )

    assert compiled.backend == "fsl"
    assert compiled.tool == "fsl.fslmaths"
    assert compiled.container_image == "/cvmfs/fsl.simg"


@patch("brain_researcher.services.agent.lpm.compiler.load_niwrap_containers")
def test_compile_op_smooth_preferred_backend(mock_load):
    """Test compile_op respects preferred backend."""
    mock_load.return_value = {
        "afni": {"image": "/cvmfs/afni.simg"},
        "fsl": {"image": "/cvmfs/fsl.simg"},
    }

    compiled = compile_op(
        "smooth",
        {
            "fwhm_mm": 6.0,
            "input": "/data/input.nii.gz",
            "output": "/data/output.nii.gz",
        },
        preferred="fsl",
    )

    # Should prefer FSL even though AFNI is available
    assert compiled.backend == "fsl"


@patch("brain_researcher.services.agent.lpm.compiler.load_niwrap_containers")
def test_compile_op_smooth_no_backend_available(mock_load):
    """Test compile_op raises error when no backend available."""
    mock_load.return_value = {}  # No containers

    with pytest.raises(RuntimeError, match="No backend available"):
        compile_op(
            "smooth",
            {
                "fwhm_mm": 6.0,
                "input": "/data/input.nii.gz",
                "output": "/data/output.nii.gz",
            },
        )


def test_compile_op_unsupported_operation():
    """Test compile_op raises error for unsupported operation."""
    with pytest.raises(ValueError, match="Unsupported operation"):
        compile_op(
            "unsupported_op",
            {"some": "params"},
        )


def test_compile_op_invalid_params():
    """Test compile_op raises error for invalid parameters."""
    with pytest.raises(ValueError, match="Invalid parameters"):
        compile_op(
            "smooth",
            {
                # Missing required input/output
                "fwhm_mm": 6.0,
            },
        )


@patch("brain_researcher.services.agent.lpm.compiler.load_niwrap_containers")
def test_compile_op_includes_canonical_params(mock_load):
    """Test that compiled result includes original canonical params."""
    mock_load.return_value = {
        "afni": {"image": "/cvmfs/afni.simg"},
    }

    original_params = {
        "fwhm_mm": 6.0,
        "input": "/data/input.nii.gz",
        "output": "/data/output.nii.gz",
    }

    compiled = compile_op("smooth", original_params)

    assert compiled.canonical_params is not None
    assert compiled.canonical_params["fwhm_mm"] == 6.0


@patch("brain_researcher.services.agent.lpm.compiler.load_niwrap_containers")
def test_compile_op_with_mask_prefers_afni(mock_load):
    """Test that masked operations prefer AFNI (native support)."""
    mock_load.return_value = {
        "afni": {"image": "/cvmfs/afni.simg"},
        "fsl": {"image": "/cvmfs/fsl.simg"},
    }

    compiled = compile_op(
        "smooth",
        {
            "fwhm_mm": 6.0,
            "mask": "/data/mask.nii.gz",
            "input": "/data/input.nii.gz",
            "output": "/data/output.nii.gz",
        },
    )

    # Should prefer AFNI for masked operations
    assert compiled.backend == "afni"
    assert "mask support" in compiled.why.lower() or "with mask" in compiled.why.lower()


# ============================================================================
# CompiledOp Model Tests
# ============================================================================


def test_compiled_op_model():
    """Test CompiledOp model validation."""
    compiled = CompiledOp(
        tool="afni.3dBlurInMask",
        params={"FWHM": 6.0},
        container_image="/cvmfs/afni.simg",
        backend="afni",
        why="AFNI selected",
    )

    assert compiled.tool == "afni.3dBlurInMask"
    assert compiled.backend == "afni"
    assert compiled.params["FWHM"] == 6.0


def test_compiled_op_serialization():
    """Test that CompiledOp is JSON serializable."""
    compiled = CompiledOp(
        tool="fsl.fslmaths",
        params={"sigma": 2.5},
        backend="fsl",
        why="FSL selected",
    )

    json_data = compiled.model_dump()
    assert json_data["tool"] == "fsl.fslmaths"
    assert json_data["backend"] == "fsl"
