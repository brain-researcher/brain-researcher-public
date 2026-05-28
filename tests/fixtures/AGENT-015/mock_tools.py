"""
Mock tools for parallel execution testing.
"""

import asyncio
import logging
import random
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MockTool:
    """Base mock tool for testing."""
    
    def __init__(self, name: str, failure_rate: float = 0.0):
        """
        Initialize mock tool.
        
        Args:
            name: Tool name
            failure_rate: Probability of failure (0.0 to 1.0)
        """
        self.name = name
        self.failure_rate = failure_rate
        self.execution_count = 0
        
    def run(self, **kwargs) -> Dict[str, Any]:
        """
        Mock tool execution.
        
        Args:
            **kwargs: Tool arguments
            
        Returns:
            Mock execution result
            
        Raises:
            Exception: If simulated failure occurs
        """
        self.execution_count += 1
        execution_id = f"{self.name}_exec_{self.execution_count}"
        
        logger.info(f"Starting mock tool {self.name} execution {execution_id}")
        
        # Simulate execution time
        execution_time = kwargs.get("duration", random.uniform(0.05, 0.2))
        time.sleep(execution_time)
        
        # Simulate random failures
        if random.random() < self.failure_rate:
            error_msg = f"Mock failure in {self.name} execution {execution_id}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        result = {
            "execution_id": execution_id,
            "tool_name": self.name,
            "status": "completed",
            "execution_time": execution_time,
            "input_args": kwargs,
            "output_data": f"Mock output from {self.name}",
            "metrics": {
                "cpu_usage": random.uniform(20, 80),
                "memory_usage": random.uniform(10, 60),
                "files_processed": random.randint(1, 100)
            }
        }
        
        logger.info(f"Completed mock tool {self.name} execution {execution_id}")
        return result


class CPUIntensiveMockTool(MockTool):
    """CPU intensive mock tool."""
    
    def __init__(self, failure_rate: float = 0.0):
        super().__init__("cpu_intensive_tool", failure_rate)
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """CPU intensive execution simulation."""
        duration = kwargs.get("duration", 1.0)
        
        # Simulate CPU work
        start_time = time.time()
        while time.time() - start_time < duration:
            # Busy work
            sum(range(1000))
        
        result = super().run(**kwargs)
        result["metrics"]["cpu_usage"] = random.uniform(80, 100)
        return result


class MemoryIntensiveMockTool(MockTool):
    """Memory intensive mock tool."""
    
    def __init__(self, failure_rate: float = 0.0):
        super().__init__("memory_intensive_tool", failure_rate)
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """Memory intensive execution simulation."""
        # Simulate memory allocation
        memory_size = kwargs.get("memory_mb", 100)
        large_data = bytearray(memory_size * 1024 * 1024)  # Allocate memory
        
        time.sleep(kwargs.get("duration", 0.5))
        
        result = super().run(**kwargs)
        result["metrics"]["memory_usage"] = random.uniform(70, 95)
        result["metrics"]["memory_allocated_mb"] = memory_size
        
        # Clean up
        del large_data
        return result


class IOIntensiveMockTool(MockTool):
    """IO intensive mock tool."""
    
    def __init__(self, failure_rate: float = 0.0):
        super().__init__("io_intensive_tool", failure_rate)
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """IO intensive execution simulation."""
        # Simulate file operations
        duration = kwargs.get("duration", 1.0)
        intervals = int(duration * 10)  # 10 operations per second
        
        for i in range(intervals):
            time.sleep(0.1)
            # Simulate IO wait
            
        result = super().run(**kwargs)
        result["metrics"]["io_operations"] = intervals
        result["metrics"]["disk_usage"] = random.uniform(30, 70)
        return result


class FMRIPrepMockTool(MockTool):
    """Mock fMRIPrep tool."""
    
    def __init__(self, failure_rate: float = 0.05):
        super().__init__("fmriprep_tool", failure_rate)
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """fMRIPrep simulation."""
        input_dir = kwargs.get("input_dir", "/data/raw")
        output_dir = kwargs.get("output_dir", "/data/preprocessed")
        
        # Simulate long preprocessing time
        duration = kwargs.get("duration", random.uniform(1800, 3600))  # 30-60 minutes
        time.sleep(min(duration, 2.0))  # Cap at 2 seconds for testing
        
        result = super().run(**kwargs)
        result.update({
            "input_directory": input_dir,
            "output_directory": output_dir,
            "preprocessing_steps": [
                "skull_stripping",
                "motion_correction",
                "spatial_normalization",
                "smoothing"
            ],
            "quality_metrics": {
                "mean_fd": random.uniform(0.1, 0.5),
                "tsnr": random.uniform(40, 80),
                "fwhm": random.uniform(6, 9)
            }
        })
        return result


