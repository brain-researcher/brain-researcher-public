#!/usr/bin/env bash
set -euo pipefail

ORCH=${1:-http://localhost:3004}
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo "Testing Orchestrator at $ORCH"
echo "=============================="

# Test LLM-only job
echo -n "1. LLM-only job... "
JOB_RESPONSE=$(curl -s -X POST $ORCH/run \
    -H 'Content-Type: application/json' \
    -d '{"prompt":"What is the n-back task?","copilot":true}')
    
JOB=$(echo "$JOB_RESPONSE" | jq -r '.job_id // .id // .data.job_id // empty')

if [ -n "$JOB" ]; then
    sleep 3
    STATUS=$(curl -s $ORCH/jobs/$JOB | jq -r '.status // "unknown"')
    if [ "$STATUS" = "completed" ] || [ "$STATUS" = "success" ]; then
        echo -e "${GREEN}✓${NC} (job: $JOB)"
    else
        echo -e "${RED}✗${NC} (status: $STATUS)"
    fi
else
    echo -e "${RED}✗${NC} (no job ID returned)"
fi

# Test tool-enabled job
echo -n "2. Tool-enabled job... "
JOB2_RESPONSE=$(curl -s -X POST $ORCH/run \
    -H 'Content-Type: application/json' \
    -d '{"prompt":"Find concepts related to hippocampus","enable_tools":true,"copilot":true}')
    
JOB2=$(echo "$JOB2_RESPONSE" | jq -r '.job_id // .id // .data.job_id // empty')

if [ -n "$JOB2" ]; then
    sleep 5
    JOB_DATA=$(curl -s $ORCH/jobs/$JOB2)
    TOOLS=$(echo "$JOB_DATA" | jq -r '.artifacts[0].type // .tool_calls[0].name // "none"')
    if [ "$TOOLS" != "none" ]; then
        echo -e "${GREEN}✓${NC} (job: $JOB2)"
    else
        STATUS=$(echo "$JOB_DATA" | jq -r '.status // "unknown"')
        echo -e "${RED}✗${NC} (no tools used, status: $STATUS)"
    fi
else
    echo -e "${RED}✗${NC} (no job ID returned)"
fi

# Test trace propagation
echo -n "3. Trace propagation... "
TRACE_TEST=$(curl -s -X POST $ORCH/run \
    -H 'Content-Type: application/json' \
    -H 'X-Trace-ID: orch-test-456' \
    -d '{"prompt":"test","copilot":true}')
if echo "$TRACE_TEST" | jq -e '.trace_id // .runCard.trace_id' > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
fi

echo "=============================="
echo "Orchestrator smoke test complete"