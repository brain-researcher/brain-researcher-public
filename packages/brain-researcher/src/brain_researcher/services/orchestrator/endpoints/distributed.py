"""Distributed Agent Endpoints

FastAPI endpoints for managing the distributed brain researcher agent system.
Provides APIs for cluster management, node operations, and system monitoring.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field
import redis.asyncio as redis

from ...agent.distributed.coordinator import (
    DistributedCoordinator,
    NodeInfo,
    NodeStatus,
    ResourceCapacity,
)
from ...agent.distributed.fault_tolerance import FaultTolerance
from ...agent.distributed.load_balancer import (
    DistributedLoadBalancer,
    LoadBalancingStrategy,
    TaskRequirements,
)
from ..models import ErrorResponse


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/distributed", tags=["distributed"])

# Global coordinator instance (will be initialized on startup)
coordinator: Optional[DistributedCoordinator] = None
load_balancer: Optional[DistributedLoadBalancer] = None
fault_tolerance: Optional[FaultTolerance] = None
redis_client: Optional[redis.Redis] = None


# Request/Response Models

class NodeRegistrationRequest(BaseModel):
    """Request to register a new node"""
    node_id: str = Field(..., description="Unique node identifier")
    hostname: str = Field(..., description="Node hostname")
    cpu_cores: int = Field(..., description="Number of CPU cores", ge=1)
    memory_gb: float = Field(..., description="Memory in GB", ge=0.1)
    gpu_count: int = Field(0, description="Number of GPUs", ge=0)
    storage_gb: float = Field(0.0, description="Storage in GB", ge=0)
    network_mbps: float = Field(1000.0, description="Network bandwidth in Mbps", ge=0)
    capabilities: Optional[List[str]] = Field(None, description="Node capabilities")
    region: str = Field("default", description="Node region")
    zone: str = Field("default", description="Node zone")
    labels: Optional[Dict[str, str]] = Field(None, description="Node labels")


class NodeResponse(BaseModel):
    """Node information response"""
    node_id: str
    hostname: str
    capacity: Dict[str, Any]
    status: str
    leader: bool
    last_heartbeat: Optional[str]
    joined_at: Optional[str]
    tasks_running: int
    load_average: float


class ClusterStatusResponse(BaseModel):
    """Cluster status response"""
    nodes: List[NodeResponse]
    leader_id: Optional[str]
    partition_detected: bool
    total_capacity: Dict[str, Any]
    active_tasks: int
    cluster_health: Dict[str, Any]


class TaskSchedulingRequest(BaseModel):
    """Request to schedule a task"""
    task_id: str = Field(..., description="Unique task identifier")
    task_type: str = Field(..., description="Task type")
    payload: Dict[str, Any] = Field(..., description="Task payload")
    cpu_cores: float = Field(1.0, description="Required CPU cores", ge=0.1)
    memory_gb: float = Field(1.0, description="Required memory in GB", ge=0.1)
    gpu_memory_gb: float = Field(0.0, description="Required GPU memory in GB", ge=0)
    timeout_seconds: int = Field(300, description="Task timeout in seconds", ge=1)
    strategy: Optional[str] = Field(None, description="Load balancing strategy")
    priority: str = Field("medium", description="Task priority")


class TaskSchedulingResponse(BaseModel):
    """Task scheduling response"""
    task_id: str
    assigned_node: Optional[str]
    strategy_used: str
    estimated_completion: Optional[str]


class LoadBalancingStatsResponse(BaseModel):
    """Load balancing statistics response"""
    total_nodes: int
    total_capacity: float
    average_utilization: float
    utilization_variance: float
    nodes: List[Dict[str, Any]]


class ClusterHealthResponse(BaseModel):
    """Cluster health response"""
    overall_health: str
    health_ratio: float
    healthy_nodes: int
    total_nodes: int
    node_states: Dict[str, str]
    active_recoveries: int
    recent_failures: int


class FailureHandlingRequest(BaseModel):
    """Request to handle a failure manually"""
    failure_type: str = Field(..., description="Type of failure")
    affected_nodes: List[str] = Field(..., description="List of affected node IDs")
    description: str = Field(..., description="Failure description")
    severity: int = Field(5, description="Failure severity (1-10)", ge=1, le=10)


# Dependency injection

async def get_redis_client():
    """Get Redis client dependency"""
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url("redis://localhost:6379", decode_responses=False)
    return redis_client


async def get_coordinator():
    """Get distributed coordinator dependency"""
    global coordinator
    if coordinator is None:
        redis = await get_redis_client()
        coordinator = DistributedCoordinator("orchestrator", redis)
        await coordinator.start()
    return coordinator


async def get_load_balancer():
    """Get load balancer dependency"""
    global load_balancer
    if load_balancer is None:
        redis = await get_redis_client()
        load_balancer = DistributedLoadBalancer(redis)
    return load_balancer


async def get_fault_tolerance():
    """Get fault tolerance system dependency"""
    global fault_tolerance
    if fault_tolerance is None:
        coord = await get_coordinator()
        fault_tolerance = FaultTolerance(coord)
        await fault_tolerance.start()
    return fault_tolerance


# Endpoints

@router.get("/status", response_model=ClusterStatusResponse)
async def get_cluster_status(coordinator: DistributedCoordinator = Depends(get_coordinator)):
    """Get current cluster status"""
    try:
        status = await coordinator.get_cluster_status()
        
        # Convert to response format
        nodes = []
        for node_data in status['nodes']:
            nodes.append(NodeResponse(
                node_id=node_data['node_id'],
                hostname=node_data['hostname'],
                capacity=node_data['capacity'],
                status=node_data['status'],
                leader=node_data['leader'],
                last_heartbeat=node_data.get('last_heartbeat'),
                joined_at=node_data.get('joined_at'),
                tasks_running=node_data['tasks_running'],
                load_average=node_data['load_average']
            ))
            
        return ClusterStatusResponse(
            nodes=nodes,
            leader_id=status['leader_id'],
            partition_detected=status['partition_detected'],
            total_capacity=status['total_capacity'],
            active_tasks=status['active_tasks'],
            cluster_health=status['cluster_health']
        )
        
    except Exception as e:
        logger.error(f"Failed to get cluster status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/nodes/register", response_model=Dict[str, str])
async def register_node(
    request: NodeRegistrationRequest,
    coordinator: DistributedCoordinator = Depends(get_coordinator)
):
    """Register a new node in the cluster"""
    try:
        # Create node info
        capacity = ResourceCapacity(
            cpu_cores=request.cpu_cores,
            memory_gb=request.memory_gb,
            gpu_count=request.gpu_count,
            storage_gb=request.storage_gb,
            network_mbps=request.network_mbps
        )
        
        node_info = NodeInfo(
            node_id=request.node_id,
            hostname=request.hostname,
            capacity=capacity,
            status=NodeStatus.JOINING
        )
        
        # Register node
        success = await coordinator.register_node(node_info)
        
        if success:
            return {"message": f"Node {request.node_id} registered successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to register node")
            
    except Exception as e:
        logger.error(f"Node registration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/nodes/{node_id}")
async def deregister_node(
    node_id: str,
    coordinator: DistributedCoordinator = Depends(get_coordinator)
):
    """Deregister a node from the cluster"""
    try:
        success = await coordinator.deregister_node(node_id)
        
        if success:
            return {"message": f"Node {node_id} deregistered successfully"}
        else:
            raise HTTPException(status_code=404, detail="Node not found")
            
    except Exception as e:
        logger.error(f"Node deregistration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leader")
async def get_leader(coordinator: DistributedCoordinator = Depends(get_coordinator)):
    """Get current cluster leader"""
    try:
        leader_id = await coordinator.elect_leader()
        
        if leader_id:
            return {
                "leader_id": leader_id,
                "is_this_node": leader_id == coordinator.node_id,
                "elected_at": datetime.utcnow().isoformat()
            }
        else:
            return {"leader_id": None, "message": "No leader elected"}
            
    except Exception as e:
        logger.error(f"Failed to get leader: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/leader/elect")
async def elect_leader(
    background_tasks: BackgroundTasks,
    coordinator: DistributedCoordinator = Depends(get_coordinator)
):
    """Trigger leader election"""
    try:
        # Run election in background
        background_tasks.add_task(coordinator.elect_leader)
        
        return {"message": "Leader election triggered"}
        
    except Exception as e:
        logger.error(f"Leader election trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/schedule", response_model=TaskSchedulingResponse)
async def schedule_task(
    request: TaskSchedulingRequest,
    load_balancer: DistributedLoadBalancer = Depends(get_load_balancer)
):
    """Schedule a task on the cluster"""
    try:
        # Create task requirements
        requirements = TaskRequirements(
            cpu_cores=request.cpu_cores,
            memory_gb=request.memory_gb,
            gpu_memory_gb=request.gpu_memory_gb,
            estimated_duration=request.timeout_seconds
        )
        
        # Determine strategy
        strategy = None
        if request.strategy:
            try:
                strategy = LoadBalancingStrategy(request.strategy)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid strategy: {request.strategy}")
        
        # Select node
        selected_node = await load_balancer.select_node(
            requirements,
            strategy=strategy,
            task_id=request.task_id
        )
        
        if selected_node:
            # In a real implementation, you would submit the task to the selected node
            return TaskSchedulingResponse(
                task_id=request.task_id,
                assigned_node=selected_node,
                strategy_used=strategy.value if strategy else "adaptive",
                estimated_completion=(
                    datetime.utcnow().isoformat() + f"+{request.timeout_seconds}s"
                )
            )
        else:
            raise HTTPException(
                status_code=503, 
                detail="No suitable node available for task"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Task scheduling failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/load-balancing/stats", response_model=LoadBalancingStatsResponse)
async def get_load_balancing_stats(
    load_balancer: DistributedLoadBalancer = Depends(get_load_balancer)
):
    """Get load balancing statistics"""
    try:
        stats = await load_balancer.get_load_balancing_stats()
        
        if "error" in stats:
            raise HTTPException(status_code=503, detail=stats["error"])
            
        return LoadBalancingStatsResponse(**stats)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get load balancing stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebalance")
async def rebalance_cluster(
    background_tasks: BackgroundTasks,
    load_balancer: DistributedLoadBalancer = Depends(get_load_balancer)
):
    """Trigger cluster rebalancing"""
    try:
        # Run rebalancing in background
        result = await load_balancer.rebalance_cluster()
        
        return result
        
    except Exception as e:
        logger.error(f"Cluster rebalancing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=ClusterHealthResponse)
async def get_cluster_health(
    fault_tolerance: FaultTolerance = Depends(get_fault_tolerance)
):
    """Get cluster health status"""
    try:
        health = fault_tolerance.get_cluster_health()
        
        return ClusterHealthResponse(**health)
        
    except Exception as e:
        logger.error(f"Failed to get cluster health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/failures/handle")
async def handle_failure(
    request: FailureHandlingRequest,
    background_tasks: BackgroundTasks,
    fault_tolerance: FaultTolerance = Depends(get_fault_tolerance)
):
    """Manually handle a failure"""
    try:
        if request.failure_type == "node_failure" and len(request.affected_nodes) == 1:
            # Handle single node failure
            success = await fault_tolerance.handle_node_failure(request.affected_nodes[0])
        elif request.failure_type == "network_partition":
            # Handle network partition
            success = await fault_tolerance.handle_network_partition(request.affected_nodes)
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported failure type: {request.failure_type}"
            )
            
        return {
            "message": f"Failure handling {'succeeded' if success else 'failed'}",
            "success": success
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failure handling failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/failures/history")
async def get_failure_history(
    limit: int = 50,
    fault_tolerance: FaultTolerance = Depends(get_fault_tolerance)
):
    """Get failure history"""
    try:
        history = fault_tolerance.failure_detector.get_failure_history(limit)
        
        return {
            "failures": [failure.to_dict() for failure in history],
            "total_count": len(history)
        }
        
    except Exception as e:
        logger.error(f"Failed to get failure history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recovery/active")
async def get_active_recoveries(
    fault_tolerance: FaultTolerance = Depends(get_fault_tolerance)
):
    """Get active recovery operations"""
    try:
        active_recoveries = fault_tolerance.recovery_manager.active_recoveries
        
        return {
            "active_recoveries": [
                recovery.to_dict() for recovery in active_recoveries.values()
            ],
            "count": len(active_recoveries)
        }
        
    except Exception as e:
        logger.error(f"Failed to get active recoveries: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/nodes")
async def get_node_metrics(
    load_balancer: DistributedLoadBalancer = Depends(get_load_balancer)
):
    """Get detailed metrics for all nodes"""
    try:
        nodes_metrics = await load_balancer._get_active_node_metrics()
        
        return {
            "nodes": [node.to_dict() for node in nodes_metrics],
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get node metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/maintenance/start/{node_id}")
async def start_node_maintenance(
    node_id: str,
    coordinator: DistributedCoordinator = Depends(get_coordinator)
):
    """Put a node into maintenance mode"""
    try:
        # In a real implementation, this would:
        # 1. Drain tasks from the node
        # 2. Mark node as in maintenance
        # 3. Prevent new task assignments
        
        # For now, we'll mark the node as draining
        if node_id not in coordinator.nodes:
            raise HTTPException(status_code=404, detail="Node not found")
            
        coordinator.nodes[node_id].status = NodeStatus.DRAINING
        
        return {"message": f"Node {node_id} entered maintenance mode"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start maintenance for node {node_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/maintenance/end/{node_id}")
async def end_node_maintenance(
    node_id: str,
    coordinator: DistributedCoordinator = Depends(get_coordinator)
):
    """Take a node out of maintenance mode"""
    try:
        if node_id not in coordinator.nodes:
            raise HTTPException(status_code=404, detail="Node not found")
            
        coordinator.nodes[node_id].status = NodeStatus.ACTIVE
        
        return {"message": f"Node {node_id} exited maintenance mode"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to end maintenance for node {node_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Startup/Shutdown events

async def startup_distributed_system():
    """Initialize distributed system on startup"""
    try:
        global coordinator, load_balancer, fault_tolerance, redis_client
        
        # Initialize Redis client
        redis_client = redis.from_url("redis://localhost:6379", decode_responses=False)
        
        # Initialize coordinator
        coordinator = DistributedCoordinator("orchestrator", redis_client)
        await coordinator.start()
        
        # Initialize load balancer
        load_balancer = DistributedLoadBalancer(redis_client)
        
        # Initialize fault tolerance
        fault_tolerance = FaultTolerance(coordinator)
        await fault_tolerance.start()
        
        logger.info("Distributed system initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize distributed system: {e}")
        raise


async def shutdown_distributed_system():
    """Cleanup distributed system on shutdown"""
    try:
        global coordinator, fault_tolerance, redis_client
        
        if fault_tolerance:
            await fault_tolerance.stop()
            
        if coordinator:
            await coordinator.stop()
            
        if redis_client:
            await redis_client.close()
            
        logger.info("Distributed system shutdown completed")
        
    except Exception as e:
        logger.error(f"Error during distributed system shutdown: {e}")


# Add to your main FastAPI app:
# app.add_event_handler("startup", startup_distributed_system)
# app.add_event_handler("shutdown", shutdown_distributed_system)
