"""Mock Functions for Workflow Debugging Testing

Provides mock function implementations for testing workflow debugging
scenarios including normal execution, errors, and complex data flows.
"""

import asyncio
import json
import random
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass
import numpy as np


class DebugVariableTracker:
    """Tracks variables for debugging test validation"""
    
    def __init__(self):
        self.variable_history = {}
        self.execution_trace = []
        
    def track_variable(self, name: str, value: Any, node_id: str = None):
        """Track variable changes"""
        if name not in self.variable_history:
            self.variable_history[name] = []
            
        self.variable_history[name].append({
            "value": value,
            "timestamp": datetime.utcnow(),
            "node_id": node_id
        })
        
    def trace_execution(self, node_id: str, event: str, metadata: Dict = None):
        """Trace execution events"""
        self.execution_trace.append({
            "node_id": node_id,
            "event": event,
            "timestamp": datetime.utcnow(),
            "metadata": metadata or {}
        })

# Global tracker instance for tests
debug_tracker = DebugVariableTracker()


class MockNeuroimagingFunctions:
    """Mock functions for neuroimaging workflow testing"""
    
    @staticmethod
    async def load_nifti_data(data_path: str = None, subjects: List[str] = None, **kwargs) -> Dict[str, Any]:
        """Mock loading of NIFTI neuroimaging data"""
        debug_tracker.trace_execution("load_raw_data", "start", {"data_path": data_path})
        
        await asyncio.sleep(0.1)  # Simulate I/O time
        
        subjects = subjects or ["sub-01"]
        
        # Simulate loading data for each subject
        loaded_data = {}
        for subject in subjects:
            loaded_data[subject] = {
                "shape": (64, 64, 30, 200),  # x, y, z, timepoints
                "voxel_size": (3.0, 3.0, 4.0),
                "tr": 2.0,
                "timepoints": 200,
                "file_path": f"{data_path}/{subject}_task-rest_bold.nii.gz"
            }
            
        result = {
            "subjects": subjects,
            "data": loaded_data,
            "total_subjects": len(subjects),
            "loading_time": 0.1,
            "data_format": "NIFTI"
        }
        
        debug_tracker.track_variable("raw_data", result, "load_raw_data")
        debug_tracker.trace_execution("load_raw_data", "complete", {"subjects_loaded": len(subjects)})
        
        return result
        
    @staticmethod
    async def check_data_quality(load_nifti_data_result=None, checks: List[str] = None, **kwargs) -> Dict[str, Any]:
        """Mock data quality checking"""
        debug_tracker.trace_execution("quality_check", "start")
        
        await asyncio.sleep(0.05)
        
        data = load_nifti_data_result or {}
        subjects = data.get("subjects", [])
        checks = checks or ["motion", "signal_dropout"]
        
        quality_results = {}
        for subject in subjects:
            subject_qc = {}
            for check in checks:
                if check == "motion":
                    subject_qc["motion"] = {
                        "max_displacement": random.uniform(0.1, 2.0),
                        "mean_fd": random.uniform(0.1, 0.5),
                        "passed": random.uniform(0.1, 2.0) < 1.5
                    }
                elif check == "signal_dropout":
                    subject_qc["signal_dropout"] = {
                        "dropout_percentage": random.uniform(0, 5),
                        "affected_slices": random.randint(0, 3),
                        "passed": random.uniform(0, 5) < 2.0
                    }
                elif check == "artifacts":
                    subject_qc["artifacts"] = {
                        "artifact_count": random.randint(0, 5),
                        "severity": random.choice(["low", "medium", "high"]),
                        "passed": random.randint(0, 5) < 3
                    }
                    
            quality_results[subject] = subject_qc
            
        overall_pass = all(
            all(check_result.get("passed", True) for check_result in subject_qc.values())
            for subject_qc in quality_results.values()
        )
        
        result = {
            "quality_results": quality_results,
            "checks_performed": checks,
            "overall_pass": overall_pass,
            "failed_subjects": [
                subj for subj, qc in quality_results.items()
                if not all(check.get("passed", True) for check in qc.values())
            ]
        }
        
        debug_tracker.track_variable("quality_check_results", result, "quality_check")
        debug_tracker.trace_execution("quality_check", "complete", 
                                    {"overall_pass": overall_pass})
        
        return result
        
    @staticmethod
    async def correct_motion(quality_check_result=None, reference_volume: int = 0, 
                           interpolation: str = "trilinear", **kwargs) -> Dict[str, Any]:
        """Mock motion correction"""
        debug_tracker.trace_execution("motion_correction", "start")
        
        await asyncio.sleep(0.15)  # Simulate processing time
        
        qc_data = quality_check_result or {}
        subjects = list(qc_data.get("quality_results", {}).keys())
        
        correction_results = {}
        for subject in subjects:
            # Simulate motion correction parameters
            correction_results[subject] = {
                "motion_parameters": [
                    [random.uniform(-2, 2) for _ in range(6)]  # 6 motion parameters
                    for _ in range(200)  # 200 timepoints
                ],
                "reference_volume": reference_volume,
                "rms_motion": random.uniform(0.1, 1.0),
                "interpolation": interpolation,
                "corrected_file": f"{subject}_motion_corrected.nii.gz"
            }
            
        result = {
            "motion_correction": correction_results,
            "subjects_processed": len(subjects),
            "reference_volume": reference_volume,
            "processing_time": 0.15
        }
        
        debug_tracker.track_variable("motion_corrected_data", result, "motion_correction")
        debug_tracker.trace_execution("motion_correction", "complete", 
                                    {"subjects_processed": len(subjects)})
        
        return result
        
    @staticmethod  
    async def correct_slice_timing(motion_correction_result=None, tr: float = 2.0,
                                 slice_order: str = "interleaved", **kwargs) -> Dict[str, Any]:
        """Mock slice timing correction"""
        debug_tracker.trace_execution("slice_timing", "start")
        
        await asyncio.sleep(0.1)
        
        motion_data = motion_correction_result or {}
        subjects = list(motion_data.get("motion_correction", {}).keys())
        
        slice_timing_results = {}
        for subject in subjects:
            slice_timing_results[subject] = {
                "tr": tr,
                "slice_order": slice_order,
                "num_slices": 30,
                "slice_times": [i * (tr / 30) for i in range(30)],
                "corrected_file": f"{subject}_slice_time_corrected.nii.gz"
            }
            
        result = {
            "slice_timing": slice_timing_results,
            "tr": tr,
            "slice_order": slice_order,
            "processing_time": 0.1
        }
        
        debug_tracker.track_variable("slice_timing_data", result, "slice_timing")
        debug_tracker.trace_execution("slice_timing", "complete")
        
        return result


