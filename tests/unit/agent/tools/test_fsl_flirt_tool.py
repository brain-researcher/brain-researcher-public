"""
Tests for FSL FLIRT registration tool implementation.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from brain_researcher.services.tools.fsl_flirt_tool import (
    FLIRTCostFunction,
    FLIRTSearchMethod,
    FSLFLIRTArgs,
    FSLFLIRTTool,
    FSLFLIRTTools,
)


class TestFSLFLIRTArgs(unittest.TestCase):
    """Test FSL FLIRT arguments validation."""

    def test_basic_args_creation(self):
        """Test creating basic FLIRT arguments."""
        args = FSLFLIRTArgs(
            input_file="/data/moving.nii.gz",
            reference_file="/data/fixed.nii.gz",
            output_file="/data/registered.nii.gz"
        )

        assert args.input_file == "/data/moving.nii.gz"
        assert args.reference_file == "/data/fixed.nii.gz"
        assert args.output_file == "/data/registered.nii.gz"
        assert args.dof == 12  # Default
        assert args.cost_function == FLIRTCostFunction.CORRELATION_RATIO

    def test_args_with_matrix(self):
        """Test arguments with transformation matrix."""
        args = FSLFLIRTArgs(
            input_file="/data/moving.nii.gz",
            reference_file="/data/fixed.nii.gz",
            output_file="/data/registered.nii.gz",
            output_matrix="/data/transform.mat",
            init_matrix="/data/init.mat"
        )

        assert args.output_matrix == "/data/transform.mat"
        assert args.init_matrix == "/data/init.mat"

    def test_dof_validation(self):
        """Test degrees of freedom validation."""
        # Valid DOF values
        for dof in [6, 7, 9, 12]:
            args = FSLFLIRTArgs(
                input_file="input.nii",
                reference_file="ref.nii",
                output_file="out.nii",
                dof=dof
            )
            assert args.dof == dof

        # Invalid DOF should raise error
        with pytest.raises(ValueError):
            FSLFLIRTArgs(
                input_file="input.nii",
                reference_file="ref.nii",
                output_file="out.nii",
                dof=5  # Too low
            )

    def test_search_ranges(self):
        """Test search range configuration."""
        args = FSLFLIRTArgs(
            input_file="input.nii",
            reference_file="ref.nii",
            output_file="out.nii",
            search_range_x=(-45, 45),
            search_range_y=(-30, 30),
            search_range_z=(-60, 60)
        )

        assert args.search_range_x == (-45, 45)
        assert args.search_range_y == (-30, 30)
        assert args.search_range_z == (-60, 60)

    def test_interpolation_methods(self):
        """Test interpolation method options."""
        valid_methods = ["nearestneighbour", "trilinear", "sinc", "spline"]

        for method in valid_methods:
            args = FSLFLIRTArgs(
                input_file="input.nii",
                reference_file="ref.nii",
                output_file="out.nii",
                interp_method=method
            )
            assert args.interp_method == method


class TestFSLFLIRTTool(unittest.TestCase):
    """Test FSL FLIRT registration tool."""

    def setUp(self):
        """Set up test environment."""
        self.tool = FSLFLIRTTool()

    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "fsl_flirt"
        assert "linear" in self.tool.get_tool_description().lower()
        assert self.tool.get_args_schema() == FSLFLIRTArgs

    @patch('subprocess.run')
    def test_basic_registration(self, mock_run):
        """Test basic registration execution."""
        # Mock successful FLIRT execution
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="FLIRT registration completed",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            output_file = os.path.join(temp_dir, "registered.nii.gz")

            # Create dummy input files
            Path(input_file).touch()
            Path(ref_file).touch()

            result = self.tool._run(
                input_file=input_file,
                reference_file=ref_file,
                output_file=output_file
            )

            assert result.status == "success"
            assert result.data["outputs"]["registered_image"] == output_file
            assert "command" in result.data

            # Verify FLIRT was called with correct arguments
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "flirt" in call_args[0]
            assert "-in" in call_args
            assert "-ref" in call_args
            assert "-out" in call_args

    @patch("brain_researcher.services.tools.fsl_flirt_tool.render_registration_checkerboard_png")
    @patch('subprocess.run')
    def test_registration_emits_qc_png_when_registered_output_exists(
        self,
        mock_run,
        mock_render,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_render.side_effect = lambda *_args, **_kwargs: str(_args[2])

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            output_file = os.path.join(temp_dir, "registered.nii.gz")

            Path(input_file).touch()
            Path(ref_file).touch()
            Path(output_file).touch()

            result = self.tool._run(
                input_file=input_file,
                reference_file=ref_file,
                output_file=output_file,
            )

            assert result.status == "success"
            assert result.data["outputs"]["qc_png"].endswith("_qc.png")
            mock_render.assert_called_once()

    @patch('subprocess.run')
    def test_registration_with_matrix(self, mock_run):
        """Test registration with transformation matrix output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            output_file = os.path.join(temp_dir, "registered.nii.gz")
            matrix_file = os.path.join(temp_dir, "transform.mat")

            Path(input_file).touch()
            Path(ref_file).touch()

            result = self.tool._run(
                input_file=input_file,
                reference_file=ref_file,
                output_file=output_file,
                output_matrix=matrix_file
            )

            assert result.status == "success"
            assert result.data["outputs"]["transformation_matrix"] == matrix_file

            call_args = mock_run.call_args[0][0]
            assert "-omat" in call_args
            matrix_idx = call_args.index("-omat")
            assert call_args[matrix_idx + 1] == matrix_file

    @patch('subprocess.run')
    def test_registration_with_init_matrix(self, mock_run):
        """Test registration with initial transformation."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            output_file = os.path.join(temp_dir, "registered.nii.gz")
            init_matrix = os.path.join(temp_dir, "init.mat")

            Path(input_file).touch()
            Path(ref_file).touch()
            Path(init_matrix).touch()

            result = self.tool._run(
                input_file=input_file,
                reference_file=ref_file,
                output_file=output_file,
                init_matrix=init_matrix
            )

            assert result.status == "success"

            call_args = mock_run.call_args[0][0]
            assert "-init" in call_args
            init_idx = call_args.index("-init")
            assert call_args[init_idx + 1] == init_matrix

    @patch('subprocess.run')
    def test_rigid_registration(self, mock_run):
        """Test rigid body registration (6 DOF)."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            output_file = os.path.join(temp_dir, "registered.nii.gz")

            Path(input_file).touch()
            Path(ref_file).touch()

            result = self.tool._run(
                input_file=input_file,
                reference_file=ref_file,
                output_file=output_file,
                dof=6  # Rigid body
            )

            assert result.status == "success"

            call_args = mock_run.call_args[0][0]
            assert "-dof" in call_args
            dof_idx = call_args.index("-dof")
            assert call_args[dof_idx + 1] == "6"

    @patch('subprocess.run')
    def test_cost_functions(self, mock_run):
        """Test different cost functions."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        cost_functions = [
            FLIRTCostFunction.CORRELATION_RATIO,
            FLIRTCostFunction.MUTUAL_INFO,
            FLIRTCostFunction.LEAST_SQUARES,
            FLIRTCostFunction.NORMALIZED_CORRELATION
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            Path(input_file).touch()
            Path(ref_file).touch()

            for cost_func in cost_functions:
                result = self.tool._run(
                    input_file=input_file,
                    reference_file=ref_file,
                    output_file=os.path.join(temp_dir, f"out_{cost_func}.nii.gz"),
                    cost_function=cost_func
                )

                assert result.status == "success"

                call_args = mock_run.call_args[0][0]
                assert "-cost" in call_args
                cost_idx = call_args.index("-cost")
                assert call_args[cost_idx + 1] == cost_func.value

    @patch('subprocess.run')
    def test_search_methods(self, mock_run):
        """Test different search methods."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            Path(input_file).touch()
            Path(ref_file).touch()

            # Test global search
            result = self.tool._run(
                input_file=input_file,
                reference_file=ref_file,
                output_file=os.path.join(temp_dir, "out_global.nii.gz"),
                search_method=FLIRTSearchMethod.GLOBAL_SEARCH
            )

            assert result.status == "success"
            call_args = mock_run.call_args[0][0]
            assert "-searchrx" in call_args  # Global search uses full search ranges

    @patch('subprocess.run')
    def test_search_ranges(self, mock_run):
        """Test custom search ranges."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            Path(input_file).touch()
            Path(ref_file).touch()

            result = self.tool._run(
                input_file=input_file,
                reference_file=ref_file,
                output_file=os.path.join(temp_dir, "out.nii.gz"),
                search_range_x=(-45, 45),
                search_range_y=(-30, 30),
                search_range_z=(-60, 60),
                search_method=FLIRTSearchMethod.GLOBAL_SEARCH
            )

            assert result.status == "success"

            call_args = mock_run.call_args[0][0]
            assert "-searchrx" in call_args
            rx_idx = call_args.index("-searchrx")
            assert float(call_args[rx_idx + 1]) == -45
            assert float(call_args[rx_idx + 2]) == 45

    @patch('subprocess.run')
    def test_interpolation_methods(self, mock_run):
        """Test different interpolation methods."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        interp_methods = ["nearestneighbour", "trilinear", "sinc", "spline"]

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            Path(input_file).touch()
            Path(ref_file).touch()

            for method in interp_methods:
                result = self.tool._run(
                    input_file=input_file,
                    reference_file=ref_file,
                    output_file=os.path.join(temp_dir, f"out_{method}.nii.gz"),
                    interp_method=method
                )

                assert result.status == "success"

                call_args = mock_run.call_args[0][0]
                assert "-interp" in call_args
                interp_idx = call_args.index("-interp")
                assert call_args[interp_idx + 1] == method

    @patch('subprocess.run')
    def test_verbose_output(self, mock_run):
        """Test verbose output option."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Registration details...",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            Path(input_file).touch()
            Path(ref_file).touch()

            result = self.tool._run(
                input_file=input_file,
                reference_file=ref_file,
                output_file=os.path.join(temp_dir, "out.nii.gz"),
                verbose=True
            )

            assert result.status == "success"

            call_args = mock_run.call_args[0][0]
            assert "-v" in call_args

    def test_missing_input_file(self):
        """Test error handling for missing input file."""
        result = self.tool._run(
            input_file="/nonexistent/input.nii.gz",
            reference_file="/nonexistent/ref.nii.gz",
            output_file="/tmp/out.nii.gz"
        )

        assert result.status == "error"
        assert "not found" in result.error.lower()

    def test_missing_reference_file(self):
        """Test error handling for missing reference file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "input.nii.gz")
            Path(input_file).touch()

            result = self.tool._run(
                input_file=input_file,
                reference_file="/nonexistent/ref.nii.gz",
                output_file="/tmp/out.nii.gz"
            )

            assert result.status == "error"
            assert "not found" in result.error.lower()

    @patch('subprocess.run')
    def test_registration_failure(self, mock_run):
        """Test handling of FLIRT execution failure."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: Registration failed"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            Path(input_file).touch()
            Path(ref_file).touch()

            result = self.tool._run(
                input_file=input_file,
                reference_file=ref_file,
                output_file=os.path.join(temp_dir, "out.nii.gz")
            )

            assert result.status == "error"
            assert "Registration failed" in result.error

    @patch('subprocess.run')
    def test_apply_transformation(self, mock_run):
        """Test applying existing transformation matrix."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "moving.nii.gz")
            ref_file = os.path.join(temp_dir, "fixed.nii.gz")
            output_file = os.path.join(temp_dir, "registered.nii.gz")
            matrix_file = os.path.join(temp_dir, "transform.mat")

            Path(input_file).touch()
            Path(ref_file).touch()
            Path(matrix_file).touch()

            # Apply existing transformation
            result = self.tool.apply_transformation(
                input_file=input_file,
                reference_file=ref_file,
                output_file=output_file,
                transformation_matrix=matrix_file
            )

            assert result.status == "success"

            call_args = mock_run.call_args[0][0]
            assert "flirt" in call_args[0]
            assert "-in" in call_args
            assert "-ref" in call_args
            assert "-out" in call_args
            assert "-init" in call_args
            assert "-applyxfm" in call_args

    @patch('subprocess.run')
    def test_invert_transformation(self, mock_run):
        """Test inverting transformation matrix."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_matrix = os.path.join(temp_dir, "forward.mat")
            output_matrix = os.path.join(temp_dir, "inverse.mat")

            Path(input_matrix).touch()

            result = self.tool.invert_transformation(
                input_matrix=input_matrix,
                output_matrix=output_matrix
            )

            assert result.status == "success"

            call_args = mock_run.call_args[0][0]
            assert "convert_xfm" in call_args[0]
            assert "-omat" in call_args
            assert "-inverse" in call_args

    @patch('subprocess.run')
    def test_concatenate_transformations(self, mock_run):
        """Test concatenating transformation matrices."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            matrix1 = os.path.join(temp_dir, "transform1.mat")
            matrix2 = os.path.join(temp_dir, "transform2.mat")
            output_matrix = os.path.join(temp_dir, "combined.mat")

            Path(matrix1).touch()
            Path(matrix2).touch()

            result = self.tool.concatenate_transformations(
                matrix1=matrix1,
                matrix2=matrix2,
                output_matrix=output_matrix
            )

            assert result.status == "success"

            call_args = mock_run.call_args[0][0]
            assert "convert_xfm" in call_args[0]
            assert "-omat" in call_args
            assert "-concat" in call_args


