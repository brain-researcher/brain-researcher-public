"""
Tool name mapper with fuzzy matching and validation.

Maps query intents and tool names to registered tools with safety guards.
"""

import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import yaml

from brain_researcher.config.paths import resolve_from_config

logger = logging.getLogger(__name__)

# Canonical tool mappings location.
MAPPINGS_FILE = resolve_from_config("catalog", "tool_mappings.yaml")


class ToolMapper:
    """
    Maps tool requests to registered tool names with validation.
    
    Provides:
    - Exact name matching
    - Alias resolution
    - Fuzzy matching with threshold
    - Whitelist/denylist enforcement
    - Logging of all remappings
    """
    
    def __init__(self, registry=None):
        """
        Initialize tool mapper.
        
        Args:
            registry: Tool registry to validate against
        """
        self.registry = registry
        self.mappings = self._load_mappings()
        self.fuzzy_threshold = self.mappings.get("settings", {}).get("fuzzy_threshold", 0.8)
        
        # Build reverse alias map for fast lookup
        self.alias_to_tool = {}
        for category in self.mappings:
            if category == "settings":
                continue
            for tool_name, config in self.mappings[category].items():
                for alias in config.get("aliases", []):
                    self.alias_to_tool[alias] = tool_name
        
        logger.info(f"ToolMapper initialized with {len(self.alias_to_tool)} aliases")
    
    def _load_mappings(self) -> Dict[str, Any]:
        """Load tool mappings from YAML file."""
        if MAPPINGS_FILE.exists():
            with open(MAPPINGS_FILE) as f:
                return yaml.safe_load(f)
        else:
            logger.warning(f"Tool mappings file not found: {MAPPINGS_FILE}")
            return {"settings": {"fuzzy_threshold": 0.8}}
    
    def map_tool_name(
        self,
        requested_name: str,
        whitelist: Optional[List[str]] = None,
        denylist: Optional[List[str]] = None,
        trace_id: Optional[str] = None
    ) -> Tuple[Optional[str], str]:
        """
        Map requested tool name to registered tool name.
        
        Args:
            requested_name: Name requested by LLM or user
            whitelist: Optional list of allowed tools
            denylist: Optional list of forbidden tools
            trace_id: Trace ID for logging
            
        Returns:
            Tuple of (mapped_name, mapping_type) where mapping_type is:
            - "exact": Direct match
            - "alias": Matched via alias
            - "fuzzy": Fuzzy match
            - None: No match found
        """
        logger.info(f"[{trace_id}] Mapping tool: {requested_name}")
        
        # Get all registered tool names if registry available
        registered_names = []
        if self.registry:
            registered_names = [t.get_tool_name() for t in self.registry.get_all_tools()]
        
        # 1. Exact match
        if requested_name in registered_names:
            if self._check_constraints(requested_name, whitelist, denylist, trace_id):
                logger.info(f"[{trace_id}] Exact match: {requested_name}")
                return requested_name, "exact"
            else:
                logger.warning(f"[{trace_id}] Tool {requested_name} blocked by constraints")
                return None, "blocked"
        
        # 2. Alias match
        if requested_name in self.alias_to_tool:
            mapped_name = self.alias_to_tool[requested_name]
            if mapped_name in registered_names:
                if self._check_constraints(mapped_name, whitelist, denylist, trace_id):
                    logger.info(f"[{trace_id}] Alias match: {requested_name} -> {mapped_name}")
                    return mapped_name, "alias"
                else:
                    logger.warning(f"[{trace_id}] Tool {mapped_name} blocked by constraints")
                    return None, "blocked"
            # If alias maps to an unregistered tool, try any registered tool sharing the alias.
            fallback = self._resolve_registered_alias(requested_name, registered_names)
            if fallback:
                if self._check_constraints(fallback, whitelist, denylist, trace_id):
                    logger.info(f"[{trace_id}] Alias fallback: {requested_name} -> {fallback}")
                    return fallback, "alias"
                logger.warning(f"[{trace_id}] Tool {fallback} blocked by constraints")
                return None, "blocked"
        
        # 3. Substring match
        for registered in registered_names:
            if requested_name.lower() in registered.lower() or registered.lower() in requested_name.lower():
                if self._check_constraints(registered, whitelist, denylist, trace_id):
                    logger.info(f"[{trace_id}] Substring match: {requested_name} -> {registered}")
                    return registered, "substring"
        
        # 4. Fuzzy match (with threshold)
        best_match, best_score = self._fuzzy_match(requested_name, registered_names)
        if best_match and best_score >= self.fuzzy_threshold:
            if self._check_constraints(best_match, whitelist, denylist, trace_id):
                logger.info(f"[{trace_id}] Fuzzy match (score={best_score:.2f}): {requested_name} -> {best_match}")
                return best_match, "fuzzy"
            else:
                logger.warning(f"[{trace_id}] Tool {best_match} blocked by constraints")
                return None, "blocked"
        
        # No match found
        logger.warning(f"[{trace_id}] No match found for: {requested_name}")
        return None, "not_found"
    
    def _fuzzy_match(self, requested: str, candidates: List[str]) -> Tuple[Optional[str], float]:
        """
        Find best fuzzy match for requested name.
        
        Returns:
            Tuple of (best_match, score) where score is 0-1
        """
        if not candidates:
            return None, 0.0
        
        best_match = None
        best_score = 0.0
        
        for candidate in candidates:
            # Use SequenceMatcher for fuzzy matching
            score = SequenceMatcher(None, requested.lower(), candidate.lower()).ratio()
            
            # Also check for word overlap
            def _normalize_words(value: str) -> set[str]:
                words = value.lower().replace("_", " ").split()
                normalized = set()
                for w in words:
                    if w.endswith("s") and len(w) > 3:
                        normalized.add(w[:-1])
                    normalized.add(w)
                return normalized

            requested_words = _normalize_words(requested)
            candidate_words = _normalize_words(candidate)
            word_overlap = len(requested_words & candidate_words) / max(len(requested_words), 1)
            
            # Combined score
            combined_score = max(score, word_overlap)
            
            if combined_score > best_score:
                best_score = combined_score
                best_match = candidate
        
        return best_match, best_score
    
    def _check_constraints(
        self,
        tool_name: str,
        whitelist: Optional[List[str]],
        denylist: Optional[List[str]],
        trace_id: Optional[str]
    ) -> bool:
        """
        Check if tool passes whitelist/denylist constraints.
        
        Returns:
            True if tool is allowed, False otherwise
        """
        # Check denylist first
        if denylist and tool_name in denylist:
            logger.info(f"[{trace_id}] Tool {tool_name} in denylist")
            return False
        
        # Check whitelist
        if whitelist and tool_name not in whitelist:
            logger.info(f"[{trace_id}] Tool {tool_name} not in whitelist: {whitelist}")
            return False
        
        return True

    def _resolve_registered_alias(
        self, alias: str, registered_names: List[str]
    ) -> Optional[str]:
        """Find a registered tool that declares the requested alias."""
        if not registered_names:
            return None
        for category, tools in self.mappings.items():
            if category == "settings" or not isinstance(tools, dict):
                continue
            for tool_name, config in tools.items():
                if tool_name not in registered_names:
                    continue
                aliases = config.get("aliases", []) if isinstance(config, dict) else []
                if alias in aliases:
                    return tool_name
        return None
    
    def get_tool_config(self, tool_name: str) -> Dict[str, Any]:
        """
        Get configuration for a tool.
        
        Returns:
            Tool configuration including adapter hints
        """
        for category in self.mappings:
            if category == "settings":
                continue
            if tool_name in self.mappings[category]:
                return self.mappings[category][tool_name]
        
        return {}
    
    def suggest_tools_for_query(self, query: str) -> List[str]:
        """
        Suggest tools based on query keywords.
        
        Args:
            query: User query
            
        Returns:
            List of suggested tool names
        """
        suggestions = []
        query_lower = query.lower()
        
        # Check example queries
        for category in self.mappings:
            if category == "settings":
                continue
            for tool_name, config in self.mappings[category].items():
                for example in config.get("example_queries", []):
                    if any(word in query_lower for word in example.lower().split()):
                        suggestions.append(tool_name)
                        break
        
        # Check tool names and aliases
        for alias, tool_name in self.alias_to_tool.items():
            if alias in query_lower or any(word in query_lower for word in alias.split("_")):
                if tool_name not in suggestions:
                    suggestions.append(tool_name)
        
        return suggestions[:5]  # Return top 5 suggestions


# Singleton instance
_mapper_instance = None


def get_tool_mapper(registry=None) -> ToolMapper:
    """Get or create singleton ToolMapper instance."""
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = ToolMapper(registry)
    return _mapper_instance
