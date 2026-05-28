"""
Tests for FreeSurfer tool implementation.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from brain_researcher.services.tools.freesurfer_tool import (
    FreeSurferConfig,
    FreeSurferParcellationArgs,
    FreeSurferParcellationTool,
    FreeSurferQCArgs,
    FreeSurferQCTool,
    FreeSurferReconAllArgs,
    FreeSurferReconAllTool,
    FreeSurferTools,
    FreeSurferVolumetricArgs,
    FreeSurferVolumetricTool,
    ParcellationAtlas,
    ReconAllStage,
    SurfaceMeasure,
)


class TestFreeSurferConfig(unittest.TestCase):
    """Test FreeSurfer configuration."""
    
    def test_config_creation(self):
        """Test configuration is created correctly."""
        config = FreeSurferConfig(
            subjects_dir="/data/subjects",
            license_file="/opt/fs/license.txt",
            n_threads=8,
            use_gpu=True
        )
        
        assert config.subjects_dir == "/data/subjects"
        assert config.license_file == "/opt/fs/license.txt"
        assert config.n_threads == 8
        assert config.use_gpu is True
    
    def test_environment_variables(self):
        """Test environment variable generation."""
        config = FreeSurferConfig(
            subjects_dir="/data/subjects",
            n_threads=4,
            use_gpu=True
        )
        
        env = config.get_environment()
        
        assert env["SUBJECTS_DIR"] == "/data/subjects"
        assert env["FS_LICENSE"] == "/opt/freesurfer/license.txt"
        assert env["OMP_NUM_THREADS"] == "4"
        assert env["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] == "4"
        assert env["FS_CUDA"] == "1"
    
    def test_default_values(self):
        """Test default configuration values."""
        config = FreeSurferConfig(subjects_dir="/data")
        
        assert config.license_file == "/opt/freesurfer/license.txt"
        assert config.n_threads == 1
        assert config.use_gpu is False
        assert config.hippocampal_subfields is False
        assert config.use_3T is True


class TestFreeSurferReconAllTool(unittest.TestCase):
    """Test FreeSurfer recon-all tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = FreeSurferReconAllTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "freesurfer_recon_all"
        assert "surface reconstruction" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == FreeSurferReconAllArgs
    
    def test_run_basic_recon_all(self):
        """Test basic recon-all execution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock T1 image
            t1_file = os.path.join(temp_dir, "t1.nii.gz")
            Path(t1_file).touch()
            
            result = self.tool._run(
                t1_image=t1_file,
                subject_id="sub001",
                subjects_dir=temp_dir,
                stage="all"
            )
            
            assert result.status == "success"
            assert "recon-all" in result.data["command"]
            assert "-subjid sub001" in result.data["command"]
            assert "-all" in result.data["command"]
            assert result.data["stage"] == "all"
            assert result.data["estimated_time"] == "6-10 hours"
    
    def test_run_with_additional_images(self):
        """Test recon-all with T2 and FLAIR images."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock images
            t1_file = os.path.join(temp_dir, "t1.nii.gz")
            t2_file = os.path.join(temp_dir, "t2.nii.gz")
            flair_file = os.path.join(temp_dir, "flair.nii.gz")
            
            Path(t1_file).touch()
            Path(t2_file).touch()
            Path(flair_file).touch()
            
            result = self.tool._run(
                t1_image=t1_file,
                subject_id="sub001",
                subjects_dir=temp_dir,
                t2_image=t2_file,
                flair_image=flair_file
            )
            
            assert result.status == "success"
            assert "-T2" in result.data["command"]
            assert "-T2pial" in result.data["command"]
            assert "-FLAIR" in result.data["command"]
            assert "-FLAIRpial" in result.data["command"]
    
    def test_run_with_stages(self):
        """Test recon-all with specific stages."""
        with tempfile.TemporaryDirectory() as temp_dir:
            t1_file = os.path.join(temp_dir, "t1.nii.gz")
            Path(t1_file).touch()
            
            # Test autorecon1
            result = self.tool._run(
                t1_image=t1_file,
                subject_id="sub001",
                subjects_dir=temp_dir,
                stage="autorecon1"
            )
            
            assert result.status == "success"
            assert "-autorecon1" in result.data["command"]
            assert result.data["estimated_time"] == "30-60 minutes"
    
    def test_run_with_subfield_segmentation(self):
        """Test recon-all with additional segmentations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            t1_file = os.path.join(temp_dir, "t1.nii.gz")
            Path(t1_file).touch()
            
            result = self.tool._run(
                t1_image=t1_file,
                subject_id="sub001",
                subjects_dir=temp_dir,
                hippocampal_subfields=True,
                brainstem=True,
                thalamus=True
            )
            
            assert result.status == "success"
            assert result.data["additional_segmentations"]["hippocampal_subfields"]
            assert result.data["additional_segmentations"]["brainstem"]
            assert result.data["additional_segmentations"]["thalamus"]
            
            # Check script content
            script_file = Path(result.data["script_file"])
            assert script_file.exists()
            script_content = script_file.read_text()
            assert "segmentHA_T1.sh" in script_content
            assert "segmentBS.sh" in script_content
            assert "segmentThalamicNuclei.sh" in script_content
    
    def test_run_with_parallel_processing(self):
        """Test recon-all with parallel processing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            t1_file = os.path.join(temp_dir, "t1.nii.gz")
            Path(t1_file).touch()
            
            result = self.tool._run(
                t1_image=t1_file,
                subject_id="sub001",
                subjects_dir=temp_dir,
                parallel=True,
                n_threads=8
            )
            
            assert result.status == "success"
            assert "-openmp 8" in result.data["command"]
            assert result.data["environment"]["OMP_NUM_THREADS"] == "8"
    
    def test_run_with_gpu(self):
        """Test recon-all with GPU acceleration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            t1_file = os.path.join(temp_dir, "t1.nii.gz")
            Path(t1_file).touch()
            
            result = self.tool._run(
                t1_image=t1_file,
                subject_id="sub001",
                subjects_dir=temp_dir,
                use_gpu=True
            )
            
            assert result.status == "success"
            assert "-use-gpu" in result.data["command"]
            assert result.data["environment"]["FS_CUDA"] == "1"
    
    def test_run_missing_t1(self):
        """Test error handling for missing T1 image."""
        result = self.tool._run(
            t1_image="/nonexistent/t1.nii.gz",
            subject_id="sub001",
            subjects_dir="/tmp"
        )
        
        assert result.status == "error"
        assert "T1 image not found" in result.error


class TestFreeSurferParcellationTool(unittest.TestCase):
    """Test FreeSurfer parcellation tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = FreeSurferParcellationTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "freesurfer_parcellation"
        assert "parcellation statistics" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == FreeSurferParcellationArgs
    
    def test_run_parcellation_extraction(self):
        """Test parcellation extraction."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock subject directory structure
            subject_dir = Path(temp_dir) / "sub001"
            subject_dir.mkdir(parents=True)
            (subject_dir / "stats").mkdir()
            (subject_dir / "label").mkdir()
            
            # Create mock stats file
            stats_file = subject_dir / "stats" / "lh.aparc.stats"
            stats_file.touch()
            
            result = self.tool._run(
                subject_id="sub001",
                subjects_dir=temp_dir,
                atlas="aparc",
                hemisphere="lh",
                measure="thickness"
            )
            
            assert result.status == "success"
            assert result.data["atlas"] == "aparc"
            assert result.data["hemisphere"] == "lh"
            assert result.data["measure"] == "thickness"
    
    def test_run_both_hemispheres(self):
        """Test parcellation for both hemispheres."""
        with tempfile.TemporaryDirectory() as temp_dir:
            subject_dir = Path(temp_dir) / "sub001"
            subject_dir.mkdir(parents=True)
            (subject_dir / "stats").mkdir()
            (subject_dir / "label").mkdir()
            
            # Create mock stats files for both hemispheres
            for hemi in ["lh", "rh"]:
                stats_file = subject_dir / "stats" / f"{hemi}.aparc.stats"
                stats_file.touch()
            
            result = self.tool._run(
                subject_id="sub001",
                subjects_dir=temp_dir,
                hemisphere="both"
            )
            
            assert result.status == "success"
            assert result.data["hemisphere"] == "both"
            assert len(result.data["commands"]) >= 2  # Commands for both hemispheres
    
    def test_run_table_output(self):
        """Test table format output."""
        with tempfile.TemporaryDirectory() as temp_dir:
            subject_dir = Path(temp_dir) / "sub001"
            subject_dir.mkdir(parents=True)
            (subject_dir / "stats").mkdir()
            
            result = self.tool._run(
                subject_id="sub001",
                subjects_dir=temp_dir,
                output_format="table"
            )
            
            assert result.status == "success"
            assert result.data["output_format"] == "table"
            assert any("aparcstats2table" in cmd for cmd in result.data["commands"])
    
    def test_run_missing_subject(self):
        """Test error handling for missing subject."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.tool._run(
                subject_id="nonexistent",
                subjects_dir=temp_dir
            )
            assert result.status == "error"
            assert "Subject directory not found" in result.error


