"""Tests for Inspector

Tests variable inspection, stack frame analysis, execution trace examination,
and debugging state inspection capabilities.
"""

import pytest
import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from unittest.mock import MagicMock, AsyncMock, patch

from brain_researcher.services.agent.debugger.inspector import (
    Inspector, StackFrame, Variable, VariableType, ExecutionTrace,
    InspectionFilter, StateSnapshot
)
from brain_researcher.services.agent.debugger.workflow_debugger import (
    ExecutionContext, DAGDefinition, DAGNode
)


class TestVariable:
    """Test variable representation and analysis"""
    
    def test_variable_creation_basic_types(self):
        """Test variable creation with basic Python types"""
        test_cases = [
            ("int_var", 42, VariableType.INTEGER),
            ("float_var", 3.14, VariableType.FLOAT),
            ("str_var", "hello", VariableType.STRING),
            ("bool_var", True, VariableType.BOOLEAN),
            ("none_var", None, VariableType.NONE)
        ]
        
        for name, value, expected_type in test_cases:
            var = Variable(name, value)
            assert var.name == name
            assert var.value == value
            assert var.type == expected_type
            assert var.size > 0
            
    def test_variable_creation_complex_types(self):
        """Test variable creation with complex types"""
        test_cases = [
            ("list_var", [1, 2, 3], VariableType.LIST),
            ("dict_var", {"key": "value"}, VariableType.DICT),
            ("tuple_var", (1, 2, 3), VariableType.TUPLE),
            ("set_var", {1, 2, 3}, VariableType.SET)
        ]
        
        for name, value, expected_type in test_cases:
            var = Variable(name, value)
            assert var.name == name
            assert var.value == value
            assert var.type == expected_type
            
    def test_variable_with_custom_object(self):
        """Test variable with custom object"""
        class CustomClass:
            def __init__(self, x, y):
                self.x = x
                self.y = y
                
        obj = CustomClass(10, 20)
        var = Variable("custom_var", obj)
        
        assert var.name == "custom_var"
        assert var.value == obj
        assert var.type == VariableType.OBJECT
        assert "CustomClass" in var.type_name
        
    def test_variable_size_calculation(self):
        """Test variable size calculation for different types"""
        large_list = list(range(1000))
        large_dict = {f"key_{i}": f"value_{i}" for i in range(100)}
        large_string = "x" * 1000
        
        list_var = Variable("large_list", large_list)
        dict_var = Variable("large_dict", large_dict)
        string_var = Variable("large_string", large_string)
        
        assert list_var.size > 100  # Should be reasonably large
        assert dict_var.size > 100
        assert string_var.size >= 1000
        
    def test_variable_summary_generation(self):
        """Test variable summary generation for inspection"""
        # Simple values
        int_var = Variable("count", 42)
        assert "42" in int_var.get_summary()
        
        # Collections
        list_var = Variable("items", [1, 2, 3, 4, 5])
        summary = list_var.get_summary()
        assert "5 items" in summary or "length: 5" in summary.lower()
        
        # Large collections (should be truncated)
        large_list = list(range(100))
        large_var = Variable("large", large_list)
        large_summary = large_var.get_summary()
        assert "..." in large_summary or "truncated" in large_summary.lower()
        
    def test_variable_serialization(self):
        """Test variable serialization for debugging output"""
        var = Variable("test_var", {"nested": {"value": 123}})
        data = var.to_dict()
        
        assert data["name"] == "test_var"
        assert data["type"] == VariableType.DICT.value
        assert data["value"] == {"nested": {"value": 123}}
        assert "size" in data
        assert "summary" in data