class TestEnumValues(unittest.TestCase):
    """Test enum value definitions."""

    def test_cost_function_enum(self):
        """Test FLIRTCostFunction enum values."""
        assert FLIRTCostFunction.CORRELATION_RATIO == "corratio"
        assert FLIRTCostFunction.MUTUAL_INFO == "mutualinfo"
        assert FLIRTCostFunction.LEAST_SQUARES == "leastsq"
        assert FLIRTCostFunction.NORMALIZED_CORRELATION == "normcorr"
        assert FLIRTCostFunction.NORMALIZED_MUTUAL_INFO == "normmi"
        assert FLIRTCostFunction.LABELLED_SLICES == "labeldiff"

    def test_search_method_enum(self):
        """Test FLIRTSearchMethod enum values."""
        assert FLIRTSearchMethod.REGULAR_STEP == "reg"
        assert FLIRTSearchMethod.GLOBAL_SEARCH == "global"


class TestIntegration(unittest.TestCase):
    """Integration tests for FSL FLIRT tools."""

    def test_tools_collection(self):
        """Test getting all FSL FLIRT tools."""
        tools = FSLFLIRTTools.get_all_tools()

        assert len(tools) == 1
        assert isinstance(tools[0], FSLFLIRTTool)

    def test_tool_inherits_base(self):
        """Test tool inherits from BRKGToolWrapper."""
        from brain_researcher.services.tools.tool_base import BRKGToolWrapper

        tool = FSLFLIRTTool()
        assert isinstance(tool, BRKGToolWrapper)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
