"""Variable Inspector

Provides variable inspection, modification, and expression evaluation
capabilities for workflow debugging.
"""

import ast
import copy
import fnmatch
import inspect
import logging
import sys
import types
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# Pull in execution trace structures from trace_analyzer for tests
try:  # pragma: no cover - defensive import
    from .trace_analyzer import EventType, ExecutionEvent, ExecutionTrace, TraceAnalyzer
except Exception:  # pragma: no cover
    TraceAnalyzer = None
    ExecutionEvent = None
    EventType = None
    ExecutionTrace = None


logger = logging.getLogger(__name__)


# Simple awaitable wrapper so methods can be used in both sync and async flows
class _AwaitableValue:
    def __init__(self, value: Any):
        self._value = value

    def __await__(self):
        async def _wrap():
            return self._value

        return _wrap().__await__()

    def __getattr__(self, item):
        return getattr(self._value, item)

    def __repr__(self):
        return repr(self._value)


def _awaitable(value: Any) -> _AwaitableValue:
    """Return a lightweight awaitable proxy around value."""
    return _AwaitableValue(value)


class VariableScope(str, Enum):
    """Variable scope types"""

    LOCAL = "local"
    GLOBAL = "global"
    BUILTIN = "builtin"
    NODE = "node"  # Node-specific variables
    DAG = "dag"  # DAG-level variables


class VariableType(str, Enum):
    """Variable type categories"

    Note: The more detailed enum values below are kept for backwards
    compatibility with the tests in ``tests/unit/test_debugger/test_inspector.py``
    which expect types like ``INTEGER``/``LIST`` rather than the coarse
    categories used internally. For external callers we still preserve the
    broader categories (PRIMITIVE/COLLECTION/OBJECT/etc.).
    """

    # Fine‑grained types expected by tests/legacy callers
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BOOLEAN = "boolean"
    NONE = "none"
    LIST = "list"
    DICT = "dict"
    TUPLE = "tuple"
    SET = "set"
    OBJECT = "object"

    # Coarse categories used internally
    PRIMITIVE = "primitive"
    COLLECTION = "collection"
    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"
    UNKNOWN = "unknown"


@dataclass
class ExecutionTrace:
    """Minimal execution trace wrapper used in debugger tests."""

    trace_id: str
    events: list[dict[str, Any]]

    def __init__(self, trace_id: str, events: list[dict[str, Any]]):
        self.trace_id = trace_id
        self.events = events or []

    def get_events_by_type(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("event_type") == event_type]

    def get_total_duration(self) -> float:
        if not self.events:
            return 0.0
        try:
            ts = [
                datetime.fromisoformat(e["timestamp"])
                for e in self.events
                if "timestamp" in e
            ]
            if len(ts) >= 2:
                return (max(ts) - min(ts)).total_seconds()
        except Exception:
            return 0.0
        return 0.0

    def get_node_execution_times(self) -> dict[str, float]:
        times: dict[str, float] = {}
        enter_ts: dict[str, datetime] = {}
        for e in self.events:
            node = e.get("node_id")
            if not node or "timestamp" not in e:
                continue
            try:
                ts = datetime.fromisoformat(e["timestamp"])
            except Exception:
                continue
            if e.get("event_type") in {"NODE_ENTER"}:
                enter_ts[node] = ts
            if (
                e.get("event_type") in {"NODE_EXIT", "NODE_SUCCESS", "NODE_ERROR"}
                and node in enter_ts
            ):
                times[node] = max(
                    times.get(node, 0.0), (ts - enter_ts[node]).total_seconds()
                )
        return times

    def get_execution_path(self) -> list[dict[str, Any]]:
        return self.events

    def get_errors(self) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("event_type") == "NODE_ERROR"]

    def get_statistics(self) -> dict[str, Any]:
        nodes = {e.get("node_id") for e in self.events if e.get("node_id")}
        errors = self.get_errors()
        return {
            "total_events": len(self.events),
            "total_nodes": len(nodes),
            "successful_nodes": len(nodes) - len(errors),
            "failed_nodes": len(errors),
            "total_duration": self.get_total_duration(),
        }


