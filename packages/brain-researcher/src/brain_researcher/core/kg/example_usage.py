#!/usr/bin/env python3
"""
Example usage of the enhanced embedding index system.

This demonstrates configuration, metrics, and the embedding index working together.
"""

import numpy as np

# Import from current module
from .embedding_config import EmbeddingConfig
from .embedding_index import EmbeddingIndex
from .embedding_metrics import get_metrics_collector


def example_basic_usage():
    """Basic usage with default configuration."""
    print("=" * 60)
    print("Example 1: Basic Usage")
    print("=" * 60)

    # Use default configuration
    index = EmbeddingIndex()

    # Add some research papers
    papers = [
        {
            "id": "pmid_12345",
            "text": "Deep learning approaches for automated segmentation of brain MRI scans have shown promising results in clinical applications.",
            "source": "pubmed",
        },
        {
            "id": "pmid_12346",
            "text": "Resting-state functional connectivity reveals disrupted network patterns in patients with major depressive disorder.",
            "source": "pubmed",
        },
        {
            "id": "pmid_12347",
            "text": "Graph neural networks provide new insights into brain connectivity patterns derived from diffusion tensor imaging data.",
            "source": "pubmed",
        },
    ]

    print(f"\nAdding {len(papers)} papers to index...")
    index.add_records(papers)

    # Search
    query = "brain connectivity depression"
    print(f"\nSearching for: '{query}'")
    results = index.search(query, top_k=2)

    for i, result in enumerate(results, 1):
        print(f"\n{i}. Paper {result['id']}")
        print(f"   Score: {result['score']:.3f}")
        print(f"   Text: {result['text'][:80]}...")

    # Get statistics
    stats = index.get_stats()
    print("\nIndex Statistics:")
    print(f"  Total shards: {stats['total_shards']}")
    print(f"  Total embeddings: {stats['total_embeddings']}")


def example_custom_configuration():
    """Using custom configuration."""
    print("\n" + "=" * 60)
    print("Example 2: Custom Configuration")
    print("=" * 60)

    # Create custom configuration
    config = EmbeddingConfig(
        model_name="sentence-transformers/all-mpnet-base-v2",  # Better model
        shard_size=100,  # Small shards for demo
        index_type="IndexFlatIP",  # Cosine similarity
        enable_metrics=True,
        log_slow_queries=True,
        slow_query_threshold=0.05,  # 50ms threshold
    )

    print("\nConfiguration:")
    print(f"  Model: {config.model_name}")
    print(f"  Shard size: {config.shard_size}")
    print(f"  Index type: {config.index_type}")

    # Create index with custom config
    index = EmbeddingIndex(config=config)

    # Add more papers to trigger sharding
    papers = []
    for i in range(150):
        papers.append(
            {
                "id": f"paper_{i}",
                "text": f"Research paper {i} about neuroimaging analysis using machine learning techniques.",
            }
        )

    print(f"\nAdding {len(papers)} papers (will create multiple shards)...")
    index.add_records(papers)

    # Check sharding
    stats = index.get_stats()
    print("\nSharding results:")
    for shard in stats["shard_details"]:
        print(
            f"  Shard {shard['shard_id']}: {shard['vectors']} vectors, dimension {shard['dimension']}"
        )


def example_multimodal_embeddings():
    """Using multimodal (text + figure) embeddings."""
    print("\n" + "=" * 60)
    print("Example 3: Multimodal Embeddings")
    print("=" * 60)

    # Enable multimodal in config
    config = EmbeddingConfig(
        enable_multimodal=True, figure_embedding_dim=512, shard_size=100
    )

    index = EmbeddingIndex(config=config)

    # Create figure embeddings (normally from a vision model)
    figure_embedding_1 = np.random.randn(512).astype(np.float32)
    figure_embedding_2 = np.random.randn(512).astype(np.float32)

    # Add papers with and without figures
    papers = [
        {
            "id": "paper_with_fig_1",
            "text": "Brain activation patterns during visual processing tasks",
            "figure": figure_embedding_1,
            "has_figure": True,
        },
        {
            "id": "paper_text_only_1",
            "text": "Review of fMRI analysis methods for cognitive neuroscience",
            "has_figure": False,
        },
        {
            "id": "paper_with_fig_2",
            "text": "Hippocampal volume changes in Alzheimer's disease progression",
            "figure": figure_embedding_2,
            "has_figure": True,
        },
    ]

    print(f"\nAdding {len(papers)} papers (mixed text-only and multimodal)...")
    index.add_records(papers)

    # Search with text only
    print("\nSearching with text query only:")
    results = index.search("brain activation visual", top_k=2)
    for res in results:
        print(
            f"  - {res['id']}: score={res['score']:.3f}, has_figure={res.get('has_figure', False)}"
        )

    # Note: In real usage, you could also search with text + figure query


