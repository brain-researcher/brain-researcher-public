"""Query and search commands for Brain Researcher CLI."""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

app = typer.Typer(help="Query and search commands")
console = Console()


def _get_neo4j_db():
    try:
        from brain_researcher.services.br_kg.db.bootstrap import get_db

        return get_db(require_neo4j=True)
    except Exception as exc:
        console.print(
            "[red]Neo4j is required for CLI queries.[/red] "
            "Set NEO4J_URI/NEO4J_PASSWORD and try again."
        )
        console.print(f"[dim]{exc}[/dim]")
        raise typer.Exit(1)


@app.command()
def interactive(
    db_path: Path | None = typer.Option(None, "--db", "-d", help="Database path"),
):
    """Start interactive query mode."""
    try:
        import query_br_kg_interactive

        console.print("[bold green]BR-KG Interactive Query Mode[/bold green]")
        console.print("Type 'help' for available commands, 'quit' to exit.\n")

        # Run interactive mode
        query_br_kg_interactive.main()

    except Exception as e:
        console.print(f"[red]Error starting interactive mode: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    search_type: str = typer.Option(
        "hybrid", "--type", "-t", help="Search type: text, vector, hybrid"
    ),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum results to return"),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="Output format: table, json, csv"
    ),
):
    """Search the knowledge graph."""
    try:
        from brain_researcher.services.br_kg.search import SearchEngine, SearchMode

        db = _get_neo4j_db()
        engine = SearchEngine(db)

        mode = SearchMode.CONTAINS
        if search_type not in {"text", "hybrid", "vector"}:
            console.print(
                f"[yellow]Unknown search type '{search_type}', using text search.[/yellow]"
            )
        if search_type in {"vector", "hybrid"}:
            console.print(
                "[yellow]Vector/hybrid search is not available in CLI; using text search.[/yellow]"
            )

        results = []
        for item in engine.search(query, mode=mode, limit=limit):
            match_field = ", ".join(item.matched_fields) if item.matched_fields else ""
            result = {
                "id": item.node_id,
                "type": item.node_type,
                "name": item.properties.get("name", item.properties.get("title", "N/A")),
                "match_field": match_field,
                "score": item.score,
            }
            results.append(result)

        db.close()

        # Display results
        if output_format == "json":
            console.print_json(data=results)
        elif output_format == "csv":
            # Convert to CSV format
            import csv
            import io

            output = io.StringIO()
            if results:
                writer = csv.DictWriter(output, fieldnames=results[0].keys())
                writer.writeheader()
                writer.writerows(results)
                console.print(output.getvalue())
        else:  # table
            table = Table(title=f"Search Results for: '{query}'")

            if results:
                # Add columns based on first result
                for key in results[0].keys():
                    table.add_column(key.title(), style="cyan")

                # Add rows
                for result in results[:limit]:
                    table.add_row(*[str(v) for v in result.values()])

            console.print(table)

    except Exception as e:
        console.print(f"[red]Search error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def cypher(
    query: str = typer.Argument(..., help="Cypher query to execute"),
    db_path: Path | None = typer.Option(None, "--db", "-d", help="Database path"),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Save results to file"
    ),
):
    """Execute a Cypher query directly."""
    try:
        if db_path:
            console.print(
                "[yellow]--db is ignored; CLI uses Neo4j via NEO4J_URI/NEO4J_PASSWORD.[/yellow]"
            )

        console.print("[bold blue]Executing Cypher query...[/bold blue]")
        console.print(Syntax(query, "cypher"))

        db = _get_neo4j_db()

        # Execute query
        results = db.execute_query(query)

        db.close()

        # Display or save results
        if output:
            with open(output, "w") as f:
                json.dump(results, f, indent=2)
            console.print(f"[green]✓[/green] Results saved to {output}")
        else:
            console.print_json(data=results)

    except Exception as e:
        console.print(f"[red]Query error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def concepts(
    term: str = typer.Argument(..., help="Concept term to search"),
    related: bool = typer.Option(
        False, "--related", "-r", help="Show related concepts"
    ),
    depth: int = typer.Option(1, "--depth", "-d", help="Depth for related concepts"),
):
    """Search for concepts in the knowledge graph."""
    try:
        console.print(f"[bold blue]Searching for concept: '{term}'[/bold blue]")

        # TODO: Implement concept search
        # This would use the find_related_concepts tool

        console.print("[yellow]Concept search implementation pending[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def coordinates(
    x: float = typer.Option(..., "--x", help="X coordinate"),
    y: float = typer.Option(..., "--y", help="Y coordinate"),
    z: float = typer.Option(..., "--z", help="Z coordinate"),
    space: str = typer.Option(
        "MNI", "--space", "-s", help="Coordinate space (MNI, Talairach)"
    ),
    radius: float = typer.Option(10.0, "--radius", "-r", help="Search radius in mm"),
):
    """Find concepts near brain coordinates."""
    try:
        console.print(
            f"[bold blue]Searching near coordinates ({x}, {y}, {z}) in {space} space[/bold blue]"
        )

        # TODO: Implement coordinate search
        # This would use the coordinate_to_concepts tool

        console.print("[yellow]Coordinate search implementation pending[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def stats():
    """Show database statistics and available entities."""
    try:
        db = _get_neo4j_db()
        stats = db.get_stats()

        node_counts = {}
        for label in stats.get("node_labels", []):
            rows = db.execute_query(f"MATCH (n:`{label}`) RETURN count(n) AS cnt")
            node_counts[label] = int(rows[0].get("cnt", 0)) if rows else 0

        rel_counts = {}
        for rel_type in stats.get("relationship_types", []):
            rows = db.execute_query(
                f"MATCH ()-[r:`{rel_type}`]->() RETURN count(r) AS cnt"
            )
            rel_counts[rel_type] = int(rows[0].get("cnt", 0)) if rows else 0

        stats.update(node_counts)
        stats.update(rel_counts)
        db.close()

        console.print("[bold]BR-KG Database Statistics[/bold]\n")

        # Overall stats
        overall_table = Table(title="Overall Statistics")
        overall_table.add_column("Metric", style="cyan")
        overall_table.add_column("Count", justify="right", style="magenta")

        if "total_nodes" in stats:
            overall_table.add_row("Total Nodes", f"{stats['total_nodes']:,}")
        if "total_relationships" in stats:
            overall_table.add_row(
                "Total Relationships", f"{stats['total_relationships']:,}"
            )

        console.print(overall_table)
        console.print()

        # Node types
        node_table = Table(title="Node Types")
        node_table.add_column("Type", style="cyan")
        node_table.add_column("Count", justify="right", style="magenta")

        for node_type in sorted(node_counts):
            node_table.add_row(node_type, f"{node_counts[node_type]:,}")

        console.print(node_table)
        console.print()

        # Relationship types
        rel_table = Table(title="Relationship Types")
        rel_table.add_column("Type", style="cyan")
        rel_table.add_column("Count", justify="right", style="magenta")

        rel_types = sorted(rel_counts.keys())
        for rel_type in rel_types:
            rel_table.add_row(rel_type, f"{rel_counts[rel_type]:,}")

        if rel_types:
            console.print(rel_table)

    except Exception as e:
        console.print(f"[red]Error getting statistics: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
