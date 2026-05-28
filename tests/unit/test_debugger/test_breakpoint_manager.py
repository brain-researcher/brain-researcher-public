"""Tests for Breakpoint Manager

Tests breakpoint management including conditional breakpoints,
data breakpoints, hit count breakpoints, and safe condition evaluation.
"""

import pytest
import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

from brain_researcher.services.agent.debugger.breakpoint_manager import (
    BreakpointManager, Breakpoint, BreakpointType, BreakpointState,
    DataChangeType, BreakpointHit, ConditionEvaluator, DataWatcher
)


class TestConditionEvaluator:
    """Test safe condition evaluation"""
    
    @pytest.fixture
    def condition_evaluator(self):
        """Create condition evaluator for testing"""
        return ConditionEvaluator()
        
    def test_safe_condition_validation(self, condition_evaluator):
        """Test validation of safe conditions"""
        # Safe conditions
        safe_conditions = [
            "x > 5",
            "len(data) == 10",
            "isinstance(value, int)",
            "hasattr(obj, 'attr')",
            "min(numbers) < max(numbers)",
            "all([x > 0 for x in values])",
            "sum(items) >= 100"
        ]
        
        for condition in safe_conditions:
            assert condition_evaluator.validate_condition(condition) is True
            
    def test_unsafe_condition_rejection(self, condition_evaluator):
        """Test rejection of unsafe conditions"""
        # Unsafe conditions
        unsafe_conditions = [
            "__import__('os')",
            "eval('malicious_code')",
            "exec('bad_code')",
            "open('/etc/passwd')",
            "globals()",
            "locals()",
            "_private_var",
            "obj.__class__",
            "getattr(obj, '_private')"
        ]
        
        for condition in unsafe_conditions:
            assert condition_evaluator.validate_condition(condition) is False
            
    def test_condition_evaluation(self, condition_evaluator):
        """Test safe condition evaluation"""
        context = {
            "x": 10,
            "y": 5,
            "data": [1, 2, 3, 4, 5],
            "obj": {"attr": "value"},
            "numbers": [1, 5, 3, 9, 2]
        }
        
        test_cases = [
            ("x > y", True),
            ("x < y", False),
            ("len(data) == 5", True),
            ("len(data) > 10", False),
            ("'attr' in obj", True),
            ("max(numbers) == 9", True),
            ("min(numbers) == 1", True),
            ("sum(data) == 15", True)
        ]
        
        for condition, expected in test_cases:
            result = condition_evaluator.evaluate_condition(condition, context)
            assert result == expected
            
    def test_condition_evaluation_with_missing_variables(self, condition_evaluator):
        """Test condition evaluation with missing variables"""
        context = {"x": 10}
        
        # Should handle missing variables gracefully
        result = condition_evaluator.evaluate_condition("missing_var > 5", context)
        assert result is False  # Should return False on error
        
    def test_condition_function_creation(self, condition_evaluator):
        """Test creating compiled condition functions"""
        condition = "x > threshold and len(data) >= min_length"
        
        condition_func = condition_evaluator.create_condition_function(condition)
        
        context1 = {"x": 10, "threshold": 5, "data": [1, 2, 3], "min_length": 3}
        context2 = {"x": 3, "threshold": 5, "data": [1, 2], "min_length": 3}
        
        assert condition_func(context1) is True
        assert condition_func(context2) is False
        
    def test_condition_syntax_errors(self, condition_evaluator):
        """Test handling of syntax errors in conditions"""
        invalid_conditions = [
            "x >",  # Incomplete expression
            "len(",  # Unmatched parenthesis
            "x == y and",  # Trailing operator
            "if x > 5:",  # Statement, not expression
        ]
        
        for condition in invalid_conditions:
            assert condition_evaluator.validate_condition(condition) is False


