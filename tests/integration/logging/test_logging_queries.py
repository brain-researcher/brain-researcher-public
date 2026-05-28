#!/usr/bin/env python3
"""
Test queries for the enhanced logging system.

This script simulates various neuroimaging analysis queries to test
the complete logging pipeline including tracing, token counting, and export.
"""

import asyncio
import json
import random
import time
from pathlib import Path
from datetime import datetime

# Add project to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from brain_researcher.services.agent.logging.run_recorder import RunRecorder
from brain_researcher.services.agent.logging.token_counter import TokenCounter, UsageTracker
from brain_researcher.services.agent.logging.export import LogExporter
from brain_researcher.services.tools.args_resolver import ArgsResolver


# Test queries covering different neuroimaging tasks
TEST_QUERIES = [
    {
        "id": "connectivity_1",
        "query": "Calculate functional connectivity matrix for subject sub-01 session ses-retest using the Harvard-Oxford atlas with correlation method",
        "tool_candidates": [
            {"name": "connectivity_matrix", "score": 0.92},
            {"name": "seed_based_connectivity", "score": 0.71},
            {"name": "graph_analysis", "score": 0.45}
        ],
        "selected_tool": "connectivity_matrix",
        "args_raw": {
            "subject": "sub-01",
            "session": "ses-retest",
            "atlas": "Harvard-Oxford",
            "method": "correlation"
        },
        "args_resolved": {
            "img": "/data/bids/sub-01/ses-retest/func/sub-01_ses-retest_task-rest_bold.nii.gz",
            "labels_img": "/atlases/HarvardOxford_cort-maxprob-thr25-2mm.nii.gz",
            "kind": "correlation",
            "standardize": True,
            "t_r": 2.0
        },
        "input_files": ["/data/bids/sub-01/ses-retest/func/sub-01_ses-retest_task-rest_bold.nii.gz"],
        "output_files": ["/output/sub-01_ses-retest_connectivity.npy"],
        "success": True
    },
    {
        "id": "glm_1",
        "query": "Run first-level GLM analysis on sub-02 task-nback data with canonical HRF and motion regressors, compute main effects contrast",
        "tool_candidates": [
            {"name": "first_level_glm", "score": 0.95},
            {"name": "glm_contrast", "score": 0.68},
            {"name": "statistical_analysis", "score": 0.52}
        ],
        "selected_tool": "first_level_glm",
        "args_raw": {
            "subject": "sub-02",
            "task": "nback",
            "hrf_model": "canonical",
            "confounds": "motion",
            "contrast": "main_effects"
        },
        "args_resolved": {
            "img": "/data/bids/sub-02/func/sub-02_task-nback_bold.nii.gz",
            "events": "/data/bids/sub-02/func/sub-02_task-nback_events.tsv",
            "confounds": "/data/derivatives/fmriprep/sub-02/func/sub-02_task-nback_desc-confounds_timeseries.tsv",
            "t_r": 2.0,
            "hrf_model": "spm",
            "drift_model": "cosine",
            "high_pass": 0.01,
            "standardize": True
        },
        "input_files": [
            "/data/bids/sub-02/func/sub-02_task-nback_bold.nii.gz",
            "/data/bids/sub-02/func/sub-02_task-nback_events.tsv"
        ],
        "output_files": [
            "/output/sub-02_task-nback_betas.nii.gz",
            "/output/sub-02_task-nback_contrast.nii.gz"
        ],
        "success": True
    },
    {
        "id": "preprocessing_1",
        "query": "Preprocess functional MRI data for sub-03: slice timing correction, motion correction, spatial smoothing with 6mm FWHM",
        "tool_candidates": [
            {"name": "fmri_preprocessing", "score": 0.88},
            {"name": "motion_correction", "score": 0.72},
            {"name": "spatial_smoothing", "score": 0.65}
        ],
        "selected_tool": "fmri_preprocessing",
        "args_raw": {
            "subject": "sub-03",
            "slice_timing": True,
            "motion_correction": True,
            "smoothing_fwhm": 6
        },
        "args_resolved": {
            "img": "/data/bids/sub-03/func/sub-03_task-rest_bold.nii.gz",
            "slice_timing_ref": 0.5,
            "motion_correction": "rigid",
            "smoothing_fwhm": 6.0,
            "standardize": False,
            "detrend": True,
            "high_pass": 0.01
        },
        "input_files": ["/data/bids/sub-03/func/sub-03_task-rest_bold.nii.gz"],
        "output_files": ["/output/sub-03_task-rest_preprocessed.nii.gz"],
        "success": True
    },
    {
        "id": "parcellation_1",
        "query": "Extract mean time series from each ROI in the Schaefer 400 parcellation for group analysis",
        "tool_candidates": [
            {"name": "extract_roi_signals", "score": 0.91},
            {"name": "parcellation_masker", "score": 0.85},
            {"name": "region_extraction", "score": 0.62}
        ],
        "selected_tool": "extract_roi_signals",
        "args_raw": {
            "parcellation": "Schaefer400",
            "aggregation": "mean",
            "purpose": "group_analysis"
        },
        "args_resolved": {
            "img": "/data/bids/derivatives/group/concat_bold.nii.gz",
            "labels_img": "/atlases/Schaefer2018_400Parcels_7Networks_order_FSLMNI152_2mm.nii.gz",
            "strategy": "mean",
            "standardize": True,
            "detrend": True
        },
        "input_files": ["/data/bids/derivatives/group/concat_bold.nii.gz"],
        "output_files": ["/output/schaefer400_timeseries.csv"],
        "success": True
    },
    {
        "id": "mvpa_1",
        "query": "Perform searchlight MVPA analysis to decode task conditions using SVM classifier with 5mm radius",
        "tool_candidates": [
            {"name": "searchlight_analysis", "score": 0.89},
            {"name": "mvpa_classification", "score": 0.83},
            {"name": "pattern_analysis", "score": 0.71}
        ],
        "selected_tool": "searchlight_analysis",
        "args_raw": {
            "analysis_type": "mvpa",
            "classifier": "svm",
            "radius": 5,
            "task": "decode_conditions"
        },
        "args_resolved": {
            "img": "/data/bids/sub-04/func/sub-04_task-localizer_bold.nii.gz",
            "y": [0, 1, 0, 1, 0, 1],  # Simplified labels
            "radius": 5.0,
            "estimator": "svc",
            "cv": 5,
            "n_jobs": -1
        },
        "input_files": ["/data/bids/sub-04/func/sub-04_task-localizer_bold.nii.gz"],
        "output_files": ["/output/sub-04_searchlight_accuracy.nii.gz"],
        "success": True
    },
    {
        "id": "registration_1",
        "query": "Register functional images to MNI152 template using FLIRT with 12 DOF affine transformation",
        "tool_candidates": [
            {"name": "image_registration", "score": 0.87},
            {"name": "flirt_registration", "score": 0.92},
            {"name": "spatial_normalization", "score": 0.75}
        ],
        "selected_tool": "flirt_registration",
        "args_raw": {
            "template": "MNI152",
            "method": "FLIRT",
            "dof": 12,
            "transform": "affine"
        },
        "args_resolved": {
            "in_file": "/data/bids/sub-05/func/sub-05_task-rest_bold.nii.gz",
            "reference": "/templates/MNI152_T1_2mm_brain.nii.gz",
            "dof": 12,
            "cost": "corratio",
            "searchr_x": [-90, 90],
            "searchr_y": [-90, 90],
            "searchr_z": [-90, 90]
        },
        "input_files": ["/data/bids/sub-05/func/sub-05_task-rest_bold.nii.gz"],
        "output_files": [
            "/output/sub-05_task-rest_mni.nii.gz",
            "/output/sub-05_task-rest_mni.mat"
        ],
        "success": False,  # Simulate a failure
        "error": "Registration failed: Cost function did not converge after 1000 iterations"
    },
    {
        "id": "ica_1",
        "query": "Run ICA decomposition on resting-state data to identify 20 independent components for network analysis",
        "tool_candidates": [
            {"name": "ica_decomposition", "score": 0.90},
            {"name": "canonica_ica", "score": 0.84},
            {"name": "network_decomposition", "score": 0.68}
        ],
        "selected_tool": "ica_decomposition",
        "args_raw": {
            "n_components": 20,
            "purpose": "network_analysis",
            "data_type": "resting_state"
        },
        "args_resolved": {
            "img": "/data/bids/sub-06/func/sub-06_task-rest_bold.nii.gz",
            "n_components": 20,
            "algorithm": "infomax",
            "random_state": 42,
            "standardize": True,
            "whiten": True
        },
        "input_files": ["/data/bids/sub-06/func/sub-06_task-rest_bold.nii.gz"],
        "output_files": [
            "/output/sub-06_ica_components.nii.gz",
            "/output/sub-06_ica_timeseries.csv"
        ],
        "success": True
    },
    {
        "id": "graph_theory_1",
        "query": "Calculate graph theory metrics (clustering coefficient, path length, modularity) from functional connectivity matrix",
        "tool_candidates": [
            {"name": "graph_metrics", "score": 0.93},
            {"name": "network_analysis", "score": 0.85},
            {"name": "connectivity_metrics", "score": 0.77}
        ],
        "selected_tool": "graph_metrics",
        "args_raw": {
            "metrics": ["clustering", "path_length", "modularity"],
            "input_type": "connectivity_matrix"
        },
        "args_resolved": {
            "connectivity_matrix": "/output/sub-01_ses-retest_connectivity.npy",
            "threshold": 0.3,
            "metrics": ["clustering_coefficient", "characteristic_path_length", "modularity"],
            "weighted": False
        },
        "input_files": ["/output/sub-01_ses-retest_connectivity.npy"],
        "output_files": ["/output/sub-01_graph_metrics.json"],
        "success": True
    }
]