class MockProcessingFunctions:
    """Mock functions for general processing workflow testing"""
    
    @staticmethod
    async def reliable_data_loader(data_source: str = None, **kwargs) -> Dict[str, Any]:
        """Reliable data loading function"""
        debug_tracker.trace_execution("reliable_start", "start")
        
        await asyncio.sleep(0.05)
        
        result = {
            "data": f"loaded_from_{data_source}",
            "source": data_source,
            "size": random.randint(1000, 10000),
            "format": "processed",
            "loaded_at": datetime.utcnow().isoformat()
        }
        
        debug_tracker.track_variable("loaded_data", result, "reliable_start")
        debug_tracker.trace_execution("reliable_start", "complete")
        
        return result
        
    @staticmethod
    async def intermittent_processor(reliable_data_loader_result=None, 
                                   failure_rate: float = 0.3,
                                   error_types: List[str] = None, **kwargs) -> Dict[str, Any]:
        """Function that fails intermittently"""
        debug_tracker.trace_execution("flaky_processing", "start")
        
        await asyncio.sleep(0.03)
        
        # Simulate intermittent failures
        if random.random() < failure_rate:
            error_types = error_types or ["ValueError", "RuntimeError"]
            error_type = random.choice(error_types)
            
            debug_tracker.trace_execution("flaky_processing", "error", 
                                        {"error_type": error_type})
            
            if error_type == "ValueError":
                raise ValueError("Intermittent processing failure (simulated)")
            elif error_type == "RuntimeError":
                raise RuntimeError("Runtime error in processing (simulated)")
            else:
                raise Exception(f"{error_type}: Simulated intermittent failure")
                
        # Successful processing
        input_data = reliable_data_loader_result or {}
        
        result = {
            "processed_data": f"processed_{input_data.get('data', 'unknown')}",
            "processing_method": "intermittent_processor",
            "failure_rate": failure_rate,
            "success": True,
            "processed_at": datetime.utcnow().isoformat()
        }
        
        debug_tracker.track_variable("processed_data", result, "flaky_processing")
        debug_tracker.trace_execution("flaky_processing", "complete")
        
        return result
        
    @staticmethod
    async def memory_heavy_operation(intermittent_processor_result=None,
                                   memory_requirement: str = "medium",
                                   allocation_size: str = "1GB", **kwargs) -> Dict[str, Any]:
        """Memory-intensive operation"""
        debug_tracker.trace_execution("memory_intensive", "start")
        
        await asyncio.sleep(0.2)
        
        # Simulate memory allocation based on size
        size_map = {"1GB": 1000000, "2GB": 2000000, "500MB": 500000}
        allocation_items = size_map.get(allocation_size, 1000000)
        
        # Create large data structure (simulated)
        large_data = list(range(min(allocation_items, 100000)))  # Limit for testing
        
        processed_input = intermittent_processor_result or {}
        
        result = {
            "memory_usage": allocation_size,
            "items_allocated": len(large_data),
            "memory_requirement": memory_requirement,
            "input_processed": processed_input.get("processed_data", "none"),
            "peak_memory_mb": allocation_items // 1000,  # Approximate MB
            "processing_time": 0.2
        }
        
        debug_tracker.track_variable("memory_data", result, "memory_intensive")
        debug_tracker.trace_execution("memory_intensive", "complete",
                                    {"memory_allocated": allocation_size})
        
        # Clean up
        del large_data
        
        return result
        
    @staticmethod
    async def parameter_dependent_analysis(memory_heavy_operation_result=None,
                                         critical_param=None,
                                         optional_param: str = "default", **kwargs) -> Dict[str, Any]:
        """Analysis that depends on specific parameters"""
        debug_tracker.trace_execution("parameter_sensitive", "start")
        
        await asyncio.sleep(0.08)
        
        # Check for required parameter
        if critical_param is None:
            debug_tracker.trace_execution("parameter_sensitive", "error",
                                        {"error": "missing_critical_param"})
            raise ValueError("Critical parameter is required but was None")
            
        memory_data = memory_heavy_operation_result or {}
        
        result = {
            "analysis_type": "parameter_dependent",
            "critical_param": critical_param,
            "optional_param": optional_param,
            "input_memory_usage": memory_data.get("memory_usage", "unknown"),
            "analysis_result": f"analyzed_with_{critical_param}",
            "parameters_valid": True
        }
        
        debug_tracker.track_variable("analysis_result", result, "parameter_sensitive")
        debug_tracker.trace_execution("parameter_sensitive", "complete")
        
        return result
        
    @staticmethod
    async def slow_operation(parameter_dependent_analysis_result=None,
                           expected_duration: int = 300,
                           timeout: int = 60, **kwargs) -> Dict[str, Any]:
        """Operation that may timeout"""
        debug_tracker.trace_execution("timeout_prone", "start")
        
        # Simulate operation that takes longer than timeout
        if expected_duration > timeout:
            await asyncio.sleep(timeout / 1000)  # Convert to seconds, but make it short for testing
            debug_tracker.trace_execution("timeout_prone", "timeout",
                                        {"expected": expected_duration, "timeout": timeout})
            raise TimeoutError(f"Operation timed out after {timeout}s (expected {expected_duration}s)")
            
        await asyncio.sleep(0.1)  # Normal operation time
        
        analysis_data = parameter_dependent_analysis_result or {}
        
        result = {
            "operation_type": "slow_operation",
            "duration": expected_duration,
            "timeout_limit": timeout,
            "analysis_input": analysis_data.get("analysis_result", "none"),
            "completed": True,
            "actual_time": 0.1
        }
        
        debug_tracker.track_variable("slow_op_result", result, "timeout_prone")
        debug_tracker.trace_execution("timeout_prone", "complete")
        
        return result


