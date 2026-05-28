import pytest
pytest.skip("real-data GNN tests skipped (heavy deps)", allow_module_level=True)
#!/usr/bin/env python3
"""
Comprehensive test script for Deep Learning and Graph Neural Network tools.

This script tests PyTorch-based deep learning models and GNN architectures
using neuroimaging data from available datasets.
"""

import json
import pytest
import os
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

# Import DL and GNN tool implementations
from brain_researcher.services.tools.tool_registry import ToolRegistry
from brain_researcher.services.tools.dl_pytorch_tool import (
    DLPyTorchTool, DLModelArgs
)
from brain_researcher.services.tools.gnn_connectivity_tool import (
    GNNConnectivityTool, GNNArgs
)
from brain_researcher.services.tools.multimodal_integration_tool import (
    MultimodalIntegrationTool, MultimodalFusionArgs
)
from brain_researcher.services.tools.feature_selection_tool import (
    FeatureSelectionTool, FeatureSelectionArgs
)

# Dataset paths
DATASET_ROOT = "/app/data/openneuro/ds000114"
MNE_SAMPLE = "/app/data/mne/sample"
OUTPUT_DIR = str(REPO_ROOT / "outputs" / "test_outputs" / "dl_gnn")

# Create output directory
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

# Performance tracking
performance_metrics = {
    "tool_timings": {},
    "memory_usage": {},
    "success_rate": {},
    "errors": [],
    "model_performance": {}
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
        
        # Check GPU availability
        try:
            import torch
            gpu_available = torch.cuda.is_available()
            if gpu_available:
                torch.cuda.reset_peak_memory_stats()
                gpu_mem_before = torch.cuda.memory_allocated() / 1024 / 1024
        except:
            gpu_available = False
            gpu_mem_before = 0
        
        result = func(*args, **kwargs)
        
        elapsed_time = time.time() - start_time
        try:
            mem_after = process.memory_info().rss / 1024 / 1024  # MB
            mem_used = mem_after - mem_before
        except:
            mem_used = 0
        
        if gpu_available:
            try:
                gpu_mem_after = torch.cuda.max_memory_allocated() / 1024 / 1024
                gpu_mem_used = gpu_mem_after - gpu_mem_before
                print(f"⏱️  Time: {elapsed_time:.2f}s | 💾 RAM: {mem_used:.1f}MB | 🎮 GPU: {gpu_mem_used:.1f}MB")
            except:
                print(f"⏱️  Time: {elapsed_time:.2f}s | 💾 Memory: {mem_used:.1f}MB")
        else:
            print(f"⏱️  Time: {elapsed_time:.2f}s | 💾 Memory: {mem_used:.1f}MB")
        
        func_name = func.__name__
        performance_metrics["tool_timings"][func_name] = elapsed_time
        performance_metrics["memory_usage"][func_name] = mem_used
        
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
                for key in ["model_type", "accuracy", "loss", "n_parameters", 
                           "n_nodes", "n_edges", "fusion_method", "n_modalities"]:
                    if key in result.data:
                        value = result.data[key]
                        if isinstance(value, float):
                            print(f"  {key}: {value:.4f}")
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


def generate_synthetic_neuroimaging_data():
    """Generate synthetic neuroimaging data for testing."""
    np.random.seed(42)
    
    # fMRI-like data: (subjects, timepoints, voxels)
    n_subjects = 20
    n_timepoints = 100
    n_voxels = 1000
    
    fmri_data = np.random.randn(n_subjects, n_timepoints, n_voxels)
    
    # Add some structure
    for i in range(n_subjects):
        if i < n_subjects // 2:
            # Group 1: Higher activation in certain regions
            fmri_data[i, :, :100] += 0.5
        else:
            # Group 2: Different pattern
            fmri_data[i, :, 100:200] += 0.5
    
    # Structural MRI-like data: (subjects, x, y, z)
    smri_data = np.random.randn(n_subjects, 64, 64, 64)
    
    # Connectivity matrices: (subjects, nodes, nodes)
    n_nodes = 90  # Like AAL atlas
    connectivity_data = []
    for i in range(n_subjects):
        # Generate symmetric positive semi-definite matrix
        A = np.random.randn(n_nodes, n_nodes)
        conn = np.dot(A, A.T)
        # Normalize
        conn = (conn - conn.min()) / (conn.max() - conn.min())
        connectivity_data.append(conn)
    connectivity_data = np.array(connectivity_data)
    
    # Labels (binary classification)
    labels = np.array([0] * (n_subjects // 2) + [1] * (n_subjects // 2))
    
    return {
        "fmri": fmri_data,
        "smri": smri_data,
        "connectivity": connectivity_data,
        "labels": labels,
        "n_subjects": n_subjects
    }


@measure_performance
def test_3d_cnn():
    """Test 3D CNN for volumetric MRI classification."""
    print_section("3D CNN - Volumetric Classification", 2)
    
    tool = DLPyTorchTool()
    
    # Generate synthetic volumetric data
    data = generate_synthetic_neuroimaging_data()
    
    args = DLModelArgs(
        model_type="cnn3d",
        data=data["smri"].tolist(),
        labels=data["labels"].tolist(),
        task="classification",
        n_epochs=5,  # Small for testing
        batch_size=4,
        learning_rate=0.001,
        validation_split=0.2,
        device="auto",
        save_path=os.path.join(OUTPUT_DIR, "cnn3d_model.pt")
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "3D CNN")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["model_performance"]["cnn3d"] = {
            "accuracy": result.data.get("accuracy"),
            "loss": result.data.get("loss"),
            "n_parameters": result.data.get("n_parameters")
        }
    
    return success


@measure_performance
def test_lstm_temporal():
    """Test LSTM for temporal dynamics modeling."""
    print_section("LSTM - Temporal Dynamics", 2)
    
    tool = DLPyTorchTool()
    
    # Generate synthetic temporal data
    data = generate_synthetic_neuroimaging_data()
    # Reshape fMRI data for LSTM: (subjects, timepoints, features)
    temporal_data = data["fmri"]
    
    args = DLModelArgs(
        model_type="lstm",
        data=temporal_data.tolist(),
        labels=data["labels"].tolist(),
        task="classification",
        n_epochs=5,
        batch_size=4,
        learning_rate=0.001,
        validation_split=0.2,
        hidden_size=128,
        n_layers=2,
        dropout=0.2,
        bidirectional=True,
        device="auto",
        save_path=os.path.join(OUTPUT_DIR, "lstm_model.pt")
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "LSTM")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["model_performance"]["lstm"] = {
            "accuracy": result.data.get("accuracy"),
            "loss": result.data.get("loss"),
            "n_parameters": result.data.get("n_parameters")
        }
    
    return success


@measure_performance
def test_vae():
    """Test Variational Autoencoder for dimensionality reduction."""
    print_section("VAE - Dimensionality Reduction", 2)
    
    tool = DLPyTorchTool()
    
    # Generate synthetic data
    data = generate_synthetic_neuroimaging_data()
    # Flatten fMRI data for VAE
    flat_data = data["fmri"].reshape(data["n_subjects"], -1)
    
    args = DLModelArgs(
        model_type="vae",
        data=flat_data.tolist(),
        labels=None,  # Unsupervised
        task="reconstruction",
        n_epochs=5,
        batch_size=4,
        learning_rate=0.001,
        latent_dim=32,
        device="auto",
        save_path=os.path.join(OUTPUT_DIR, "vae_model.pt")
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "VAE")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["model_performance"]["vae"] = {
            "reconstruction_loss": result.data.get("loss"),
            "latent_dim": 32,
            "n_parameters": result.data.get("n_parameters")
        }
    
    return success


@measure_performance
def test_transformer():
    """Test Transformer for sequence modeling."""
    print_section("Transformer - Sequence Modeling", 2)
    
    tool = DLPyTorchTool()
    
    # Generate synthetic sequence data
    data = generate_synthetic_neuroimaging_data()
    # Use fMRI temporal data
    sequence_data = data["fmri"]
    
    args = DLModelArgs(
        model_type="transformer",
        data=sequence_data.tolist(),
        labels=data["labels"].tolist(),
        task="classification",
        n_epochs=3,  # Transformers are expensive
        batch_size=2,
        learning_rate=0.0001,
        n_heads=4,
        n_layers=2,
        d_model=128,
        dropout=0.1,
        device="auto",
        save_path=os.path.join(OUTPUT_DIR, "transformer_model.pt")
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "Transformer")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["model_performance"]["transformer"] = {
            "accuracy": result.data.get("accuracy"),
            "loss": result.data.get("loss"),
            "n_parameters": result.data.get("n_parameters")
        }
    
    return success


@measure_performance
def test_gnn_node_classification():
    """Test GNN for node classification in brain networks."""
    print_section("GNN - Node Classification", 2)
    
    tool = GNNConnectivityTool()
    
    # Generate synthetic connectivity data
    data = generate_synthetic_neuroimaging_data()
    
    # Use first subject's connectivity as adjacency
    adjacency = data["connectivity"][0]
    
    # Node features (e.g., regional measures)
    n_nodes = adjacency.shape[0]
    node_features = np.random.randn(n_nodes, 32)
    
    # Node labels (e.g., functional modules)
    node_labels = np.random.choice([0, 1, 2], size=n_nodes)
    
    args = GNNArgs(
        adjacency_matrix=adjacency.tolist(),
        node_features=node_features.tolist(),
        labels=node_labels.tolist(),
        task="node_classification",
        model_type="gcn",
        hidden_dim=64,
        n_layers=2,
        dropout=0.2,
        n_epochs=10,
        learning_rate=0.01,
        device="auto",
        save_path=os.path.join(OUTPUT_DIR, "gnn_node_model.pt")
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "GNN Node Classification")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["model_performance"]["gnn_node"] = {
            "accuracy": result.data.get("accuracy"),
            "n_nodes": n_nodes,
            "model_type": "gcn"
        }
    
    return success


@measure_performance
def test_gnn_graph_classification():
    """Test GNN for whole-brain graph classification."""
    print_section("GNN - Graph Classification", 2)
    
    tool = GNNConnectivityTool()
    
    # Generate synthetic connectivity data
    data = generate_synthetic_neuroimaging_data()
    
    # Multiple graphs (one per subject)
    graphs = []
    for i in range(data["n_subjects"]):
        adjacency = data["connectivity"][i]
        # Simple node features
        node_features = np.mean(adjacency, axis=1).reshape(-1, 1)
        graphs.append({
            "adjacency": adjacency.tolist(),
            "features": node_features.tolist()
        })
    
    args = GNNArgs(
        graphs=graphs,
        labels=data["labels"].tolist(),
        task="graph_classification",
        model_type="gat",  # Graph Attention Network
        hidden_dim=32,
        n_layers=3,
        n_heads=4,
        dropout=0.2,
        n_epochs=10,
        learning_rate=0.001,
        device="auto",
        save_path=os.path.join(OUTPUT_DIR, "gnn_graph_model.pt")
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "GNN Graph Classification")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["model_performance"]["gnn_graph"] = {
            "accuracy": result.data.get("accuracy"),
            "n_graphs": len(graphs),
            "model_type": "gat"
        }
    
    return success


@measure_performance
def test_gnn_link_prediction():
    """Test GNN for link prediction in brain networks."""
    print_section("GNN - Link Prediction", 2)
    
    tool = GNNConnectivityTool()
    
    # Generate synthetic connectivity data
    data = generate_synthetic_neuroimaging_data()
    adjacency = data["connectivity"][0]
    
    # Node features
    n_nodes = adjacency.shape[0]
    node_features = np.random.randn(n_nodes, 16)
    
    # Create train/test edge splits
    edges = []
    edge_labels = []
    for i in range(n_nodes):
        for j in range(i+1, n_nodes):
            edges.append([i, j])
            # Use threshold for binary edges
            edge_labels.append(1 if adjacency[i, j] > 0.5 else 0)
    
    args = GNNArgs(
        adjacency_matrix=adjacency.tolist(),
        node_features=node_features.tolist(),
        edges=edges,
        edge_labels=edge_labels,
        task="link_prediction",
        model_type="graphsage",
        hidden_dim=32,
        n_layers=2,
        dropout=0.1,
        n_epochs=5,
        learning_rate=0.01,
        device="auto",
        save_path=os.path.join(OUTPUT_DIR, "gnn_link_model.pt")
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "GNN Link Prediction")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["model_performance"]["gnn_link"] = {
            "auc": result.data.get("auc", result.data.get("accuracy")),
            "n_edges": len(edges),
            "model_type": "graphsage"
        }
    
    return success


@measure_performance
def test_gnn_community_detection():
    """Test GNN for community detection in brain networks."""
    print_section("GNN - Community Detection", 2)
    
    tool = GNNConnectivityTool()
    
    # Generate synthetic connectivity with community structure
    n_nodes = 60
    n_communities = 3
    
    # Create block-diagonal adjacency matrix
    adjacency = np.zeros((n_nodes, n_nodes))
    nodes_per_community = n_nodes // n_communities
    
    for c in range(n_communities):
        start = c * nodes_per_community
        end = (c + 1) * nodes_per_community
        # Within-community connections
        adjacency[start:end, start:end] = np.random.uniform(0.6, 1.0, 
                                                            (nodes_per_community, nodes_per_community))
    
    # Between-community connections (weaker)
    adjacency += np.random.uniform(0, 0.3, (n_nodes, n_nodes))
    adjacency = (adjacency + adjacency.T) / 2  # Symmetrize
    np.fill_diagonal(adjacency, 0)  # Remove self-loops
    
    # Node features
    node_features = np.random.randn(n_nodes, 16)
    
    args = GNNArgs(
        adjacency_matrix=adjacency.tolist(),
        node_features=node_features.tolist(),
        task="community_detection",
        n_communities=n_communities,
        model_type="gcn",
        hidden_dim=32,
        n_layers=2,
        n_epochs=10,
        learning_rate=0.01,
        device="auto"
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "GNN Community Detection")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["model_performance"]["gnn_community"] = {
            "modularity": result.data.get("modularity"),
            "n_communities": n_communities,
            "n_nodes": n_nodes
        }
    
    return success


@measure_performance
def test_feature_selection():
    """Test feature selection for neuroimaging data."""
    print_section("Feature Selection", 2)
    
    tool = FeatureSelectionTool()
    
    # Generate high-dimensional data
    data = generate_synthetic_neuroimaging_data()
    # Flatten fMRI data
    X = data["fmri"].reshape(data["n_subjects"], -1)
    y = data["labels"]
    
    print(f"  Original features: {X.shape[1]}")
    
    args = FeatureSelectionArgs(
        data=X.tolist(),
        labels=y.tolist(),
        method="mutual_info",
        n_features=100,
        cv_folds=5
    )
    
    result = tool._run(**args.model_dump())
    success = handle_result(result, "Feature Selection")
    
    if hasattr(result, 'data') and result.data:
        performance_metrics["model_performance"]["feature_selection"] = {
            "original_features": X.shape[1],
            "selected_features": result.data.get("n_selected", 100),
            "method": "mutual_info"
        }
    
    return success


def test_dl_gnn_pipeline():
    """Test complete DL/GNN analysis pipeline."""
    print_section("Deep Learning Pipeline", 1)
    
    print("Pipeline: Feature Selection → 3D CNN → LSTM → GNN → Ensemble")
    
    pipeline_results = {}
    
    # Step 1: Feature Selection
    print_section("Step 1: Feature Selection", 3)
    fs_success = test_feature_selection()
    pipeline_results["feature_selection"] = fs_success
    
    # Step 2: 3D CNN
    print_section("Step 2: 3D CNN Classification", 3)
    cnn_success = test_3d_cnn()
    pipeline_results["cnn3d"] = cnn_success
    
    # Step 3: LSTM
    print_section("Step 3: LSTM Temporal Modeling", 3)
    lstm_success = test_lstm_temporal()
    pipeline_results["lstm"] = lstm_success
    
    # Step 4: GNN
    print_section("Step 4: GNN Graph Classification", 3)
    gnn_success = test_gnn_graph_classification()
    pipeline_results["gnn"] = gnn_success
    
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
        "test_type": "Deep Learning and Graph Neural Networks",
        "output_directory": OUTPUT_DIR,
        "performance_metrics": performance_metrics,
        "model_categories": {
            "Deep Learning": ["3D CNN", "LSTM", "VAE", "Transformer"],
            "Graph Neural Networks": ["GCN", "GAT", "GraphSAGE"],
            "Tasks": ["Classification", "Reconstruction", "Link Prediction", "Community Detection"]
        }
    }
    
    # Check GPU availability
    try:
        import torch
        report["gpu_available"] = torch.cuda.is_available()
        if report["gpu_available"]:
            report["gpu_device"] = torch.cuda.get_device_name(0)
    except:
        report["gpu_available"] = False
    
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
        "model_performance": performance_metrics["model_performance"]
    }
    
    # Save JSON report
    report_file = os.path.join(OUTPUT_DIR, "test_report_dl_gnn.json")
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"📊 Report saved to: {report_file}")
    
    # Generate markdown report
    md_report = f"""# Deep Learning & GNN Tools Test Report

## Test Summary
- **Date**: {report['test_date']}
- **GPU Available**: {report.get('gpu_available', False)}
- **Output Directory**: {OUTPUT_DIR}

## Performance Metrics
- **Total Tests**: {report['summary']['total_tests']}
- **Successful**: {report['summary']['successful_tests']}
- **Success Rate**: {report['summary']['success_rate']:.1f}%
- **Total Time**: {report['summary']['total_time']:.2f} seconds
- **Total Memory**: {report['summary']['total_memory']:.1f} MB

## Model Performance Summary
"""
    
    for model, metrics in performance_metrics["model_performance"].items():
        md_report += f"\n### {model.upper()}\n"
        for key, value in metrics.items():
            if isinstance(value, float):
                md_report += f"- {key}: {value:.4f}\n"
            else:
                md_report += f"- {key}: {value}\n"
    
    md_report += "\n## Tool Timings\n"
    for tool, timing in sorted(performance_metrics["tool_timings"].items()):
        md_report += f"- {tool}: {timing:.2f}s\n"
    
    if performance_metrics["errors"]:
        md_report += "\n## Errors Encountered\n"
        for error in performance_metrics["errors"]:
            md_report += f"- **{error['tool']}**: {error['error']}\n"
    
    md_file = os.path.join(OUTPUT_DIR, "test_report_dl_gnn.md")
    with open(md_file, 'w') as f:
        f.write(md_report)
    
    print(f"📝 Markdown report saved to: {md_file}")
    
    return report


