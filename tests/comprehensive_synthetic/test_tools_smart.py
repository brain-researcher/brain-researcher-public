#!/usr/bin/env python
"""
Smart test suite that properly handles each tool's specific requirements.
"""

import os
import json
import tempfile
import numpy as np
from pathlib import Path
import logging
import time
import nibabel as nib
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import the registry to access tools
from brain_researcher.services.tools.tool_registry import ToolRegistry


class SmartToolTester:
    """Test tools with proper argument mapping."""

    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Create test data
        self.test_data = self._create_test_data()

        # Initialize registry
        self.registry = ToolRegistry()

        self.results = {}
        self.timings = {}

    def _create_test_data(self):
        """Create minimal test data."""
        data_dir = self.output_dir / "test_data"
        data_dir.mkdir(exist_ok=True)

        # Create a small test NIfTI
        test_img = np.random.randn(64, 64, 40)
        affine = np.eye(4)
        nii = nib.Nifti1Image(test_img, affine)
        test_nifti = data_dir / "test.nii.gz"
        nib.save(nii, test_nifti)

        # Create fMRI data
        fmri_img = np.random.randn(64, 64, 40, 100)
        fmri_nii = nib.Nifti1Image(fmri_img, affine)
        fmri_path = data_dir / "fmri.nii.gz"
        nib.save(fmri_nii, fmri_path)

        # Create mask
        mask = test_img > 0
        mask_nii = nib.Nifti1Image(mask.astype(np.uint8), affine)
        mask_path = data_dir / "mask.nii.gz"
        nib.save(mask_nii, mask_path)

        # Create design matrix
        design = np.random.randn(100, 3)
        design_path = data_dir / "design.npy"
        np.save(design_path, design)

        # Create DWI data
        dwi_img = np.random.randn(64, 64, 40, 30)
        dwi_nii = nib.Nifti1Image(dwi_img, affine)
        dwi_path = data_dir / "dwi.nii.gz"
        nib.save(dwi_nii, dwi_path)

        # Create bvals/bvecs
        bvals = np.concatenate([[0], np.ones(29) * 1000])
        bvecs = np.random.randn(3, 30)
        bvecs[:, 0] = 0
        bvecs[:, 1:] /= np.linalg.norm(bvecs[:, 1:], axis=0)

        bvals_path = data_dir / "bvals.txt"
        bvecs_path = data_dir / "bvecs.txt"
        np.savetxt(bvals_path, bvals)
        np.savetxt(bvecs_path, bvecs)

        # Create timeseries
        ts = np.random.randn(100, 90)
        ts_path = data_dir / "timeseries.npy"
        np.save(ts_path, ts)

        # Create EEG data
        eeg = np.random.randn(64, 10000)
        eeg_path = data_dir / "eeg.npy"
        np.save(eeg_path, eeg)

        # Create p-values for stats
        pvals = np.random.rand(1000)
        pvals_path = data_dir / "pvalues.npy"
        np.save(pvals_path, pvals)

        # Create predictions and ground truth
        pred = np.random.randn(100)
        gt = pred + np.random.randn(100) * 0.1
        pred_path = data_dir / "predictions.npy"
        gt_path = data_dir / "ground_truth.npy"
        np.save(pred_path, pred)
        np.save(gt_path, gt)

        # Create data and labels for ML
        X = np.random.randn(100, 50)
        y = np.random.randint(0, 2, 100)
        X_path = data_dir / "features.npy"
        y_path = data_dir / "labels.npy"
        np.save(X_path, X)
        np.save(y_path, y)

        # Create BIDS directory structure
        bids_dir = data_dir / "bids"
        bids_dir.mkdir(exist_ok=True)
        (bids_dir / "sub-01" / "func").mkdir(parents=True, exist_ok=True)

        # Create events file
        events = np.array([[0, 1, 1], [10, 1, 2], [20, 1, 1]])
        events_path = data_dir / "events.tsv"
        np.savetxt(events_path, events, delimiter='\t',
                   header='onset\tduration\ttrial_type', comments='')

        return {
            'nifti': str(test_nifti),
            'fmri': str(fmri_path),
            'mask': str(mask_path),
            'design': str(design_path),
            'dwi': str(dwi_path),
            'bvals': str(bvals_path),
            'bvecs': str(bvecs_path),
            'timeseries': str(ts_path),
            'eeg': str(eeg_path),
            'pvalues': str(pvals_path),
            'predictions': str(pred_path),
            'ground_truth': str(gt_path),
            'features': str(X_path),
            'labels': str(y_path),
            'bids_dir': str(bids_dir),
            'events': str(events_path),
            'data_dir': str(data_dir)
        }

    def test_all_tools(self):
        """Test all tools with proper arguments."""

        # Tool-specific argument mappings
        tool_args = {
            # Analysis tools
            'glm_analysis': {
                'fmri_file': self.test_data['fmri'],
                'design_matrix': self.test_data['design'],
                'mask_file': self.test_data['mask'],
                'output_dir': str(self.output_dir / 'glm')
            },
            'contrast_analysis': {
                'fmri_file': self.test_data['fmri'],
                'design_matrix': self.test_data['design'],
                'mask_file': self.test_data['mask'],
                'output_dir': str(self.output_dir / 'contrast')
            },
            'functional_connectivity': {
                'fmri_file': self.test_data['fmri'],
                'mask_file': self.test_data['mask'],
                'output_dir': str(self.output_dir / 'fc')
            },
            'effective_connectivity': {
                'timeseries_file': self.test_data['timeseries'],
                'output_dir': str(self.output_dir / 'ec')
            },
            'dynamic_connectivity': {
                'timeseries_file': self.test_data['timeseries'],
                'output_dir': str(self.output_dir / 'dc')
            },
            'graph_network_analysis': {
                'connectivity_matrix': self.test_data['timeseries'],
                'output_dir': str(self.output_dir / 'graph')
            },

            # Segmentation tools
            'brain_segmentation': {
                'input_image': self.test_data['nifti'],
                'modality': 'T1',
                'output_dir': str(self.output_dir / 'seg')
            },
            'lesion_detection': {
                'flair_image': self.test_data['nifti'],
                't1_image': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'lesion')
            },

            # Preprocessing tools
            'skull_stripping': {
                'input_image': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'skull')
            },
            'bias_field_correction': {
                'input_image': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'bias')
            },
            'coregistration': {
                'moving_image': self.test_data['nifti'],
                'fixed_image': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'coreg')
            },
            'registration_pipeline': {
                'moving_image': self.test_data['nifti'],
                'fixed_image': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'reg')
            },

            # DWI/DTI tools
            'diffusion_tractography': {
                'dwi_file': self.test_data['dwi'],
                'bvals_file': self.test_data['bvals'],
                'bvecs_file': self.test_data['bvecs'],
                'mask_file': self.test_data['mask'],
                'output_dir': str(self.output_dir / 'tract')
            },

            # Perfusion tools
            'asl_perfusion': {
                'asl_file': self.test_data['fmri'],
                'm0_file': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'asl')
            },

            # QSM tools
            'qsm_reconstruction': {
                'phase_file': self.test_data['nifti'],
                'magnitude_file': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'qsm')
            },

            # Stats tools
            'permutation_testing': {
                'data_file': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'perm')
            },
            'multiple_comparison_correction': {
                'pvalues_file': self.test_data['pvalues'],
                'output_dir': str(self.output_dir / 'mcc')
            },
            'validation_metrics': {
                'prediction_file': self.test_data['predictions'],
                'ground_truth_file': self.test_data['ground_truth'],
                'output_dir': str(self.output_dir / 'val')
            },
            'cross_validation': {
                'data_file': self.test_data['features'],
                'labels_file': self.test_data['labels'],
                'output_dir': str(self.output_dir / 'cv')
            },

            # ML tools
            'mvpa_classification': {
                'fmri_file': self.test_data['fmri'],
                'labels_file': self.test_data['labels'][:100],  # Match timepoints
                'mask_file': self.test_data['mask'],
                'output_dir': str(self.output_dir / 'mvpa')
            },
            'encoding_models': {
                'fmri_file': self.test_data['fmri'],
                'stimulus_file': self.test_data['features'],
                'mask_file': self.test_data['mask'],
                'output_dir': str(self.output_dir / 'encode')
            },

            # Meta-analysis
            'meta_analysis': {
                'studies': [
                    {'coordinates': [[10, 20, 30]], 'sample_size': 20},
                    {'coordinates': [[15, 25, 35]], 'sample_size': 25}
                ],
                'output_dir': str(self.output_dir / 'meta')
            },

            # Quality control
            'motion_quantification': {
                'fmri_file': self.test_data['fmri'],
                'output_dir': str(self.output_dir / 'motion')
            },
            'quality_control': {
                'input_image': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'qc')
            },

            # Radiomics
            'radiomics_extraction': {
                'image_file': self.test_data['nifti'],
                'mask_file': self.test_data['mask'],
                'output_dir': str(self.output_dir / 'radiomics')
            },

            # Visualization
            'advanced_brain_plotting': {
                'stat_map': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'plot')
            },
            'interactive_visualization': {
                'image_file': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'viz')
            },

            # Surface analysis
            'surface_analysis': {
                'surface_file': self.test_data['nifti'],
                'output_dir': str(self.output_dir / 'surface')
            },

            # BIDS tools
            'validate_bids': {
                'bids_dir': self.test_data['bids_dir']
            },
            'query_bids_layout': {
                'bids_dir': self.test_data['bids_dir'],
                'query': {}
            },

            # Pipeline tools that need BIDS
            'fmriprep_preprocessing': {
                'bids_dir': self.test_data['bids_dir'],
                'output_dir': str(self.output_dir / 'fmriprep')
            },
            'run_mriqc': {
                'bids_dir': self.test_data['bids_dir'],
                'output_dir': str(self.output_dir / 'mriqc')
            },
            'run_qsiprep': {
                'bids_dir': self.test_data['bids_dir'],
                'output_dir': str(self.output_dir / 'qsiprep')
            },

            # FSL tools
            'fsl_bet': {
                'input_file': self.test_data['nifti'],
                'output_file': str(self.output_dir / 'fsl_bet' / 'brain.nii.gz')
            },
            'fsl_flirt': {
                'input_file': self.test_data['nifti'],
                'reference_file': self.test_data['nifti'],
                'output_file': str(self.output_dir / 'fsl_flirt' / 'aligned.nii.gz')
            },
            'fsl_feat_glm': {
                'input_file': self.test_data['fmri'],
                'tr': 2.0,
                'ev_files': [self.test_data['events']],
                'contrasts': [[1, -1]],
                'output_dir': str(self.output_dir / 'feat')
            },

            # Dataset tools
            'openneuro_download': {
                'dataset_id': 'ds000001',
                'output_dir': str(self.output_dir / 'openneuro')
            },
            'dandi_download': {
                'dandiset_id': '000001',
                'output_dir': str(self.output_dir / 'dandi')
            },
            'neurovault_download_collection': {
                'collection_id': 1,
                'output_dir': str(self.output_dir / 'neurovault')
            }
        }

        # Test each tool
        all_tools = list(self.registry.tools.keys())
        print(f"\nTesting {len(all_tools)} tools...")
        print("=" * 60)

        for i, tool_name in enumerate(all_tools, 1):
            print(f"\n[{i}/{len(all_tools)}] Testing: {tool_name}")

            tool = self.registry.get_tool(tool_name)
            if not tool:
                print(f"  ✗ Tool not found in registry")
                self.results[tool_name] = "NOT_FOUND"
                continue

            # Get arguments for this tool
            args = tool_args.get(tool_name, {})

            # If no specific args, try generic approach
            if not args:
                # Try to infer based on tool name
                if 'fmri' in tool_name or 'functional' in tool_name:
                    args = {'fmri_file': self.test_data['fmri']}
                elif 'structural' in tool_name or 'anat' in tool_name:
                    args = {'input_image': self.test_data['nifti']}
                elif 'dwi' in tool_name or 'diffusion' in tool_name:
                    args = {'dwi_file': self.test_data['dwi']}

                # Always add output_dir if not present
                if 'output_dir' not in args:
                    args['output_dir'] = str(self.output_dir / tool_name)

            # Test the tool
            try:
                start = time.time()
                result = tool._run(**args)
                elapsed = time.time() - start

                if hasattr(result, 'status') and result.status == 'success':
                    print(f"  ✓ SUCCESS ({elapsed:.2f}s)")
                    self.results[tool_name] = "SUCCESS"
                    self.timings[tool_name] = elapsed
                else:
                    error_msg = getattr(result, 'error', 'Unknown error')
                    print(f"  ✗ FAILED: {error_msg}")
                    self.results[tool_name] = f"FAILED: {error_msg}"

            except TypeError as e:
                print(f"  ✗ ARGS ERROR: {str(e)}")
                self.results[tool_name] = f"ARGS_ERROR: {str(e)}"
            except Exception as e:
                print(f"  ✗ ERROR: {str(e)}")
                self.results[tool_name] = f"ERROR: {str(e)}"

        return self.results, self.timings

    def generate_report(self):
        """Generate test report."""
        total = len(self.results)
        successful = sum(1 for r in self.results.values() if r == "SUCCESS")
        failed = sum(1 for r in self.results.values() if "FAILED" in str(r))
        errors = sum(1 for r in self.results.values() if "ERROR" in str(r))

        report = f"""
# Tool Test Report

**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Total Tools**: {total}

## Summary
- ✅ Successful: {successful} ({successful/total*100:.1f}%)
- ❌ Failed: {failed}
- ⚠️ Errors: {errors}

## Successful Tools ({successful})
"""
        for tool, status in sorted(self.results.items()):
            if status == "SUCCESS":
                time_str = f"{self.timings.get(tool, 0):.2f}s"
                report += f"- {tool}: {time_str}\n"

        if failed > 0:
            report += f"\n## Failed Tools ({failed})\n"
            for tool, status in sorted(self.results.items()):
                if "FAILED" in str(status):
                    report += f"- {tool}: {status}\n"

        if errors > 0:
            report += f"\n## Error Tools ({errors})\n"
            for tool, status in sorted(self.results.items()):
                if "ERROR" in str(status):
                    report += f"- {tool}: {status}\n"

        # Save report
        report_path = self.output_dir / "TEST_REPORT.md"
        with open(report_path, 'w') as f:
            f.write(report)

        print(f"\n📊 Report saved to: {report_path}")
        return report


def main():
    """Run smart tool testing."""
    print("\n" + "=" * 60)
    print("SMART TOOL TESTING")
    print("=" * 60)

    # Create test directory
    test_dir = Path("smart_test_output")
    test_dir.mkdir(exist_ok=True)

    # Run tests
    tester = SmartToolTester(test_dir)
    results, timings = tester.test_all_tools()

    # Generate report
    report = tester.generate_report()

    # Summary
    successful = sum(1 for r in results.values() if r == "SUCCESS")
    print(f"\n{'=' * 60}")
    print(f"COMPLETE: {successful}/{len(results)} tools successful")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()