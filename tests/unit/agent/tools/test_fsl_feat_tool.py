"""
Tests for FSL FEAT GLM tool implementation.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from brain_researcher.services.tools.fsl_feat_tool import (
    AnalysisLevel,
    DesignMatrix,
    FEATGLMArgs,
    FEATGroupArgs,
    FSLFEATGroupTool,
    FSLFEATNiWrapTool,
    FSLFEATTool,
    MotionCorrection,
    StatThreshold,
)


class TestDesignMatrix(unittest.TestCase):
    """Test design matrix generation."""
    
    def setUp(self):
        """Set up test design matrix."""
        self.design = DesignMatrix(
            n_timepoints=200,
            n_evs=2,
            ev_names=["task", "rest"],
            ev_files=["/tmp/task.txt", "/tmp/rest.txt"],
            contrasts={"task_vs_rest": [1, -1], "rest_vs_task": [-1, 1]},
            tr=2.0
        )
    
    def test_design_matrix_creation(self):
        """Test design matrix is created correctly."""
        assert self.design.n_timepoints == 200
        assert self.design.n_evs == 2
        assert len(self.design.ev_names) == 2
        assert len(self.design.contrasts) == 2
        assert self.design.tr == 2.0
    
    def test_fsf_lines_generation(self):
        """Test FSF file lines are generated correctly."""
        lines = self.design.to_fsf_lines()
        
        # Check basic parameters are present
        assert any("set fmri(npts) 200" in line for line in lines)
        assert any("set fmri(tr) 2.0" in line for line in lines)
        assert any("set fmri(evs_orig) 2" in line for line in lines)
        assert any("set fmri(ncon_orig) 2" in line for line in lines)
        
        # Check EV specifications
        assert any('set fmri(evtitle1) "task"' in line for line in lines)
        assert any('set fmri(evtitle2) "rest"' in line for line in lines)
        assert any('set fmri(custom1) "/tmp/task.txt"' in line for line in lines)
        assert any('set fmri(custom2) "/tmp/rest.txt"' in line for line in lines)
        
        # Check contrast specifications
        assert any('set fmri(conname_orig.1) "task_vs_rest"' in line for line in lines)
        assert any('set fmri(conname_orig.2) "rest_vs_task"' in line for line in lines)
        assert any("set fmri(con_orig1.1) 1" in line for line in lines)
        assert any("set fmri(con_orig1.2) -1" in line for line in lines)


class TestFSLFEATTool(unittest.TestCase):
    """Test FSL FEAT GLM tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = FSLFEATTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "fsl_feat_glm"
        assert "FSL FEAT" in self.tool.get_tool_description()
        assert "GLM analysis" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == FEATGLMArgs
    
    def test_fsf_generation_basic(self):
        """Test basic FSF file generation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test input file
            input_file = os.path.join(temp_dir, "func.nii.gz")
            Path(input_file).touch()
            
            # Create test EV files
            ev_files = {
                "task": os.path.join(temp_dir, "task.txt"),
                "rest": os.path.join(temp_dir, "rest.txt")
            }
            for ev_file in ev_files.values():
                Path(ev_file).touch()
            
            args = FEATGLMArgs(
                input_file=input_file,
                output_dir=temp_dir,
                tr=2.0,
                ev_files=ev_files,
                contrasts={"task_vs_rest": [1, -1]}
            )
            
            fsf_file = self.tool._generate_fsf_file(args, temp_dir)
            
            # Check FSF file was created
            assert os.path.exists(fsf_file)
            
            # Check FSF content
            with open(fsf_file, 'r') as f:
                content = f.read()
                
                # Check basic settings
                assert "set fmri(tr) 2.0" in content
                assert f'set feat_files(1) "{input_file}"' in content
                assert f'set fmri(outputdir) "{temp_dir}"' in content
                
                # Check preprocessing options
                assert "set fmri(smooth) 5.0" in content
                assert "set fmri(temphp_yn) 1" in content
                assert "set fmri(paradigm_hp) 100.0" in content
                assert "set fmri(mc) 1" in content  # MCFLIRT
                
                # Check statistical options
                assert "set fmri(thresh) 3" in content  # Cluster correction
                assert "set fmri(z_thresh) 3.1" in content
                assert "set fmri(prob_thresh) 0.05" in content
    
    def test_fsf_generation_with_confounds(self):
        """Test FSF generation with confound regressors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "func.nii.gz")
            Path(input_file).touch()
            
            ev_files = {"task": os.path.join(temp_dir, "task.txt")}
            Path(ev_files["task"]).touch()
            
            confound_file = os.path.join(temp_dir, "motion.txt")
            Path(confound_file).touch()
            
            args = FEATGLMArgs(
                input_file=input_file,
                output_dir=temp_dir,
                tr=2.0,
                ev_files=ev_files,
                contrasts={"task": [1]},
                confound_evs={"motion": confound_file}
            )
            
            fsf_file = self.tool._generate_fsf_file(args, temp_dir)
            
            with open(fsf_file, 'r') as f:
                content = f.read()
                assert 'set fmri(evtitle2) "motion"' in content
                assert f'set fmri(custom2) "{confound_file}"' in content
                assert "set fmri(convolve2) 0" in content  # No convolution for confounds
    
    def test_run_success(self):
        """Test successful FEAT execution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "func.nii.gz")
            Path(input_file).touch()
            
            ev_files = {
                "task": os.path.join(temp_dir, "task.txt"),
                "rest": os.path.join(temp_dir, "rest.txt")
            }
            for ev_file in ev_files.values():
                with open(ev_file, 'w') as f:
                    f.write("10 5 1\n")  # onset duration weight
                    f.write("30 5 1\n")
            
            result = self.tool._run(
                input_file=input_file,
                output_dir=temp_dir,
                tr=2.0,
                ev_files=ev_files,
                contrasts={"task_vs_rest": [1, -1], "rest_vs_task": [-1, 1]}
            )
            
            assert result.status == "success"
            assert "command" in result.data
            assert "feat" in result.data["command"]
            assert "fsf_file" in result.data
            assert result.data["output_dir"] == temp_dir
    
    def test_run_missing_input(self):
        """Test error handling for missing input file."""
        result = self.tool._run(
            input_file="/nonexistent/file.nii.gz",
            output_dir="/tmp/output",
            tr=2.0,
            ev_files={"task": "/tmp/task.txt"},
            contrasts={"task": [1]}
        )
        
        assert result.status == "error"
        assert "not found" in result.error
    
    def test_run_missing_ev_file(self):
        """Test error handling for missing EV file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "func.nii.gz")
            Path(input_file).touch()
            
            result = self.tool._run(
                input_file=input_file,
                output_dir=temp_dir,
                tr=2.0,
                ev_files={"task": "/nonexistent/task.txt"},
                contrasts={"task": [1]}
            )
            
            assert result.status == "error"
            assert "EV file not found" in result.error
    
    @patch('brain_researcher.services.tools.fsl_feat_tool.FSLFEATTool._get_n_timepoints')
    def test_get_n_timepoints_fallback(self, mock_get_n):
        """Test timepoints extraction with fallback."""
        mock_get_n.return_value = 300
        
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "func.nii.gz")
            Path(input_file).touch()
            
            ev_files = {"task": os.path.join(temp_dir, "task.txt")}
            Path(ev_files["task"]).touch()
            
            args = FEATGLMArgs(
                input_file=input_file,
                output_dir=temp_dir,
                tr=2.0,
                ev_files=ev_files,
                contrasts={"task": [1]}
            )
            
            fsf_file = self.tool._generate_fsf_file(args, temp_dir)
            
            with open(fsf_file, 'r') as f:
                content = f.read()
                assert "set fmri(npts) 300" in content
    
    def test_extract_results(self):
        """Test results extraction from FEAT directory."""
        with tempfile.TemporaryDirectory() as feat_dir:
            # Create mock FEAT output structure
            stats_dir = os.path.join(feat_dir, "stats")
            os.makedirs(stats_dir)
            
            # Create mock z-stat files
            Path(os.path.join(stats_dir, "zstat1.nii.gz")).touch()
            Path(os.path.join(stats_dir, "zstat2.nii.gz")).touch()
            
            # Create mock cluster file
            cluster_file = os.path.join(stats_dir, "cluster_zstat1.txt")
            with open(cluster_file, 'w') as f:
                f.write("Cluster Index\tVoxels\tP\tZ-MAX\n")
                f.write("1\t100\t0.001\t4.5\n")
            
            # Create registration directory
            reg_dir = os.path.join(feat_dir, "reg")
            os.makedirs(reg_dir)
            Path(os.path.join(reg_dir, "example_func2standard.mat")).touch()
            Path(os.path.join(reg_dir, "standard.nii.gz")).touch()
            
            # Create design files
            Path(os.path.join(feat_dir, "design.mat")).touch()
            Path(os.path.join(feat_dir, "design.png")).touch()
            Path(os.path.join(feat_dir, "report.html")).touch()
            
            results = self.tool._extract_results(feat_dir)
            
            assert results["feat_dir"] == feat_dir
            assert "zstat1" in results["stats"]
            assert "zstat2" in results["stats"]
            assert "cluster1" in results["clusters"]
            assert "func2standard" in results["registration"]
            assert "matrix" in results["design"]
            assert "image" in results["design"]
            assert "report" in results


