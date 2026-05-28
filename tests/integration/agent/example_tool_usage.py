#!/usr/bin/env python3
"""
Example of how to use Brain Researcher tools in the agent backend.
Shows both direct Python calls and LangGraph agent usage.
"""

import asyncio
from typing import Dict, Any

# Direct tool usage (for testing or standalone scripts)
def example_direct_tool_usage():
    """Examples of calling tools directly in Python."""
    
    from brain_researcher.services.tools.neurokg_tools import (
        TaskMappingTool,
        CoordinateToConceptTool,
        FindRelatedConceptsTool,
        LiteratureSearchTool,
        GraphQueryTool
    )
    from brain_researcher.services.tools.fmri_tools import (
        ContrastAnalysisTool,
        GLMAnalysisTool,
        EncodingModelTool,
        BrainSimilarityTool
    )
    
    print("=== Direct Tool Usage Examples ===\n")
    
    # 1. Task to Concept Mapping (uses real vocabulary)
    print("1. Task to Concept Mapping:")
    task_tool = TaskMappingTool()
    result = task_tool._run(
        task_name="n-back",
        include_synonyms=True
    )
    print(f"   Concepts for n-back: {result.data['concepts'][:3]}...")
    
    # 2. Coordinate to Concept (uses NiCLIP if available)
    print("\n2. Coordinate to Concept Mapping:")
    coord_tool = CoordinateToConceptTool()
    result = coord_tool._run(
        coordinates=[[-42, -22, 54], [0, -2, 48]],  # Motor and SMA
        radius=10.0,
        top_k=3
    )
    for mapping in result.data['coordinate_mappings']:
        coord = mapping['coordinate']
        top_concept = mapping['concepts'][0]['concept']
        print(f"   {coord} -> {top_concept}")
    
    # 3. Contrast Analysis (uses real GLM data)
    print("\n3. Contrast Analysis with Real GLM:")
    contrast_tool = ContrastAnalysisTool()
    result = contrast_tool._run(
        z_map_path="/data/glm/ds000001/pumps_zmap.nii.gz",  # Will find real file
        contrast_name="pumps",
        task_description="Balloon analog risk task - pump events"
    )
    print(f"   Real data used: {not result.metadata.get('mock_mode', True)}")
    print(f"   Actual file: {result.data.get('z_map_used', 'mock data')}")
    
    # 4. Find Related Concepts
    print("\n4. Find Related Concepts:")
    concept_tool = FindRelatedConceptsTool()
    result = concept_tool._run(
        concept="working memory",
        depth=2,
        limit=5
    )
    print(f"   Related to 'working memory': {[r['concept'] for r in result.data['related_concepts'][:3]]}...")
    
    # 5. Literature Search
    print("\n5. Literature Search:")
    lit_tool = LiteratureSearchTool()
    result = lit_tool._run(
        concepts=["motor cortex", "hand movement"],
        keywords=["fMRI", "activation"],
        max_results=5
    )
    if result.status == "success":
        print(f"   Found {result.data['n_papers']} papers")
    else:
        print(f"   Error: {result.error}")
    
    # 6. Graph Query
    print("\n6. Graph Query - Neighbors:")
    graph_tool = GraphQueryTool()
    result = graph_tool._run(
        query_type="neighbors",
        start_node="executive function"
    )
    if result.status == "success":
        print(f"   Neighbors of 'executive function': {result.data['n_neighbors']} nodes")
    else:
        print(f"   Error: {result.error}")


# LangGraph agent usage
async def example_langgraph_agent_usage():
    """Example of using tools through the LangGraph agent."""
    
    from brain_researcher.services.agent.brain_researcher_graph import BrainResearcherGraph
    import os
    
    print("\n\n=== LangGraph Agent Usage Examples ===\n")
    
    # Initialize the graph
    graph = BrainResearcherGraph()
    
    # Example queries that will trigger tool usage
    example_queries = [
        # Query 1: Task analysis
        {
            "query": "What brain regions are involved in the n-back working memory task?",
            "expected_tools": ["task_to_concept_mapping", "coordinate_to_concept"]
        },
        
        # Query 2: Contrast analysis
        {
            "query": "Analyze the pumps contrast from the balloon analog risk task dataset ds000001",
            "expected_tools": ["contrast_analysis"]
        },
        
        # Query 3: Literature search
        {
            "query": "Find recent papers about motor cortex activation during finger tapping",
            "expected_tools": ["task_to_concept_mapping", "concept_literature_search"]
        },
        
        # Query 4: Coordinate mapping
        {
            "query": "What cognitive functions are associated with activation at coordinates [-42, -22, 54] and [0, -2, 48]?",
            "expected_tools": ["coordinate_to_concept"]
        },
        
        # Query 5: Knowledge graph exploration
        {
            "query": "Show me concepts related to executive function and their connections",
            "expected_tools": ["find_related_concepts", "graph_query"]
        }
    ]
    
    # Run example queries
    for i, example in enumerate(example_queries, 1):
        print(f"{i}. Query: {example['query']}")
        print(f"   Expected tools: {', '.join(example['expected_tools'])}")
        
        # In real usage, you would run:
        # result = await graph.arun({"query": example['query']})
        # print(f"   Response: {result['response']}")
        print()


