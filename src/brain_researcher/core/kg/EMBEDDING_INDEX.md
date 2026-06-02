# Embedding Index Documentation

## Overview

The Embedding Index system provides efficient vector similarity search for neuroimaging literature using a sharded FAISS index architecture. It supports both text and multimodal (text + figure) embeddings with automatic sharding, persistence, and monitoring.

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         RAG Knowledge System                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ Embedding Index │  │ Configuration    │  │ Metrics       │  │
│  │                 │  │                  │  │ Collector     │  │
│  │ - Sharded FAISS │  │ - Model params   │  │ - Query stats │  │
│  │ - Multimodal    │  │ - Shard config   │  │ - Performance │  │
│  │ - Thread-safe   │  │ - Refresh setup  │  │ - Index state │  │
│  └────────┬────────┘  └──────────────────┘  └───────────────┘  │
│           │                                                       │
│  ┌────────▼────────────────────────────────────────────────┐    │
│  │                    Shard Management                      │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐             │    │
│  │  │ Shard 0  │  │ Shard 1  │  │ Shard N  │  ...        │    │
│  │  │ 10k vecs │  │ 10k vecs │  │ <10k vecs│             │    │
│  │  └──────────┘  └──────────┘  └──────────┘             │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Sharding Strategy

The system uses automatic sharding to handle large-scale embeddings:

1. **Shard Size**: Configurable (default: 10,000 embeddings per shard)
2. **Shard Creation**: New shard created when current shard reaches capacity
3. **Search**: Parallel search across all shards with result aggregation
4. **Persistence**: Each shard saved as separate FAISS index + metadata pickle

Benefits:
- Memory efficiency: Load only needed shards
- Scalability: No limit on total embeddings
- Performance: Parallel search across shards
- Flexibility: Different shard sizes for different use cases

### File Structure

```
knowledge/db/
├── shard_0.faiss      # FAISS index for shard 0
├── shard_0.pkl        # Metadata for shard 0
├── shard_1.faiss      # FAISS index for shard 1
├── shard_1.pkl        # Metadata for shard 1
└── ...

knowledge/config/
└── embedding_config.json  # Configuration file

knowledge/metrics/
└── embedding_metrics.json # Metrics snapshots
```

## Multimodal Embedding Format

The system supports combining text and figure embeddings:

### Text-Only Embedding
```python
{
    "id": "paper_123",
    "text": "Deep learning methods for fMRI analysis...",
    # Embedding dimension: 384 (for all-MiniLM-L6-v2)
}
```

### Text + Figure Embedding
```python
{
    "id": "paper_456",
    "text": "Visual cortex activation patterns...",
    "figure": np.array([...])  # Figure embedding (512-dim)
    # Combined embedding dimension: 384 + 512 = 896
}
```

### Concatenation Strategies

1. **Simple Concatenation** (default):
   ```
   combined = [text_embedding; figure_embedding]
   ```

2. **Weighted Concatenation** (future):
   ```
   combined = [α * text_embedding; β * figure_embedding]
   ```

## Configuration

### Environment Variables

```bash
# Model configuration
export EMBEDDING_MODEL_NAME="all-MiniLM-L6-v2"
export EMBEDDING_MODEL_CACHE="/path/to/cache"

# Index configuration
export EMBEDDING_DB_DIR="knowledge/db"
export EMBEDDING_SHARD_SIZE="10000"
export EMBEDDING_INDEX_TYPE="IndexFlatIP"  # or "IndexFlatL2"

# Performance
export EMBEDDING_REFRESH_INTERVAL="86400"  # 24 hours
export EMBEDDING_SLOW_QUERY_THRESHOLD="1.0"  # seconds

# Monitoring
export EMBEDDING_METRICS_PORT="9090"
```

### Configuration File

Create `knowledge/config/embedding_config.json`:

```json
{
  "model_name": "sentence-transformers/all-mpnet-base-v2",
  "shard_size": 50000,
  "index_type": "IndexFlatIP",
  "enable_multimodal": true,
  "figure_embedding_dim": 512,
  "refresh_interval": 3600,
  "enable_metrics": true,
  "slow_query_threshold": 0.5
}
```

### Loading Priority

1. Default values
2. Configuration file (if exists)
3. Environment variables (override all)

## API Reference

### EmbeddingIndex

```python
from knowledge.embedding_index import EmbeddingIndex

# Initialize
index = EmbeddingIndex(
    db_dir="knowledge/db",
    model_name="all-MiniLM-L6-v2",
    shard_size=10000
)

# Add records
records = [
    {"id": "1", "text": "Brain imaging study..."},
    {"id": "2", "text": "Neural networks...", "figure": figure_embedding}
]
index.add_records(records)

# Search
results = index.search("deep learning fMRI", top_k=5)
# Returns: [{"id": "1", "score": 0.85, "text": "...", ...}, ...]

# Save to disk
index.save()

# Shutdown (saves and stops refresh)
index.shutdown()
```

