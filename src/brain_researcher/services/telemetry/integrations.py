"""
TelemetryIntegration - Integration hooks for Agent, BR-KG, and UI services.
"""

import asyncio
import functools
import logging
import time
from datetime import datetime
from typing import Optional, Callable, Any, Dict, List
from contextlib import contextmanager
import threading

from .collector import TelemetryCollector
from .models import EventType, ServiceType, PrivacyLevel, TelemetryConfiguration


logger = logging.getLogger(__name__)


class TelemetryIntegration:
    """
    Centralized telemetry integration for all Brain Researcher services.
    """

    def __init__(self,
                 service_type: ServiceType,
                 collector: Optional[TelemetryCollector] = None,
                 config: Optional[TelemetryConfiguration] = None):
        self.service_type = service_type
        self.collector = collector or TelemetryCollector(config)
        self.config = config or TelemetryConfiguration()

        # Thread-local storage for context
        self._local = threading.local()

        logger.info(f"TelemetryIntegration initialized for service: {service_type}")

    # Context Management

    def set_user_context(self, user_id: Optional[str], session_id: Optional[str] = None):
        """Set user context for current thread."""
        self._local.user_id = user_id
        self._local.session_id = session_id

    def get_user_context(self) -> tuple[Optional[str], Optional[str]]:
        """Get user context for current thread."""
        return (
            getattr(self._local, 'user_id', None),
            getattr(self._local, 'session_id', None)
        )

    @contextmanager
    def user_context(self, user_id: Optional[str], session_id: Optional[str] = None):
        """Context manager for temporary user context."""
        old_user_id = getattr(self._local, 'user_id', None)
        old_session_id = getattr(self._local, 'session_id', None)

        try:
            self.set_user_context(user_id, session_id)
            yield
        finally:
            self.set_user_context(old_user_id, old_session_id)

    # Event Collection Methods

    def track_tool_usage(self,
                        tool_name: str,
                        action: str = "invoke",
                        user_id: Optional[str] = None,
                        parameters: Optional[Dict[str, Any]] = None,
                        duration_ms: Optional[int] = None,
                        success: bool = True,
                        error_message: Optional[str] = None) -> Optional[str]:
        """Track tool usage event."""
        user_id = user_id or getattr(self._local, 'user_id', None)
        session_id = getattr(self._local, 'session_id', None)

        return self.collector.collect_tool_usage(
            tool_name=tool_name,
            action=action,
            service=self.service_type,
            user_id=user_id,
            parameters=parameters,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message
        )

    def track_feature_usage(self,
                           feature_name: str,
                           action: str,
                           user_id: Optional[str] = None,
                           context: Optional[Dict[str, Any]] = None,
                           success: bool = True) -> Optional[str]:
        """Track feature usage event."""
        user_id = user_id or getattr(self._local, 'user_id', None)
        session_id = getattr(self._local, 'session_id', None)

        return self.collector.collect_feature_usage(
            feature_name=feature_name,
            action=action,
            service=self.service_type,
            user_id=user_id,
            context=context,
            success=success
        )

    def track_page_view(self,
                       page_path: str,
                       user_id: Optional[str] = None,
                       referrer: Optional[str] = None,
                       user_agent: Optional[str] = None) -> Optional[str]:
        """Track page view event (primarily for UI service)."""
        user_id = user_id or getattr(self._local, 'user_id', None)

        return self.collector.collect_page_view(
            page_path=page_path,
            service=self.service_type,
            user_id=user_id,
            referrer=referrer,
            user_agent=user_agent
        )

    def track_search_query(self,
                          query: str,
                          results_count: Optional[int] = None,
                          user_id: Optional[str] = None,
                          filters_applied: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Track search query event."""
        user_id = user_id or getattr(self._local, 'user_id', None)
        session_id = getattr(self._local, 'session_id', None)

        context = {"query_length": len(query)}
        if results_count is not None:
            context["results_count"] = results_count
        if filters_applied:
            context["filters_applied"] = list(filters_applied.keys())

        return self.collector.collect(
            event_type=EventType.SEARCH_QUERY,
            service=self.service_type,
            feature_name="search",
            action="query",
            user_id=user_id,
            session_id=session_id,
            context=context,
            parameters={"query_hash": hash(query)},  # Don't store actual query for privacy
            privacy_level=PrivacyLevel.AGGREGATE_ONLY
        )

    def track_analysis_start(self,
                            analysis_type: str,
                            dataset_id: Optional[str] = None,
                            parameters: Optional[Dict[str, Any]] = None,
                            user_id: Optional[str] = None) -> Optional[str]:
        """Track analysis start event."""
        user_id = user_id or getattr(self._local, 'user_id', None)
        session_id = getattr(self._local, 'session_id', None)

        context = {"analysis_type": analysis_type}
        if dataset_id:
            context["dataset_id"] = dataset_id

        return self.collector.collect(
            event_type=EventType.ANALYSIS_START,
            service=self.service_type,
            feature_name="analysis",
            action="start",
            user_id=user_id,
            session_id=session_id,
            context=context,
            parameters=parameters,
            privacy_level=PrivacyLevel.AGGREGATE_ONLY
        )

    def track_analysis_complete(self,
                               analysis_type: str,
                               duration_ms: int,
                               success: bool = True,
                               artifacts_generated: int = 0,
                               error_message: Optional[str] = None,
                               user_id: Optional[str] = None) -> Optional[str]:
        """Track analysis completion event."""
        user_id = user_id or getattr(self._local, 'user_id', None)
        session_id = getattr(self._local, 'session_id', None)

        context = {
            "analysis_type": analysis_type,
            "artifacts_generated": artifacts_generated
        }

        return self.collector.collect(
            event_type=EventType.ANALYSIS_COMPLETE,
            service=self.service_type,
            feature_name="analysis",
            action="complete",
            user_id=user_id,
            session_id=session_id,
            context=context,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
            privacy_level=PrivacyLevel.AGGREGATE_ONLY
        )

    def track_error(self,
                   error_type: str,
                   error_message: str,
                   feature_name: Optional[str] = None,
                   context: Optional[Dict[str, Any]] = None,
                   user_id: Optional[str] = None) -> Optional[str]:
        """Track error event."""
        user_id = user_id or getattr(self._local, 'user_id', None)
        session_id = getattr(self._local, 'session_id', None)

        error_context = {"error_type": error_type}
        if context:
            error_context.update(context)

        return self.collector.collect(
            event_type=EventType.TOOL_ERROR,
            service=self.service_type,
            feature_name=feature_name,
            action="error",
            user_id=user_id,
            session_id=session_id,
            context=error_context,
            error_message=error_message,
            success=False,
            privacy_level=PrivacyLevel.INTERNAL_ONLY
        )

    # Decorator Functions

    def track_function_call(self,
                           feature_name: Optional[str] = None,
                           track_args: bool = False,
                           track_result: bool = False,
                           privacy_level: PrivacyLevel = PrivacyLevel.AGGREGATE_ONLY):
        """Decorator to automatically track function calls."""
        def decorator(func: Callable) -> Callable:
            fname = feature_name or func.__name__

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                user_id, session_id = self.get_user_context()

                # Prepare context
                context = {"function_name": func.__name__}
                parameters = {}

                if track_args and args:
                    parameters["args_count"] = len(args)
                if track_args and kwargs:
                    parameters["kwargs_keys"] = list(kwargs.keys())

                try:
                    result = await func(*args, **kwargs)
                    duration_ms = int((time.time() - start_time) * 1000)

                    if track_result and result is not None:
                        context["has_result"] = True
                        if hasattr(result, '__len__'):
                            context["result_length"] = len(result)

                    self.collector.collect(
                        event_type=EventType.TOOL_COMPLETION,
                        service=self.service_type,
                        feature_name=fname,
                        action="call",
                        user_id=user_id,
                        session_id=session_id,
                        context=context,
                        parameters=parameters,
                        duration_ms=duration_ms,
                        success=True,
                        privacy_level=privacy_level
                    )

                    return result

                except Exception as e:
                    duration_ms = int((time.time() - start_time) * 1000)

                    self.collector.collect(
                        event_type=EventType.TOOL_ERROR,
                        service=self.service_type,
                        feature_name=fname,
                        action="call",
                        user_id=user_id,
                        session_id=session_id,
                        context=context,
                        parameters=parameters,
                        duration_ms=duration_ms,
                        success=False,
                        error_message=str(e),
                        privacy_level=privacy_level
                    )

                    raise

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                user_id, session_id = self.get_user_context()

                # Prepare context
                context = {"function_name": func.__name__}
                parameters = {}

                if track_args and args:
                    parameters["args_count"] = len(args)
                if track_args and kwargs:
                    parameters["kwargs_keys"] = list(kwargs.keys())

                try:
                    result = func(*args, **kwargs)
                    duration_ms = int((time.time() - start_time) * 1000)

                    if track_result and result is not None:
                        context["has_result"] = True
                        if hasattr(result, '__len__'):
                            context["result_length"] = len(result)

                    self.collector.collect(
                        event_type=EventType.TOOL_COMPLETION,
                        service=self.service_type,
                        feature_name=fname,
                        action="call",
                        user_id=user_id,
                        session_id=session_id,
                        context=context,
                        parameters=parameters,
                        duration_ms=duration_ms,
                        success=True,
                        privacy_level=privacy_level
                    )

                    return result

                except Exception as e:
                    duration_ms = int((time.time() - start_time) * 1000)

                    self.collector.collect(
                        event_type=EventType.TOOL_ERROR,
                        service=self.service_type,
                        feature_name=fname,
                        action="call",
                        user_id=user_id,
                        session_id=session_id,
                        context=context,
                        parameters=parameters,
                        duration_ms=duration_ms,
                        success=False,
                        error_message=str(e),
                        privacy_level=privacy_level
                    )

                    raise

            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

        return decorator

    def track_performance(self, operation_name: str):
        """Decorator to track performance metrics."""
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                user_id, session_id = self.get_user_context()

                try:
                    result = await func(*args, **kwargs)
                    duration_ms = int((time.time() - start_time) * 1000)

                    self.collector.collect(
                        event_type=EventType.FEATURE_COMPLETION,
                        service=self.service_type,
                        feature_name="performance",
                        action=operation_name,
                        user_id=user_id,
                        session_id=session_id,
                        duration_ms=duration_ms,
                        success=True,
                        privacy_level=PrivacyLevel.AGGREGATE_ONLY
                    )

                    return result

                except Exception as e:
                    duration_ms = int((time.time() - start_time) * 1000)

                    self.collector.collect(
                        event_type=EventType.FEATURE_ERROR,
                        service=self.service_type,
                        feature_name="performance",
                        action=operation_name,
                        user_id=user_id,
                        session_id=session_id,
                        duration_ms=duration_ms,
                        success=False,
                        error_message=str(e),
                        privacy_level=PrivacyLevel.INTERNAL_ONLY
                    )

                    raise

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                user_id, session_id = self.get_user_context()

                try:
                    result = func(*args, **kwargs)
                    duration_ms = int((time.time() - start_time) * 1000)

                    self.collector.collect(
                        event_type=EventType.FEATURE_COMPLETION,
                        service=self.service_type,
                        feature_name="performance",
                        action=operation_name,
                        user_id=user_id,
                        session_id=session_id,
                        duration_ms=duration_ms,
                        success=True,
                        privacy_level=PrivacyLevel.AGGREGATE_ONLY
                    )

                    return result

                except Exception as e:
                    duration_ms = int((time.time() - start_time) * 1000)

                    self.collector.collect(
                        event_type=EventType.FEATURE_ERROR,
                        service=self.service_type,
                        feature_name="performance",
                        action=operation_name,
                        user_id=user_id,
                        session_id=session_id,
                        duration_ms=duration_ms,
                        success=False,
                        error_message=str(e),
                        privacy_level=PrivacyLevel.INTERNAL_ONLY
                    )

                    raise

            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

        return decorator


# Service-Specific Integration Classes

class AgentTelemetry(TelemetryIntegration):
    """Telemetry integration for Agent service."""

    def __init__(self, collector: Optional[TelemetryCollector] = None, config: Optional[TelemetryConfiguration] = None):
        super().__init__(ServiceType.AGENT, collector, config)

    def track_tool_execution(self,
                            tool_name: str,
                            input_params: Dict[str, Any],
                            output_artifacts: List[str],
                            execution_time_ms: int,
                            success: bool = True,
                            error_message: Optional[str] = None,
                            user_id: Optional[str] = None) -> Optional[str]:
        """Track agent tool execution."""
        context = {
            "input_param_count": len(input_params),
            "output_artifact_count": len(output_artifacts),
            "tool_category": self._categorize_tool(tool_name)
        }

        # Sanitize parameters for privacy
        sanitized_params = {
            k: type(v).__name__ if not isinstance(v, (str, int, float, bool)) else v
            for k, v in input_params.items()
        }

        return self.track_tool_usage(
            tool_name=tool_name,
            action="execute",
            user_id=user_id,
            parameters=sanitized_params,
            duration_ms=execution_time_ms,
            success=success,
            error_message=error_message
        )

    def track_workflow_step(self,
                           workflow_id: str,
                           step_name: str,
                           step_index: int,
                           success: bool = True,
                           user_id: Optional[str] = None) -> Optional[str]:
        """Track workflow step execution."""
        return self.track_feature_usage(
            feature_name="workflow",
            action="step",
            user_id=user_id,
            context={
                "workflow_id": workflow_id,
                "step_name": step_name,
                "step_index": step_index,
                "success": success
            },
            success=success
        )

    def _categorize_tool(self, tool_name: str) -> str:
        """Categorize tool by name patterns."""
        tool_lower = tool_name.lower()
        if "fmri" in tool_lower or "bold" in tool_lower:
            return "fmri_analysis"
        elif "statistical" in tool_lower or "glm" in tool_lower:
            return "statistical_analysis"
        elif "visualization" in tool_lower or "plot" in tool_lower:
            return "visualization"
        elif "preprocessing" in tool_lower:
            return "preprocessing"
        else:
            return "general"


class BRKGTelemetry(TelemetryIntegration):
    """Telemetry integration for BR-KG service."""

    def __init__(self, collector: Optional[TelemetryCollector] = None, config: Optional[TelemetryConfiguration] = None):
        super().__init__(ServiceType.BR_KG, collector, config)

    def track_graph_query(self,
                         query_type: str,
                         query_complexity: str,
                         results_count: int,
                         execution_time_ms: int,
                         success: bool = True,
                         user_id: Optional[str] = None) -> Optional[str]:
        """Track graph database query."""
        context = {
            "query_type": query_type,
            "query_complexity": query_complexity,
            "results_count": results_count,
            "performance_tier": self._categorize_performance(execution_time_ms)
        }

        return self.track_feature_usage(
            feature_name="graph_query",
            action="execute",
            user_id=user_id,
            context=context,
            success=success
        )

    def track_data_ingestion(self,
                            data_source: str,
                            record_count: int,
                            processing_time_ms: int,
                            success: bool = True,
                            errors_encountered: int = 0,
                            user_id: Optional[str] = None) -> Optional[str]:
        """Track data ingestion process."""
        context = {
            "data_source": data_source,
            "record_count": record_count,
            "errors_encountered": errors_encountered,
            "throughput_rps": record_count / (processing_time_ms / 1000) if processing_time_ms > 0 else 0
        }

        return self.track_feature_usage(
            feature_name="data_ingestion",
            action="process",
            user_id=user_id,
            context=context,
            success=success
        )

    def track_knowledge_discovery(self,
                                 discovery_type: str,
                                 entities_analyzed: int,
                                 relationships_found: int,
                                 confidence_score: float,
                                 user_id: Optional[str] = None) -> Optional[str]:
        """Track knowledge discovery operations."""
        context = {
            "discovery_type": discovery_type,
            "entities_analyzed": entities_analyzed,
            "relationships_found": relationships_found,
            "confidence_score": confidence_score,
            "discovery_quality": "high" if confidence_score > 0.8 else "medium" if confidence_score > 0.5 else "low"
        }

        return self.track_feature_usage(
            feature_name="knowledge_discovery",
            action="discover",
            user_id=user_id,
            context=context,
            success=True
        )

    def _categorize_performance(self, execution_time_ms: int) -> str:
        """Categorize query performance."""
        if execution_time_ms < 100:
            return "fast"
        elif execution_time_ms < 1000:
            return "medium"
        elif execution_time_ms < 5000:
            return "slow"
        else:
            return "very_slow"


class UITelemetry(TelemetryIntegration):
    """Telemetry integration for Web UI service."""

    def __init__(self, collector: Optional[TelemetryCollector] = None, config: Optional[TelemetryConfiguration] = None):
        super().__init__(ServiceType.WEB_UI, collector, config)

    def track_component_interaction(self,
                                   component_name: str,
                                   interaction_type: str,
                                   user_id: Optional[str] = None,
                                   additional_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Track UI component interactions."""
        context = {
            "component_name": component_name,
            "interaction_type": interaction_type
        }

        if additional_data:
            context.update(additional_data)

        return self.track_feature_usage(
            feature_name="ui_component",
            action=interaction_type,
            user_id=user_id,
            context=context,
            success=True
        )

    def track_dashboard_view(self,
                            dashboard_type: str,
                            widgets_loaded: int,
                            load_time_ms: int,
                            user_id: Optional[str] = None) -> Optional[str]:
        """Track dashboard views."""
        context = {
            "dashboard_type": dashboard_type,
            "widgets_loaded": widgets_loaded,
            "load_time_ms": load_time_ms,
            "performance_rating": "fast" if load_time_ms < 1000 else "slow"
        }

        return self.track_feature_usage(
            feature_name="dashboard",
            action="view",
            user_id=user_id,
            context=context,
            success=True
        )

    def track_form_submission(self,
                             form_type: str,
                             field_count: int,
                             validation_errors: int,
                             success: bool = True,
                             user_id: Optional[str] = None) -> Optional[str]:
        """Track form submissions."""
        context = {
            "form_type": form_type,
            "field_count": field_count,
            "validation_errors": validation_errors,
            "completion_rate": 1.0 if success else 0.0
        }

        return self.track_feature_usage(
            feature_name="form",
            action="submit",
            user_id=user_id,
            context=context,
            success=success
        )


# Convenience factory functions

def create_agent_telemetry(config: Optional[TelemetryConfiguration] = None) -> AgentTelemetry:
    """Create telemetry integration for Agent service."""
    return AgentTelemetry(config=config)


def create_br_kg_telemetry(config: Optional[TelemetryConfiguration] = None) -> BRKGTelemetry:
    """Create telemetry integration for BR-KG service."""
    return BRKGTelemetry(config=config)


def create_ui_telemetry(config: Optional[TelemetryConfiguration] = None) -> UITelemetry:
    """Create telemetry integration for Web UI service."""
    return UITelemetry(config=config)