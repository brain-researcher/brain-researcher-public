"""
Advanced Plan Optimization for Brain Researcher Agent (AGENT-013)

This module implements multi-objective optimization for execution plans,
focusing on cost, time, and resource efficiency with Pareto-optimal solutions.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from brain_researcher.services.agent.cost_models import (
    CloudProvider,
    CostModel,
    ResourceCostCalculator,
    create_cost_model,
)
from brain_researcher.services.agent.planning import ExecutionPlan, WorkflowStep

logger = logging.getLogger(__name__)


class OptimizationObjective(str, Enum):
    """Optimization objectives for plan optimization."""

    MINIMIZE_COST = "cost"
    MINIMIZE_TIME = "time"
    MINIMIZE_RESOURCES = "resources"
    MAXIMIZE_RELIABILITY = "reliability"
    MAXIMIZE_THROUGHPUT = "throughput"


class OptimizationStrategy(str, Enum):
    """Optimization strategies."""

    PARETO_OPTIMAL = "pareto"  # Find Pareto frontier
    WEIGHTED_SUM = "weighted"  # Weighted sum of objectives
    LEXICOGRAPHIC = "lexicographic"  # Prioritized objectives
    EPSILON_CONSTRAINT = "epsilon_constraint"  # Constraint method


@dataclass
class OptimizationConstraint:
    """Constraint specification for optimization."""

    objective: OptimizationObjective
    constraint_type: str  # "max", "min", "equal"
    value: float
    weight: float = 1.0
    priority: int = 1


@dataclass
class OptimizationPreferences:
    """User preferences for optimization."""

    primary_objective: OptimizationObjective
    secondary_objectives: List[OptimizationObjective] = field(default_factory=list)
    constraints: List[OptimizationConstraint] = field(default_factory=list)
    strategy: OptimizationStrategy = OptimizationStrategy.PARETO_OPTIMAL
    max_cost_budget: Optional[float] = None
    max_time_budget: Optional[float] = None
    target_reliability: float = 0.95
    preferred_cloud_provider: Optional[CloudProvider] = None


@dataclass
class PlanMetrics:
    """Metrics for an execution plan."""

    total_cost: float
    total_time: float
    total_cpu_hours: float
    total_memory_gb_hours: float
    total_storage_gb: float
    reliability_score: float
    complexity_score: float
    parallel_efficiency: float


@dataclass
class OptimizedPlan:
    """An optimized execution plan with metrics."""

    plan_id: str
    original_plan: ExecutionPlan
    optimized_steps: List[WorkflowStep]
    metrics: PlanMetrics
    optimization_score: float
    pareto_rank: int = 0
    dominated_by: List[str] = field(default_factory=list)
    dominates: List[str] = field(default_factory=list)
    trade_off_analysis: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParetoSolution:
    """Pareto-optimal solution."""

    solution_id: str
    plan: OptimizedPlan
    objectives: Dict[OptimizationObjective, float]
    rank: int
    crowding_distance: float = 0.0
    is_extreme_point: bool = False


class TimeEstimator:
    """Estimates execution time for workflow steps."""

    def __init__(self):
        """Initialize time estimator."""
        # Historical data for time estimation (would be learned from actual executions)
        self.tool_base_times = {
            "fmriprep": 3600.0,  # 1 hour base time
            "fsl_feat": 900.0,  # 15 minutes
            "fsl_flirt": 300.0,  # 5 minutes
            "connectivity_analysis": 600.0,  # 10 minutes
            "glm_analysis": 1200.0,  # 20 minutes
            "meta_analysis": 1800.0,  # 30 minutes
            "default": 300.0,  # 5 minutes default
        }

        # Complexity multipliers based on data size, parameters, etc.
        self.complexity_factors = {
            "data_size_small": 1.0,
            "data_size_medium": 2.0,
            "data_size_large": 4.0,
            "high_resolution": 1.5,
            "multi_session": 2.0,
            "group_analysis": 3.0,
        }

    def estimate_step_time(self, step: WorkflowStep) -> float:
        """
        Estimate execution time for a workflow step.

        Args:
            step: Workflow step to estimate

        Returns:
            Estimated time in seconds
        """
        base_time = self.tool_base_times.get(
            step.tool_name, self.tool_base_times["default"]
        )

        # Apply complexity factors based on tool arguments
        complexity_multiplier = 1.0

        args = step.tool_args
        if "dataset_size" in args:
            size = args["dataset_size"]
            if size == "large":
                complexity_multiplier *= self.complexity_factors["data_size_large"]
            elif size == "medium":
                complexity_multiplier *= self.complexity_factors["data_size_medium"]

        if args.get("high_resolution", False):
            complexity_multiplier *= self.complexity_factors["high_resolution"]

        if args.get("n_subjects", 1) > 50:
            complexity_multiplier *= self.complexity_factors["group_analysis"]

        estimated_time = base_time * complexity_multiplier

        # Add some randomness for realistic estimation
        import random

        variation = random.uniform(0.8, 1.2)  # ±20% variation

        return estimated_time * variation

    def estimate_parallel_time(self, steps: List[WorkflowStep]) -> float:
        """
        Estimate total time for parallel execution.

        Args:
            steps: List of workflow steps

        Returns:
            Estimated parallel execution time
        """
        # Build dependency graph and calculate critical path
        from brain_researcher.services.agent.dependency_resolver import (
            DependencyResolver,
            Task,
        )

        resolver = DependencyResolver()

        # Convert steps to tasks for dependency analysis
        tasks = []
        for step in steps:
            task = Task(
                task_id=step.step_id,
                name=step.description,
                tool_name=step.tool_name,
                tool_args=step.tool_args,
                dependencies=step.dependencies,
                estimated_duration=self.estimate_step_time(step),
            )
            tasks.append(task)

        try:
            batches = resolver.create_execution_batches(tasks)
            total_time = sum(batch.estimated_duration for batch in batches)
            return total_time
        except Exception:
            # Fallback to sequential time estimation
            return sum(self.estimate_step_time(step) for step in steps)


class ParetoOptimizer:
    """Pareto frontier optimization for multi-objective problems."""

    def __init__(self):
        """Initialize Pareto optimizer."""
        pass

    def find_pareto_frontier(
        self, solutions: List[OptimizedPlan], objectives: List[OptimizationObjective]
    ) -> List[ParetoSolution]:
        """
        Find Pareto-optimal solutions using NSGA-II-like approach.

        Args:
            solutions: List of candidate solutions
            objectives: Objectives to optimize

        Returns:
            Pareto frontier solutions
        """
        if not solutions:
            return []

        # Convert solutions to Pareto solutions
        pareto_solutions = []
        for i, solution in enumerate(solutions):
            objectives_dict = self._extract_objectives(solution, objectives)
            pareto_sol = ParetoSolution(
                solution_id=f"pareto_{i}",
                plan=solution,
                objectives=objectives_dict,
                rank=0,
            )
            pareto_solutions.append(pareto_sol)

        # Fast non-dominated sorting
        fronts = self._fast_non_dominated_sort(pareto_solutions, objectives)

        # Calculate crowding distance for each front
        for front in fronts:
            self._calculate_crowding_distance(front, objectives)

        # Return first front (Pareto optimal solutions)
        if fronts:
            return fronts[0]
        else:
            return []

    def _extract_objectives(
        self, solution: OptimizedPlan, objectives: List[OptimizationObjective]
    ) -> Dict[OptimizationObjective, float]:
        """Extract objective values from a solution."""
        objectives_dict = {}

        for obj in objectives:
            if obj == OptimizationObjective.MINIMIZE_COST:
                objectives_dict[obj] = solution.metrics.total_cost
            elif obj == OptimizationObjective.MINIMIZE_TIME:
                objectives_dict[obj] = solution.metrics.total_time
            elif obj == OptimizationObjective.MINIMIZE_RESOURCES:
                # Combine CPU, memory, and storage into resource score
                resource_score = (
                    solution.metrics.total_cpu_hours
                    + solution.metrics.total_memory_gb_hours / 10  # Scale memory
                    + solution.metrics.total_storage_gb / 100  # Scale storage
                )
                objectives_dict[obj] = resource_score
            elif obj == OptimizationObjective.MAXIMIZE_RELIABILITY:
                objectives_dict[obj] = (
                    -solution.metrics.reliability_score
                )  # Negative for minimization
            elif obj == OptimizationObjective.MAXIMIZE_THROUGHPUT:
                objectives_dict[obj] = (
                    -solution.metrics.parallel_efficiency
                )  # Negative for minimization

        return objectives_dict

    def _fast_non_dominated_sort(
        self, solutions: List[ParetoSolution], objectives: List[OptimizationObjective]
    ) -> List[List[ParetoSolution]]:
        """Fast non-dominated sorting algorithm."""
        fronts = []

        # Initialize domination data
        for sol1 in solutions:
            sol1.dominated_by = []
            sol1.dominates = []

            for sol2 in solutions:
                if sol1 == sol2:
                    continue

                if self._dominates(sol1, sol2, objectives):
                    sol1.dominates.append(sol2.solution_id)
                elif self._dominates(sol2, sol1, objectives):
                    sol1.dominated_by.append(sol2.solution_id)

        # Find first front
        first_front = []
        for sol in solutions:
            if len(sol.dominated_by) == 0:
                sol.rank = 0
                first_front.append(sol)

        fronts.append(first_front)

        # Find subsequent fronts
        front_idx = 0
        while len(fronts[front_idx]) > 0:
            next_front = []

            for sol1 in fronts[front_idx]:
                for dominated_id in sol1.dominates:
                    # Find the dominated solution
                    dominated_sol = next(
                        s for s in solutions if s.solution_id == dominated_id
                    )
                    dominated_sol.dominated_by.remove(sol1.solution_id)

                    if len(dominated_sol.dominated_by) == 0:
                        dominated_sol.rank = front_idx + 1
                        next_front.append(dominated_sol)

            fronts.append(next_front)
            front_idx += 1

        # Remove empty last front
        if not fronts[-1]:
            fronts.pop()

        return fronts

    def _dominates(
        self,
        sol1: ParetoSolution,
        sol2: ParetoSolution,
        objectives: List[OptimizationObjective],
    ) -> bool:
        """Check if solution 1 dominates solution 2."""
        at_least_one_better = False

        for obj in objectives:
            val1 = sol1.objectives.get(obj, float("inf"))
            val2 = sol2.objectives.get(obj, float("inf"))

            if val1 > val2:  # sol1 is worse in this objective
                return False
            elif val1 < val2:  # sol1 is better in this objective
                at_least_one_better = True

        return at_least_one_better

    def _calculate_crowding_distance(
        self, front: List[ParetoSolution], objectives: List[OptimizationObjective]
    ):
        """Calculate crowding distance for solutions in a front."""
        if len(front) <= 2:
            for sol in front:
                sol.crowding_distance = float("inf")
            return

        # Initialize distances
        for sol in front:
            sol.crowding_distance = 0.0

        # Calculate distance for each objective
        for obj in objectives:
            # Sort by objective value
            front.sort(key=lambda s: s.objectives.get(obj, float("inf")))

            # Set boundary points to infinite distance
            front[0].crowding_distance = float("inf")
            front[-1].crowding_distance = float("inf")
            front[0].is_extreme_point = True
            front[-1].is_extreme_point = True

            # Calculate normalized distance for interior points
            obj_min = front[0].objectives.get(obj, 0.0)
            obj_max = front[-1].objectives.get(obj, 0.0)
            obj_range = obj_max - obj_min

            if obj_range > 0:
                for i in range(1, len(front) - 1):
                    distance = (
                        front[i + 1].objectives.get(obj, 0.0)
                        - front[i - 1].objectives.get(obj, 0.0)
                    ) / obj_range
                    front[i].crowding_distance += distance


class AdvancedPlanOptimizer:
    """
    Advanced execution plan optimizer with multi-objective optimization.

    Features:
    - Cost optimization with cloud pricing models
    - Time optimization with parallelization awareness
    - Resource balancing across compute/memory/storage
    - Pareto-optimal solution generation
    - Trade-off analysis and visualization
    - >20% cost reduction target for typical workflows
    """

    def __init__(
        self,
        cost_model: Optional[CostModel] = None,
        cloud_provider: CloudProvider = CloudProvider.AWS,
    ):
        """
        Initialize advanced plan optimizer.

        Args:
            cost_model: Cost model for optimization
            cloud_provider: Preferred cloud provider
        """
        self.cost_model = cost_model or create_cost_model(cloud_provider)
        self.cost_calculator = ResourceCostCalculator(self.cost_model)
        self.time_estimator = TimeEstimator()
        self.pareto_optimizer = ParetoOptimizer()

        # Optimization parameters
        self.max_iterations = 100
        self.convergence_threshold = 0.001
        self.population_size = 50

        logger.info(
            f"Plan optimizer initialized with {cloud_provider.value} cost model"
        )

    def optimize(
        self,
        plan: ExecutionPlan,
        preferences: OptimizationPreferences,
        constraints: Optional[List[OptimizationConstraint]] = None,
    ) -> List[OptimizedPlan]:
        """
        Optimize execution plan based on preferences and constraints.

        Args:
            plan: Original execution plan
            preferences: Optimization preferences
            constraints: Additional constraints

        Returns:
            List of optimized plans (Pareto frontier if applicable)
        """
        logger.info(f"Optimizing plan {plan.plan_id} with {len(plan.steps)} steps")

        start_time = time.time()

        # Generate candidate solutions
        candidates = self._generate_candidate_solutions(plan, preferences)

        # Evaluate each candidate
        evaluated_candidates = []
        for candidate in candidates:
            metrics = self._evaluate_plan_metrics(candidate)
            optimization_score = self._calculate_optimization_score(
                metrics, preferences
            )

            optimized_plan = OptimizedPlan(
                plan_id=f"{plan.plan_id}_opt_{len(evaluated_candidates)}",
                original_plan=plan,
                optimized_steps=candidate,
                metrics=metrics,
                optimization_score=optimization_score,
            )
            evaluated_candidates.append(optimized_plan)

        # Apply optimization strategy
        if preferences.strategy == OptimizationStrategy.PARETO_OPTIMAL:
            optimized_plans = self._pareto_optimization(
                evaluated_candidates, preferences
            )
        elif preferences.strategy == OptimizationStrategy.WEIGHTED_SUM:
            optimized_plans = self._weighted_sum_optimization(
                evaluated_candidates, preferences
            )
        else:
            # Default to single best solution
            optimized_plans = [
                max(evaluated_candidates, key=lambda p: p.optimization_score)
            ]

        # Generate trade-off analysis
        for plan in optimized_plans:
            plan.trade_off_analysis = self._generate_trade_off_analysis(
                plan, plan.original_plan
            )

        optimization_time = time.time() - start_time

        logger.info(
            f"Plan optimization completed in {optimization_time:.2f}s, "
            f"generated {len(optimized_plans)} solutions"
        )

        return optimized_plans

    def _generate_candidate_solutions(
        self, plan: ExecutionPlan, preferences: OptimizationPreferences
    ) -> List[List[WorkflowStep]]:
        """
        Generate candidate optimized solutions.

        Args:
            plan: Original execution plan
            preferences: Optimization preferences

        Returns:
            List of candidate step sequences
        """
        candidates = []

        # Original plan as baseline
        candidates.append(plan.steps.copy())

        # Tool substitution optimization
        substituted_plan = self._optimize_tool_substitution(plan.steps)
        if substituted_plan != plan.steps:
            candidates.append(substituted_plan)

        # Parameter optimization
        param_optimized_plan = self._optimize_parameters(plan.steps)
        if param_optimized_plan != plan.steps:
            candidates.append(param_optimized_plan)

        # Parallelization optimization
        parallel_optimized_plan = self._optimize_parallelization(plan.steps)
        if parallel_optimized_plan != plan.steps:
            candidates.append(parallel_optimized_plan)

        # Resource allocation optimization
        resource_optimized_plan = self._optimize_resource_allocation(plan.steps)
        if resource_optimized_plan != plan.steps:
            candidates.append(resource_optimized_plan)

        # Instance type optimization
        instance_optimized_plan = self._optimize_instance_types(plan.steps)
        if instance_optimized_plan != plan.steps:
            candidates.append(instance_optimized_plan)

        # Hybrid optimizations (combinations)
        hybrid_plan = self._combine_optimizations(
            [substituted_plan, param_optimized_plan, parallel_optimized_plan]
        )
        if hybrid_plan and hybrid_plan not in candidates:
            candidates.append(hybrid_plan)

        return candidates

    def _optimize_tool_substitution(
        self, steps: List[WorkflowStep]
    ) -> List[WorkflowStep]:
        """Optimize by substituting tools with more efficient alternatives."""
        optimized_steps = []

        tool_substitutions = {
            "fsl_feat": "afni_3ddeconvolve",  # Potentially faster alternative
            "fsl_flirt": "ants_registration",  # More accurate but slower
            "freesurfer_recon": "fastsurfer",  # Faster deep learning version
        }

        for step in steps:
            if step.tool_name in tool_substitutions:
                # Create substituted step
                new_step = WorkflowStep(
                    step_id=step.step_id,
                    step_number=step.step_number,
                    description=step.description.replace(
                        step.tool_name, tool_substitutions[step.tool_name]
                    ),
                    tool_name=tool_substitutions[step.tool_name],
                    tool_args=step.tool_args.copy(),
                    dependencies=step.dependencies.copy(),
                    expected_output=step.expected_output,
                    estimated_time_seconds=step.estimated_time_seconds
                    * 0.8,  # Assume 20% faster
                    resource_requirements=step.resource_requirements.copy(),
                )
                optimized_steps.append(new_step)
            else:
                optimized_steps.append(step)

        return optimized_steps

    def _optimize_parameters(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        """Optimize tool parameters for better performance."""
        optimized_steps = []

        for step in steps:
            new_step = WorkflowStep(
                step_id=step.step_id,
                step_number=step.step_number,
                description=step.description,
                tool_name=step.tool_name,
                tool_args=step.tool_args.copy(),
                dependencies=step.dependencies.copy(),
                expected_output=step.expected_output,
                estimated_time_seconds=step.estimated_time_seconds,
                resource_requirements=step.resource_requirements.copy(),
            )

            # Optimize parameters based on tool type
            if "fmriprep" in step.tool_name.lower():
                # Optimize fMRIPrep parameters
                new_step.tool_args.update(
                    {
                        "nprocs": min(8, new_step.tool_args.get("nprocs", 4)),
                        "mem_mb": 16000,  # Optimize memory usage
                        "use_syn_sdc": False,  # Disable slow distortion correction
                    }
                )
                new_step.estimated_time_seconds *= 0.7  # 30% faster with optimizations

            elif "glm" in step.tool_name.lower():
                # Optimize GLM parameters
                new_step.tool_args.update(
                    {
                        "high_pass_filter": 128,  # Standard high-pass filter
                        "motion_outliers": True,  # Enable motion outlier detection
                    }
                )

            optimized_steps.append(new_step)

        return optimized_steps

    def _optimize_parallelization(
        self, steps: List[WorkflowStep]
    ) -> List[WorkflowStep]:
        """Optimize parallelization of workflow steps."""
        # Identify steps that can be parallelized
        parallel_candidates = []
        sequential_steps = []

        for step in steps:
            if not step.dependencies and step.tool_name.lower() not in [
                "preprocessing",
                "fmriprep",
            ]:
                # Independent steps can potentially be parallelized
                parallel_candidates.append(step)
            else:
                sequential_steps.append(step)

        # Create optimized version with better parallelization
        optimized_steps = []

        # Add sequential steps first
        for step in sequential_steps:
            optimized_steps.append(step)

        # Add parallel candidates with optimized resource allocation
        for step in parallel_candidates:
            new_step = WorkflowStep(
                step_id=step.step_id,
                step_number=step.step_number,
                description=step.description,
                tool_name=step.tool_name,
                tool_args=step.tool_args.copy(),
                dependencies=step.dependencies.copy(),
                expected_output=step.expected_output,
                estimated_time_seconds=step.estimated_time_seconds,
                resource_requirements=step.resource_requirements.copy(),
            )

            # Optimize resource allocation for parallel execution
            if "cpu" in new_step.resource_requirements:
                # Use fewer CPUs per task to allow more parallel tasks
                new_step.resource_requirements["cpu"] = max(
                    1.0, new_step.resource_requirements["cpu"] * 0.6
                )

            optimized_steps.append(new_step)

        return optimized_steps

    def _optimize_resource_allocation(
        self, steps: List[WorkflowStep]
    ) -> List[WorkflowStep]:
        """Optimize resource allocation for steps."""
        optimized_steps = []

        for step in steps:
            new_step = WorkflowStep(
                step_id=step.step_id,
                step_number=step.step_number,
                description=step.description,
                tool_name=step.tool_name,
                tool_args=step.tool_args.copy(),
                dependencies=step.dependencies.copy(),
                expected_output=step.expected_output,
                estimated_time_seconds=step.estimated_time_seconds,
                resource_requirements=step.resource_requirements.copy(),
            )

            # Optimize resource allocation based on workload characteristics
            tool_name_lower = step.tool_name.lower()

            if "connectivity" in tool_name_lower:
                # Connectivity analysis is memory-intensive
                new_step.resource_requirements.update(
                    {
                        "memory": new_step.resource_requirements.get("memory", 4.0)
                        * 1.5,
                        "cpu": max(2.0, new_step.resource_requirements.get("cpu", 1.0)),
                    }
                )
            elif "glm" in tool_name_lower:
                # GLM analysis benefits from more CPU cores
                new_step.resource_requirements.update(
                    {
                        "cpu": min(
                            8.0, new_step.resource_requirements.get("cpu", 2.0) * 2
                        ),
                        "memory": new_step.resource_requirements.get("memory", 8.0),
                    }
                )

            optimized_steps.append(new_step)

        return optimized_steps

    def _optimize_instance_types(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        """Optimize cloud instance types for steps."""
        optimized_steps = []

        for step in steps:
            new_step = WorkflowStep(
                step_id=step.step_id,
                step_number=step.step_number,
                description=step.description,
                tool_name=step.tool_name,
                tool_args=step.tool_args.copy(),
                dependencies=step.dependencies.copy(),
                expected_output=step.expected_output,
                estimated_time_seconds=step.estimated_time_seconds,
                resource_requirements=step.resource_requirements.copy(),
            )

            # Add instance type recommendations based on workload
            cpu_req = new_step.resource_requirements.get("cpu", 1.0)
            memory_req = new_step.resource_requirements.get("memory", 4.0)

            if cpu_req >= 8.0:
                new_step.tool_args["preferred_instance_type"] = "compute_optimized"
            elif memory_req >= 16.0:
                new_step.tool_args["preferred_instance_type"] = "memory_optimized"
            else:
                new_step.tool_args["preferred_instance_type"] = "general_purpose"

            # Enable spot instances for non-critical tasks
            if step.tool_name.lower() not in ["preprocessing", "critical_analysis"]:
                new_step.tool_args["use_spot_instances"] = True
                # Spot instances can reduce cost by 50-90%
                new_step.resource_requirements["cost_multiplier"] = 0.3

            optimized_steps.append(new_step)

        return optimized_steps

    def _combine_optimizations(
        self, plans: List[List[WorkflowStep]]
    ) -> Optional[List[WorkflowStep]]:
        """Combine multiple optimization strategies."""
        if not plans:
            return None

        base_plan = plans[0]
        combined_steps = []

        for i, base_step in enumerate(base_plan):
            # Start with base step
            best_step = base_step
            best_score = self._score_step(best_step)

            # Check alternatives from other plans
            for plan in plans[1:]:
                if i < len(plan):
                    alternative_step = plan[i]
                    alt_score = self._score_step(alternative_step)

                    if alt_score > best_score:
                        best_step = alternative_step
                        best_score = alt_score

            combined_steps.append(best_step)

        return combined_steps

    def _score_step(self, step: WorkflowStep) -> float:
        """Score a workflow step for optimization selection."""
        # Simple scoring based on estimated efficiency
        time_score = 1.0 / max(
            0.1, step.estimated_time_seconds / 3600
        )  # Prefer faster steps

        cpu_req = step.resource_requirements.get("cpu", 1.0)
        memory_req = step.resource_requirements.get("memory", 4.0)
        resource_score = 1.0 / (cpu_req + memory_req / 4)  # Prefer lower resource usage

        cost_multiplier = step.resource_requirements.get("cost_multiplier", 1.0)
        cost_score = 1.0 / cost_multiplier  # Prefer lower cost multipliers

        return (time_score + resource_score + cost_score) / 3

    def _evaluate_plan_metrics(self, steps: List[WorkflowStep]) -> PlanMetrics:
        """
        Evaluate comprehensive metrics for a plan.

        Args:
            steps: Workflow steps

        Returns:
            Plan metrics
        """
        # Calculate cost metrics
        total_cost = self.cost_calculator.calculate_total_cost(steps)

        # Calculate time metrics
        total_time = self.time_estimator.estimate_parallel_time(steps)

        # Calculate resource metrics
        total_cpu_hours = sum(
            step.resource_requirements.get("cpu", 1.0)
            * step.estimated_time_seconds
            / 3600
            for step in steps
        )

        total_memory_gb_hours = sum(
            step.resource_requirements.get("memory", 4.0)
            * step.estimated_time_seconds
            / 3600
            for step in steps
        )

        total_storage_gb = sum(
            step.resource_requirements.get("storage", 10.0) for step in steps
        )

        # Calculate reliability score
        reliability_score = self._calculate_reliability_score(steps)

        # Calculate complexity score
        complexity_score = len(steps) + sum(len(step.dependencies) for step in steps)

        # Calculate parallel efficiency
        sequential_time = sum(step.estimated_time_seconds for step in steps)
        parallel_efficiency = sequential_time / max(total_time, 1.0)

        return PlanMetrics(
            total_cost=total_cost,
            total_time=total_time,
            total_cpu_hours=total_cpu_hours,
            total_memory_gb_hours=total_memory_gb_hours,
            total_storage_gb=total_storage_gb,
            reliability_score=reliability_score,
            complexity_score=complexity_score,
            parallel_efficiency=parallel_efficiency,
        )

    def _calculate_reliability_score(self, steps: List[WorkflowStep]) -> float:
        """Calculate reliability score for a plan."""
        # Base reliability for each tool type
        tool_reliability = {
            "fmriprep": 0.95,
            "fsl": 0.98,
            "afni": 0.96,
            "ants": 0.94,
            "freesurfer": 0.92,
            "default": 0.90,
        }

        total_reliability = 1.0
        for step in steps:
            tool_name_lower = step.tool_name.lower()

            # Find matching tool reliability
            step_reliability = tool_reliability["default"]
            for tool, reliability in tool_reliability.items():
                if tool in tool_name_lower:
                    step_reliability = reliability
                    break

            # Adjust for spot instances (lower reliability)
            if step.tool_args.get("use_spot_instances", False):
                step_reliability *= 0.95

            total_reliability *= step_reliability

        return total_reliability

    def _calculate_optimization_score(
        self, metrics: PlanMetrics, preferences: OptimizationPreferences
    ) -> float:
        """
        Calculate optimization score based on preferences.

        Args:
            metrics: Plan metrics
            preferences: Optimization preferences

        Returns:
            Optimization score (higher is better)
        """
        score = 0.0

        # Weight based on primary objective
        if preferences.primary_objective == OptimizationObjective.MINIMIZE_COST:
            score += 1000.0 / max(1.0, metrics.total_cost)
        elif preferences.primary_objective == OptimizationObjective.MINIMIZE_TIME:
            score += 10000.0 / max(1.0, metrics.total_time)
        elif preferences.primary_objective == OptimizationObjective.MINIMIZE_RESOURCES:
            resource_usage = (
                metrics.total_cpu_hours + metrics.total_memory_gb_hours / 10
            )
            score += 1000.0 / max(1.0, resource_usage)
        elif (
            preferences.primary_objective == OptimizationObjective.MAXIMIZE_RELIABILITY
        ):
            score += metrics.reliability_score * 1000
        elif preferences.primary_objective == OptimizationObjective.MAXIMIZE_THROUGHPUT:
            score += metrics.parallel_efficiency * 1000

        # Add secondary objectives with lower weight
        for secondary_obj in preferences.secondary_objectives:
            if secondary_obj == OptimizationObjective.MINIMIZE_COST:
                score += 200.0 / max(1.0, metrics.total_cost)
            elif secondary_obj == OptimizationObjective.MINIMIZE_TIME:
                score += 2000.0 / max(1.0, metrics.total_time)
            elif secondary_obj == OptimizationObjective.MAXIMIZE_RELIABILITY:
                score += metrics.reliability_score * 200

        # Apply constraint penalties
        for constraint in preferences.constraints:
            penalty = self._evaluate_constraint_penalty(metrics, constraint)
            score -= penalty

        return score

    def _evaluate_constraint_penalty(
        self, metrics: PlanMetrics, constraint: OptimizationConstraint
    ) -> float:
        """Evaluate penalty for constraint violation."""
        value = 0.0

        if constraint.objective == OptimizationObjective.MINIMIZE_COST:
            value = metrics.total_cost
        elif constraint.objective == OptimizationObjective.MINIMIZE_TIME:
            value = metrics.total_time
        elif constraint.objective == OptimizationObjective.MAXIMIZE_RELIABILITY:
            value = metrics.reliability_score

        penalty = 0.0
        if constraint.constraint_type == "max" and value > constraint.value:
            penalty = (value - constraint.value) * constraint.weight * 100
        elif constraint.constraint_type == "min" and value < constraint.value:
            penalty = (constraint.value - value) * constraint.weight * 100

        return penalty

    def _pareto_optimization(
        self, candidates: List[OptimizedPlan], preferences: OptimizationPreferences
    ) -> List[OptimizedPlan]:
        """Perform Pareto optimization."""
        objectives = [preferences.primary_objective] + preferences.secondary_objectives

        pareto_solutions = self.pareto_optimizer.find_pareto_frontier(
            candidates, objectives
        )

        # Convert back to OptimizedPlan format
        optimized_plans = []
        for pareto_sol in pareto_solutions:
            pareto_sol.plan.pareto_rank = pareto_sol.rank
            optimized_plans.append(pareto_sol.plan)

        return optimized_plans

    def _weighted_sum_optimization(
        self, candidates: List[OptimizedPlan], preferences: OptimizationPreferences
    ) -> List[OptimizedPlan]:
        """Perform weighted sum optimization."""
        # Return top candidate based on optimization score
        best_candidate = max(candidates, key=lambda p: p.optimization_score)
        return [best_candidate]

    def _generate_trade_off_analysis(
        self, optimized_plan: OptimizedPlan, original_plan: ExecutionPlan
    ) -> Dict[str, Any]:
        """Generate trade-off analysis comparing optimized vs original plan."""
        original_metrics = self._evaluate_plan_metrics(original_plan.steps)

        cost_reduction = (
            (original_metrics.total_cost - optimized_plan.metrics.total_cost)
            / original_metrics.total_cost
            * 100
        )

        time_change = (
            (optimized_plan.metrics.total_time - original_metrics.total_time)
            / original_metrics.total_time
            * 100
        )

        reliability_change = (
            optimized_plan.metrics.reliability_score
            - original_metrics.reliability_score
        )

        return {
            "cost_reduction_percent": cost_reduction,
            "time_change_percent": time_change,
            "reliability_change": reliability_change,
            "optimization_achieved": cost_reduction
            > 20.0,  # Target >20% cost reduction
            "trade_offs": {
                "cost_vs_time": f"Cost reduced by {cost_reduction:.1f}%, time {'increased' if time_change > 0 else 'decreased'} by {abs(time_change):.1f}%",
                "cost_vs_reliability": f"Cost reduced by {cost_reduction:.1f}%, reliability {'improved' if reliability_change > 0 else 'decreased'} by {abs(reliability_change):.3f}",
                "efficiency_gain": f"Parallel efficiency: {optimized_plan.metrics.parallel_efficiency:.2f}x",
            },
            "recommendations": self._generate_recommendations(
                optimized_plan, original_metrics
            ),
        }

    def _generate_recommendations(
        self, optimized_plan: OptimizedPlan, original_metrics: PlanMetrics
    ) -> List[str]:
        """Generate optimization recommendations."""
        recommendations = []

        if optimized_plan.metrics.total_cost < original_metrics.total_cost * 0.8:
            recommendations.append(
                "Significant cost reduction achieved through optimization"
            )

        if optimized_plan.metrics.parallel_efficiency > 2.0:
            recommendations.append(
                "High parallel efficiency - consider increasing parallelism"
            )

        if optimized_plan.metrics.reliability_score < 0.9:
            recommendations.append(
                "Consider reliability improvements with backup strategies"
            )

        spot_instance_steps = sum(
            1
            for step in optimized_plan.optimized_steps
            if step.tool_args.get("use_spot_instances", False)
        )
        if spot_instance_steps > 0:
            recommendations.append(
                f"Using spot instances for {spot_instance_steps} steps - monitor for interruptions"
            )

        return recommendations


# Factory function
def create_plan_optimizer(
    cost_model: Optional[CostModel] = None,
    cloud_provider: CloudProvider = CloudProvider.AWS,
) -> AdvancedPlanOptimizer:
    """
    Create an advanced plan optimizer.

    Args:
        cost_model: Optional cost model
        cloud_provider: Cloud provider for cost optimization

    Returns:
        Configured plan optimizer
    """
    return AdvancedPlanOptimizer(cost_model=cost_model, cloud_provider=cloud_provider)
