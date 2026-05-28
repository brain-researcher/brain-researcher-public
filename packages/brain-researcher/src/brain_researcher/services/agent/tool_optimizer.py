"""Tool Optimization Framework for Performance & Scale

Implements parallel execution, batching, and performance optimization for 207+ tools.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Callable
import time
import hashlib
import json

from brain_researcher.services.tools.tool_base import NeuroKGToolWrapper
from brain_researcher.services.agent.cache_manager import CacheManager
from brain_researcher.services.agent.parallel_executor import ParallelExecutor

logger = logging.getLogger(__name__)


class ToolCategory(Enum):
    """Categories for tool grouping and optimization."""
    FMRI_ANALYSIS = "fmri_analysis"
    PREPROCESSING = "preprocessing"
    STATISTICAL = "statistical"
    VISUALIZATION = "visualization"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    NLP = "nlp"
    DEEP_LEARNING = "deep_learning"
    META_ANALYSIS = "meta_analysis"
    CONNECTIVITY = "connectivity"
    SEGMENTATION = "segmentation"


class ExecutionMode(Enum):
    """Execution modes for tools."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    BATCH = "batch"
    DISTRIBUTED = "distributed"
    GPU_ACCELERATED = "gpu_accelerated"


@dataclass
class ToolProfile:
    """Performance profile for a tool."""
    tool_name: str
    category: ToolCategory
    avg_execution_time: float = 0.0
    memory_usage_mb: float = 0.0
    gpu_capable: bool = False
    parallelizable: bool = True
    cacheable: bool = True
    batch_size: int = 1
    dependencies: Set[str] = field(default_factory=set)
    execution_count: int = 0
    cache_hit_rate: float = 0.0


@dataclass 
class BatchRequest:
    """Batch execution request."""
    tool_name: str
    requests: List[Dict[str, Any]]
    mode: ExecutionMode = ExecutionMode.BATCH
    max_parallel: int = 10
    use_cache: bool = True


