"""
Advanced Error Recovery System with Checkpoint/Restart and Intelligent Fallback

This module implements sophisticated error recovery mechanisms including:
- Automatic checkpoint/restart for long-running workflows
- Intelligent fallback tool selection
- Execution rollback capabilities
- Context-aware error analysis and recovery strategies
"""

import asyncio
import json
import logging
import pickle
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from uuid import uuid4

import redis
from fakeredis import FakeRedis

from brain_researcher.services.agent.error_handling import (
    ErrorHandler, ErrorCategory, ErrorSeverity, AgentError
)
from brain_researcher.services.agent.checkpoint_manager import CheckpointManager, ExecutionState
from brain_researcher.services.tools.enhanced_registry import EnhancedToolRegistry

logger = logging.getLogger(__name__)


class RecoveryStrategy(Enum):
    """Recovery strategy types."""
    RETRY_SAME_TOOL = "retry_same_tool"
    FALLBACK_TOOL = "fallback_tool"
    PARAMETER_ADJUSTMENT = "parameter_adjustment"
    ROLLBACK_CHECKPOINT = "rollback_checkpoint"
    SKIP_STEP = "skip_step"
    REQUEST_CLARIFICATION = "request_clarification"
    ABORT_WORKFLOW = "abort_workflow"


class ErrorPattern(Enum):
    """Common error patterns in neuroimaging workflows."""
    MEMORY_EXHAUSTION = "memory_exhaustion"
    TIMEOUT = "timeout"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    INVALID_PARAMETERS = "invalid_parameters"
    TOOL_UNAVAILABLE = "tool_unavailable"
    DATA_CORRUPTION = "data_corruption"
    NETWORK_ERROR = "network_error"
    DEPENDENCY_MISSING = "dependency_missing"
    EMPTY_RESULT = "empty_result"


@dataclass
class RecoveryAction:
    """Single recovery action definition."""
    action_id: str
    strategy: RecoveryStrategy
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    success_probability: float = 0.5
    estimated_cost: float = 1.0  # Relative cost (time/resources)
    prerequisites: List[str] = field(default_factory=list)


@dataclass
class RecoveryPlan:
    """Complete recovery plan with multiple actions."""
    plan_id: str
    error_context: Dict[str, Any]
    actions: List[RecoveryAction] = field(default_factory=list)
    fallback_actions: List[RecoveryAction] = field(default_factory=list)
    estimated_recovery_time: float = 0.0
    confidence_score: float = 0.0


@dataclass
class ExecutionCheckpoint:
    """Enhanced execution checkpoint with recovery context."""
    checkpoint_id: str
    execution_id: str
    timestamp: float
    step_index: int
    completed_steps: Set[str]
    step_results: Dict[str, Any]
    execution_context: Dict[str, Any]
    tool_states: Dict[str, Any] = field(default_factory=dict)
    resource_usage: Dict[str, Any] = field(default_factory=dict)
    recovery_metadata: Dict[str, Any] = field(default_factory=dict)


