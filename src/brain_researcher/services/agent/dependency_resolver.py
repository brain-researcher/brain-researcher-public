"""
Dependency Resolution for Parallel Execution (AGENT-015)

This module implements dependency resolution with topological sorting,
cycle detection, and execution graph generation for parallel task execution.
"""

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)


class DependencyType(str, Enum):
    """Types of dependencies between tasks."""

    DATA = "data"  # Task B needs output from Task A
    RESOURCE = "resource"  # Task B needs resource freed by Task A
    ORDERING = "ordering"  # Task B must run after Task A (soft dependency)
    CONDITIONAL = "conditional"  # Task B runs only if Task A succeeds


@dataclass
class Dependency:
    """Represents a dependency between tasks."""

    from_task: str
    to_task: str
    dependency_type: DependencyType
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Task:
    """Represents a task node in the execution graph."""

    task_id: str
    name: str
    tool_name: str
    tool_args: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    estimated_duration: float = 60.0
    priority: int = 1  # 1=low, 2=medium, 3=high
    resource_requirements: Dict[str, float] = field(default_factory=dict)


@dataclass
class ExecutionGraph:
    """Represents a directed acyclic graph of tasks for execution."""

    graph_id: str = field(default_factory=lambda: str(uuid4()))
    tasks: List[Task] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionBatch:
    """Represents a batch of tasks that can execute in parallel."""

    batch_id: str
    tasks: List[Task]
    batch_level: int  # 0 is first batch, 1 is second, etc.
    estimated_duration: float = 0.0  # Max duration in batch
    total_resource_needs: Dict[str, float] = field(default_factory=dict)


class CycleDetectionError(Exception):
    """Raised when a dependency cycle is detected."""

    def __init__(self, cycle: List[str]):
        self.cycle = cycle
        super().__init__(f"Dependency cycle detected: {' -> '.join(cycle)}")


