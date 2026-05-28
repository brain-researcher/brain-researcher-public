#!/bin/bash

# Test suite for tool calling use cases
# Run with: bash test_tool_use_cases.sh
# Specialty runner: not part of default CI. Requires a running agent service at
# AGENT_URL.

AGENT_URL="http://localhost:8000"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/results"

mkdir -p "$OUTPUT_DIR"

echo "🧪 Testing Tool Calling Use Cases"
echo "=================================="
echo ""

# Test 1: Knowledge Graph Query
echo "1️⃣  Testing: Knowledge Graph Query (find_related_concepts)"
curl -X POST "$AGENT_URL/act" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What brain regions are associated with working memory?",
    "session_id": "test_kg_query"
  }' 2>/dev/null | jq '.' > "$OUTPUT_DIR/test1_kg_query.json"

if [ $? -eq 0 ]; then
  echo "   ✅ Request successful"
  jq -r '.tool_calls[]? | "   Tool: \(.name), Status: \(.status)"' "$OUTPUT_DIR/test1_kg_query.json"
else
  echo "   ❌ Request failed"
fi
echo ""

# Test 2: Coordinate Mapping
echo "2️⃣  Testing: Coordinate-to-Concept Mapping"
curl -X POST "$AGENT_URL/act" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What cognitive functions are associated with MNI coordinates x=40, y=-50, z=30?",
    "session_id": "test_coord_mapping"
  }' 2>/dev/null | jq '.' > "$OUTPUT_DIR/test2_coord_mapping.json"

if [ $? -eq 0 ]; then
  echo "   ✅ Request successful"
  jq -r '.tool_calls[]? | "   Tool: \(.name), Status: \(.status)"' "$OUTPUT_DIR/test2_coord_mapping.json"
else
  echo "   ❌ Request failed"
fi
echo ""

# Test 3: Literature Search
echo "3️⃣  Testing: Literature Search"
curl -X POST "$AGENT_URL/act" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Find recent papers about default mode network connectivity",
    "session_id": "test_literature"
  }' 2>/dev/null | jq '.' > "$OUTPUT_DIR/test3_literature.json"

if [ $? -eq 0 ]; then
  echo "   ✅ Request successful"
  jq -r '.tool_calls[]? | "   Tool: \(.name), Status: \(.status)"' "$OUTPUT_DIR/test3_literature.json"
else
  echo "   ❌ Request failed"
fi
echo ""

# Test 4: Task Mapping
echo "4️⃣  Testing: Task-to-Concept Mapping"
curl -X POST "$AGENT_URL/act" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What cognitive concepts are measured by the n-back task?",
    "session_id": "test_task_mapping"
  }' 2>/dev/null | jq '.' > "$OUTPUT_DIR/test4_task_mapping.json"

if [ $? -eq 0 ]; then
  echo "   ✅ Request successful"
  jq -r '.tool_calls[]? | "   Tool: \(.name), Status: \(.status)"' "$OUTPUT_DIR/test4_task_mapping.json"
else
  echo "   ❌ Request failed"
fi
echo ""

# Test 5: Multi-Tool Reasoning
echo "5️⃣  Testing: Multi-Tool Reasoning Chain"
curl -X POST "$AGENT_URL/act" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "I have activation at MNI coordinates [45, -55, 25]. What brain region is this, and what papers discuss its role in memory?",
    "session_id": "test_multi_tool"
  }' 2>/dev/null | jq '.' > "$OUTPUT_DIR/test5_multi_tool.json"

if [ $? -eq 0 ]; then
  echo "   ✅ Request successful"
  jq -r '.tool_calls[]? | "   Tool: \(.name), Status: \(.status)"' "$OUTPUT_DIR/test5_multi_tool.json"
else
  echo "   ❌ Request failed"
fi
echo ""

# Test 6: Graph Query
echo "6️⃣  Testing: Direct Graph Query"
curl -X POST "$AGENT_URL/act" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show me the subgraph of concepts related to episodic memory",
    "session_id": "test_graph_query"
  }' 2>/dev/null | jq '.' > "$OUTPUT_DIR/test6_graph_query.json"

if [ $? -eq 0 ]; then
  echo "   ✅ Request successful"
  jq -r '.tool_calls[]? | "   Tool: \(.name), Status: \(.status)"' "$OUTPUT_DIR/test6_graph_query.json"
else
  echo "   ❌ Request failed"
fi
echo ""

# Summary
echo "=================================="
echo "📊 Test Results Summary"
echo "=================================="
echo "Results saved to: $OUTPUT_DIR"
echo ""

# Count successful tool calls
total_tests=6
successful_tests=0

for i in {1..6}; do
  if [ -f "$OUTPUT_DIR/test${i}_*.json" ]; then
    status=$(jq -r '.tool_calls[]?.status' "$OUTPUT_DIR/test${i}"_*.json 2>/dev/null | head -1)
    if [ "$status" = "success" ] || [ "$status" = "error" ]; then
      # Tool was called (even if it errored, the calling mechanism worked)
      successful_tests=$((successful_tests + 1))
    fi
  fi
done

echo "Tests that called tools: $successful_tests/$total_tests"
echo ""
echo "View detailed results:"
echo "  ls -lh $OUTPUT_DIR"
echo "  jq '.' $OUTPUT_DIR/test1_kg_query.json"
