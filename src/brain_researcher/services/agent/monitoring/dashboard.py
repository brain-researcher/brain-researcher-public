"""Monitoring Dashboard API for Brain Researcher Agent

Provides REST API endpoints and WebSocket support for real-time monitoring.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from brain_researcher.services.agent.monitoring.alerting import (
    Alert,
    AlertManager,
    AlertSeverity,
)
from brain_researcher.services.agent.monitoring.health_monitor import (
    HealthMonitor,
    HealthStatus,
    ServiceType,
)
from brain_researcher.services.agent.monitoring.metrics_collector import (
    MetricsCollector,
)

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    uptime: float
    services: Dict[str, Any]
    metrics: Dict[str, Any]
    timestamp: str


class AlertRequest(BaseModel):
    """Alert acknowledgment request."""

    fingerprint: str
    action: str  # acknowledge, resolve


class MetricsQuery(BaseModel):
    """Metrics query parameters."""

    metric_names: List[str]
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    resolution: str = "1m"  # 1m, 5m, 15m, 1h


class CliMetricRequest(BaseModel):
    """Payload for CLI metric ingestion."""

    command: str
    duration_ms: float
    status: str
    job_kind: Optional[str] = None


class MonitoringDashboard:
    """Main monitoring dashboard service."""

    def __init__(
        self,
        health_monitor: Optional[HealthMonitor] = None,
        alert_manager: Optional[AlertManager] = None,
        metrics_collector: Optional[MetricsCollector] = None,
    ):
        """Initialize dashboard.

        Args:
            health_monitor: Health monitoring instance
            alert_manager: Alert manager instance
            metrics_collector: Metrics collector instance
        """
        self.health_monitor = health_monitor or HealthMonitor()
        self.alert_manager = alert_manager or AlertManager()
        self.metrics_collector = metrics_collector or MetricsCollector()

        # WebSocket connections for real-time updates
        self.websocket_clients: List[WebSocket] = []

        # Create FastAPI app
        self.app = self._create_app()

    def _create_app(self) -> FastAPI:
        """Create FastAPI application with monitoring endpoints."""
        app = FastAPI(
            title="Brain Researcher Monitoring",
            description="Production monitoring dashboard",
            version="1.0.0",
        )

        # Health endpoints
        @app.get("/health")
        async def health_check() -> HealthResponse:
            """Basic health check endpoint."""
            status = self.health_monitor.get_status()
            return HealthResponse(
                status=status["status"],
                uptime=status["uptime_seconds"],
                services=status["services"],
                metrics=status["metrics"],
                timestamp=status["timestamp"],
            )

        @app.get("/health/live")
        async def liveness_probe():
            """Kubernetes liveness probe."""
            return {"status": "alive"}

        @app.get("/health/ready")
        async def readiness_probe():
            """Kubernetes readiness probe."""
            status = self.health_monitor.get_status()
            if status["status"] in ["healthy", "degraded"]:
                return {"status": "ready"}
            else:
                raise HTTPException(status_code=503, detail="Service not ready")

        # Metrics endpoints
        @app.post("/metrics/query")
        async def query_metrics(query: MetricsQuery):
            """Query historical metrics."""
            return await self.metrics_collector.query(
                metric_names=query.metric_names,
                start_time=query.start_time,
                end_time=query.end_time,
                resolution=query.resolution,
            )

        @app.get("/metrics/current")
        async def current_metrics():
            """Get current metrics snapshot."""
            return self.metrics_collector.get_current_metrics()

        @app.post("/metrics/cli")
        async def ingest_cli_metrics(payload: CliMetricRequest):
            """Record CLI metrics forwarded from local commands."""
            self.metrics_collector.record_cli_command(
                command=payload.command,
                duration_ms=payload.duration_ms,
                status=payload.status,
                job_kind=payload.job_kind,
            )
            return {"status": "ok"}

        @app.get("/metrics", response_class=PlainTextResponse)
        async def prometheus_metrics():
            """Expose Prometheus-formatted metrics for scraping."""
            return PlainTextResponse(
                self.metrics_collector.export_prometheus(),
                media_type="text/plain; version=0.0.4",
            )

        # Alert endpoints
        @app.get("/alerts/active")
        async def get_active_alerts():
            """Get list of active alerts."""
            alerts = self.alert_manager.get_active_alerts()
            return {
                "alerts": [
                    {
                        "fingerprint": state.alert.fingerprint,
                        "title": state.alert.title,
                        "severity": state.alert.severity.value,
                        "count": state.count,
                        "first_seen": state.first_seen.isoformat(),
                        "acknowledged": state.acknowledged,
                    }
                    for state in alerts
                ]
            }

        @app.get("/alerts/summary")
        async def get_alert_summary():
            """Get alert summary statistics."""
            return self.alert_manager.get_alert_summary()

        @app.post("/alerts/action")
        async def alert_action(request: AlertRequest):
            """Acknowledge or resolve an alert."""
            if request.action == "acknowledge":
                self.alert_manager.acknowledge_alert(request.fingerprint)
            elif request.action == "resolve":
                self.alert_manager.resolve_alert(request.fingerprint)
            else:
                raise HTTPException(status_code=400, detail="Invalid action")

            return {"status": "success"}

        # WebSocket for real-time updates
        @app.websocket("/ws/metrics")
        async def websocket_metrics(websocket: WebSocket):
            """WebSocket endpoint for real-time metrics."""
            await websocket.accept()
            self.websocket_clients.append(websocket)

            try:
                while True:
                    # Send metrics every second
                    metrics = self.metrics_collector.get_current_metrics()
                    await websocket.send_json(metrics)
                    await asyncio.sleep(1)

            except WebSocketDisconnect:
                self.websocket_clients.remove(websocket)

        # Dashboard UI
        @app.get("/dashboard")
        async def dashboard():
            """Serve monitoring dashboard HTML."""
            return HTMLResponse(content=self._get_dashboard_html())

        # Tool performance endpoints
        @app.get("/tools/performance")
        async def tool_performance():
            """Get tool performance metrics."""
            return self.metrics_collector.get_tool_metrics()

        @app.get("/tools/{tool_name}/metrics")
        async def tool_specific_metrics(tool_name: str):
            """Get metrics for specific tool."""
            metrics = self.metrics_collector.get_tool_metrics(tool_name)
            if not metrics:
                raise HTTPException(status_code=404, detail="Tool not found")
            return metrics

        return app

    async def start(self):
        """Start monitoring services."""
        # Start health monitoring
        await self.health_monitor.start_monitoring()

        # Start metrics collection
        await self.metrics_collector.start_collection()

        # Register alert handler for WebSocket broadcast
        self.alert_manager.add_alert_handler(self._broadcast_alert)

        logger.info("Monitoring dashboard started")

    async def stop(self):
        """Stop monitoring services."""
        await self.health_monitor.stop_monitoring()
        await self.metrics_collector.stop_collection()

        # Close WebSocket connections
        for client in self.websocket_clients:
            await client.close()

        logger.info("Monitoring dashboard stopped")

    async def _broadcast_alert(self, alert: Alert):
        """Broadcast alert to WebSocket clients.

        Args:
            alert: Alert to broadcast
        """
        message = {
            "type": "alert",
            "data": {
                "id": alert.alert_id,
                "title": alert.title,
                "severity": alert.severity.value,
                "timestamp": alert.timestamp.isoformat(),
            },
        }

        # Send to all connected clients
        disconnected = []
        for client in self.websocket_clients:
            try:
                await client.send_json(message)
            except:
                disconnected.append(client)

        # Remove disconnected clients
        for client in disconnected:
            self.websocket_clients.remove(client)

    def _get_dashboard_html(self) -> str:
        """Get dashboard HTML content."""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Brain Researcher Monitoring</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                .metric {
                    display: inline-block;
                    margin: 10px;
                    padding: 15px;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                }
                .healthy { background-color: #d4edda; }
                .degraded { background-color: #fff3cd; }
                .unhealthy { background-color: #f8d7da; }
                .alert {
                    margin: 10px 0;
                    padding: 10px;
                    border-left: 4px solid;
                }
                .alert-warning { border-color: #ffc107; background-color: #fff3cd; }
                .alert-error { border-color: #dc3545; background-color: #f8d7da; }
                .alert-critical { border-color: #721c24; background-color: #f8d7da; }
                #metrics-chart { width: 100%; height: 300px; }
            </style>
        </head>
        <body>
            <h1>Brain Researcher Monitoring Dashboard</h1>

            <div id="health-status">
                <h2>System Health</h2>
                <div id="health-metrics"></div>
            </div>

            <div id="planner-status">
                <h2>Planner & Catalog</h2>
                <div id="planner-metrics"></div>
            </div>

            <div id="performance-metrics">
                <h2>Performance Metrics</h2>
                <canvas id="metrics-chart"></canvas>
            </div>

            <div id="active-alerts">
                <h2>Active Alerts</h2>
                <div id="alerts-list"></div>
            </div>

            <div id="tool-performance">
                <h2>Tool Performance</h2>
                <div id="tools-table"></div>
            </div>

            <script>
                // WebSocket connection for real-time updates
                const ws = new WebSocket('ws://localhost:8000/ws/metrics');

                ws.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    updateMetrics(data);
                };

                // Fetch and display health status
                async function updateHealth() {
                    const response = await fetch('/health');
                    const data = await response.json();

                    const healthDiv = document.getElementById('health-metrics');
                    healthDiv.innerHTML = `
                        <div class="metric ${data.status}">
                            <strong>Status:</strong> ${data.status}<br>
                            <strong>Uptime:</strong> ${Math.floor(data.uptime / 3600)}h ${Math.floor((data.uptime % 3600) / 60)}m
                        </div>
                        <div class="metric">
                            <strong>CPU:</strong> ${data.metrics.cpu_percent?.toFixed(1)}%<br>
                            <strong>Memory:</strong> ${data.metrics.memory_percent?.toFixed(1)}%<br>
                            <strong>Disk:</strong> ${data.metrics.disk_percent?.toFixed(1)}%
                        </div>
                    `;
                }

                // Fetch and display alerts
                async function updateAlerts() {
                    const response = await fetch('/alerts/active');
                    const data = await response.json();

                    const alertsDiv = document.getElementById('alerts-list');
                    if (data.alerts.length === 0) {
                        alertsDiv.innerHTML = '<p>No active alerts</p>';
                    } else {
                        alertsDiv.innerHTML = data.alerts.map(alert => `
                            <div class="alert alert-${alert.severity}">
                                <strong>${alert.title}</strong><br>
                                Severity: ${alert.severity} | Count: ${alert.count}<br>
                                First seen: ${new Date(alert.first_seen).toLocaleString()}
                                ${alert.acknowledged ? ' (Acknowledged)' : ''}
                            </div>
                        `).join('');
                    }
                }

                // Update metrics chart
                function updateMetrics(data) {
                    // Render planner & catalog metrics (latest values)
                    const plannerDiv = document.getElementById('planner-metrics');
                    const metrics = {
                        planner_requests_total: 'Planner Requests',
                        planner_errors_total: 'Planner Errors',
                        planner_request_duration_ms: 'Planner Latency (ms, latest)',
                        catalog_load_failures_total: 'Catalog Load Failures',
                        tool_executions_total: 'Tool Executions (latest sample)',
                        agent_errors_total: 'Agent Errors'
                    };
                    const rows = [];
                    for (const [name, label] of Object.entries(metrics)) {
                        if (data[name]) {
                            rows.push(`<div class="metric"><strong>${label}:</strong> ${data[name].value}</div>`);
                        }
                    }
                    plannerDiv.innerHTML = rows.join('') || '<p>No planner metrics yet.</p>';
                }

                // Fetch tool performance
                async function updateToolPerformance() {
                    const response = await fetch('/tools/performance');
                    const data = await response.json();

                    const toolsDiv = document.getElementById('tools-table');
                    // Render tool performance table
                    // Implementation would go here
                }

                // Initial load and periodic updates
                updateHealth();
                updateAlerts();
                updateToolPerformance();

                setInterval(updateHealth, 5000);
                setInterval(updateAlerts, 10000);
                setInterval(updateToolPerformance, 30000);
            </script>
        </body>
        </html>
        """
