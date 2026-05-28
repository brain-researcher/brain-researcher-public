import pytest
pytest.skip("real-data multimodal tests skipped (requires deps)", allow_module_level=True)
#!/usr/bin/env python3
"""
Comprehensive test script for Multimodal Integration tools.

This script tests various multimodal fusion techniques for combining
different neuroimaging modalities (fMRI, sMRI, DTI, MEG/EEG, PET).
"""

import json
import os
import pytest
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

# Add project to path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import multimodal integration tools
from brain_researcher.services.tools.tool_registry import ToolRegistry
from brain_researcher.services.tools.multimodal_integration_tool import (
    MultimodalIntegrationTool, MultimodalFusionArgs
)

# Dataset paths
DATASET_ROOT = "/app/data/openneuro/ds000114"
MEG_DATASET = "/app/data/openneuro/ds000117"
MNE_SAMPLE = "/app/data/mne/sample"
OUTPUT_DIR = str(REPO_ROOT / "outputs" / "test_outputs" / "multimodal")

# Create output directory
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# Performance tracking
performance_metrics = {
    "tool_timings": {},
    "memory_usage": {},
    "success_rate": {},
    "errors": [],
    "fusion_results": {}
}


def print_section(title: str, level: int = 1):
    """Print a formatted section header."""
    if level == 1:
        print("\n" + "=" * 70)
        print(f" {title}")
        print("=" * 70)
    elif level == 2:
        print("\n" + "-" * 60)
        print(f" {title}")
        print("-" * 60)
    else:
        print(f"\n### {title}")


def measure_performance(func):
    """Decorator to measure function performance."""
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            import psutil
            process = psutil.Process()
            mem_before = process.memory_info().rss / 1024 / 1024  # MB
        except ImportError:
            mem_before = 0
        
        result = func(*args, **kwargs)
        
        elapsed_time = time.time() - start_time
        try:
            mem_after = process.memory_info().rss / 1024 / 1024  # MB
            mem_used = mem_after - mem_before
        except:
            mem_used = 0
        
        func_name = func.__name__
        performance_metrics["tool_timings"][func_name] = elapsed_time
        performance_metrics["memory_usage"][func_name] = mem_used
        
        print(f"⏱️  Time: {elapsed_time:.2f}s | 💾 Memory: {mem_used:.1f}MB")
        
        return result
    return wrapper


def handle_result(result, tool_name: str) -> bool:
    """Process and display tool result."""
    success = False
    
    if hasattr(result, 'status'):
        success = result.status == "success"
        status_icon = "✅" if success else "❌"
        print(f"{status_icon} {tool_name}: {result.status}")
        
        if result.data:
            if isinstance(result.data, dict):
                # Show key metrics
                for key in ["n_modalities", "fusion_method", "n_components", 
                           "explained_variance", "correlation", "n_features"]:
                    if key in result.data:
                        value = result.data[key]
                        if isinstance(value, float):
                            print(f"  {key}: {value:.4f}")
                        elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], float):
                            print(f"  {key}: {[f'{v:.4f}' for v in value[:3]]}")
                        else:
                            print(f"  {key}: {value}")
        
        if result.error:
            print(f"  ⚠️ Error: {result.error}")
            performance_metrics["errors"].append({
                "tool": tool_name,
                "error": str(result.error)
            })
    else:
        success = result.get("success", False)
        status_icon = "✅" if success else "❌"
        print(f"{status_icon} {tool_name}")
        
        if result.get("message"):
            print(f"  Message: {result['message'][:200]}")
    
    return success