class TestStackFrame:
    """Test stack frame representation"""
    
    def test_stack_frame_creation(self):
        """Test stack frame creation with variables"""
        variables = {
            "x": Variable("x", 10),
            "y": Variable("y", "hello"),
            "z": Variable("z", [1, 2, 3])
        }
        
        frame = StackFrame(
            function_name="test_function",
            node_id="test_node",
            variables=variables,
            file_path="/test/path.py",
            line_number=42
        )
        
        assert frame.function_name == "test_function"
        assert frame.node_id == "test_node"
        assert len(frame.variables) == 3
        assert frame.file_path == "/test/path.py"
        assert frame.line_number == 42
        
    def test_stack_frame_variable_access(self):
        """Test accessing variables in stack frame"""
        variables = {
            "param1": Variable("param1", "value1"),
            "param2": Variable("param2", 100)
        }
        
        frame = StackFrame("func", "node", variables)
        
        # Test variable lookup
        var1 = frame.get_variable("param1")
        assert var1 is not None
        assert var1.value == "value1"
        
        # Test non-existent variable
        var_none = frame.get_variable("nonexistent")
        assert var_none is None
        
        # Test variable listing
        var_names = frame.get_variable_names()
        assert set(var_names) == {"param1", "param2"}
        
    def test_stack_frame_filtering(self):
        """Test filtering variables in stack frame"""
        variables = {
            "public_var": Variable("public_var", "visible"),
            "_private_var": Variable("_private_var", "hidden"),
            "__internal__": Variable("__internal__", "internal"),
            "large_data": Variable("large_data", list(range(1000)))
        }
        
        frame = StackFrame("func", "node", variables)
        
        # Filter private variables
        public_vars = frame.filter_variables(exclude_private=True)
        assert "public_var" in public_vars
        assert "_private_var" not in public_vars
        assert "__internal__" not in public_vars
        
        # Filter by type
        list_vars = frame.filter_variables(type_filter=VariableType.LIST)
        assert "large_data" in list_vars
        assert len(list_vars) == 1
        
    def test_stack_frame_serialization(self):
        """Test stack frame serialization"""
        variables = {"var1": Variable("var1", "value1")}
        frame = StackFrame(
            "serialize_func", 
            "serialize_node", 
            variables,
            file_path="/path/file.py",
            line_number=10
        )
        
        data = frame.to_dict()
        
        assert data["function_name"] == "serialize_func"
        assert data["node_id"] == "serialize_node" 
        assert "variables" in data
        assert data["file_path"] == "/path/file.py"
        assert data["line_number"] == 10


class TestExecutionTrace:
    """Test execution trace analysis"""
    
    @pytest.fixture
    def sample_trace_events(self):
        """Create sample trace events for testing"""
        events = []
        base_time = datetime.utcnow()
        
        # Create a sequence of events
        event_data = [
            ("START", "dag_start", {}),
            ("NODE_ENTER", "node1", {"input": "data"}),
            ("NODE_SUCCESS", "node1", {"output": "processed_data"}),
            ("NODE_EXIT", "node1", {}),
            ("NODE_ENTER", "node2", {"input": "processed_data"}),
            ("NODE_ERROR", "node2", {"error": "Processing failed"}),
            ("END", "dag_end", {})
        ]
        
        for i, (event_type, node_id, metadata) in enumerate(event_data):
            events.append({
                "event_id": f"event_{i}",
                "event_type": event_type,
                "node_id": node_id,
                "timestamp": (base_time + timedelta(milliseconds=i*100)).isoformat(),
                "metadata": metadata
            })
            
        return events
        
    def test_execution_trace_creation(self, sample_trace_events):
        """Test execution trace creation and analysis"""
        trace = ExecutionTrace("trace_123", sample_trace_events)
        
        assert trace.trace_id == "trace_123"
        assert len(trace.events) == len(sample_trace_events)
        
        # Test event filtering
        node_events = trace.get_events_by_type("NODE_ENTER")
        assert len(node_events) == 2
        
        error_events = trace.get_events_by_type("NODE_ERROR")
        assert len(error_events) == 1
        assert error_events[0]["node_id"] == "node2"
        
    def test_execution_trace_timing_analysis(self, sample_trace_events):
        """Test timing analysis of execution trace"""
        trace = ExecutionTrace("timing_trace", sample_trace_events)
        
        # Test duration calculation
        duration = trace.get_total_duration()
        assert duration > 0
        
        # Test node execution times
        node_times = trace.get_node_execution_times()
        assert "node1" in node_times
        assert node_times["node1"] > 0
        
    def test_execution_trace_path_analysis(self, sample_trace_events):
        """Test execution path analysis"""
        trace = ExecutionTrace("path_trace", sample_trace_events)
        
        # Test execution path extraction
        path = trace.get_execution_path()
        node_path = [event["node_id"] for event in path if "node" in event["node_id"]]
        
        assert "node1" in node_path
        assert "node2" in node_path
        
        # Test error detection
        errors = trace.get_errors()
        assert len(errors) == 1
        assert errors[0]["node_id"] == "node2"
        
    def test_execution_trace_statistics(self, sample_trace_events):
        """Test execution trace statistics"""
        trace = ExecutionTrace("stats_trace", sample_trace_events)
        
        stats = trace.get_statistics()
        
        assert stats["total_events"] == len(sample_trace_events)
        assert stats["total_nodes"] >= 2
        assert stats["successful_nodes"] >= 1
        assert stats["failed_nodes"] >= 1
        assert stats["total_duration"] > 0


