"""Mock Tasks for Distributed System Testing

Provides mock task implementations for testing distributed task execution,
load balancing, and fault tolerance scenarios.
"""

import asyncio
import json
import random
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class MockTaskMetrics:
    """Metrics collected during mock task execution"""
    execution_time: float
    cpu_usage: float
    memory_usage: float
    success: bool
    error_message: Optional[str] = None


class MockTaskRegistry:
    """Registry of mock tasks for testing"""
    
    def __init__(self):
        self.tasks = {
            "fmri_preprocessing": self.fmri_preprocessing_task,
            "statistical_analysis": self.statistical_analysis_task,
            "deep_learning": self.deep_learning_task,
            "data_transfer": self.data_transfer_task,
            "quick_task": self.quick_task,
            "long_task": self.long_task,
            "memory_intensive": self.memory_intensive_task,
            "cpu_intensive": self.cpu_intensive_task,
            "failing_task": self.failing_task,
            "intermittent_task": self.intermittent_task
        }
        
    async def fmri_preprocessing_task(self, **kwargs) -> Dict[str, Any]:
        """Mock fMRI preprocessing task"""
        await asyncio.sleep(0.2)  # Simulate processing time
        
        input_file = kwargs.get("input_file", "unknown.nii.gz")
        
        # Simulate preprocessing steps
        steps = [
            "motion_correction",
            "slice_timing_correction", 
            "spatial_smoothing",
            "temporal_filtering"
        ]
        
        results = {
            "input_file": input_file,
            "output_file": input_file.replace(".nii.gz", "_preprocessed.nii.gz"),
            "steps_completed": steps,
            "processing_stats": {
                "motion_parameters": [random.uniform(-2, 2) for _ in range(6)],
                "smoothing_fwhm": 8.0,
                "filter_cutoff": 128.0
            },
            "execution_time": 0.2,
            "success": True
        }
        
        return results
        
    async def statistical_analysis_task(self, **kwargs) -> Dict[str, Any]:
        """Mock statistical analysis task"""
        await asyncio.sleep(0.4)  # Longer processing
        
        design_matrix = kwargs.get("design_matrix", [[1, 0], [0, 1]])
        data_file = kwargs.get("data_file", "preprocessed_data.nii.gz")
        
        # Simulate GLM analysis
        n_voxels = random.randint(50000, 200000)
        n_regressors = len(design_matrix[0]) if design_matrix else 2
        
        results = {
            "input_data": data_file,
            "design_matrix_shape": [len(design_matrix), n_regressors],
            "statistics": {
                "t_statistics": [random.uniform(-5, 5) for _ in range(n_regressors)],
                "p_values": [random.uniform(0, 1) for _ in range(n_regressors)],
                "effect_sizes": [random.uniform(-2, 2) for _ in range(n_regressors)]
            },
            "significant_voxels": random.randint(1000, 20000),
            "total_voxels": n_voxels,
            "analysis_type": "GLM",
            "execution_time": 0.4,
            "success": True
        }
        
        return results
        
    async def deep_learning_task(self, **kwargs) -> Dict[str, Any]:
        """Mock deep learning task"""
        await asyncio.sleep(0.8)  # Intensive processing
        
        model_type = kwargs.get("model_type", "CNN")
        epochs = kwargs.get("epochs", 10)
        batch_size = kwargs.get("batch_size", 32)
        
        # Simulate training metrics
        training_history = []
        for epoch in range(epochs):
            training_history.append({
                "epoch": epoch + 1,
                "loss": random.uniform(0.1, 2.0) * (0.9 ** epoch),  # Decreasing loss
                "accuracy": min(0.99, random.uniform(0.6, 0.9) * (1.1 ** (epoch * 0.1))),
                "val_loss": random.uniform(0.1, 2.5) * (0.85 ** epoch),
                "val_accuracy": min(0.97, random.uniform(0.5, 0.85) * (1.15 ** (epoch * 0.08)))
            })
            
        results = {
            "model_type": model_type,
            "training_config": {
                "epochs": epochs,
                "batch_size": batch_size,
                "learning_rate": 0.001,
                "optimizer": "Adam"
            },
            "training_history": training_history,
            "final_metrics": training_history[-1] if training_history else {},
            "model_size_mb": random.uniform(10, 500),
            "execution_time": 0.8,
            "success": True
        }
        
        return results
        
    async def data_transfer_task(self, **kwargs) -> Dict[str, Any]:
        """Mock data transfer task"""
        await asyncio.sleep(0.1)  # Quick transfer simulation
        
        source = kwargs.get("source", "/data/input/")
        destination = kwargs.get("destination", "/data/output/")
        file_size_mb = kwargs.get("file_size_mb", random.uniform(100, 5000))
        
        # Simulate transfer metrics
        transfer_speed_mbps = random.uniform(100, 1000)
        transfer_time = file_size_mb / transfer_speed_mbps
        
        results = {
            "source": source,
            "destination": destination,
            "file_size_mb": file_size_mb,
            "transfer_speed_mbps": transfer_speed_mbps,
            "transfer_time": transfer_time,
            "checksum": f"sha256:{random.randint(1000000, 9999999)}",
            "compression_ratio": random.uniform(0.6, 0.9),
            "execution_time": 0.1,
            "success": True
        }
        
        return results
        
    async def quick_task(self, **kwargs) -> Dict[str, Any]:
        """Quick task for latency testing"""
        await asyncio.sleep(0.01)
        
        return {
            "task_type": "quick",
            "input_data": kwargs.get("data", "test"),
            "execution_time": 0.01,
            "timestamp": datetime.utcnow().isoformat(),
            "success": True
        }
        
    async def long_task(self, **kwargs) -> Dict[str, Any]:
        """Long-running task for throughput testing"""
        duration = kwargs.get("duration", 2.0)
        await asyncio.sleep(duration)
        
        return {
            "task_type": "long",
            "duration_requested": duration,
            "actual_duration": duration,
            "work_units": int(duration * 100),
            "execution_time": duration,
            "success": True
        }
        
    async def memory_intensive_task(self, **kwargs) -> Dict[str, Any]:
        """Memory-intensive task for resource testing"""
        await asyncio.sleep(0.15)
        
        # Simulate memory usage
        memory_mb = kwargs.get("memory_mb", 100)
        
        # Create large data structure (simulation)
        large_data = list(range(memory_mb * 1000))  # Approximate memory usage
        
        results = {
            "task_type": "memory_intensive",
            "allocated_memory_mb": memory_mb,
            "data_points": len(large_data),
            "peak_memory": memory_mb * 1.2,  # Simulate peak usage
            "memory_efficiency": 0.85,
            "execution_time": 0.15,
            "success": True
        }
        
        # Clean up
        del large_data
        
        return results
        
    async def cpu_intensive_task(self, **kwargs) -> Dict[str, Any]:
        """CPU-intensive task for resource testing"""
        await asyncio.sleep(0.3)
        
        iterations = kwargs.get("iterations", 1000000)
        
        # Simulate CPU work (in actual implementation, would be real computation)
        compute_result = sum(range(min(iterations, 10000)))  # Limit for testing
        
        results = {
            "task_type": "cpu_intensive",
            "iterations": iterations,
            "compute_result": compute_result,
            "cpu_utilization": random.uniform(80, 95),
            "flops": iterations * 2,  # Approximate floating point operations
            "execution_time": 0.3,
            "success": True
        }
        
        return results
        
    async def failing_task(self, **kwargs) -> Dict[str, Any]:
        """Task that always fails for error testing"""
        await asyncio.sleep(0.05)
        
        error_type = kwargs.get("error_type", "ValueError")
        error_message = kwargs.get("error_message", "Simulated task failure")
        
        # Simulate different error types
        if error_type == "ValueError":
            raise ValueError(error_message)
        elif error_type == "RuntimeError":
            raise RuntimeError(error_message)
        elif error_type == "TimeoutError":
            raise TimeoutError(error_message)
        else:
            raise Exception(f"{error_type}: {error_message}")
            
    async def intermittent_task(self, **kwargs) -> Dict[str, Any]:
        """Task that fails intermittently for resilience testing"""
        await asyncio.sleep(0.05)
        
        failure_rate = kwargs.get("failure_rate", 0.3)  # 30% failure rate
        
        if random.random() < failure_rate:
            raise RuntimeError("Intermittent task failure (simulated)")
            
        return {
            "task_type": "intermittent",
            "failure_rate": failure_rate,
            "execution_time": 0.05,
            "attempt_successful": True,
            "success": True
        }


