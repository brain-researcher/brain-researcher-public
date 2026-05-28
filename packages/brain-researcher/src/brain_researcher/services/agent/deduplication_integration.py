"""Agent Deduplication Integration.

This module integrates the deduplication system (INGEST-021) with the agent service
to provide data deduplication capabilities in agent tools and workflows.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from brain_researcher.core.ingestion.deduplication.data_deduplication import (
    DataDeduplication,
    DuplicateCandidate,
    MergeDecision,
    MergeStrategy,
    MatchType,
    DeduplicationReport
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper

logger = logging.getLogger(__name__)


@dataclass
class AgentDeduplicationConfig:
    """Configuration for agent deduplication features."""
    
    auto_deduplicate: bool = True
    merge_strategy: MergeStrategy = MergeStrategy.KEEP_HIGHEST_QUALITY
    similarity_threshold: float = 0.85
    enable_fuzzy_matching: bool = True
    enable_semantic_matching: bool = False
    max_candidates: int = 100


class AgentDataDeduplication:
    """Agent-specific data deduplication manager."""
    
    def __init__(self, deduplication_system: DataDeduplication, config: Optional[AgentDeduplicationConfig] = None):
        """Initialize agent deduplication manager.
        
        Args:
            deduplication_system: Core deduplication system
            config: Agent-specific configuration
        """
        self.deduplication = deduplication_system
        self.config = config or AgentDeduplicationConfig()
        
        # Statistics
        self.stats = {
            "tool_calls_deduplicated": 0,
            "duplicates_found": 0,
            "duplicates_merged": 0,
            "processing_time_saved": 0.0
        }
        
        # Cache of recent deduplication decisions
        self.decision_cache: Dict[str, MergeDecision] = {}
        self.cache_max_size = 1000
        
    async def deduplicate_tool_results(
        self,
        tool_name: str,
        results: List[Dict[str, Any]],
        entity_type: str = "result"
    ) -> Tuple[List[Dict[str, Any]], DeduplicationReport]:
        """Deduplicate results from a tool execution.
        
        Args:
            tool_name: Name of the tool
            results: Results to deduplicate
            entity_type: Type of entities in results
            
        Returns:
            (deduplicated_results, report)
        """
        start_time = datetime.now()
        
        if len(results) < 2:
            # No need to deduplicate single result
            empty_report = DeduplicationReport(
                report_id=f"no_dedup_{start_time.strftime('%Y%m%d%H%M%S')}",
                total_entities=len(results),
                duplicates_found=0,
                duplicates_merged=0,
                duplicates_skipped=0,
                conflicts_encountered=0,
                execution_time_ms=0
            )
            return results, empty_report
            
        # Determine match types based on configuration
        match_types = [MatchType.EXACT]
        if self.config.enable_fuzzy_matching:
            match_types.append(MatchType.FUZZY)
        if self.config.enable_semantic_matching:
            match_types.append(MatchType.SEMANTIC)
            
        # Find duplicates
        duplicates = self.deduplication.find_duplicates(
            results, 
            entity_type, 
            match_types
        )
        
        # Filter by similarity threshold
        duplicates = [
            d for d in duplicates 
            if d.similarity_score >= self.config.similarity_threshold
        ]
        
        # Limit number of candidates
        duplicates = duplicates[:self.config.max_candidates]
        
        # Group duplicates for merging
        merge_groups = self._group_duplicates(duplicates, results)
        
        # Perform merges
        merged_results = []
        merge_decisions = []
        
        # Track which entities have been merged
        merged_entities = set()
        
        for group in merge_groups:
            if self.config.auto_deduplicate:
                # Automatic merge
                decision = self.deduplication.merge_entities(
                    group,
                    self.config.merge_strategy
                )
                merge_decisions.append(decision)
                merged_results.append(decision.merged_entity)
                
                # Mark entities as merged
                for entity in group:
                    entity_id = entity.get("id", str(entity))
                    merged_entities.add(entity_id)
            else:
                # Manual review required - keep first entity for now
                merged_results.append(group[0])
                for entity in group[1:]:
                    entity_id = entity.get("id", str(entity))
                    merged_entities.add(entity_id)
                    
        # Add non-duplicate entities
        for result in results:
            result_id = result.get("id", str(result))
            if result_id not in merged_entities:
                merged_results.append(result)
                
        # Generate report
        execution_time = (datetime.now() - start_time).total_seconds() * 1000
        
        report = self.deduplication.generate_report(
            duplicates,
            merge_decisions,
            execution_time,
            len(results)
        )
        
        # Update statistics
        self.stats["tool_calls_deduplicated"] += 1
        self.stats["duplicates_found"] += len(duplicates)
        self.stats["duplicates_merged"] += len(merge_decisions)
        self.stats["processing_time_saved"] += execution_time
        
        # Cache decisions
        for decision in merge_decisions:
            self._cache_decision(decision)
            
        logger.info(
            f"Deduplicated {tool_name} results: "
            f"{len(results)} -> {len(merged_results)} "
            f"({len(duplicates)} duplicates found)"
        )
        
        return merged_results, report
        
    def _group_duplicates(
        self,
        duplicates: List[DuplicateCandidate],
        entities: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """Group duplicate candidates into merge groups.
        
        Args:
            duplicates: List of duplicate candidates
            entities: Original entities
            
        Returns:
            Groups of entities to merge
        """
        # Create entity lookup
        entity_lookup = {}
        for entity in entities:
            entity_id = entity.get("id", str(entity))
            entity_lookup[entity_id] = entity
            
        # Build graph of duplicate relationships
        edges = []
        for dup in duplicates:
            edges.append((dup.entity1_id, dup.entity2_id))
            
        # Find connected components (groups)
        groups = []
        visited = set()
        
        for entity_id in entity_lookup:
            if entity_id in visited:
                continue
                
            # DFS to find connected component
            group = []
            stack = [entity_id]
            
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                    
                visited.add(current)
                if current in entity_lookup:
                    group.append(entity_lookup[current])
                    
                # Find connected entities
                for e1, e2 in edges:
                    if e1 == current and e2 not in visited:
                        stack.append(e2)
                    elif e2 == current and e1 not in visited:
                        stack.append(e1)
                        
            if len(group) > 1:
                groups.append(group)
                
        return groups
        
    def _cache_decision(self, decision: MergeDecision):
        """Cache a merge decision for future reference.
        
        Args:
            decision: Merge decision to cache
        """
        # Manage cache size
        if len(self.decision_cache) >= self.cache_max_size:
            # Remove oldest entry
            oldest_key = min(
                self.decision_cache.keys(),
                key=lambda k: self.decision_cache[k].timestamp
            )
            del self.decision_cache[oldest_key]
            
        self.decision_cache[decision.decision_id] = decision
        
    async def check_query_duplicates(
        self,
        query: str,
        thread_id: str,
        recent_queries: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Check if a query is similar to recent queries in the thread.
        
        Args:
            query: Current query
            thread_id: Thread ID
            recent_queries: Recent queries in the thread
            
        Returns:
            Similar query if found, None otherwise
        """
        if not recent_queries:
            return None
            
        # Create query entities for comparison
        query_entities = []
        
        # Add current query
        current_entity = {
            "id": f"query_{datetime.now().timestamp()}",
            "query": query,
            "thread_id": thread_id,
            "timestamp": datetime.now().isoformat()
        }
        query_entities.append(current_entity)
        
        # Add recent queries
        for i, recent_query in enumerate(recent_queries):
            entity = {
                "id": f"recent_{i}",
                "query": recent_query.get("query", ""),
                "thread_id": thread_id,
                "timestamp": recent_query.get("timestamp", "")
            }
            query_entities.append(entity)
            
        # Find duplicates
        try:
            duplicates = self.deduplication.find_duplicates(
                query_entities,
                "query",
                [MatchType.FUZZY]
            )
            
            # Look for matches to current query
            for dup in duplicates:
                if (dup.entity1_id == current_entity["id"] or 
                    dup.entity2_id == current_entity["id"]):
                    if dup.similarity_score >= 0.9:  # High threshold for queries
                        # Find the matching recent query
                        match_id = (dup.entity2_id if dup.entity1_id == current_entity["id"] 
                                   else dup.entity1_id)
                        
                        for recent_query in recent_queries:
                            if f"recent_{recent_queries.index(recent_query)}" == match_id:
                                logger.info(f"Found similar query in thread {thread_id}")
                                return recent_query
                                
        except Exception as e:
            logger.error(f"Error checking query duplicates: {e}")
            
        return None
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get deduplication statistics."""
        return self.stats.copy()
        
    def get_recent_decisions(self, limit: int = 10) -> List[MergeDecision]:
        """Get recent merge decisions.
        
        Args:
            limit: Maximum number of decisions to return
            
        Returns:
            Recent merge decisions
        """
        decisions = list(self.decision_cache.values())
        decisions.sort(key=lambda d: d.timestamp, reverse=True)
        return decisions[:limit]


class DeduplicatedToolWrapper(NeuroToolWrapper):
    """Wrapper that adds deduplication to tool results."""
    
    def __init__(self, original_tool: NeuroToolWrapper, dedup_manager: AgentDataDeduplication):
        """Initialize wrapper.
        
        Args:
            original_tool: Original tool to wrap
            dedup_manager: Deduplication manager
        """
        self.original_tool = original_tool
        self.dedup_manager = dedup_manager
        
    def get_tool_name(self) -> str:
        """Get tool name."""
        return f"dedup_{self.original_tool.get_tool_name()}"
        
    def get_tool_description(self) -> str:
        """Get tool description."""
        return f"Deduplicated version of {self.original_tool.get_tool_description()}"
        
    async def run(self, *args, **kwargs) -> Any:
        """Run tool with deduplication."""
        # Execute original tool
        result = await asyncio.to_thread(self.original_tool.run, *args, **kwargs)
        
        # Only deduplicate if result is a list of dictionaries
        if isinstance(result, list) and result and isinstance(result[0], dict):
            deduplicated_result, report = await self.dedup_manager.deduplicate_tool_results(
                self.original_tool.get_tool_name(),
                result
            )
            
            # Attach deduplication report to result
            if hasattr(deduplicated_result, "__dict__"):
                deduplicated_result.__dict__["deduplication_report"] = report
            
            return deduplicated_result
        else:
            return result
            
    def as_langchain_tool(self):
        """Convert to LangChain tool."""
        return self.original_tool.as_langchain_tool()


# Integration helper functions
async def setup_agent_deduplication(
    agent_state_machine,
    neo4j_driver=None,
    redis_client=None,
    config: Optional[AgentDeduplicationConfig] = None
) -> AgentDataDeduplication:
    """Set up agent deduplication integration.
    
    Args:
        agent_state_machine: Core agent state machine
        neo4j_driver: Optional Neo4j driver
        redis_client: Optional Redis client
        config: Optional configuration
        
    Returns:
        Agent deduplication manager
    """
    # Create core deduplication system
    core_dedup = DataDeduplication(neo4j_driver, redis_client)
    
    # Create agent deduplication manager
    agent_dedup = AgentDataDeduplication(core_dedup, config)
    
    # Add to state machine
    agent_state_machine.deduplication_manager = agent_dedup
    
    logger.info("Agent deduplication integration setup completed")
    
    return agent_dedup


def wrap_tools_for_deduplication(
    tool_registry,
    dedup_manager: AgentDataDeduplication,
    tool_names: Optional[List[str]] = None
):
    """Wrap specified tools with deduplication.
    
    Args:
        tool_registry: Tool registry to modify
        dedup_manager: Deduplication manager
        tool_names: Optional list of tool names to wrap (wraps all if None)
    """
    tools_to_wrap = tool_names or list(tool_registry.tools.keys())
    
    for tool_name in tools_to_wrap:
        if tool_name in tool_registry.tools:
            original_tool = tool_registry.tools[tool_name]
            wrapped_tool = DeduplicatedToolWrapper(original_tool, dedup_manager)
            
            # Replace in registry
            tool_registry.tools[f"dedup_{tool_name}"] = wrapped_tool
            
            logger.debug(f"Wrapped tool {tool_name} with deduplication")
            
    logger.info(f"Wrapped {len(tools_to_wrap)} tools with deduplication")


# Query deduplication middleware
class QueryDeduplicationMiddleware:
    """Middleware to check for duplicate queries in agent conversations."""
    
    def __init__(self, dedup_manager: AgentDataDeduplication, redis_client=None):
        """Initialize middleware.
        
        Args:
            dedup_manager: Deduplication manager
            redis_client: Optional Redis client for query history
        """
        self.dedup_manager = dedup_manager
        self.redis = redis_client
        
    async def check_query(
        self,
        query: str,
        thread_id: str,
        max_recent: int = 10
    ) -> Optional[Dict[str, Any]]:
        """Check if query is similar to recent queries.
        
        Args:
            query: Query to check
            thread_id: Thread ID
            max_recent: Maximum recent queries to check
            
        Returns:
            Similar query data if found
        """
        # Get recent queries from Redis or memory
        recent_queries = await self._get_recent_queries(thread_id, max_recent)
        
        # Check for duplicates
        similar_query = await self.dedup_manager.check_query_duplicates(
            query, thread_id, recent_queries
        )
        
        # Store current query for future checks
        await self._store_query(query, thread_id)
        
        return similar_query
        
    async def _get_recent_queries(self, thread_id: str, limit: int) -> List[Dict[str, Any]]:
        """Get recent queries for a thread."""
        if not self.redis:
            return []
            
        try:
            key = f"agent:queries:{thread_id}"
            raw_queries = await self.redis.lrange(key, 0, limit - 1)
            
            queries = []
            for raw in raw_queries:
                try:
                    query_data = json.loads(raw)
                    queries.append(query_data)
                except json.JSONDecodeError:
                    continue
                    
            return queries
            
        except Exception as e:
            logger.error(f"Error retrieving recent queries: {e}")
            return []
            
    async def _store_query(self, query: str, thread_id: str):
        """Store query for future duplicate checking."""
        if not self.redis:
            return
            
        try:
            key = f"agent:queries:{thread_id}"
            query_data = {
                "query": query,
                "timestamp": datetime.now().isoformat(),
                "thread_id": thread_id
            }
            
            await self.redis.lpush(key, json.dumps(query_data))
            await self.redis.ltrim(key, 0, 49)  # Keep only 50 recent queries
            await self.redis.expire(key, 86400)  # 24 hour TTL
            
        except Exception as e:
            logger.error(f"Error storing query: {e}")
