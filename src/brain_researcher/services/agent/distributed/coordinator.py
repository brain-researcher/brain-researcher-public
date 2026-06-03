"""Distributed Coordinator

Manages cluster coordination, leader election, and node registration
for the distributed brain researcher agent system.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, asdict
from enum import Enum

import redis.asyncio as redis
from pydantic import BaseModel


logger = logging.getLogger(__name__)


class NodeStatus(str, Enum):
    ACTIVE = "active"
    DRAINING = "draining"
    FAILED = "failed"
    JOINING = "joining"


@dataclass
class ResourceCapacity:
    """Resource capacity information for a node"""
    cpu_cores: int
    memory_gb: float
    gpu_count: int = 0
    storage_gb: float = 0.0
    network_mbps: float = 1000.0

    def __post_init__(self):
        if self.cpu_cores < 0:
            raise ValueError("CPU cores cannot be negative")
        if self.memory_gb < 0:
            raise ValueError("Memory cannot be negative")


@dataclass
class NodeInfo:
    """Information about a cluster node"""
    node_id: str
    hostname: str
    capacity: ResourceCapacity
    status: NodeStatus = NodeStatus.JOINING
    leader: bool = False
    last_heartbeat: Optional[datetime] = None
    joined_at: Optional[datetime] = None
    tasks_running: int = 0
    load_average: float = 0.0

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        if self.last_heartbeat:
            data['last_heartbeat'] = self.last_heartbeat.isoformat()
        if self.joined_at:
            data['joined_at'] = self.joined_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> 'NodeInfo':
        """Create from dictionary"""
        if 'last_heartbeat' in data and data['last_heartbeat']:
            data['last_heartbeat'] = datetime.fromisoformat(data['last_heartbeat'])
        if 'joined_at' in data and data['joined_at']:
            data['joined_at'] = datetime.fromisoformat(data['joined_at'])

        # Convert capacity dict to ResourceCapacity
        if isinstance(data.get('capacity'), dict):
            data['capacity'] = ResourceCapacity(**data['capacity'])

        return cls(**data)


class HeartbeatManager:
    """Manages heartbeat monitoring for cluster nodes"""

    def __init__(self, redis_client: redis.Redis, heartbeat_interval: int = 30):
        self.redis = redis_client
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_interval * 3
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def start_heartbeat(self, node_id: str):
        """Start sending heartbeats for this node"""
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(node_id))
        logger.info(f"Started heartbeat for node {node_id}")

    async def stop_heartbeat(self):
        """Stop sending heartbeats"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped heartbeat")

    async def _heartbeat_loop(self, node_id: str):
        """Main heartbeat loop"""
        while self._running:
            try:
                await self._send_heartbeat(node_id)
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error for {node_id}: {e}")
                await asyncio.sleep(5)  # Retry after short delay

    async def _send_heartbeat(self, node_id: str):
        """Send a heartbeat for this node"""
        heartbeat_data = {
            'node_id': node_id,
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'alive'
        }
        # Store as a single JSON blob with TTL to mirror legacy aioredis usage
        await self.redis.setex(
            f"heartbeat:{node_id}",
            self.heartbeat_timeout,
            json.dumps(heartbeat_data)
        )

    async def is_node_alive(self, node_id: str) -> bool:
        """Return True if a recent heartbeat exists for node_id."""
        heartbeat_raw = await self.redis.get(f"heartbeat:{node_id}")
        if not heartbeat_raw:
            return False
        try:
            data = json.loads(heartbeat_raw)
            timestamp = datetime.fromisoformat(data.get("timestamp"))
            return (datetime.utcnow() - timestamp).total_seconds() < self.heartbeat_timeout
        except Exception:
            return False

    async def check_node_health(self, node_id: str) -> bool:
        """Alias maintained for existing callers."""
        return await self.is_node_alive(node_id)