class MockConditionalFunctions:
    """Mock functions for conditional workflow testing"""
    
    @staticmethod
    async def load_input(input_type: str = "numeric", **kwargs) -> Dict[str, Any]:
        """Load input data with variable type"""
        debug_tracker.trace_execution("data_input", "start")
        
        await asyncio.sleep(0.02)
        
        # Generate different types of data based on input_type
        data_generators = {
            "numeric": lambda: [random.uniform(0, 100) for _ in range(100)],
            "categorical": lambda: [random.choice(["A", "B", "C", "D"]) for _ in range(100)],
            "mixed": lambda: [
                random.uniform(0, 100) if i % 2 == 0 else random.choice(["X", "Y", "Z"])
                for i in range(100)
            ]
        }
        
        # Randomly choose data type if variable
        if input_type == "variable":
            actual_type = random.choice(["numeric", "categorical", "mixed"])
        else:
            actual_type = input_type
            
        data = data_generators[actual_type]()
        
        result = {
            "data": data,
            "data_type": actual_type,
            "requested_type": input_type,
            "size": len(data),
            "loaded_at": datetime.utcnow().isoformat()
        }
        
        debug_tracker.track_variable("input_data", result, "data_input")
        debug_tracker.track_variable("data_type", actual_type, "data_input")
        debug_tracker.trace_execution("data_input", "complete", {"type": actual_type})
        
        return result
        
    @staticmethod
    async def validate_data_type(load_input_result=None, 
                               expected_types: List[str] = None, **kwargs) -> Dict[str, Any]:
        """Validate the data type"""
        debug_tracker.trace_execution("check_data_type", "start")
        
        await asyncio.sleep(0.01)
        
        input_data = load_input_result or {}
        data_type = input_data.get("data_type", "unknown")
        expected_types = expected_types or ["numeric", "categorical", "mixed"]
        
        is_valid = data_type in expected_types
        
        result = {
            "validated_type": data_type,
            "expected_types": expected_types,
            "is_valid": is_valid,
            "data_size": input_data.get("size", 0),
            "validation_passed": is_valid
        }
        
        debug_tracker.track_variable("validation_result", result, "check_data_type")
        debug_tracker.trace_execution("check_data_type", "complete", 
                                    {"validated_type": data_type})
        
        return result
        
    @staticmethod
    async def process_numeric_data(validate_data_type_result=None, **kwargs) -> Dict[str, Any]:
        """Process numeric data"""
        debug_tracker.trace_execution("numeric_processing", "start")
        
        await asyncio.sleep(0.05)
        
        validation_data = validate_data_type_result or {}
        
        if validation_data.get("validated_type") != "numeric":
            debug_tracker.trace_execution("numeric_processing", "skipped", 
                                        {"reason": "not_numeric_data"})
            return {"skipped": True, "reason": "Data type not numeric"}
            
        # Simulate numeric processing
        result = {
            "processing_type": "numeric",
            "operations": ["normalize", "standardize", "outlier_removal"],
            "mean": random.uniform(40, 60),
            "std": random.uniform(10, 20),
            "outliers_removed": random.randint(0, 5),
            "processed": True
        }
        
        debug_tracker.track_variable("numeric_processed", result, "numeric_processing")
        debug_tracker.trace_execution("numeric_processing", "complete")
        
        return result