class QuerySimulator:
    """Simulate query execution with logging."""
    
    def __init__(self, log_path: str = "test_logs"):
        """Initialize simulator."""
        self.recorder = RunRecorder(base_path=log_path)
        self.resolver = ArgsResolver()
        self.usage_tracker = UsageTracker()
        self.log_path = Path(log_path)
    
    async def simulate_query(self, query_data: dict) -> dict:
        """
        Simulate a single query execution through all phases.
        
        Args:
            query_data: Query test data
            
        Returns:
            Execution results
        """
        print(f"\n{'='*60}")
        print(f"Simulating: {query_data['id']}")
        print(f"Query: {query_data['query'][:80]}...")
        
        # Generate trace context (simulating distributed system)
        from brain_researcher.services.agent.logging.run_recorder import generate_trace_id
        trace_id = generate_trace_id() if self.recorder.enable_otel else None
        
        # Phase 1: Planning
        run_id = self.recorder.start("planning", trace_id=trace_id)
        print(f"Run ID: {run_id}")
        
        # Simulate planning delay
        await asyncio.sleep(random.uniform(0.1, 0.3))
        
        planning_log = self.recorder.record_planning(
            query=query_data['query'],
            tool_candidates=query_data['tool_candidates'],
            selected_tool=query_data['selected_tool'],
            llm_provider="google",
            llm_model="gemini-2.0-flash",
            llm_params={
                "temperature": 0.2,
                "max_tokens": 2048,
                "top_p": 0.95
            }
        )
        
        print(f"✓ Planning phase logged (duration: {planning_log['timestamps']['perf']['duration_ms']:.2f}ms)")
        
        # Track token usage
        self.usage_tracker.track_usage(
            session_id=run_id,
            provider="google",
            model="gemini-2.0-flash",
            input_text=query_data['query'],
            output_text=json.dumps(query_data['tool_candidates']),
            timestamp=planning_log['timestamps']['ts_event_utc']
        )
        
        # Phase 2: Execution
        self.recorder.start("execution", run_id=run_id, trace_id=trace_id, 
                          parent_span_id=planning_log.get('trace', {}).get('span_id'))
        
        # Simulate execution delay
        exec_time = random.uniform(1.0, 5.0) if query_data['success'] else random.uniform(0.5, 1.5)
        await asyncio.sleep(exec_time)
        
        execution_log = self.recorder.record_execution(
            query=query_data['query'],
            selected_tool=query_data['selected_tool'],
            args_raw=query_data['args_raw'],
            args_resolved=query_data['args_resolved'],
            validation_ok=query_data['success'],
            validation_errors=[] if query_data['success'] else [query_data.get('error', 'Unknown error')],
            input_files=query_data.get('input_files', []),
            output_files=query_data.get('output_files', []) if query_data['success'] else [],
            exit_code=0 if query_data['success'] else 1,
            plan_cmd=f"python -m brain_researcher.tools.{query_data['selected_tool']}"
        )
        
        status = "✓" if query_data['success'] else "✗"
        print(f"{status} Execution phase logged (duration: {execution_log['timestamps']['perf']['duration_ms']:.2f}ms)")
        
        # Phase 3: Review
        self.recorder.start("review", run_id=run_id, trace_id=trace_id,
                          parent_span_id=execution_log.get('trace', {}).get('span_id'))
        
        # Simulate review delay
        await asyncio.sleep(random.uniform(0.1, 0.2))
        
        # Generate review checks
        checks = []
        if query_data['success']:
            checks = [
                {"item": "output_validation", "result": "OK", "note": "Output files exist and valid"},
                {"item": "performance", "result": "OK", "note": f"Execution time: {exec_time:.2f}s"},
                {"item": "resource_usage", "result": "OK", "note": "Memory usage within limits"}
            ]
            review_status = "PASS"
        else:
            checks = [
                {"item": "error_analysis", "result": "FAILED", "note": query_data.get('error', 'Unknown error')},
                {"item": "recovery_attempted", "result": "FAILED", "note": "No recovery strategy available"}
            ]
            review_status = "FAIL"
        
        review_log = self.recorder.record_review(
            query=query_data['query'],
            status=review_status,
            checks=checks,
            notes=f"Query {query_data['id']} completed with status: {review_status}"
        )
        
        print(f"✓ Review phase logged (status: {review_status})")
        
        # Print trace information if enabled
        if self.recorder.enable_otel and 'trace' in review_log:
            print(f"Trace ID: {review_log['trace']['trace_id']}")
            print(f"Span ID: {review_log['trace']['span_id']}")
        
        return {
            "run_id": run_id,
            "query_id": query_data['id'],
            "success": query_data['success'],
            "total_duration_ms": (
                planning_log['timestamps']['perf']['duration_ms'] +
                execution_log['timestamps']['perf']['duration_ms'] +
                review_log['timestamps']['perf']['duration_ms']
            )
        }
    
    async def run_all_queries(self):
        """Run all test queries."""
        print("\n" + "="*60)
        print("STARTING QUERY SIMULATION")
        print("="*60)
        
        results = []
        for query_data in TEST_QUERIES:
            result = await self.simulate_query(query_data)
            results.append(result)
            
            # Small delay between queries
            await asyncio.sleep(0.5)
        
        # Print summary
        print("\n" + "="*60)
        print("SIMULATION COMPLETE")
        print("="*60)
        
        successful = sum(1 for r in results if r['success'])
        failed = len(results) - successful
        total_time = sum(r['total_duration_ms'] for r in results)
        
        print(f"\nTotal queries: {len(results)}")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total execution time: {total_time:.2f}ms")
        print(f"Average time per query: {total_time/len(results):.2f}ms")
        
        # Print token usage summary
        print("\n" + "="*60)
        print("TOKEN USAGE SUMMARY")
        print("="*60)
        
        for session_id in self.usage_tracker.sessions:
            summary = self.usage_tracker.get_session_summary(session_id)
            if summary:
                print(f"\nSession: {summary['session_id'][:8]}...")
                print(f"  Total tokens: {summary['total_tokens']}")
                print(f"  Estimated cost: ${summary['total_cost_usd']:.4f}")
                print(f"  Calls: {summary['call_count']}")
        
        # Calculate daily projection
        from datetime import datetime
        current_date = datetime.now().strftime("%Y-%m-%d")
        monthly_estimate = self.usage_tracker.estimate_monthly_cost(current_date)
        
        print(f"\nDaily average cost: ${monthly_estimate['daily_average']:.4f}")
        print(f"Projected monthly cost: ${monthly_estimate['projected_month_total']:.2f}")
        
        return results


