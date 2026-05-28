"""
Memory Selector for choosing relevant memories and injecting them into prompts.

This module handles:
- Selecting top-K relevant memories based on task context
- Resolving conflicts between memories
- Generating house rules for prompt injection
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .memory_store import MemoryStore, Memory

logger = logging.getLogger(__name__)


@dataclass
class TaskContext:
    """Context information about the current task."""
    
    task_type: str  # e.g., "fmri_analysis", "data_ingestion", "debugging"
    environment: str  # e.g., "hpc", "local", "docker"
    tools: List[str] = None  # e.g., ["fsl", "ants", "nilearn"]
    datasets: List[str] = None  # e.g., ["openneuro", "hcp"]
    description: str = ""
    
    def __post_init__(self):
        if self.tools is None:
            self.tools = []
        if self.datasets is None:
            self.datasets = []


class MemorySelector:
    """Selects and formats relevant memories for prompt injection."""
    
    def __init__(self, memory_store: Optional[MemoryStore] = None):
        """
        Initialize the selector.
        
        Args:
            memory_store: MemoryStore instance, creates new one if None
        """
        self.store = memory_store or MemoryStore()
    
    def select_memories(self,
                        task: str,
                        context: Optional[TaskContext] = None,
                        k: int = 6,
                        min_confidence: float = 0.3) -> List[Memory]:
        """
        Select top-K relevant memories for a task.
        
        Args:
            task: Task description or query
            context: Additional task context
            k: Number of memories to select
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of selected memories
        """
        if not self.store.memories:
            logger.warning("No memories loaded in store")
            return []
        
        # Start with semantic/keyword search
        candidates = self.store.search(
            query=task,
            limit=k * 3,  # Get more candidates for filtering
            min_confidence=min_confidence
        )
        
        # Apply context filters if provided
        if context:
            candidates = self._apply_context_filters(candidates, context)
        
        # Check applicability conditions
        scored_memories = []
        for memory in candidates:
            score = self._score_memory(memory, task, context)
            if score > 0:
                scored_memories.append((score, memory))
        
        # Sort by score and take top K
        scored_memories.sort(key=lambda x: x[0], reverse=True)
        selected = [m for _, m in scored_memories[:k]]
        
        # Resolve conflicts
        selected = self._resolve_conflicts(selected)
        
        logger.info(f"Selected {len(selected)} memories for task: {task[:50]}...")
        return selected
    
    def _apply_context_filters(self, 
                               memories: List[Memory], 
                               context: TaskContext) -> List[Memory]:
        """Filter memories based on task context."""
        filtered = []
        
        for memory in memories:
            # Check scope match
            if context.environment == "hpc" and memory.scope == "ops":
                score_boost = 1.2
            elif context.task_type in ["fmri_analysis", "glm"] and memory.scope == "research":
                score_boost = 1.3
            else:
                score_boost = 1.0
            
            # Check tool relevance
            if context.tools:
                tool_overlap = any(
                    tool.lower() in memory.content.lower() 
                    for tool in context.tools
                )
                if tool_overlap:
                    score_boost *= 1.2
            
            # Check dataset relevance
            if context.datasets:
                dataset_overlap = any(
                    dataset.lower() in memory.content.lower()
                    for dataset in context.datasets
                )
                if dataset_overlap:
                    score_boost *= 1.1
            
            # Apply boost to confidence for filtering
            if score_boost > 1.0:
                filtered.append(memory)
        
        return filtered if filtered else memories
    
    def _score_memory(self,
                     memory: Memory,
                     task: str,
                     context: Optional[TaskContext]) -> float:
        """
        Score a memory's relevance to the current task.
        
        Args:
            memory: Memory to score
            task: Task description
            context: Task context
            
        Returns:
            Relevance score (0-1)
        """
        score = memory.effective_confidence
        
        # Check applies_when conditions
        applies_count = 0
        for condition in memory.applies_when:
            if condition.lower() in task.lower():
                applies_count += 1
            elif context and context.description:
                if condition.lower() in context.description.lower():
                    applies_count += 1
        
        if memory.applies_when and applies_count > 0:
            score *= (1 + applies_count * 0.2)
        
        # Check avoid_when conditions (negative scoring)
        for condition in memory.avoid_when:
            if condition.lower() in task.lower():
                score *= 0.3  # Significantly reduce score
                logger.debug(f"Memory {memory.id} penalized: avoid condition '{condition}' matched")
        
        # Boost for exact tag matches
        if context and context.tools:
            tag_matches = len(set(memory.tags) & set(context.tools))
            score *= (1 + tag_matches * 0.15)
        
        return min(score, 1.0)
    
    def _resolve_conflicts(self, memories: List[Memory]) -> List[Memory]:
        """
        Resolve conflicts between selected memories.
        
        Args:
            memories: List of memories to check for conflicts
            
        Returns:
            Filtered list with conflicts resolved
        """
        resolved = []
        topics_seen = {}
        
        for memory in memories:
            # Extract topic from tags or title
            topic = self._extract_topic(memory)
            
            if topic in topics_seen:
                # Keep the one with higher confidence
                existing = topics_seen[topic]
                if memory.effective_confidence > existing.effective_confidence:
                    # Replace existing with this one
                    resolved = [m for m in resolved if m.id != existing.id]
                    resolved.append(memory)
                    topics_seen[topic] = memory
                    logger.debug(f"Replaced {existing.id} with {memory.id} for topic {topic}")
            else:
                resolved.append(memory)
                topics_seen[topic] = memory
        
        return resolved
    
    def _extract_topic(self, memory: Memory) -> str:
        """Extract main topic from memory for conflict detection."""
        # Use first tag as topic, or extract from title
        if memory.tags:
            return memory.tags[0]
        
        # Extract first significant word from title
        words = memory.title.split()
        for word in words:
            if len(word) > 3 and word.lower() not in ['with', 'from', 'using', 'when']:
                return word.lower()
        
        return memory.id
    
    def format_as_house_rules(self, memories: List[Memory]) -> str:
        """
        Format selected memories as house rules for prompt injection.
        
        Args:
            memories: List of selected memories
            
        Returns:
            Formatted string of house rules
        """
        if not memories:
            return ""
        
        rules = ["[Project Memory - House Rules]"]
        rules.append("The following are established patterns and decisions for this project:")
        rules.append("")
        
        for i, memory in enumerate(memories, 1):
            # Use LLM prompt if available, otherwise use title
            if memory.llm_prompt:
                rule = memory.llm_prompt
            else:
                rule = f"{memory.title}"
                if memory.applies_when:
                    rule += f" (when: {memory.applies_when[0]})"
            
            rules.append(f"{i}. {rule}")
        
        rules.append("")
        rules.append("Apply these rules unless explicitly asked to deviate.")
        
        return "\n".join(rules)
    
    def check_plan_compliance(self, 
                             plan: str, 
                             memories: List[Memory]) -> List[str]:
        """
        Check if a plan violates any house rules.
        
        Args:
            plan: Proposed plan text
            memories: Active memories to check against
            
        Returns:
            List of violation warnings
        """
        violations = []
        
        for memory in memories:
            # Check avoid_when conditions
            for condition in memory.avoid_when:
                if condition.lower() in plan.lower():
                    violations.append(
                        f"Plan may violate rule '{memory.title}': "
                        f"avoid when '{condition}'"
                    )
            
            # Check for missing required patterns
            if memory.applies_when:
                applies = any(
                    cond.lower() in plan.lower() 
                    for cond in memory.applies_when
                )
                if applies and memory.llm_prompt:
                    # Check if the plan follows the rule
                    key_terms = self._extract_key_terms(memory.llm_prompt)
                    missing = [
                        term for term in key_terms 
                        if term.lower() not in plan.lower()
                    ]
                    if missing:
                        violations.append(
                            f"Plan may not follow '{memory.title}': "
                            f"missing key aspects {missing}"
                        )
        
        return violations
    
    def _extract_key_terms(self, prompt: str) -> List[str]:
        """Extract key terms from an LLM prompt."""
        # Simple extraction of capitalized terms and technical words
        import re
        
        # Find technical terms (containing numbers, underscores, or all caps)
        technical = re.findall(r'\b[A-Z][A-Z0-9_]+\b|\b\w+_\w+\b', prompt)
        
        # Find emphasized terms (in quotes or after "use", "prefer", "always")
        emphasized = re.findall(r'(?:use|prefer|always)\s+(\w+)', prompt, re.IGNORECASE)
        
        return list(set(technical + emphasized))
    
    def get_context_from_state(self, state: Dict[str, Any]) -> TaskContext:
        """
        Extract task context from LangGraph agent state.
        
        Args:
            state: Agent state dictionary
            
        Returns:
            TaskContext object
        """
        # Extract from messages
        task_description = ""
        if "messages" in state:
            for msg in state.get("messages", []):
                if hasattr(msg, "content"):
                    task_description += msg.content + " "
        
        # Detect task type from content
        task_type = "general"
        if any(word in task_description.lower() for word in ["fmri", "glm", "preprocessing"]):
            task_type = "fmri_analysis"
        elif any(word in task_description.lower() for word in ["download", "openneuro", "bids"]):
            task_type = "data_ingestion"
        elif any(word in task_description.lower() for word in ["debug", "error", "fix"]):
            task_type = "debugging"
        
        # Detect environment
        environment = "local"
        if any(word in task_description.lower() for word in ["sherlock", "hpc", "slurm"]):
            environment = "hpc"
        elif any(word in task_description.lower() for word in ["docker", "container"]):
            environment = "docker"
        
        # Extract tool mentions
        tools = []
        tool_keywords = ["fsl", "ants", "fmriprep", "nilearn", "spm", "afni", "freesurfer"]
        for tool in tool_keywords:
            if tool in task_description.lower():
                tools.append(tool)
        
        # Extract dataset mentions
        datasets = []
        dataset_keywords = ["openneuro", "hcp", "abide", "adni", "ukbiobank"]
        for dataset in dataset_keywords:
            if dataset in task_description.lower():
                datasets.append(dataset)
        
        return TaskContext(
            task_type=task_type,
            environment=environment,
            tools=tools,
            datasets=datasets,
            description=task_description[:500]  # Limit length
        )