class MockTaskWorkload:
    """Generates workloads for testing distributed systems"""
    
    def __init__(self, task_registry: MockTaskRegistry):
        self.task_registry = task_registry
        
    def generate_balanced_workload(self, total_tasks: int = 100) -> List[Dict[str, Any]]:
        """Generate balanced mix of different task types"""
        tasks = []
        
        task_distribution = {
            "fmri_preprocessing": 0.3,
            "statistical_analysis": 0.25,
            "data_transfer": 0.2,
            "deep_learning": 0.15,
            "quick_task": 0.1
        }
        
        for task_type, proportion in task_distribution.items():
            count = int(total_tasks * proportion)
            
            for i in range(count):
                task = {
                    "task_id": f"{task_type}_{i}",
                    "task_type": task_type,
                    "priority": random.randint(1, 5),
                    "timeout": 300,
                    "parameters": self._get_task_parameters(task_type)
                }
                tasks.append(task)
                
        return tasks
        
    def generate_stress_workload(self, total_tasks: int = 500) -> List[Dict[str, Any]]:
        """Generate high-load workload for stress testing"""
        tasks = []
        
        # Heavy mix for stress testing
        stress_distribution = {
            "memory_intensive": 0.3,
            "cpu_intensive": 0.3,
            "long_task": 0.2,
            "deep_learning": 0.2
        }
        
        for task_type, proportion in stress_distribution.items():
            count = int(total_tasks * proportion)
            
            for i in range(count):
                task = {
                    "task_id": f"stress_{task_type}_{i}",
                    "task_type": task_type,
                    "priority": random.randint(3, 5),  # Higher priority
                    "timeout": 600,
                    "parameters": self._get_stress_parameters(task_type)
                }
                tasks.append(task)
                
        return tasks
        
    def generate_failure_workload(self, total_tasks: int = 50) -> List[Dict[str, Any]]:
        """Generate workload with intentional failures for fault tolerance testing"""
        tasks = []
        
        failure_distribution = {
            "failing_task": 0.3,
            "intermittent_task": 0.4,
            "fmri_preprocessing": 0.3  # Some normal tasks
        }
        
        for task_type, proportion in failure_distribution.items():
            count = int(total_tasks * proportion)
            
            for i in range(count):
                task = {
                    "task_id": f"fault_{task_type}_{i}",
                    "task_type": task_type,
                    "priority": random.randint(1, 3),
                    "timeout": 120,
                    "parameters": self._get_failure_parameters(task_type)
                }
                tasks.append(task)
                
        return tasks
        
    def _get_task_parameters(self, task_type: str) -> Dict[str, Any]:
        """Get parameters for normal task execution"""
        param_sets = {
            "fmri_preprocessing": {
                "input_file": f"subject_{random.randint(1, 100)}.nii.gz",
                "smoothing_fwhm": random.choice([4, 6, 8]),
                "tr": random.uniform(1.0, 3.0)
            },
            "statistical_analysis": {
                "design_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "contrast": [1, -1, 0],
                "data_file": "preprocessed.nii.gz"
            },
            "deep_learning": {
                "model_type": random.choice(["CNN", "RNN", "Transformer"]),
                "epochs": random.randint(5, 20),
                "batch_size": random.choice([16, 32, 64])
            },
            "data_transfer": {
                "source": f"/data/input/dataset_{random.randint(1, 100)}/",
                "destination": f"/data/output/processed_{random.randint(1, 100)}/",
                "file_size_mb": random.uniform(500, 5000)
            },
            "quick_task": {
                "data": f"test_data_{random.randint(1, 1000)}"
            }
        }
        
        return param_sets.get(task_type, {})
        
    def _get_stress_parameters(self, task_type: str) -> Dict[str, Any]:
        """Get parameters for stress testing"""
        stress_params = {
            "memory_intensive": {
                "memory_mb": random.randint(500, 2000)
            },
            "cpu_intensive": {
                "iterations": random.randint(5000000, 20000000)
            },
            "long_task": {
                "duration": random.uniform(5.0, 30.0)
            },
            "deep_learning": {
                "model_type": "Large_Transformer",
                "epochs": random.randint(50, 200),
                "batch_size": 128
            }
        }
        
        return stress_params.get(task_type, {})
        
    def _get_failure_parameters(self, task_type: str) -> Dict[str, Any]:
        """Get parameters for failure testing"""
        failure_params = {
            "failing_task": {
                "error_type": random.choice(["ValueError", "RuntimeError", "TimeoutError"]),
                "error_message": "Controlled failure for testing"
            },
            "intermittent_task": {
                "failure_rate": random.uniform(0.2, 0.5)
            },
            "fmri_preprocessing": self._get_task_parameters("fmri_preprocessing")
        }
        
        return failure_params.get(task_type, {})


# Create global instances for use in tests
mock_task_registry = MockTaskRegistry()
mock_workload_generator = MockTaskWorkload(mock_task_registry)