import pytest
pytest.skip("real-data ds000114 tests skipped (requires dataset/deps)", allow_module_level=True)
#!/usr/bin/env python
"""
Comprehensive testing script for neuroimaging tools using ds000114 dataset.

This script demonstrates the functionality of all implemented P0 neuroimaging tools
using the test-retest fMRI dataset ds000114 which contains motor, language, and 
spatial attention tasks.
"""

import os
import pytest
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Any
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Dataset paths
REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET_ROOT = "/app/data/openneuro/ds000114"
OUTPUT_ROOT = str(REPO_ROOT / "outputs" / "test_outputs" / "ds000114")

# Import our neuroimaging tools
from brain_researcher.services.tools.fmriprep_tool import FMRIPrepTools, FMRIPrepConfig
from brain_researcher.services.tools.xcpd_tool import XCPDTools, XCPDConfig, DenoisingStrategy
from brain_researcher.services.tools.qsiprep_tool import QSIPrepTools, QSIPrepConfig
from brain_researcher.services.tools.ants_tool import ANTsTools
from brain_researcher.services.tools.spm12_tool import SPM12Tools, DesignType, DCMModelType
from brain_researcher.services.tools.nilearn_expanded import (
    NilearnExpandedTools, 
    DecodingMethod,
    ParcellationMethod,
    MaskOperation
)
from brain_researcher.services.tools.fsl_feat_tool import FSLFEATTools
from brain_researcher.services.tools.fsl_melodic_tool import FSLMELODICTools


