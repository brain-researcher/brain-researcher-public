"""
Metrics emission helper for LLM router.

Separated into its own module to avoid circular imports.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brain_researcher.services.agent.router import LLMRouteMetadata

logger = logging.getLogger(__name__)

# Global metrics collector instance (lazy-loaded)
_metrics_collector = None


def get_metrics_collector():
    """Get or create global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        try:
            from brain_researcher.services.agent.monitoring.metrics_collector import (
                MetricsCollector,
            )

            _metrics_collector = MetricsCollector()
        except ImportError:
            logger.debug("MetricsCollector not available")
            _metrics_collector = None
    return _metrics_collector


def emit_llm_metrics(metadata: "LLMRouteMetadata") -> None:
    """
    Emit Prometheus metrics for an LLM invocation.

    Args:
        metadata: LLMRouteMetadata from router
    """
    metrics = get_metrics_collector()
    if metrics is None:
        return

    try:
        metrics.record_llm_invocation(
            provider=metadata.provider,
            model=metadata.model,
            route=metadata.route,
            transport=metadata.transport,
            bill_to=metadata.bill_to,
            usage=metadata.usage,
            estimated_cost=metadata.estimated_cost,
            latency_ms=metadata.latency_ms,
            fallback_reason=metadata.fallback_reason,
        )
    except Exception as e:
        logger.debug(f"Failed to emit LLM metrics: {e}")
