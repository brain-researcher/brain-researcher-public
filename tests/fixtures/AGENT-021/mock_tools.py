"""
Mock tools and utilities for AGENT-021 testing.

Provides mock implementations of neuroimaging tools with configurable
behavior for testing the adaptive execution strategy.
"""

import asyncio
import random
import time
from typing import Any, Dict
from unittest.mock import MagicMock


class MockTool:
    """Base mock tool with configurable behavior."""
    
    def __init__(
        self,
        name: str,
        duration: float = 1.0,
        success_rate: float = 1.0,
        cpu_usage: float = 50.0,
        memory_usage: float = 50.0,
        io_usage: float = 10.0
    ):
        """Initialize mock tool."""
        self.name = name
        self.duration = duration
        self.success_rate = success_rate
        self.cpu_usage = cpu_usage
        self.memory_usage = memory_usage
        self.io_usage = io_usage
        self.call_count = 0
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """Run the mock tool."""
        self.call_count += 1
        
        # Simulate execution time
        if self.duration > 0:
            time.sleep(self.duration)
        
        # Simulate failure
        if random.random() > self.success_rate:
            raise Exception(f"Mock failure in {self.name}")
        
        return {
            "tool": self.name,
            "status": "completed",
            "duration": self.duration,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "io_usage": self.io_usage,
            "call_count": self.call_count,
            "result": f"Mock result from {self.name}"
        }


class MockAdaptiveTool(MockTool):
    """Mock tool that adapts behavior based on system conditions."""
    
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)
        self.system_monitor = None
    
    def set_system_monitor(self, monitor):
        """Set system monitor for adaptive behavior."""
        self.system_monitor = monitor
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """Run with system-adaptive behavior."""
        # Adjust duration based on system load
        if self.system_monitor:
            metrics = self.system_monitor.get_system_metrics()
            if metrics:
                if metrics.cpu_usage > 80:
                    self.duration *= 1.5  # Slower when system is loaded
                elif metrics.cpu_usage < 30:
                    self.duration *= 0.8  # Faster when system is idle
        
        return super().run(**kwargs)


class MockPreemptibleTool(MockTool):
    """Mock tool that supports preemption."""
    
    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)
        self.preempted = False
        self.resume_count = 0
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """Run with preemption support."""
        # Simulate preemption during execution
        segments = max(1, int(self.duration))
        segment_duration = self.duration / segments
        
        for i in range(segments):
            if self.preempted:
                # Simulate save state and return partial result
                return {
                    "tool": self.name,
                    "status": "preempted",
                    "progress": i / segments,
                    "can_resume": True
                }
            
            time.sleep(segment_duration)
        
        result = super().run(**kwargs)
        result["resume_count"] = self.resume_count
        return result
    
    def preempt(self):
        """Preempt the tool execution."""
        self.preempted = True
    
    def resume(self):
        """Resume tool execution."""
        self.preempted = False
        self.resume_count += 1


class MockResourceIntensiveTool(MockTool):
    """Mock tool with high resource requirements."""
    
    def __init__(self, name: str, resource_multiplier: float = 2.0, **kwargs):
        super().__init__(name, **kwargs)
        self.resource_multiplier = resource_multiplier
        self.cpu_usage *= resource_multiplier
        self.memory_usage *= resource_multiplier
        self.io_usage *= resource_multiplier
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """Run with high resource usage."""
        result = super().run(**kwargs)
        result["resource_intensive"] = True
        result["resource_multiplier"] = self.resource_multiplier
        return result


class MockFailingTool(MockTool):
    """Mock tool that fails predictably."""
    
    def __init__(self, name: str, failure_mode: str = "random", **kwargs):
        super().__init__(name, **kwargs)
        self.failure_mode = failure_mode
        self.failure_count = 0
    
    def run(self, **kwargs) -> Dict[str, Any]:
        """Run with configurable failure modes."""
        should_fail = False
        
        if self.failure_mode == "always":
            should_fail = True
        elif self.failure_mode == "nth_call" and self.call_count % 3 == 0:
            should_fail = True
        elif self.failure_mode == "after_retries" and self.call_count > 2:
            should_fail = True
        elif self.failure_mode == "random":
            should_fail = random.random() > self.success_rate
        
        if should_fail:
            self.failure_count += 1
            raise Exception(f"Intentional failure in {self.name} (failure #{self.failure_count})")
        
        result = super().run(**kwargs)
        result["failure_count"] = self.failure_count
        return result