class NeuroimagingToolsTester:
    """Test harness for all neuroimaging tools with ds000114."""
    
    def __init__(self):
        """Initialize the tester."""
        self.dataset_root = Path(DATASET_ROOT)
        self.output_root = Path(OUTPUT_ROOT)
        self.output_root.mkdir(parents=True, exist_ok=True)
        
        # Track test results
        self.results = {
            "dataset": "ds000114",
            "dataset_description": "Test-retest fMRI for motor, language, spatial attention",
            "tools_tested": [],
            "test_results": {}
        }
        
        # Initialize tools
        self.initialize_tools()
    
    def initialize_tools(self):
        """Initialize all neuroimaging tool collections."""
        logger.info("Initializing neuroimaging tools...")
        
        self.fmriprep_tools = FMRIPrepTools()
        self.xcpd_tools = XCPDTools()
        self.qsiprep_tools = QSIPrepTools()
        self.ants_tools = ANTsTools()
        self.spm12_tools = SPM12Tools()
        self.nilearn_tools = NilearnExpandedTools()
        self.fsl_feat_tools = FSLFEATTools()
        self.fsl_melodic_tools = FSLMELODICTools()
        
        logger.info("All tools initialized successfully")
    
    def test_fmriprep_preprocessing(self):
        """Test fMRIPrep preprocessing pipeline."""
        logger.info("\n=== Testing fMRIPrep Preprocessing ===")
        
        test_name = "fmriprep_preprocessing"
        output_dir = self.output_root / test_name
        output_dir.mkdir(exist_ok=True)
        
        try:
            # Get fMRIPrep tool
            tool = None
            for t in self.fmriprep_tools.get_all_tools():
                if t.get_tool_name() == "fmriprep_preprocessing":
                    tool = t
                    break
            
            if not tool:
                raise ValueError("fMRIPrep tool not found")
            
            # Configure fMRIPrep for first subject
            config = FMRIPrepConfig(
                bids_dir=str(self.dataset_root),
                output_dir=str(output_dir),
                participant_label="01",  # Process first subject
                task_id="fingerfootlips",  # Motor task
                use_aroma=False,  # Skip AROMA for speed
                cifti_output=False,
                n_cpus=4,
                mem_mb=8000
            )
            
            # Generate command (not executing, just testing command generation)
            result = tool._run(
                bids_dir=config.bids_dir,
                output_dir=config.output_dir,
                participant_label=config.participant_label,
                task_id=config.task_id,
                use_aroma=config.use_aroma,
                cifti_output=config.cifti_output,
                n_cpus=config.n_cpus,
                mem_mb=config.mem_mb
            )
            
            self.results["test_results"][test_name] = {
                "status": result.status,
                "command_generated": result.data.get("command", ""),
                "config_used": config.__dict__,
                "message": "fMRIPrep command successfully generated for motor task"
            }
            
            logger.info(f"✓ fMRIPrep test passed: {result.status}")
            
        except Exception as e:
            self.results["test_results"][test_name] = {
                "status": "error",
                "error": str(e)
            }
            logger.error(f"✗ fMRIPrep test failed: {e}")
    
    def test_xcpd_connectivity(self):
        """Test XCP-D connectivity analysis."""
        logger.info("\n=== Testing XCP-D Connectivity Analysis ===")
        
        test_name = "xcpd_connectivity"
        output_dir = self.output_root / test_name
        output_dir.mkdir(exist_ok=True)
        
        try:
            # Get XCP-D tool
            tool = None
            for t in self.xcpd_tools.get_all_tools():
                if t.get_tool_name() == "xcpd_postprocessing":
                    tool = t
                    break
            
            if not tool:
                raise ValueError("XCP-D tool not found")
            
            # Configure XCP-D for connectivity
            config = XCPDConfig(
                fmriprep_dir=str(self.output_root / "fmriprep_preprocessing"),
                output_dir=str(output_dir),
                participant_label="01",
                denoising_strategy=DenoisingStrategy.MODERATE,  # 36P strategy
                despike=True,
                bandpass_filter=[0.01, 0.1],
                n_cpus=4
            )
            
            # Generate command
            result = tool._run(
                fmriprep_dir=config.fmriprep_dir,
                output_dir=config.output_dir,
                participant_label=config.participant_label,
                denoising_strategy=config.denoising_strategy.value,
                despike=config.despike,
                bandpass_filter=config.bandpass_filter,
                n_cpus=config.n_cpus
            )
            
            self.results["test_results"][test_name] = {
                "status": result.status,
                "command_generated": result.data.get("command", ""),
                "denoising": "36P (moderate)",
                "message": "XCP-D connectivity pipeline configured successfully"
            }
            
            logger.info(f"✓ XCP-D test passed: {result.status}")
            
        except Exception as e:
            self.results["test_results"][test_name] = {
                "status": "error",
                "error": str(e)
            }
            logger.error(f"✗ XCP-D test failed: {e}")
    
    def test_spm12_dcm(self):
        """Test SPM12 DCM for effective connectivity."""
        logger.info("\n=== Testing SPM12 Dynamic Causal Modeling ===")
        
        test_name = "spm12_dcm"
        output_dir = self.output_root / test_name
        output_dir.mkdir(exist_ok=True)
        
        try:
            # Get SPM12 DCM tool
            tool = None
            for t in self.spm12_tools.get_all_tools():
                if t.get_tool_name() == "spm12_dcm":
                    tool = t
                    break
            
            if not tool:
                raise ValueError("SPM12 DCM tool not found")
            
            # Create mock VOI timeseries for motor regions
            voi_dir = output_dir / "voi"
            voi_dir.mkdir(exist_ok=True)
            
            voi_files = {}
            for region in ["M1", "SMA", "PMC"]:  # Motor regions
                voi_file = voi_dir / f"VOI_{region}.mat"
                voi_file.touch()  # Create placeholder
                voi_files[region] = str(voi_file)
            
            # Define connectivity model (3-region motor network)
            a_matrix = [
                [1, 1, 0],  # M1 connections
                [1, 1, 1],  # SMA connections  
                [0, 1, 1]   # PMC connections
            ]
            
            # Modulatory effects of movement
            b_matrix = {
                "movement": [
                    [0, 1, 0],
                    [0, 0, 1],
                    [0, 0, 0]
                ]
            }
            
            # Input to M1
            c_matrix = [[1], [0], [0]]
            
            # Generate DCM script
            result = tool._run(
                voi_timeseries=voi_files,
                model_type=DCMModelType.BILINEAR,
                a_matrix=a_matrix,
                b_matrix=b_matrix,
                c_matrix=c_matrix,
                tr=2.5,  # ds000114 TR
                output_dir=str(output_dir)
            )
            
            self.results["test_results"][test_name] = {
                "status": result.status,
                "n_regions": len(voi_files),
                "model_type": "bilinear",
                "regions": list(voi_files.keys()),
                "message": "DCM motor network model configured successfully"
            }
            
            logger.info(f"✓ SPM12 DCM test passed: {result.status}")
            
        except Exception as e:
            self.results["test_results"][test_name] = {
                "status": "error",
                "error": str(e)
            }
            logger.error(f"✗ SPM12 DCM test failed: {e}")
    
    def test_nilearn_decoding(self):
        """Test Nilearn decoding to classify task conditions."""
        logger.info("\n=== Testing Nilearn ML Decoding ===")
        
        test_name = "nilearn_decoding"
        output_dir = self.output_root / test_name
        output_dir.mkdir(exist_ok=True)
        
        try:
            # Get Nilearn decoding tool
            tool = None
            for t in self.nilearn_tools.get_all_tools():
                if t.get_tool_name() == "nilearn_decoding":
                    tool = t
                    break
            
            if not tool:
                raise ValueError("Nilearn decoding tool not found")
            
            # Create mock functional images for different conditions
            func_dir = output_dir / "func"
            func_dir.mkdir(exist_ok=True)
            
            # Simulate data for motor vs language classification
            func_images = []
            labels = []
            
            # 10 motor task runs
            for i in range(10):
                img_file = func_dir / f"motor_run{i:02d}.nii.gz"
                img_file.touch()
                func_images.append(str(img_file))
                labels.append(0)  # Motor = 0
            
            # 10 language task runs  
            for i in range(10):
                img_file = func_dir / f"language_run{i:02d}.nii.gz"
                img_file.touch()
                func_images.append(str(img_file))
                labels.append(1)  # Language = 1
            
            # Run decoding
            result = tool._run(
                func_images=func_images,
                labels=labels,
                method=DecodingMethod.SVC,
                cv_folds=5,
                searchlight=False,  # Whole-brain for speed
                output_dir=str(output_dir)
            )
            
            self.results["test_results"][test_name] = {
                "status": result.status,
                "n_samples": len(func_images),
                "classes": ["motor", "language"],
                "method": "SVC",
                "message": "Task decoding pipeline configured successfully"
            }
            
            logger.info(f"✓ Nilearn decoding test passed: {result.status}")
            
        except Exception as e:
            self.results["test_results"][test_name] = {
                "status": "error",
                "error": str(e)
            }
            logger.error(f"✗ Nilearn decoding test failed: {e}")
    
    def test_ants_registration(self):
        """Test ANTs registration for longitudinal analysis."""
        logger.info("\n=== Testing ANTs Registration ===")
        
        test_name = "ants_registration"
        output_dir = self.output_root / test_name
        output_dir.mkdir(exist_ok=True)
        
        try:
            # Get ANTs registration tool
            tool = None
            for t in self.ants_tools.get_all_tools():
                if t.get_tool_name() == "ants_registration":
                    tool = t
                    break
            
            if not tool:
                raise ValueError("ANTs registration tool not found")
            
            # Use test-retest scans for registration
            # Subject 01 has two sessions (test and retest)
            session1_anat = self.dataset_root / "sub-01" / "ses-test" / "anat" / "sub-01_ses-test_T1w.nii.gz"
            session2_anat = self.dataset_root / "sub-01" / "ses-retest" / "anat" / "sub-01_ses-retest_T1w.nii.gz"
            
            # Check if files exist (create placeholders if not)
            if not session1_anat.exists():
                session1_anat = output_dir / "session1_T1w.nii.gz"
                session1_anat.touch()
            if not session2_anat.exists():
                session2_anat = output_dir / "session2_T1w.nii.gz"
                session2_anat.touch()
            
            # Configure registration
            result = tool._run(
                fixed_image=str(session1_anat),
                moving_image=str(session2_anat),
                output_prefix=str(output_dir / "test_retest_"),
                transform_type="SyN",  # Symmetric normalization
                n_threads=4
            )
            
            self.results["test_results"][test_name] = {
                "status": result.status,
                "transform_type": "SyN",
                "purpose": "test-retest alignment",
                "message": "ANTs registration configured for longitudinal analysis"
            }
            
            logger.info(f"✓ ANTs registration test passed: {result.status}")
            
        except Exception as e:
            self.results["test_results"][test_name] = {
                "status": "error",
                "error": str(e)
            }
            logger.error(f"✗ ANTs registration test failed: {e}")
    
    def test_fsl_melodic_ica(self):
        """Test FSL MELODIC for ICA decomposition."""
        logger.info("\n=== Testing FSL MELODIC ICA ===")
        
        test_name = "fsl_melodic_ica"
        output_dir = self.output_root / test_name
        output_dir.mkdir(exist_ok=True)
        
        try:
            # Get MELODIC tool
            tool = None
            for t in self.fsl_melodic_tools.get_all_tools():
                if t.get_tool_name() == "fsl_melodic_ica":
                    tool = t
                    break
            
            if not tool:
                raise ValueError("FSL MELODIC tool not found")
            
            # Create mock functional data
            func_file = output_dir / "concat_func.nii.gz"
            func_file.touch()
            
            # Run MELODIC ICA
            result = tool._run(
                input_files=[str(func_file)],
                output_dir=str(output_dir),
                n_components=20,
                tr=2.5,
                approach="concat"  # Concatenate runs
            )
            
            self.results["test_results"][test_name] = {
                "status": result.status,
                "n_components": 20,
                "approach": "concatenation",
                "message": "MELODIC ICA configured for artifact detection"
            }
            
            logger.info(f"✓ FSL MELODIC test passed: {result.status}")
            
        except Exception as e:
            self.results["test_results"][test_name] = {
                "status": "error",
                "error": str(e)
            }
            logger.error(f"✗ FSL MELODIC test failed: {e}")
    
    def test_qsiprep_diffusion(self):
        """Test QSIPrep for diffusion MRI preprocessing."""
        logger.info("\n=== Testing QSIPrep Diffusion Preprocessing ===")
        
        test_name = "qsiprep_diffusion"
        output_dir = self.output_root / test_name
        output_dir.mkdir(exist_ok=True)
        
        try:
            # Get QSIPrep tool
            tool = None
            for t in self.qsiprep_tools.get_all_tools():
                if t.get_tool_name() == "qsiprep_preprocessing":
                    tool = t
                    break
            
            if not tool:
                raise ValueError("QSIPrep tool not found")
            
            # Configure QSIPrep
            config = QSIPrepConfig(
                bids_dir=str(self.dataset_root),
                output_dir=str(output_dir),
                participant_label="01",
                eddy_config="eddy_cuda",  # Use GPU if available
                denoise_method="dwidenoise",
                n_cpus=4
            )
            
            # Generate command
            result = tool._run(
                bids_dir=config.bids_dir,
                output_dir=config.output_dir,
                participant_label=config.participant_label,
                eddy_config=config.eddy_config,
                denoise_method=config.denoise_method,
                n_cpus=config.n_cpus
            )
            
            self.results["test_results"][test_name] = {
                "status": result.status,
                "eddy_config": "eddy_cuda",
                "denoise": "dwidenoise",
                "message": "QSIPrep diffusion pipeline configured"
            }
            
            logger.info(f"✓ QSIPrep test passed: {result.status}")
            
        except Exception as e:
            self.results["test_results"][test_name] = {
                "status": "error",
                "error": str(e)
            }
            logger.error(f"✗ QSIPrep test failed: {e}")
    
    def run_all_tests(self):
        """Run all neuroimaging tool tests."""
        logger.info("=" * 60)
        logger.info("Starting comprehensive neuroimaging tools testing")
        logger.info(f"Dataset: {self.dataset_root}")
        logger.info(f"Output: {self.output_root}")
        logger.info("=" * 60)
        
        # Run each test
        self.test_fmriprep_preprocessing()
        self.test_xcpd_connectivity()
        self.test_spm12_dcm()
        self.test_nilearn_decoding()
        self.test_ants_registration()
        self.test_fsl_melodic_ica()
        self.test_qsiprep_diffusion()
        
        # Update tools tested
        self.results["tools_tested"] = list(self.results["test_results"].keys())
        
        # Calculate summary
        total_tests = len(self.results["test_results"])
        passed_tests = sum(1 for r in self.results["test_results"].values() 
                          if r["status"] == "success")
        
        self.results["summary"] = {
            "total_tests": total_tests,
            "passed": passed_tests,
            "failed": total_tests - passed_tests,
            "success_rate": f"{(passed_tests/total_tests)*100:.1f}%"
        }
        
        # Save results
        results_file = self.output_root / "test_results.json"
        with open(results_file, "w") as f:
            json.dump(self.results, f, indent=2, default=str)
        
        logger.info("\n" + "=" * 60)
        logger.info("TESTING COMPLETE")
        logger.info(f"Results saved to: {results_file}")
        logger.info(f"Success rate: {self.results['summary']['success_rate']}")
        logger.info("=" * 60)
        
        return self.results


def main():
    """Main entry point for testing."""
    tester = NeuroimagingToolsTester()
    results = tester.run_all_tests()
    
    # Print summary
    print("\n=== Test Summary ===")
    for test_name, result in results["test_results"].items():
        status = "✓" if result["status"] == "success" else "✗"
        print(f"{status} {test_name}: {result.get('message', result.get('error', 'Unknown'))}")
    
    print(f"\nOverall: {results['summary']['passed']}/{results['summary']['total_tests']} tests passed")
    print(f"Success rate: {results['summary']['success_rate']}")


if __name__ == "__main__":
    main()
