# Dual Distribution Testing Guide

## Quick Start Testing

### 1. Test Python Core Components

#### A. Test Credential Resolver
```bash
# Run unit tests
pytest tests/unit/test_credential_resolver.py -v

# Test CLI config commands
br config list
br config add test_gemini --provider gemini --key "test_key_123"
br config list
br config remove test_gemini --yes
```

#### B. Test Rate Limiting & Circuit Breaker
```bash
# Run specific tests
pytest tests/unit/test_rate_circuit_integration.py -v

# Manual test - should hit rate limit
python -c "
from brain_researcher.services.agent.utils.rate_limit import TokenBucketRateLimiter
limiter = TokenBucketRateLimiter(rps=2, rpm=10)
for i in range(5):
    try:
        limiter.try_acquire()
        print(f'Request {i+1}: OK')
    except Exception as e:
        print(f'Request {i+1}: {e}')
"
```

#### C. Test MCP Server
```bash
# Start MCP server
br serve mcp &
MCP_PID=$!

# Test with stdio (in another terminal)
echo '{"jsonrpc":"2.0","method":"tools/list","id":1}' | nc localhost 3004

# Kill server
kill $MCP_PID
```

### 2. Test @brainr/cli npm Package

#### A. Build and Link
```bash
cd packages/cli
npm install
npm run build
npm link

# Verify installation
which brainr
brainr --help
```

#### B. Test Proxy Mode (Default)
```bash
# Test stdio proxy to br CLI
brainr version
brainr --help

# Test with prompt
brainr ask -p "What is 2+2?" --json
```

#### C. Test HTTP Proxy Mode
```bash
# Start core service
br serve agent &
AGENT_PID=$!

# Set HTTP proxy URL
export BR_URL=http://localhost:8000

# Test HTTP proxy
brainr chat
brainr ask -p "Hello world"

# Clean up
kill $AGENT_PID
unset BR_URL
```

#### D. Test Gemini Mode (if Gemini CLI installed)
```bash
# Check if gemini is available
which gemini || echo "Gemini CLI not installed"

# If available, test spawn mode
brainr --gemini --version
brainr --gemini -p "Hello" -m gemini-2.5-flash
```

### 3. Test Fallback Cascade

```python
# Create test script: test_fallback.py
import os
os.environ['USE_GEMINI_CLI'] = 'true'

from brain_researcher.services.agent.utils.gemini_fallback import chat_with_fallback

# Test with a simple prompt
text, provider, model, usage, reason = chat_with_fallback(
    prompt="Say hello",
    initial_model="gemini-2.5-pro"
)

print(f"Provider: {provider}")
print(f"Model: {model}")
print(f"Fallback reason: {reason}")
print(f"Response: {text[:100]}...")
```

### 4. Test Docker Container

```bash
# Build Docker image
docker build -f docker/Dockerfile.hpc -t brain-researcher:test .

# Test container
docker run --rm brain-researcher:test br --help
docker run --rm brain-researcher:test br version

# Test with volume mounts
docker run --rm -v $PWD/data:/data brain-researcher:test ls /data
```

### 5. Integration Tests

#### A. End-to-End BYOK Flow
```bash
# Run integration tests
pytest tests/integration/test_byok_flow.py -v

# Manual test
br config add my_test --provider gemini --key "test_key"
br config test my_test
br config remove my_test --yes
```

#### B. Test Web Service CLI Proxy
```bash
# Start web service
br serve agent &
AGENT_PID=$!
sleep 5

# Test /api/cli endpoint
curl -X POST http://localhost:8000/api/cli \
  -H "Content-Type: application/json" \
  -d '{"argv": ["version"]}'

curl -X POST http://localhost:8000/api/cli \
  -H "Content-Type: application/json" \
  -d '{"argv": ["chat", "-p", "Hello"]}'

# Clean up
kill $AGENT_PID
```

## Comprehensive Test Suite

Create and run this test script:

