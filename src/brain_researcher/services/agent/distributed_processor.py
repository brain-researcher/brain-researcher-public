"""Distributed Processing Framework with Ray and Dask

Implements distributed execution across multiple nodes for large-scale processing.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Dynamic imports for optional dependencies
try:
    import ray

    RAY_AVAILABLE = True
except ImportError:
    RAY_AVAILABLE = False
    logger.warning("Ray not installed. Distributed processing with Ray unavailable.")

try:
    import dask
    import dask.distributed
    from dask.distributed import Client, as_completed

    DASK_AVAILABLE = True
except ImportError:
    DASK_AVAILABLE = False
    logger.warning("Dask not installed. Distributed processing with Dask unavailable.")


class DistributedBackend(Enum):
    """Available distributed processing backends."""

    RAY = "ray"
    DASK = "dask"
    LOCAL = "local"  # Fallback


@dataclass
class DistributedConfig:
    """Configuration for distributed processing."""

    backend: DistributedBackend = DistributedBackend.LOCAL
    num_workers: int = 4
    memory_per_worker: str = "4GB"
    dashboard_port: Optional[int] = 8787
    ray_address: Optional[str] = None  # For connecting to existing Ray cluster
    dask_scheduler: Optional[str] = None  # For connecting to existing Dask scheduler


class DistributedProcessor:
    """Manages distributed processing across multiple nodes."""

    def __init__(self, config: Optional[DistributedConfig] = None):
        """Initialize distributed processor.

        Args:
            config: Distributed processing configuration
        """
        self.config = config or DistributedConfig()
        self.backend = self._select_backend()
        self.client = None
        self.workers = []

        # Metrics
        self.metrics = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "total_time": 0.0,
            "worker_utilization": {},
        }

    def _select_backend(self) -> DistributedBackend:
        """Select appropriate backend based on availability."""
        if self.config.backend == DistributedBackend.RAY and RAY_AVAILABLE:
            return DistributedBackend.RAY
        elif self.config.backend == DistributedBackend.DASK and DASK_AVAILABLE:
            return DistributedBackend.DASK
        else:
            logger.info("Using local backend (distributed backends not available)")
            return DistributedBackend.LOCAL

    async def initialize(self):
        """Initialize the distributed processing backend."""
        if self.backend == DistributedBackend.RAY:
            await self._initialize_ray()
        elif self.backend == DistributedBackend.DASK:
            await self._initialize_dask()
        else:
            logger.info("Using local processing (no distributed backend)")

    async def _initialize_ray(self):
        """Initialize Ray cluster."""
        if not RAY_AVAILABLE:
            raise RuntimeError("Ray is not installed")

        if self.config.ray_address:
            # Connect to existing cluster
            ray.init(address=self.config.ray_address)
            logger.info(f"Connected to Ray cluster at {self.config.ray_address}")
        else:
            # Start local cluster
            ray.init(
                num_cpus=self.config.num_workers,
                dashboard_port=self.config.dashboard_port,
                ignore_reinit_error=True,
            )
            logger.info(
                f"Started local Ray cluster with {self.config.num_workers} workers"
            )

        # Get cluster resources
        resources = ray.cluster_resources()
        logger.info(f"Ray cluster resources: {resources}")

    async def _initialize_dask(self):
        """Initialize Dask cluster."""
        if not DASK_AVAILABLE:
            raise RuntimeError("Dask is not installed")

        if self.config.dask_scheduler:
            # Connect to existing scheduler
            self.client = Client(self.config.dask_scheduler)
            logger.info(f"Connected to Dask scheduler at {self.config.dask_scheduler}")
        else:
            # Start local cluster
            from dask.distributed import LocalCluster

            cluster = LocalCluster(
                n_workers=self.config.num_workers,
                threads_per_worker=2,
                memory_limit=self.config.memory_per_worker,
                dashboard_address=(
                    f":{self.config.dashboard_port}"
                    if self.config.dashboard_port
                    else None
                ),
            )
            self.client = Client(cluster)
            logger.info(
                f"Started local Dask cluster with {self.config.num_workers} workers"
            )

        # Get cluster info
        info = self.client.scheduler_info()
        logger.info(f"Dask cluster workers: {len(info['workers'])}")

    async def execute_distributed(
        self, func: Callable, inputs: List[Any], batch_size: Optional[int] = None
    ) -> List[Any]:
        """Execute function across distributed workers.

        Args:
            func: Function to execute
            inputs: List of inputs to process
            batch_size: Optional batch size for grouping

        Returns:
            List of results
        """
        start_time = time.time()
        self.metrics["total_tasks"] += len(inputs)

        try:
            if self.backend == DistributedBackend.RAY:
                results = await self._execute_ray(func, inputs, batch_size)
            elif self.backend == DistributedBackend.DASK:
                results = await self._execute_dask(func, inputs, batch_size)
            else:
                results = await self._execute_local(func, inputs)

            self.metrics["completed_tasks"] += len(results)

        except Exception as e:
            logger.error(f"Distributed execution failed: {e}")
            self.metrics["failed_tasks"] += len(inputs)
            raise

        finally:
            self.metrics["total_time"] += time.time() - start_time

        return results

    async def _execute_ray(
        self, func: Callable, inputs: List[Any], batch_size: Optional[int]
    ) -> List[Any]:
        """Execute using Ray."""
        if not RAY_AVAILABLE:
            raise RuntimeError("Ray is not available")

        # Create Ray remote function
        @ray.remote
        def ray_func(input_data):
            return func(input_data)

        # Submit tasks
        if batch_size:
            # Process in batches
            futures = []
            for i in range(0, len(inputs), batch_size):
                batch = inputs[i : i + batch_size]
                future = ray_func.remote(batch)
                futures.append(future)

            # Wait for results
            results = ray.get(futures)

            # Flatten batch results
            flattened = []
            for batch_result in results:
                if isinstance(batch_result, list):
                    flattened.extend(batch_result)
                else:
                    flattened.append(batch_result)

            return flattened
        else:
            # Process individually
            futures = [ray_func.remote(inp) for inp in inputs]
            return ray.get(futures)

    async def _execute_dask(
        self, func: Callable, inputs: List[Any], batch_size: Optional[int]
    ) -> List[Any]:
        """Execute using Dask."""
        if not DASK_AVAILABLE or not self.client:
            raise RuntimeError("Dask is not available")

        # Submit tasks
        if batch_size:
            # Process in batches
            futures = []
            for i in range(0, len(inputs), batch_size):
                batch = inputs[i : i + batch_size]
                future = self.client.submit(func, batch)
                futures.append(future)

            # Wait for results
            results = []
            for future in as_completed(futures):
                batch_result = future.result()
                if isinstance(batch_result, list):
                    results.extend(batch_result)
                else:
                    results.append(batch_result)

            return results
        else:
            # Process individually
            futures = [self.client.submit(func, inp) for inp in inputs]
            return self.client.gather(futures)

    async def _execute_local(self, func: Callable, inputs: List[Any]) -> List[Any]:
        """Execute locally as fallback."""
        results = []
        for inp in inputs:
            try:
                result = func(inp)
                results.append(result)
            except Exception as e:
                logger.error(f"Local execution failed for input: {e}")
                results.append(None)

        return results

    async def map_reduce(
        self, map_func: Callable, reduce_func: Callable, inputs: List[Any]
    ) -> Any:
        """Execute map-reduce operation.

        Args:
            map_func: Function to map over inputs
            reduce_func: Function to reduce results
            inputs: Input data

        Returns:
            Reduced result
        """
        # Map phase
        mapped_results = await self.execute_distributed(map_func, inputs)

        # Reduce phase
        if self.backend == DistributedBackend.RAY:
            return await self._reduce_ray(reduce_func, mapped_results)
        elif self.backend == DistributedBackend.DASK:
            return await self._reduce_dask(reduce_func, mapped_results)
        else:
            return self._reduce_local(reduce_func, mapped_results)

    async def _reduce_ray(self, reduce_func: Callable, values: List[Any]) -> Any:
        """Reduce using Ray."""
        if not values:
            return None

        @ray.remote
        def ray_reduce(vals):
            result = vals[0]
            for val in vals[1:]:
                result = reduce_func(result, val)
            return result

        # Tree reduction for efficiency
        while len(values) > 1:
            futures = []
            for i in range(0, len(values), 2):
                if i + 1 < len(values):
                    future = ray_reduce.remote([values[i], values[i + 1]])
                else:
                    future = ray.put(values[i])
                futures.append(future)

            values = ray.get(futures)

        return values[0]

    async def _reduce_dask(self, reduce_func: Callable, values: List[Any]) -> Any:
        """Reduce using Dask."""
        if not values or not self.client:
            return None

        # Tree reduction
        while len(values) > 1:
            futures = []
            for i in range(0, len(values), 2):
                if i + 1 < len(values):
                    future = self.client.submit(reduce_func, values[i], values[i + 1])
                else:
                    future = self.client.scatter(values[i])
                futures.append(future)

            values = self.client.gather(futures)

        return values[0]

    def _reduce_local(self, reduce_func: Callable, values: List[Any]) -> Any:
        """Reduce locally."""
        if not values:
            return None

        result = values[0]
        for val in values[1:]:
            result = reduce_func(result, val)

        return result

    async def scatter_data(self, data: Any) -> Any:
        """Scatter data to workers for efficient access.

        Args:
            data: Data to scatter

        Returns:
            Reference to scattered data
        """
        if self.backend == DistributedBackend.RAY:
            return ray.put(data)
        elif self.backend == DistributedBackend.DASK and self.client:
            return self.client.scatter(data, broadcast=True)
        else:
            return data

    def get_cluster_info(self) -> Dict[str, Any]:
        """Get information about the distributed cluster."""
        info = {"backend": self.backend.value, "metrics": self.metrics.copy()}

        if self.backend == DistributedBackend.RAY and RAY_AVAILABLE:
            info["ray_resources"] = ray.cluster_resources()
            info["ray_nodes"] = ray.nodes()
        elif self.backend == DistributedBackend.DASK and self.client:
            scheduler_info = self.client.scheduler_info()
            info["dask_workers"] = len(scheduler_info.get("workers", {}))
            info["dask_tasks"] = len(scheduler_info.get("tasks", {}))

        return info

    async def shutdown(self):
        """Shutdown the distributed processing backend."""
        if self.backend == DistributedBackend.RAY and RAY_AVAILABLE:
            ray.shutdown()
            logger.info("Ray cluster shutdown")
        elif self.backend == DistributedBackend.DASK and self.client:
            await self.client.close()
            logger.info("Dask cluster shutdown")

        logger.info(f"Distributed processor shutdown. Metrics: {self.metrics}")


class DistributedToolExecutor:
    """Executes tools in a distributed manner."""

    def __init__(self, processor: DistributedProcessor):
        """Initialize distributed tool executor.

        Args:
            processor: Distributed processor instance
        """
        self.processor = processor

    async def execute_tool_batch(
        self,
        tool_func: Callable,
        tool_args: List[Dict[str, Any]],
        max_parallel: int = 10,
    ) -> List[Any]:
        """Execute a tool across multiple inputs in parallel.

        Args:
            tool_func: Tool function to execute
            tool_args: List of argument dictionaries
            max_parallel: Maximum parallel executions

        Returns:
            List of results
        """

        # Wrapper function for distributed execution
        def execute_single(args):
            try:
                return tool_func(**args)
            except Exception as e:
                logger.error(f"Tool execution failed: {e}")
                return {"error": str(e)}

        # Execute distributed
        results = await self.processor.execute_distributed(
            execute_single, tool_args, batch_size=max_parallel
        )

        return results

    async def execute_tool_pipeline(
        self, tools: List[Callable], initial_input: Any
    ) -> Any:
        """Execute a pipeline of tools.

        Args:
            tools: List of tool functions
            initial_input: Initial input data

        Returns:
            Final result
        """
        result = initial_input

        for tool in tools:
            # Execute tool on current result
            if isinstance(result, list):
                # Parallel execution for list inputs
                result = await self.processor.execute_distributed(tool, result)
            else:
                # Single execution
                result = tool(result)

        return result

    async def execute_tool_dag(
        self, dag: Dict[str, Dict[str, Any]], inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute tools in a DAG structure.

        Args:
            dag: DAG definition with nodes and dependencies
            inputs: Initial inputs

        Returns:
            Results from all nodes
        """
        results = {}
        executed = set()

        # Topological execution
        while len(executed) < len(dag):
            ready_nodes = []

            for node_id, node_info in dag.items():
                if node_id in executed:
                    continue

                # Check if dependencies are satisfied
                deps = node_info.get("dependencies", [])
                if all(dep in executed for dep in deps):
                    ready_nodes.append(node_id)

            if not ready_nodes:
                raise RuntimeError("Circular dependency in DAG")

            # Execute ready nodes in parallel
            node_futures = []
            for node_id in ready_nodes:
                node_info = dag[node_id]
                tool_func = node_info["function"]

                # Prepare inputs from dependencies
                node_inputs = inputs.get(node_id, {})
                for dep in node_info.get("dependencies", []):
                    if dep in results:
                        node_inputs[dep] = results[dep]

                # Execute node
                future = self.processor.execute_distributed(tool_func, [node_inputs])
                node_futures.append((node_id, future))

            # Collect results
            for node_id, future in node_futures:
                result = await future
                results[node_id] = result[0] if result else None
                executed.add(node_id)

        return results
