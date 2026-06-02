#!/usr/bin/env python
"""Launch Production Monitoring Service

Starts the monitoring dashboard and all monitoring components.
"""

import asyncio
import uvicorn
import signal
import sys
from datetime import datetime

from brain_researcher.services.agent.monitoring_integration import get_monitoring_integration


class MonitoringServiceLauncher:
    """Production monitoring service launcher."""

    def __init__(self):
        self.monitoring = get_monitoring_integration()
        self.server = None

    async def start_services(self):
        """Start all monitoring services."""
        print("\n" + "="*70)
        print("  🚀 BRAIN RESEARCHER MONITORING SERVICE")
        print("="*70)
        print(f"  Starting at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70 + "\n")

        # Start monitoring components
        print("▶️  Starting monitoring components...")
        await self.monitoring.start()
        print("  ✅ Health Monitor: Active")
        print("  ✅ Metrics Collector: Active")
        print("  ✅ Alert Manager: Active")
        print("  ✅ Circuit Breakers: Armed")

        # Register some demo tools for monitoring
        await self._register_demo_tools()

        print("\n📊 Dashboard Endpoints:")
        print("  Main Dashboard:    http://localhost:8100/dashboard")
        print("  Health Status:     http://localhost:8100/health")
        print("  Current Metrics:   http://localhost:8100/metrics/current")
        print("  Active Alerts:     http://localhost:8100/alerts/active")
        print("  Alert History:     http://localhost:8100/alerts/history")
        print("  Tool Metrics:      http://localhost:8100/metrics/tools")
        print("  System Metrics:    http://localhost:8100/metrics/system")

        print("\n🔧 WebSocket Endpoints:")
        print("  Real-time Metrics: ws://localhost:8100/ws/metrics")
        print("  Real-time Alerts:  ws://localhost:8100/ws/alerts")

        print("\n" + "="*70)
        print("  ✨ Monitoring Service Ready!")
        print("  Press Ctrl+C to shutdown")
        print("="*70 + "\n")

    async def _register_demo_tools(self):
        """Register demo tools for monitoring."""
        from brain_researcher.services.agent.monitoring import ServiceType

        # Register some services for demo
        self.monitoring.health_monitor.register_service(
            "glm_analysis",
            ServiceType.TOOL
        )
        self.monitoring.health_monitor.register_service(
            "fmri_preprocessing",
            ServiceType.TOOL
        )
        self.monitoring.health_monitor.register_service(
            "connectivity_analysis",
            ServiceType.TOOL
        )

        # Create some initial metrics
        self.monitoring.metrics_collector.increment("agent_requests_total", 0)
        self.monitoring.metrics_collector.record("agent_request_duration", 0)

    async def shutdown(self):
        """Gracefully shutdown services."""
        print("\n⏹️  Shutting down monitoring service...")
        await self.monitoring.stop()
        print("  ✅ All services stopped gracefully")

    def run(self):
        """Run the monitoring service."""
        # Setup signal handlers
        def signal_handler(sig, frame):
            print("\n  🛑 Shutdown signal received...")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Get the FastAPI app
        app = self.monitoring.get_monitoring_dashboard_app()

        # Create async loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # Start monitoring services
            loop.run_until_complete(self.start_services())

            # Run the FastAPI server
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=8100,
                log_level="info",
                access_log=True,
                loop="asyncio"
            )

        except KeyboardInterrupt:
            loop.run_until_complete(self.shutdown())
        finally:
            loop.close()


def main():
    """Main entry point."""
    launcher = MonitoringServiceLauncher()
    launcher.run()


if __name__ == "__main__":
    main()