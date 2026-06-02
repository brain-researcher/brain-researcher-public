#!/usr/bin/env python3
"""
Simple examples of using Brain Researcher tools in the agent backend.
Focus on the most common use cases.
"""

# === OPTION 1: Through the Chat API (Recommended) ===
"""
The easiest way is to use the chat endpoint and let the agent decide which tools to use:

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What brain regions are involved in working memory?",
    "thread_id": "my-session-123"
  }'

The agent will automatically:
1. Use task_to_concept_mapping to understand "working memory"
2. Find related brain regions
3. Return a comprehensive answer
"""

# === OPTION 2: Direct Python Usage ===
from brain_researcher.services.tools.br_kg_tools import (
    CoordinateToConceptTool,
    FindRelatedConceptsTool,
    TaskMappingTool,
)
from brain_researcher.services.tools.fmri_tools import ContrastAnalysisTool


def simple_examples():
    """Most common tool usage patterns."""

    # Example 1: Map a cognitive task to brain concepts
    print("Example 1: What concepts are related to the n-back task?")
    task_tool = TaskMappingTool()
    result = task_tool._run(task_name="n-back")
    if result.status == "success":
        print(f"Concepts: {result.data['concepts']}")
        print(f"Data source: {result.data.get('source', 'unknown')}\n")

    # Example 2: What cognitive function is at this brain location?
    print("Example 2: What's at MNI coordinate [-42, -22, 54]?")
    coord_tool = CoordinateToConceptTool()
    result = coord_tool._run(coordinates=[[-42, -22, 54]])
    if result.status == "success":
        mapping = result.data["coordinate_mappings"][0]
        top_concept = mapping["concepts"][0]
        print(
            f"Top concept: {top_concept['concept']} (score: {top_concept['score']:.2f})"
        )
        print(f"Method: {result.data.get('method', 'unknown')}\n")

    # Example 3: Analyze a contrast with real GLM data
    print("Example 3: Analyze the 'pumps' contrast from balloon task")
    contrast_tool = ContrastAnalysisTool()
    result = contrast_tool._run(
        z_map_path="/data/glm/ds000001/pumps_zmap.nii.gz", contrast_name="pumps"
    )
    if result.status == "success":
        print(f"Using real data: {not result.metadata.get('mock_mode', True)}")
        if result.data.get("z_map_used"):
            print(f"File: {result.data['z_map_used']}")
        print(f"Found {result.data['n_clusters']} significant clusters\n")

    # Example 4: Find related concepts in the knowledge graph
    print("Example 4: What's related to 'working memory'?")
    concept_tool = FindRelatedConceptsTool()
    result = concept_tool._run(concept="working memory", limit=3)
    if result.status == "success":
        for rel in result.data["related_concepts"]:
            print(f"- {rel['concept']} ({rel['relationship']})")


# === OPTION 3: Through LangGraph Agent ===
async def agent_example():
    """Use through the LangGraph agent for complex queries."""
    from brain_researcher.services.agent.brain_researcher_graph import (
        BrainResearcherGraph,
    )

    # Initialize agent
    graph = BrainResearcherGraph()

    # Complex query that uses multiple tools
    result = await graph.arun(
        {
            "query": "Compare activation patterns between pumps and control conditions in the balloon task, focusing on motor regions",
            "thread_id": "analysis-001",
        }
    )

    print(result["response"])


# === Common Query Patterns ===
"""
1. Task Analysis:
   "What brain regions are involved in [TASK NAME]?"
   "Explain the neural basis of [COGNITIVE FUNCTION]"

2. Coordinate Queries:
   "What cognitive functions are at coordinates [X, Y, Z]?"
   "What's activated at these locations: [[X1,Y1,Z1], [X2,Y2,Z2]]?"

3. Contrast Analysis:
   "Analyze the [CONTRAST NAME] contrast from dataset [DATASET ID]"
   "Show me activation clusters for [TASK] > [BASELINE]"

4. Literature Search:
   "Find papers about [CONCEPT1] and [CONCEPT2]"
   "Recent research on [BRAIN REGION] during [TASK]"

5. Knowledge Graph:
   "How is [CONCEPT1] related to [CONCEPT2]?"
   "Show connections between [BRAIN REGION] and [FUNCTION]"
"""

# === Available Real Data ===
"""
The tools will automatically use these real data sources when available:

1. Vocabulary: /data/vocab/ca_topics_level0_v2.json
   - Cognitive Atlas concepts and mappings

2. GLM Data: /llm_cognitive_function/data/z_statmap/ds000001/
   - Balloon analog risk task contrasts:
     * pumps, control, cash, explode, rt
     * Various parametric contrasts

3. NiCLIP Models:
   - Brain coordinate to concept mapping
   - Uses DiFuMo-512 atlas
   - Brain-language alignment

4. BR-KG API:
   - Knowledge graph queries
   - Literature connections
   - Concept relationships
"""

if __name__ == "__main__":
    print("=== Simple Brain Researcher Tool Examples ===\n")
    simple_examples()

    print("\n=== Quick Reference ===")
    print("Chat API: POST /chat with message and thread_id")
    print("Tools: task_mapping, coordinate_mapping, contrast_analysis, concept_search")
    print("Real data: Vocab file, GLM maps, NiCLIP models, BR-KG graph")