class RaftConsensus:
    """Simplified Raft consensus implementation for leader election"""

    def __init__(self, redis_client: redis.Redis, node_id: str):
        self.redis = redis_client
        self.node_id = node_id
        self.current_term = 0
        self.voted_for: Optional[str] = None
        self.leader_id: Optional[str] = None
        self.election_timeout = 5.0  # seconds
        self.heartbeat_interval = 1.0  # seconds

    async def start_election(self) -> bool:
        """Start a new leader election"""
        self.current_term += 1
        self.voted_for = self.node_id

        logger.info(f"Starting election for term {self.current_term}")

        # Vote for ourselves
        votes = 1

        # Get all active nodes
        nodes = await self._get_active_nodes()

        # Request votes from other nodes
        vote_tasks = []
        for node_id in nodes:
            if node_id != self.node_id:
                task = asyncio.create_task(self._request_vote(node_id))
                vote_tasks.append(task)

        # Wait for vote responses with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*vote_tasks, return_exceptions=True),
                timeout=self.election_timeout
            )

            for result in results:
                if isinstance(result, bool) and result:
                    votes += 1

        except asyncio.TimeoutError:
            logger.warning("Election timeout reached")

        # Need majority to become leader
        majority = len(nodes) // 2 + 1

        if votes >= majority:
            await self._become_leader()
            return True
        else:
            logger.info(f"Election failed: {votes}/{len(nodes)} votes")
            return False

    async def _request_vote(self, candidate_node: str) -> bool:
        """Request vote from another node"""
        try:
            # In a real implementation, this would be an RPC call
            # For now, we simulate with Redis-based voting
            vote_key = f"vote:{self.current_term}:{candidate_node}"

            # Check if node already voted in this term
            existing_vote = await self.redis.get(vote_key)
            if existing_vote:
                return False

            # Cast vote (simplified - in real Raft this would check log consistency)
            await self.redis.setex(vote_key, 10, self.node_id)
            return True

        except Exception as e:
            logger.error(f"Error requesting vote from {candidate_node}: {e}")
            return False

    async def _become_leader(self):
        """Become the cluster leader"""
        self.leader_id = self.node_id

        # Announce leadership
        await self.redis.setex(
            "cluster:leader",
            30,  # Leader lease duration
            json.dumps({
                'node_id': self.node_id,
                'term': self.current_term,
                'elected_at': datetime.utcnow().isoformat()
            })
        )

        logger.info(f"Became leader for term {self.current_term}")

    async def _get_active_nodes(self) -> List[str]:
        """Get list of active nodes in cluster"""
        nodes = []
        node_pattern = "node:*"

        async for key in self.redis.scan_iter(match=node_pattern):
            node_data = await self.redis.hgetall(key)
            if node_data and node_data.get(b'status') == b'active':
                nodes.append(node_data[b'node_id'].decode())

        return nodes