class ErrorPatternAnalyzer:
    """Analyzes error patterns and suggests recovery strategies."""
    
    def __init__(self):
        """Initialize error pattern analyzer."""
        self.error_patterns = self._initialize_error_patterns()
        self.recovery_history: Dict[str, List[Dict[str, Any]]] = {}
        
        logger.info("Error pattern analyzer initialized")
    
    def _initialize_error_patterns(self) -> Dict[ErrorPattern, Dict[str, Any]]:
        """Initialize known error patterns and their characteristics."""
        patterns = {
            ErrorPattern.MEMORY_EXHAUSTION: {
                "keywords": ["memory", "out of memory", "oom", "ram", "malloc"],
                "typical_tools": ["fmriprep", "freesurfer", "ants"],
                "recovery_strategies": [
                    RecoveryStrategy.PARAMETER_ADJUSTMENT,
                    RecoveryStrategy.FALLBACK_TOOL,
                    RecoveryStrategy.ROLLBACK_CHECKPOINT
                ],
                "parameter_adjustments": {
                    "n_jobs": lambda x: max(1, x // 2),
                    "memory_gb": lambda x: max(4, x * 0.8),
                    "low_mem": lambda x: True
                }
            },
            
            ErrorPattern.TIMEOUT: {
                "keywords": ["timeout", "time limit", "exceeded", "hung", "stuck"],
                "typical_tools": ["connectivity", "glm", "registration"],
                "recovery_strategies": [
                    RecoveryStrategy.RETRY_SAME_TOOL,
                    RecoveryStrategy.PARAMETER_ADJUSTMENT,
                    RecoveryStrategy.FALLBACK_TOOL
                ],
                "parameter_adjustments": {
                    "timeout": lambda x: x * 2 if x else 3600,
                    "max_iter": lambda x: x * 2 if x else 1000
                }
            },
            
            ErrorPattern.FILE_NOT_FOUND: {
                "keywords": ["file not found", "no such file", "missing file", "cannot find"],
                "typical_tools": ["all"],
                "recovery_strategies": [
                    RecoveryStrategy.PARAMETER_ADJUSTMENT,
                    RecoveryStrategy.ROLLBACK_CHECKPOINT,
                    RecoveryStrategy.SKIP_STEP
                ],
                "parameter_adjustments": {
                    "input_file": "check_file_existence",
                    "mask": "use_default_mask",
                    "template": "use_default_template"
                }
            },
            
            ErrorPattern.INVALID_PARAMETERS: {
                "keywords": ["invalid", "parameter", "argument", "value error", "type error"],
                "typical_tools": ["all"],
                "recovery_strategies": [
                    RecoveryStrategy.PARAMETER_ADJUSTMENT,
                    RecoveryStrategy.FALLBACK_TOOL,
                    RecoveryStrategy.REQUEST_CLARIFICATION,
                ],
                "parameter_adjustments": {
                    "threshold": lambda x: 0.05 if x is None else max(0.001, min(0.1, x)),
                    "fwhm": lambda x: 6.0 if x is None else max(2.0, min(12.0, x))
                }
            },
            
            ErrorPattern.TOOL_UNAVAILABLE: {
                "keywords": ["command not found", "module not found", "import error", "not installed"],
                "typical_tools": ["specialized"],
                "recovery_strategies": [
                    RecoveryStrategy.FALLBACK_TOOL,
                    RecoveryStrategy.SKIP_STEP
                ]
            },
            
            ErrorPattern.DEPENDENCY_MISSING: {
                "keywords": ["dependency", "missing", "required", "not available"],
                "typical_tools": ["all"],
                "recovery_strategies": [
                    RecoveryStrategy.FALLBACK_TOOL,
                    RecoveryStrategy.SKIP_STEP
                ]
            },

            ErrorPattern.EMPTY_RESULT: {
                "keywords": ["empty", "no data", "0 results", "not found"],
                "typical_tools": ["all"],
                "recovery_strategies": [
                    RecoveryStrategy.REQUEST_CLARIFICATION,
                    RecoveryStrategy.FALLBACK_TOOL,
                ],
            }
        }

        return patterns
    
    def analyze_error(self, error_message: str, context: Dict[str, Any]) -> Tuple[ErrorPattern, float]:
        """
        Analyze error message and context to identify error pattern.
        
        Args:
            error_message: Error message text
            context: Error context (tool name, parameters, etc.)
            
        Returns:
            Tuple of (identified pattern, confidence score)
        """
        error_lower = error_message.lower()
        tool_name = context.get('tool_name', '').lower()
        
        pattern_scores = {}
        
        # Check each pattern
        for pattern, config in self.error_patterns.items():
            score = 0.0
            
            # Keyword matching
            keywords = config.get('keywords', [])
            matching_keywords = sum(1 for keyword in keywords if keyword in error_lower)
            if keywords:
                score += (matching_keywords / len(keywords)) * 0.7
            
            # Tool matching
            typical_tools = config.get('typical_tools', [])
            if 'all' in typical_tools:
                score += 0.2
            elif any(tool in tool_name for tool in typical_tools):
                score += 0.3
            
            # Context-based scoring
            if pattern == ErrorPattern.MEMORY_EXHAUSTION:
                if context.get('memory_usage', 0) > 0.8:
                    score += 0.2
            elif pattern == ErrorPattern.TIMEOUT:
                if context.get('execution_time', 0) > context.get('expected_time', 300):
                    score += 0.2
            elif pattern == ErrorPattern.EMPTY_RESULT:
                if context.get('result_size', 1) == 0:
                    score += 0.3

            pattern_scores[pattern] = score
        
        # Return highest scoring pattern
        best_pattern = max(pattern_scores.items(), key=lambda x: x[1])
        return best_pattern[0], best_pattern[1]
    
    def get_recovery_strategies(self, pattern: ErrorPattern) -> List[RecoveryStrategy]:
        """Get recommended recovery strategies for an error pattern."""
        config = self.error_patterns.get(pattern, {})
        return config.get('recovery_strategies', [RecoveryStrategy.RETRY_SAME_TOOL])
    
    def suggest_parameter_adjustments(
        self, 
        pattern: ErrorPattern, 
        current_parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Suggest parameter adjustments for an error pattern."""
        config = self.error_patterns.get(pattern, {})
        adjustments = config.get('parameter_adjustments', {})
        
        suggested_params = current_parameters.copy()
        
        for param_name, adjustment in adjustments.items():
            if callable(adjustment):
                current_value = current_parameters.get(param_name)
                try:
                    suggested_params[param_name] = adjustment(current_value)
                except:
                    continue
            elif isinstance(adjustment, str):
                # Handle special adjustment functions
                if adjustment == "check_file_existence":
                    # Logic to find alternative file paths
                    pass
                elif adjustment == "use_default_mask":
                    suggested_params[param_name] = None  # Use tool default
                elif adjustment == "use_default_template":
                    suggested_params[param_name] = "MNI152"
            else:
                suggested_params[param_name] = adjustment
        
        return suggested_params
    
    def record_recovery_attempt(
        self, 
        error_pattern: ErrorPattern, 
        recovery_strategy: RecoveryStrategy, 
        success: bool,
        context: Dict[str, Any] = None
    ):
        """Record the outcome of a recovery attempt for learning."""
        pattern_key = error_pattern.value
        
        if pattern_key not in self.recovery_history:
            self.recovery_history[pattern_key] = []
        
        record = {
            'strategy': recovery_strategy.value,
            'success': success,
            'timestamp': time.time(),
            'context': context or {}
        }
        
        self.recovery_history[pattern_key].append(record)
        
        # Keep only recent history (last 100 attempts per pattern)
        if len(self.recovery_history[pattern_key]) > 100:
            self.recovery_history[pattern_key] = self.recovery_history[pattern_key][-100:]
    
    def get_strategy_success_rate(
        self, 
        error_pattern: ErrorPattern, 
        recovery_strategy: RecoveryStrategy
    ) -> float:
        """Get historical success rate for a recovery strategy on an error pattern."""
        pattern_key = error_pattern.value
        
        if pattern_key not in self.recovery_history:
            return 0.5  # Default assumption
        
        history = self.recovery_history[pattern_key]
        strategy_attempts = [
            record for record in history 
            if record['strategy'] == recovery_strategy.value
        ]
        
        if not strategy_attempts:
            return 0.5
        
        successes = sum(1 for attempt in strategy_attempts if attempt['success'])
        return successes / len(strategy_attempts)


class IntelligentFallbackSelector:
    """Selects appropriate fallback tools based on context and capabilities."""
    
    def __init__(self, tool_registry: EnhancedToolRegistry):
        """Initialize fallback selector."""
        self.tool_registry = tool_registry
        self.tool_capabilities: Dict[str, Set[str]] = {}
        self.fallback_mappings: Dict[str, List[str]] = {}
        
        self._initialize_tool_capabilities()
        self._initialize_fallback_mappings()
        
        logger.info("Intelligent fallback selector initialized")
    
    def _initialize_tool_capabilities(self):
        """Initialize tool capability mapping."""
        # This would be populated from tool metadata or configuration
        capability_mapping = {
            # Preprocessing tools
            "fmriprep": {"preprocessing", "motion_correction", "registration", "normalization"},
            "spm_preprocess": {"preprocessing", "motion_correction", "registration", "smoothing"},
            "afni_preprocess": {"preprocessing", "motion_correction", "registration"},
            
            # Analysis tools
            "glm_analysis": {"statistical_analysis", "activation", "contrast"},
            "spm_glm": {"statistical_analysis", "activation", "contrast"},
            "fsl_feat": {"statistical_analysis", "activation", "contrast"},
            
            # Connectivity tools
            "connectivity_analysis": {"connectivity", "network_analysis"},
            "conn_toolbox": {"connectivity", "network_analysis", "graph_theory"},
            "nilearn_connectivity": {"connectivity", "functional_networks"},
            
            # Registration tools
            "ants_registration": {"registration", "normalization", "spatial_transform"},
            "fsl_flirt": {"registration", "linear_transform"},
            "spm_normalize": {"registration", "normalization"}
        }
        
        # Get actual tools from registry and map capabilities
        for tool in self.tool_registry.get_all_tools():
            tool_name = tool.get_tool_name().lower()
            
            # Find matching capability mapping
            for pattern, capabilities in capability_mapping.items():
                if pattern in tool_name:
                    self.tool_capabilities[tool.get_tool_name()] = capabilities
                    break
            
            # Fallback: infer capabilities from tool name and description
            if tool.get_tool_name() not in self.tool_capabilities:
                self.tool_capabilities[tool.get_tool_name()] = self._infer_capabilities(tool)
    
    def _infer_capabilities(self, tool) -> Set[str]:
        """Infer tool capabilities from name and description."""
        name = tool.get_tool_name().lower()
        description = tool.get_tool_description().lower()
        text = f"{name} {description}"
        
        capabilities = set()
        
        # Capability inference rules
        capability_keywords = {
            "preprocessing": ["preprocess", "prep", "clean", "denoise"],
            "registration": ["register", "align", "normalize", "transform"],
            "statistical_analysis": ["glm", "analysis", "statistical", "test"],
            "connectivity": ["connectivity", "network", "functional", "correlation"],
            "activation": ["activation", "contrast", "task", "stimulus"],
            "visualization": ["plot", "visualize", "display", "show"],
            "quality_control": ["quality", "qc", "check", "validate"]
        }
        
        for capability, keywords in capability_keywords.items():
            if any(keyword in text for keyword in keywords):
                capabilities.add(capability)
        
        return capabilities if capabilities else {"general"}
    
    def _initialize_fallback_mappings(self):
        """Initialize explicit fallback tool mappings."""
        # Common fallback patterns
        self.fallback_mappings = {
            # Preprocessing fallbacks
            "fmriprep": ["spm_preprocess", "afni_preprocess", "manual_preprocess"],
            "spm_preprocess": ["fmriprep", "afni_preprocess"],
            
            # Analysis fallbacks
            "glm_analysis": ["spm_glm", "fsl_feat", "afni_glm"],
            "spm_glm": ["fsl_feat", "glm_analysis"],
            "fsl_feat": ["spm_glm", "glm_analysis"],
            
            # Registration fallbacks
            "ants_registration": ["fsl_flirt", "spm_normalize"],
            "fsl_flirt": ["ants_registration", "spm_normalize"],
            
            # Connectivity fallbacks
            "connectivity_analysis": ["conn_toolbox", "nilearn_connectivity"],
            "conn_toolbox": ["nilearn_connectivity", "connectivity_analysis"]
        }
    
    def find_fallback_tools(
        self, 
        failed_tool_name: str, 
        required_capabilities: Set[str] = None,
        context: Dict[str, Any] = None
    ) -> List[Tuple[str, float]]:
        """
        Find appropriate fallback tools for a failed tool.
        
        Args:
            failed_tool_name: Name of the tool that failed
            required_capabilities: Required capabilities for replacement
            context: Execution context
            
        Returns:
            List of (tool_name, suitability_score) tuples, sorted by score
        """
        context = context or {}
        
        # Get capabilities of the failed tool
        failed_capabilities = self.tool_capabilities.get(failed_tool_name, set())
        
        # Use specified capabilities or infer from failed tool
        target_capabilities = required_capabilities or failed_capabilities
        
        # Start with explicit fallback mappings
        candidates = []
        
        explicit_fallbacks = self.fallback_mappings.get(failed_tool_name, [])
        for fallback_name in explicit_fallbacks:
            if fallback_name in [tool.get_tool_name() for tool in self.tool_registry.get_all_tools()]:
                candidates.append((fallback_name, 0.8))  # High score for explicit mappings
        
        # Find tools with matching capabilities
        for tool in self.tool_registry.get_all_tools():
            tool_name = tool.get_tool_name()
            
            if tool_name == failed_tool_name:
                continue  # Skip the failed tool
            
            if tool_name in [c[0] for c in candidates]:
                continue  # Skip already added candidates
            
            tool_capabilities = self.tool_capabilities.get(tool_name, set())
            
            # Calculate capability overlap
            if target_capabilities and tool_capabilities:
                overlap = len(target_capabilities & tool_capabilities)
                total_required = len(target_capabilities)
                
                if overlap > 0:
                    capability_score = overlap / total_required
                    
                    # Boost score for tools with additional capabilities
                    additional_capabilities = len(tool_capabilities) - overlap
                    bonus = min(0.2, additional_capabilities * 0.05)
                    
                    final_score = capability_score + bonus
                    candidates.append((tool_name, final_score))
        
        # Apply contextual scoring
        scored_candidates = []
        for tool_name, base_score in candidates:
            contextual_score = self._apply_contextual_scoring(
                tool_name, base_score, context
            )
            scored_candidates.append((tool_name, contextual_score))
        
        # Sort by score (descending)
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        
        return scored_candidates[:5]  # Return top 5 candidates
    
    def _apply_contextual_scoring(
        self, 
        tool_name: str, 
        base_score: float, 
        context: Dict[str, Any]
    ) -> float:
        """Apply contextual adjustments to tool scores."""
        score = base_score
        
        # Consider tool success history
        if 'tool_success_rates' in context:
            success_rate = context['tool_success_rates'].get(tool_name, 0.5)
            score *= (0.5 + success_rate * 0.5)  # Weight by historical success
        
        # Consider resource availability
        if 'available_resources' in context:
            # Prefer lighter-weight tools if resources are constrained
            tool_name_lower = tool_name.lower()
            if any(heavy_tool in tool_name_lower for heavy_tool in ['fmriprep', 'freesurfer']):
                if context['available_resources'].get('memory_gb', 16) < 8:
                    score *= 0.7  # Penalize resource-intensive tools
        
        # Consider data type compatibility
        if 'data_type' in context:
            data_type = context['data_type'].lower()
            tool_name_lower = tool_name.lower()
            
            # Boost score for data-type specific tools
            if data_type == 'fmri' and 'fmri' in tool_name_lower:
                score *= 1.2
            elif data_type == 'dwi' and any(term in tool_name_lower for term in ['dwi', 'diffusion']):
                score *= 1.2
        
        return min(1.0, score)  # Cap at 1.0


class AdvancedErrorRecoverySystem:
    """Main error recovery system coordinating all recovery mechanisms."""
    
    def __init__(
        self,
        tool_registry: EnhancedToolRegistry,
        checkpoint_manager: Optional[CheckpointManager] = None,
        redis_url: Optional[str] = None,
        max_attempts: int = 3,
    ):
        """Initialize advanced error recovery system."""
        self.tool_registry = tool_registry
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()
        
        # Initialize components
        self.error_analyzer = ErrorPatternAnalyzer()
        self.fallback_selector = IntelligentFallbackSelector(tool_registry)
        self.error_handler = ErrorHandler()
        self.max_attempts = max_attempts
        
        # Recovery state tracking
        self.active_recoveries: Dict[str, Dict[str, Any]] = {}
        self.recovery_history: List[Dict[str, Any]] = []
        
        # Redis for distributed coordination (optional)
        self.redis_client = None
        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
            except:
                self.redis_client = FakeRedis()
        
        logger.info("Advanced error recovery system initialized")
    
    async def handle_error_with_recovery(
        self,
        error: Exception,
        execution_context: Dict[str, Any],
        recovery_options: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Handle an error with intelligent recovery strategies.
        
        Args:
            error: The exception that occurred
            execution_context: Context of the failed execution
            recovery_options: Additional recovery configuration
            
        Returns:
            Recovery result with status and actions taken
        """
        recovery_id = f"recovery_{uuid4().hex[:8]}"
        recovery_start_time = time.time()
        
        logger.info(f"Starting error recovery {recovery_id}")
        
        # Initialize recovery tracking
        self.active_recoveries[recovery_id] = {
            'start_time': recovery_start_time,
            'error': str(error),
            'context': execution_context,
            'status': 'analyzing',
            'attempts': []
        }
        
        try:
            # Step 1: Analyze the error
            error_pattern, confidence = self.error_analyzer.analyze_error(
                str(error), execution_context
            )
            recovery_tracking['error_pattern'] = error_pattern.value
            
            logger.info(f"Error pattern identified: {error_pattern.value} (confidence: {confidence:.2f})")
            
            # Step 2: Create recovery plan
            recovery_plan = self._create_recovery_plan(
                error_pattern, execution_context, recovery_options or {}
            )

            # Step 3: Execute recovery plan
            recovery_result = await self._execute_recovery_plan(
                recovery_id, recovery_plan, execution_context, recovery_options or {}
            )
            
            # Step 4: Update tracking and history
            self._record_recovery_result(recovery_id, recovery_result)
            
            return recovery_result
        
        except Exception as recovery_error:
            logger.error(f"Recovery system error: {recovery_error}")
            return {
                'success': False,
                'recovery_id': recovery_id,
                'error': f"Recovery system error: {str(recovery_error)}",
                'actions_taken': []
            }
        
        finally:
            # Clean up active recovery tracking
            if recovery_id in self.active_recoveries:
                del self.active_recoveries[recovery_id]
    
    def _create_recovery_plan(
        self,
        error_pattern: ErrorPattern,
        execution_context: Dict[str, Any],
        recovery_options: Dict[str, Any]
    ) -> RecoveryPlan:
        """Create a comprehensive recovery plan for the error."""
        plan = RecoveryPlan(
            plan_id=f"plan_{uuid4().hex[:8]}",
            error_context=execution_context
        )
        
        # Get recommended strategies for this error pattern
        strategies = self.error_analyzer.get_recovery_strategies(error_pattern)
        
        # Create recovery actions based on strategies
        for i, strategy in enumerate(strategies):
            action = self._create_recovery_action(
                strategy, error_pattern, execution_context, i
            )
            if action:
                plan.actions.append(action)
        
        # Add fallback actions
        plan.fallback_actions = self._create_fallback_actions(
            error_pattern, execution_context
        )
        
        # Calculate plan metrics
        plan.estimated_recovery_time = sum(
            action.estimated_cost * 60 for action in plan.actions  # Convert to seconds
        )
        
        # Plan confidence based on historical success rates
        success_rates = []
        for action in plan.actions:
            success_rate = self.error_analyzer.get_strategy_success_rate(
                error_pattern, action.strategy
            )
            success_rates.append(success_rate)
        
        plan.confidence_score = max(success_rates) if success_rates else 0.3
        
        return plan
    
    def _create_recovery_action(
        self,
        strategy: RecoveryStrategy,
        error_pattern: ErrorPattern,
        execution_context: Dict[str, Any],
        priority: int
    ) -> Optional[RecoveryAction]:
        """Create a specific recovery action for a strategy."""
        
        if strategy == RecoveryStrategy.RETRY_SAME_TOOL:
            return RecoveryAction(
                action_id=f"retry_{priority}",
                strategy=strategy,
                description="Retry the same tool with original parameters",
                success_probability=0.3,
                estimated_cost=1.0
            )
        
        elif strategy == RecoveryStrategy.PARAMETER_ADJUSTMENT:
            adjusted_params = self.error_analyzer.suggest_parameter_adjustments(
                error_pattern, execution_context.get('parameters', {})
            )
            
            return RecoveryAction(
                action_id=f"adjust_params_{priority}",
                strategy=strategy,
                description="Retry with adjusted parameters",
                parameters={'adjusted_parameters': adjusted_params},
                success_probability=0.6,
                estimated_cost=1.2
            )
        
        elif strategy == RecoveryStrategy.FALLBACK_TOOL:
            failed_tool = execution_context.get('tool_name')
            if failed_tool:
                fallback_candidates = self.fallback_selector.find_fallback_tools(
                    failed_tool, context=execution_context
                )
                
                if fallback_candidates:
                    best_fallback = fallback_candidates[0]
                    return RecoveryAction(
                        action_id=f"fallback_{priority}",
                        strategy=strategy,
                        description=f"Use fallback tool: {best_fallback[0]}",
                        parameters={
                            'fallback_tool': best_fallback[0],
                            'fallback_score': best_fallback[1],
                            'all_candidates': fallback_candidates[:3]
                        },
                        success_probability=min(0.8, best_fallback[1]),
                        estimated_cost=1.5
                    )
        
        elif strategy == RecoveryStrategy.ROLLBACK_CHECKPOINT:
            # Check if checkpoints are available
            execution_id = execution_context.get('execution_id')
            if execution_id and hasattr(self.checkpoint_manager, 'get_latest_checkpoint'):
                return RecoveryAction(
                    action_id=f"rollback_{priority}",
                    strategy=strategy,
                    description="Rollback to last stable checkpoint",
                    parameters={'execution_id': execution_id},
                    success_probability=0.7,
                    estimated_cost=0.5
                )
        
        elif strategy == RecoveryStrategy.SKIP_STEP:
            step_id = execution_context.get('step_id')
            if step_id:
                return RecoveryAction(
                    action_id=f"skip_{priority}",
                    strategy=strategy,
                    description=f"Skip current step: {step_id}",
                    parameters={'step_id': step_id},
                    success_probability=0.5,
                    estimated_cost=0.1
                )

        elif strategy == RecoveryStrategy.REQUEST_CLARIFICATION:
            question = self._build_clarification_question(error_pattern, execution_context)
            return RecoveryAction(
                action_id=f"clarify_{priority}",
                strategy=strategy,
                description="Ask user for missing info",
                parameters={"question": question},
                success_probability=0.0,
                estimated_cost=0.1,
            )

        return None
    
    def _create_fallback_actions(
        self,
        error_pattern: ErrorPattern,
        execution_context: Dict[str, Any]
    ) -> List[RecoveryAction]:
        """Create fallback actions as last resort options."""
        fallback_actions = []
        
        # Always include abort as final fallback
        fallback_actions.append(
            RecoveryAction(
                action_id="abort_final",
                strategy=RecoveryStrategy.ABORT_WORKFLOW,
                description="Abort workflow execution",
                success_probability=1.0,  # Always "succeeds" at stopping
                estimated_cost=0.0
            )
        )
        
        return fallback_actions

    def _build_clarification_question(
        self, error_pattern: ErrorPattern, execution_context: Dict[str, Any]
    ) -> str:
        base = execution_context.get("original_query") or "the last request"
        tool_name = execution_context.get("tool_name", "this tool")
        if error_pattern == ErrorPattern.EMPTY_RESULT:
            return (
                f"I could not find data for {tool_name}."
                " Which dataset/run should I use instead?"
            )
        if error_pattern == ErrorPattern.INVALID_PARAMETERS:
            missing = [k for k, v in (execution_context.get("parameters") or {}).items() if v in (None, "", [])]
            if missing:
                return f"Please provide values for {', '.join(missing)} so I can retry {tool_name}."
        return f"Can you confirm key parameters (dataset, subject, contrast) for {base}?"
    
    async def _execute_recovery_plan(
        self,
        recovery_id: str,
        plan: RecoveryPlan,
        execution_context: Dict[str, Any],
        recovery_options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a recovery plan, trying actions in sequence."""
        recovery_tracking = self.active_recoveries[recovery_id]
        recovery_tracking['status'] = 'executing'
        recovery_tracking['plan'] = plan.plan_id

        actions_taken = []
        max_attempts = recovery_options.get("max_attempts", self.max_attempts)
        attempts_used = 0
        
        # Try primary recovery actions
        for action in plan.actions:
            if attempts_used >= max_attempts:
                break
            logger.info(f"Attempting recovery action: {action.description}")

            try:
                action_result = await self._execute_recovery_action(
                    action, execution_context
                )

                actions_taken.append({
                    'action_id': action.action_id,
                    'strategy': action.strategy.value,
                    'description': action.description,
                    'result': action_result,
                    'timestamp': time.time()
                })
                attempts_used += 1

                recovery_tracking['attempts'].append(actions_taken[-1])

                if action_result.get('clarification_needed'):
                    return {
                        'success': False,
                        'recovery_id': recovery_id,
                        'clarification_needed': True,
                        'question': action_result.get('question'),
                        'actions_taken': actions_taken,
                    }

                if action_result.get('success'):
                    logger.info(f"Recovery action succeeded: {action.action_id}")
                    return {
                        'success': True,
                        'recovery_id': recovery_id,
                        'successful_action': action.action_id,
                        'actions_taken': actions_taken,
                        'recovery_time': time.time() - recovery_tracking['start_time']
                    }
                else:
                    logger.warning(f"Recovery action failed: {action.action_id}")
                    
                    # Check if we should continue or abort
                    if action_result.get('abort_recovery'):
                        break
            
            except Exception as action_error:
                logger.error(f"Recovery action error: {action_error}")
                actions_taken.append({
                    'action_id': action.action_id,
                    'strategy': action.strategy.value,
                    'description': action.description,
                    'result': {'success': False, 'error': str(action_error)},
                    'timestamp': time.time()
                })
        
        # Try fallback actions if primary actions failed
        for fallback_action in plan.fallback_actions:
            if attempts_used >= max_attempts:
                break
            logger.info(f"Attempting fallback action: {fallback_action.description}")
            
            try:
                fallback_result = await self._execute_recovery_action(
                    fallback_action, execution_context
                )
                
                actions_taken.append({
                    'action_id': fallback_action.action_id,
                    'strategy': fallback_action.strategy.value,
                    'description': fallback_action.description,
                    'result': fallback_result,
                    'timestamp': time.time()
                })
                if fallback_result.get('clarification_needed'):
                    return {
                        'success': False,
                        'recovery_id': recovery_id,
                        'clarification_needed': True,
                        'question': fallback_result.get('question'),
                        'actions_taken': actions_taken,
                    }
                attempts_used += 1
                
                if fallback_result.get('success'):
                    return {
                        'success': True,
                        'recovery_id': recovery_id,
                        'successful_action': fallback_action.action_id,
                        'actions_taken': actions_taken,
                        'recovery_time': time.time() - recovery_tracking['start_time']
                    }
            
            except Exception as fallback_error:
                logger.error(f"Fallback action error: {fallback_error}")
        
        # All recovery attempts failed
        return {
            'success': False,
            'recovery_id': recovery_id,
            'error': 'All recovery attempts failed',
            'actions_taken': actions_taken,
            'recovery_time': time.time() - recovery_tracking['start_time']
        }
    
    async def _execute_recovery_action(
        self,
        action: RecoveryAction,
        execution_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single recovery action."""
        
        if action.strategy == RecoveryStrategy.RETRY_SAME_TOOL:
            return await self._retry_same_tool(action, execution_context)
        
        elif action.strategy == RecoveryStrategy.PARAMETER_ADJUSTMENT:
            return await self._retry_with_adjusted_parameters(action, execution_context)
        
        elif action.strategy == RecoveryStrategy.FALLBACK_TOOL:
            return await self._execute_fallback_tool(action, execution_context)
        
        elif action.strategy == RecoveryStrategy.ROLLBACK_CHECKPOINT:
            return await self._rollback_to_checkpoint(action, execution_context)
        
        elif action.strategy == RecoveryStrategy.SKIP_STEP:
            return self._skip_step(action, execution_context)

        elif action.strategy == RecoveryStrategy.REQUEST_CLARIFICATION:
            return {
                'success': False,
                'clarification_needed': True,
                'question': action.parameters.get('question'),
            }

        elif action.strategy == RecoveryStrategy.ABORT_WORKFLOW:
            return self._abort_workflow(action, execution_context)
        
        else:
            return {'success': False, 'error': f'Unknown recovery strategy: {action.strategy}'}
    
    async def _retry_same_tool(
        self, 
        action: RecoveryAction, 
        execution_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Retry the same tool with original parameters."""
        tool_name = execution_context.get('tool_name')
        parameters = execution_context.get('parameters', {})
        
        if not tool_name:
            return {'success': False, 'error': 'No tool name in context'}
        
        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            return {'success': False, 'error': f'Tool {tool_name} not found'}
        
        try:
            result = await self._execute_tool_with_registry(tool, parameters, execution_context)
            return {
                'success': result.get('status') in {'success', 'ok', 'completed'},
                'result': result,
                'retry_attempt': True
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _retry_with_adjusted_parameters(
        self, 
        action: RecoveryAction, 
        execution_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Retry with adjusted parameters."""
        tool_name = execution_context.get('tool_name')
        adjusted_params = action.parameters.get('adjusted_parameters', {})
        
        if not tool_name:
            return {'success': False, 'error': 'No tool name in context'}
        
        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            return {'success': False, 'error': f'Tool {tool_name} not found'}
        
        try:
            tuned_params = self._apply_safety_adjustments(adjusted_params)
            result = await self._execute_tool_with_registry(
                tool=tool,
                parameters=tuned_params,
                execution_context=execution_context,
            )

            return {
                'success': result['status'] == 'success',
                'result': result,
                'adjusted_parameters': tuned_params
            }
        
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _apply_safety_adjustments(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Apply generic safe fallbacks such as reducing parallelism."""

        tuned = params.copy()
        for key in ("n_jobs", "num_workers", "threads"):
            if key in tuned:
                try:
                    tuned[key] = max(1, int(tuned[key] or 1))
                except Exception:
                    tuned[key] = 1
        if "batch_size" in tuned:
            try:
                tuned["batch_size"] = max(1, int(tuned["batch_size"] or 1) // 2)
            except Exception:
                tuned["batch_size"] = 1
        if "timeout" in tuned:
            try:
                tuned["timeout"] = int(tuned["timeout"] or 0) * 2 or 600
            except Exception:
                tuned["timeout"] = 600
        tuned.setdefault("low_mem", True)
        return tuned

    async def _execute_tool_with_registry(
        self,
        tool,
        parameters: Dict[str, Any],
        execution_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute using registry if available, otherwise run the tool directly."""

        if hasattr(self.tool_registry, "execute_with_monitoring"):
            return await self.tool_registry.execute_with_monitoring(
                tool=tool, parameters=parameters, context=execution_context
            )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: tool.run(**parameters))
        return {"status": "success", "result": result}
    
    async def _execute_fallback_tool(
        self, 
        action: RecoveryAction, 
        execution_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a fallback tool."""
        fallback_tool_name = action.parameters.get('fallback_tool')
        original_params = execution_context.get('parameters', {})
        
        if not fallback_tool_name:
            return {'success': False, 'error': 'No fallback tool specified'}
        
        fallback_tool = self.tool_registry.get_tool(fallback_tool_name)
        if not fallback_tool:
            return {'success': False, 'error': f'Fallback tool {fallback_tool_name} not found'}
        
        try:
            # Get parameter recommendations for the fallback tool
            fallback_params = original_params.copy()
            if hasattr(self.tool_registry, 'get_intelligent_recommendations'):
                recommendations = self.tool_registry.get_intelligent_recommendations(
                    query=execution_context.get('original_query', ''),
                    context=execution_context
                )

                for rec in recommendations:
                    if rec.tool.get_tool_name() == fallback_tool_name:
                        fallback_params.update(rec.parameter_suggestions)
                        break
            
            fallback_params = self._apply_safety_adjustments(fallback_params)
            result = await self._execute_tool_with_registry(
                tool=fallback_tool,
                parameters=fallback_params,
                execution_context=execution_context,
            )
            
            return {
                'success': result['status'] == 'success',
                'result': result,
                'fallback_tool': fallback_tool_name,
                'fallback_parameters': fallback_params
            }
        
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _rollback_to_checkpoint(
        self, 
        action: RecoveryAction, 
        execution_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Rollback execution to a previous checkpoint."""
        checkpoint_id = (
            action.parameters.get('execution_id')
            or execution_context.get('checkpoint_id')
        )

        if not checkpoint_id:
            return {'success': False, 'error': 'No checkpoint available for rollback'}

        try:
            state = self.checkpoint_manager.restore_from_checkpoint(checkpoint_id)
            return {
                'success': True,
                'rollback_point': checkpoint_id,
                'restored_state': state.__dict__ if state else None,
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _skip_step(
        self, 
        action: RecoveryAction, 
        execution_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Skip the current step."""
        step_id = action.parameters.get('step_id')
        
        return {
            'success': True,
            'skipped_step': step_id,
            'message': f'Skipped step {step_id}'
        }
    
    def _abort_workflow(
        self, 
        action: RecoveryAction, 
        execution_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Abort the workflow execution."""
        return {
            'success': True,
            'aborted': True,
            'message': 'Workflow execution aborted'
        }
    
    def _record_recovery_result(self, recovery_id: str, result: Dict[str, Any]):
        """Record the result of a recovery attempt for learning."""
        recovery_record = {
            'recovery_id': recovery_id,
            'timestamp': time.time(),
            'success': result.get('success', False),
            'actions_taken': result.get('actions_taken', []),
            'recovery_time': result.get('recovery_time', 0)
        }
        recovery_meta = self.active_recoveries.get(recovery_id, {})
        pattern_str = recovery_meta.get('error_pattern')

        self.recovery_history.append(recovery_record)
        
        # Keep only recent history
        if len(self.recovery_history) > 1000:
            self.recovery_history = self.recovery_history[-1000:]
        
        # Update error analyzer with results
        for action in result.get('actions_taken', []):
            if 'strategy' in action and 'result' in action:
                try:
                    pattern = ErrorPattern(pattern_str) if pattern_str else ErrorPattern.INVALID_PARAMETERS
                except Exception:
                    pattern = ErrorPattern.INVALID_PARAMETERS
                self.error_analyzer.record_recovery_attempt(
                    pattern,
                    RecoveryStrategy(action['strategy']),
                    action['result'].get('success', False)
                )
    
    def get_recovery_statistics(self) -> Dict[str, Any]:
        """Get statistics about recovery system performance."""
        if not self.recovery_history:
            return {'message': 'No recovery history available'}
        
        total_recoveries = len(self.recovery_history)
        successful_recoveries = sum(1 for r in self.recovery_history if r['success'])
        success_rate = successful_recoveries / total_recoveries
        
        avg_recovery_time = np.mean([r['recovery_time'] for r in self.recovery_history])
        
        # Strategy effectiveness
        strategy_stats = {}
        for record in self.recovery_history:
            for action in record.get('actions_taken', []):
                strategy = action.get('strategy')
                if strategy:
                    if strategy not in strategy_stats:
                        strategy_stats[strategy] = {'attempts': 0, 'successes': 0}
                    strategy_stats[strategy]['attempts'] += 1
                    if action.get('result', {}).get('success'):
                        strategy_stats[strategy]['successes'] += 1
        
        # Calculate success rates for each strategy
        for strategy, stats in strategy_stats.items():
            if stats['attempts'] > 0:
                stats['success_rate'] = stats['successes'] / stats['attempts']
            else:
                stats['success_rate'] = 0.0
        
        return {
            'total_recoveries': total_recoveries,
            'successful_recoveries': successful_recoveries,
            'overall_success_rate': success_rate,
            'average_recovery_time': avg_recovery_time,
            'strategy_effectiveness': strategy_stats,
            'active_recoveries': len(self.active_recoveries)
        }


# Factory function for easy integration
def create_error_recovery_system(
    tool_registry: EnhancedToolRegistry,
    redis_url: Optional[str] = None,
    max_attempts: int = 3,
) -> AdvancedErrorRecoverySystem:
    """Create an advanced error recovery system instance."""
    return AdvancedErrorRecoverySystem(
        tool_registry=tool_registry,
        redis_url=redis_url,
        max_attempts=max_attempts,
    )
