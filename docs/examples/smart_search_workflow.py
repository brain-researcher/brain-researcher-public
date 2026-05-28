#!/usr/bin/env python3
"""
Example workflow using BR-KG Smart Search API

This demonstrates a complete research workflow:
1. Search for papers on a topic
2. Find related concepts and brain regions
3. Summarize findings
4. Export results for further analysis
"""

import json
import os
from typing import Any

import pandas as pd
import requests

# Configuration
API_BASE = (
    os.getenv("BR_NEUROKG_URL")
    or os.getenv("NEUROKG_BASE_URL")
    or os.getenv("NEUROKG_URL")
    or os.getenv("NEUROKG_API_URL")
    or "http://localhost:5000"
)


class NeuroKGClient:
    """Client for interacting with BR-KG Smart Search API."""

    def __init__(self, api_base: str = API_BASE):
        self.api_base = api_base
        self.session = requests.Session()

    def smart_search(self, query: str, limit: int = 100) -> dict[str, Any]:
        """Perform a smart search with natural language."""
        response = self.session.post(
            f"{self.api_base}/api/search/smart", json={"query": query, "limit": limit}
        )
        response.raise_for_status()
        return response.json()

    def summarize_nodes(self, node_ids: list[str]) -> dict[str, Any]:
        """Get a summary of selected nodes."""
        response = self.session.post(
            f"{self.api_base}/api/summarize", json={"node_ids": node_ids}
        )
        response.raise_for_status()
        return response.json()

    def find_similar(self, node_id: str, limit: int = 10) -> dict[str, Any]:
        """Find nodes similar to a given node."""
        response = self.session.get(
            f"{self.api_base}/api/similar/{node_id}", params={"limit": limit}
        )
        response.raise_for_status()
        return response.json()

    def expand_node(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        """Get neighbors of a node."""
        response = self.session.get(
            f"{self.api_base}/api/search_and_expand",
            params={"q": node_id, "depth": depth},
        )
        response.raise_for_status()
        return response.json()


def research_workflow_example():
    """Example research workflow using smart search."""

    client = NeuroKGClient()

    print("=== BR-KG Research Workflow Example ===\n")

    # Step 1: Initial search
    research_question = "working memory and executive control in aging populations"
    print(f"Research Question: {research_question}\n")

    print("Step 1: Searching for relevant papers...")
    search_results = client.smart_search(research_question, limit=20)

    print("Query understood as:")
    print(f"  Entity type: {search_results['parsed']['entity_type']}")
    print(f"  Concepts: {search_results['parsed']['filters'].get('concepts', [])}")
    print(f"  Confidence: {search_results['parsed']['confidence']:.2f}")
    print(f"  Found {search_results['total_count']} results\n")

    # Step 2: Analyze top papers
    if search_results["results"]:
        print("Step 2: Analyzing top papers...")

        # Get top 5 paper IDs
        top_paper_ids = [r["id"] for r in search_results["results"][:5]]

        # Summarize the papers
        summary = client.summarize_nodes(top_paper_ids)
        print("Summary of top papers:")
        print(f"  {summary['summary']}\n")

        # Step 3: Find related concepts
        print("Step 3: Finding related concepts...")

        # Look for concept nodes in the results
        concept_nodes = [
            r for r in search_results["results"] if r["type"] == "Concept"
        ][:3]

        if concept_nodes:
            for concept in concept_nodes:
                print(f"\nConcept: {concept['display_name']}")

                # Find similar concepts
                similar = client.find_similar(concept["id"], limit=3)
                if similar["similar_nodes"]:
                    print("  Related concepts:")
                    for sim in similar["similar_nodes"]:
                        print(
                            f"    - {sim['node']['properties'].get('name', 'Unknown')}"
                        )
                        print(f"      (similarity: {sim['similarity']:.3f})")

        # Step 4: Explore brain regions
        print("\nStep 4: Exploring brain regions...")

        # For each top paper, find connected brain regions
        brain_regions = set()

        for paper_id in top_paper_ids[:3]:
            # Expand to find connected nodes
            expanded = client.expand_node(paper_id, depth=2)

            # Extract brain regions
            for node in expanded.get("nodes", []):
                if "BrainRegion" in node.get("data", {}).get("labels", []):
                    region_name = node["data"].get("name", node["data"]["id"])
                    brain_regions.add(region_name)

        if brain_regions:
            print("Brain regions mentioned in top papers:")
            for region in list(brain_regions)[:10]:
                print(f"  - {region}")

        # Step 5: Generate report
        print("\nStep 5: Generating research report...")

        report = {
            "research_question": research_question,
            "search_metadata": {
                "total_results": search_results["total_count"],
                "confidence": search_results["parsed"]["confidence"],
                "extracted_concepts": search_results["parsed"]["filters"].get(
                    "concepts", []
                ),
            },
            "top_papers": [
                {
                    "title": r["properties"].get("title", r["display_name"]),
                    "year": r["properties"].get("year", "N/A"),
                    "pmid": r["properties"].get("pmid", "N/A"),
                }
                for r in search_results["results"][:5]
                if r["type"] == "Study"
            ],
            "summary": summary["summary"],
            "brain_regions": list(brain_regions)[:10],
            "cypher_query": search_results["cypher"],
        }

        # Save report
        with open("research_report.json", "w") as f:
            json.dump(report, f, indent=2)

        print("Report saved to research_report.json")

        # Step 6: Export data for analysis
        print("\nStep 6: Exporting data for analysis...")

        # Convert to pandas DataFrame
        papers_data = []
        for result in search_results["results"]:
            if result["type"] == "Study":
                papers_data.append(
                    {
                        "pmid": result["properties"].get("pmid", ""),
                        "title": result["properties"].get("title", ""),
                        "year": result["properties"].get("year", ""),
                        "journal": result["properties"].get("journal", ""),
                        "abstract": result["properties"].get("abstract", "")[:200],
                    }
                )

        if papers_data:
            df = pd.DataFrame(papers_data)
            df.to_csv("search_results.csv", index=False)
            print(f"Exported {len(df)} papers to search_results.csv")

            # Basic analysis
            print("\nYear distribution:")
            if "year" in df.columns:
                year_counts = df["year"].value_counts().head()
                for year, count in year_counts.items():
                    print(f"  {year}: {count} papers")


def concept_exploration_example():
    """Example of exploring concept relationships."""

    client = NeuroKGClient()

    print("\n=== Concept Exploration Example ===\n")

    # Search for a specific concept
    concept_query = "executive function"
    print(f"Exploring concept: {concept_query}\n")

    # Search for the concept
    results = client.smart_search(f"concepts related to {concept_query}", limit=10)

    if results["results"]:
        main_concept = results["results"][0]
        print(f"Found concept: {main_concept['display_name']}")

        # Find similar concepts
        similar = client.find_similar(main_concept["id"], limit=10)

        print("\nRelated concepts network:")
        for i, sim in enumerate(similar["similar_nodes"]):
            concept_name = sim["node"]["properties"].get("name", "Unknown")
            similarity = sim["similarity"]
            shared = sim["shared_connections"]

            print(f"{i+1}. {concept_name}")
            print(f"   Similarity: {similarity:.3f}")
            print(f"   Shared connections: {shared}")

            # For top related concepts, find their connections
            if i < 3:
                sub_similar = client.find_similar(sim["node"]["id"], limit=3)
                if sub_similar["similar_nodes"]:
                    print("   Sub-concepts:")
                    for sub in sub_similar["similar_nodes"][:3]:
                        sub_name = sub["node"]["properties"].get("name", "Unknown")
                        print(f"     - {sub_name}")
            print()


def main():
    """Run example workflows."""

    # Check if API is available
    try:
        response = requests.get(f"{API_BASE}/health")
        if response.status_code != 200:
            print("BR-KG API is not running. Please start it first.")
            return
    except:
        print("Cannot connect to BR-KG API. Please start it first.")
        print("Run: br serve kg --host 0.0.0.0 --port 5000")
        return

    # Run workflows
    research_workflow_example()
    concept_exploration_example()

    print("\n=== Workflow Examples Complete ===")
    print("Check the generated files:")
    print("  - research_report.json: Structured research findings")
    print("  - search_results.csv: Papers data for analysis")


if __name__ == "__main__":
    main()