@dataclass
class Variable:
    """Lightweight variable representation used by debugger tests."""

    name: str
    value: Any
    type: VariableType
    type_name: str
    size: int

    def __init__(self, name: str, value: Any):
        self.name = name
        self.value = value
        self.type, self.type_name = self._infer_type(value)
        self.size = self._calc_size(value)

    @staticmethod
    def _infer_type(value: Any) -> tuple[VariableType, str]:
        if isinstance(value, bool):
            return VariableType.BOOLEAN, "bool"
        if isinstance(value, int):
            return VariableType.INTEGER, "int"
        if isinstance(value, float):
            return VariableType.FLOAT, "float"
        if isinstance(value, str):
            return VariableType.STRING, "str"
        if value is None:
            return VariableType.NONE, "NoneType"
        if isinstance(value, list):
            return VariableType.LIST, "list"
        if isinstance(value, dict):
            return VariableType.DICT, "dict"
        if isinstance(value, tuple):
            return VariableType.TUPLE, "tuple"
        if isinstance(value, set):
            return VariableType.SET, "set"
        return VariableType.OBJECT, type(value).__name__

    @staticmethod
    def _calc_size(value: Any) -> int:
        try:
            return sys.getsizeof(value)
        except Exception:
            return 0

    def get_summary(self) -> str:
        if self.type in {VariableType.LIST, VariableType.TUPLE, VariableType.SET}:
            length = len(self.value) if hasattr(self.value, "__len__") else 0
            return f"{self.type_name} with {length} items"
        if self.type == VariableType.DICT:
            length = len(self.value) if hasattr(self.value, "__len__") else 0
            return f"dict with {length} keys"
        return str(self.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "type": self.type.value,
            "type_name": self.type_name,
            "size": self.size,
            "summary": self.get_summary(),
        }


@dataclass
class InspectionFilter:
    """Configurable filter for variable inspection."""

    include_private: bool = True
    include_methods: bool = True
    max_depth: int = 5
    max_items: int = 1000
    type_filters: list[VariableType] | None = None
    name_patterns: list[str] | None = None

    def apply_to_variables(self, variables: dict[str, Variable]) -> dict[str, Variable]:
        result = {}
        patterns = self.name_patterns or []
        for name, var in variables.items():
            if not self.include_private and name.startswith("_"):
                continue
            if self.type_filters and var.type not in self.type_filters:
                continue
            if patterns:
                matched = any(fnmatch.fnmatch(name, pat) for pat in patterns)
                if not matched:
                    continue
            result[name] = var
        if len(result) > self.max_items:
            # deterministic truncate
            result = dict(list(result.items())[: self.max_items])
        return result


@dataclass
class StateSnapshot:
    """Minimal snapshot of execution state used for comparisons in tests."""

    session_id: str
    timestamp: datetime
    variables: dict[str, Any]
    node_results: dict[str, Any]
    execution_stack: list[str]