class TestInspectionFilter:
    """Test inspection filtering capabilities"""
    
    def test_inspection_filter_creation(self):
        """Test inspection filter creation and configuration"""
        filter_config = InspectionFilter(
            include_private=False,
            include_methods=False,
            max_depth=3,
            max_items=100,
            type_filters=[VariableType.STRING, VariableType.INTEGER],
            name_patterns=["test_*", "*_result"]
        )
        
        assert filter_config.include_private is False
        assert filter_config.include_methods is False
        assert filter_config.max_depth == 3
        assert filter_config.max_items == 100
        assert VariableType.STRING in filter_config.type_filters
        assert "test_*" in filter_config.name_patterns
        
    def test_variable_filtering_by_name(self):
        """Test filtering variables by name patterns"""
        filter_config = InspectionFilter(name_patterns=["test_*", "*_data"])
        
        variables = {
            "test_var": Variable("test_var", "value"),
            "input_data": Variable("input_data", "data"),
            "other_var": Variable("other_var", "other"),
            "test_count": Variable("test_count", 5),
            "result_data": Variable("result_data", "result")
        }
        
        filtered = filter_config.apply_to_variables(variables)
        
        # Should include test_var, input_data, test_count, result_data
        expected_names = {"test_var", "input_data", "test_count", "result_data"}
        assert set(filtered.keys()) == expected_names
        
    def test_variable_filtering_by_type(self):
        """Test filtering variables by type"""
        filter_config = InspectionFilter(
            type_filters=[VariableType.STRING, VariableType.LIST]
        )
        
        variables = {
            "str_var": Variable("str_var", "string"),
            "int_var": Variable("int_var", 42),
            "list_var": Variable("list_var", [1, 2, 3]),
            "dict_var": Variable("dict_var", {"key": "value"})
        }
        
        filtered = filter_config.apply_to_variables(variables)
        
        # Should include only string and list variables
        assert "str_var" in filtered
        assert "list_var" in filtered
        assert "int_var" not in filtered
        assert "dict_var" not in filtered
        
    def test_private_variable_filtering(self):
        """Test filtering of private variables"""
        filter_config = InspectionFilter(include_private=False)
        
        variables = {
            "public_var": Variable("public_var", "public"),
            "_private_var": Variable("_private_var", "private"),
            "__internal_var__": Variable("__internal_var__", "internal"),
            "normal_var": Variable("normal_var", "normal")
        }
        
        filtered = filter_config.apply_to_variables(variables)
        
        assert "public_var" in filtered
        assert "normal_var" in filtered
        assert "_private_var" not in filtered
        assert "__internal_var__" not in filtered


