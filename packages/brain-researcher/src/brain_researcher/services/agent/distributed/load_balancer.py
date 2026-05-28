"""Distributed Load Balancer

Implements multiple load balancing strategies for task distribution
in the distributed brain researcher agent system.
"""

import asyncio
import json
import logging
import time
import hashlib
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict, deque
import statistics

import redis.asyncio as redis


logger = logging.getLogger(__name__)


class LoadBalancingStrategy(str, Enum):
    """Available load balancing strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    CONSISTENT_HASH = "consistent_hash"
    WORK_STEALING = "work_stealing"
    RESOURCE_AWARE = "resource_aware"
    LOCALITY_AWARE = "locality_aware"
    ADAPTIVE = "adaptive"


class NodeCapability(str, Enum):
    """Node capability types"""
    CPU_INTENSIVE = "cpu_intensive"
    MEMORY_INTENSIVE = "memory_intensive"
    GPU_COMPUTE = "gpu_compute"
    NETWORK_IO = "network_io"
    STORAGE_IO = "storage_io"
    GENERAL_PURPOSE = "general_purpose"


@dataclass
class TaskRequirements:
    """Task resource and capability requirements"""
    cpu_cores: float = 1.0
    memory_gb: float = 1.0
    gpu_memory_gb: float = 0.0
    network_mbps: float = 0.0
    storage_gb: float = 0.0
    estimated_duration: float = 60.0  # seconds
    capabilities: List[NodeCapability] = None
    locality_preferences: List[str] = None  # preferred regions/zones
    affinity_labels: Dict[str, str] = None
    anti_affinity_labels: Dict[str, str] = None
    
    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = [NodeCapability.GENERAL_PURPOSE]
        if self.locality_preferences is None:
            self.locality_preferences = []
        if self.affinity_labels is None:
            self.affinity_labels = {}
        if self.anti_affinity_labels is None:
            self.anti_affinity_labels = {}


@dataclass
class NodeMetrics:
    """Real-time node performance metrics"""
    node_id: str
    cpu_utilization: float  # 0-100%
    memory_utilization: float  # 0-100%
    gpu_utilization: float = 0.0  # 0-100%
    network_utilization: float = 0.0  # 0-100%
    storage_utilization: float = 0.0  # 0-100%
    active_tasks: int = 0
    queue_length: int = 0
    average_response_time: float = 0.0  # milliseconds
    success_rate: float = 100.0  # percentage
    last_updated: datetime = None
    capabilities: List[NodeCapability] = None
    region: str = "default"
    zone: str = "default"
    labels: Dict[str, str] = None
    
    def __post_init__(self):
        if self.last_updated is None:
            self.last_updated = datetime.utcnow()
        if self.capabilities is None:
            self.capabilities = [NodeCapability.GENERAL_PURPOSE]
        if self.labels is None:
            self.labels = {}
            
    def overall_utilization(self) -> float:
        """Calculate overall node utilization"""
        weights = {
            'cpu': 0.4,
            'memory': 0.3,
            'gpu': 0.2,
            'network': 0.05,
            'storage': 0.05
        }
        
        return (
            weights['cpu'] * self.cpu_utilization +
            weights['memory'] * self.memory_utilization +
            weights['gpu'] * self.gpu_utilization +
            weights['network'] * self.network_utilization +
            weights['storage'] * self.storage_utilization
        )
        
    def can_handle_task(self, requirements: TaskRequirements) -> bool:
        """Check if node can handle task requirements"""
        # Check capability match
        if not any(cap in self.capabilities for cap in requirements.capabilities):
            return False
            
        # Check basic resource availability (simplified)
        if self.cpu_utilization > 90 and requirements.cpu_cores > 0.5:
            return False
        if self.memory_utilization > 90 and requirements.memory_gb > 0.5:
            return False
        if self.gpu_utilization > 90 and requirements.gpu_memory_gb > 0:
            return False
            
        return True
        
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        data = asdict(self)
        if self.last_updated:
            data['last_updated'] = self.last_updated.isoformat()
        return data
        
    @classmethod
    def from_dict(cls, data: Dict) -> 'NodeMetrics':
        """Create from dictionary"""
        if 'last_updated' in data and data['last_updated']:
            data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return cls(**data)


class RoundRobinStrategy:
    """Round-robin load balancing strategy"""
    
    def __init__(self):
        self.current_index = 0
        
    async def select_node(self, 
                         nodes: List[NodeMetrics], 
                         task_requirements: TaskRequirements) -> Optional[NodeMetrics]:
        """Select node using round-robin strategy"""
        if not nodes:
            return None
            
        # Filter nodes that can handle the task
        capable_nodes = [node for node in nodes if node.can_handle_task(task_requirements)]
        
        if not capable_nodes:
            return None
            
        # Round-robin selection
        selected_node = capable_nodes[self.current_index % len(capable_nodes)]
        self.current_index += 1
        
        return selected_node


class LeastLoadedStrategy:
    """Least-loaded load balancing strategy"""
    
    async def select_node(self, 
                         nodes: List[NodeMetrics], 
                         task_requirements: TaskRequirements) -> Optional[NodeMetrics]:
        """Select node with least load"""
        if not nodes:
            return None
            
        # Filter nodes that can handle the task
        capable_nodes = [node for node in nodes if node.can_handle_task(task_requirements)]
        
        if not capable_nodes:
            return None
            
        # Sort by overall utilization (ascending)
        capable_nodes.sort(key=lambda x: x.overall_utilization())
        
        return capable_nodes[0]


class ConsistentHashStrategy:
    """Consistent hashing load balancing strategy"""
    
    def __init__(self, replicas: int = 150):
        self.replicas = replicas
        self.ring: Dict[int, str] = {}  # hash -> node_id
        self.nodes: Set[str] = set()
        
    def add_node(self, node_id: str):
        """Add node to hash ring"""
        if node_id in self.nodes:
            return
            
        self.nodes.add(node_id)
        
        for i in range(self.replicas):
            key = self._hash(f"{node_id}:{i}")
            self.ring[key] = node_id
            
    def remove_node(self, node_id: str):
        """Remove node from hash ring"""
        if node_id not in self.nodes:
            return
            
        self.nodes.remove(node_id)
        
        keys_to_remove = [key for key, node in self.ring.items() if node == node_id]
        for key in keys_to_remove:
            del self.ring[key]
            
    def update_nodes(self, node_ids: List[str]):
        """Update hash ring with current nodes"""
        current_nodes = set(node_ids)
        
        # Remove nodes no longer present
        for node_id in list(self.nodes):
            if node_id not in current_nodes:
                self.remove_node(node_id)
                
        # Add new nodes
        for node_id in current_nodes:
            if node_id not in self.nodes:
                self.add_node(node_id)
                
    async def select_node(self, 
                         nodes: List[NodeMetrics], 
                         task_requirements: TaskRequirements,
                         task_id: str = None) -> Optional[NodeMetrics]:
        """Select node using consistent hashing"""
        if not nodes:
            return None
            
        # Update hash ring
        node_ids = [node.node_id for node in nodes]
        self.update_nodes(node_ids)
        
        if not self.ring:
            return None
            
        # Generate hash for task
        if task_id is None:
            task_id = str(time.time())
        task_hash = self._hash(task_id)
        
        # Find next node in ring
        sorted_keys = sorted(self.ring.keys())
        
        for key in sorted_keys:
            if key >= task_hash:
                selected_node_id = self.ring[key]
                break
        else:
            # Wrap around to first node
            selected_node_id = self.ring[sorted_keys[0]]
            
        # Find node metrics for selected node
        for node in nodes:
            if node.node_id == selected_node_id and node.can_handle_task(task_requirements):
                return node
                
        # If selected node can't handle task, fall back to least loaded
        fallback_strategy = LeastLoadedStrategy()
        return await fallback_strategy.select_node(nodes, task_requirements)
        
    def _hash(self, key: str) -> int:
        """Generate hash for key"""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)


class WorkStealingStrategy:
    """Work stealing load balancing strategy"""
    
    def __init__(self, steal_threshold: float = 0.3):
        self.steal_threshold = steal_threshold  # Steal if utilization < threshold
        
    async def select_node(self, 
                         nodes: List[NodeMetrics], 
                         task_requirements: TaskRequirements) -> Optional[NodeMetrics]:
        """Select node using work stealing logic"""
        if not nodes:
            return None
            
        # Filter nodes that can handle the task
        capable_nodes = [node for node in nodes if node.can_handle_task(task_requirements)]
        
        if not capable_nodes:
            return None
            
        # Find nodes with low utilization (good candidates for work stealing)
        underutilized_nodes = [
            node for node in capable_nodes 
            if node.overall_utilization() < self.steal_threshold * 100
        ]
        
        if underutilized_nodes:
            # Select least loaded among underutilized nodes
            return min(underutilized_nodes, key=lambda x: x.overall_utilization())
        else:
            # Fall back to least loaded overall
            return min(capable_nodes, key=lambda x: x.overall_utilization())


class ResourceAwareStrategy:
    """Resource-aware load balancing strategy"""
    
    async def select_node(self, 
                         nodes: List[NodeMetrics], 
                         task_requirements: TaskRequirements) -> Optional[NodeMetrics]:
        """Select node based on resource requirements"""
        if not nodes:
            return None
            
        # Score nodes based on resource availability and requirements
        scored_nodes = []
        
        for node in nodes:
            if not node.can_handle_task(task_requirements):
                continue
                
            score = self._calculate_resource_score(node, task_requirements)
            scored_nodes.append((score, node))
            
        if not scored_nodes:
            return None
            
        # Select node with highest score
        scored_nodes.sort(key=lambda x: x[0], reverse=True)
        return scored_nodes[0][1]
        
    def _calculate_resource_score(self, 
                                 node: NodeMetrics, 
                                 requirements: TaskRequirements) -> float:
        """Calculate resource match score for a node"""
        score = 0.0
        
        # CPU score (higher available CPU = higher score)
        cpu_available = 100 - node.cpu_utilization
        cpu_needed = requirements.cpu_cores * 25  # rough conversion to percentage
        if cpu_available >= cpu_needed:
            score += 0.3 * (cpu_available - cpu_needed) / 100
        else:
            score -= 0.5  # Penalty for insufficient CPU
            
        # Memory score
        memory_available = 100 - node.memory_utilization
        memory_needed = requirements.memory_gb * 10  # rough conversion
        if memory_available >= memory_needed:
            score += 0.3 * (memory_available - memory_needed) / 100
        else:
            score -= 0.5
            
        # GPU score (if needed)
        if requirements.gpu_memory_gb > 0:
            gpu_available = 100 - node.gpu_utilization
            if gpu_available > 50:  # Sufficient GPU
                score += 0.2
            else:
                score -= 0.3
                
        # Queue length penalty
        score -= node.queue_length * 0.05
        
        # Success rate bonus
        score += (node.success_rate - 90) * 0.01
        
        return score


class LocalityAwareStrategy:
    """Locality-aware load balancing strategy"""
    
    async def select_node(self, 
                         nodes: List[NodeMetrics], 
                         task_requirements: TaskRequirements) -> Optional[NodeMetrics]:
        """Select node considering locality preferences"""
        if not nodes:
            return None
            
        # Filter nodes that can handle the task
        capable_nodes = [node for node in nodes if node.can_handle_task(task_requirements)]
        
        if not capable_nodes:
            return None
            
        # Score nodes based on locality preferences
        scored_nodes = []
        
        for node in capable_nodes:
            score = self._calculate_locality_score(node, task_requirements)
            scored_nodes.append((score, node))
            
        # Sort by score (descending)
        scored_nodes.sort(key=lambda x: x[0], reverse=True)
        
        # Among top-scored nodes, pick least loaded
        top_score = scored_nodes[0][0]
        top_nodes = [node for score, node in scored_nodes if score == top_score]
        
        return min(top_nodes, key=lambda x: x.overall_utilization())
        
    def _calculate_locality_score(self, 
                                 node: NodeMetrics, 
                                 requirements: TaskRequirements) -> float:
        """Calculate locality preference score"""
        score = 0.0
        
        # Region preference
        if requirements.locality_preferences:
            if node.region in requirements.locality_preferences:
                score += 10.0
            if node.zone in requirements.locality_preferences:
                score += 5.0
                
        # Affinity labels
        if requirements.affinity_labels:
            matches = sum(
                1 for key, value in requirements.affinity_labels.items()
                if node.labels.get(key) == value
            )
            score += matches * 3.0
            
        # Anti-affinity labels (negative score)
        if requirements.anti_affinity_labels:
            matches = sum(
                1 for key, value in requirements.anti_affinity_labels.items()
                if node.labels.get(key) == value
            )
            score -= matches * 5.0
            
        return score


class AdaptiveStrategy:
    """Adaptive load balancing that switches strategies based on conditions"""
    
    def __init__(self):
        self.strategies = {
            LoadBalancingStrategy.ROUND_ROBIN: RoundRobinStrategy(),
            LoadBalancingStrategy.LEAST_LOADED: LeastLoadedStrategy(),
            LoadBalancingStrategy.CONSISTENT_HASH: ConsistentHashStrategy(),
            LoadBalancingStrategy.WORK_STEALING: WorkStealingStrategy(),
            LoadBalancingStrategy.RESOURCE_AWARE: ResourceAwareStrategy(),
            LoadBalancingStrategy.LOCALITY_AWARE: LocalityAwareStrategy()
        }
        
        # Strategy selection history for learning
        self.performance_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        
    async def select_node(self, 
                         nodes: List[NodeMetrics], 
                         task_requirements: TaskRequirements,
                         task_id: str = None) -> Optional[NodeMetrics]:
        """Adaptively select best strategy and node"""
        if not nodes:
            return None
            
        # Choose strategy based on current conditions
        strategy_name = self._choose_strategy(nodes, task_requirements)
        strategy = self.strategies[strategy_name]
        
        # Select node using chosen strategy
        if strategy_name == LoadBalancingStrategy.CONSISTENT_HASH:
            selected_node = await strategy.select_node(nodes, task_requirements, task_id)
        else:
            selected_node = await strategy.select_node(nodes, task_requirements)
            
        return selected_node
        
    def _choose_strategy(self, 
                        nodes: List[NodeMetrics], 
                        requirements: TaskRequirements) -> LoadBalancingStrategy:
        """Choose best strategy based on current conditions"""
        
        # Calculate cluster metrics
        total_nodes = len(nodes)
        avg_utilization = statistics.mean([node.overall_utilization() for node in nodes])
        utilization_variance = statistics.variance([node.overall_utilization() for node in nodes])
        
        # Strategy selection logic
        if total_nodes <= 2:
            return LoadBalancingStrategy.ROUND_ROBIN
            
        elif requirements.locality_preferences or requirements.affinity_labels:
            return LoadBalancingStrategy.LOCALITY_AWARE
            
        elif requirements.gpu_memory_gb > 0 or any(
            cap in [NodeCapability.GPU_COMPUTE, NodeCapability.CPU_INTENSIVE, NodeCapability.MEMORY_INTENSIVE]
            for cap in requirements.capabilities
        ):
            return LoadBalancingStrategy.RESOURCE_AWARE
            
        elif avg_utilization > 80:  # High load - use work stealing
            return LoadBalancingStrategy.WORK_STEALING
            
        elif utilization_variance > 500:  # High variance - balance load
            return LoadBalancingStrategy.LEAST_LOADED
            
        else:  # Default to consistent hashing for even distribution
            return LoadBalancingStrategy.CONSISTENT_HASH
            
    def record_performance(self, strategy: str, response_time: float, success: bool):
        """Record strategy performance for learning"""
        score = 1.0 if success else 0.0
        if success:
            # Lower response time = higher score
            score += max(0, (1000 - response_time) / 1000)
            
        self.performance_history[strategy].append(score)


class DistributedLoadBalancer:
    """Main distributed load balancer"""
    
    def __init__(self, 
                 redis_client: redis.Redis,
                 default_strategy: LoadBalancingStrategy = LoadBalancingStrategy.ADAPTIVE):
        self.redis = redis_client
        self.default_strategy = default_strategy
        
        # Initialize all strategies
        self.strategies = {
            LoadBalancingStrategy.ROUND_ROBIN: RoundRobinStrategy(),
            LoadBalancingStrategy.LEAST_LOADED: LeastLoadedStrategy(),
            LoadBalancingStrategy.CONSISTENT_HASH: ConsistentHashStrategy(),
            LoadBalancingStrategy.WORK_STEALING: WorkStealingStrategy(),
            LoadBalancingStrategy.RESOURCE_AWARE: ResourceAwareStrategy(),
            LoadBalancingStrategy.LOCALITY_AWARE: LocalityAwareStrategy(),
            LoadBalancingStrategy.ADAPTIVE: AdaptiveStrategy()
        }
        
        # Metrics collection
        self.node_metrics: Dict[str, NodeMetrics] = {}
        self.metrics_ttl = 300  # 5 minutes
        
        logger.info(f"Initialized load balancer with strategy: {default_strategy}")
        
    async def select_node(self, 
                         task_requirements: TaskRequirements,
                         strategy: LoadBalancingStrategy = None,
                         task_id: str = None) -> Optional[str]:
        """Select best node for task execution"""
        try:
            # Use specified strategy or default
            if strategy is None:
                strategy = self.default_strategy
                
            # Get current node metrics
            nodes = await self._get_active_node_metrics()
            
            if not nodes:
                logger.warning("No active nodes available")
                return None
                
            # Select node using strategy
            selected_strategy = self.strategies[strategy]
            
            if strategy == LoadBalancingStrategy.CONSISTENT_HASH:
                selected_node = await selected_strategy.select_node(nodes, task_requirements, task_id)
            else:
                selected_node = await selected_strategy.select_node(nodes, task_requirements)
                
            if selected_node:
                logger.debug(f"Selected node {selected_node.node_id} using {strategy}")
                return selected_node.node_id
            else:
                logger.warning("No suitable node found for task requirements")
                return None
                
        except Exception as e:
            logger.error(f"Node selection failed: {e}")
            return None
            
    async def update_node_metrics(self, node_metrics: NodeMetrics):
        """Update metrics for a node"""
        try:
            self.node_metrics[node_metrics.node_id] = node_metrics
            
            # Store in Redis with TTL
            await self.redis.setex(
                f"node_metrics:{node_metrics.node_id}",
                self.metrics_ttl,
                json.dumps(node_metrics.to_dict())
            )
            
        except Exception as e:
            logger.error(f"Failed to update node metrics for {node_metrics.node_id}: {e}")
            
    async def get_load_balancing_stats(self) -> Dict:
        """Get load balancing statistics"""
        nodes = await self._get_active_node_metrics()
        
        if not nodes:
            return {"error": "No active nodes"}
            
        total_capacity = sum(100 - node.overall_utilization() for node in nodes)
        avg_utilization = statistics.mean([node.overall_utilization() for node in nodes])
        
        utilizations = [node.overall_utilization() for node in nodes]
        utilization_variance = statistics.variance(utilizations) if len(utilizations) > 1 else 0
        
        return {
            "total_nodes": len(nodes),
            "total_capacity": total_capacity,
            "average_utilization": avg_utilization,
            "utilization_variance": utilization_variance,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "utilization": node.overall_utilization(),
                    "active_tasks": node.active_tasks,
                    "queue_length": node.queue_length,
                    "capabilities": [cap.value for cap in node.capabilities]
                }
                for node in nodes
            ]
        }
        
    async def rebalance_cluster(self) -> Dict:
        """Trigger cluster rebalancing"""
        try:
            # Get current load distribution
            stats = await self.get_load_balancing_stats()
            
            if "error" in stats:
                return stats
                
            # Check if rebalancing is needed
            if stats["utilization_variance"] < 100:  # Low variance, no rebalancing needed
                return {
                    "action": "none",
                    "reason": "Load is already well balanced"
                }
                
            # Publish rebalancing event
            await self.redis.publish(
                "cluster:rebalance",
                json.dumps({
                    "timestamp": datetime.utcnow().isoformat(),
                    "stats": stats,
                    "action": "rebalance_requested"
                })
            )
            
            return {
                "action": "rebalance_triggered",
                "stats": stats
            }
            
        except Exception as e:
            logger.error(f"Cluster rebalancing failed: {e}")
            return {"error": str(e)}
            
    async def _get_active_node_metrics(self) -> List[NodeMetrics]:
        """Get metrics for all active nodes"""
        try:
            nodes = []
            
            # Get from Redis
            async for key in self.redis.scan_iter(match="node_metrics:*"):
                metrics_data = await self.redis.get(key)
                if metrics_data:
                    try:
                        metrics_dict = json.loads(metrics_data)
                        node_metrics = NodeMetrics.from_dict(metrics_dict)
                        
                        # Check if metrics are recent
                        time_since_update = datetime.utcnow() - node_metrics.last_updated
                        if time_since_update.total_seconds() < self.metrics_ttl:
                            nodes.append(node_metrics)
                            
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        logger.warning(f"Invalid metrics data for {key}: {e}")
                        
            return nodes
            
        except Exception as e:
            logger.error(f"Failed to get active node metrics: {e}")
            return []