class MockIterativeFunctions:
    """Mock functions for iterative/loop workflow testing"""
    
    @staticmethod
    async def setup_iteration(max_iterations: int = 10,
                            convergence_threshold: float = 0.001, **kwargs) -> Dict[str, Any]:
        """Initialize iterative process"""
        debug_tracker.trace_execution("initialize", "start")
        
        await asyncio.sleep(0.01)
        
        result = {
            "iteration": 0,
            "max_iterations": max_iterations,
            "convergence_threshold": convergence_threshold,
            "converged": False,
            "current_error": 1.0,  # Start with high error
            "history": []
        }
        
        debug_tracker.track_variable("iteration_state", result, "initialize")
        debug_tracker.trace_execution("initialize", "complete")
        
        return result
        
    @staticmethod
    async def iterative_processing(setup_iteration_result=None, **kwargs) -> Dict[str, Any]:
        """Perform iterative processing"""
        debug_tracker.trace_execution("iteration_body", "start")
        
        await asyncio.sleep(0.03)
        
        state = setup_iteration_result or {"iteration": 0, "current_error": 1.0, "history": []}
        
        # Simulate iterative improvement
        current_iteration = state.get("iteration", 0) + 1
        previous_error = state.get("current_error", 1.0)
        
        # Error decreases with each iteration (with some noise)
        new_error = previous_error * random.uniform(0.7, 0.9)
        convergence_threshold = state.get("convergence_threshold", 0.001)
        
        converged = new_error < convergence_threshold
        
        # Update history
        history = state.get("history", [])
        history.append({
            "iteration": current_iteration,
            "error": new_error,
            "improvement": previous_error - new_error
        })
        
        result = {
            "iteration": current_iteration,
            "max_iterations": state.get("max_iterations", 10),
            "convergence_threshold": convergence_threshold,
            "current_error": new_error,
            "converged": converged,
            "history": history,
            "improvement": previous_error - new_error
        }
        
        debug_tracker.track_variable("iteration_state", result, "iteration_body")
        debug_tracker.track_variable("current_error", new_error, "iteration_body")
        debug_tracker.track_variable("converged", converged, "iteration_body")
        
        debug_tracker.trace_execution("iteration_body", "complete", 
                                    {"iteration": current_iteration, "converged": converged})
        
        return result