class TestFreeSurferVolumetricTool(unittest.TestCase):
    """Test FreeSurfer volumetric tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = FreeSurferVolumetricTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "freesurfer_volumetric"
        assert "volumetric measurements" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == FreeSurferVolumetricArgs
    
    def test_run_volumetric_extraction(self):
        """Test volumetric measurement extraction."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock subject directory structure
            subject_dir = Path(temp_dir) / "sub001"
            mri_dir = subject_dir / "mri"
            mri_dir.mkdir(parents=True)
            
            # Create mock segmentation file
            seg_file = mri_dir / "aseg.mgz"
            seg_file.touch()
            norm_file = mri_dir / "norm.mgz"
            norm_file.touch()
            
            result = self.tool._run(
                subject_id="sub001",
                subjects_dir=temp_dir,
                segmentation="aseg"
            )
            
            assert result.status == "success"
            assert result.data["segmentation"] == "aseg"
            assert any("mri_segstats" in cmd for cmd in result.data["commands"])
    
    def test_run_etiv_only(self):
        """Test eTIV-only extraction."""
        with tempfile.TemporaryDirectory() as temp_dir:
            subject_dir = Path(temp_dir) / "sub001"
            mri_dir = subject_dir / "mri"
            mri_dir.mkdir(parents=True)
            
            seg_file = mri_dir / "aseg.mgz"
            seg_file.touch()
            
            result = self.tool._run(
                subject_id="sub001",
                subjects_dir=temp_dir,
                etiv_only=True
            )
            
            assert result.status == "success"
            assert result.data["etiv_only"] is True
            assert any("--etiv-only" in cmd for cmd in result.data["commands"])
    
    def test_run_missing_segmentation(self):
        """Test error handling for missing segmentation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            subject_dir = Path(temp_dir) / "sub001"
            subject_dir.mkdir(parents=True)
            
            result = self.tool._run(
                subject_id="sub001",
                subjects_dir=temp_dir,
                segmentation="aseg"
            )
            
            assert result.status == "error"
            assert "Segmentation file not found" in result.error


class TestFreeSurferQCTool(unittest.TestCase):
    """Test FreeSurfer QC tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = FreeSurferQCTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "freesurfer_qc"
        assert "quality control" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == FreeSurferQCArgs
    
    def test_run_qc_checks(self):
        """Test QC check execution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock subject directory structure
            subject_dir = Path(temp_dir) / "sub001"
            (subject_dir / "surf").mkdir(parents=True)
            (subject_dir / "mri").mkdir(parents=True)
            (subject_dir / "label").mkdir(parents=True)
            
            # Create mock surface files
            for hemi in ["lh", "rh"]:
                (subject_dir / "surf" / f"{hemi}.orig").touch()
                (subject_dir / "surf" / f"{hemi}.pial").touch()
                (subject_dir / "surf" / f"{hemi}.white").touch()
            
            # Create mock segmentation
            (subject_dir / "mri" / "aseg.mgz").touch()
            (subject_dir / "mri" / "brain.mgz").touch()
            (subject_dir / "mri" / "norm.mgz").touch()
            
            output_dir = os.path.join(temp_dir, "qc")
            
            result = self.tool._run(
                subject_id="sub001",
                subjects_dir=temp_dir,
                output_dir=output_dir,
                checks=["surfaces", "aseg"]
            )
            
            assert result.status == "success"
            assert result.data["checks"] == ["surfaces", "aseg"]
            assert os.path.exists(result.data["script_file"])
            
            # Check report file
            report_file = Path(result.data["report_file"])
            assert report_file.exists()
            report = json.loads(report_file.read_text())
            assert report["subject_id"] == "sub001"
            assert report["checks_performed"] == ["surfaces", "aseg"]
    
    def test_run_with_screenshots(self):
        """Test QC with screenshot generation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            subject_dir = Path(temp_dir) / "sub001"
            (subject_dir / "surf").mkdir(parents=True)
            (subject_dir / "mri").mkdir(parents=True)
            
            # Create mock files
            for hemi in ["lh", "rh"]:
                (subject_dir / "surf" / f"{hemi}.pial").touch()
            (subject_dir / "mri" / "aseg.mgz").touch()
            (subject_dir / "mri" / "brain.mgz").touch()
            
            output_dir = os.path.join(temp_dir, "qc")
            
            result = self.tool._run(
                subject_id="sub001",
                subjects_dir=temp_dir,
                output_dir=output_dir,
                checks=["surfaces", "aseg"],
                screenshots=True
            )
            
            assert result.status == "success"
            assert any("freeview" in cmd for cmd in result.data["commands"])
            assert any("-ss" in cmd for cmd in result.data["commands"])
    
    def test_run_snr_check(self):
        """Test SNR measurement check."""
        with tempfile.TemporaryDirectory() as temp_dir:
            subject_dir = Path(temp_dir) / "sub001"
            (subject_dir / "surf").mkdir(parents=True)
            (subject_dir / "mri").mkdir(parents=True)
            
            (subject_dir / "mri" / "norm.mgz").touch()
            (subject_dir / "mri" / "aseg.mgz").touch()
            
            output_dir = os.path.join(temp_dir, "qc")
            
            result = self.tool._run(
                subject_id="sub001",
                subjects_dir=temp_dir,
                output_dir=output_dir,
                checks=["snr"]
            )
            
            assert result.status == "success"
            assert any("mri_cnr" in cmd for cmd in result.data["commands"])
    
    def test_run_missing_subject(self):
        """Test error handling for missing subject."""
        with tempfile.TemporaryDirectory() as temp_dir:
            qc_dir = Path(temp_dir) / "qc"
            result = self.tool._run(
                subject_id="nonexistent",
                subjects_dir=temp_dir,
                output_dir=str(qc_dir),
            )
            assert result.status == "error"
            assert "Subject directory not found" in result.error