def generate_multimodal_synthetic_data():
    """Generate synthetic multimodal neuroimaging data."""
    np.random.seed(42)
    
    n_subjects = 30
    n_timepoints = 200
    n_voxels = 500
    n_rois = 90
    n_channels = 64
    
    # Create correlated multimodal data with shared and unique components
    
    # Shared latent factors
    n_shared_components = 5
    shared_factors = np.random.randn(n_subjects, n_shared_components)
    
    # fMRI: temporal dynamics (subjects x timepoints x voxels)
    fmri_unique = np.random.randn(n_subjects, n_timepoints, n_voxels) * 0.5
    fmri_shared = np.einsum('sc,tv->stv', shared_factors[:, :3], 
                           np.random.randn(n_timepoints, n_voxels))
    fmri_data = fmri_unique + fmri_shared[:, :n_timepoints, :n_voxels]
    
    # sMRI: structural features (subjects x voxels)
    smri_unique = np.random.randn(n_subjects, n_voxels * 2) * 0.5
    smri_shared = np.dot(shared_factors[:, :2], 
                         np.random.randn(2, n_voxels * 2))
    smri_data = smri_unique + smri_shared
    
    # DTI: connectivity (subjects x ROIs x ROIs)
    dti_data = []
    for i in range(n_subjects):
        # Generate symmetric connectivity matrix
        A = np.random.randn(n_rois, n_rois) * 0.3
        # Add subject-specific variation based on shared factors
        A += shared_factors[i, 0] * 0.1
        conn = np.dot(A, A.T)
        conn = (conn - conn.min()) / (conn.max() - conn.min())
        dti_data.append(conn)
    dti_data = np.array(dti_data)
    
    # MEG/EEG: high temporal resolution (subjects x timepoints x channels)
    meg_unique = np.random.randn(n_subjects, n_timepoints * 5, n_channels) * 0.5
    meg_shared = np.einsum('sc,tc->stc', shared_factors[:, 1:4], 
                          np.random.randn(n_timepoints * 5, n_channels))
    meg_data = meg_unique + meg_shared[:, :n_timepoints * 5, :n_channels]
    
    # PET: metabolic activity (subjects x voxels)
    pet_unique = np.random.randn(n_subjects, n_voxels) * 0.5
    pet_shared = np.dot(shared_factors[:, 2:4], 
                        np.random.randn(2, n_voxels))
    pet_data = pet_unique + pet_shared
    
    # Generate labels based on shared factors
    labels = (shared_factors[:, 0] > np.median(shared_factors[:, 0])).astype(int)
    
    # Add some structure to make fusion meaningful
    for i in range(n_subjects):
        if labels[i] == 1:
            fmri_data[i, :, :50] += 0.3
            smri_data[i, :100] += 0.3
            pet_data[i, :50] += 0.3
    
    return {
        "fmri": fmri_data,
        "smri": smri_data,
        "dti": dti_data,
        "meg": meg_data,
        "pet": pet_data,
        "labels": labels,
        "n_subjects": n_subjects,
        "shared_factors": shared_factors
    }


@measure_performance
def test_cca_fusion():
    """Test Canonical Correlation Analysis fusion."""
    print_section("CCA - Canonical Correlation Analysis", 2)
    
    tool = MultimodalIntegrationTool()
    
    # Generate synthetic multimodal data
    data = generate_multimodal_synthetic_data()
    
    # Prepare data for CCA (flatten temporal dimensions)
    fmri_flat = data["fmri"].mean(axis=1)  # Average over time
    smri_flat = data["smri"]
    
    modalities = [
        {"data": fmri_flat.tolist(), "name": "fMRI"},
        {"data": smri_flat.tolist(), "name": "sMRI"}
    ]
    
    args = MultimodalFusionArgs(
        modalities=modalities,
        fusion_method="cca",
        n_components=5,
        labels=data["labels"].tolist(),
        validation_split=0.2,
        normalize=True
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "CCA Fusion")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["fusion_results"]["cca"] = {
            "n_modalities": 2,
            "n_components": 5,
            "correlation": result.data.get("correlation"),
            "explained_variance": result.data.get("explained_variance")
        }
    
    return success


