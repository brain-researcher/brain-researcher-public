"""Breakpoint Manager

Manages various types of breakpoints for workflow debugging including
conditional breakpoints, data breakpoints, and hit count breakpoints.
"""

import ast
import asyncio
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)


class BreakpointType(str, Enum):
    """Types of breakpoints"""

    NODE = "node"  # Break at specific node
    CONDITION = "condition"  # Break when condition is true
    DATA = "data"  # Break on variable change
    EXCEPTION = "exception"  # Break on exception
    HIT_COUNT = "hit_count"  # Break after N hits
    TIME = "time"  # Break at specific time or after duration


class BreakpointState(str, Enum):
    """Breakpoint states"""

    ACTIVE = "active"
    DISABLED = "disabled"
    HIT = "hit"
    EXPIRED = "expired"


class DataChangeType(str, Enum):
    """Types of data changes to watch"""

    READ = "read"
    WRITE = "write"
    CHANGE = "change"
    DELETE = "delete"


@dataclass
class BreakpointHit:
    """Records when a breakpoint was hit"""

    hit_id: str
    breakpoint_id: str
    timestamp: datetime
    node_id: Optional[str]
    context: Dict[str, Any]
    condition_result: Any = None
    hit_count: int = 0

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class Breakpoint:
    """Represents a breakpoint with its configuration"""

    breakpoint_id: str
    breakpoint_type: BreakpointType
    enabled: bool = True
    state: BreakpointState = BreakpointState.ACTIVE

    # Location
    node_id: Optional[str] = None
    line_number: Optional[int] = None

    # Condition
    condition: Optional[str] = None
    condition_function: Optional[Callable] = None

    # Data watching
    variable_name: Optional[str] = None
    change_type: DataChangeType = DataChangeType.CHANGE
    previous_value: Any = None

    # Hit count
    hit_count_target: Optional[int] = None
    current_hit_count: int = 0

    # Time-based
    time_condition: Optional[str] = None  # e.g., "after 5s", "at 14:30"
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Metadata
    description: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # History
    hits: List[BreakpointHit] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["hits"] = [hit.to_dict() for hit in self.hits]
        # Remove function from serialization
        data.pop("condition_function", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "Breakpoint":
        """Create from dictionary"""
        if "created_at" in data:
            data["created_at"] = datetime.fromisoformat(data["created_at"])

        if "hits" in data:
            hits = []
            for hit_data in data["hits"]:
                if "timestamp" in hit_data:
                    hit_data["timestamp"] = datetime.fromisoformat(
                        hit_data["timestamp"]
                    )
                hits.append(BreakpointHit(**hit_data))
            data["hits"] = hits

        return cls(**data)


class ConditionEvaluator:
    """Safely evaluates breakpoint conditions"""

    def __init__(self):
        # Safe functions available in conditions
        self.safe_functions = {
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "any": any,
            "all": all,
            "isinstance": isinstance,
            "hasattr": hasattr,
            "getattr": getattr,
        }

        # Safe nodes for AST validation
        self.safe_nodes = {
            ast.Expression,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
            ast.BoolOp,
            ast.Constant,
            ast.Name,
            ast.Call,
            ast.Attribute,
            ast.Subscript,
            ast.List,
            ast.Dict,
            ast.Tuple,
            ast.Set,
            ast.ListComp,
            ast.DictComp,
            ast.SetComp,
            ast.GeneratorExp,
        }

    def validate_condition(self, condition: str) -> bool:
        """Validate that condition is safe to execute"""
        try:
            tree = ast.parse(condition, mode="eval")

            for node in ast.walk(tree):
                if type(node) not in self.safe_nodes:
                    return False

                # Check for dangerous function calls
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id not in self.safe_functions:
                            return False
                    elif isinstance(node.func, ast.Attribute):
                        # Allow basic method calls on safe objects
                        if node.func.attr.startswith("_"):
                            return False

            return True

        except SyntaxError:
            return False

    def evaluate_condition(self, condition: str, context: Dict[str, Any]) -> Any:
        """Safely evaluate condition in given context"""
        if not self.validate_condition(condition):
            raise ValueError(f"Unsafe condition: {condition}")

        try:
            # Create safe evaluation environment
            safe_context = {}
            safe_context.update(self.safe_functions)
            safe_context.update(context)

            # Remove potentially dangerous items
            for key in list(safe_context.keys()):
                if key.startswith("_"):
                    del safe_context[key]

            return eval(condition, {"__builtins__": {}}, safe_context)

        except Exception as e:
            logger.warning(f"Condition evaluation failed: {e}")
            return False

    def create_condition_function(self, condition: str) -> Callable:
        """Create a compiled condition function for better performance"""
        if not self.validate_condition(condition):
            raise ValueError(f"Unsafe condition: {condition}")

        code = compile(condition, "<condition>", "eval")

        def condition_func(context: Dict[str, Any]) -> Any:
            try:
                safe_context = {}
                safe_context.update(self.safe_functions)
                safe_context.update(context)

                # Remove potentially dangerous items
                for key in list(safe_context.keys()):
                    if key.startswith("_"):
                        del safe_context[key]

                return eval(code, {"__builtins__": {}}, safe_context)
            except Exception as e:
                logger.warning(f"Condition function evaluation failed: {e}")
                return False

        return condition_func


class DataWatcher:
    """Watches for changes in variables"""

    def __init__(self):
        self.watched_variables: Dict[str, Any] = {}
        self.variable_history: Dict[str, List[Any]] = {}
        self.max_history_per_variable = 100

    def watch_variable(self, name: str, initial_value: Any = None):
        """Start watching a variable"""
        self.watched_variables[name] = initial_value
        if name not in self.variable_history:
            self.variable_history[name] = []

    def unwatch_variable(self, name: str):
        """Stop watching a variable"""
        self.watched_variables.pop(name, None)
        self.variable_history.pop(name, None)

    def check_variable_change(
        self, name: str, current_value: Any, change_type: DataChangeType
    ) -> bool:
        """Check if variable has changed according to change type"""
        if name not in self.watched_variables:
            return False

        previous_value = self.watched_variables[name]

        # Update watched value
        self.watched_variables[name] = current_value

        # Record in history
        history = self.variable_history[name]
        history.append(current_value)
        if len(history) > self.max_history_per_variable:
            history.pop(0)

        # Check change type
        if change_type == DataChangeType.READ:
            # Always trigger on read (if we can detect it)
            return True
        elif change_type == DataChangeType.WRITE:
            # Trigger on any write
            return True
        elif change_type == DataChangeType.CHANGE:
            # Trigger only if value actually changed
            return current_value != previous_value
        elif change_type == DataChangeType.DELETE:
            # Trigger if value is None/deleted
            return current_value is None

        return False

    def get_variable_history(self, name: str) -> List[Any]:
        """Get history of variable values"""
        return self.variable_history.get(name, [])


class BreakpointManager:
    """Manages all breakpoints for debugging sessions"""

    def __init__(self):
        self.breakpoints: Dict[str, Breakpoint] = {}
        self.condition_evaluator = ConditionEvaluator()
        self.data_watcher = DataWatcher()

        # Statistics
        self.total_hits = 0
        self.total_evaluations = 0

        logger.info("Breakpoint manager initialized")

    async def add_breakpoint(
        self,
        node_id: Optional[str] = None,
        breakpoint_type: BreakpointType = BreakpointType.NODE,
        condition: Optional[str] = None,
        variable_name: Optional[str] = None,
        change_type: DataChangeType = DataChangeType.CHANGE,
        hit_count: Optional[int] = None,
        time_condition: Optional[str] = None,
        description: str = "",
        tags: List[str] = None,
        **kwargs,
    ) -> Breakpoint:
        """Add a new breakpoint"""

        breakpoint_id = f"bp_{int(time.time())}_{uuid.uuid4().hex[:8]}"

        # Create breakpoint
        breakpoint = Breakpoint(
            breakpoint_id=breakpoint_id,
            breakpoint_type=breakpoint_type,
            node_id=node_id,
            condition=condition,
            variable_name=variable_name,
            change_type=change_type,
            hit_count_target=hit_count,
            time_condition=time_condition,
            description=description,
            tags=tags or [],
            **kwargs,
        )

        # Validate and compile condition if provided
        if condition:
            try:
                breakpoint.condition_function = (
                    self.condition_evaluator.create_condition_function(condition)
                )
            except ValueError as e:
                raise ValueError(f"Invalid condition: {e}")

        # Set up data watching if needed
        if breakpoint_type == BreakpointType.DATA and variable_name:
            self.data_watcher.watch_variable(variable_name)

        # Store breakpoint
        self.breakpoints[breakpoint_id] = breakpoint

        logger.info(f"Added breakpoint {breakpoint_id}: {breakpoint_type.value}")
        return breakpoint

    async def remove_breakpoint(self, breakpoint_id: str) -> bool:
        """Remove a breakpoint"""
        if breakpoint_id not in self.breakpoints:
            return False

        breakpoint = self.breakpoints[breakpoint_id]

        # Stop data watching if needed
        if (
            breakpoint.breakpoint_type == BreakpointType.DATA
            and breakpoint.variable_name
        ):
            self.data_watcher.unwatch_variable(breakpoint.variable_name)

        # Remove breakpoint
        del self.breakpoints[breakpoint_id]

        logger.info(f"Removed breakpoint {breakpoint_id}")
        return True

    async def enable_breakpoint(self, breakpoint_id: str) -> bool:
        """Enable a breakpoint"""
        if breakpoint_id not in self.breakpoints:
            return False

        self.breakpoints[breakpoint_id].enabled = True
        self.breakpoints[breakpoint_id].state = BreakpointState.ACTIVE
        return True

    async def disable_breakpoint(self, breakpoint_id: str) -> bool:
        """Disable a breakpoint"""
        if breakpoint_id not in self.breakpoints:
            return False

        self.breakpoints[breakpoint_id].enabled = False
        self.breakpoints[breakpoint_id].state = BreakpointState.DISABLED
        return True

    async def should_break(
        self, node_id: Optional[str] = None, context: Dict[str, Any] = None
    ) -> bool:
        """Check if execution should break at current point"""
        if not context:
            context = {}

        self.total_evaluations += 1

        for breakpoint in self.breakpoints.values():
            if not breakpoint.enabled or breakpoint.state != BreakpointState.ACTIVE:
                continue

            should_break = False

            try:
                # Check node breakpoint
                if (
                    breakpoint.breakpoint_type == BreakpointType.NODE
                    and breakpoint.node_id == node_id
                ):
                    should_break = True

                # Check condition breakpoint
                elif (
                    breakpoint.breakpoint_type == BreakpointType.CONDITION
                    and breakpoint.condition_function
                ):
                    should_break = bool(breakpoint.condition_function(context))

                # Check data breakpoint
                elif (
                    breakpoint.breakpoint_type == BreakpointType.DATA
                    and breakpoint.variable_name
                    and breakpoint.variable_name in context
                ):
                    should_break = self.data_watcher.check_variable_change(
                        breakpoint.variable_name,
                        context[breakpoint.variable_name],
                        breakpoint.change_type,
                    )

                # Check hit count breakpoint
                elif breakpoint.breakpoint_type == BreakpointType.HIT_COUNT:
                    breakpoint.current_hit_count += 1
                    if (
                        breakpoint.hit_count_target
                        and breakpoint.current_hit_count >= breakpoint.hit_count_target
                    ):
                        should_break = True
                        breakpoint.state = BreakpointState.EXPIRED

                # Check time breakpoint
                elif breakpoint.breakpoint_type == BreakpointType.TIME:
                    should_break = self._check_time_condition(breakpoint)

                # Additional condition check for any breakpoint type
                if should_break and breakpoint.condition_function:
                    should_break = bool(breakpoint.condition_function(context))

                if should_break:
                    await self._record_breakpoint_hit(breakpoint, node_id, context)
                    return True

            except Exception as e:
                logger.error(
                    f"Error evaluating breakpoint {breakpoint.breakpoint_id}: {e}"
                )

        return False

    async def _record_breakpoint_hit(
        self, breakpoint: Breakpoint, node_id: Optional[str], context: Dict[str, Any]
    ):
        """Record a breakpoint hit"""
        hit_id = f"hit_{int(time.time())}_{uuid.uuid4().hex[:8]}"

        hit = BreakpointHit(
            hit_id=hit_id,
            breakpoint_id=breakpoint.breakpoint_id,
            timestamp=datetime.utcnow(),
            node_id=node_id,
            context=context.copy(),  # Make a copy to avoid mutations
            hit_count=len(breakpoint.hits) + 1,
        )

        breakpoint.hits.append(hit)
        breakpoint.state = BreakpointState.HIT

        self.total_hits += 1

        logger.info(f"Breakpoint {breakpoint.breakpoint_id} hit at node {node_id}")

    def _check_time_condition(self, breakpoint: Breakpoint) -> bool:
        """Check if time-based breakpoint should trigger"""
        if not breakpoint.time_condition:
            return False

        try:
            condition = breakpoint.time_condition.lower().strip()
            now = datetime.utcnow()

            # Parse "after Xs" format
            if condition.startswith("after "):
                duration_str = condition[6:].strip()

                # Parse duration (e.g., "5s", "2m", "1h")
                if duration_str.endswith("s"):
                    seconds = float(duration_str[:-1])
                elif duration_str.endswith("m"):
                    seconds = float(duration_str[:-1]) * 60
                elif duration_str.endswith("h"):
                    seconds = float(duration_str[:-1]) * 3600
                else:
                    seconds = float(duration_str)

                elapsed = (now - breakpoint.created_at).total_seconds()
                return elapsed >= seconds

            # Parse "at HH:MM" format
            elif condition.startswith("at "):
                time_str = condition[3:].strip()
                target_time = datetime.strptime(time_str, "%H:%M").time()
                current_time = now.time()

                return current_time >= target_time

            # Parse "every Xs" format (periodic)
            elif condition.startswith("every "):
                # This would need additional state tracking
                # For now, just return False
                return False

        except (ValueError, AttributeError) as e:
            logger.warning(f"Invalid time condition '{breakpoint.time_condition}': {e}")

        return False

    def get_breakpoint(self, breakpoint_id: str) -> Optional[Breakpoint]:
        """Get a specific breakpoint"""
        return self.breakpoints.get(breakpoint_id)

    def get_all_breakpoints(self) -> List[Breakpoint]:
        """Get all breakpoints"""
        return list(self.breakpoints.values())

    def get_breakpoints_by_node(self, node_id: str) -> List[Breakpoint]:
        """Get all breakpoints for a specific node"""
        return [bp for bp in self.breakpoints.values() if bp.node_id == node_id]

    def get_breakpoints_by_type(
        self, breakpoint_type: BreakpointType
    ) -> List[Breakpoint]:
        """Get all breakpoints of a specific type"""
        return [
            bp
            for bp in self.breakpoints.values()
            if bp.breakpoint_type == breakpoint_type
        ]

    def get_active_breakpoints(self) -> List[Breakpoint]:
        """Get all active breakpoints"""
        return [
            bp
            for bp in self.breakpoints.values()
            if bp.enabled and bp.state == BreakpointState.ACTIVE
        ]

    def clear_all_breakpoints(self):
        """Clear all breakpoints"""
        # Stop all data watching
        for breakpoint in self.breakpoints.values():
            if (
                breakpoint.breakpoint_type == BreakpointType.DATA
                and breakpoint.variable_name
            ):
                self.data_watcher.unwatch_variable(breakpoint.variable_name)

        self.breakpoints.clear()
        logger.info("Cleared all breakpoints")

    def get_statistics(self) -> Dict[str, Any]:
        """Get breakpoint statistics"""
        active_count = len(self.get_active_breakpoints())
        disabled_count = len([bp for bp in self.breakpoints.values() if not bp.enabled])

        type_counts = {}
        for bp_type in BreakpointType:
            type_counts[bp_type.value] = len(self.get_breakpoints_by_type(bp_type))

        return {
            "total_breakpoints": len(self.breakpoints),
            "active_breakpoints": active_count,
            "disabled_breakpoints": disabled_count,
            "breakpoints_by_type": type_counts,
            "total_hits": self.total_hits,
            "total_evaluations": self.total_evaluations,
            "hit_rate": (
                self.total_hits / self.total_evaluations
                if self.total_evaluations > 0
                else 0
            ),
        }