class TestIntegration(unittest.TestCase):
    """Integration tests for FreeSurfer tools."""
    
    def test_tools_collection(self):
        """Test getting all FreeSurfer tools."""
        tools = FreeSurferTools.get_all_tools()
        
        assert len(tools) == 4
        assert any(isinstance(t, FreeSurferReconAllTool) for t in tools)
        assert any(isinstance(t, FreeSurferParcellationTool) for t in tools)
        assert any(isinstance(t, FreeSurferVolumetricTool) for t in tools)
        assert any(isinstance(t, FreeSurferQCTool) for t in tools)
    
    def test_stage_enum_values(self):
        """Test ReconAllStage enum values."""
        assert ReconAllStage.AUTORECON1 == "autorecon1"
        assert ReconAllStage.AUTORECON2 == "autorecon2"
        assert ReconAllStage.AUTORECON3 == "autorecon3"
        assert ReconAllStage.AUTORECON_ALL == "all"
    
    def test_atlas_enum_values(self):
        """Test ParcellationAtlas enum values."""
        assert ParcellationAtlas.DESIKAN_KILLIANY == "aparc"
        assert ParcellationAtlas.DESTRIEUX == "aparc.a2009s"
        assert ParcellationAtlas.DKT == "aparc.DKTatlas"
    
    def test_measure_enum_values(self):
        """Test SurfaceMeasure enum values."""
        assert SurfaceMeasure.THICKNESS == "thickness"
        assert SurfaceMeasure.AREA == "area"
        assert SurfaceMeasure.VOLUME == "volume"
        assert SurfaceMeasure.CURVATURE == "curv"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