@measure_performance
def test_pls_fusion():
    """Test Partial Least Squares fusion."""
    print_section("PLS - Partial Least Squares", 2)
    
    tool = MultimodalIntegrationTool()
    
    # Generate synthetic multimodal data
    data = generate_multimodal_synthetic_data()
    
    # Use fMRI and PET for PLS
    fmri_flat = data["fmri"].mean(axis=1)
    pet_flat = data["pet"]
    
    modalities = [
        {"data": fmri_flat.tolist(), "name": "fMRI"},
        {"data": pet_flat.tolist(), "name": "PET"}
    ]
    
    args = MultimodalFusionArgs(
        modalities=modalities,
        fusion_method="pls",
        n_components=4,
        labels=data["labels"].tolist(),
        validation_split=0.2,
        normalize=True
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "PLS Fusion")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["fusion_results"]["pls"] = {
            "n_modalities": 2,
            "n_components": 4,
            "explained_variance": result.data.get("explained_variance")
        }
    
    return success


@measure_performance
def test_ica_fusion():
    """Test ICA-based multimodal fusion."""
    print_section("ICA - Independent Component Analysis Fusion", 2)
    
    tool = MultimodalIntegrationTool()
    
    # Generate synthetic multimodal data
    data = generate_multimodal_synthetic_data()
    
    # Use multiple modalities for ICA
    fmri_flat = data["fmri"].reshape(data["n_subjects"], -1)[:, :1000]  # Subsample
    smri_flat = data["smri"][:, :1000]
    dti_flat = data["dti"].reshape(data["n_subjects"], -1)[:, :1000]
    
    modalities = [
        {"data": fmri_flat.tolist(), "name": "fMRI"},
        {"data": smri_flat.tolist(), "name": "sMRI"},
        {"data": dti_flat.tolist(), "name": "DTI"}
    ]
    
    args = MultimodalFusionArgs(
        modalities=modalities,
        fusion_method="ica",
        n_components=10,
        labels=data["labels"].tolist(),
        ica_algorithm="fastica",
        max_iter=200,
        normalize=True
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "ICA Fusion")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["fusion_results"]["ica"] = {
            "n_modalities": 3,
            "n_components": 10,
            "algorithm": "fastica"
        }
    
    return success


@measure_performance
def test_nmf_fusion():
    """Test Non-negative Matrix Factorization fusion."""
    print_section("NMF - Non-negative Matrix Factorization", 2)
    
    tool = MultimodalIntegrationTool()
    
    # Generate synthetic multimodal data
    data = generate_multimodal_synthetic_data()
    
    # Make data non-negative for NMF
    fmri_positive = np.abs(data["fmri"].mean(axis=1))
    pet_positive = np.abs(data["pet"])
    
    modalities = [
        {"data": fmri_positive.tolist(), "name": "fMRI"},
        {"data": pet_positive.tolist(), "name": "PET"}
    ]
    
    args = MultimodalFusionArgs(
        modalities=modalities,
        fusion_method="nmf",
        n_components=6,
        labels=data["labels"].tolist(),
        nmf_init="nndsvda",
        max_iter=300,
        normalize=False  # NMF works with non-negative data
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "NMF Fusion")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["fusion_results"]["nmf"] = {
            "n_modalities": 2,
            "n_components": 6,
            "reconstruction_error": result.data.get("reconstruction_error")
        }
    
    return success


@measure_performance
def test_tensor_fusion():
    """Test Tensor decomposition fusion (PARAFAC/Tucker)."""
    print_section("Tensor Decomposition - PARAFAC", 2)
    
    tool = MultimodalIntegrationTool()
    
    # Generate synthetic multimodal data
    data = generate_multimodal_synthetic_data()
    
    # Create 3D tensors for each modality
    # Subsample for computational efficiency
    n_subs = data["n_subjects"]
    n_time = 50
    n_space = 100
    
    fmri_tensor = data["fmri"][:, :n_time, :n_space]
    meg_tensor = data["meg"][:, :n_time, :64]
    
    # Pad MEG to match spatial dimension
    meg_padded = np.zeros((n_subs, n_time, n_space))
    meg_padded[:, :, :64] = meg_tensor
    
    modalities = [
        {"data": fmri_tensor.tolist(), "name": "fMRI", "shape": [n_subs, n_time, n_space]},
        {"data": meg_padded.tolist(), "name": "MEG", "shape": [n_subs, n_time, n_space]}
    ]
    
    args = MultimodalFusionArgs(
        modalities=modalities,
        fusion_method="tensor",
        tensor_method="parafac",
        n_components=5,
        labels=data["labels"].tolist(),
        max_iter=100,
        normalize=True
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "Tensor Fusion")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["fusion_results"]["tensor"] = {
            "n_modalities": 2,
            "n_components": 5,
            "method": "parafac",
            "tensor_shape": [n_subs, n_time, n_space]
        }
    
    return success


