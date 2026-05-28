# AGENT-021 Test Fixtures

This directory contains test fixtures and data for AGENT-021: Adaptive Execution Strategy testing.

## Files Overview

### `mock_tools.py`
Provides mock implementations of neuroimaging tools with configurable behavior for testing:
- `MockTool`: Basic mock tool with configurable duration, success rate, and resource usage
- `MockAdaptiveTool`: Tool that adapts behavior based on system conditions  
- `MockPreemptibleTool`: Tool supporting preemption and resumption
- `MockResourceIntensiveTool`: Tool with high resource requirements
- `MockFailingTool`: Tool with predictable failure modes
- `MockToolRegistry`: Registry managing all mock tools
- `MockExecutionTracker`: Mock execution progress tracker

### `system_metrics.json`
Contains test scenarios for system monitoring:
- **Test Scenarios**: Healthy, moderate, stressed, and critical system states
- **Resource Limits**: Default, high-performance, and limited resource configurations
- **Mock Metrics Progression**: Degrading, recovering, and stable system trends over time

### `task_scenarios.json`
Defines task scheduling and execution scenarios:
- **Scheduling Scenarios**: High priority tasks, mixed workloads, resource-intensive tasks, preemption tests
- **Queue Scenarios**: Empty, moderate, heavy, and backlog queue states
- **Performance Expectations**: Expected metrics for each execution strategy

### `performance_benchmarks.json`
Performance testing and benchmarking data:
- **Benchmark Scenarios**: Performance expectations under different load conditions
- **Stress Test Patterns**: Burst load, gradual increase, resource exhaustion patterns
- **Preemption Test Cases**: Various preemption scenarios and expected outcomes
- **Load Balancing Scenarios**: Resource distribution and contention resolution tests
- **Performance Regression Tests**: Latency, overhead, and speed benchmarks

## Usage in Tests

### Unit Tests
- Import mock tools and utilities for isolated component testing
- Use predefined system metrics for consistent test conditions
- Apply task scenarios to test scheduler behavior

### Integration Tests  
- Load complete scenarios to test component interactions
- Use progression data to simulate system state changes over time
- Apply stress test patterns to verify system resilience

### Performance Tests
- Use benchmark data to establish performance baselines
- Apply regression test cases to detect performance degradation
- Use load patterns to test scaling behavior

## Test Data Structure

### System Metrics
```json
{
  "cpu_usage": 75.0,
  "memory_usage": 80.0, 
  "memory_available": 5.0,
  "disk_io_read": 25.0,
  "disk_io_write": 20.0,
  "network_sent": 12.0,
  "network_recv": 10.0,
  "load_average": [2.5, 2.8, 3.0],
  "active_processes": 180,
  "gpu_usage": 70.0,
  "gpu_memory": 80.0
}
```

### Task Definition
```json
{
  "task_id": "example_task",
  "name": "Example Task",
  "tool_name": "mock_tool",
  "tool_args": {"param": "value"},
  "priority": "HIGH",
  "deadline": 300,
  "preemptible": true,
  "estimated_duration": 180,
  "resource_requirements": [
    {"resource_type": "cpu", "amount": 2.0},
    {"resource_type": "memory", "amount": 4.0}
  ]
}
```

### Performance Expectation
```json
{
  "strategy": "balanced",
  "throughput_min": 3.0,
  "latency_max": 150.0,
  "error_rate_max": 0.02,
  "resource_efficiency_min": 0.80
}
```

## Mock Tool Behavior

### Configurable Parameters
- **Duration**: Execution time simulation
- **Success Rate**: Probability of successful completion
- **Resource Usage**: CPU, memory, I/O usage simulation
- **Failure Modes**: Random, predictable, or conditional failures
- **Preemption Support**: Ability to pause and resume execution
- **System Awareness**: Adaptation to system conditions

### Example Usage
```python
from mock_tools import MockToolRegistry, create_mock_system_monitor

# Create mock tools
registry = MockToolRegistry()
tool = registry.get_tool("fmri_glm")

# Create mock monitor
monitor = create_mock_system_monitor()

# Configure tool behavior
tool.duration = 2.0
tool.success_rate = 0.95
tool.cpu_usage = 70.0
```

## Test Scenarios

### Basic Functionality
- Component initialization and configuration
- Task scheduling and priority handling  
- Resource allocation and management
- System monitoring and health assessment
- Strategy selection and adaptation

### Stress Testing
- High load conditions with resource contention
- Rapid priority changes and preemption
- System health degradation and recovery
- Concurrent execution with multiple users
- Long-running stability tests

### Performance Testing
- Scheduling latency under various loads
- Memory usage growth and cleanup
- CPU overhead of monitoring and adaptation
- Throughput scaling with task count
- Strategy selection speed benchmarks

### Edge Cases
- Resource exhaustion scenarios
- Task failure and retry handling
- Deadline miss and recovery
- Component failure simulation
- Configuration boundary testing

This fixture data enables comprehensive testing of the adaptive execution strategy across all operational scenarios and performance requirements.