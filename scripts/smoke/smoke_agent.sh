#!/usr/bin/env bash
set -euo pipefail

BASE=${1:-http://localhost:8000}
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo "Testing Agent at $BASE"
echo "========================"

# Test /tools endpoint
echo -n "1. /tools endpoint... "
TOOLS=$(curl -s $BASE/tools)
TOTAL=$(echo $TOOLS | jq -r '.metadata.total_tools')
if [ "$TOTAL" -gt 100 ]; then
    echo -e "${GREEN}✓${NC} ($TOTAL tools)"
else
    echo -e "${RED}✗${NC} (only $TOTAL tools)"
fi

# Test /tools/<name>
echo -n "2. /tools/glm_analysis... "
DETAIL=$(curl -s $BASE/tools/glm_analysis)
if echo $DETAIL | jq -e '.name' > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# Test /chat
echo -n "3. /chat endpoint... "
CHAT=$(curl -s -X POST $BASE/chat \
    -H 'Content-Type: application/json' \
    -d '{"query":"What is n-back task?"}')
if echo $CHAT | jq -e '.message.content' > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# Test /act with tool
echo -n "4. /act with tool... "
ACT=$(curl -s -X POST $BASE/act \
    -H 'Content-Type: application/json' \
    -H 'X-Trace-ID: smoke-test-001' \
    -d '{"query":"Find concepts related to hippocampus","tools_whitelist":["find_related_concepts"]}')
if echo $ACT | jq -e '.tool_calls[0].name' > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

# Test trace propagation
echo -n "5. Trace propagation... "
TRACE_RESPONSE=$(curl -sI -X POST $BASE/act \
    -H 'Content-Type: application/json' \
    -H 'X-Trace-ID: test-trace-123' \
    -d '{"query":"test"}' | grep -i x-trace-id)
if echo "$TRACE_RESPONSE" | grep -q "test-trace-123"; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

echo "========================"
echo "Agent smoke test complete"