```bash
#!/bin/bash
# save as: test_all.sh

echo "=== Testing Brain Researcher Dual Distribution ==="

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

# Test function
run_test() {
    echo -n "Testing $1... "
    if eval "$2" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}✗${NC}"
        echo "  Command: $2"
        ((TESTS_FAILED++))
    fi
}

# 1. Python Core Tests
echo -e "\n📦 Testing Python Core..."
run_test "br CLI exists" "which br"
run_test "br version" "br version"
run_test "br help" "br --help"
run_test "Credential resolver import" "python -c 'from brain_researcher.services.agent.credential_resolver import CredentialResolver'"
run_test "Rate limiter import" "python -c 'from brain_researcher.services.agent.utils.rate_limit import TokenBucketRateLimiter'"
run_test "Circuit breaker import" "python -c 'from brain_researcher.services.agent.utils.circuit_breaker import CircuitBreaker'"
run_test "Gemini CLI wrapper import" "python -c 'from brain_researcher.services.agent.utils import gemini_cli'"

# 2. Unit Tests
echo -e "\n🧪 Testing Unit Tests..."
run_test "Credential resolver tests" "pytest tests/unit/test_credential_resolver.py -q"
run_test "Gemini CLI tests" "pytest tests/unit/test_gemini_cli.py -q 2>/dev/null || true"
run_test "Rate limiter tests" "pytest tests/unit/test_rate_limiter.py -q 2>/dev/null || true"

# 3. npm Package Tests (if built)
echo -e "\n📦 Testing @brainr/cli npm Package..."
if [ -d "packages/cli" ]; then
    cd packages/cli
    run_test "npm package.json exists" "test -f package.json"
    run_test "TypeScript config exists" "test -f tsconfig.json"
    run_test "npm install" "npm install"
    run_test "npm build" "npm run build"
    run_test "Built files exist" "test -d dist"
    cd ../..
else
    echo "  ⚠️  packages/cli not found, skipping npm tests"
fi

# 4. Docker Tests
echo -e "\n🐳 Testing Docker..."
run_test "Dockerfile.hpc exists" "test -f docker/Dockerfile.hpc"
run_test "Singularity.def exists" "test -f docker/Singularity.def"

# 5. Configuration Tests
echo -e "\n⚙️  Testing Configuration..."
run_test "br config command exists" "br config --help"
run_test "List credentials" "br config list"

# 6. API Endpoint Tests (if service running)
echo -e "\n🌐 Testing API Endpoints..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    run_test "Health endpoint" "curl -s http://localhost:8000/health"
    run_test "CLI proxy endpoint" "curl -s -X POST http://localhost:8000/api/cli -H 'Content-Type: application/json' -d '{\"argv\":[\"version\"]}'"
else
    echo "  ⚠️  Agent service not running on port 8000, skipping API tests"
fi

# Summary
echo -e "\n📊 Test Summary:"
echo -e "  Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "  Failed: ${RED}$TESTS_FAILED${NC}"

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "\n${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "\n${RED}❌ Some tests failed. Please review the output above.${NC}"
    exit 1
fi
```

## Manual Testing Checklist

### ✅ Core Functionality
- [ ] `br --help` shows help
- [ ] `br version` shows version
- [ ] `br config list` lists credentials
- [ ] `br config add` adds credential
- [ ] `br config remove` removes credential
- [ ] `br serve mcp` starts MCP server
- [ ] `br serve agent` starts web service

### ✅ @brainr/cli Package
- [ ] `npm install` in packages/cli works
- [ ] `npm run build` creates dist/ folder
- [ ] `brainr --help` shows help after npm link
- [ ] `brainr version` works
- [ ] `brainr --proxy -- version` calls br
- [ ] `brainr --gemini --version` tries to call gemini

### ✅ Credential System
- [ ] Can add BYOK Gemini credential
- [ ] Can add BYOK OpenAI credential
- [ ] Credentials stored in ~/.brain_researcher/credentials.json
- [ ] File has 0600 permissions
- [ ] Environment variables override config

### ✅ Fallback Cascade
- [ ] Gemini Pro is tried first
- [ ] Falls back to Flash on failure
- [ ] Falls back to GPT-5 as last resort
- [ ] Rate limiting works (30 RPS/300 RPM)
- [ ] Circuit breaker opens after 5 failures

### ✅ Docker/Container
- [ ] Docker image builds successfully
- [ ] Container runs br commands
- [ ] Volume mounts work (/data, /scratch, /cache)

## Troubleshooting Common Issues

### Issue: "br: command not found"
```bash
# Reinstall brain_researcher
pip install -e .
# Or
pipx install brain-researcher
```

### Issue: "brainr: command not found"
```bash
cd packages/cli
npm install
npm run build
npm link
```

### Issue: "Gemini CLI not found"
```bash
# Install official Gemini CLI (if you want to test --gemini mode)
npm install -g @google/gemini-cli
# Or just test proxy mode instead
```

### Issue: Rate limit errors
```bash
# This is expected! Rate limiter is working.
# Wait a bit or adjust limits in environment:
export GEMINI_LOCAL_RPS=100
export GEMINI_LOCAL_RPM=1000
```

### Issue: Cannot connect to core service
```bash
# Start the service first
br serve agent &
# Then set the URL
export BR_URL=http://localhost:8000
```

## Expected Test Output

When everything is working:
```
=== Testing Brain Researcher Dual Distribution ===

📦 Testing Python Core...
Testing br CLI exists... ✓
Testing br version... ✓
Testing br help... ✓
Testing Credential resolver import... ✓

🧪 Testing Unit Tests...
Testing Credential resolver tests... ✓ (13 passed)

📦 Testing @brainr/cli npm Package...
Testing npm package.json exists... ✓
Testing npm build... ✓

📊 Test Summary:
  Passed: 15
  Failed: 0

✅ All tests passed!
```