# Web API usage
def example_web_api_usage():
    """Example of calling tools through the web API."""
    
    print("\n=== Web API Usage Examples ===\n")
    
    # These are example curl commands for the web service
    examples = """
    # 1. Chat endpoint (triggers appropriate tools automatically)
    curl -X POST http://localhost:8000/chat \\
      -H "Content-Type: application/json" \\
      -d '{
        "message": "What brain regions are activated during the n-back task?",
        "thread_id": "example-thread-1"
      }'
    
    # 2. Direct tool invocation (if implemented)
    curl -X POST http://localhost:8000/tools/task_to_concept_mapping \\
      -H "Content-Type: application/json" \\
      -d '{
        "task_name": "finger tapping",
        "include_synonyms": true
      }'
    
    # 3. Contrast analysis with real data
    curl -X POST http://localhost:8000/tools/contrast_analysis \\
      -H "Content-Type: application/json" \\
      -d '{
        "z_map_path": "/data/glm/ds000001/pumps_zmap.nii.gz",
        "contrast_name": "pumps",
        "coordinates": [[-42, -22, 54], [38, -86, -8]]
      }'
    
    # 4. Multi-tool query through chat
    curl -X POST http://localhost:8000/chat \\
      -H "Content-Type: application/json" \\
      -d '{
        "message": "Compare brain activation between pumps and control conditions in the balloon task, then find related literature",
        "thread_id": "example-thread-2"
      }'
    """
    
    print(examples)


# Tool parameter reference
def show_tool_parameters():
    """Display all available tools and their parameters."""
    
    print("\n=== Tool Parameter Reference ===\n")
    
    tool_params = {
        "task_to_concept_mapping": {
            "task_name": "str - Name of cognitive task (e.g., 'n-back', 'finger tapping')",
            "include_synonyms": "bool - Include task synonyms (default: True)"
        },
        
        "coordinate_to_concept": {
            "coordinates": "list[list[float]] - MNI coordinates [[x,y,z], ...]",
            "radius": "float - Search radius in mm (default: 10.0)",
            "top_k": "int - Number of concepts per coordinate (default: 5)"
        },
        
        "contrast_analysis": {
            "z_map_path": "str - Path to z-map (will auto-find real files)",
            "contrast_name": "str - Name of contrast (e.g., 'pumps', 'control')",
            "task_description": "str - Optional task description",
            "coordinates": "list[list[float]] - Optional specific coordinates"
        },
        
        "find_related_concepts": {
            "concept": "str - Concept to search from",
            "depth": "int - Graph traversal depth (default: 2)",
            "limit": "int - Max related concepts (default: 10)"
        },
        
        "concept_literature_search": {
            "concepts": "list[str] - Concepts to search",
            "keywords": "list[str] - Additional keywords (optional)",
            "max_results": "int - Max papers (default: 20)",
            "year_range": "tuple[int,int] - Year filter (optional)"
        },
        
        "graph_query": {
            "query_type": "str - 'subgraph', 'path', or 'neighbors'",
            "start_node": "str - Starting node name",
            "end_node": "str - End node for path queries (optional)",
            "filters": "dict - Additional filters (optional)"
        },
        
        "glm_analysis": {
            "dataset_id": "str - OpenNeuro dataset ID (e.g., 'ds000001')",
            "contrasts": "dict[str,list[float]] - Contrast definitions",
            "output_dir": "str - Output directory (optional)",
            "threshold": "float - Statistical threshold (default: 3.1)"
        },
        
        "encoding_model": {
            "dataset_id": "str - Dataset ID",
            "parcellation": "str - Brain parcellation (default: 'schaefer_400')",
            "features": "list[str] - Feature names (optional)"
        },
        
        "brain_similarity": {
            "dataset1": "str - First dataset ID or path",
            "dataset2": "str - Second dataset ID or path",
            "metric": "str - 'correlation', 'cosine', or 'euclidean'",
            "mask": "str - Brain mask (optional)"
        }
    }
    
    for tool_name, params in tool_params.items():
        print(f"{tool_name}:")
        for param, desc in params.items():
            print(f"  - {param}: {desc}")
        print()


def main():
    """Run all examples."""
    
    print("Brain Researcher Tools - Usage Examples")
    print("=" * 50)
    
    # 1. Direct tool usage
    example_direct_tool_usage()
    
    # 2. LangGraph agent usage
    # asyncio.run(example_langgraph_agent_usage())
    example_langgraph_agent_usage()  # Just show examples, don't run
    
    # 3. Web API usage
    example_web_api_usage()
    
    # 4. Parameter reference
    show_tool_parameters()
    
    print("\n" + "=" * 50)
    print("Note: Tools will use real data when available:")
    print("- Vocabulary: ca_topics_level0_v2.json")
    print("- GLM data: llm_cognitive_function/data/z_statmap/")
    print("- NiCLIP: Brain-language alignment models")
    print("- BR-KG: Knowledge graph API at http://localhost:5000")


if __name__ == "__main__":
    main()