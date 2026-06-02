#!/bin/bash
set -euo pipefail

echo "🚀 Deploying Brain Researcher to Production"

# 1. Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Docker required"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "Node.js required"; exit 1; }

# 2. Build frontend
echo "📦 Building frontend..."
cd apps/web-ui
npm ci --production
npm run build

# 3. Build Docker images
echo "🐳 Building Docker images..."
docker-compose -f docker-compose.prod.yml build

# 4. Run database migrations
echo "🔄 Running migrations..."
docker-compose -f docker-compose.prod.yml run --rm orchestrator python -m alembic upgrade head

# 5. Deploy services
echo "🚢 Deploying services..."
docker-compose -f docker-compose.prod.yml up -d

# 6. Health checks
echo "❤️ Running health checks..."
sleep 10
curl -f http://localhost:3000 || exit 1
curl -f http://localhost:3004/health || exit 1
curl -f http://localhost:8000/health || exit 1
curl -f http://localhost:5000/health || exit 1

echo "✅ Deployment complete!"
echo "🌐 Visit https://brain-researcher.com"