class TestDataWatcher:
    """Test data watching functionality"""
    
    @pytest.fixture
    def data_watcher(self):
        """Create data watcher for testing"""
        return DataWatcher()
        
    def test_variable_watching(self, data_watcher):
        """Test watching variables for changes"""
        # Start watching a variable
        data_watcher.watch_variable("test_var", "initial_value")
        
        assert "test_var" in data_watcher.watched_variables
        assert data_watcher.watched_variables["test_var"] == "initial_value"
        
    def test_variable_change_detection(self, data_watcher):
        """Test detection of variable changes"""
        data_watcher.watch_variable("counter", 0)
        
        # Test CHANGE detection
        changed = data_watcher.check_variable_change("counter", 1, DataChangeType.CHANGE)
        assert changed is True
        
        # Test no change
        no_change = data_watcher.check_variable_change("counter", 1, DataChangeType.CHANGE)
        assert no_change is False
        
    def test_variable_write_detection(self, data_watcher):
        """Test detection of variable writes"""
        data_watcher.watch_variable("write_var", "old")
        
        # WRITE should always trigger (even with same value)
        write_detected = data_watcher.check_variable_change("write_var", "old", DataChangeType.WRITE)
        assert write_detected is True
        
    def test_variable_delete_detection(self, data_watcher):
        """Test detection of variable deletion"""
        data_watcher.watch_variable("delete_var", "exists")
        
        # DELETE triggers when value becomes None
        delete_detected = data_watcher.check_variable_change("delete_var", None, DataChangeType.DELETE)
        assert delete_detected is True
        
    def test_variable_history_tracking(self, data_watcher):
        """Test variable value history tracking"""
        data_watcher.watch_variable("history_var", 0)
        
        # Make several changes
        for i in range(1, 6):
            data_watcher.check_variable_change("history_var", i, DataChangeType.CHANGE)
            
        history = data_watcher.get_variable_history("history_var")
        
        assert len(history) == 5  # 1, 2, 3, 4, 5
        assert history == [1, 2, 3, 4, 5]
        
    def test_variable_history_limits(self, data_watcher):
        """Test variable history size limits"""
        data_watcher.max_history_per_variable = 3
        data_watcher.watch_variable("limited_var", 0)
        
        # Add more changes than the limit
        for i in range(1, 8):
            data_watcher.check_variable_change("limited_var", i, DataChangeType.CHANGE)
            
        history = data_watcher.get_variable_history("limited_var")
        
        # Should only keep the most recent entries
        assert len(history) == 3
        assert history == [5, 6, 7]  # Most recent values
        
    def test_unwatching_variables(self, data_watcher):
        """Test stopping variable watching"""
        data_watcher.watch_variable("temp_var", "value")
        assert "temp_var" in data_watcher.watched_variables
        
        data_watcher.unwatch_variable("temp_var")
        assert "temp_var" not in data_watcher.watched_variables
        assert "temp_var" not in data_watcher.variable_history


class TestBreakpoint:
    """Test breakpoint representation and functionality"""
    
    def test_breakpoint_creation(self):
        """Test breakpoint creation with all parameters"""
        now = datetime.utcnow()
        
        breakpoint = Breakpoint(
            breakpoint_id="bp_123",
            breakpoint_type=BreakpointType.CONDITION,
            enabled=True,
            node_id="test_node",
            condition="x > 10",
            variable_name="watched_var",
            change_type=DataChangeType.WRITE,
            hit_count_target=5,
            description="Test breakpoint",
            tags=["test", "conditional"],
            created_at=now
        )
        
        assert breakpoint.breakpoint_id == "bp_123"
        assert breakpoint.breakpoint_type == BreakpointType.CONDITION
        assert breakpoint.enabled is True
        assert breakpoint.node_id == "test_node"
        assert breakpoint.condition == "x > 10"
        assert breakpoint.variable_name == "watched_var"
        assert breakpoint.hit_count_target == 5
        assert breakpoint.description == "Test breakpoint"
        assert breakpoint.tags == ["test", "conditional"]
        
    def test_breakpoint_serialization(self):
        """Test breakpoint serialization and deserialization"""
        original = Breakpoint(
            breakpoint_id="serialize_test",
            breakpoint_type=BreakpointType.NODE,
            node_id="node1",
            condition="data.status == 'ready'",
            description="Serialization test"
        )
        
        # Add a hit for completeness
        hit = BreakpointHit(
            hit_id="hit_1",
            breakpoint_id="serialize_test",
            timestamp=datetime.utcnow(),
            node_id="node1",
            context={"data": {"status": "ready"}},
            hit_count=1
        )
        original.hits.append(hit)
        
        # Serialize and deserialize
        data = original.to_dict()
        reconstructed = Breakpoint.from_dict(data)
        
        assert reconstructed.breakpoint_id == original.breakpoint_id
        assert reconstructed.breakpoint_type == original.breakpoint_type
        assert reconstructed.node_id == original.node_id
        assert reconstructed.condition == original.condition
        assert reconstructed.description == original.description
        assert len(reconstructed.hits) == 1
        assert reconstructed.hits[0].hit_id == "hit_1"


