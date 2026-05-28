#!/bin/bash

# Brain Researcher Monitoring Stack Startup Script
set -e

MONITORING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$MONITORING_DIR"

echo "🚀 Starting Brain Researcher Monitoring Stack..."

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Creating from template..."
    cp .env.example .env
    echo "📝 Please edit .env file with your configuration before running again."
    exit 1
fi

# Create necessary directories
echo "📁 Creating necessary directories..."
mkdir -p logs/{prometheus,grafana,alertmanager,loki}

# Validate Docker Compose file
echo "✅ Validating Docker Compose configuration..."
docker-compose -f docker-compose.monitoring.yml config > /dev/null

# Pull latest images
echo "📦 Pulling latest monitoring images..."
docker-compose -f docker-compose.monitoring.yml pull

# Start the monitoring stack
echo "🏃 Starting monitoring services..."
docker-compose -f docker-compose.monitoring.yml up -d

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 30

# Health checks
echo "🏥 Performing health checks..."

check_service() {
    local service_name=$1
    local port=$2
    local endpoint=${3:-/}
    
    echo -n "  Checking $service_name... "
    if curl -sf "http://localhost:$port$endpoint" > /dev/null 2>&1; then
        echo "✅ OK"
    else
        echo "❌ FAILED"
        return 1
    fi
}

check_service "Prometheus" 9090 "/-/healthy"
check_service "Grafana" 3000 "/api/health"
check_service "AlertManager" 9093 "/-/healthy"
check_service "Loki" 3100 "/ready"
check_service "Node Exporter" 9100 "/metrics"
check_service "cAdvisor" 8080 "/healthz"

echo ""
echo "🎉 Monitoring stack is running!"
echo ""
echo "📊 Access URLs:"
echo "  • Grafana:      http://localhost:3000"
echo "  • Prometheus:   http://localhost:9090"
echo "  • AlertManager: http://localhost:9093"
echo ""
echo "🔑 Default Grafana credentials:"
echo "  • Username: admin"
echo "  • Password: admin (change in .env file)"
echo ""
echo "📈 Pre-configured dashboards:"
echo "  • Service Health Overview"
echo "  • Performance Metrics"
echo "  • Resource Utilization"
echo "  • Alert Status"
echo ""
echo "🔔 AlertManager is configured for:"
echo "  • Email notifications"
echo "  • Slack integration (if configured)"
echo "  • PagerDuty integration (if configured)"
echo ""
echo "📝 To stop the monitoring stack:"
echo "  docker-compose -f docker-compose.monitoring.yml down"
echo ""
echo "📚 Check runbooks.md for troubleshooting guides"