"""Performance Benchmarking and Validation Framework

Validates optimizations and measures performance improvements.
"""

import asyncio
import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import GPUtil
import psutil

logger = logging.getLogger(__name__)


class BenchmarkType(Enum):
    """Types of benchmarks to run."""

    LATENCY = "latency"
    THROUGHPUT = "throughput"
    MEMORY = "memory"
    GPU_UTILIZATION = "gpu_utilization"
    CACHE_EFFICIENCY = "cache_efficiency"
    SCALABILITY = "scalability"


@dataclass
class BenchmarkResult:
    """Result from a benchmark run."""

    benchmark_type: BenchmarkType
    tool_name: str
    execution_mode: str
    duration_ms: float
    throughput: Optional[float] = None  # ops/sec
    memory_mb: Optional[float] = None
    gpu_memory_mb: Optional[float] = None
    cache_hit_rate: Optional[float] = None
    error_rate: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ComparisonResult:
    """Comparison between baseline and optimized execution."""

    tool_name: str
    baseline: BenchmarkResult
    optimized: BenchmarkResult
    speedup: float
    memory_reduction: float
    improvement_summary: str


class PerformanceBenchmark:
    """Benchmarks and validates performance optimizations."""

    def __init__(self):
        """Initialize performance benchmark."""
        self.results: List[BenchmarkResult] = []
        self.comparisons: List[ComparisonResult] = []

        # System monitoring
        self.cpu_count = psutil.cpu_count()
        self.total_memory = psutil.virtual_memory().total / (1024**3)  # GB

        try:
            self.gpus = GPUtil.getGPUs()
            self.gpu_available = len(self.gpus) > 0
        except:
            self.gpu_available = False
            self.gpus = []

    async def benchmark_tool(
        self,
        tool_func: Callable,
        test_inputs: List[Dict[str, Any]],
        execution_mode: str = "baseline",
        warmup_runs: int = 2,
        benchmark_runs: int = 10,
    ) -> BenchmarkResult:
        """Benchmark a single tool execution.

        Args:
            tool_func: Tool function to benchmark
            test_inputs: Test input data
            execution_mode: Mode of execution (baseline/optimized)
            warmup_runs: Number of warmup runs
            benchmark_runs: Number of benchmark runs

        Returns:
            Benchmark result
        """
        tool_name = getattr(tool_func, "__name__", "unknown")

        # Warmup runs
        for _ in range(warmup_runs):
            try:
                await self._execute_tool(tool_func, test_inputs[0])
            except:
                pass

        # Benchmark runs
        durations = []
        memory_usage = []
        gpu_memory = []
        errors = 0

        for i in range(benchmark_runs):
            test_input = test_inputs[i % len(test_inputs)]

            # Memory before
            mem_before = psutil.Process().memory_info().rss / (1024**2)  # MB
            gpu_mem_before = self._get_gpu_memory() if self.gpu_available else 0

            # Execute and time
            start_time = time.perf_counter()
            try:
                await self._execute_tool(tool_func, test_input)
            except Exception as e:
                logger.error(f"Benchmark execution failed: {e}")
                errors += 1

            duration = (time.perf_counter() - start_time) * 1000  # ms
            durations.append(duration)

            # Memory after
            mem_after = psutil.Process().memory_info().rss / (1024**2)
            gpu_mem_after = self._get_gpu_memory() if self.gpu_available else 0

            memory_usage.append(mem_after - mem_before)
            if self.gpu_available:
                gpu_memory.append(gpu_mem_after - gpu_mem_before)

        # Calculate statistics
        avg_duration = statistics.mean(durations)
        throughput = (
            (1000 / avg_duration) * len(test_inputs[0])
            if isinstance(test_inputs[0], list)
            else 1000 / avg_duration
        )
        avg_memory = statistics.mean(memory_usage) if memory_usage else 0
        avg_gpu_memory = statistics.mean(gpu_memory) if gpu_memory else None

        result = BenchmarkResult(
            benchmark_type=BenchmarkType.LATENCY,
            tool_name=tool_name,
            execution_mode=execution_mode,
            duration_ms=avg_duration,
            throughput=throughput,
            memory_mb=avg_memory,
            gpu_memory_mb=avg_gpu_memory,
            error_rate=errors / benchmark_runs,
            metadata={
                "min_duration": min(durations),
                "max_duration": max(durations),
                "std_duration": (
                    statistics.stdev(durations) if len(durations) > 1 else 0
                ),
                "runs": benchmark_runs,
            },
        )

        self.results.append(result)
        return result

    async def benchmark_parallel_execution(
        self,
        tool_func: Callable,
        test_inputs: List[Dict[str, Any]],
        parallel_degrees: List[int] = [1, 2, 4, 8, 16],
    ) -> Dict[int, BenchmarkResult]:
        """Benchmark parallel execution with different degrees of parallelism.

        Args:
            tool_func: Tool function to benchmark
            test_inputs: Test input data
            parallel_degrees: Degrees of parallelism to test

        Returns:
            Results for each degree of parallelism
        """
        results = {}

        for degree in parallel_degrees:
            # Execute with specific parallelism
            start_time = time.perf_counter()

            tasks = []
            for i in range(min(degree, len(test_inputs))):
                task = asyncio.create_task(
                    self._execute_tool(tool_func, test_inputs[i])
                )
                tasks.append(task)

            await asyncio.gather(*tasks, return_exceptions=True)

            duration = (time.perf_counter() - start_time) * 1000
            throughput = (len(tasks) / duration) * 1000

            result = BenchmarkResult(
                benchmark_type=BenchmarkType.THROUGHPUT,
                tool_name=getattr(tool_func, "__name__", "unknown"),
                execution_mode=f"parallel_{degree}",
                duration_ms=duration,
                throughput=throughput,
                metadata={"parallel_degree": degree},
            )

            results[degree] = result
            self.results.append(result)

        return results

    async def benchmark_cache_efficiency(
        self,
        tool_func: Callable,
        cache_manager: Any,
        test_inputs: List[Dict[str, Any]],
        repeat_factor: int = 3,
    ) -> BenchmarkResult:
        """Benchmark cache efficiency.

        Args:
            tool_func: Tool function to benchmark
            cache_manager: Cache manager instance
            test_inputs: Test input data
            repeat_factor: How many times to repeat inputs

        Returns:
            Cache efficiency benchmark result
        """
        tool_name = getattr(tool_func, "__name__", "unknown")

        # Clear cache
        if hasattr(cache_manager, "clear"):
            await cache_manager.clear()

        cache_hits = 0
        cache_misses = 0
        total_duration = 0

        # Execute with repeated inputs
        for _ in range(repeat_factor):
            for test_input in test_inputs:
                start_time = time.perf_counter()

                # Check if result is cached
                cache_key = self._generate_cache_key(tool_name, test_input)
                cached = await cache_manager.get(cache_key) if cache_manager else None

                if cached:
                    cache_hits += 1
                else:
                    cache_misses += 1
                    # Execute and cache
                    result = await self._execute_tool(tool_func, test_input)
                    if cache_manager:
                        await cache_manager.set(cache_key, result)

                total_duration += (time.perf_counter() - start_time) * 1000

        hit_rate = (
            cache_hits / (cache_hits + cache_misses)
            if (cache_hits + cache_misses) > 0
            else 0
        )

        result = BenchmarkResult(
            benchmark_type=BenchmarkType.CACHE_EFFICIENCY,
            tool_name=tool_name,
            execution_mode="cached",
            duration_ms=total_duration / (len(test_inputs) * repeat_factor),
            cache_hit_rate=hit_rate,
            metadata={
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "repeat_factor": repeat_factor,
            },
        )

        self.results.append(result)
        return result

    async def benchmark_memory_usage(
        self,
        tool_func: Callable,
        test_inputs: List[Dict[str, Any]],
        measure_peak: bool = True,
    ) -> BenchmarkResult:
        """Benchmark memory usage.

        Args:
            tool_func: Tool function to benchmark
            test_inputs: Test input data
            measure_peak: Whether to measure peak memory

        Returns:
            Memory usage benchmark result
        """
        tool_name = getattr(tool_func, "__name__", "unknown")

        # Get baseline memory
        process = psutil.Process()
        baseline_memory = process.memory_info().rss / (1024**2)  # MB

        peak_memory = baseline_memory
        memory_samples = []

        # Monitor memory during execution
        async def monitor_memory():
            nonlocal peak_memory
            while monitoring:
                current_memory = process.memory_info().rss / (1024**2)
                memory_samples.append(current_memory)
                peak_memory = max(peak_memory, current_memory)
                await asyncio.sleep(0.1)

        monitoring = True
        monitor_task = asyncio.create_task(monitor_memory())

        # Execute tool
        start_time = time.perf_counter()
        for test_input in test_inputs:
            await self._execute_tool(tool_func, test_input)
        duration = (time.perf_counter() - start_time) * 1000

        monitoring = False
        await monitor_task

        # Calculate memory statistics
        avg_memory = (
            statistics.mean(memory_samples) if memory_samples else baseline_memory
        )
        memory_increase = (
            peak_memory - baseline_memory
            if measure_peak
            else avg_memory - baseline_memory
        )

        result = BenchmarkResult(
            benchmark_type=BenchmarkType.MEMORY,
            tool_name=tool_name,
            execution_mode="memory_profile",
            duration_ms=duration,
            memory_mb=memory_increase,
            metadata={
                "baseline_memory": baseline_memory,
                "peak_memory": peak_memory,
                "avg_memory": avg_memory,
                "samples": len(memory_samples),
            },
        )

        self.results.append(result)
        return result

    async def compare_execution_modes(
        self,
        tool_func: Callable,
        baseline_executor: Callable,
        optimized_executor: Callable,
        test_inputs: List[Dict[str, Any]],
    ) -> ComparisonResult:
        """Compare baseline vs optimized execution.

        Args:
            tool_func: Tool function to benchmark
            baseline_executor: Baseline execution function
            optimized_executor: Optimized execution function
            test_inputs: Test input data

        Returns:
            Comparison result
        """
        tool_name = getattr(tool_func, "__name__", "unknown")

        # Benchmark baseline
        baseline_result = await self.benchmark_tool(
            lambda args: baseline_executor(tool_func, args),
            test_inputs,
            execution_mode="baseline",
        )

        # Benchmark optimized
        optimized_result = await self.benchmark_tool(
            lambda args: optimized_executor(tool_func, args),
            test_inputs,
            execution_mode="optimized",
        )

        # Calculate improvements
        speedup = (
            baseline_result.duration_ms / optimized_result.duration_ms
            if optimized_result.duration_ms > 0
            else 1.0
        )

        memory_reduction = 0.0
        if baseline_result.memory_mb and optimized_result.memory_mb:
            memory_reduction = (
                baseline_result.memory_mb - optimized_result.memory_mb
            ) / baseline_result.memory_mb

        # Generate summary
        summary = f"Speedup: {speedup:.2f}x, Memory reduction: {memory_reduction:.1%}"
        if optimized_result.cache_hit_rate:
            summary += f", Cache hit rate: {optimized_result.cache_hit_rate:.1%}"

        comparison = ComparisonResult(
            tool_name=tool_name,
            baseline=baseline_result,
            optimized=optimized_result,
            speedup=speedup,
            memory_reduction=memory_reduction,
            improvement_summary=summary,
        )

        self.comparisons.append(comparison)
        return comparison

    async def validate_thread_safety(
        self,
        tool_func: Callable,
        test_input: Dict[str, Any],
        num_threads: int = 10,
        iterations: int = 100,
    ) -> bool:
        """Validate thread safety of tool execution.

        Args:
            tool_func: Tool function to test
            test_input: Test input data
            num_threads: Number of concurrent threads
            iterations: Number of iterations per thread

        Returns:
            True if thread-safe
        """
        results = []
        errors = []

        async def thread_execution():
            for _ in range(iterations):
                try:
                    result = await self._execute_tool(tool_func, test_input)
                    results.append(result)
                except Exception as e:
                    errors.append(str(e))

        # Run concurrent executions
        tasks = [asyncio.create_task(thread_execution()) for _ in range(num_threads)]
        await asyncio.gather(*tasks)

        # Check for errors
        if errors:
            logger.error(f"Thread safety validation failed with {len(errors)} errors")
            return False

        # Check result consistency
        if results:
            # Simple check: all results should be similar
            first_result = str(results[0])
            inconsistent = sum(1 for r in results if str(r) != first_result)

            if inconsistent > len(results) * 0.1:  # Allow 10% variation
                logger.warning(
                    f"Result inconsistency detected: {inconsistent}/{len(results)}"
                )
                return False

        logger.info(f"Thread safety validation passed for {tool_func.__name__}")
        return True

    async def benchmark_scalability(
        self, tool_func: Callable, input_sizes: List[int] = [10, 100, 1000, 10000]
    ) -> Dict[int, BenchmarkResult]:
        """Benchmark scalability with different input sizes.

        Args:
            tool_func: Tool function to benchmark
            input_sizes: Different input sizes to test

        Returns:
            Results for each input size
        """
        results = {}

        for size in input_sizes:
            # Generate test data of appropriate size
            test_inputs = [
                self._generate_test_input(size) for _ in range(min(10, size))
            ]

            # Benchmark with this size
            result = await self.benchmark_tool(
                tool_func, test_inputs, execution_mode=f"size_{size}"
            )

            results[size] = result

        # Analyze scalability
        if len(results) > 1:
            sizes = sorted(results.keys())
            times = [results[s].duration_ms for s in sizes]

            # Check if linear or worse
            complexity = "linear"
            if len(sizes) > 2:
                ratio1 = times[1] / times[0]
                ratio2 = times[-1] / times[-2]

                if ratio2 > ratio1 * 1.5:
                    complexity = "super-linear"
                elif ratio2 < ratio1 * 0.8:
                    complexity = "sub-linear"

            logger.info(f"Scalability analysis: {complexity} complexity")

        return results

    def _get_gpu_memory(self) -> float:
        """Get current GPU memory usage in MB."""
        if not self.gpu_available:
            return 0.0

        try:
            gpu = self.gpus[0]  # Use first GPU
            return gpu.memoryUsed
        except:
            return 0.0

    async def _execute_tool(self, tool_func: Callable, args: Dict[str, Any]) -> Any:
        """Execute a tool function."""
        if asyncio.iscoroutinefunction(tool_func):
            return await tool_func(args)
        else:
            return tool_func(args)

    def _generate_cache_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Generate cache key for tool execution."""
        import hashlib

        key_data = json.dumps({"tool": tool_name, "args": args}, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()

    def _generate_test_input(self, size: int) -> Dict[str, Any]:
        """Generate test input of specified size."""
        import numpy as np

        return {
            "data": np.random.randn(size, 100).tolist(),  # size x 100 matrix
            "params": {"size": size, "test": True},
        }

    def generate_report(self) -> str:
        """Generate performance benchmark report.

        Returns:
            Formatted report string
        """
        report = ["=" * 80]
        report.append("PERFORMANCE BENCHMARK REPORT")
        report.append("=" * 80)
        report.append(f"Timestamp: {datetime.now().isoformat()}")
        report.append(f"System: {self.cpu_count} CPUs, {self.total_memory:.1f} GB RAM")

        if self.gpu_available:
            report.append(f"GPU: {len(self.gpus)} device(s) available")

        report.append("")

        # Benchmark results
        if self.results:
            report.append("BENCHMARK RESULTS:")
            report.append("-" * 40)

            for result in self.results:
                report.append(f"\n{result.tool_name} ({result.execution_mode}):")
                report.append(f"  Duration: {result.duration_ms:.2f} ms")

                if result.throughput:
                    report.append(f"  Throughput: {result.throughput:.2f} ops/sec")

                if result.memory_mb:
                    report.append(f"  Memory: {result.memory_mb:.2f} MB")

                if result.cache_hit_rate is not None:
                    report.append(f"  Cache hit rate: {result.cache_hit_rate:.1%}")

                if result.error_rate > 0:
                    report.append(f"  Error rate: {result.error_rate:.1%}")

        # Comparisons
        if self.comparisons:
            report.append("\n" + "=" * 40)
            report.append("OPTIMIZATION COMPARISONS:")
            report.append("-" * 40)

            for comp in self.comparisons:
                report.append(f"\n{comp.tool_name}:")
                report.append(f"  Speedup: {comp.speedup:.2f}x")
                report.append(f"  Memory reduction: {comp.memory_reduction:.1%}")
                report.append(f"  Summary: {comp.improvement_summary}")

        report.append("\n" + "=" * 80)

        return "\n".join(report)

    def save_results(self, filepath: str):
        """Save benchmark results to file.

        Args:
            filepath: Path to save results
        """
        data = {
            "timestamp": datetime.now().isoformat(),
            "system": {
                "cpus": self.cpu_count,
                "memory_gb": self.total_memory,
                "gpu_available": self.gpu_available,
            },
            "results": [
                {
                    "type": r.benchmark_type.value,
                    "tool": r.tool_name,
                    "mode": r.execution_mode,
                    "duration_ms": r.duration_ms,
                    "throughput": r.throughput,
                    "memory_mb": r.memory_mb,
                    "cache_hit_rate": r.cache_hit_rate,
                    "error_rate": r.error_rate,
                    "metadata": r.metadata,
                }
                for r in self.results
            ],
            "comparisons": [
                {
                    "tool": c.tool_name,
                    "speedup": c.speedup,
                    "memory_reduction": c.memory_reduction,
                    "summary": c.improvement_summary,
                }
                for c in self.comparisons
            ],
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Benchmark results saved to {filepath}")