@dataclass
class VariableInfo:
    """Information about a variable (internal, richer than Variable)."""

    name: str
    value: Any
    type_name: str
    scope: VariableScope
    size_bytes: int | None = None
    is_mutable: bool = True
    is_callable: bool = False
    doc_string: str | None = None
    source_location: str | None = None
    attributes: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)

    def to_dict(self, max_value_length: int = 1000) -> dict:
        """Convert to dictionary with value truncation"""
        data = asdict(self)

        # Handle value serialization
        try:
            if self.value is None:
                data["value"] = None
                data["string_value"] = "None"
            elif isinstance(self.value, str | int | float | bool):
                data["value"] = self.value
                data["string_value"] = str(self.value)
            else:
                # For complex objects, store string representation
                string_val = str(self.value)
                if len(string_val) > max_value_length:
                    string_val = string_val[:max_value_length] + "..."
                data["string_value"] = string_val
                data["value"] = f"<{self.type_name} object>"

        except Exception as e:
            data["value"] = f"<Error converting value: {e}>"
            data["string_value"] = data["value"]

        return data

    @staticmethod
    def from_variable(
        name: str, value: Any, scope: VariableScope = VariableScope.LOCAL
    ) -> "VariableInfo":
        """Create VariableInfo from a variable"""

        # Determine type information
        var_type = type(value)
        type_name = var_type.__name__

        # Categorize variable type
        if isinstance(value, int | float | str | bool | type(None)):
            pass
        elif isinstance(value, list | tuple | set | dict):
            pass
        elif callable(value):
            pass
        elif inspect.isclass(value):
            pass
        elif inspect.ismodule(value):
            pass
        else:
            pass

        # Calculate size
        size_bytes = None
        try:
            size_bytes = sys.getsizeof(value)
        except (TypeError, AttributeError):
            pass

        # Check mutability
        is_mutable = not isinstance(
            value, int | float | str | bool | tuple | frozenset | type(None)
        )

        # Check if callable
        is_callable = callable(value)

        # Get docstring
        doc_string = None
        try:
            if hasattr(value, "__doc__") and value.__doc__:
                doc_string = value.__doc__.strip()
        except (AttributeError, TypeError):
            pass

        # Get attributes and methods
        attributes = []
        methods = []

        try:
            for attr_name in dir(value):
                if not attr_name.startswith("_"):
                    try:
                        attr_value = getattr(value, attr_name)
                        if callable(attr_value):
                            methods.append(attr_name)
                        else:
                            attributes.append(attr_name)
                    except (AttributeError, TypeError):
                        pass
        except (TypeError, AttributeError):
            pass

        return VariableInfo(
            name=name,
            value=value,
            type_name=type_name,
            scope=scope,
            size_bytes=size_bytes,
            is_mutable=is_mutable,
            is_callable=is_callable,
            doc_string=doc_string,
            attributes=attributes,
            methods=methods,
        )


@dataclass
class StackFrame:
    """Represents a stack frame for debugging"""

    function_name: str
    node_id: str | None = None
    variables: dict[str, Variable] = field(default_factory=dict)
    file_path: str | None = None
    line_number: int | None = None
    frame_id: str | None = None
    source_code: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["variables"] = {
            name: var.to_dict() for name, var in self.variables.items()
        }
        # datetime to isoformat for serialization
        if isinstance(self.created_at, datetime):
            data["created_at"] = self.created_at.isoformat()
        return data

    # Helpers used in tests
    def get_variable(self, name: str) -> Variable | None:
        return self.variables.get(name)

    def get_variable_names(self) -> list[str]:
        return list(self.variables.keys())

    def filter_variables(
        self,
        exclude_private: bool = False,
        type_filter: VariableType | None = None,
    ) -> dict[str, Variable]:
        result = {}
        for name, var in self.variables.items():
            if exclude_private and name.startswith("_"):
                continue
            if type_filter and var.type != type_filter:
                continue
            result[name] = var
        return result