class DependencyResolver:
    """
    Resolves task dependencies and creates execution graphs for parallel execution.

    Features:
    - Topological sorting for dependency ordering
    - Cycle detection and reporting
    - Batch generation for parallel execution
    - Resource-aware grouping
    - Priority-based optimization
    """

    def __init__(self):
        """Initialize dependency resolver."""
        self.logger = logging.getLogger(__name__)

    def resolve(self, tasks: List[Task]) -> ExecutionGraph:
        """
        Resolve task dependencies and create execution graph.

        Args:
            tasks: List of tasks with dependencies

        Returns:
            Execution graph with resolved dependencies

        Raises:
            CycleDetectionError: If circular dependencies are found
        """
        if not tasks:
            return ExecutionGraph(graph_id=str(uuid4()), tasks=[], dependencies=[])

        # Build dependency graph
        graph = self._build_graph(tasks)

        # Detect cycles
        cycles = self._detect_cycles(graph)
        if cycles:
            raise CycleDetectionError(cycles[0])  # Report first cycle found

        # Perform topological sort
        sorted_tasks = self._topological_sort(tasks, graph)

        # Extract explicit dependency relationships
        dependencies = self._extract_dependencies(sorted_tasks, graph)

        # Create execution graph
        execution_graph = ExecutionGraph(
            graph_id=str(uuid4()),
            tasks=sorted_tasks,
            dependencies=dependencies,
            metadata={
                "total_tasks": len(sorted_tasks),
                "dependency_count": len(dependencies),
                "max_parallelism": self._calculate_max_parallelism(sorted_tasks, graph),
            },
        )

        self.logger.info(
            f"Resolved dependencies for {len(tasks)} tasks, "
            f"max parallelism: {execution_graph.metadata['max_parallelism']}"
        )

        return execution_graph

    def _build_graph(self, tasks: List[Task]) -> Dict[str, Set[str]]:
        """
        Build adjacency list representation of dependency graph.

        Args:
            tasks: List of tasks

        Returns:
            Dictionary mapping task_id to set of dependent task_ids
        """
        graph = defaultdict(set)
        task_ids = {task.task_id for task in tasks}

        for task in tasks:
            for dep_id in task.dependencies:
                if dep_id in task_ids:
                    graph[dep_id].add(task.task_id)
                else:
                    self.logger.warning(
                        f"Task {task.task_id} has invalid dependency: {dep_id}"
                    )

        # Ensure all tasks are represented in graph
        for task in tasks:
            if task.task_id not in graph:
                graph[task.task_id] = set()

        return dict(graph)

    def _detect_cycles(self, graph: Dict[str, Set[str]]) -> List[List[str]]:
        """
        Detect cycles in the dependency graph using DFS.

        Args:
            graph: Adjacency list representation

        Returns:
            List of cycles found (each cycle is a list of task_ids)
        """
        cycles = []
        visited = set()
        rec_stack = set()

        def dfs_cycle_detect(node: str, path: List[str]) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    if dfs_cycle_detect(neighbor, path.copy()):
                        return True
                elif neighbor in rec_stack:
                    # Found back edge - cycle detected
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)
                    return True

            rec_stack.remove(node)
            return False

        for node in graph:
            if node not in visited:
                dfs_cycle_detect(node, [])

        return cycles

    def _topological_sort(
        self, tasks: List[Task], graph: Dict[str, Set[str]]
    ) -> List[Task]:
        """
        Perform topological sort using Kahn's algorithm with priority handling.

        Args:
            tasks: Original list of tasks
            graph: Dependency graph

        Returns:
            Topologically sorted list of tasks
        """
        # Create task lookup
        task_lookup = {task.task_id: task for task in tasks}

        # Calculate in-degrees
        in_degree = defaultdict(int)
        for node in graph:
            for neighbor in graph[node]:
                in_degree[neighbor] += 1

        # Initialize queue with nodes having no incoming edges
        # Use priority queue (simulate with sorted list) for deterministic ordering
        queue = []
        for task in tasks:
            if in_degree[task.task_id] == 0:
                queue.append(task)

        # Sort by priority (higher priority first) and then by name for determinism
        queue.sort(key=lambda t: (-t.priority, t.task_id))

        result = []

        while queue:
            # Remove highest priority task
            current_task = queue.pop(0)
            result.append(current_task)

            # Process all dependent tasks
            dependents = []
            for dependent_id in graph.get(current_task.task_id, set()):
                in_degree[dependent_id] -= 1

                if in_degree[dependent_id] == 0:
                    dependent_task = task_lookup[dependent_id]
                    dependents.append(dependent_task)

            # Add ready tasks to queue maintaining priority order
            dependents.sort(key=lambda t: (-t.priority, t.task_id))

            # Insert into queue maintaining sorted order
            for dep_task in dependents:
                inserted = False
                for i, queued_task in enumerate(queue):
                    if dep_task.priority > queued_task.priority or (
                        dep_task.priority == queued_task.priority
                        and dep_task.task_id < queued_task.task_id
                    ):
                        queue.insert(i, dep_task)
                        inserted = True
                        break
                if not inserted:
                    queue.append(dep_task)

        if len(result) != len(tasks):
            missing_tasks = [task.task_id for task in tasks if task not in result]
            raise CycleDetectionError(missing_tasks)

        return result

    def _extract_dependencies(
        self, sorted_tasks: List[Task], graph: Dict[str, Set[str]]
    ) -> List[Dependency]:
        """
        Extract explicit dependency objects from the graph.

        Args:
            sorted_tasks: Topologically sorted tasks
            graph: Dependency graph

        Returns:
            List of dependency objects
        """
        dependencies = []

        for task in sorted_tasks:
            for dep_task_id in task.dependencies:
                # Determine dependency type based on heuristics
                dep_type = self._infer_dependency_type(task, dep_task_id)

                dependency = Dependency(
                    from_task=dep_task_id,
                    to_task=task.task_id,
                    dependency_type=dep_type,
                    metadata={},
                )
                dependencies.append(dependency)

        return dependencies

    def _infer_dependency_type(self, task: Task, dependency_id: str) -> DependencyType:
        """
        Infer the type of dependency based on task characteristics.

        Args:
            task: Task with dependency
            dependency_id: ID of dependency task

        Returns:
            Inferred dependency type
        """
        # Simple heuristics for dependency type inference
        if "output" in task.tool_args or "input" in task.tool_args:
            return DependencyType.DATA
        elif any(
            key in self._resource_keys(task.resource_requirements)
            for key in ["gpu", "memory"]
        ):
            return DependencyType.RESOURCE
        else:
            return DependencyType.ORDERING

    def _calculate_max_parallelism(
        self, tasks: List[Task], graph: Dict[str, Set[str]]
    ) -> int:
        """
        Calculate maximum theoretical parallelism for the task graph.

        Args:
            tasks: List of tasks
            graph: Dependency graph

        Returns:
            Maximum number of tasks that could run in parallel
        """
        # Create execution levels
        levels = self._create_execution_levels(tasks, graph)

        # Maximum parallelism is the size of the largest level
        return max(len(level) for level in levels) if levels else 0

    def _create_execution_levels(
        self, tasks: List[Task], graph: Dict[str, Set[str]]
    ) -> List[List[Task]]:
        """
        Create execution levels for determining parallelism.

        Args:
            tasks: List of tasks
            graph: Dependency graph

        Returns:
            List of execution levels (each level can run in parallel)
        """
        task_lookup = {task.task_id: task for task in tasks}
        levels = []
        processed = set()
        remaining_tasks = set(task.task_id for task in tasks)

        while remaining_tasks:
            # Find tasks with all dependencies satisfied
            current_level = []

            for task_id in list(remaining_tasks):
                task = task_lookup[task_id]

                # Check if all dependencies are processed
                if all(dep_id in processed for dep_id in task.dependencies):
                    current_level.append(task)

            if not current_level:
                # This should not happen if cycles are properly detected
                raise CycleDetectionError(list(remaining_tasks))

            # Remove processed tasks
            for task in current_level:
                remaining_tasks.remove(task.task_id)
                processed.add(task.task_id)

            levels.append(current_level)

        return levels

    def create_execution_batches(
        self,
        tasks: List[Task],
        max_batch_size: Optional[int] = None,
        resource_aware: bool = True,
    ) -> List[ExecutionBatch]:
        """
        Create execution batches for parallel execution.

        Args:
            tasks: List of tasks (should be topologically sorted)
            max_batch_size: Maximum tasks per batch
            resource_aware: Whether to consider resource requirements

        Returns:
            List of execution batches
        """
        if not tasks:
            return []

        # Build graph for level calculation
        graph = self._build_graph(tasks)

        # Create execution levels
        levels = self._create_execution_levels(tasks, graph)

        batches = []

        for level_idx, level_tasks in enumerate(levels):
            if max_batch_size and len(level_tasks) > max_batch_size:
                # Split large levels into smaller batches
                level_batches = self._split_level_into_batches(
                    level_tasks, max_batch_size, resource_aware
                )
                for batch_idx, batch_tasks in enumerate(level_batches):
                    batch = self._create_batch(
                        batch_tasks, f"{level_idx}_{batch_idx}", level_idx
                    )
                    batches.append(batch)
            else:
                # Create single batch for level
                batch = self._create_batch(level_tasks, str(level_idx), level_idx)
                batches.append(batch)

        self.logger.info(
            f"Created {len(batches)} execution batches from {len(levels)} dependency levels"
        )

        return batches

    def _split_level_into_batches(
        self, tasks: List[Task], max_batch_size: int, resource_aware: bool
    ) -> List[List[Task]]:
        """
        Split a level of tasks into smaller batches.

        Args:
            tasks: Tasks in the level
            max_batch_size: Maximum tasks per batch
            resource_aware: Whether to consider resources

        Returns:
            List of task batches
        """
        if not resource_aware:
            # Simple splitting by size
            batches = []
            for i in range(0, len(tasks), max_batch_size):
                batches.append(tasks[i : i + max_batch_size])
            return batches

        # Resource-aware batching using first-fit decreasing
        sorted_tasks = sorted(
            tasks,
            key=lambda t: sum(
                amount for _, amount in self._resource_items(t.resource_requirements)
            ),
            reverse=True,
        )

        batches = []

        for task in sorted_tasks:
            # Find a batch that can accommodate this task
            placed = False
            for batch in batches:
                if len(batch) < max_batch_size and self._can_add_to_batch(task, batch):
                    batch.append(task)
                    placed = True
                    break

            if not placed:
                # Create new batch
                batches.append([task])

        return batches

    def _can_add_to_batch(self, task: Task, batch: List[Task]) -> bool:
        """
        Check if a task can be added to a batch based on resource constraints.

        Args:
            task: Task to add
            batch: Current batch

        Returns:
            True if task can be added to batch
        """
        # Calculate total resource requirements
        total_resources = defaultdict(float)

        for batch_task in batch:
            for resource, amount in self._resource_items(
                batch_task.resource_requirements
            ):
                total_resources[resource] += amount

        for resource, amount in self._resource_items(task.resource_requirements):
            total_resources[resource] += amount

        # Simple resource limits (could be made configurable)
        limits = {"cpu": 8.0, "memory": 32.0, "gpu": 1.0}

        for resource, total in total_resources.items():
            if resource in limits and total > limits[resource]:
                return False

        return True

    def _resource_items(self, requirements: Any) -> List[Tuple[str, float]]:
        """Normalize resource requirements to (resource, amount) pairs."""
        items: List[Tuple[str, float]] = []
        if isinstance(requirements, dict):
            for resource, amount in requirements.items():
                items.append((self._resource_key(resource), amount))
        else:
            for req in requirements:
                resource = getattr(req, "resource_type", None)
                amount = getattr(req, "amount", 0.0)
                items.append((self._resource_key(resource), amount))
        return items

    def _resource_key(self, resource: Any) -> str:
        if hasattr(resource, "value"):
            return str(resource.value)
        return str(resource)

    def _resource_keys(self, requirements: Any) -> Set[str]:
        return {resource for resource, _ in self._resource_items(requirements)}

    def _create_batch(
        self, tasks: List[Task], batch_id: str, batch_level: int
    ) -> ExecutionBatch:
        """
        Create an execution batch from tasks.

        Args:
            tasks: Tasks for the batch
            batch_id: Batch identifier
            batch_level: Execution level

        Returns:
            Execution batch
        """
        # Calculate batch metrics
        estimated_duration = (
            max(task.estimated_duration for task in tasks) if tasks else 0.0
        )

        # Calculate total resource needs
        total_resources = defaultdict(float)
        for task in tasks:
            requirements = task.resource_requirements
            if isinstance(requirements, dict):
                for resource, amount in requirements.items():
                    total_resources[resource] = max(total_resources[resource], amount)
            else:
                for req in requirements:
                    resource = getattr(req, "resource_type", None)
                    amount = getattr(req, "amount", 0.0)
                    total_resources[resource] = max(total_resources[resource], amount)

        return ExecutionBatch(
            batch_id=batch_id,
            tasks=tasks,
            batch_level=batch_level,
            estimated_duration=estimated_duration,
            total_resource_needs=dict(total_resources),
        )

    def validate_execution_graph(self, graph: ExecutionGraph) -> List[str]:
        """
        Validate an execution graph for correctness.

        Args:
            graph: Execution graph to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check for empty graph
        if not graph.tasks:
            errors.append("Execution graph is empty")
            return errors

        # Build task ID set
        task_ids = {task.task_id for task in graph.tasks}

        # Validate dependencies
        for task in graph.tasks:
            for dep_id in task.dependencies:
                if dep_id not in task_ids:
                    errors.append(
                        f"Task {task.task_id} has invalid dependency: {dep_id}"
                    )

        # Check for cycles
        try:
            graph_dict = self._build_graph(graph.tasks)
            cycles = self._detect_cycles(graph_dict)
            if cycles:
                for cycle in cycles:
                    errors.append(f"Dependency cycle detected: {' -> '.join(cycle)}")
        except Exception as e:
            errors.append(f"Error checking for cycles: {e}")

        # Validate dependency objects
        for dep in graph.dependencies:
            if dep.from_task not in task_ids:
                errors.append(
                    f"Dependency references unknown from_task: {dep.from_task}"
                )
            if dep.to_task not in task_ids:
                errors.append(f"Dependency references unknown to_task: {dep.to_task}")

        return errors

    def optimize_graph(self, graph: ExecutionGraph) -> ExecutionGraph:
        """
        Optimize execution graph for better parallel performance.

        Args:
            graph: Original execution graph

        Returns:
            Optimized execution graph
        """
        # Create optimized copy
        optimized_tasks = []

        for task in graph.tasks:
            # Optimize task properties
            optimized_task = Task(
                task_id=task.task_id,
                name=task.name,
                tool_name=task.tool_name,
                tool_args=task.tool_args.copy(),
                dependencies=task.dependencies.copy(),
                estimated_duration=task.estimated_duration,
                priority=task.priority,
                resource_requirements=task.resource_requirements.copy(),
            )

            # Optimize resource requirements
            optimized_task.resource_requirements = self._optimize_resources(
                optimized_task.resource_requirements
            )

            optimized_tasks.append(optimized_task)

        # Create optimized graph
        optimized_graph = ExecutionGraph(
            graph_id=f"{graph.graph_id}_optimized",
            tasks=optimized_tasks,
            dependencies=graph.dependencies.copy(),
            metadata=graph.metadata.copy(),
        )

        # Recalculate metadata
        graph_dict = self._build_graph(optimized_tasks)
        optimized_graph.metadata.update(
            {
                "optimized": True,
                "max_parallelism": self._calculate_max_parallelism(
                    optimized_tasks, graph_dict
                ),
            }
        )

        return optimized_graph

    def _optimize_resources(self, resources: Dict[str, float]) -> Dict[str, float]:
        """
        Optimize resource requirements for better packing.

        Args:
            resources: Original resource requirements

        Returns:
            Optimized resource requirements
        """
        optimized = resources.copy()

        # Round up to next power of 2 for better allocation
        for resource, amount in resources.items():
            if resource in ["cpu", "memory"]:
                import math

                if amount > 0:
                    optimized[resource] = 2 ** math.ceil(math.log2(amount))

        return optimized


# Factory function
def create_dependency_resolver() -> DependencyResolver:
    """
    Create a dependency resolver instance.

    Returns:
        Configured dependency resolver
    """
    return DependencyResolver()
