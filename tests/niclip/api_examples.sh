#!/bin/bash
# NiCLIP API Examples

echo "🧠 NiCLIP API Examples"
echo "====================="

# 1. Basic task mapping
echo -e "\n1️⃣ Basic Task Mapping:"
curl -X POST http://localhost:8000/debug/tool/task_to_concept_mapping \
  -H "Content-Type: application/json" \
  -d '{
    "args": {
      "task_name": "n-back task",
      "include_synonyms": true
    }
  }' | python -m json.tool

# 2. Check service health
echo -e "\n\n2️⃣ Service Health Check:"
curl http://localhost:8000/health

# 3. List all available tools
echo -e "\n\n3️⃣ Available Tools:"
curl http://localhost:8000/tools | python -m json.tool | grep name

# 4. Multiple task lookups
echo -e "\n\n4️⃣ Multiple Task Lookups:"
for task in "stroop task" "emotional faces task" "finger tapping"; do
  echo -e "\n→ $task:"
  curl -s -X POST http://localhost:8000/debug/tool/task_to_concept_mapping \
    -H "Content-Type: application/json" \
    -d "{\"args\": {\"task_name\": \"$task\"}}" | \
    python -m json.tool | grep -E "(concepts|primary_process|source)"
done

# 5. Using the LangGraph API
echo -e "\n\n5️⃣ LangGraph API - Create Thread:"
THREAD_ID=$(curl -s -X POST http://localhost:8000/threads | python -c "import sys, json; print(json.load(sys.stdin)['thread_id'])")
echo "Thread ID: $THREAD_ID"

# 6. Send a message
echo -e "\n6️⃣ Send Message to Thread:"
curl -X POST "http://localhost:8000/threads/$THREAD_ID/messages" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "user",
    "content": "What concepts are associated with the n-back task?"
  }'

# 7. Run the agent
echo -e "\n\n7️⃣ Run Agent:"
curl -X POST "http://localhost:8000/threads/$THREAD_ID/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "brain-researcher",
    "stream": false
  }' | python -m json.tool