class ToolOptimizer:
    """Optimizes tool execution through parallelization, batching, and caching."""
    
    def __init__(self, 
                 max_workers: int = 10,
                 enable_gpu: bool = True,
                 cache_manager: Optional[CacheManager] = None):
        """Initialize the tool optimizer.
        
        Args:
            max_workers: Maximum parallel workers
            enable_gpu: Enable GPU acceleration
            cache_manager: Cache manager instance
        """
        self.max_workers = max_workers
        self.enable_gpu = enable_gpu
        self.cache_manager = cache_manager or CacheManager()
        
        # Execution pools
        self.thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self.process_pool = ProcessPoolExecutor(max_workers=max_workers // 2)
        
        # Tool profiles for optimization decisions
        self.tool_profiles: Dict[str, ToolProfile] = {}
        
        # Category-specific executors
        self.category_executors: Dict[ToolCategory, Callable] = {
            ToolCategory.FMRI_ANALYSIS: self._execute_fmri_batch,
            ToolCategory.PREPROCESSING: self._execute_preprocessing_batch,
            ToolCategory.STATISTICAL: self._execute_statistical_batch,
            ToolCategory.VISUALIZATION: self._execute_visualization_batch,
            ToolCategory.DEEP_LEARNING: self._execute_deep_learning_batch,
        }
        
        # Performance metrics
        self.metrics = {
            "total_executions": 0,
            "parallel_executions": 0,
            "batch_executions": 0,
            "cache_hits": 0,
            "gpu_accelerated": 0,
            "avg_speedup": 1.0,
        }
    
    def profile_tool(self, tool: NeuroKGToolWrapper) -> ToolProfile:
        """Profile a tool for optimization.
        
        Args:
            tool: Tool to profile
            
        Returns:
            Tool performance profile
        """
        tool_name = tool.get_tool_name()
        
        # Categorize tool based on name patterns
        category = self._categorize_tool(tool_name)
        
        # Check capabilities
        gpu_capable = self._check_gpu_capability(tool_name)
        parallelizable = self._check_parallelizable(tool_name)
        cacheable = self._check_cacheable(tool_name)
        
        profile = ToolProfile(
            tool_name=tool_name,
            category=category,
            gpu_capable=gpu_capable,
            parallelizable=parallelizable,
            cacheable=cacheable,
            batch_size=self._determine_batch_size(category),
        )
        
        self.tool_profiles[tool_name] = profile
        return profile
    
    async def execute_optimized(self, 
                                tool: NeuroKGToolWrapper,
                                args: Dict[str, Any],
                                mode: Optional[ExecutionMode] = None) -> Any:
        """Execute a tool with optimizations.
        
        Args:
            tool: Tool to execute
            args: Tool arguments
            mode: Execution mode override
            
        Returns:
            Tool execution result
        """
        tool_name = tool.get_tool_name()
        
        # Get or create tool profile
        if tool_name not in self.tool_profiles:
            self.profile_tool(tool)
        
        profile = self.tool_profiles[tool_name]
        
        # Check cache first if enabled
        if profile.cacheable and self.cache_manager:
            cache_key = self._generate_cache_key(tool_name, args)
            cached_result = await self.cache_manager.get(cache_key)
            if cached_result is not None:
                self.metrics["cache_hits"] += 1
                profile.cache_hit_rate = self.metrics["cache_hits"] / (profile.execution_count + 1)
                return cached_result
        
        # Determine execution mode
        if mode is None:
            mode = self._select_execution_mode(profile, args)
        
        # Execute with selected mode
        start_time = time.time()
        
        if mode == ExecutionMode.GPU_ACCELERATED and profile.gpu_capable:
            result = await self._execute_gpu_accelerated(tool, args)
            self.metrics["gpu_accelerated"] += 1
        elif mode == ExecutionMode.PARALLEL and profile.parallelizable:
            result = await self._execute_parallel(tool, args)
            self.metrics["parallel_executions"] += 1
        else:
            result = await self._execute_sequential(tool, args)
        
        execution_time = time.time() - start_time
        
        # Update profile
        profile.execution_count += 1
        profile.avg_execution_time = (
            (profile.avg_execution_time * (profile.execution_count - 1) + execution_time) 
            / profile.execution_count
        )
        
        # Cache result if applicable
        if profile.cacheable and self.cache_manager and result:
            await self.cache_manager.set(cache_key, result, ttl=3600)
        
        self.metrics["total_executions"] += 1
        
        return result
    
    async def execute_batch(self, batch_request: BatchRequest) -> List[Any]:
        """Execute a batch of requests for the same tool.
        
        Args:
            batch_request: Batch execution request
            
        Returns:
            List of results
        """
        tool_name = batch_request.tool_name
        profile = self.tool_profiles.get(tool_name)
        
        if not profile:
            logger.warning(f"No profile for tool {tool_name}, using sequential execution")
            return await self._execute_batch_sequential(batch_request)
        
        # Select appropriate batch executor
        executor = self.category_executors.get(
            profile.category, 
            self._execute_batch_parallel
        )
        
        self.metrics["batch_executions"] += 1
        
        return await executor(batch_request, profile)
    
    def _categorize_tool(self, tool_name: str) -> ToolCategory:
        """Categorize a tool based on its name."""
        name_lower = tool_name.lower()
        
        if any(x in name_lower for x in ["fmri", "glm", "contrast"]):
            return ToolCategory.FMRI_ANALYSIS
        elif any(x in name_lower for x in ["preprocess", "normalize", "smooth"]):
            return ToolCategory.PREPROCESSING
        elif any(x in name_lower for x in ["stat", "test", "anova", "correlation"]):
            return ToolCategory.STATISTICAL
        elif any(x in name_lower for x in ["plot", "visual", "display", "render"]):
            return ToolCategory.VISUALIZATION
        elif any(x in name_lower for x in ["graph", "kg", "knowledge"]):
            return ToolCategory.KNOWLEDGE_GRAPH
        elif any(x in name_lower for x in ["nlp", "text", "language"]):
            return ToolCategory.NLP
        elif any(x in name_lower for x in ["nn", "deep", "torch", "tensorflow"]):
            return ToolCategory.DEEP_LEARNING
        elif any(x in name_lower for x in ["meta", "pooled", "aggregate"]):
            return ToolCategory.META_ANALYSIS
        elif any(x in name_lower for x in ["connect", "network", "graph"]):
            return ToolCategory.CONNECTIVITY
        elif any(x in name_lower for x in ["segment", "parcell", "roi"]):
            return ToolCategory.SEGMENTATION
        
        return ToolCategory.STATISTICAL  # Default
    
    def _check_gpu_capability(self, tool_name: str) -> bool:
        """Check if a tool can use GPU acceleration."""
        gpu_keywords = ["torch", "tensorflow", "cuda", "gpu", "deep", "nn", 
                       "convol", "transform", "fft", "matrix"]
        return any(keyword in tool_name.lower() for keyword in gpu_keywords)
    
    def _check_parallelizable(self, tool_name: str) -> bool:
        """Check if a tool can be parallelized."""
        # Most tools can be parallelized except those with state dependencies
        non_parallel = ["sequential", "state", "session", "interactive"]
        return not any(keyword in tool_name.lower() for keyword in non_parallel)
    
    def _check_cacheable(self, tool_name: str) -> bool:
        """Check if tool results can be cached."""
        # Don't cache tools that have side effects or return time-sensitive data
        non_cacheable = ["write", "save", "delete", "update", "random", "realtime"]
        return not any(keyword in tool_name.lower() for keyword in non_cacheable)
    
    def _determine_batch_size(self, category: ToolCategory) -> int:
        """Determine optimal batch size for a category."""
        batch_sizes = {
            ToolCategory.FMRI_ANALYSIS: 5,
            ToolCategory.PREPROCESSING: 10,
            ToolCategory.STATISTICAL: 20,
            ToolCategory.VISUALIZATION: 15,
            ToolCategory.KNOWLEDGE_GRAPH: 50,
            ToolCategory.NLP: 30,
            ToolCategory.DEEP_LEARNING: 8,
            ToolCategory.META_ANALYSIS: 10,
            ToolCategory.CONNECTIVITY: 10,
            ToolCategory.SEGMENTATION: 5,
        }
        return batch_sizes.get(category, 10)
    
    def _generate_cache_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Generate a cache key for tool execution."""
        key_data = json.dumps({"tool": tool_name, "args": args}, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()
    
    def _select_execution_mode(self, profile: ToolProfile, args: Dict[str, Any]) -> ExecutionMode:
        """Select optimal execution mode based on profile and args."""
        # Check for GPU acceleration first
        if profile.gpu_capable and self.enable_gpu:
            return ExecutionMode.GPU_ACCELERATED
        
        # Check data size for distributed execution
        data_size = self._estimate_data_size(args)
        if data_size > 1000:  # MB
            return ExecutionMode.DISTRIBUTED
        
        # Use parallel for parallelizable tools
        if profile.parallelizable:
            return ExecutionMode.PARALLEL
        
        return ExecutionMode.SEQUENTIAL
    
    def _estimate_data_size(self, args: Dict[str, Any]) -> float:
        """Estimate data size in MB from arguments."""
        # Simplified estimation
        import sys
        return sys.getsizeof(args) / (1024 * 1024)
    
    async def _execute_sequential(self, tool: NeuroKGToolWrapper, args: Dict[str, Any]) -> Any:
        """Execute tool sequentially."""
        return tool.run(**args)
    
    async def _execute_parallel(self, tool: NeuroKGToolWrapper, args: Dict[str, Any]) -> Any:
        """Execute tool in parallel thread."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, tool.run, **args)
    
    async def _execute_gpu_accelerated(self, tool: NeuroKGToolWrapper, args: Dict[str, Any]) -> Any:
        """Execute tool with GPU acceleration."""
        # Check for GPU availability
        try:
            import torch
            if torch.cuda.is_available():
                # Move data to GPU if applicable
                args = self._move_to_gpu(args)
        except ImportError:
            pass
        
        return await self._execute_parallel(tool, args)
    
    def _move_to_gpu(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Move applicable data to GPU."""
        import torch
        
        gpu_args = {}
        for key, value in args.items():
            if isinstance(value, (list, tuple)) and len(value) > 0:
                # Convert to tensor if numeric
                try:
                    tensor = torch.tensor(value).cuda()
                    gpu_args[key] = tensor
                except:
                    gpu_args[key] = value
            else:
                gpu_args[key] = value
        
        return gpu_args
    
    async def _execute_batch_sequential(self, batch_request: BatchRequest) -> List[Any]:
        """Execute batch requests sequentially."""
        results = []
        for request in batch_request.requests:
            # Implement actual tool execution here
            results.append(await self._execute_sequential(None, request))
        return results
    
    async def _execute_batch_parallel(self, 
                                     batch_request: BatchRequest, 
                                     profile: ToolProfile) -> List[Any]:
        """Execute batch requests in parallel."""
        tasks = []
        for request in batch_request.requests:
            # Create async task for each request
            task = asyncio.create_task(self._execute_parallel(None, request))
            tasks.append(task)
        
        # Execute with concurrency limit
        results = []
        for i in range(0, len(tasks), batch_request.max_parallel):
            batch_tasks = tasks[i:i + batch_request.max_parallel]
            batch_results = await asyncio.gather(*batch_tasks)
            results.extend(batch_results)
        
        return results
    
    async def _execute_fmri_batch(self, 
                                  batch_request: BatchRequest,
                                  profile: ToolProfile) -> List[Any]:
        """Optimized batch execution for fMRI tools."""
        # Group by similar parameters for better cache utilization
        grouped = self._group_similar_requests(batch_request.requests)
        
        results = []
        for group in grouped:
            # Process similar requests together
            group_results = await self._execute_batch_parallel(
                BatchRequest(
                    tool_name=batch_request.tool_name,
                    requests=group,
                    max_parallel=min(5, batch_request.max_parallel)
                ),
                profile
            )
            results.extend(group_results)
        
        return results
    
    async def _execute_preprocessing_batch(self,
                                          batch_request: BatchRequest,
                                          profile: ToolProfile) -> List[Any]:
        """Optimized batch execution for preprocessing tools."""
        # Use process pool for CPU-intensive preprocessing
        loop = asyncio.get_event_loop()
        
        futures = []
        for request in batch_request.requests:
            future = loop.run_in_executor(self.process_pool, self._process_data, request)
            futures.append(future)
        
        return await asyncio.gather(*futures)
    
    async def _execute_statistical_batch(self,
                                        batch_request: BatchRequest,
                                        profile: ToolProfile) -> List[Any]:
        """Optimized batch execution for statistical tools."""
        # Vectorize operations where possible
        if self._can_vectorize(batch_request.requests):
            return await self._execute_vectorized(batch_request)
        
        return await self._execute_batch_parallel(batch_request, profile)
    
    async def _execute_visualization_batch(self,
                                          batch_request: BatchRequest,
                                          profile: ToolProfile) -> List[Any]:
        """Optimized batch execution for visualization tools."""
        # Render visualizations in parallel with resource limits
        return await self._execute_batch_parallel(
            BatchRequest(
                tool_name=batch_request.tool_name,
                requests=batch_request.requests,
                max_parallel=min(3, batch_request.max_parallel)  # Limit concurrent renders
            ),
            profile
        )
    
    async def _execute_deep_learning_batch(self,
                                          batch_request: BatchRequest,
                                          profile: ToolProfile) -> List[Any]:
        """Optimized batch execution for deep learning tools."""
        # Batch inputs for GPU processing
        if self.enable_gpu and profile.gpu_capable:
            return await self._execute_gpu_batch(batch_request)
        
        return await self._execute_batch_parallel(batch_request, profile)
    
    async def _execute_gpu_batch(self, batch_request: BatchRequest) -> List[Any]:
        """Execute batch on GPU."""
        try:
            import torch
            
            # Combine batch inputs
            batched_input = self._combine_batch_inputs(batch_request.requests)
            
            # Process entire batch on GPU
            if torch.cuda.is_available():
                batched_input = self._move_to_gpu(batched_input)
            
            # Execute batched computation
            # This would call the actual tool with batched input
            result = None  # Placeholder
            
            # Split results back
            return self._split_batch_results(result, len(batch_request.requests))
            
        except ImportError:
            # Fallback to CPU execution
            return await self._execute_batch_parallel(batch_request, None)
    
    def _group_similar_requests(self, requests: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Group similar requests for better cache utilization."""
        groups = {}
        
        for request in requests:
            # Create signature based on parameter types
            signature = self._get_request_signature(request)
            if signature not in groups:
                groups[signature] = []
            groups[signature].append(request)
        
        return list(groups.values())
    
    def _get_request_signature(self, request: Dict[str, Any]) -> str:
        """Get signature of request for grouping."""
        # Simple signature based on keys and types
        signature_parts = []
        for key in sorted(request.keys()):
            signature_parts.append(f"{key}:{type(request[key]).__name__}")
        return ":".join(signature_parts)
    
    def _can_vectorize(self, requests: List[Dict[str, Any]]) -> bool:
        """Check if requests can be vectorized."""
        if not requests:
            return False
        
        # Check if all requests have same structure
        first_keys = set(requests[0].keys())
        for request in requests[1:]:
            if set(request.keys()) != first_keys:
                return False
        
        # Check if values are numeric
        for request in requests:
            for value in request.values():
                if not isinstance(value, (int, float, list, tuple)):
                    return False
        
        return True
    
    async def _execute_vectorized(self, batch_request: BatchRequest) -> List[Any]:
        """Execute vectorized operations."""
        import numpy as np
        
        # Convert to numpy arrays
        vectorized_data = {}
        for key in batch_request.requests[0].keys():
            values = [req[key] for req in batch_request.requests]
            vectorized_data[key] = np.array(values)
        
        # Execute vectorized operation
        # This would call the actual tool with vectorized input
        result = None  # Placeholder
        
        return [result] * len(batch_request.requests)
    
    def _combine_batch_inputs(self, requests: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Combine multiple requests into batch input."""
        if not requests:
            return {}
        
        batched = {}
        for key in requests[0].keys():
            values = [req.get(key) for req in requests]
            batched[key] = values
        
        return batched
    
    def _split_batch_results(self, batch_result: Any, num_requests: int) -> List[Any]:
        """Split batch results back to individual results."""
        if isinstance(batch_result, list):
            return batch_result[:num_requests]
        
        # For other types, duplicate the result
        return [batch_result] * num_requests
    
    def _process_data(self, request: Dict[str, Any]) -> Any:
        """Process data in separate process."""
        # Placeholder for actual processing
        return request
    
    def get_optimization_stats(self) -> Dict[str, Any]:
        """Get optimization statistics."""
        stats = self.metrics.copy()
        
        # Calculate speedup
        if stats["total_executions"] > 0:
            optimized = stats["parallel_executions"] + stats["gpu_accelerated"]
            stats["optimization_rate"] = optimized / stats["total_executions"]
        else:
            stats["optimization_rate"] = 0.0
        
        # Add tool profile stats
        stats["profiled_tools"] = len(self.tool_profiles)
        stats["gpu_capable_tools"] = sum(1 for p in self.tool_profiles.values() if p.gpu_capable)
        stats["cacheable_tools"] = sum(1 for p in self.tool_profiles.values() if p.cacheable)
        
        return stats
    
    async def shutdown(self):
        """Shutdown the optimizer and clean up resources."""
        self.thread_pool.shutdown(wait=True)
        self.process_pool.shutdown(wait=True)
        logger.info("Tool optimizer shutdown complete")