def example_monitoring_and_metrics():
    """Using the monitoring system."""
    print("\n" + "=" * 60)
    print("Example 4: Monitoring and Metrics")
    print("=" * 60)

    # Get metrics collector
    metrics = get_metrics_collector()

    # Create index with metrics enabled
    config = EmbeddingConfig(
        enable_metrics=True,
        log_slow_queries=True,
        slow_query_threshold=0.01,  # 10ms for demo
    )

    index = EmbeddingIndex(config=config)

    # Add test data
    papers = [
        {"id": f"doc_{i}", "text": f"Document {i} about brain research"}
        for i in range(50)
    ]
    index.add_records(papers)

    # Perform various searches
    queries = [
        "deep learning brain imaging",
        "functional connectivity analysis",
        "hippocampal segmentation methods",
        "error query that might fail",
        "slow query with many results",
    ]

    print("\nPerforming test queries...")
    for i, query in enumerate(queries):
        try:
            results = index.search(query, top_k=10)
            print(f"  Query {i+1}: '{query[:30]}...' - Found {len(results)} results")
        except Exception as e:
            print(f"  Query {i+1}: '{query[:30]}...' - ERROR: {e}")

    # Get metrics summary
    summary = metrics.get_summary()

    print("\nMetrics Summary:")
    print(f"  Total queries: {summary['total_queries']}")
    print(f"  Error rate: {summary['error_rate']:.2%}")
    print(f"  Queries per second: {summary['queries_per_second']:.2f}")
    print("\nLatency statistics:")
    print(f"  Average: {summary['latency_ms']['avg']:.1f}ms")
    print(f"  P95: {summary['latency_ms']['p95']:.1f}ms")
    print(f"  P99: {summary['latency_ms']['p99']:.1f}ms")
    print("\nIndex state:")
    print(f"  Total embeddings: {summary['index']['total_embeddings']}")
    print(f"  Memory usage: {summary['index']['memory_usage_mb']:.1f}MB")

    # Export Prometheus metrics
    print("\nPrometheus metrics (first 10 lines):")
    prometheus_data = metrics.get_prometheus_metrics()
    for line in prometheus_data.split("\n")[:10]:
        print(f"  {line}")


def example_persistence_and_loading():
    """Demonstrate saving and loading indices."""
    print("\n" + "=" * 60)
    print("Example 5: Persistence and Loading")
    print("=" * 60)

    # Use a temporary directory
    import tempfile

    temp_dir = tempfile.mkdtemp()

    config = EmbeddingConfig(db_dir=temp_dir, shard_size=50)

    # Create and populate index
    print(f"\nCreating index in {temp_dir}")
    index1 = EmbeddingIndex(config=config)

    papers = [
        {"id": f"paper_{i}", "text": f"Research paper {i} content"} for i in range(120)
    ]
    index1.add_records(papers)

    print(f"Added {len(papers)} papers")
    print(f"Created {len(index1.indices)} shards")

    # Save
    print("\nSaving index...")
    index1.save()

    # Create new instance that loads existing shards
    print("\nLoading in new instance...")
    index2 = EmbeddingIndex(config=config)

    stats = index2.get_stats()
    print(
        f"Loaded {stats['total_shards']} shards with {stats['total_embeddings']} embeddings"
    )

    # Verify search works
    results = index2.search("research paper 42", top_k=1)
    if results:
        print(f"\nSearch verification: Found {results[0]['id']}")

    # Cleanup
    import shutil

    shutil.rmtree(temp_dir)


def main():
    """Run all examples."""
    print("Enhanced Embedding Index System - Examples")
    print("=" * 60)

    # Run examples
    example_basic_usage()
    example_custom_configuration()
    example_multimodal_embeddings()
    example_monitoring_and_metrics()
    example_persistence_and_loading()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
