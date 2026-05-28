# Tool Calling Test Suite

This directory contains test scripts and results for validating the LLM agent's tool calling functionality.

## Quick Start

```bash
# Run all use case tests
cd tests/tool_calling
bash run_use_case_tests.sh
```

## Test Structure

- `run_use_case_tests.sh` - Main test script with 6 use case scenarios
- `results/` - JSON output files from test runs (gitignored)

## Use Cases Tested

### 1. Knowledge Graph Query
**Query**: "What brain regions are associated with working memory?"
**Expected Tool**: `find_related_concepts`

### 2. Coordinate-to-Concept Mapping
**Query**: "What cognitive functions are associated with MNI coordinates x=40, y=-50, z=30?"
**Expected Tool**: `coordinate_to_concept`

### 3. Literature Search
**Query**: "Find recent papers about default mode network connectivity"
**Expected Tool**: `concept_literature_search`

### 4. Task-to-Concept Mapping
**Query**: "What cognitive concepts are measured by the n-back task?"
**Expected Tool**: `task_to_concept_mapping`

### 5. Multi-Tool Reasoning Chain
**Query**: "I have activation at MNI coordinates [45, -55, 25]. What brain region is this, and what papers discuss its role in memory?"
**Expected Tools**: `coordinate_to_concept` → `concept_literature_search`

### 6. Direct Graph Query
**Query**: "Show me the subgraph of concepts related to episodic memory"
**Expected Tool**: `graph_query`

## Viewing Results

```bash
# List all test results
ls -lh results/

# View specific test result
jq '.' results/test1_kg_query.json

# View tool call details for all tests
for f in results/*.json; do
  echo "=== $f ==="
  jq -r '.tool_calls[] | "Tool: \(.name), Status: \(.status)"' "$f"
done
```

## Prerequisites

The agent service must be running with environment variables exported:

```bash
export GEMINI_API_KEY="your-key"
export DEFAULT_LLM_MODEL="gemini-2.0-flash"
export NEUROKG_API_URL="http://localhost:5000"

br serve agent --port 8000
```

See `docs/ENVIRONMENT_SETUP.md` for detailed setup instructions.

## Known Issues

- Some tools may return 404 errors if the BR-KG service doesn't have the expected endpoints
- This is expected for test instances without full data ingestion
- The important verification is that **tools are being called**, even if they error due to missing data