class ExpressionEvaluator:
    """Safely evaluates expressions in debugging context"""

    def __init__(self):
        # Safe built-in functions
        self.safe_builtins = {
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "chr": chr,
            "dict": dict,
            "dir": dir,
            "divmod": divmod,
            "enumerate": enumerate,
            "filter": filter,
            "float": float,
            "frozenset": frozenset,
            "getattr": getattr,
            "hasattr": hasattr,
            "hash": hash,
            "hex": hex,
            "id": id,
            "int": int,
            "isinstance": isinstance,
            "issubclass": issubclass,
            "iter": iter,
            "len": len,
            "list": list,
            "map": map,
            "max": max,
            "min": min,
            "next": next,
            "oct": oct,
            "ord": ord,
            "pow": pow,
            "range": range,
            "repr": repr,
            "reversed": reversed,
            "round": round,
            "set": set,
            "slice": slice,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "type": type,
            "zip": zip,
        }

        # Forbidden names
        self.forbidden_names = {
            "eval",
            "exec",
            "compile",
            "open",
            "__import__",
            "globals",
            "locals",
            "vars",
            "dir",
            "help",
            "input",
            "print",
            "breakpoint",
        }

        # Safe AST node types
        self.safe_node_types = {
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
            ast.IfExp,
            ast.JoinedStr,
            ast.FormattedValue,
            ast.Slice,
        }

    def validate_expression(self, expression: str) -> tuple[bool, str]:
        """Validate that expression is safe to evaluate"""
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            return False, f"Syntax error: {e}"

        for node in ast.walk(tree):
            node_type = type(node)

            # Check for forbidden node types
            if node_type not in self.safe_node_types:
                return False, f"Forbidden operation: {node_type.__name__}"

            # Check for forbidden names
            if isinstance(node, ast.Name):
                if node.id in self.forbidden_names:
                    return False, f"Forbidden name: {node.id}"

            # Check for forbidden function calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.forbidden_names:
                        return False, f"Forbidden function: {node.func.id}"

            # Check for attribute access to private members
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("_"):
                    return False, f"Access to private attribute: {node.attr}"

        return True, "Expression is safe"

    def evaluate_expression(
        self, expression: str, context: dict[str, Any]
    ) -> tuple[bool, Any, str]:
        """Evaluate expression in given context"""

        # First validate the expression
        is_safe, message = self.validate_expression(expression)
        if not is_safe:
            return False, None, message

        try:
            # Create safe execution environment
            safe_globals = {"__builtins__": self.safe_builtins}
            safe_locals = {}

            # Add context variables
            for name, value in context.items():
                if not name.startswith("_"):
                    safe_locals[name] = value

            # Evaluate expression
            result = eval(expression, safe_globals, safe_locals)
            return True, result, "Success"

        except Exception as e:
            return False, None, f"Evaluation error: {e}"


class WatchExpression:
    """Represents a watched expression"""

    def __init__(self, expression: str, name: str | None = None):
        self.expression = expression
        self.name = name or expression
        self.last_value: Any = None
        self.last_evaluation_time: datetime | None = None
        self.evaluation_count = 0
        self.error_count = 0
        self.last_error: str | None = None

    def evaluate(self, context: dict[str, Any], evaluator: ExpressionEvaluator) -> dict:
        """Evaluate the watch expression"""
        self.evaluation_count += 1
        current_time = datetime.utcnow()

        success, result, message = evaluator.evaluate_expression(
            self.expression, context
        )

        if success:
            self.last_value = result
            self.last_error = None
        else:
            self.error_count += 1
            self.last_error = message

        self.last_evaluation_time = current_time

        return {
            "name": self.name,
            "expression": self.expression,
            "success": success,
            "value": result if success else None,
            "error": message if not success else None,
            "last_evaluation": current_time.isoformat(),
            "evaluation_count": self.evaluation_count,
            "error_count": self.error_count,
        }


