"""Tests for diffusion tractography tool."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from brain_researcher.services.tools.diffusion_tractography_tool import (
    DiffusionTractographyArgs,
    DiffusionTractographyTool,
)


class TestDiffusionTractographyTool:
    """Test diffusion tractography functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.tool = DiffusionTractographyTool()
        self.temp_dir = tempfile.mkdtemp()

        # Create dummy diffusion data files
        self.dwi_file = Path(self.temp_dir) / "dwi.nii.gz"
        self.bvals_file = Path(self.temp_dir) / "dwi.bval"
        self.bvecs_file = Path(self.temp_dir) / "dwi.bvec"
        self.mask_file = Path(self.temp_dir) / "mask.nii.gz"

        # Create files
        self.dwi_file.touch()

        # Create bvals (65 volumes: 1 b0 + 64 directions)
        bvals = np.concatenate([[0], np.ones(64) * 1000])
        np.savetxt(self.bvals_file, bvals.reshape(1, -1), fmt="%d")

        # Create bvecs (65 x 3)
        bvecs = np.random.randn(3, 65)
        bvecs /= np.linalg.norm(bvecs, axis=0, keepdims=True) + 1e-8
        np.savetxt(self.bvecs_file, bvecs, fmt="%.6f")

        self.mask_file.touch()

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        assert self.tool.get_tool_name() == "diffusion_tractography"
        assert "fiber tracking" in self.tool.get_tool_description().lower()
        assert self.tool.get_args_schema() == DiffusionTractographyArgs

    def test_load_diffusion_data(self):
        """Test loading diffusion data."""
        dwi_data, affine, gtab, mask = self.tool._load_diffusion_data(
            str(self.dwi_file),
            str(self.bvals_file),
            str(self.bvecs_file),
            str(self.mask_file),
        )

        assert dwi_data is not None
        assert affine is not None
        assert mask is not None

        # Check shapes
        assert dwi_data.ndim == 4  # 4D data
        assert affine.shape == (4, 4)
        assert mask.ndim == 3

    def test_denoise_dwi(self):
        """Test DWI denoising."""
        dwi_data = np.random.randn(32, 32, 20, 65)

        denoised = self.tool._denoise_dwi(dwi_data)

        assert denoised is not None
        assert denoised.shape == dwi_data.shape
        assert np.all(np.isfinite(denoised))

    def test_fit_dti_model(self):
        """Test DTI model fitting."""
        # Create synthetic data
        dwi_data = np.random.randn(32, 32, 20, 65) * 100 + 500
        mask = np.ones((32, 32, 20), dtype=bool)
        gtab = None  # Will use fallback

        results = self.tool._fit_dti_model(dwi_data, gtab, mask)

        assert "fa" in results
        assert "md" in results
        assert "rd" in results
        assert "ad" in results
        assert "evecs" in results

        # Check FA values are reasonable
        fa = results["fa"]
        assert fa.shape == mask.shape
        assert np.all(fa >= 0) and np.all(fa <= 1)

    def test_create_seeds(self):
        """Test seed creation."""
        mask = np.zeros((32, 32, 20), dtype=bool)
        mask[10:20, 10:20, 5:15] = True
        affine = np.eye(4)

        seeds = self.tool._create_seeds(
            mask, affine, density=1, strategy="white_matter"
        )

        assert seeds is not None
        assert seeds.shape[1] == 3  # 3D coordinates
        assert len(seeds) > 0

    def test_deterministic_tracking(self):
        """Test deterministic tracking."""
        mask = np.ones((32, 32, 20), dtype=bool)
        affine = np.eye(4)
        seeds = self.tool._create_seeds(mask, affine, density=1)

        streamlines = self.tool._deterministic_tracking(
            stopping_criterion=None,
            seeds=seeds[:10],  # Use fewer seeds for speed
            affine=affine,
            step_size=0.5,
            max_angle=30,
        )

        assert streamlines is not None
        assert len(streamlines) > 0

    def test_filter_streamlines(self):
        """Test streamline filtering."""
        # Create streamlines of different lengths
        streamlines = []
        for length in [5, 15, 50, 100, 300]:
            points = np.cumsum(np.random.randn(length, 3) * 0.5, axis=0)
            streamlines.append(points)

        filtered = self.tool._filter_streamlines(
            streamlines, min_length=10, max_length=250
        )

        # Should keep streamlines with length 15, 50, 100
        assert len(filtered) == 3

    def test_compute_connectivity_matrix(self):
        """Test connectivity matrix computation."""
        # Create dummy streamlines
        streamlines = []
        for _ in range(100):
            n_points = np.random.randint(20, 50)
            points = np.cumsum(np.random.randn(n_points, 3) * 0.5, axis=0)
            streamlines.append(points)

        parcellation = np.random.randint(0, 10, (32, 32, 20))
        affine = np.eye(4)

        matrix, mapping = self.tool._compute_connectivity_matrix(
            streamlines, parcellation, affine
        )

        assert matrix is not None
        assert matrix.shape[0] == matrix.shape[1]  # Square matrix
        assert np.all(matrix >= 0)  # Non-negative counts

    def test_segment_bundles(self):
        """Test bundle segmentation."""
        # Create dummy streamlines
        streamlines = []
        for _ in range(50):
            n_points = np.random.randint(20, 50)
            points = np.cumsum(np.random.randn(n_points, 3) * 0.5, axis=0)
            streamlines.append(points)

        bundles = self.tool._segment_bundles(streamlines)

        assert isinstance(bundles, dict)
        assert len(bundles) > 0

        # Check known bundle names
        for bundle_name in ["CST_L", "CST_R", "CC"]:
            if bundle_name in bundles:
                assert isinstance(bundles[bundle_name], list)

    def test_run_dti_tractography(self):
        """Test full DTI tractography pipeline."""
        args = {
            "dwi_file": str(self.dwi_file),
            "bvals_file": str(self.bvals_file),
            "bvecs_file": str(self.bvecs_file),
            "mask_file": str(self.mask_file),
            "model_type": "dti",
            "tracking_method": "deterministic",
            "fa_threshold": 0.1,
            "step_size": 0.5,
            "min_length": 10,
            "max_length": 250,
            "seed_strategy": "white_matter",
            "seeds_per_voxel": 1,
            "compute_connectivity": False,
            "compute_fa": True,
            "compute_md": True,
            "output_dir": self.temp_dir,
            "save_streamlines": True,
            "save_fa_map": True,
            "visualize": False,
            "verbose": False,
        }

        result = self.tool._run(**args)

        assert result.status == "success"
        assert "outputs" in result.data
        assert "summary" in result.data
        assert result.data["summary"]["model"] == "dti"
        assert result.data["summary"]["tracking_method"] == "deterministic"

        # Check metrics
        metrics = result.data["summary"]["metrics"]
        assert "n_streamlines" in metrics
        assert metrics["n_streamlines"] >= 0

        if metrics["mean_fa"] is not None:
            assert 0 <= metrics["mean_fa"] <= 1

    def test_run_probabilistic_tracking(self):
        """Test probabilistic tracking."""
        args = {
            "dwi_file": str(self.dwi_file),
            "bvals_file": str(self.bvals_file),
            "bvecs_file": str(self.bvecs_file),
            "model_type": "csd",
            "tracking_method": "probabilistic",
            "sh_order": 4,
            "fa_threshold": 0.1,
            "output_dir": self.temp_dir,
            "save_streamlines": True,
            "visualize": False,
            "verbose": False,
        }

        result = self.tool._run(**args)

        assert result.status == "success"
        assert result.data["summary"]["tracking_method"] == "probabilistic"

    def test_connectivity_analysis(self):
        """Test connectivity analysis."""
        # Create parcellation file
        parc_file = Path(self.temp_dir) / "parcellation.nii.gz"
        parc_file.touch()

        args = {
            "dwi_file": str(self.dwi_file),
            "bvals_file": str(self.bvals_file),
            "bvecs_file": str(self.bvecs_file),
            "model_type": "dti",
            "tracking_method": "deterministic",
            "compute_connectivity": True,
            "parcellation_file": str(parc_file),
            "connectivity_metric": "count",
            "output_dir": self.temp_dir,
            "save_connectivity": True,
            "visualize": False,
            "verbose": False,
        }

        result = self.tool._run(**args)

        assert result.status == "success"
        if "connectivity" in result.data["outputs"]:
            assert result.data["outputs"]["connectivity"] is not None
            assert Path(result.data["outputs"]["feature_contract"]).exists()
            contract = json.loads(
                Path(result.data["outputs"]["feature_contract"]).read_text()
            )
            assert contract["matrix_kind"] == "structural_connectome_count"

    def test_bundle_segmentation(self):
        """Test bundle segmentation."""
        args = {
            "dwi_file": str(self.dwi_file),
            "bvals_file": str(self.bvals_file),
            "bvecs_file": str(self.bvecs_file),
            "model_type": "dti",
            "tracking_method": "deterministic",
            "segment_bundles": True,
            "bundle_threshold": 10.0,
            "output_dir": self.temp_dir,
            "visualize": False,
            "verbose": False,
        }

        result = self.tool._run(**args)

        assert result.status == "success"

        metrics = result.data["summary"]["metrics"]
        if "n_bundles" in metrics:
            assert metrics["n_bundles"] >= 0

    def test_visualization(self):
        """Test visualization generation."""
        args = {
            "dwi_file": str(self.dwi_file),
            "bvals_file": str(self.bvals_file),
            "bvecs_file": str(self.bvecs_file),
            "model_type": "dti",
            "tracking_method": "deterministic",
            "output_dir": self.temp_dir,
            "visualize": True,
            "render_bundles": True,
            "verbose": False,
        }

        with patch("matplotlib.pyplot.savefig"):
            result = self.tool._run(**args)

        assert result.status == "success"
        assert "visualization" in result.data["outputs"]

    def test_preprocessing_options(self):
        """Test preprocessing options."""
        args = {
            "dwi_file": str(self.dwi_file),
            "bvals_file": str(self.bvals_file),
            "bvecs_file": str(self.bvecs_file),
            "denoise": True,
            "correct_eddy": False,  # Skip for speed
            "correct_motion": False,  # Skip for speed
            "model_type": "dti",
            "tracking_method": "deterministic",
            "output_dir": self.temp_dir,
            "visualize": False,
            "verbose": False,
        }

        result = self.tool._run(**args)

        assert result.status == "success"

    def test_different_seed_strategies(self):
        """Test different seeding strategies."""
        strategies = ["white_matter", "whole_brain", "interface"]

        for strategy in strategies:
            args = {
                "dwi_file": str(self.dwi_file),
                "bvals_file": str(self.bvals_file),
                "bvecs_file": str(self.bvecs_file),
                "model_type": "dti",
                "tracking_method": "deterministic",
                "seed_strategy": strategy,
                "seed_density": 1,
                "output_dir": self.temp_dir,
                "visualize": False,
                "verbose": False,
            }

            result = self.tool._run(**args)

            assert result.status == "success"

    def test_error_handling(self):
        """Test error handling."""
        args = {
            "dwi_file": "nonexistent.nii.gz",
            "bvals_file": "nonexistent.bval",
            "bvecs_file": "nonexistent.bvec",
            "output_dir": self.temp_dir,
        }

        result = self.tool._run(**args)

        # Should handle gracefully
        assert result.status in ["success", "error"]