@measure_performance
def test_graph_fusion():
    """Test Graph-based multimodal fusion."""
    print_section("Graph-based Fusion", 2)
    
    tool = MultimodalIntegrationTool()
    
    # Generate synthetic multimodal data
    data = generate_multimodal_synthetic_data()
    
    # Use connectivity data and functional data
    dti_flat = data["dti"].reshape(data["n_subjects"], -1)[:, :500]
    fmri_flat = data["fmri"].mean(axis=1)[:, :500]
    
    modalities = [
        {"data": dti_flat.tolist(), "name": "DTI_connectivity"},
        {"data": fmri_flat.tolist(), "name": "fMRI_activation"}
    ]
    
    args = MultimodalFusionArgs(
        modalities=modalities,
        fusion_method="graph",
        graph_method="similarity_network",
        n_neighbors=5,
        labels=data["labels"].tolist(),
        normalize=True
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "Graph Fusion")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["fusion_results"]["graph"] = {
            "n_modalities": 2,
            "method": "similarity_network",
            "n_neighbors": 5
        }
    
    return success


@measure_performance
def test_deep_fusion():
    """Test Deep Learning-based multimodal fusion."""
    print_section("Deep Learning Fusion - Autoencoder", 2)
    
    tool = MultimodalIntegrationTool()
    
    # Generate synthetic multimodal data
    data = generate_multimodal_synthetic_data()
    
    # Use multiple modalities
    fmri_flat = data["fmri"].reshape(data["n_subjects"], -1)[:, :500]
    smri_flat = data["smri"][:, :500]
    pet_flat = data["pet"][:, :500]
    
    modalities = [
        {"data": fmri_flat.tolist(), "name": "fMRI"},
        {"data": smri_flat.tolist(), "name": "sMRI"},
        {"data": pet_flat.tolist(), "name": "PET"}
    ]
    
    args = MultimodalFusionArgs(
        modalities=modalities,
        fusion_method="deep",
        deep_method="autoencoder",
        hidden_dims=[256, 128, 64],
        n_epochs=10,
        batch_size=8,
        learning_rate=0.001,
        labels=data["labels"].tolist(),
        validation_split=0.2,
        normalize=True
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "Deep Fusion")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["fusion_results"]["deep"] = {
            "n_modalities": 3,
            "method": "autoencoder",
            "architecture": [500, 256, 128, 64],
            "loss": result.data.get("loss")
        }
    
    return success


@measure_performance
def test_cross_modal_validation():
    """Test cross-modal validation and prediction."""
    print_section("Cross-Modal Validation", 2)
    
    tool = MultimodalIntegrationTool()
    
    # Generate synthetic multimodal data
    data = generate_multimodal_synthetic_data()
    
    # Test predicting one modality from others
    fmri_flat = data["fmri"].mean(axis=1)
    smri_flat = data["smri"]
    pet_flat = data["pet"]
    
    # Predict PET from fMRI and sMRI
    modalities = [
        {"data": fmri_flat.tolist(), "name": "fMRI"},
        {"data": smri_flat.tolist(), "name": "sMRI"}
    ]
    
    args = MultimodalFusionArgs(
        modalities=modalities,
        fusion_method="cross_modal",
        target_modality={"data": pet_flat.tolist(), "name": "PET"},
        prediction_method="ridge",
        cv_folds=5,
        normalize=True
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "Cross-Modal Validation")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["fusion_results"]["cross_modal"] = {
            "source_modalities": ["fMRI", "sMRI"],
            "target_modality": "PET",
            "prediction_r2": result.data.get("r2_score"),
            "prediction_mse": result.data.get("mse")
        }
    
    return success