class MockToolRegistry:
    """Mock tool registry for testing."""
    
    def __init__(self):
        """Initialize mock registry."""
        self.tools = {
            # Standard neuroimaging tools
            "fmri_glm": MockTool("fmri_glm", duration=2.0, cpu_usage=60, memory_usage=40),
            "fmriprep": MockResourceIntensiveTool("fmriprep", duration=5.0, resource_multiplier=2.5),
            "quality_check": MockTool("quality_check", duration=1.0, cpu_usage=20, memory_usage=30),
            "statistical_test": MockTool("statistical_test", duration=1.5, cpu_usage=40, memory_usage=50),
            "connectivity_analysis": MockTool("connectivity_analysis", duration=3.0, cpu_usage=70, memory_usage=60),
            
            # Resource intensive tools
            "ml_training": MockResourceIntensiveTool("ml_training", duration=10.0, resource_multiplier=4.0),
            "large_dataset_processing": MockResourceIntensiveTool("large_dataset_processing", duration=8.0, resource_multiplier=3.0),
            
            # Preemptible tools
            "long_computation": MockPreemptibleTool("long_computation", duration=15.0),
            "quick_analysis": MockTool("quick_analysis", duration=0.5, cpu_usage=80, memory_usage=30),
            
            # Failing tools for testing
            "unreliable_tool": MockFailingTool("unreliable_tool", failure_mode="random", success_rate=0.7),
            "failing_tool": MockFailingTool("failing_tool", failure_mode="always"),
            
            # Adaptive tools
            "adaptive_processing": MockAdaptiveTool("adaptive_processing", duration=2.0),
            "system_aware_tool": MockAdaptiveTool("system_aware_tool", duration=3.0),
            
            # Default mock tool
            "mock_tool": MockTool("mock_tool", duration=1.0)
        }
    
    def get_tool(self, name: str) -> MockTool:
        """Get tool by name."""
        return self.tools.get(name, self.tools["mock_tool"])
    
    def register_tool(self, name: str, tool: MockTool):
        """Register a new tool."""
        self.tools[name] = tool
    
    def get_all_tools(self) -> Dict[str, MockTool]:
        """Get all registered tools."""
        return self.tools.copy()
    
    def reset_all_tools(self):
        """Reset all tools to initial state."""
        for tool in self.tools.values():
            tool.call_count = 0
            if hasattr(tool, 'failure_count'):
                tool.failure_count = 0
            if hasattr(tool, 'preempted'):
                tool.preempted = False
                tool.resume_count = 0


def create_mock_system_monitor():
    """Create a mock system monitor for testing."""
    monitor = MagicMock()
    
    # Default healthy metrics
    mock_metrics = MagicMock()
    mock_metrics.cpu_usage = 30.0
    mock_metrics.memory_usage = 40.0
    mock_metrics.memory_available = 12.8
    mock_metrics.disk_io_read = 5.0
    mock_metrics.disk_io_write = 3.0
    mock_metrics.network_sent = 2.0
    mock_metrics.network_recv = 1.5
    mock_metrics.load_average = (0.8, 0.9, 1.0)
    mock_metrics.active_processes = 120
    mock_metrics.queue_depth = 3
    mock_metrics.gpu_usage = 15.0
    mock_metrics.gpu_memory = 20.0
    mock_metrics.timestamp = time.time()
    
    monitor.get_system_metrics.return_value = mock_metrics
    monitor.get_health_status.return_value = "healthy"
    monitor.get_resource_utilization.return_value = {
        "cpu": 30.0,
        "memory": 40.0,
        "load_1min": 20.0,
        "gpu": 15.0,
        "gpu_memory": 20.0
    }
    monitor.update_queue_depth = MagicMock()
    monitor._monitoring = True
    
    return monitor


def create_performance_test_tools():
    """Create tools specifically for performance testing."""
    tools = {
        "cpu_intensive": MockTool("cpu_intensive", duration=1.0, cpu_usage=90, memory_usage=20),
        "memory_intensive": MockTool("memory_intensive", duration=1.0, cpu_usage=30, memory_usage=90),
        "io_intensive": MockTool("io_intensive", duration=1.0, cpu_usage=20, memory_usage=30, io_usage=80),
        "balanced_tool": MockTool("balanced_tool", duration=1.0, cpu_usage=50, memory_usage=50, io_usage=30),
        "quick_tool": MockTool("quick_tool", duration=0.1, cpu_usage=40, memory_usage=30),
        "slow_tool": MockTool("slow_tool", duration=5.0, cpu_usage=60, memory_usage=70)
    }
    
    registry = MockToolRegistry()
    for name, tool in tools.items():
        registry.register_tool(name, tool)
    
    return registry


class MockExecutionTracker:
    """Mock execution tracker for testing."""
    
    def __init__(self):
        self.steps = []
        self.current_step = 0
        self.completed_steps = 0
        self.failed_steps = 0
        self.started = False
        self.completed = False
        self.error = None
        self.result = None
    
    def start_execution(self):
        self.started = True
    
    def add_step(self, name: str, description: str, estimated_duration: float = 60.0):
        self.steps.append({
            "name": name,
            "description": description,
            "estimated_duration": estimated_duration,
            "status": "pending"
        })
    
    def complete_step(self, error: str = None):
        if self.current_step < len(self.steps):
            if error:
                self.steps[self.current_step]["status"] = "failed"
                self.steps[self.current_step]["error"] = error
                self.failed_steps += 1
            else:
                self.steps[self.current_step]["status"] = "completed"
                self.completed_steps += 1
            
            self.current_step += 1
    
    def complete_execution(self, error: str = None, result: Any = None):
        self.completed = True
        self.error = error
        self.result = result
    
    def get_status(self):
        return {
            "started": self.started,
            "completed": self.completed,
            "total_steps": len(self.steps),
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "current_step": self.current_step,
            "error": self.error,
            "result": self.result
        }