class DistributedCoordinator:
    """Main coordinator for distributed agent cluster"""

    def __init__(self,
                 node_id: str,
                 redis_client: redis.Redis,
                 heartbeat_interval: int = 30):
        self.node_id = node_id
        self.cluster_id = "brain_researcher_cluster"
        self.redis = redis_client
        self.nodes: Dict[str, NodeInfo] = {}
        self.leader_node: Optional[str] = None
        self.leader_id: Optional[str] = None
        self._is_leader = False
        self.is_running: bool = False
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Components
        self.heartbeat_manager = HeartbeatManager(redis_client, heartbeat_interval)
        self.consensus = RaftConsensus(redis_client, node_id)

        # State
        self._running = False
        self._coordination_task: Optional[asyncio.Task] = None

        logger.info(f"Initialized coordinator for node {node_id}")

    async def start(self):
        """Start the coordinator"""
        self._running = True
        self.is_running = True

        # Start heartbeat
        await self.heartbeat_manager.start_heartbeat(self.node_id)
        self._heartbeat_task = self.heartbeat_manager._heartbeat_task

        # Start coordination loop
        self._coordination_task = asyncio.create_task(self._coordination_loop())

        # Register this node
        await self._register_self()

        logger.info("Coordinator started")

    async def stop(self):
        """Stop the coordinator"""
        self._running = False
        self.is_running = False

        # Stop heartbeat
        await self.heartbeat_manager.stop_heartbeat()

        # Stop coordination loop
        if self._coordination_task:
            self._coordination_task.cancel()
            try:
                await self._coordination_task
            except asyncio.CancelledError:
                pass

        # Deregister node
        await self._deregister_self()

        logger.info("Coordinator stopped")

    async def register_node(self, node_info: NodeInfo) -> bool:
        """Register a new node in the cluster"""
        try:
            # Validate node info
            if not node_info.node_id or not node_info.hostname:
                raise ValueError("Node ID and hostname are required")

            # Set registration timestamp
            node_info.joined_at = datetime.utcnow()
            node_info.status = NodeStatus.ACTIVE

            # Store in Redis
            await self.redis.hset(
                f"node:{node_info.node_id}",
                mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        for k, v in node_info.to_dict().items()}
            )

            # Update local cache
            self.nodes[node_info.node_id] = node_info

            # Trigger rebalancing if we're the leader
            if self._is_leader:
                await self._trigger_rebalance()

            logger.info(f"Registered node {node_info.node_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to register node {node_info.node_id}: {e}")
            return False

    async def deregister_node(self, node_id: str) -> bool:
        """Deregister a node from the cluster"""
        try:
            # Remove from Redis (keep hdel for legacy expectations)
            await self.redis.hdel(f"node:{node_id}", "node_id", "hostname", "capacity",
                                  "status", "leader", "last_heartbeat", "joined_at",
                                  "tasks_running", "load_average")
            await self.redis.delete(f"node:{node_id}")
            await self.redis.delete(f"heartbeat:{node_id}")

            # Remove from local cache
            if node_id in self.nodes:
                del self.nodes[node_id]

            # If the leader left, trigger new election
            if node_id == self.leader_node:
                self.leader_node = None
                self._is_leader = False
                await self.elect_leader()

            logger.info(f"Deregistered node {node_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to deregister node {node_id}: {e}")
            return False

    async def elect_leader(self) -> Optional[str]:
        """Elect a new cluster leader"""
        try:
            leader_key = "cluster:leader"
            # Attempt to acquire leader lock
            if await self.redis.setnx(leader_key, self.node_id):
                # Set short lease
                await self.redis.setex(
                    leader_key,
                    30,
                    json.dumps({
                        "node_id": self.node_id,
                        "elected_at": datetime.utcnow().isoformat()
                    })
                )
                self.leader_node = self.node_id
                self.leader_id = self.node_id
                self._is_leader = True
                return self.node_id

            # Another leader exists; read it
            leader_data = await self.redis.get(leader_key)
            if leader_data:
                try:
                    leader_info = json.loads(leader_data)
                    leader_id = leader_info.get("node_id") or leader_data
                except Exception:
                    leader_id = leader_data.decode() if isinstance(leader_data, (bytes, bytearray)) else leader_data
                self.leader_node = leader_id
                self.leader_id = leader_id
                self._is_leader = (leader_id == self.node_id)
                return leader_id
            return None

        except Exception as e:
            logger.error(f"Leader election failed: {e}")
            return None

    async def get_cluster_status(self) -> Dict:
        """Get current cluster status"""
        # Update node information
        await self._update_node_cache()

        total_capacity = ResourceCapacity(0, 0.0)
        active_nodes = 0
        failed_nodes = 0
        total_tasks = 0

        for node in self.nodes.values():
            if node.status == NodeStatus.ACTIVE:
                active_nodes += 1
                total_capacity.cpu_cores += node.capacity.cpu_cores
                total_capacity.memory_gb += node.capacity.memory_gb
                total_capacity.gpu_count += node.capacity.gpu_count
                total_capacity.storage_gb += node.capacity.storage_gb
                total_tasks += node.tasks_running
            elif node.status == NodeStatus.FAILED:
                failed_nodes += 1

        return {
            'nodes': [node.to_dict() for node in self.nodes.values()],
            'leader_id': self.leader_node,
            'partition_detected': False,  # TODO: Implement partition detection
            'total_capacity': asdict(total_capacity),
            'active_tasks': total_tasks,
            'cluster_health': {
                'active_nodes': active_nodes,
                'failed_nodes': failed_nodes,
                'total_nodes': len(self.nodes)
            }
        }

    async def handle_split_brain(self) -> bool:
        """Handle split-brain scenarios"""
        try:
            # Check if multiple leaders exist
            leaders = []

            async for key in self.redis.scan_iter(match="leader:*"):
                leader_data = await self.redis.get(key)
                if leader_data:
                    leaders.append(json.loads(leader_data))

            if len(leaders) > 1:
                logger.warning("Split-brain detected - multiple leaders")

                # Choose leader with highest term
                chosen_leader = max(leaders, key=lambda x: x.get('term', 0))

                # Remove other leader entries
                for leader in leaders:
                    if leader['node_id'] != chosen_leader['node_id']:
                        await self.redis.delete(f"leader:{leader['node_id']}")

                # Update our state
                self.leader_node = chosen_leader['node_id']
                self.is_leader = (chosen_leader['node_id'] == self.node_id)

                logger.info(f"Resolved split-brain, leader: {self.leader_node}")
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to handle split-brain: {e}")
            return False

    async def _coordination_loop(self):
        """Main coordination loop"""
        while self._running:
            try:
                # Update node cache
                await self._update_node_cache()

                # Check for failed nodes
                await self._check_node_health()

                # Elect leader if needed
                if not self.leader_node:
                    await self.elect_leader()

                # Leader duties
                if self.is_leader:
                    await self._leader_duties()

                # Check for split-brain
                await self.handle_split_brain()

                await asyncio.sleep(10)  # Coordination interval

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Coordination loop error: {e}")
                await asyncio.sleep(5)

    async def _register_self(self):
        """Register this node with the cluster"""
        node_info = NodeInfo(
            node_id=self.node_id,
            hostname="localhost",  # TODO: Get actual hostname
            capacity=ResourceCapacity(cpu_cores=4, memory_gb=8.0),  # TODO: Get actual capacity
            status=NodeStatus.ACTIVE
        )

        await self.register_node(node_info)

    async def _deregister_self(self):
        """Deregister this node from the cluster"""
        await self.deregister_node(self.node_id)

    async def _update_node_cache(self):
        """Update local node cache from Redis"""
        try:
            nodes = {}

            async for key in self.redis.scan_iter(match="node:*"):
                node_data = await self.redis.hgetall(key)
                if node_data:
                    # Convert bytes to strings and parse JSON
                    parsed_data = {}
                    for k, v in node_data.items():
                        key_str = k.decode() if isinstance(k, bytes) else k
                        val_str = v.decode() if isinstance(v, bytes) else v

                        try:
                            parsed_data[key_str] = json.loads(val_str)
                        except json.JSONDecodeError:
                            parsed_data[key_str] = val_str

                    node_info = NodeInfo.from_dict(parsed_data)
                    nodes[node_info.node_id] = node_info

            # If Redis had entries use them, otherwise keep existing cache
            if nodes:
                self.nodes = nodes

        except Exception as e:
            logger.error(f"Failed to update node cache: {e}")

    async def _check_node_health(self):
        """Check health of all nodes"""
        for node_id, node in list(self.nodes.items()):
            if not await self.heartbeat_manager.check_node_health(node_id):
                logger.warning(f"Node {node_id} appears unhealthy")
                node.status = NodeStatus.FAILED

                # Update in Redis
                await self.redis.hset(
                    f"node:{node_id}",
                    "status",
                    NodeStatus.FAILED.value
                )

    async def _leader_duties(self):
        """Perform leader-specific duties"""
        try:
            # Maintain leader lease
            await self.redis.setex(
                "cluster:leader",
                30,
                json.dumps({
                    'node_id': self.node_id,
                    'term': self.consensus.current_term,
                    'elected_at': datetime.utcnow().isoformat()
                })
            )

            # Other leader duties can be added here
            # - Resource allocation
            # - Task distribution
            # - Cluster optimization

        except Exception as e:
            logger.error(f"Leader duties error: {e}")

    def is_leader(self) -> bool:
        """Return True if this coordinator is the current leader."""
        return self._is_leader

    def calculate_quorum(self) -> int:
        """Compute majority quorum size based on current node count."""
        total_nodes = max(len(self.nodes), 1)
        return total_nodes // 2 + 1

    async def reach_consensus(self, proposal: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        """
        Simplified consensus: gather yes/no votes from all nodes via Redis keys
        and return majority decision.
        """
        votes_for = 0
        votes_against = 0
        for node_id in self.nodes.keys():
            try:
                vote_raw = await self.redis.get(f"vote:{proposal.get('action','proposal')}:{node_id}")
            except Exception:
                vote_raw = None
            # allow injected side_effects in tests regardless of key
            if vote_raw is None:
                continue
            vote_val = vote_raw.decode() if isinstance(vote_raw, (bytes, bytearray)) else vote_raw
            if str(vote_val).lower() == "yes":
                votes_for += 1
            else:
                votes_against += 1
        consensus_reached = votes_for >= self.calculate_quorum()
        return {
            "consensus_reached": consensus_reached,
            "votes_for": votes_for,
            "votes_against": votes_against,
            "proposal": proposal
        }

    async def detect_partition(self) -> bool:
        """Detect partition by checking recent heartbeats; returns True if any node missing."""
        for node_id in self.nodes.keys():
            if not await self.heartbeat_manager.check_node_health(node_id):
                return True
        return False

    async def get_cluster_health(self) -> Dict[str, Any]:
        """Summarize cluster health based on node statuses."""
        total_nodes = len(self.nodes)
        healthy_nodes = sum(1 for n in self.nodes.values() if n.status == NodeStatus.ACTIVE)
        failed_nodes = sum(1 for n in self.nodes.values() if n.status == NodeStatus.FAILED)
        health_ratio = healthy_nodes / total_nodes if total_nodes else 0
        if health_ratio == 1:
            overall = "healthy"
        elif health_ratio > 0:
            overall = "degraded"
        else:
            overall = "unhealthy"
        return {
            "total_nodes": total_nodes,
            "healthy_nodes": healthy_nodes,
            "failed_nodes": failed_nodes,
            "health_ratio": health_ratio,
            "overall_health": overall
        }

    async def _trigger_rebalance(self):
        """Trigger cluster rebalancing"""
        try:
            # Publish rebalance event
            await self.redis.publish(
                "cluster:events",
                json.dumps({
                    'type': 'rebalance_requested',
                    'timestamp': datetime.utcnow().isoformat(),
                    'leader': self.node_id
                })
            )

            logger.info("Triggered cluster rebalancing")

        except Exception as e:
            logger.error(f"Failed to trigger rebalance: {e}")
