"""Main Performance Optimization Integration Module

Coordinates all performance optimizations including parallel execution,
distributed processing, caching, and GPU acceleration.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from brain_researcher.services.agent.tool_optimizer import ToolOptimizer, ToolCategory, ExecutionMode
from brain_researcher.services.agent.distributed_processor import DistributedProcessor, DistributedConfig, DistributedBackend
from brain_researcher.services.agent.cache_manager import CacheManager, CachePolicy
from brain_researcher.services.agent.performance_benchmark import PerformanceBenchmark
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class OptimizationLevel(Enum):
    """Optimization levels for performance tuning."""
    NONE = "none"           # No optimizations
    BASIC = "basic"         # Basic parallelization only
    STANDARD = "standard"   # Parallelization + caching
    ADVANCED = "advanced"   # All optimizations including distributed
    ADAPTIVE = "adaptive"   # Auto-tune based on workload


@dataclass
class PerformanceConfig:
    """Configuration for performance optimizations."""
    optimization_level: OptimizationLevel = OptimizationLevel.STANDARD
    max_parallel_tools: int = 10
    enable_caching: bool = True
    cache_policy: CachePolicy = CachePolicy.MODERATE
    enable_distributed: bool = False
    distributed_backend: DistributedBackend = DistributedBackend.LOCAL
    enable_gpu: bool = True
    enable_monitoring: bool = True
    auto_tune: bool = False
    benchmark_interval: int = 100  # Benchmark every N executions


class PerformanceOptimizer:
    """Main coordinator for all performance optimizations."""
    
    def __init__(self, 
                 config: Optional[PerformanceConfig] = None,
                 tool_registry: Optional[ToolRegistry] = None):
        """Initialize performance optimizer.
        
        Args:
            config: Performance configuration
            tool_registry: Tool registry instance
        """
        self.config = config or PerformanceConfig()
        self.tool_registry = tool_registry or ToolRegistry()
        
        # Initialize components based on optimization level
        self._initialize_components()
        
        # Execution statistics
        self.stats = {
            "total_executions": 0,
            "optimized_executions": 0,
            "cache_hits": 0,
            "distributed_executions": 0,
            "gpu_executions": 0,
            "avg_speedup": 1.0
        }
        
        # Auto-tuning state
        self.auto_tune_history = []
        self.current_settings = {}
    
    def _initialize_components(self):
        """Initialize optimization components based on config."""
        # Tool optimizer for parallel execution and batching
        self.tool_optimizer = ToolOptimizer(
            max_workers=self.config.max_parallel_tools,
            enable_gpu=self.config.enable_gpu,
            cache_manager=None  # Will set after cache init
        )
        
        # Cache manager
        if self.config.enable_caching:
            self.cache_manager = CacheManager(
                cache_policy=self.config.cache_policy,
                enable_multi_level=self.config.optimization_level in [
                    OptimizationLevel.ADVANCED, 
                    OptimizationLevel.ADAPTIVE
                ]
            )
            self.tool_optimizer.cache_manager = self.cache_manager
        else:
            self.cache_manager = None
        
        # Distributed processor
        if self.config.enable_distributed:
            dist_config = DistributedConfig(
                backend=self.config.distributed_backend,
                num_workers=self.config.max_parallel_tools
            )
            self.distributed_processor = DistributedProcessor(dist_config)
        else:
            self.distributed_processor = None
        
        # Performance benchmark
        if self.config.enable_monitoring:
            self.benchmark = PerformanceBenchmark()
        else:
            self.benchmark = None
        
        logger.info(f"Performance optimizer initialized with level: {self.config.optimization_level.value}")
    
    async def initialize(self):
        """Initialize async components."""
        # Initialize distributed processor if enabled
        if self.distributed_processor:
            await self.distributed_processor.initialize()
            logger.info("Distributed processor initialized")
        
        # Profile all tools for optimization
        await self._profile_all_tools()
        
        # Start auto-tuning if enabled
        if self.config.auto_tune:
            asyncio.create_task(self._auto_tune_loop())
    
    async def _profile_all_tools(self):
        """Profile all registered tools for optimization."""
        logger.info("Profiling all registered tools...")
        
        for tool in self.tool_registry.get_all_tools():
            profile = self.tool_optimizer.profile_tool(tool)
            logger.debug(f"Profiled {tool.get_tool_name()}: "
                        f"GPU={profile.gpu_capable}, "
                        f"Parallel={profile.parallelizable}, "
                        f"Cache={profile.cacheable}")
        
        logger.info(f"Profiled {len(self.tool_optimizer.tool_profiles)} tools")
    
    async def execute_tool(self,
                          tool_name: str,
                          args: Dict[str, Any],
                          force_mode: Optional[ExecutionMode] = None) -> Any:
        """Execute a tool with optimizations.
        
        Args:
            tool_name: Name of the tool to execute
            args: Tool arguments
            force_mode: Force specific execution mode
            
        Returns:
            Tool execution result
        """
        self.stats["total_executions"] += 1
        
        # Get tool from registry
        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool {tool_name} not found")
        
        # Determine execution strategy
        mode = force_mode or self._select_execution_mode(tool_name, args)
        
        # Execute with appropriate strategy
        if mode == ExecutionMode.DISTRIBUTED and self.distributed_processor:
            result = await self._execute_distributed(tool, args)
            self.stats["distributed_executions"] += 1
        else:
            result = await self.tool_optimizer.execute_optimized(tool, args, mode)
            
            if mode == ExecutionMode.GPU_ACCELERATED:
                self.stats["gpu_executions"] += 1
            elif mode in [ExecutionMode.PARALLEL, ExecutionMode.BATCH]:
                self.stats["optimized_executions"] += 1
        
        # Update cache hit statistics
        if self.cache_manager:
            cache_stats = self.cache_manager.metrics
            self.stats["cache_hits"] = cache_stats.total_hits
        
        # Periodic benchmarking
        if self.benchmark and self.stats["total_executions"] % self.config.benchmark_interval == 0:
            await self._run_benchmark()
        
        return result
    
    async def execute_batch(self,
                          tool_name: str,
                          batch_args: List[Dict[str, Any]],
                          max_parallel: Optional[int] = None) -> List[Any]:
        """Execute a tool on multiple inputs in batch.
        
        Args:
            tool_name: Name of the tool to execute
            batch_args: List of argument dictionaries
            max_parallel: Maximum parallel executions
            
        Returns:
            List of results
        """
        from brain_researcher.services.agent.tool_optimizer import BatchRequest
        
        batch_request = BatchRequest(
            tool_name=tool_name,
            requests=batch_args,
            max_parallel=max_parallel or self.config.max_parallel_tools
        )
        
        return await self.tool_optimizer.execute_batch(batch_request)
    
    async def execute_workflow(self,
                              workflow: List[Dict[str, Any]],
                              initial_input: Any) -> Any:
        """Execute a workflow of tools.
        
        Args:
            workflow: List of tool definitions with dependencies
            initial_input: Initial input data
            
        Returns:
            Final workflow result
        """
        result = initial_input
        
        for step in workflow:
            tool_name = step["tool"]
            args = step.get("args", {})
            
            # Add previous result to args if specified
            if step.get("use_previous_result", True):
                args["input_data"] = result
            
            # Execute tool
            result = await self.execute_tool(tool_name, args)
            
            # Check for early termination
            if step.get("stop_on_error") and isinstance(result, dict) and "error" in result:
                logger.warning(f"Workflow stopped at {tool_name} due to error")
                break
        
        return result
    
    def _select_execution_mode(self, tool_name: str, args: Dict[str, Any]) -> ExecutionMode:
        """Select optimal execution mode based on config and tool profile."""
        # Check optimization level
        if self.config.optimization_level == OptimizationLevel.NONE:
            return ExecutionMode.SEQUENTIAL
        
        # Get tool profile
        profile = self.tool_optimizer.tool_profiles.get(tool_name)
        if not profile:
            return ExecutionMode.SEQUENTIAL
        
        # Adaptive mode - use historical data
        if self.config.optimization_level == OptimizationLevel.ADAPTIVE:
            return self._adaptive_mode_selection(profile, args)
        
        # Advanced mode - use all optimizations
        if self.config.optimization_level == OptimizationLevel.ADVANCED:
            if profile.gpu_capable and self.config.enable_gpu:
                return ExecutionMode.GPU_ACCELERATED
            elif self.config.enable_distributed:
                return ExecutionMode.DISTRIBUTED
            elif profile.parallelizable:
                return ExecutionMode.PARALLEL
        
        # Standard mode - parallel + cache
        if self.config.optimization_level == OptimizationLevel.STANDARD:
            if profile.parallelizable:
                return ExecutionMode.PARALLEL
        
        # Basic mode - simple parallel
        if self.config.optimization_level == OptimizationLevel.BASIC:
            if profile.parallelizable and profile.avg_execution_time > 1.0:
                return ExecutionMode.PARALLEL
        
        return ExecutionMode.SEQUENTIAL
    
    def _adaptive_mode_selection(self, profile, args: Dict[str, Any]) -> ExecutionMode:
        """Adaptively select execution mode based on historical performance."""
        # Estimate data size
        import sys
        data_size = sys.getsizeof(args) / (1024 * 1024)  # MB
        
        # Use heuristics based on profile and data size
        if profile.gpu_capable and data_size > 10 and self.config.enable_gpu:
            return ExecutionMode.GPU_ACCELERATED
        
        if data_size > 100 and self.config.enable_distributed:
            return ExecutionMode.DISTRIBUTED
        
        if profile.parallelizable and (data_size > 1 or profile.avg_execution_time > 0.5):
            return ExecutionMode.PARALLEL
        
        return ExecutionMode.SEQUENTIAL
    
    async def _execute_distributed(self, tool, args: Dict[str, Any]) -> Any:
        """Execute tool using distributed processing."""
        if not self.distributed_processor:
            return await self.tool_optimizer.execute_optimized(tool, args)
        
        # Wrapper for distributed execution
        def tool_wrapper(tool_args):
            return tool.run(**tool_args)
        
        # Execute distributed
        results = await self.distributed_processor.execute_distributed(
            tool_wrapper,
            [args]
        )
        
        return results[0] if results else None
    
    async def _run_benchmark(self):
        """Run periodic performance benchmark."""
        if not self.benchmark:
            return
        
        logger.info("Running performance benchmark...")
        
        # Select representative tools for benchmarking
        sample_tools = self._select_benchmark_tools()
        
        for tool_name in sample_tools:
            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                continue
            
            # Generate test inputs
            test_inputs = self._generate_test_inputs(tool_name)
            
            # Benchmark different modes
            try:
                # Baseline
                baseline = await self.benchmark.benchmark_tool(
                    tool.run,
                    test_inputs,
                    execution_mode="sequential"
                )
                
                # Optimized
                optimized = await self.benchmark.benchmark_tool(
                    lambda args: self.execute_tool(tool_name, args),
                    test_inputs,
                    execution_mode="optimized"
                )
                
                # Calculate speedup
                if baseline.duration_ms > 0:
                    speedup = baseline.duration_ms / optimized.duration_ms
                    self.stats["avg_speedup"] = (
                        self.stats["avg_speedup"] * 0.9 + speedup * 0.1
                    )  # Exponential moving average
                    
                    logger.info(f"{tool_name} speedup: {speedup:.2f}x")
                    
            except Exception as e:
                logger.error(f"Benchmark failed for {tool_name}: {e}")
    
    def _select_benchmark_tools(self) -> List[str]:
        """Select representative tools for benchmarking."""
        # Select one tool from each category
        selected = []
        categories_seen = set()
        
        for name, profile in self.tool_optimizer.tool_profiles.items():
            if profile.category not in categories_seen:
                selected.append(name)
                categories_seen.add(profile.category)
                
                if len(selected) >= 5:  # Limit to 5 tools
                    break
        
        return selected
    
    def _generate_test_inputs(self, tool_name: str) -> List[Dict[str, Any]]:
        """Generate test inputs for benchmarking."""
        # Simple test data generation
        import numpy as np
        
        return [
            {
                "data": np.random.randn(100, 100).tolist(),
                "params": {"test": True, "iteration": i}
            }
            for i in range(5)
        ]
    
    async def _auto_tune_loop(self):
        """Auto-tuning loop for adaptive optimization."""
        while True:
            await asyncio.sleep(60)  # Tune every minute
            
            try:
                # Analyze recent performance
                if self.stats["total_executions"] > 100:
                    await self._auto_tune()
            except Exception as e:
                logger.error(f"Auto-tuning error: {e}")
    
    async def _auto_tune(self):
        """Automatically tune optimization settings."""
        logger.info("Running auto-tuning...")
        
        # Analyze cache efficiency
        if self.cache_manager:
            cache_stats = self.cache_manager.metrics
            hit_rate = cache_stats.hit_rate
            
            # Adjust cache policy based on hit rate
            if hit_rate < 0.2 and self.config.cache_policy != CachePolicy.CONSERVATIVE:
                self.config.cache_policy = CachePolicy.CONSERVATIVE
                logger.info("Switched to conservative caching due to low hit rate")
            elif hit_rate > 0.7 and self.config.cache_policy != CachePolicy.AGGRESSIVE:
                self.config.cache_policy = CachePolicy.AGGRESSIVE
                logger.info("Switched to aggressive caching due to high hit rate")
        
        # Analyze parallelization efficiency
        if self.stats["optimized_executions"] > 0:
            optimization_rate = self.stats["optimized_executions"] / self.stats["total_executions"]
            
            # Adjust parallel workers based on efficiency
            if self.stats["avg_speedup"] < 1.2 and self.config.max_parallel_tools > 4:
                self.config.max_parallel_tools = max(4, self.config.max_parallel_tools - 2)
                logger.info(f"Reduced parallel workers to {self.config.max_parallel_tools}")
            elif self.stats["avg_speedup"] > 2.0 and self.config.max_parallel_tools < 20:
                self.config.max_parallel_tools = min(20, self.config.max_parallel_tools + 2)
                logger.info(f"Increased parallel workers to {self.config.max_parallel_tools}")
        
        # Record tuning history
        self.auto_tune_history.append({
            "timestamp": asyncio.get_event_loop().time(),
            "stats": self.stats.copy(),
            "settings": {
                "cache_policy": self.config.cache_policy.value,
                "max_parallel": self.config.max_parallel_tools
            }
        })
    
    def get_performance_report(self) -> Dict[str, Any]:
        """Get comprehensive performance report.
        
        Returns:
            Performance statistics and recommendations
        """
        report = {
            "configuration": {
                "optimization_level": self.config.optimization_level.value,
                "max_parallel_tools": self.config.max_parallel_tools,
                "caching_enabled": self.config.enable_caching,
                "distributed_enabled": self.config.enable_distributed,
                "gpu_enabled": self.config.enable_gpu
            },
            "statistics": self.stats.copy(),
            "tool_profiles": {
                name: {
                    "category": profile.category.value,
                    "avg_execution_time": profile.avg_execution_time,
                    "gpu_capable": profile.gpu_capable,
                    "cache_hit_rate": profile.cache_hit_rate,
                    "execution_count": profile.execution_count
                }
                for name, profile in self.tool_optimizer.tool_profiles.items()
            }
        }
        
        # Add cache statistics
        if self.cache_manager:
            report["cache_stats"] = {
                "hit_rate": self.cache_manager.metrics.hit_rate,
                "total_hits": self.cache_manager.metrics.total_hits,
                "total_misses": self.cache_manager.metrics.total_misses
            }
        
        # Add distributed statistics
        if self.distributed_processor:
            report["distributed_stats"] = self.distributed_processor.get_cluster_info()
        
        # Add benchmark results
        if self.benchmark:
            report["benchmark_summary"] = self.benchmark.generate_report()
        
        # Generate recommendations
        report["recommendations"] = self._generate_recommendations()
        
        return report
    
    def _generate_recommendations(self) -> List[str]:
        """Generate performance optimization recommendations."""
        recommendations = []
        
        # Check cache efficiency
        if self.cache_manager and self.cache_manager.metrics.hit_rate < 0.3:
            recommendations.append("Consider adjusting cache policy or TTL settings for better hit rate")
        
        # Check parallelization usage
        if self.stats["total_executions"] > 0:
            opt_rate = self.stats["optimized_executions"] / self.stats["total_executions"]
            if opt_rate < 0.5:
                recommendations.append("Many executions are not optimized - consider profiling more tools")
        
        # Check speedup
        if self.stats["avg_speedup"] < 1.5:
            recommendations.append("Low average speedup - consider enabling GPU or distributed processing")
        
        # Check GPU usage
        if self.config.enable_gpu and self.stats["gpu_executions"] == 0:
            recommendations.append("GPU is enabled but not being used - check GPU availability")
        
        return recommendations
    
    async def shutdown(self):
        """Shutdown the performance optimizer and clean up resources."""
        logger.info("Shutting down performance optimizer...")
        
        # Save final statistics
        report = self.get_performance_report()
        logger.info(f"Final performance report: {report['statistics']}")
        
        # Shutdown components
        if self.distributed_processor:
            await self.distributed_processor.shutdown()
        
        if self.tool_optimizer:
            await self.tool_optimizer.shutdown()
        
        logger.info("Performance optimizer shutdown complete")