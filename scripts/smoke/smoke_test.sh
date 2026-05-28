#!/bin/bash
# Brain Researcher - Deployment Smoke Test
# Tests health endpoints and Prometheus targets

set -e

# Configuration
AGENT_URL="${AGENT_URL:-http://localhost:8000}"
NEUROKG_URL="${NEUROKG_URL:-http://localhost:5000}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
TIMEOUT=5

echo "=========================================="
echo "Brain Researcher Smoke Test"
echo "=========================================="
echo "Agent:      $AGENT_URL"
echo "BR-KG:    $NEUROKG_URL"
echo "Prometheus: $PROMETHEUS_URL"
echo "=========================================="

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# Test 1: Agent health/full endpoint
echo ""
echo "Test 1: Agent /api/health/full"
HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT "$AGENT_URL/api/health/full" 2>/dev/null || echo "000")
HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -n1)
BODY=$(echo "$HEALTH_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    pass "Agent health endpoint returned 200"

    # Check for required fields
    echo "$BODY" | jq -e '.status' > /dev/null 2>&1 && pass "  - status field present" || warn "  - status field missing"
    echo "$BODY" | jq -e '.services' > /dev/null 2>&1 && pass "  - services field present" || warn "  - services field missing"
    echo "$BODY" | jq -e '.queue' > /dev/null 2>&1 && pass "  - queue field present" || warn "  - queue field missing"
    echo "$BODY" | jq -e '.neo4j' > /dev/null 2>&1 && pass "  - neo4j field present" || warn "  - neo4j field missing"

    # Show summary
    STATUS=$(echo "$BODY" | jq -r '.status // "unknown"')
    NODE_COUNT=$(echo "$BODY" | jq -r '.neo4j.node_count // 0')
    REL_COUNT=$(echo "$BODY" | jq -r '.neo4j.relationship_count // 0')
    echo "  Overall status: $STATUS"
    echo "  Neo4j nodes: $NODE_COUNT, relationships: $REL_COUNT"
else
    fail "Agent health endpoint returned $HTTP_CODE (expected 200)"
fi

# Test 2: BR-KG health endpoint
echo ""
echo "Test 2: BR-KG /health"
NEUROKG_HEALTH=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT "$NEUROKG_URL/health" 2>/dev/null || echo "000")
HTTP_CODE=$(echo "$NEUROKG_HEALTH" | tail -n1)

if [ "$HTTP_CODE" = "200" ]; then
    pass "BR-KG health endpoint returned 200"
else
    fail "BR-KG health endpoint returned $HTTP_CODE (expected 200)"
fi

# Test 3: BR-KG health/stats endpoint
echo ""
echo "Test 3: BR-KG /health/stats"
STATS_RESPONSE=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT "$NEUROKG_URL/health/stats" 2>/dev/null || echo "000")
HTTP_CODE=$(echo "$STATS_RESPONSE" | tail -n1)
BODY=$(echo "$STATS_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    pass "BR-KG stats endpoint returned 200"

    NODE_COUNT=$(echo "$BODY" | jq -r '.node_count // 0')
    REL_COUNT=$(echo "$BODY" | jq -r '.relationship_count // 0')
    echo "  - Node count: $NODE_COUNT"
    echo "  - Relationship count: $REL_COUNT"
elif [ "$HTTP_CODE" = "503" ]; then
    warn "BR-KG stats returned 503 (SQLite mock mode - Neo4j not connected)"
else
    fail "BR-KG stats endpoint returned $HTTP_CODE"
fi

# Test 4: BR-KG /metrics endpoint
echo ""
echo "Test 4: BR-KG /metrics"
METRICS_RESPONSE=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT "$NEUROKG_URL/metrics" 2>/dev/null || echo "000")
HTTP_CODE=$(echo "$METRICS_RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "200" ]; then
    pass "BR-KG metrics endpoint returned 200"
    BODY=$(echo "$METRICS_RESPONSE" | sed '$d')
    if echo "$BODY" | grep -q "neurokg_up"; then
        pass "  - neurokg_up metric present"
    else
        warn "  - neurokg_up metric missing"
    fi
else
    warn "BR-KG metrics endpoint returned $HTTP_CODE"
fi

# Test 5: Agent /metrics endpoint
echo ""
echo "Test 5: Agent /metrics"
AGENT_METRICS=$(curl -s -w "\n%{http_code}" --max-time $TIMEOUT "$AGENT_URL/metrics" 2>/dev/null || echo "000")
HTTP_CODE=$(echo "$AGENT_METRICS" | tail -n1)

if [ "$HTTP_CODE" = "200" ]; then
    pass "Agent metrics endpoint returned 200"
elif [ "$HTTP_CODE" = "404" ]; then
    warn "Agent metrics disabled (returned 404)"
else
    warn "Agent metrics endpoint returned $HTTP_CODE"
fi

# Test 6: Prometheus targets (if available)
echo ""
echo "Test 6: Prometheus Targets"
PROM_TARGETS=$(curl -s --max-time $TIMEOUT "$PROMETHEUS_URL/api/v1/targets" 2>/dev/null || echo "")

if [ -n "$PROM_TARGETS" ]; then
    ACTIVE_TARGETS=$(echo "$PROM_TARGETS" | jq '.data.activeTargets | length' 2>/dev/null || echo "0")
    UP_TARGETS=$(echo "$PROM_TARGETS" | jq '[.data.activeTargets[] | select(.health == "up")] | length' 2>/dev/null || echo "0")

    if [ "$ACTIVE_TARGETS" -gt 0 ]; then
        pass "Prometheus has $ACTIVE_TARGETS active targets ($UP_TARGETS up)"

        # List targets
        echo "  Targets:"
        echo "$PROM_TARGETS" | jq -r '.data.activeTargets[] | "    - \(.labels.job): \(.health)"' 2>/dev/null || true
    else
        warn "Prometheus has no active targets"
    fi
else
    warn "Prometheus not reachable at $PROMETHEUS_URL (optional)"
fi

# Summary
echo ""
echo "=========================================="
echo "Smoke Test Complete"
echo "=========================================="