def main():
    """Run comprehensive DL/GNN tool tests."""
    print("\n" + "🧠" * 25)
    print("  DEEP LEARNING & GNN TOOLS TEST SUITE")
    print("  Testing PyTorch models and Graph Neural Networks")
    print("🧠" * 25)
    
    # Check PyTorch availability
    try:
        import torch
        print(f"\n📦 PyTorch version: {torch.__version__}")
        print(f"🎮 CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"🎮 GPU: {torch.cuda.get_device_name(0)}")
    except ImportError:
        print("⚠️ PyTorch not installed - tests will use fallback implementations")
    
    # Initialize registry
    print_section("Initializing Tool Registry")
    registry = ToolRegistry(auto_discover=True)
    print(f"Total tools available: {len(registry.tools)}")
    
    # Track results
    all_results = {}
    
    # Run individual tool tests
    print_section("Individual Tool Tests", 1)
    
    # Deep Learning Models
    print_section("Deep Learning Models", 2)
    all_results["cnn3d"] = test_3d_cnn()
    all_results["lstm"] = test_lstm_temporal()
    all_results["vae"] = test_vae()
    all_results["transformer"] = test_transformer()
    
    # Graph Neural Networks
    print_section("Graph Neural Network Models", 2)
    all_results["gnn_node"] = test_gnn_node_classification()
    all_results["gnn_graph"] = test_gnn_graph_classification()
    all_results["gnn_link"] = test_gnn_link_prediction()
    all_results["gnn_community"] = test_gnn_community_detection()
    
    # Feature Selection
    print_section("Feature Engineering", 2)
    all_results["feature_selection"] = test_feature_selection()
    
    # Update success rates
    performance_metrics["success_rate"] = all_results
    
    # Run integration pipeline
    pipeline_results = test_dl_gnn_pipeline()
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
    print(f"  - test_report_dl_gnn.json")
    print(f"  - test_report_dl_gnn.md")
    
    # Model summary
    if performance_metrics["model_performance"]:
        print(f"\n🤖 Models Tested:")
        for model in performance_metrics["model_performance"].keys():
            print(f"  - {model}")
    
    return all_results


if __name__ == "__main__":
    try:
        results = main()
        sys.exit(0 if all(results.values()) else 1)
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        traceback.print_exc()
        sys.exit(1)
