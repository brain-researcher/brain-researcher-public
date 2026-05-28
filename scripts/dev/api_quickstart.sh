#!/bin/bash

# Brain Researcher Agent - API Quick Start Commands
# ==================================================

echo "🧠 Brain Researcher Agent - API Quick Examples"
echo "=============================================="
echo ""

# Base URL
BASE_URL="http://localhost:8000"

# 1. Health Check
echo "1️⃣  Health Check:"
echo "   curl $BASE_URL/health"
curl -s "$BASE_URL/health" | python -m json.tool
echo ""

# 2. List Available Tools
echo "2️⃣  List Tools (first 5):"
echo "   curl $BASE_URL/tools"
curl -s "$BASE_URL/tools" | python -m json.tool | head -30
echo ""

# 3. Simple Tool Execution - Coordinate to Concept
echo "3️⃣  Map Brain Coordinate to Concept:"
echo "   Motor cortex coordinate: [-38, -25, 50]"
echo ""
echo "   curl -X POST $BASE_URL/debug/tool/coordinate_to_concept \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"coordinates\": [[-38, -25, 50]]}'"
echo ""
curl -s -X POST "$BASE_URL/debug/tool/coordinate_to_concept" \
     -H "Content-Type: application/json" \
     -d '{"coordinates": [[-38, -25, 50]]}' | python -m json.tool 2>/dev/null || echo "Processing..."
echo ""

# 4. Task to Concept Mapping
echo "4️⃣  Map Task to Concept:"
echo "   Task: 'finger tapping'"
echo ""
echo "   curl -X POST $BASE_URL/debug/tool/task_to_concept_mapping \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"task_name\": \"finger tapping\"}'"
echo ""
curl -s -X POST "$BASE_URL/debug/tool/task_to_concept_mapping" \
     -H "Content-Type: application/json" \
     -d '{"task_name": "finger tapping"}' | python -m json.tool 2>/dev/null || echo "Processing..."
echo ""

# 5. Find Related Concepts
echo "5️⃣  Find Related Concepts:"
echo "   Concept: 'working memory'"
echo ""
echo "   curl -X POST $BASE_URL/debug/tool/find_related_concepts \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"concept\": \"working memory\", \"limit\": 5}'"
echo ""
curl -s -X POST "$BASE_URL/debug/tool/find_related_concepts" \
     -H "Content-Type: application/json" \
     -d '{"concept": "working memory", "limit": 5}' | python -m json.tool 2>/dev/null || echo "Processing..."
echo ""

# 6. Neurosynth Meta-Analysis
echo "6️⃣  Neurosynth Meta-Analysis:"
echo "   Term: 'motor'"
echo ""
echo "   curl -X POST $BASE_URL/debug/tool/neurosynth_meta_analysis \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"term\": \"motor\", \"threshold\": 0.01}'"
echo ""
curl -s -X POST "$BASE_URL/debug/tool/neurosynth_meta_analysis" \
     -H "Content-Type: application/json" \
     -d '{"term": "motor", "threshold": 0.01}' | python -m json.tool 2>/dev/null || echo "Processing..."
echo ""

echo "=============================================="
echo "✅ Quick examples completed!"
echo ""
echo "📚 More Examples:"
echo "   • Python client: python api_usage_examples.py"
echo "   • Web interface: http://localhost:8000"
echo "   • Full tool list: curl $BASE_URL/tools | python -m json.tool"
echo ""
echo "💡 Tips:"
echo "   • Use python -m json.tool to format JSON output"
echo "   • Add -s flag to curl for silent mode"
echo "   • Check /debug/tool/{tool_name} for direct tool access"
echo ""