def test_export_functionality():
    """Test the export utilities."""
    print("\n" + "="*60)
    print("TESTING EXPORT FUNCTIONALITY")
    print("="*60)
    
    exporter = LogExporter(log_path="test_logs")
    
    # Test 1: Export conversation pairs
    print("\nExporting conversation pairs...")
    pairs_count = exporter.export_conversation_pairs(
        output_file="test_logs/conversation_pairs.jsonl",
        min_quality_score=0.5
    )
    print(f"✓ Exported {pairs_count} conversation pairs")
    
    # Test 2: Export tool usage dataset
    print("\nExporting tool usage dataset...")
    tool_count = exporter.export_tool_usage_dataset(
        output_file="test_logs/tool_usage.jsonl",
        include_failures=True
    )
    print(f"✓ Exported {tool_count} tool usage records")
    
    # Test 3: Create train/val/test split
    print("\nCreating dataset splits...")
    splits = exporter.export_evaluation_dataset(
        output_dir="test_logs/splits",
        split_ratio=(0.7, 0.15, 0.15)
    )
    print(f"✓ Created splits - Train: {splits.get('train', 0)}, Val: {splits.get('val', 0)}, Test: {splits.get('test', 0)}")
    
    # Test 4: Generate analytics report
    print("\nGenerating analytics report...")
    analytics = exporter.generate_analytics_report(
        output_file="test_logs/analytics_report.json"
    )
    print(f"✓ Analytics report generated")
    print(f"  Total logs: {analytics['total_logs']}")
    print(f"  By phase: {analytics['by_phase']}")
    print(f"  By status: {analytics['by_status']}")
    
    # Test 5: Export for training in different formats
    print("\nExporting training datasets...")
    
    # JSONL format
    jsonl_count = exporter.export_for_training(
        output_file="test_logs/training_data.jsonl",
        format='jsonl'
    )
    print(f"✓ Exported {jsonl_count} records to JSONL")
    
    # CSV format
    csv_count = exporter.export_for_training(
        output_file="test_logs/training_data.csv",
        format='csv'
    )
    print(f"✓ Exported {csv_count} records to CSV")


async def main():
    """Run all tests."""
    print("="*60)
    print("ENHANCED LOGGING SYSTEM TEST")
    print("="*60)
    
    # Create test directory
    test_dir = Path("test_logs")
    test_dir.mkdir(exist_ok=True)
    
    try:
        # Run query simulation
        simulator = QuerySimulator(log_path="test_logs")
        results = await simulator.run_all_queries()
        
        # Test export functionality
        test_export_functionality()
        
        print("\n" + "="*60)
        print("ALL TESTS COMPLETED SUCCESSFULLY! 🎉")
        print("="*60)
        
        print(f"\nLog files created in: {test_dir.absolute()}")
        print("\nYou can now:")
        print("1. Check the JSONL files in test_logs/sessions/")
        print("2. Review the conversation pairs in test_logs/conversation_pairs.jsonl")
        print("3. Examine the analytics report in test_logs/analytics_report.json")
        print("4. Use the training datasets in test_logs/training_data.*")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    # Run async main
    exit_code = asyncio.run(main())
    sys.exit(exit_code)