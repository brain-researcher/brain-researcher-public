#!/usr/bin/env python3
"""
Test script for NICLIP integration with vector search
"""

import json
import os
import time

import pytest
import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

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


def test_niclip_vs_sentence_transformer():
    """Compare search results between NICLIP and sentence-transformers."""
    console.print(Panel.fit(
        "[bold]NICLIP vs Sentence-Transformer Comparison[/bold]\n"
        "Testing vector search with both embedding models",
        style="blue"
    ))
    
    # Test queries related to neuroscience
    queries = [
        "working memory executive function",
        "visual perception attention",
        "motor cortex movement planning",
        "default mode network resting state",
        "language processing Broca area"
    ]
    
    for query in queries:
        console.print(f"\n[bold cyan]Query: {query}[/bold cyan]")
        console.print("=" * 60)
        
        # Test with sentence-transformers
        console.print("\n[yellow]1. Sentence-Transformers (384-dim):[/yellow]")
        response = requests.post(
            f"{BASE_URL}/vector/search",
            json={
                "query": query,
                "k": 3,
                "use_niclip": False
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            console.print(f"   Search time: {data.get('search_time_ms', 'N/A')}ms")
            
            table = Table(show_header=True, header_style="bold")
            table.add_column("Rank", style="cyan", width=6)
            table.add_column("Score", style="green", width=8)
            table.add_column("Type", style="yellow", width=10)
            table.add_column("Name", style="white")
            
            for i, result in enumerate(data.get('results', [])[:3], 1):
                name = result.get('properties', {}).get('name', 'N/A')
                table.add_row(
                    str(i),
                    f"{result['score']:.3f}",
                    result['node_type'],
                    name[:50] + "..." if len(name) > 50 else name
                )
            
            console.print(table)
        else:
            console.print(f"[red]Error: {response.status_code}[/red]")
        
        # Test with NICLIP
        console.print("\n[yellow]2. NICLIP BrainGPT (4096-dim):[/yellow]")
        response = requests.post(
            f"{BASE_URL}/vector/search",
            json={
                "query": query,
                "k": 3,
                "use_niclip": True
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            console.print(f"   Search time: {data.get('search_time_ms', 'N/A')}ms")
            
            table = Table(show_header=True, header_style="bold")
            table.add_column("Rank", style="cyan", width=6)
            table.add_column("Score", style="green", width=8)
            table.add_column("Type", style="yellow", width=10)
            table.add_column("Name", style="white")
            
            for i, result in enumerate(data.get('results', [])[:3], 1):
                name = result.get('properties', {}).get('name', 'N/A')
                table.add_row(
                    str(i),
                    f"{result['score']:.3f}",
                    result['node_type'],
                    name[:50] + "..." if len(name) > 50 else name
                )
            
            console.print(table)
        else:
            console.print(f"[red]Error: {response.status_code}[/red]")
            console.print(f"[red]Response: {response.text[:500]}[/red]")
        
        time.sleep(0.5)  # Small delay between queries


def test_embedding_generation():
    """Test embedding generation with both models."""
    console.print("\n" + "=" * 60)
    console.print("[bold]Testing Embedding Generation[/bold]")
    console.print("=" * 60)
    
    test_text = "functional connectivity analysis"
    
    # Generate with sentence-transformers
    console.print(f"\nText: '{test_text}'")
    
    response = requests.post(
        f"{BASE_URL}/vector/embedding",
        json={
            "text": test_text,
            "use_niclip": False
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        console.print(f"\n[yellow]Sentence-Transformers:[/yellow]")
        console.print(f"  Dimension: {data['embedding_dimension']}")
        console.print(f"  Model: {data['model']}")
        console.print(f"  Preview: {data['embedding_preview'][:3]}...")
    
    # Generate with NICLIP
    response = requests.post(
        f"{BASE_URL}/vector/embedding",
        json={
            "text": test_text,
            "use_niclip": True
        }
    )
    
    if response.status_code == 200:
        data = response.json()
        console.print(f"\n[yellow]NICLIP:[/yellow]")
        console.print(f"  Dimension: {data['embedding_dimension']}")
        console.print(f"  Model: {data['model']}")
        console.print(f"  Preview: {data['embedding_preview'][:3]}...")
    else:
        console.print(f"[red]NICLIP Error: {response.status_code}[/red]")
        console.print(f"[red]{response.text[:500]}[/red]")


def main():
    """Run all tests."""
    # Check if service is running
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
        test_niclip_vs_sentence_transformer()
        test_embedding_generation()
        
        console.print("\n[bold green]✓ All tests completed![/bold green]")
        
    except Exception as e:
        console.print(f"\n[red]Error during testing: {e}[/red]")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