class TestBreakpointHit:
    """Test breakpoint hit recording"""
    
    def test_breakpoint_hit_creation(self):
        """Test breakpoint hit creation"""
        now = datetime.utcnow()
        context = {"variable": "value", "counter": 5}
        
        hit = BreakpointHit(
            hit_id="hit_123",
            breakpoint_id="bp_456",
            timestamp=now,
            node_id="test_node",
            context=context,
            condition_result=True,
            hit_count=3
        )
        
        assert hit.hit_id == "hit_123"
        assert hit.breakpoint_id == "bp_456"
        assert hit.timestamp == now
        assert hit.node_id == "test_node"
        assert hit.context == context
        assert hit.condition_result is True
        assert hit.hit_count == 3
        
    def test_breakpoint_hit_serialization(self):
        """Test breakpoint hit serialization"""
        original = BreakpointHit(
            hit_id="serialize_hit",
            breakpoint_id="bp_test",
            timestamp=datetime.utcnow(),
            node_id="node_test",
            context={"test": "data"},
            hit_count=1
        )
        
        data = original.to_dict()
        
        assert data["hit_id"] == "serialize_hit"
        assert data["breakpoint_id"] == "bp_test"
        assert "timestamp" in data
        assert data["context"]["test"] == "data"


@pytest.mark.asyncio
class TestBreakpointManager:
    """Test complete breakpoint manager functionality"""
    
    @pytest.fixture
    def breakpoint_manager(self):
        """Create breakpoint manager for testing"""
        return BreakpointManager()
        
    async def test_breakpoint_manager_initialization(self, breakpoint_manager):
        """Test breakpoint manager initialization"""
        assert len(breakpoint_manager.breakpoints) == 0
        assert isinstance(breakpoint_manager.condition_evaluator, ConditionEvaluator)
        assert isinstance(breakpoint_manager.data_watcher, DataWatcher)
        assert breakpoint_manager.total_hits == 0
        assert breakpoint_manager.total_evaluations == 0
        
    async def test_add_node_breakpoint(self, breakpoint_manager):
        """Test adding node-based breakpoints"""
        breakpoint = await breakpoint_manager.add_breakpoint(
            node_id="test_node",
            breakpoint_type=BreakpointType.NODE,
            description="Node breakpoint test"
        )
        
        assert breakpoint.breakpoint_type == BreakpointType.NODE
        assert breakpoint.node_id == "test_node"
        assert breakpoint.description == "Node breakpoint test"
        assert len(breakpoint_manager.breakpoints) == 1
        
    async def test_add_conditional_breakpoint(self, breakpoint_manager):
        """Test adding conditional breakpoints"""
        breakpoint = await breakpoint_manager.add_breakpoint(
            node_id="conditional_node",
            breakpoint_type=BreakpointType.CONDITION,
            condition="x > 5 and y < 10",
            description="Conditional breakpoint"
        )
        
        assert breakpoint.breakpoint_type == BreakpointType.CONDITION
        assert breakpoint.condition == "x > 5 and y < 10"
        assert breakpoint.condition_function is not None
        
    async def test_add_data_breakpoint(self, breakpoint_manager):
        """Test adding data watch breakpoints"""
        breakpoint = await breakpoint_manager.add_breakpoint(
            breakpoint_type=BreakpointType.DATA,
            variable_name="watched_variable",
            change_type=DataChangeType.CHANGE,
            description="Data watch breakpoint"
        )
        
        assert breakpoint.breakpoint_type == BreakpointType.DATA
        assert breakpoint.variable_name == "watched_variable"
        assert breakpoint.change_type == DataChangeType.CHANGE
        
        # Should start watching the variable
        assert "watched_variable" in breakpoint_manager.data_watcher.watched_variables
        
    async def test_add_hit_count_breakpoint(self, breakpoint_manager):
        """Test adding hit count breakpoints"""
        breakpoint = await breakpoint_manager.add_breakpoint(
            node_id="count_node",
            breakpoint_type=BreakpointType.HIT_COUNT,
            hit_count=3,
            description="Hit count breakpoint"
        )
        
        assert breakpoint.breakpoint_type == BreakpointType.HIT_COUNT
        assert breakpoint.hit_count_target == 3
        assert breakpoint.current_hit_count == 0
        
    async def test_add_time_breakpoint(self, breakpoint_manager):
        """Test adding time-based breakpoints"""
        breakpoint = await breakpoint_manager.add_breakpoint(
            breakpoint_type=BreakpointType.TIME,
            time_condition="after 5s",
            description="Time breakpoint"
        )
        
        assert breakpoint.breakpoint_type == BreakpointType.TIME
        assert breakpoint.time_condition == "after 5s"
        
    async def test_invalid_condition_rejection(self, breakpoint_manager):
        """Test rejection of invalid conditions"""
        with pytest.raises(ValueError, match="Invalid condition"):
            await breakpoint_manager.add_breakpoint(
                breakpoint_type=BreakpointType.CONDITION,
                condition="__import__('os')"  # Unsafe condition
            )
            
    async def test_breakpoint_removal(self, breakpoint_manager):
        """Test breakpoint removal"""
        # Add breakpoint
        breakpoint = await breakpoint_manager.add_breakpoint(
            node_id="remove_test",
            breakpoint_type=BreakpointType.NODE
        )
        
        bp_id = breakpoint.breakpoint_id
        assert bp_id in breakpoint_manager.breakpoints
        
        # Remove breakpoint
        success = await breakpoint_manager.remove_breakpoint(bp_id)
        
        assert success is True
        assert bp_id not in breakpoint_manager.breakpoints
        
    async def test_breakpoint_enable_disable(self, breakpoint_manager):
        """Test enabling and disabling breakpoints"""
        breakpoint = await breakpoint_manager.add_breakpoint(
            node_id="toggle_test",
            breakpoint_type=BreakpointType.NODE
        )
        
        bp_id = breakpoint.breakpoint_id
        
        # Initially enabled
        assert breakpoint.enabled is True
        assert breakpoint.state == BreakpointState.ACTIVE
        
        # Disable
        await breakpoint_manager.disable_breakpoint(bp_id)
        assert breakpoint.enabled is False
        assert breakpoint.state == BreakpointState.DISABLED
        
        # Re-enable
        await breakpoint_manager.enable_breakpoint(bp_id)
        assert breakpoint.enabled is True
        assert breakpoint.state == BreakpointState.ACTIVE
        
    async def test_node_breakpoint_evaluation(self, breakpoint_manager):
        """Test node breakpoint evaluation"""
        # Add node breakpoint
        await breakpoint_manager.add_breakpoint(
            node_id="target_node",
            breakpoint_type=BreakpointType.NODE
        )
        
        # Should break at target node
        should_break = await breakpoint_manager.should_break(node_id="target_node")
        assert should_break is True
        
        # Should not break at other nodes
        should_not_break = await breakpoint_manager.should_break(node_id="other_node")
        assert should_not_break is False
        
    async def test_conditional_breakpoint_evaluation(self, breakpoint_manager):
        """Test conditional breakpoint evaluation"""
        # Add conditional breakpoint
        await breakpoint_manager.add_breakpoint(
            breakpoint_type=BreakpointType.CONDITION,
            condition="counter >= 10"
        )
        
        # Should break when condition is true
        context_true = {"counter": 15}
        should_break = await breakpoint_manager.should_break(context=context_true)
        assert should_break is True
        
        # Should not break when condition is false
        context_false = {"counter": 5}
        should_not_break = await breakpoint_manager.should_break(context=context_false)
        assert should_not_break is False
        
    async def test_data_breakpoint_evaluation(self, breakpoint_manager):
        """Test data breakpoint evaluation"""
        # Add data breakpoint
        await breakpoint_manager.add_breakpoint(
            breakpoint_type=BreakpointType.DATA,
            variable_name="data_var",
            change_type=DataChangeType.CHANGE
        )
        
        # First evaluation - establish baseline
        context1 = {"data_var": "initial"}
        await breakpoint_manager.should_break(context=context1)
        
        # Second evaluation with change - should break
        context2 = {"data_var": "changed"}
        should_break = await breakpoint_manager.should_break(context=context2)
        assert should_break is True
        
        # Third evaluation with same value - should not break
        context3 = {"data_var": "changed"}
        should_not_break = await breakpoint_manager.should_break(context=context3)
        assert should_not_break is False
        
    async def test_hit_count_breakpoint_evaluation(self, breakpoint_manager):
        """Test hit count breakpoint evaluation"""
        # Add hit count breakpoint
        await breakpoint_manager.add_breakpoint(
            breakpoint_type=BreakpointType.HIT_COUNT,
            hit_count=3
        )
        
        # Should not break on first two hits
        for i in range(2):
            should_not_break = await breakpoint_manager.should_break()
            assert should_not_break is False
            
        # Should break on third hit
        should_break = await breakpoint_manager.should_break()
        assert should_break is True
        
        # Should not break again (expired)
        should_not_break_again = await breakpoint_manager.should_break()
        assert should_not_break_again is False
        
    async def test_time_breakpoint_evaluation(self, breakpoint_manager):
        """Test time-based breakpoint evaluation"""
        # Add time breakpoint for very short duration
        await breakpoint_manager.add_breakpoint(
            breakpoint_type=BreakpointType.TIME,
            time_condition="after 0.1s"
        )
        
        # Should not break immediately
        should_not_break = await breakpoint_manager.should_break()
        assert should_not_break is False
        
        # Wait for time condition
        await asyncio.sleep(0.15)
        
        # Should break now
        should_break = await breakpoint_manager.should_break()
        assert should_break is True
        
    async def test_breakpoint_hit_recording(self, breakpoint_manager):
        """Test recording of breakpoint hits"""
        # Add breakpoint
        breakpoint = await breakpoint_manager.add_breakpoint(
            node_id="hit_test",
            breakpoint_type=BreakpointType.NODE
        )
        
        # Trigger breakpoint
        context = {"test_data": "value"}
        await breakpoint_manager.should_break(node_id="hit_test", context=context)
        
        # Verify hit was recorded
        assert len(breakpoint.hits) == 1
        assert breakpoint.state == BreakpointState.HIT
        assert breakpoint.hits[0].node_id == "hit_test"
        assert breakpoint.hits[0].context == context
        assert breakpoint_manager.total_hits == 1
        
    async def test_combined_conditions(self, breakpoint_manager):
        """Test breakpoints with both node and condition requirements"""
        # Add node breakpoint with additional condition
        await breakpoint_manager.add_breakpoint(
            node_id="combo_node",
            breakpoint_type=BreakpointType.NODE,
            condition="value > 5"
        )
        
        # Should not break with wrong condition
        context_false = {"value": 3}
        should_not_break = await breakpoint_manager.should_break(
            node_id="combo_node", 
            context=context_false
        )
        assert should_not_break is False
        
        # Should break with correct node and condition
        context_true = {"value": 10}
        should_break = await breakpoint_manager.should_break(
            node_id="combo_node",
            context=context_true
        )
        assert should_break is True
        
    async def test_breakpoint_statistics(self, breakpoint_manager):
        """Test breakpoint statistics collection"""
        # Add various types of breakpoints
        await breakpoint_manager.add_breakpoint(
            node_id="stats_node1", 
            breakpoint_type=BreakpointType.NODE
        )
        await breakpoint_manager.add_breakpoint(
            node_id="stats_node2",
            breakpoint_type=BreakpointType.NODE,
            enabled=False  # Disabled
        )
        await breakpoint_manager.add_breakpoint(
            breakpoint_type=BreakpointType.CONDITION,
            condition="x > 0"
        )
        
        # Trigger some evaluations
        await breakpoint_manager.should_break(node_id="stats_node1")  # Hit
        await breakpoint_manager.should_break(node_id="other_node")   # Miss
        
        stats = breakpoint_manager.get_statistics()
        
        assert stats["total_breakpoints"] == 3
        assert stats["active_breakpoints"] == 2  # One disabled
        assert stats["disabled_breakpoints"] == 1
        assert stats["total_hits"] == 1
        assert stats["total_evaluations"] >= 2
        assert stats["hit_rate"] == 1 / stats["total_evaluations"]
        
    async def test_clear_all_breakpoints(self, breakpoint_manager):
        """Test clearing all breakpoints"""
        # Add several breakpoints
        await breakpoint_manager.add_breakpoint(
            node_id="clear_test1",
            breakpoint_type=BreakpointType.NODE
        )
        await breakpoint_manager.add_breakpoint(
            breakpoint_type=BreakpointType.DATA,
            variable_name="clear_var"
        )
        
        assert len(breakpoint_manager.breakpoints) == 2
        assert "clear_var" in breakpoint_manager.data_watcher.watched_variables
        
        # Clear all breakpoints
        breakpoint_manager.clear_all_breakpoints()
        
        assert len(breakpoint_manager.breakpoints) == 0
        assert "clear_var" not in breakpoint_manager.data_watcher.watched_variables
        
    async def test_breakpoint_querying(self, breakpoint_manager):
        """Test querying breakpoints by various criteria"""
        # Add breakpoints with different properties
        bp1 = await breakpoint_manager.add_breakpoint(
            node_id="query_node1",
            breakpoint_type=BreakpointType.NODE,
            tags=["test"]
        )
        bp2 = await breakpoint_manager.add_breakpoint(
            node_id="query_node2", 
            breakpoint_type=BreakpointType.NODE,
            enabled=False
        )
        bp3 = await breakpoint_manager.add_breakpoint(
            breakpoint_type=BreakpointType.CONDITION,
            condition="x > 0"
        )
        
        # Test various queries
        all_bps = breakpoint_manager.get_all_breakpoints()
        assert len(all_bps) == 3
        
        node_bps = breakpoint_manager.get_breakpoints_by_type(BreakpointType.NODE)
        assert len(node_bps) == 2
        
        condition_bps = breakpoint_manager.get_breakpoints_by_type(BreakpointType.CONDITION)
        assert len(condition_bps) == 1
        
        node1_bps = breakpoint_manager.get_breakpoints_by_node("query_node1")
        assert len(node1_bps) == 1
        assert node1_bps[0].breakpoint_id == bp1.breakpoint_id
        
        active_bps = breakpoint_manager.get_active_breakpoints()
        assert len(active_bps) == 2  # bp2 is disabled