class TestFSLFEATGroupTool(unittest.TestCase):
    """Test FSL FEAT group analysis tool."""
    
    def setUp(self):
        """Set up test environment."""
        self.tool = FSLFEATGroupTool()
    
    def test_tool_metadata(self):
        """Test tool metadata is correct."""
        assert self.tool.get_tool_name() == "fsl_feat_group"
        assert "group" in self.tool.get_tool_description()
        assert "FLAME" in self.tool.get_tool_description()
        assert self.tool.get_args_schema() == FEATGroupArgs
    
    def test_run_success(self):
        """Test successful group analysis setup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create mock FEAT directories
            feat_dirs = []
            for i in range(3):
                feat_dir = os.path.join(temp_dir, f"sub{i+1}.feat")
                os.makedirs(feat_dir)
                feat_dirs.append(feat_dir)
            
            output_dir = os.path.join(temp_dir, "group.gfeat")
            
            result = self.tool._run(
                feat_dirs=feat_dirs,
                output_dir=output_dir,
                group_design={"group_mean": [1, 1, 1]},
                mixed_effects=True
            )
            
            assert result.status == "success"
            assert result.data["n_subjects"] == 3
            assert result.data["mixed_effects"] is True
            assert os.path.exists(output_dir)
    
    def test_run_missing_feat_dir(self):
        """Test error handling for missing FEAT directory."""
        result = self.tool._run(
            feat_dirs=["/nonexistent/sub1.feat"],
            output_dir="/tmp/group",
            group_design={"group_mean": [1]}
        )
        
        assert result.status == "error"
        assert "not found" in result.error


class TestIntegration(unittest.TestCase):
    """Integration tests for FSL FEAT tools."""
    
    def test_tools_collection(self):
        """Test getting all FSL FEAT tools."""
        from brain_researcher.services.tools.fsl_feat_tool import FSLFEATTools
        from brain_researcher.services.tools.fsl_feat_tool import FSLFEATNiWrapTool

        tools = FSLFEATTools.get_all_tools()
        assert len(tools) == 3
        assert any(isinstance(t, FSLFEATTool) for t in tools)
        assert any(isinstance(t, FSLFEATGroupTool) for t in tools)
        assert any(isinstance(t, FSLFEATNiWrapTool) for t in tools)
    
    def test_feat_tool_with_all_options(self):
        """Test FEAT tool with all options enabled."""
        tool = FSLFEATTool()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            input_file = os.path.join(temp_dir, "func.nii.gz")
            Path(input_file).touch()
            
            ev_file = os.path.join(temp_dir, "task.txt")
            with open(ev_file, 'w') as f:
                f.write("10 5 1\n")
            
            result = tool._run(
                input_file=input_file,
                output_dir=temp_dir,
                tr=2.0,
                ev_files={"task": ev_file},
                contrasts={"task": [1]},
                analysis_level=AnalysisLevel.FIRST_LEVEL,
                high_pass_filter=128.0,
                smoothing_fwhm=6.0,
                motion_correction=MotionCorrection.MCFLIRT,
                brain_extraction=True,
                registration=True,
                thresh_type=StatThreshold.CLUSTER_CORRECTED,
                z_threshold=2.3,
                p_threshold=0.01
            )
            
            assert result.status == "success"
            assert "feat" in result.data["command"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
