#!/bin/bash
set -e

# Pact Broker setup script for Brain Researcher contract testing
# Legacy standalone API gateway contract coverage is opt-in only.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../../" && pwd)"

echo "🚀 Setting up Pact Broker for Brain Researcher contract testing..."

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is required but not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is required but not installed. Please install Docker Compose first."
    exit 1
fi

# Create .env file for configuration
cat > "${SCRIPT_DIR}/.env" << EOF
# Pact Broker Configuration
PACT_BROKER_DATABASE_URL=postgres://pact_broker:password@postgres:5432/pact_broker
PACT_BROKER_BASIC_AUTH_USERNAME=pact_workshop
PACT_BROKER_BASIC_AUTH_PASSWORD=pact_workshop

# GitHub Integration (optional - replace with your values)
GITHUB_REPO=YOUR_GITHUB_USER/brain_researcher
GITHUB_TOKEN=YOUR_GITHUB_TOKEN

# Service URLs for testing
ORCHESTRATOR_URL=http://localhost:3001
AGENT_URL=http://localhost:8000
NEUROKG_URL=http://localhost:5000
WEB_UI_URL=http://localhost:3000
BR_ENABLE_LEGACY_GATEWAY_TESTS=0
# Optional legacy standalone gateway compatibility surface:
# API_GATEWAY_URL=http://localhost:8080
EOF

echo "📝 Created .env configuration file"

# Start Pact Broker
echo "🐳 Starting Pact Broker services..."
cd "${SCRIPT_DIR}"
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
timeout=60
counter=0

while [ $counter -lt $timeout ]; do
    if curl -f -s http://localhost:9292/diagnostic/status/heartbeat > /dev/null 2>&1; then
        echo "✅ Pact Broker is ready!"
        break
    fi
    
    counter=$((counter + 5))
    echo "Waiting for Pact Broker... ($counter/$timeout seconds)"
    sleep 5
done

if [ $counter -ge $timeout ]; then
    echo "❌ Timeout waiting for Pact Broker to start"
    docker-compose logs pact-broker
    exit 1
fi

# Set up initial webhooks (if GitHub token is configured)
if [ "$GITHUB_TOKEN" != "YOUR_GITHUB_TOKEN" ] && [ -n "$GITHUB_TOKEN" ]; then
    echo "🔗 Setting up GitHub webhooks..."
    
    # Create webhook for contract changes
    curl -X POST http://localhost:9292/webhooks \
        -H 'Content-Type: application/json' \
        -H 'Authorization: Basic cGFjdF93b3Jrc2hvcDpwYWN0X3dvcmtzaG9w' \
        -d '{
            "description": "GitHub commit status for contract verification",
            "events": ["provider_verification_published"],
            "request": {
                "method": "POST",
                "url": "https://api.github.com/repos/'$GITHUB_REPO'/statuses/${pactbroker.consumerVersionNumber}",
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "token '$GITHUB_TOKEN'"
                },
                "body": {
                    "state": "${pactbroker.githubVerificationStatus}",
                    "description": "Pact verification result",
                    "context": "pact-broker/verification",
                    "target_url": "${pactbroker.verificationResultUrl}"
                }
            }
        }' || echo "⚠️  Failed to create GitHub webhook (this is optional)"
else
    echo "⚠️  GitHub integration not configured (set GITHUB_TOKEN in .env to enable)"
fi

# Create initial environments and teams
echo "🏗️  Setting up environments..."

# Production environment
curl -X PUT http://localhost:9292/environments/production \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Basic cGFjdF93b3Jrc2hvcDpwYWN0X3dvcmtzaG9w' \
    -d '{
        "name": "production",
        "displayName": "Production",
        "production": true
    }' || echo "⚠️  Production environment may already exist"

# Staging environment  
curl -X PUT http://localhost:9292/environments/staging \
    -H 'Content-Type: application/json' \
    -H 'Authorization: Basic cGFjdF93b3Jrc2hvcDpwYWN0X3dvcmtzaG9w' \
    -d '{
        "name": "staging", 
        "displayName": "Staging",
        "production": false
    }' || echo "⚠️  Staging environment may already exist"

echo ""
echo "🎉 Pact Broker setup complete!"
echo ""
echo "📍 Access URLs:"
echo "   Pact Broker UI: http://localhost:9292"
echo "   Username: pact_workshop"
echo "   Password: pact_workshop"
echo ""
echo "🛠️  Next steps:"
echo "   1. Run consumer contract tests: pytest tests/contracts/consumers/"
echo "   2. Run provider verification tests: pytest tests/contracts/providers/"
echo "   3. Check compatibility: python tests/contracts/compatibility_checker.py"
echo "   4. Legacy gateway contracts remain opt-in: export BR_ENABLE_LEGACY_GATEWAY_TESTS=1"
echo ""
echo "📊 Monitor your contracts at: http://localhost:9292"
echo ""

# Create quick start script
cat > "${PROJECT_ROOT}/run_contract_tests.sh" << 'EOF'
#!/bin/bash
# Quick contract testing script for Brain Researcher

set -e

echo "🧪 Running Brain Researcher contract tests..."

# Ensure Pact Broker is running
if ! curl -f -s http://localhost:9292/diagnostic/status/heartbeat > /dev/null 2>&1; then
    echo "⚠️  Pact Broker not running. Starting..."
    cd tests/contracts/pact_broker
    docker-compose up -d
    sleep 10
fi

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r tests/contracts/requirements.txt

# Run consumer tests
echo "🏃 Running consumer contract tests..."
pytest tests/contracts/consumers/ -v

# Run provider verification tests
echo "🔍 Running provider verification tests..."
pytest tests/contracts/providers/ -v

# Check compatibility
echo "🔎 Checking contract compatibility..."
python tests/contracts/compatibility_checker.py --verbose

echo "✅ All contract tests completed!"
echo "📊 View results at: http://localhost:9292"
echo "ℹ️  Legacy gateway contracts require BR_ENABLE_LEGACY_GATEWAY_TESTS=1"
EOF

chmod +x "${PROJECT_ROOT}/run_contract_tests.sh"
echo "📜 Created run_contract_tests.sh script in project root"
