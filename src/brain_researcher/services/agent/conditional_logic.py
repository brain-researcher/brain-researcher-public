"""
Conditional Logic Executor for Complex DAG Workflows

This module provides safe evaluation of conditional expressions and execution of
conditional branches in DAG workflows. It supports:
- Safe expression evaluation with restricted scope
- Comparison operators and logical operations
- Variable substitution from execution context
- Switch/case statements with default branches
- Type-safe comparisons
"""

import ast
import logging
import operator
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class ComparisonOperator(Enum):
    """Supported comparison operators"""

    EQ = "=="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    IN = "in"
    NOT_IN = "not in"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    REGEX = "regex"


class LogicalOperator(Enum):
    """Supported logical operators"""

    AND = "and"
    OR = "or"
    NOT = "not"


@dataclass
class ConditionResult:
    """Result of condition evaluation"""

    value: bool
    explanation: str
    variables_used: List[str]
    errors: List[str] = None


class SafeExpressionEvaluator:
    """Safe evaluation of expressions with restricted operations"""

    # Allowed operations for safe evaluation
    ALLOWED_OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.In: lambda x, y: x in y,
        ast.NotIn: lambda x, y: x not in y,
        ast.And: lambda x, y: x and y,
        ast.Or: lambda x, y: x or y,
        ast.Not: operator.not_,
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    # Allowed functions
    ALLOWED_FUNCTIONS = {
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
    }

    def __init__(self):
        self.variables_used = set()

    def evaluate(self, expression: str, context: Dict[str, Any]) -> Any:
        """Safely evaluate an expression with given context"""
        self.variables_used.clear()

        try:
            # Parse the expression
            tree = ast.parse(expression, mode="eval")
            return self._eval_node(tree.body, context)
        except Exception as e:
            logger.error(f"Error evaluating expression '{expression}': {e}")
            raise ValueError(f"Invalid expression: {e}")

    def _eval_node(self, node: ast.AST, context: Dict[str, Any]) -> Any:
        """Recursively evaluate AST nodes"""
        if isinstance(node, ast.Constant):  # Python 3.8+
            return node.value
        elif isinstance(node, ast.Num):  # Python < 3.8
            return node.n
        elif isinstance(node, ast.Str):  # Python < 3.8
            return node.s
        elif isinstance(node, ast.NameConstant):  # Python < 3.8
            return node.value
        elif isinstance(node, ast.Name):
            var_name = node.id
            self.variables_used.add(var_name)
            if var_name in context:
                return context[var_name]
            else:
                raise NameError(f"Variable '{var_name}' not found in context")
        elif isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, context)
            right = self._eval_node(node.right, context)
            op_func = self.ALLOWED_OPERATORS.get(type(node.op))
            if op_func:
                return op_func(left, right)
            else:
                raise ValueError(f"Operator {type(node.op).__name__} not allowed")
        elif isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand, context)
            op_func = self.ALLOWED_OPERATORS.get(type(node.op))
            if op_func:
                return op_func(operand)
            else:
                raise ValueError(f"Unary operator {type(node.op).__name__} not allowed")
        elif isinstance(node, ast.Compare):
            left = self._eval_node(node.left, context)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, context)
                op_func = self.ALLOWED_OPERATORS.get(type(op))
                if op_func:
                    if not op_func(left, right):
                        return False
                    left = right  # For chained comparisons
                else:
                    raise ValueError(
                        f"Comparison operator {type(op).__name__} not allowed"
                    )
            return True
        elif isinstance(node, ast.BoolOp):
            values = [self._eval_node(value, context) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            elif isinstance(node.op, ast.Or):
                return any(values)
            else:
                raise ValueError(
                    f"Boolean operator {type(node.op).__name__} not allowed"
                )
        elif isinstance(node, ast.Call):
            func_name = node.func.id if isinstance(node.func, ast.Name) else None
            if func_name in self.ALLOWED_FUNCTIONS:
                args = [self._eval_node(arg, context) for arg in node.args]
                kwargs = {
                    kw.arg: self._eval_node(kw.value, context) for kw in node.keywords
                }
                return self.ALLOWED_FUNCTIONS[func_name](*args, **kwargs)
            else:
                raise ValueError(f"Function '{func_name}' not allowed")
        elif isinstance(node, ast.Subscript):
            value = self._eval_node(node.value, context)
            slice_value = self._eval_node(node.slice, context)
            return value[slice_value]
        elif isinstance(node, ast.Attribute):
            value = self._eval_node(node.value, context)
            return getattr(value, node.attr)
        elif isinstance(node, ast.List):
            return [self._eval_node(elem, context) for elem in node.elts]
        elif isinstance(node, ast.Dict):
            keys = [self._eval_node(k, context) for k in node.keys]
            values = [self._eval_node(v, context) for v in node.values]
            return dict(zip(keys, values))
        else:
            raise ValueError(f"AST node type {type(node).__name__} not allowed")


class ConditionalExecutor:
    """Executes conditional logic in DAG workflows"""

    def __init__(self):
        self.evaluator = SafeExpressionEvaluator()

    def evaluate_condition(
        self, condition: str, context: Dict[str, Any]
    ) -> ConditionResult:
        """Evaluate a conditional expression and return detailed result"""
        try:
            # Preprocess condition for common patterns
            processed_condition = self._preprocess_condition(condition)

            # Evaluate the condition
            result = self.evaluator.evaluate(processed_condition, context)

            # Convert to boolean if necessary
            bool_result = bool(result)

            return ConditionResult(
                value=bool_result,
                explanation=f"Condition '{condition}' evaluated to {bool_result}",
                variables_used=list(self.evaluator.variables_used),
                errors=[],
            )

        except Exception as e:
            logger.error(f"Error evaluating condition '{condition}': {e}")
            return ConditionResult(
                value=False,
                explanation=f"Condition evaluation failed: {e}",
                variables_used=[],
                errors=[str(e)],
            )

    def _preprocess_condition(self, condition: str) -> str:
        """Preprocess condition to handle common patterns"""
        # Handle attribute access patterns like "node.status == 'success'"
        condition = re.sub(r"(\w+)\.(\w+)", r'\1["\2"]', condition)

        # Handle contains/starts_with/ends_with patterns
        condition = re.sub(r"(\w+)\s+contains\s+(.+)", r'"\2" in \1', condition)
        condition = re.sub(
            r"(\w+)\s+starts_with\s+(.+)", r"\1.startswith(\2)", condition
        )
        condition = re.sub(r"(\w+)\s+ends_with\s+(.+)", r"\1.endswith(\2)", condition)

        return condition

    def execute_if_else(
        self,
        condition: str,
        true_branch: List[str],
        false_branch: List[str],
        context: Dict[str, Any],
    ) -> List[str]:
        """Execute if-else conditional logic"""
        result = self.evaluate_condition(condition, context)

        if result.value:
            logger.info(f"Condition '{condition}' is true, executing true branch")
            return true_branch
        else:
            logger.info(f"Condition '{condition}' is false, executing false branch")
            return false_branch

    def execute_switch(
        self,
        switch_value: Any,
        branches: Dict[str, List[str]],
        default_branch: Optional[List[str]] = None,
    ) -> List[str]:
        """Execute switch-case logic"""
        switch_value_str = str(switch_value)

        if switch_value_str in branches:
            logger.info(f"Switch value '{switch_value}' matched, executing branch")
            return branches[switch_value_str]
        elif default_branch:
            logger.info(
                f"Switch value '{switch_value}' not matched, executing default branch"
            )
            return default_branch
        else:
            logger.warning(
                f"Switch value '{switch_value}' not matched and no default branch"
            )
            return []

    def execute_multi_condition(
        self, conditions: List[Dict[str, Any]], context: Dict[str, Any]
    ) -> List[str]:
        """Execute multiple conditions (if-elif-else pattern)"""
        for condition_spec in conditions:
            condition = condition_spec.get("condition")
            branch = condition_spec.get("branch", [])

            if condition is None:  # else clause
                logger.info("Executing else clause")
                return branch

            result = self.evaluate_condition(condition, context)
            if result.value:
                logger.info(f"Condition '{condition}' is true, executing branch")
                return branch

        logger.info("No conditions matched, no branch executed")
        return []


class LoopManager:
    """Manages loop execution with bounds checking and break conditions"""

    def __init__(self):
        self.evaluator = SafeExpressionEvaluator()
        self.max_global_iterations = 10000  # Global safety limit

    def execute_for_loop(
        self,
        items: List[Any],
        body: List[str],
        max_iterations: int,
        context: Dict[str, Any],
        break_condition: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a for loop with iteration bounds"""
        results = []
        iterations = 0

        for i, item in enumerate(items):
            if iterations >= max_iterations:
                logger.warning(
                    f"For loop terminated: reached max iterations ({max_iterations})"
                )
                break

            if iterations >= self.max_global_iterations:
                logger.error(
                    f"For loop terminated: reached global safety limit ({self.max_global_iterations})"
                )
                break

            # Update context with loop variables
            loop_context = context.copy()
            loop_context.update(
                {"loop_item": item, "loop_index": i, "loop_iteration": iterations}
            )

            # Check break condition
            if break_condition and self._should_break(break_condition, loop_context):
                logger.info(f"For loop terminated: break condition met")
                break

            # Execute loop body (this would be handled by the DAG executor)
            results.append(
                {
                    "iteration": iterations,
                    "item": item,
                    "body_nodes": body,
                    "context": loop_context,
                }
            )

            iterations += 1

        return results

    def execute_while_loop(
        self,
        condition: str,
        body: List[str],
        max_iterations: int,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Execute a while loop with iteration bounds"""
        results = []
        iterations = 0

        while iterations < max_iterations and iterations < self.max_global_iterations:
            # Update context with loop variables
            loop_context = context.copy()
            loop_context.update({"loop_iteration": iterations})

            # Evaluate while condition
            try:
                condition_result = self.evaluator.evaluate(condition, loop_context)
                if not condition_result:
                    logger.info(
                        f"While loop terminated: condition '{condition}' is false"
                    )
                    break
            except Exception as e:
                logger.error(f"Error evaluating while condition '{condition}': {e}")
                break

            # Execute loop body
            results.append(
                {"iteration": iterations, "body_nodes": body, "context": loop_context}
            )

            iterations += 1

        if iterations >= max_iterations:
            logger.warning(
                f"While loop terminated: reached max iterations ({max_iterations})"
            )
        elif iterations >= self.max_global_iterations:
            logger.error(
                f"While loop terminated: reached global safety limit ({self.max_global_iterations})"
            )

        return results

    def execute_foreach_loop(
        self,
        items_param: str,
        body: List[str],
        max_iterations: int,
        context: Dict[str, Any],
        break_condition: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a foreach loop over items in context"""
        if items_param not in context:
            logger.error(
                f"Foreach loop error: items parameter '{items_param}' not found in context"
            )
            return []

        items = context[items_param]
        if not isinstance(items, (list, tuple)):
            logger.error(
                f"Foreach loop error: items parameter '{items_param}' is not iterable"
            )
            return []

        return self.execute_for_loop(
            items, body, max_iterations, context, break_condition
        )

    def _should_break(self, break_condition: str, context: Dict[str, Any]) -> bool:
        """Check if break condition is met"""
        try:
            result = self.evaluator.evaluate(break_condition, context)
            return bool(result)
        except Exception as e:
            logger.error(f"Error evaluating break condition '{break_condition}': {e}")
            return False


class ConditionalBranchBuilder:
    """Helper class to build conditional branches programmatically"""

    def __init__(self):
        self.conditions = []

    def if_condition(
        self, condition: str, branch: List[str]
    ) -> "ConditionalBranchBuilder":
        """Add an if condition"""
        self.conditions.append({"type": "if", "condition": condition, "branch": branch})
        return self

    def elif_condition(
        self, condition: str, branch: List[str]
    ) -> "ConditionalBranchBuilder":
        """Add an elif condition"""
        self.conditions.append(
            {"type": "elif", "condition": condition, "branch": branch}
        )
        return self

    def else_branch(self, branch: List[str]) -> "ConditionalBranchBuilder":
        """Add an else branch"""
        self.conditions.append({"type": "else", "condition": None, "branch": branch})
        return self

    def build(self) -> List[Dict[str, Any]]:
        """Build the conditional structure"""
        return self.conditions.copy()


# Example usage and testing
if __name__ == "__main__":
    # Test conditional executor
    executor = ConditionalExecutor()

    # Test basic conditions
    context = {
        "qc_score": 0.85,
        "subjects": ["sub-001", "sub-002", "sub-003"],
        "threshold": 0.05,
        "preprocessing": {"status": "success", "qc_score": 0.85},
    }

    # Test simple condition
    result = executor.evaluate_condition("qc_score > 0.8", context)
    print(f"Simple condition result: {result.value}")

    # Test complex condition
    result = executor.evaluate_condition(
        "len(subjects) >= 3 and threshold < 0.1", context
    )
    print(f"Complex condition result: {result.value}")

    # Test attribute access
    result = executor.evaluate_condition(
        'preprocessing["status"] == "success"', context
    )
    print(f"Attribute access result: {result.value}")

    # Test loop manager
    loop_manager = LoopManager()

    # Test for loop
    loop_results = loop_manager.execute_for_loop(
        items=["sub-001", "sub-002"],
        body=["process_subject", "compute_stats"],
        max_iterations=10,
        context=context,
    )
    print(f"For loop executed {len(loop_results)} iterations")

    # Test conditional branch builder
    builder = ConditionalBranchBuilder()
    branches = (
        builder.if_condition("qc_score > 0.9", ["high_quality_analysis"])
        .elif_condition("qc_score > 0.7", ["standard_analysis"])
        .else_branch(["reprocess_data"])
        .build()
    )

    print(f"Built {len(branches)} conditional branches")