class GLMAnalysisMockTool(MockTool):
    """Mock GLM analysis tool."""
    
    def __init__(self, failure_rate: float = 0.02):
        super().__init__("glm_analysis_tool", failure_rate)
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """GLM analysis simulation."""
        hemisphere = kwargs.get("hemisphere", "both")
        task = kwargs.get("task", "unknown")
        
        # Simulate GLM computation
        duration = kwargs.get("duration", random.uniform(900, 1800))  # 15-30 minutes
        time.sleep(min(duration, 1.0))  # Cap at 1 second for testing
        
        result = super().run(**kwargs)
        result.update({
            "hemisphere": hemisphere,
            "task": task,
            "contrast_maps": [
                f"{task}_positive",
                f"{task}_negative",
                f"{task}_interaction"
            ],
            "statistics": {
                "max_t_stat": random.uniform(3.0, 8.0),
                "cluster_count": random.randint(5, 50),
                "peak_coordinates": [
                    [random.randint(-50, 50), random.randint(-80, 80), random.randint(-40, 70)]
                    for _ in range(3)
                ]
            }
        })
        return result


class ConnectivityMockTool(MockTool):
    """Mock connectivity analysis tool."""
    
    def __init__(self, failure_rate: float = 0.03):
        super().__init__("connectivity_tool", failure_rate)
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """Connectivity analysis simulation."""
        atlas = kwargs.get("atlas", "schaefer400")
        
        # Simulate connectivity computation
        duration = kwargs.get("duration", random.uniform(1200, 2400))  # 20-40 minutes
        time.sleep(min(duration, 1.5))  # Cap at 1.5 seconds for testing
        
        result = super().run(**kwargs)
        result.update({
            "atlas": atlas,
            "connectivity_matrices": {
                "correlation": f"connectivity_corr_{atlas}.npy",
                "partial_correlation": f"connectivity_pcorr_{atlas}.npy",
                "coherence": f"connectivity_coh_{atlas}.npy"
            },
            "network_metrics": {
                "global_efficiency": random.uniform(0.3, 0.7),
                "clustering_coefficient": random.uniform(0.4, 0.8),
                "small_worldness": random.uniform(1.2, 2.5)
            }
        })
        return result


class ReportGeneratorMockTool(MockTool):
    """Mock report generator tool."""
    
    def __init__(self, failure_rate: float = 0.01):
        super().__init__("report_generator_tool", failure_rate)
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """Report generation simulation."""
        include_all = kwargs.get("include_all", True)
        
        # Simulate report generation
        duration = kwargs.get("duration", random.uniform(300, 600))  # 5-10 minutes
        time.sleep(min(duration, 0.5))  # Cap at 0.5 seconds for testing
        
        result = super().run(**kwargs)
        result.update({
            "report_sections": [
                "summary",
                "preprocessing_qa",
                "activation_maps",
                "connectivity_analysis",
                "statistical_results"
            ] if include_all else ["summary", "statistical_results"],
            "output_files": {
                "html_report": "analysis_report.html",
                "pdf_report": "analysis_report.pdf",
                "figures": ["figure_1.png", "figure_2.png", "figure_3.png"]
            }
        })
        return result


# Tool registry for mock tools
MOCK_TOOLS = {
    "mock_tool": MockTool,
    "cpu_intensive_tool": CPUIntensiveMockTool,
    "memory_intensive_tool": MemoryIntensiveMockTool,
    "io_intensive_tool": IOIntensiveMockTool,
    "fmriprep_tool": FMRIPrepMockTool,
    "glm_analysis_tool": GLMAnalysisMockTool,
    "connectivity_tool": ConnectivityMockTool,
    "report_generator_tool": ReportGeneratorMockTool,
    "freesurfer_tool": MockTool,
    "bids_validator_tool": MockTool,
    "surface_analysis_tool": MockTool,
    "group_glm_tool": MockTool,
    "merge_results_tool": MockTool
}


def get_mock_tool(tool_name: str, failure_rate: float = 0.0) -> MockTool:
    """
    Get a mock tool instance.
    
    Args:
        tool_name: Name of the tool
        failure_rate: Failure rate for the tool
        
    Returns:
        Mock tool instance
    """
    tool_class = MOCK_TOOLS.get(tool_name, MockTool)
    if tool_class == MockTool:
        return MockTool(tool_name, failure_rate)
    else:
        return tool_class(failure_rate)


class MockToolRegistry:
    """Mock tool registry for testing."""
    
    def __init__(self):
        """Initialize mock registry."""
        self.tools = {}
        
    def register_tool(self, name: str, tool_class: type, failure_rate: float = 0.0):
        """Register a mock tool."""
        self.tools[name] = (tool_class, failure_rate)
    
    def get_tool(self, name: str) -> MockTool:
        """Get a tool instance."""
        if name in self.tools:
            tool_class, failure_rate = self.tools[name]
            return tool_class(failure_rate) if tool_class != MockTool else MockTool(name, failure_rate)
        else:
            return MockTool(name, 0.0)
    
    def list_tools(self) -> list:
        """List available tools."""
        return list(self.tools.keys())


# Global mock registry instance
mock_registry = MockToolRegistry()

# Register all mock tools
for tool_name, tool_class in MOCK_TOOLS.items():
    mock_registry.register_tool(tool_name, tool_class)
