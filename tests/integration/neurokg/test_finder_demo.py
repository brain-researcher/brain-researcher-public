#!/usr/bin/env python
"""
Interactive demo script for testing the Finder API
This is for manual testing and demonstration purposes
"""

import requests
import json
from pprint import pprint
from typing import Dict, List, Any
import os

# Base URL - can be overridden by environment variable
BASE_URL = os.getenv("NEUROKG_URL", "http://localhost:5000")


class FinderAPIDemo:
    """Demo class for Finder API testing"""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.check_connection()
    
    def check_connection(self):
        """Check if server is accessible"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            if response.status_code == 200:
                print(f"✅ Connected to BR-KG at {self.base_url}")
                return True
        except requests.exceptions.RequestException as e:
            print(f"❌ Cannot connect to {self.base_url}: {e}")
            print("Start the server with: br serve kg")
            return False
        return False
    
    def demo_suggest_filters(self):
        """Demo natural language to filters conversion"""
        print("\n" + "=" * 60)
        print("DEMO: Natural Language to Filters")
        print("=" * 60)
        
        queries = [
            "task fMRI motor studies in older adults",
            "resting state fMRI with n >= 100",
            "language processing in children under 12",
            "BIDS compliant datasets from OpenNeuro after 2020",
            "structural MRI studies with sample size between 50 and 200"
        ]
        
        for query in queries:
            print(f"\n📝 Query: '{query}'")
            response = requests.post(
                f"{self.base_url}/kg/suggestFilters",
                json={"text": query}
            )
            
            if response.status_code == 200:
                filters = response.json()["filters"]
                print("   Extracted filters:")
                for f in filters:
                    op = f.get('op', '=')
                    print(f"     • {f['facet']} {op} {f['value']}")
            else:
                print(f"   ❌ Error: {response.status_code}")
    
    def demo_facets(self):
        """Demo facet counting"""
        print("\n" + "=" * 60)
        print("DEMO: Facet Counting")
        print("=" * 60)
        
        test_cases = [
            {
                "name": "No filters (all data)",
                "filters": []
            },
            {
                "name": "Filter by fMRI",
                "filters": [{"facet": "modality", "value": "fmri", "op": "="}]
            },
            {
                "name": "Filter by fMRI and large sample",
                "filters": [
                    {"facet": "modality", "value": "fmri", "op": "="},
                    {"facet": "n", "value": 50, "op": ">="}
                ]
            }
        ]
        
        for test in test_cases:
            print(f"\n📊 {test['name']}")
            print(f"   Filters: {test['filters']}")
            
            response = requests.post(
                f"{self.base_url}/kg/facets",
                json={"filters": test["filters"]}
            )
            
            if response.status_code == 200:
                facets = response.json()
                print("   Facet counts:")
                for facet_name, values in list(facets.items())[:3]:  # Show first 3 facets
                    print(f"     {facet_name}:")
                    for item in values[:3]:  # Show top 3 values
                        print(f"       • {item['value']}: {item['count']}")
            else:
                print(f"   ⚠️  Skipped (Neo4j required): {response.status_code}")
    
    def demo_search(self):
        """Demo dataset search"""
        print("\n" + "=" * 60)
        print("DEMO: Dataset Search")
        print("=" * 60)
        
        searches = [
            {
                "name": "Motor task fMRI",
                "filters": [
                    {"facet": "modality", "value": "fmri", "op": "="},
                    {"facet": "task", "value": "motor", "op": "="}
                ]
            },
            {
                "name": "Large sample resting state",
                "filters": [
                    {"facet": "task", "value": "rest", "op": "="},
                    {"facet": "n", "value": 100, "op": ">="}
                ]
            }
        ]
        
        for search in searches:
            print(f"\n🔍 Search: {search['name']}")
            print(f"   Filters: {search['filters']}")
            
            response = requests.post(
                f"{self.base_url}/kg/searchDatasets",
                json={
                    "filters": search["filters"],
                    "sort": "n_desc",
                    "page": 1,
                    "pageSize": 3
                }
            )
            
            if response.status_code == 200:
                results = response.json()
                print(f"   Found {results['total']} datasets")
                
                for item in results["items"][:3]:
                    readiness_icon = {
                        "green": "🟢",
                        "yellow": "🟡", 
                        "red": "🔴"
                    }.get(item.get("readiness", "red"), "⚪")
                    
                    print(f"\n   {readiness_icon} Dataset: {item.get('id', 'Unknown')}")
                    print(f"      Title: {item.get('title', 'N/A')}")
                    print(f"      N: {item.get('n', 'N/A')}")
                    print(f"      Tasks: {', '.join(item.get('tasks', []))}")
                    
                    if item.get('why'):
                        print("      Why matched:")
                        for why in item['why']:
                            print(f"        • {why['type']}: {why['value']}")
            else:
                print(f"   ⚠️  Skipped (Neo4j required): {response.status_code}")
    
    def demo_explain(self):
        """Demo dataset explanation"""
        print("\n" + "=" * 60)
        print("DEMO: Dataset Explanation")
        print("=" * 60)
        
        # First try to get a dataset ID
        response = requests.post(
            f"{self.base_url}/kg/searchDatasets",
            json={"filters": [], "page": 1, "pageSize": 1}
        )
        
        if response.status_code == 200 and response.json().get("items"):
            dataset_id = response.json()["items"][0]["id"]
            print(f"📚 Explaining dataset: {dataset_id}")
            
            response = requests.get(f"{self.base_url}/kg/explain/{dataset_id}")
            
            if response.status_code == 200:
                explanation = response.json()
                
                print(f"\n   Summary: {explanation.get('summary', 'N/A')}")
                
                if explanation.get('topCitations'):
                    print("\n   Top Citations:")
                    for cite in explanation['topCitations'][:3]:
                        print(f"     • {cite.get('title', 'N/A')}")
                        if cite.get('doi'):
                            print(f"       DOI: {cite['doi']}")
                
                if explanation.get('miniGraph'):
                    graph = explanation['miniGraph']
                    print(f"\n   Mini Graph:")
                    print(f"     • Nodes: {len(graph.get('nodes', []))}")
                    print(f"     • Edges: {len(graph.get('edges', []))}")
                    
                    print("     Node types:")
                    for node in graph.get('nodes', [])[:5]:
                        print(f"       • {node['type']}: {node['label']}")
            else:
                print(f"   ❌ Error: {response.status_code}")
        else:
            print("   ⚠️  No datasets available to explain (Neo4j required)")
    
    def run_all_demos(self):
        """Run all demos in sequence"""
        self.demo_suggest_filters()
        self.demo_facets()
        self.demo_search()
        self.demo_explain()
        
        print("\n" + "=" * 60)
        print("DEMO COMPLETE")
        print("=" * 60)
        print("\nThe /kg/suggestFilters API works without Neo4j.")
        print("Other endpoints require Neo4j with data to function fully.")


def main():
    """Main entry point for demo"""
    print("=" * 60)
    print("NEUROKG FINDER API DEMO")
    print("=" * 60)
    
    demo = FinderAPIDemo()
    demo.run_all_demos()


if __name__ == "__main__":
    main()