@pytest.mark.asyncio
class TestInspector:
    """Test complete inspector functionality"""
    
    @pytest.fixture
    def sample_execution_context(self):
        """Create sample execution context for testing"""
        # Create simple DAG
        nodes = {
            "input": DAGNode("input", "source", lambda: {"data": "test"}),
            "process": DAGNode("process", "transform", lambda data: {"result": f"processed_{data}"}, ["input"])
        }
        
        dag = DAGDefinition("test_dag", "Test DAG", "Testing DAG", nodes)
        context = ExecutionContext(dag, "test_session")
        
        # Add some execution state
        context.variables = {
            "session_var": "session_value",
            "counter": 42,
            "data_list": [1, 2, 3, 4, 5],
            "_private": "hidden"
        }
        
        context.node_results = {
            "input": {"data": "test"},
            "process": {"result": "processed_test"}
        }
        
        context.execution_stack = ["input", "process"]
        context.current_node = "process"
        
        return context
        
    def test_inspector_initialization(self, sample_execution_context):
        """Test inspector initialization"""
        inspector = Inspector(sample_execution_context)
        
        assert inspector.execution_context == sample_execution_context
        assert isinstance(inspector.inspection_filter, InspectionFilter)
        assert len(inspector.inspection_history) == 0
        
    async def test_variable_inspection(self, sample_execution_context):
        """Test inspecting variables in current context"""
        inspector = Inspector(sample_execution_context)
        
        # Inspect all variables
        variables = await inspector.inspect_variables()
        
        assert "session_var" in variables
        assert "counter" in variables
        assert "data_list" in variables
        
        # Verify variable details
        session_var = variables["session_var"]
        assert session_var.value == "session_value"
        assert session_var.type == VariableType.STRING
        
        counter_var = variables["counter"]
        assert counter_var.value == 42
        assert counter_var.type == VariableType.INTEGER
        
    async def test_specific_variable_inspection(self, sample_execution_context):
        """Test inspecting specific variables"""
        inspector = Inspector(sample_execution_context)
        
        # Inspect specific variable
        counter_var = await inspector.inspect_variable("counter")
        
        assert counter_var is not None
        assert counter_var.name == "counter"
        assert counter_var.value == 42
        
        # Inspect non-existent variable
        missing_var = await inspector.inspect_variable("nonexistent")
        assert missing_var is None
        
    async def test_stack_frame_inspection(self, sample_execution_context):
        """Test inspecting execution stack frames"""
        inspector = Inspector(sample_execution_context)
        
        # Get current stack frame
        current_frame = await inspector.get_current_stack_frame()
        
        assert current_frame is not None
        assert current_frame.node_id == "process"  # Current node
        assert len(current_frame.variables) > 0
        
    async def test_execution_state_inspection(self, sample_execution_context):
        """Test inspecting overall execution state"""
        inspector = Inspector(sample_execution_context)
        
        state = await inspector.inspect_execution_state()
        
        assert state["session_id"] == "test_session"
        assert state["current_node"] == "process"
        assert state["execution_stack"] == ["input", "process"]
        assert "variables" in state
        assert "node_results" in state
        
    async def test_node_results_inspection(self, sample_execution_context):
        """Test inspecting node execution results"""
        inspector = Inspector(sample_execution_context)
        
        # Inspect all results
        all_results = await inspector.inspect_node_results()
        
        assert "input" in all_results
        assert "process" in all_results
        assert all_results["input"]["data"] == "test"
        assert all_results["process"]["result"] == "processed_test"
        
        # Inspect specific node result
        process_result = await inspector.inspect_node_result("process")
        assert process_result["result"] == "processed_test"
        
    async def test_filtered_variable_inspection(self, sample_execution_context):
        """Test variable inspection with filters"""
        # Configure filter to exclude private variables
        filter_config = InspectionFilter(include_private=False)
        inspector = Inspector(sample_execution_context, filter_config)
        
        variables = await inspector.inspect_variables()
        
        # Should not include _private variable
        assert "_private" not in variables
        assert "session_var" in variables
        assert "counter" in variables
        
    async def test_variable_watch_inspection(self, sample_execution_context):
        """Test inspecting watched variables over time"""
        inspector = Inspector(sample_execution_context)
        
        # Start watching a variable
        await inspector.start_watching_variable("counter")
        
        # Modify the variable
        sample_execution_context.variables["counter"] = 43
        await inspector.update_watched_variables()
        
        sample_execution_context.variables["counter"] = 44
        await inspector.update_watched_variables()
        
        # Get watch history
        history = await inspector.get_variable_watch_history("counter")
        
        assert len(history) >= 2
        assert history[-1]["value"] == 44  # Latest value
        assert history[-2]["value"] == 43  # Previous value
        
    async def test_deep_variable_inspection(self, sample_execution_context):
        """Test deep inspection of complex variables"""
        # Add complex nested structure
        complex_data = {
            "level1": {
                "level2": {
                    "level3": {
                        "deep_value": "found it!",
                        "deep_list": [1, 2, {"nested": True}]
                    }
                }
            },
            "simple": "value"
        }
        
        sample_execution_context.variables["complex_var"] = complex_data
        
        inspector = Inspector(sample_execution_context)
        
        # Deep inspect the complex variable
        inspection = await inspector.deep_inspect_variable("complex_var", max_depth=4)
        
        assert inspection is not None
        assert inspection["type"] == VariableType.DICT.value
        assert "children" in inspection
        
        # Verify nested structure is captured
        level1 = inspection["children"]["level1"]
        assert level1["type"] == VariableType.DICT.value
        
    async def test_inspection_history_tracking(self, sample_execution_context):
        """Test tracking inspection history"""
        inspector = Inspector(sample_execution_context)
        
        # Perform several inspections
        await inspector.inspect_variables()
        await inspector.inspect_variable("counter")
        await inspector.inspect_execution_state()
        
        history = inspector.get_inspection_history()
        
        assert len(history) == 3
        assert all("timestamp" in entry for entry in history)
        assert all("operation" in entry for entry in history)
        
    async def test_performance_profiling_integration(self, sample_execution_context):
        """Test integration with performance profiling"""
        inspector = Inspector(sample_execution_context)
        
        # Enable profiling
        inspector.enable_profiling = True
        
        start_time = time.time()
        
        # Perform some inspections
        await inspector.inspect_variables()
        await inspector.inspect_execution_state()
        
        end_time = time.time()
        
        # Get profiling data
        profile_data = inspector.get_profiling_data()
        
        assert "total_inspections" in profile_data
        assert "total_time" in profile_data
        assert profile_data["total_time"] <= (end_time - start_time) * 1.1  # Some tolerance
        
    async def test_memory_usage_inspection(self, sample_execution_context):
        """Test memory usage inspection"""
        inspector = Inspector(sample_execution_context)
        
        # Add some large data structures
        large_list = list(range(10000))
        large_dict = {f"key_{i}": f"value_{i}" for i in range(1000)}
        
        sample_execution_context.variables["large_list"] = large_list
        sample_execution_context.variables["large_dict"] = large_dict
        
        memory_info = await inspector.inspect_memory_usage()
        
        assert "total_variables" in memory_info
        assert "total_size_bytes" in memory_info
        assert "largest_variables" in memory_info
        
        # Large variables should be identified
        largest_vars = memory_info["largest_variables"]
        var_names = [var["name"] for var in largest_vars]
        assert "large_list" in var_names or "large_dict" in var_names
        
    async def test_state_snapshot_creation(self, sample_execution_context):
        """Test creating state snapshots for debugging"""
        inspector = Inspector(sample_execution_context)
        
        snapshot = await inspector.create_state_snapshot()
        
        assert isinstance(snapshot, StateSnapshot)
        assert snapshot.session_id == "test_session"
        assert snapshot.timestamp is not None
        assert len(snapshot.variables) > 0
        assert len(snapshot.node_results) > 0
        assert snapshot.execution_stack == ["input", "process"]
        
    async def test_state_comparison(self, sample_execution_context):
        """Test comparing states between snapshots"""
        inspector = Inspector(sample_execution_context)
        
        # Create first snapshot
        snapshot1 = await inspector.create_state_snapshot()
        
        # Modify state
        sample_execution_context.variables["counter"] = 100
        sample_execution_context.variables["new_var"] = "added"
        del sample_execution_context.variables["session_var"]
        
        # Create second snapshot
        snapshot2 = await inspector.create_state_snapshot()
        
        # Compare snapshots
        comparison = inspector.compare_snapshots(snapshot1, snapshot2)
        
        assert "added_variables" in comparison
        assert "removed_variables" in comparison
        assert "modified_variables" in comparison
        
        assert "new_var" in comparison["added_variables"]
        assert "session_var" in comparison["removed_variables"]
        assert "counter" in comparison["modified_variables"]
        
        # Verify modification details
        counter_change = comparison["modified_variables"]["counter"]
        assert counter_change["old_value"] == 42
        assert counter_change["new_value"] == 100