# Create function registry for easy access in tests
MOCK_FUNCTION_REGISTRY = {
    # Neuroimaging functions
    "load_nifti_data": MockNeuroimagingFunctions.load_nifti_data,
    "check_data_quality": MockNeuroimagingFunctions.check_data_quality,
    "correct_motion": MockNeuroimagingFunctions.correct_motion,
    "correct_slice_timing": MockNeuroimagingFunctions.correct_slice_timing,
    
    # Processing functions
    "reliable_data_loader": MockProcessingFunctions.reliable_data_loader,
    "intermittent_processor": MockProcessingFunctions.intermittent_processor,
    "memory_heavy_operation": MockProcessingFunctions.memory_heavy_operation,
    "parameter_dependent_analysis": MockProcessingFunctions.parameter_dependent_analysis,
    "slow_operation": MockProcessingFunctions.slow_operation,
    
    # Conditional functions
    "load_input": MockConditionalFunctions.load_input,
    "validate_data_type": MockConditionalFunctions.validate_data_type,
    "process_numeric_data": MockConditionalFunctions.process_numeric_data,
    
    # Iterative functions
    "setup_iteration": MockIterativeFunctions.setup_iteration,
    "iterative_processing": MockIterativeFunctions.iterative_processing,
    
    # Simple utility functions
    "simple_transform": lambda data=None, **kwargs: {"transformed": f"transformed_{data}"},
    "simple_output": lambda result=None, **kwargs: {"saved": f"saved_{result}"},
}