### Configuration

```python
from knowledge.embedding_config import EmbeddingConfig, get_config

# Load configuration
config = get_config("knowledge/config/embedding_config.json")

# Access values
print(f"Model: {config.model_name}")
print(f"Shard size: {config.shard_size}")

# Validate
if config.validate():
    print("Configuration is valid")
```

### Metrics

```python
from knowledge.embedding_metrics import get_metrics_collector, QueryTimer

# Get collector
metrics = get_metrics_collector()

# Time a query
with QueryTimer(metrics, "test query", shard_count=3) as timer:
    results = index.search("brain imaging", top_k=5)
    timer.set_results(len(results))

# Get summary
summary = metrics.get_summary()
print(f"Total queries: {summary['total_queries']}")
print(f"Average latency: {summary['latency_ms']['avg']:.1f}ms")

# Export Prometheus metrics
prometheus_data = metrics.get_prometheus_metrics()
```

## Performance Tuning

### Shard Size Selection

| Use Case | Recommended Shard Size | Rationale |
|----------|------------------------|-----------|
| Development | 1,000 - 5,000 | Fast iteration, easy debugging |
| Production | 10,000 - 50,000 | Balance memory/performance |
| Large-scale | 50,000 - 100,000 | Minimize shard count |

### Index Type Selection

- **IndexFlatIP**: Inner product (cosine similarity after normalization)
  - Best for: Normalized embeddings, semantic similarity
  - Default choice

- **IndexFlatL2**: L2 (Euclidean) distance
  - Best for: Raw embeddings, geometric similarity
  - Use when embeddings aren't normalized

### Memory Optimization

```python
# Estimate memory usage
embedding_dim = 384
embeddings_per_shard = 10000
bytes_per_float = 4

memory_per_shard_mb = (embedding_dim * embeddings_per_shard * bytes_per_float) / (1024 * 1024)
# ~14.6 MB per shard for 384-dim embeddings
```

### Query Optimization

1. **Batch Queries**: Process multiple queries together
2. **Limit Top-K**: Use smallest k that meets requirements
3. **Cache Results**: For repeated queries
4. **Parallel Search**: Utilize multiple CPU cores

## Monitoring

### Key Metrics

1. **Query Performance**
   - Average latency
   - P95/P99 latency
   - Queries per second

2. **Index Health**
   - Total embeddings
   - Number of shards
   - Memory usage
   - Last refresh time

3. **Error Tracking**
   - Error rate
   - Error types
   - Failed queries

### Prometheus Integration

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'embedding_index'
    static_configs:
      - targets: ['localhost:9090']
```

### Alerting Rules

```yaml
# High query latency
- alert: HighEmbeddingQueryLatency
  expr: embedding_latency_ms_p99 > 1000
  for: 5m
  annotations:
    summary: "High embedding search latency"

# Index not refreshed
- alert: EmbeddingIndexStale
  expr: time() - embedding_index_last_refresh > 172800  # 48 hours
  annotations:
    summary: "Embedding index hasn't been refreshed"
```

## Troubleshooting

### Common Issues

1. **Dimension Mismatch Error**
   - Cause: Mixing text-only and multimodal embeddings in same shard
   - Fix: Ensure consistent embedding dimensions within shards

2. **High Memory Usage**
   - Cause: Too many shards loaded simultaneously
   - Fix: Reduce shard size or implement shard unloading

3. **Slow Queries**
   - Cause: Searching across many shards
   - Fix: Increase shard size or implement index pruning

4. **Corrupted Shard**
   - Cause: Interrupted save operation
   - Fix: Delete corrupted shard files, rebuild from source

### Debug Mode

```python
import logging

# Enable debug logging
logging.getLogger('knowledge.embedding_index').setLevel(logging.DEBUG)

# Check shard status
for i, (idx, meta) in enumerate(zip(index.indices, index.metadata)):
    print(f"Shard {i}: {idx.ntotal} vectors, {len(meta)} metadata entries")
```

## Best Practices

1. **Regular Refreshes**: Schedule periodic index updates
2. **Monitor Performance**: Track query latency and error rates
3. **Backup Shards**: Keep backups of shard files
4. **Test Multimodal**: Validate figure embeddings before indexing
5. **Version Control**: Track embedding model versions
6. **Gradual Migration**: When changing models, maintain old index during transition

## Future Enhancements

1. **Advanced Index Types**
   - IVF (Inverted File) for larger scales
   - HNSW for better speed/accuracy trade-off

2. **Distributed Sharding**
   - Shard distribution across multiple machines
   - Consistent hashing for shard assignment

3. **Smart Caching**
   - LRU cache for frequently accessed shards
   - Query result caching

4. **Enhanced Multimodal**
   - Support for more modalities (tables, equations)
   - Learned fusion strategies

5. **Real-time Updates**
   - Incremental index updates
   - Write-ahead logging for durability
