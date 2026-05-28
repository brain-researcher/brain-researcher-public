"""
Monitoring and observability for the Brain Researcher Agent.
Tracks tool usage, performance metrics, and error rates.
"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
import json
from pathlib import Path

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    
logger = logging.getLogger(__name__)


@dataclass
class ToolMetrics:
    """Metrics for a single tool."""
    tool_name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_execution_time: float = 0.0
    avg_execution_time: float = 0.0
    min_execution_time: float = float('inf')
    max_execution_time: float = 0.0
    last_called: Optional[datetime] = None
    error_messages: List[str] = field(default_factory=list)


@dataclass
class WorkflowMetrics:
    """Metrics for LangGraph workflows."""
    workflow_id: str
    tools_used: List[str] = field(default_factory=list)
    total_time: float = 0.0
    state_transitions: int = 0
    checkpoints_saved: int = 0
    success: bool = False
    timestamp: datetime = field(default_factory=datetime.now)


class MetricsCollector:
    """Collects and exports metrics for monitoring."""
    
    def __init__(self, export_path: Optional[str] = None):
        self.export_path = Path(export_path) if export_path else Path("metrics")
        self.export_path.mkdir(parents=True, exist_ok=True)
        
        # Tool metrics
        self.tool_metrics: Dict[str, ToolMetrics] = {}
        
        # Workflow metrics
        self.workflow_metrics: List[WorkflowMetrics] = []
        
        # Real-time counters
        self.active_workflows = 0
        self.total_workflows = 0
        
        # Initialize Prometheus metrics if available
        if PROMETHEUS_AVAILABLE:
            self._init_prometheus_metrics()
    
    def _init_prometheus_metrics(self):
        """Initialize Prometheus metrics."""
        # Tool metrics
        self.prom_tool_calls = Counter(
            'brain_researcher_tool_calls_total',
            'Total number of tool calls',
            ['tool_name', 'status']
        )
        
        self.prom_tool_duration = Histogram(
            'brain_researcher_tool_duration_seconds',
            'Tool execution duration in seconds',
            ['tool_name']
        )
        
        # Workflow metrics
        self.prom_workflow_duration = Histogram(
            'brain_researcher_workflow_duration_seconds',
            'Workflow execution duration in seconds'
        )
        
        self.prom_active_workflows = Gauge(
            'brain_researcher_active_workflows',
            'Number of active workflows'
        )
        
        # Error metrics
        self.prom_errors = Counter(
            'brain_researcher_errors_total',
            'Total number of errors',
            ['tool_name', 'error_type']
        )

        self.prom_gfs_autoretrieval = Counter(
            'brain_researcher_gfs_autoretrieval_total',
            'Google File Search auto-retrieval decisions by surface and status',
            ['surface', 'status', 'triggered']
        )
        self.prom_gfs_autoretrieval_calls = Counter(
            'brain_researcher_gfs_autoretrieval_calls_total',
            'Google File Search auto-retrieval downstream call count by surface',
            ['surface']
        )
        self.prom_gfs_docs = Counter(
            'brain_researcher_gfs_autoretrieval_docs_total',
            'Google File Search documents returned by surface',
            ['surface']
        )

        # Knowledge cache metrics
        self.prom_knowledge_hits = Counter(
            'brain_researcher_knowledge_cache_hits_total',
            'Knowledge cache hits',
            ['layer', 'account_id']
        )
        self.prom_knowledge_misses = Counter(
            'brain_researcher_knowledge_cache_misses_total',
            'Knowledge cache misses',
            ['layer', 'account_id']
        )
        self.prom_knowledge_sets = Counter(
            'brain_researcher_knowledge_cache_sets_total',
            'Knowledge cache writes',
            ['layer', 'account_id']
        )

        # Knowledge memory size (per account)
        self.prom_knowledge_memory_size = Gauge(
            'brain_researcher_knowledge_memory_size',
            'Number of stored knowledge bundles per account',
            ['account_id']
        )
    
    def record_tool_call(
        self,
        tool_name: str,
        execution_time: float,
        success: bool,
        error_message: Optional[str] = None
    ):
        """Record a tool call."""
        # Update or create tool metrics
        if tool_name not in self.tool_metrics:
            self.tool_metrics[tool_name] = ToolMetrics(tool_name=tool_name)
        
        metrics = self.tool_metrics[tool_name]
        metrics.total_calls += 1
        
        if success:
            metrics.successful_calls += 1
        else:
            metrics.failed_calls += 1
            if error_message:
                metrics.error_messages.append(error_message[-100:])  # Keep last 100 chars
                if len(metrics.error_messages) > 10:
                    metrics.error_messages.pop(0)  # Keep only last 10 errors
        
        # Update timing
        metrics.total_execution_time += execution_time
        metrics.avg_execution_time = metrics.total_execution_time / metrics.total_calls
        metrics.min_execution_time = min(metrics.min_execution_time, execution_time)
        metrics.max_execution_time = max(metrics.max_execution_time, execution_time)
        metrics.last_called = datetime.now()
        
        # Update Prometheus metrics if available
        if PROMETHEUS_AVAILABLE:
            status = "success" if success else "failure"
            self.prom_tool_calls.labels(tool_name=tool_name, status=status).inc()
            self.prom_tool_duration.labels(tool_name=tool_name).observe(execution_time)
            
            if not success and error_message:
                error_type = self._classify_error(error_message)
                self.prom_errors.labels(tool_name=tool_name, error_type=error_type).inc()

    def record_gfs_usage(
        self,
        *,
        surface: str,
        status: str,
        call_count: int,
        triggered: bool,
        n_docs_hit: int = 0,
    ) -> None:
        """Record Google File Search auto-retrieval usage."""
        if not PROMETHEUS_AVAILABLE:
            return
        surface_label = surface or "unknown"
        status_label = status or "unknown"
        triggered_label = "true" if triggered else "false"
        self.prom_gfs_autoretrieval.labels(
            surface=surface_label,
            status=status_label,
            triggered=triggered_label,
        ).inc()
        if call_count:
            self.prom_gfs_autoretrieval_calls.labels(surface=surface_label).inc(
                call_count
            )
        if n_docs_hit:
            self.prom_gfs_docs.labels(surface=surface_label).inc(n_docs_hit)
    
    def start_workflow(self, workflow_id: str) -> WorkflowMetrics:
        """Start tracking a workflow."""
        workflow = WorkflowMetrics(workflow_id=workflow_id)
        self.workflow_metrics.append(workflow)
        
        self.active_workflows += 1
        self.total_workflows += 1
        
        if PROMETHEUS_AVAILABLE:
            self.prom_active_workflows.set(self.active_workflows)
        
        return workflow
    
    def end_workflow(self, workflow_id: str, success: bool):
        """End tracking a workflow."""
        # Find workflow
        workflow = next(
            (w for w in self.workflow_metrics if w.workflow_id == workflow_id),
            None
        )
        
        if workflow:
            workflow.success = success
            workflow.total_time = (datetime.now() - workflow.timestamp).total_seconds()
            
        if PROMETHEUS_AVAILABLE:
            self.prom_workflow_duration.observe(workflow.total_time)

        self.active_workflows = max(0, self.active_workflows - 1)

        if PROMETHEUS_AVAILABLE:
            self.prom_active_workflows.set(self.active_workflows)

    def record_knowledge_cache_metrics(
        self,
        l1_hits: int = 0,
        l1_misses: int = 0,
        shared_hits: int = 0,
        shared_sets: int = 0,
        account_id: str = "unknown",
    ):
        """Record knowledge cache telemetry into Prometheus counters if available."""

        if not PROMETHEUS_AVAILABLE:
            return

        if l1_hits:
            self.prom_knowledge_hits.labels(layer="l1", account_id=account_id).inc(l1_hits)
        if shared_hits:
            self.prom_knowledge_hits.labels(layer="shared", account_id=account_id).inc(shared_hits)
        if l1_misses:
            self.prom_knowledge_misses.labels(layer="l1", account_id=account_id).inc(l1_misses)
        if shared_sets:
            self.prom_knowledge_sets.labels(layer="shared", account_id=account_id).inc(shared_sets)

    def record_knowledge_memory_size(self, account_id: str, size: int):
        """Set per-account knowledge memory size gauge."""

        if not PROMETHEUS_AVAILABLE:
            return
        self.prom_knowledge_memory_size.labels(account_id=account_id).set(size)
    
    def add_tool_to_workflow(self, workflow_id: str, tool_name: str):
        """Add a tool to workflow tracking."""
        workflow = next(
            (w for w in self.workflow_metrics if w.workflow_id == workflow_id),
            None
        )
        
        if workflow:
            workflow.tools_used.append(tool_name)
    
    def increment_state_transitions(self, workflow_id: str):
        """Increment state transitions for a workflow."""
        workflow = next(
            (w for w in self.workflow_metrics if w.workflow_id == workflow_id),
            None
        )
        
        if workflow:
            workflow.state_transitions += 1
    
    def get_tool_statistics(self) -> Dict[str, Any]:
        """Get comprehensive tool statistics."""
        stats = {
            "total_tools": len(self.tool_metrics),
            "total_calls": sum(m.total_calls for m in self.tool_metrics.values()),
            "success_rate": self._calculate_success_rate(),
            "most_used_tools": self._get_most_used_tools(5),
            "slowest_tools": self._get_slowest_tools(5),
            "error_prone_tools": self._get_error_prone_tools(5),
            "tool_details": {
                name: asdict(metrics) 
                for name, metrics in self.tool_metrics.items()
            }
        }
        return stats
    
    def get_workflow_statistics(self) -> Dict[str, Any]:
        """Get workflow statistics."""
        if not self.workflow_metrics:
            return {
                "total_workflows": 0,
                "active_workflows": self.active_workflows
            }
        
        successful = sum(1 for w in self.workflow_metrics if w.success)
        avg_duration = sum(w.total_time for w in self.workflow_metrics) / len(self.workflow_metrics)
        
        return {
            "total_workflows": len(self.workflow_metrics),
            "active_workflows": self.active_workflows,
            "success_rate": successful / len(self.workflow_metrics),
            "avg_duration": avg_duration,
            "avg_tools_per_workflow": sum(len(w.tools_used) for w in self.workflow_metrics) / len(self.workflow_metrics),
            "recent_workflows": [
                {
                    "id": w.workflow_id,
                    "tools": w.tools_used,
                    "duration": w.total_time,
                    "success": w.success,
                    "timestamp": w.timestamp.isoformat()
                }
                for w in self.workflow_metrics[-10:]  # Last 10 workflows
            ]
        }
    
    def export_metrics(self):
        """Export metrics to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Export tool metrics
        tool_stats = self.get_tool_statistics()
        tool_file = self.export_path / f"tool_metrics_{timestamp}.json"
        with open(tool_file, 'w') as f:
            json.dump(tool_stats, f, indent=2, default=str)
        
        # Export workflow metrics
        workflow_stats = self.get_workflow_statistics()
        workflow_file = self.export_path / f"workflow_metrics_{timestamp}.json"
        with open(workflow_file, 'w') as f:
            json.dump(workflow_stats, f, indent=2, default=str)
        
        logger.info(f"Metrics exported to {self.export_path}")
        
        return tool_file, workflow_file
    
    def get_prometheus_metrics(self) -> bytes:
        """Get Prometheus metrics in text format."""
        if PROMETHEUS_AVAILABLE:
            return generate_latest()
        return b""
    
    def _calculate_success_rate(self) -> float:
        """Calculate overall success rate."""
        total_success = sum(m.successful_calls for m in self.tool_metrics.values())
        total_calls = sum(m.total_calls for m in self.tool_metrics.values())
        
        if total_calls == 0:
            return 0.0
        
        return total_success / total_calls
    
    def _get_most_used_tools(self, n: int) -> List[Dict[str, Any]]:
        """Get n most used tools."""
        sorted_tools = sorted(
            self.tool_metrics.values(),
            key=lambda m: m.total_calls,
            reverse=True
        )
        
        return [
            {
                "name": m.tool_name,
                "calls": m.total_calls,
                "success_rate": m.successful_calls / m.total_calls if m.total_calls > 0 else 0
            }
            for m in sorted_tools[:n]
        ]
    
    def _get_slowest_tools(self, n: int) -> List[Dict[str, Any]]:
        """Get n slowest tools."""
        sorted_tools = sorted(
            self.tool_metrics.values(),
            key=lambda m: m.avg_execution_time,
            reverse=True
        )
        
        return [
            {
                "name": m.tool_name,
                "avg_time": m.avg_execution_time,
                "max_time": m.max_execution_time
            }
            for m in sorted_tools[:n]
        ]
    
    def _get_error_prone_tools(self, n: int) -> List[Dict[str, Any]]:
        """Get n most error-prone tools."""
        tools_with_errors = [
            m for m in self.tool_metrics.values() 
            if m.failed_calls > 0
        ]
        
        sorted_tools = sorted(
            tools_with_errors,
            key=lambda m: m.failed_calls / m.total_calls,
            reverse=True
        )
        
        return [
            {
                "name": m.tool_name,
                "error_rate": m.failed_calls / m.total_calls,
                "failed_calls": m.failed_calls,
                "recent_errors": m.error_messages[-3:]  # Last 3 errors
            }
            for m in sorted_tools[:n]
        ]
    
    def _classify_error(self, error_message: str) -> str:
        """Classify error type from message."""
        error_lower = error_message.lower()
        
        if "timeout" in error_lower:
            return "timeout"
        elif "memory" in error_lower:
            return "memory"
        elif "file not found" in error_lower or "no such file" in error_lower:
            return "file_not_found"
        elif "permission" in error_lower:
            return "permission"
        elif "network" in error_lower or "connection" in error_lower:
            return "network"
        elif "invalid" in error_lower or "malformed" in error_lower:
            return "validation"
        else:
            return "unknown"


# Global metrics collector instance
metrics_collector = MetricsCollector()


class MonitoredTool:
    """Decorator for monitoring tool execution."""
    
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
    
    def __call__(self, func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            error_message = None
            success = False
            
            try:
                result = func(*args, **kwargs)
                success = True
                return result
            except Exception as e:
                error_message = str(e)
                raise
            finally:
                execution_time = time.time() - start_time
                metrics_collector.record_tool_call(
                    self.tool_name,
                    execution_time,
                    success,
                    error_message
                )
        
        return wrapper


def get_metrics_summary() -> Dict[str, Any]:
    """Get a summary of all metrics."""
    return {
        "tools": metrics_collector.get_tool_statistics(),
        "workflows": metrics_collector.get_workflow_statistics(),
        "health": {
            "active_workflows": metrics_collector.active_workflows,
            "total_tools_registered": len(metrics_collector.tool_metrics),
            "overall_success_rate": metrics_collector._calculate_success_rate()
        }
    }


def export_metrics_report() -> tuple:
    """Export comprehensive metrics report."""
    return metrics_collector.export_metrics()