def test_multimodal_pipeline():
    """Test complete multimodal integration pipeline."""
    print_section("Multimodal Integration Pipeline", 1)
    
    print("Pipeline: CCA → ICA → Tensor → Deep Fusion → Cross-Modal Validation")
    
    pipeline_results = {}
    
    # Step 1: CCA Fusion
    print_section("Step 1: CCA Fusion", 3)
    cca_success = test_cca_fusion()
    pipeline_results["cca"] = cca_success
    
    # Step 2: ICA Fusion
    print_section("Step 2: ICA Fusion", 3)
    ica_success = test_ica_fusion()
    pipeline_results["ica"] = ica_success
    
    # Step 3: Tensor Decomposition
    print_section("Step 3: Tensor Decomposition", 3)
    tensor_success = test_tensor_fusion()
    pipeline_results["tensor"] = tensor_success
    
    # Step 4: Deep Fusion
    print_section("Step 4: Deep Learning Fusion", 3)
    deep_success = test_deep_fusion()
    pipeline_results["deep"] = deep_success
    
    # Step 5: Cross-Modal Validation
    print_section("Step 5: Cross-Modal Validation", 3)
    cross_modal_success = test_cross_modal_validation()
    pipeline_results["cross_modal"] = cross_modal_success
    
    # Summary
    print_section("Pipeline Summary", 2)
    total_steps = len(pipeline_results)
    successful_steps = sum(pipeline_results.values())
    
    for step, success in pipeline_results.items():
        status = "✅" if success else "❌"
        print(f"  {status} {step}")
    
    print(f"\nPipeline Success Rate: {successful_steps}/{total_steps} ({successful_steps/total_steps*100:.1f}%)")
    
    return pipeline_results


def generate_report():
    """Generate comprehensive test report."""
    print_section("Generating Test Report", 1)
    
    report = {
        "test_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_type": "Multimodal Integration",
        "output_directory": OUTPUT_DIR,
        "performance_metrics": performance_metrics,
        "fusion_methods": {
            "Statistical": ["CCA", "PLS", "ICA", "NMF"],
            "Tensor": ["PARAFAC", "Tucker"],
            "Graph": ["Similarity Network", "Multi-layer Networks"],
            "Deep Learning": ["Autoencoder", "Multi-modal Networks"],
            "Validation": ["Cross-modal Prediction", "Consensus"]
        },
        "modalities_tested": ["fMRI", "sMRI", "DTI", "MEG/EEG", "PET"]
    }
    
    # Calculate overall statistics
    total_tests = len(performance_metrics["tool_timings"])
    successful_tests = sum(1 for tool in performance_metrics.get("success_rate", {}).values() if tool)
    
    report["summary"] = {
        "total_tests": total_tests,
        "successful_tests": successful_tests,
        "success_rate": successful_tests / total_tests * 100 if total_tests > 0 else 0,
        "total_time": sum(performance_metrics["tool_timings"].values()),
        "total_memory": sum(performance_metrics["memory_usage"].values()),
        "errors_count": len(performance_metrics["errors"]),
        "fusion_results": performance_metrics["fusion_results"]
    }
    
    # Save JSON report
    report_file = os.path.join(OUTPUT_DIR, "test_report_multimodal.json")
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"📊 Report saved to: {report_file}")
    
    # Generate markdown report
    md_report = f"""# Multimodal Integration Test Report

## Test Summary
- **Date**: {report['test_date']}
- **Modalities Tested**: {', '.join(report['modalities_tested'])}
- **Output Directory**: {OUTPUT_DIR}

## Performance Metrics
- **Total Tests**: {report['summary']['total_tests']}
- **Successful**: {report['summary']['successful_tests']}
- **Success Rate**: {report['summary']['success_rate']:.1f}%
- **Total Time**: {report['summary']['total_time']:.2f} seconds
- **Total Memory**: {report['summary']['total_memory']:.1f} MB

## Fusion Results Summary
"""
    
    for method, results in performance_metrics["fusion_results"].items():
        md_report += f"\n### {method.upper()}\n"
        for key, value in results.items():
            if isinstance(value, float):
                md_report += f"- {key}: {value:.4f}\n"
            elif isinstance(value, list) and len(value) > 0:
                if isinstance(value[0], float):
                    md_report += f"- {key}: {[f'{v:.4f}' for v in value[:3]]}\n"
                else:
                    md_report += f"- {key}: {value}\n"
            else:
                md_report += f"- {key}: {value}\n"
    
    md_report += "\n## Fusion Methods Tested\n"
    for category, methods in report["fusion_methods"].items():
        md_report += f"\n### {category}\n"
        for method in methods:
            md_report += f"- {method}\n"
    
    md_report += "\n## Tool Timings\n"
    for tool, timing in sorted(performance_metrics["tool_timings"].items()):
        md_report += f"- {tool}: {timing:.2f}s\n"
    
    if performance_metrics["errors"]:
        md_report += "\n## Errors Encountered\n"
        for error in performance_metrics["errors"]:
            md_report += f"- **{error['tool']}**: {error['error']}\n"
    
    md_file = os.path.join(OUTPUT_DIR, "test_report_multimodal.md")
    with open(md_file, 'w') as f:
        f.write(md_report)
    
    print(f"📝 Markdown report saved to: {md_file}")
    
    return report