class Inspector:
    """Main variable inspector"""

    def __init__(
        self,
        execution_context=None,
        inspection_filter: InspectionFilter | None = None,
    ):
        self.execution_context = execution_context
        self.inspection_filter = inspection_filter or InspectionFilter()
        self.evaluator = ExpressionEvaluator()
        self.watch_expressions: dict[str, WatchExpression] = {}
        self.watched_variables: set[str] = set()
        self.variable_watch_history: dict[str, list[dict[str, Any]]] = {}
        self.variable_history: dict[str, list[Any]] = {}
        self.max_history_per_variable = 100
        self.inspection_history: list[dict[str, Any]] = []

        # Scoped variable stores
        self.scoped_variables: dict[VariableScope, dict[str, Any]] = {
            scope: {} for scope in VariableScope
        }

        logger.info("Variable inspector initialized")

    def _inspect_variable_sync(
        self, name: str, scope: VariableScope = VariableScope.LOCAL
    ) -> Variable | None:
        """Synchronous helper to inspect a specific variable."""
        value = self._get_variable_value(name, scope)
        if value is None and name not in self._get_scope_dict(scope):
            return None
        try:
            return Variable(name, value)
        except Exception:
            return None

    async def inspect_variable(
        self, name: str, scope: VariableScope = VariableScope.LOCAL
    ) -> Variable | None:
        """Async-friendly inspection used in tests/integration."""
        return self._inspect_variable_sync(name, scope)

    def inspect_variables(self, scope: VariableScope = VariableScope.LOCAL):
        """Sync entrypoint kept for backward compatibility; returns awaitable wrapper."""
        return _awaitable(self._inspect_variables_sync(scope))

    async def _inspect_variables_async(
        self, scope: VariableScope = VariableScope.LOCAL
    ) -> dict[str, Variable]:
        return self._inspect_variables_sync(scope)

    def _inspect_variables_sync(
        self, scope: VariableScope = VariableScope.LOCAL
    ) -> dict[str, Variable]:
        scope_dict = self._get_scope_dict(scope)
        variables: dict[str, Variable] = {}
        for name, value in scope_dict.items():
            if not isinstance(name, str):
                continue
            if not self.inspection_filter.include_private and name.startswith("_"):
                continue
            try:
                variables[name] = Variable(name, value)
            except Exception:
                continue
        # apply filters (name/type patterns)
        variables = self.inspection_filter.apply_to_variables(variables)
        self._record_inspection(
            "inspect_variables", {"scope": scope.value, "count": len(variables)}
        )
        return variables

    def inspect_all_variables(self) -> dict[VariableScope, dict[str, VariableInfo]]:
        """Inspect all variables in all scopes"""
        result = {}

        for scope in VariableScope:
            scope_vars = {}
            scope_dict = self._get_scope_dict(scope)

            for name, value in scope_dict.items():
                if not name.startswith("_"):  # Skip private variables
                    try:
                        var_info = VariableInfo.from_variable(name, value, scope)
                        scope_vars[name] = var_info
                    except Exception as e:
                        logger.warning(f"Failed to inspect variable {name}: {e}")

            result[scope] = scope_vars

        return result

    async def get_current_stack_frame(self) -> StackFrame | None:
        """Return a simple stack frame based on current execution context."""
        if not self.execution_context:
            return None
        variables = {
            name: Variable(name, val)
            for name, val in self.execution_context.variables.items()
            if not str(name).startswith("_")
        }
        frame = StackFrame(
            function_name=self.execution_context.current_node or "current",
            node_id=self.execution_context.current_node,
            variables=variables,
            file_path=None,
            line_number=None,
        )
        self._record_inspection(
            "stack_frame", {"node": self.execution_context.current_node}
        )
        return frame

    async def inspect_execution_state(self) -> dict[str, Any]:
        """Return a serialized view of execution state."""
        if not self.execution_context:
            return {}
        state = {
            "session_id": getattr(self.execution_context, "session_id", None),
            "current_node": self.execution_context.current_node,
            "execution_stack": list(self.execution_context.execution_stack),
            "variables": dict(self.execution_context.variables),
            "node_results": dict(self.execution_context.node_results),
        }
        self._record_inspection(
            "execution_state",
            {"stack_len": len(self.execution_context.execution_stack)},
        )
        return state

    async def inspect_node_results(self) -> dict[str, Any]:
        if not self.execution_context:
            return {}
        self._record_inspection(
            "node_results", {"count": len(self.execution_context.node_results)}
        )
        return dict(self.execution_context.node_results)

    async def inspect_node_result(self, node_id: str) -> dict[str, Any] | None:
        if not self.execution_context:
            return None
        self._record_inspection("node_result", {"node": node_id})
        return self.execution_context.node_results.get(node_id)

    def modify_variable(
        self, name: str, new_value: Any, scope: VariableScope = VariableScope.LOCAL
    ) -> bool:
        """Modify a variable's value"""
        try:
            scope_dict = self._get_scope_dict(scope)

            if name not in scope_dict:
                return False

            # Record old value in history
            old_value = scope_dict[name]
            self._record_variable_change(name, old_value, new_value)

            # Set new value
            scope_dict[name] = new_value

            # If we have execution context, update it too
            if self.execution_context and scope == VariableScope.LOCAL:
                self.execution_context.variables[name] = new_value
            elif self.execution_context and scope == VariableScope.DAG:
                self.execution_context.dag_definition.global_parameters[name] = (
                    new_value
                )

            logger.info(f"Modified variable {name} in {scope.value} scope")
            return True

        except Exception as e:
            logger.error(f"Failed to modify variable {name}: {e}")
            return False

    def create_variable(
        self, name: str, value: Any, scope: VariableScope = VariableScope.LOCAL
    ) -> bool:
        """Create a new variable"""
        try:
            scope_dict = self._get_scope_dict(scope)

            # Check if variable already exists
            if name in scope_dict:
                logger.warning(f"Variable {name} already exists in {scope.value} scope")
                return False

            # Create variable
            scope_dict[name] = value

            # Update execution context if needed
            if self.execution_context and scope == VariableScope.LOCAL:
                self.execution_context.variables[name] = value
            elif self.execution_context and scope == VariableScope.DAG:
                self.execution_context.dag_definition.global_parameters[name] = value

            # Record creation
            self._record_variable_change(name, None, value)

            logger.info(f"Created variable {name} in {scope.value} scope")
            return True

        except Exception as e:
            logger.error(f"Failed to create variable {name}: {e}")
            return False

    def delete_variable(
        self, name: str, scope: VariableScope = VariableScope.LOCAL
    ) -> bool:
        """Delete a variable"""
        try:
            scope_dict = self._get_scope_dict(scope)

            if name not in scope_dict:
                return False

            # Record deletion
            old_value = scope_dict[name]
            self._record_variable_change(name, old_value, None)

            # Delete variable
            del scope_dict[name]

            # Update execution context if needed
            if self.execution_context and scope == VariableScope.LOCAL:
                self.execution_context.variables.pop(name, None)
            elif self.execution_context and scope == VariableScope.DAG:
                self.execution_context.dag_definition.global_parameters.pop(name, None)

            logger.info(f"Deleted variable {name} from {scope.value} scope")
            return True

        except Exception as e:
            logger.error(f"Failed to delete variable {name}: {e}")
            return False

    async def start_watching_variable(self, name: str) -> bool:
        """Begin tracking changes to a variable in the current execution context."""
        self.watched_variables.add(name)
        if name not in self.variable_watch_history:
            self.variable_watch_history[name] = []
        return True

    async def update_watched_variables(self):
        """Capture the current value of watched variables."""
        if not self.execution_context:
            return
        now = datetime.utcnow().isoformat()
        for name in list(self.watched_variables):
            value = self.execution_context.variables.get(name)
            history = self.variable_watch_history.setdefault(name, [])
            history.append({"timestamp": now, "value": value})
            # keep small history
            if len(history) > self.max_history_per_variable:
                history.pop(0)

    async def get_variable_watch_history(self, name: str) -> list[dict[str, Any]]:
        return self.variable_watch_history.get(name, [])

    def evaluate_expression(self, expression: str) -> dict[str, Any]:
        """Evaluate an expression in current context"""

        # Gather all variables from all scopes for context
        context = {}
        for scope in VariableScope:
            scope_dict = self._get_scope_dict(scope)
            for name, value in scope_dict.items():
                if not name.startswith("_"):
                    context[name] = value

        success, result, message = self.evaluator.evaluate_expression(
            expression, context
        )

        return {
            "expression": expression,
            "success": success,
            "result": result,
            "message": message,
            "context_size": len(context),
            "evaluation_time": datetime.utcnow().isoformat(),
        }

    def add_watch_expression(self, expression: str, name: str | None = None) -> str:
        """Add a watch expression"""
        watch_name = name or f"watch_{len(self.watch_expressions)}"

        watch = WatchExpression(expression, watch_name)
        self.watch_expressions[watch_name] = watch

        logger.info(f"Added watch expression: {watch_name} = {expression}")
        return watch_name

    def remove_watch_expression(self, name: str) -> bool:
        """Remove a watch expression"""
        if name in self.watch_expressions:
            del self.watch_expressions[name]
            logger.info(f"Removed watch expression: {name}")
            return True
        return False

    def evaluate_all_watches(self) -> dict[str, dict]:
        """Evaluate all watch expressions"""
        results = {}

        # Gather context
        context = {}
        for scope in VariableScope:
            scope_dict = self._get_scope_dict(scope)
            for name, value in scope_dict.items():
                if not name.startswith("_"):
                    context[name] = value

        # Evaluate each watch
        for watch_name, watch in self.watch_expressions.items():
            results[watch_name] = watch.evaluate(context, self.evaluator)

        return results

    def get_call_stack(self) -> list[StackFrame]:
        """Get current call stack"""
        frames = []

        if self.execution_context:
            # Build stack from execution context
            for i, node_id in enumerate(self.execution_context.execution_stack):
                frame = StackFrame(
                    frame_id=f"frame_{i}",
                    function_name=node_id,
                    filename=None,
                    line_number=None,
                )

                # Add variables visible at this frame
                frame.variables = {}

                # Add local variables
                for name, value in self.execution_context.variables.items():
                    if not name.startswith("_"):
                        frame.variables[name] = VariableInfo.from_variable(
                            name, value, VariableScope.LOCAL
                        )

                # Add node results up to this point
                for (
                    result_name,
                    result_value,
                ) in self.execution_context.node_results.items():
                    frame.variables[f"{result_name}_result"] = (
                        VariableInfo.from_variable(
                            f"{result_name}_result", result_value, VariableScope.NODE
                        )
                    )

                frames.append(frame)

        return frames

    def get_variable_history(self, name: str) -> list[dict]:
        """Get history of changes for a variable"""
        history = self.variable_history.get(name, [])

        return [
            {
                "timestamp": change["timestamp"].isoformat(),
                "old_value": str(change["old_value"]),
                "new_value": str(change["new_value"]),
                "change_type": change["change_type"],
            }
            for change in history
        ]

    def search_variables(
        self, query: str, scope: VariableScope | None = None
    ) -> list[VariableInfo]:
        """Search for variables matching query"""
        results = []

        scopes_to_search = [scope] if scope else list(VariableScope)

        for search_scope in scopes_to_search:
            scope_dict = self._get_scope_dict(search_scope)

            for name, value in scope_dict.items():
                # Search by name
                if query.lower() in name.lower():
                    var_info = VariableInfo.from_variable(name, value, search_scope)
                    results.append(var_info)
                # Search by type
                elif query.lower() in type(value).__name__.lower():
                    var_info = VariableInfo.from_variable(name, value, search_scope)
                    results.append(var_info)
                # Search by string representation
                elif query.lower() in str(value).lower():
                    var_info = VariableInfo.from_variable(name, value, search_scope)
                    results.append(var_info)

        return results

    async def deep_inspect_variable(
        self, name: str, max_depth: int = 3
    ) -> dict[str, Any] | None:
        """Recursively inspect a variable up to max_depth."""
        value = self._get_variable_value(name, VariableScope.LOCAL)
        if value is None and self.execution_context:
            value = self.execution_context.variables.get(name)
        if value is None:
            return None

        def _walk(val, depth):
            var_type, type_name = Variable(name, val)._infer_type(val)
            node = {"type": var_type.value, "type_name": type_name}
            if depth >= max_depth:
                return node
            if isinstance(val, dict):
                node["children"] = {k: _walk(v, depth + 1) for k, v in val.items()}
            elif isinstance(val, list | tuple):
                node["children"] = {
                    str(i): _walk(v, depth + 1) for i, v in enumerate(val)
                }
            return node

        result = _walk(value, 0)
        result["name"] = name
        return result

    def get_inspection_history(self) -> list[dict[str, Any]]:
        return self.inspection_history

    async def inspect_memory_usage(self) -> dict[str, Any]:
        if not self.execution_context:
            return {
                "total_variables": 0,
                "total_size_bytes": 0,
                "largest_variables": [],
            }
        vars_dict = self.execution_context.variables
        sizes = []
        total = 0
        for name, val in vars_dict.items():
            try:
                size = sys.getsizeof(val)
            except Exception:
                size = 0
            total += size
            sizes.append((name, size, Variable(name, val)))
        sizes.sort(key=lambda x: x[1], reverse=True)
        largest = [
            {"name": n, "size": s, "type": v.type.value, "value": v.value}
            for n, s, v in sizes[:5]
        ]
        return {
            "total_variables": len(vars_dict),
            "total_size_bytes": total,
            "largest_variables": largest,
        }

    async def create_state_snapshot(self) -> "StateSnapshot":
        if not self.execution_context:
            return StateSnapshot("unknown", datetime.utcnow(), {}, {}, [])
        return StateSnapshot(
            session_id=self.execution_context.session_id,
            timestamp=datetime.utcnow(),
            variables=copy.deepcopy(self.execution_context.variables),
            node_results=copy.deepcopy(self.execution_context.node_results),
            execution_stack=list(self.execution_context.execution_stack),
        )

    def compare_snapshots(
        self, snap1: "StateSnapshot", snap2: "StateSnapshot"
    ) -> dict[str, Any]:
        vars1 = snap1.variables
        vars2 = snap2.variables
        added = {k: v for k, v in vars2.items() if k not in vars1}
        removed = {k: v for k, v in vars1.items() if k not in vars2}
        modified = {}
        for k in vars1.keys() & vars2.keys():
            if vars1[k] != vars2[k]:
                modified[k] = {"old_value": vars1[k], "new_value": vars2[k]}
        return {
            "added_variables": added,
            "removed_variables": removed,
            "modified_variables": modified,
        }

    def get_inspector_statistics(self) -> dict[str, Any]:
        """Get inspector statistics"""
        stats = {
            "total_variables": 0,
            "variables_by_scope": {},
            "watch_expressions": len(self.watch_expressions),
            "variable_history_entries": sum(
                len(history) for history in self.variable_history.values()
            ),
        }

        for scope in VariableScope:
            scope_dict = self._get_scope_dict(scope)
            count = len(
                [name for name in scope_dict.keys() if not name.startswith("_")]
            )
            stats["variables_by_scope"][scope.value] = count
            stats["total_variables"] += count

        return stats

    def _record_inspection(self, operation: str, details: dict[str, Any]):
        """Track inspection operations for history/debugging."""
        record = {
            "timestamp": datetime.utcnow(),
            "operation": operation,
            "details": details,
        }
        self.inspection_history.append(record)

    def _get_variable_value(self, name: str, scope: VariableScope) -> Any:
        """Get variable value from specified scope"""
        scope_dict = self._get_scope_dict(scope)
        return scope_dict.get(name)

    def _get_scope_dict(self, scope: VariableScope) -> dict[str, Any]:
        """Get the dictionary for a specific scope"""
        if scope == VariableScope.LOCAL:
            return self.scoped_variables[scope]
        elif scope == VariableScope.GLOBAL:
            return globals()
        elif scope == VariableScope.BUILTIN:
            return (
                vars(__builtins__)
                if isinstance(__builtins__, types.ModuleType)
                else __builtins__
            )
        elif scope == VariableScope.NODE and self.execution_context:
            return self.execution_context.node_results
        elif scope == VariableScope.DAG and self.execution_context:
            return self.execution_context.dag_definition.global_parameters
        else:
            return self.scoped_variables[scope]

    def _record_variable_change(self, name: str, old_value: Any, new_value: Any):
        """Record a variable change in history"""
        if name not in self.variable_history:
            self.variable_history[name] = []

        change_type = (
            "created"
            if old_value is None
            else "deleted" if new_value is None else "modified"
        )

        change_record = {
            "timestamp": datetime.utcnow(),
            "old_value": old_value,
            "new_value": new_value,
            "change_type": change_type,
        }

        history = self.variable_history[name]
        history.append(change_record)

        # Trim history if needed
        if len(history) > self.max_history_per_variable:
            history.pop(0)
