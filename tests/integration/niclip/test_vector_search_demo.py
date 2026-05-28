#!/usr/bin/env python3
"""
Demo script to test vector search functionality with BR-KG
Tests the KG-016 Vector Search Integration
"""

import json
import os
import time

import pytest
import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# Base URL for BR-KG API
BASE_URL = os.environ.get("NEUROKG_API_URL")
if not BASE_URL:
    base_root = os.environ.get("NEUROKG_URL", "http://127.0.0.1:5000").rstrip("/")
    BASE_URL = f"{base_root}/api"


def _health_url(api_url: str) -> str:
    if api_url.endswith("/api"):
        return f"{api_url[:-4]}/health"
    return f"{api_url.rstrip('/')}/health"


def _service_reachable() -> bool:
    try:
        resp = requests.get(_health_url(BASE_URL), timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


if not _service_reachable():
    pytest.skip(f"BR-KG service not reachable at {BASE_URL}", allow_module_level=True)


def test_vector_search():
    """Test basic vector search."""
    console.print("\n[bold blue]Testing Vector Search[/bold blue]")
    
    # Test queries
    queries = [
        "functional connectivity fMRI brain networks",
        "motor cortex activation tasks",
        "working memory cognitive load",
        "default mode network resting state"
    ]
    
    for query in queries:
        console.print(f"\n[cyan]Query: {query}[/cyan]")
        
        response = requests.post(
            f"{BASE_URL}/vector/search",
            json={
                "query": query,
                "k": 5,
                "threshold": 0.3
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            console.print(f"Found {data['count']} results in {data['search_time_ms']}ms")
            
            # Display results in table
            if data['results']:
                table = Table(title="Vector Search Results")
                table.add_column("Node ID", style="cyan", no_wrap=True)
                table.add_column("Type", style="green")
                table.add_column("Score", style="yellow")
                table.add_column("Text Preview", style="white")
                
                for result in data['results'][:3]:  # Show top 3
                    table.add_row(
                        result['node_id'][:20] + "...",
                        result['node_type'],
                        f"{result['score']:.3f}",
                        result['text_representation'][:50] + "..."
                    )
                
                console.print(table)
        else:
            console.print(f"[red]Error: {response.status_code} - {response.text}[/red]")


def test_hybrid_search():
    """Test hybrid search combining vector and text."""
    console.print("\n[bold blue]Testing Hybrid Search[/bold blue]")
    
    query = "prefrontal cortex executive function"
    console.print(f"\n[cyan]Query: {query}[/cyan]")
    
    response = requests.post(
        f"{BASE_URL}/vector/hybrid",
        json={
            "query": query,
            "k": 5,
            "vector_weight": 0.7,
            "text_weight": 0.3
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        console.print(f"Found {data['count']} results in {data['search_time_ms']}ms")
        console.print(f"Weights: Vector={data['search_config']['vector_weight']}, Text={data['search_config']['text_weight']}")
        
        # Display results
        for i, result in enumerate(data['results'][:3], 1):
            panel = Panel(
                f"[yellow]Combined Score:[/yellow] {result['combined_score']:.3f}\n"
                f"[cyan]Vector Score:[/cyan] {result['vector_score']:.3f}\n"
                f"[green]Text Score:[/green] {result['text_score']:.3f}\n"
                f"[white]Node:[/white] {result['node_type']}:{result['node_id'][:30]}...",
                title=f"Result {i}"
            )
            console.print(panel)
    else:
        console.print(f"[red]Error: {response.status_code} - {response.text}[/red]")


def test_similar_nodes():
    """Test finding similar nodes."""
    console.print("\n[bold blue]Testing Similar Nodes Search[/bold blue]")
    
    # First, get a sample node
    response = requests.post(
        f"{BASE_URL}/search",
        json={
            "query": "memory",
            "limit": 1
        }
    )
    
    if response.status_code == 200:
        payload = response.json()
        if isinstance(payload, dict):
            search_results = payload.get("results", [])
        else:
            search_results = payload
        if search_results:
            sample_node = search_results[0]
            node_id = sample_node['node_id']
            node_type = sample_node['node_type']
            
            console.print(f"\n[cyan]Finding nodes similar to {node_type}:{node_id[:30]}...[/cyan]")
            
            # Find similar nodes
            response = requests.get(
                f"{BASE_URL}/vector/similar/{node_type}/{node_id}",
                params={"k": 5}
            )
            
            if response.status_code == 200:
                data = response.json()
                console.print(f"Found {data['count']} similar nodes")
                
                # Display similar nodes
                table = Table(title="Similar Nodes")
                table.add_column("Node ID", style="cyan")
                table.add_column("Type", style="green")
                table.add_column("Similarity", style="yellow")
                
                for node in data['similar_nodes']:
                    table.add_row(
                        node['node_id'][:30] + "...",
                        node['node_type'],
                        f"{node['similarity_score']:.3f}"
                    )
                
                console.print(table)
            else:
                console.print(f"[red]Error finding similar nodes: {response.text}[/red]")
    else:
        console.print(f"[red]Error getting sample node: {response.text}[/red]")


def test_vector_stats():
    """Test getting vector search statistics."""
    console.print("\n[bold blue]Vector Search Statistics[/bold blue]")
    
    response = requests.get(f"{BASE_URL}/vector/stats")
    
    if response.status_code == 200:
        stats = response.json()
        
        panel = Panel(
            f"[yellow]Model:[/yellow] {stats['model']}\n"
            f"[cyan]Dimension:[/cyan] {stats['dimension']}\n"
            f"[green]Cache Enabled:[/green] {stats['cache']['enabled']}\n"
            f"[white]Cache Size:[/white] {stats['cache']['size']}/{stats['cache']['max_size']}\n"
            f"[magenta]Indices:[/magenta] {len(stats['indices'])} types indexed",
            title="Vector Search Statistics"
        )
        console.print(panel)
        
        # Show index details
        if stats['indices']:
            table = Table(title="Index Details")
            table.add_column("Node Type", style="cyan")
            table.add_column("Vectors", style="yellow")
            table.add_column("Index Type", style="green")
            
            for node_type, details in stats['indices'].items():
                table.add_row(
                    node_type,
                    str(details['num_vectors']),
                    details['index_type']
                )
            
            console.print(table)
    else:
        console.print(f"[red]Error getting stats: {response.text}[/red]")


def main():
    """Run all vector search tests."""
    console.print(Panel.fit(
        "[bold]Vector Search Integration Demo[/bold]\n"
        "Testing KG-016 implementation",
        style="blue"
    ))
    
    # Check if BR-KG is running
    try:
        response = requests.get(f"http://localhost:5000/health")
        if response.status_code != 200:
            console.print("[red]BR-KG service is not running![/red]")
            console.print("[yellow]Start it with: br serve kg[/yellow]")
            return
    except requests.exceptions.ConnectionError:
        console.print("[red]Cannot connect to BR-KG service on port 5000![/red]")
        console.print("[yellow]Start it with: br serve kg[/yellow]")
        return
    
    console.print("[green]✓ BR-KG service is running[/green]\n")
    
    # Run tests
    try:
        test_vector_stats()
        time.sleep(1)
        
        test_vector_search()
        time.sleep(1)
        
        test_hybrid_search()
        time.sleep(1)
        
        test_similar_nodes()
        
        console.print("\n[bold green]✓ All vector search tests completed![/bold green]")
        
    except Exception as e:
        console.print(f"\n[red]Error during testing: {e}[/red]")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