def main():
    """Run comprehensive multimodal integration tests."""
    print("\n" + "🧠" * 25)
    print("  MULTIMODAL INTEGRATION TEST SUITE")
    print("  Testing fusion of fMRI, sMRI, DTI, MEG/EEG, PET")
    print("🧠" * 25)
    
    # Initialize registry
    print_section("Initializing Tool Registry")
    registry = ToolRegistry(auto_discover=True)
    print(f"Total tools available: {len(registry.tools)}")
    
    # Track results
    all_results = {}
    
    # Run individual fusion tests
    print_section("Individual Fusion Method Tests", 1)
    
    # Statistical Methods
    print_section("Statistical Fusion Methods", 2)
    all_results["cca"] = test_cca_fusion()
    all_results["pls"] = test_pls_fusion()
    all_results["ica"] = test_ica_fusion()
    all_results["nmf"] = test_nmf_fusion()
    
    # Advanced Methods
    print_section("Advanced Fusion Methods", 2)
    all_results["tensor"] = test_tensor_fusion()
    all_results["graph"] = test_graph_fusion()
    all_results["deep"] = test_deep_fusion()
    
    # Validation
    print_section("Cross-Modal Validation", 2)
    all_results["cross_modal"] = test_cross_modal_validation()
    
    # Update success rates
    performance_metrics["success_rate"] = all_results
    
    # Run integration pipeline
    pipeline_results = test_multimodal_pipeline()
    all_results["pipeline"] = all(pipeline_results.values())
    
    # Generate report
    report = generate_report()
    
    # Final summary
    print_section("FINAL TEST SUMMARY", 1)
    
    total = len(all_results)
    passed = sum(all_results.values())
    
    print(f"\n📊 Overall Results:")
    print(f"  Total Tests: {total}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {total - passed}")
    print(f"  Success Rate: {passed/total*100:.1f}%")
    
    print(f"\n📁 Output Directory: {OUTPUT_DIR}")
    print(f"📊 Reports Generated:")
    print(f"  - test_report_multimodal.json")
    print(f"  - test_report_multimodal.md")
    
    # Fusion summary
    if performance_metrics["fusion_results"]:
        print(f"\n🔄 Fusion Methods Tested:")
        for method in performance_metrics["fusion_results"].keys():
            print(f"  - {method}")
    
    return all_results


if __name__ == "__main__":
    try:
        results = main()
        sys.exit(0 if all(results.values()) else 1)
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        traceback.print_exc()
        sys.exit(1)
