# BR-KG - Knowledge Graph Service

A high-performance knowledge graph service for neuroimaging data, providing GraphQL API, bulk loading, and advanced querying capabilities.

## Features

- 🚀 **GraphQL API** - Full query and mutation support
- 📊 **Persisted Queries** - 20+ optimized pre-defined queries
- 🔄 **Bulk Loading** - High-performance NDJSON loader (121+ entities/sec)
- 🔍 **Search** - Full-text search with ranking (coming soon)
- 📈 **Statistics** - Graph analytics and metrics
- 💾 **Export** - Multiple format support (JSON, CSV, GraphML)
- 🔐 **Provenance** - Complete tracking with timestamps and sources
- ⚡ **Performance** - Optimized for large-scale neuroimaging datasets

## Quick Start

### Starting the Service

```bash
# Using the CLI
br serve kg

# Or directly
PORT=5000 python -m brain_researcher.services.br_kg.app

# Service will be available at:
# - GraphQL: http://localhost:5000/graphql
# - REST API: http://localhost:5000/api/
# - Health: http://localhost:5000/health
```

### Explorer UI (Next.js)

The official Explorer UI is part of Brain Researcher Web (Next.js) and consumes the BR-KG API:
```bash
br serve web
```

Open `http://localhost:3000/en/kg/explore`.

### GraphQL Usage

Access the GraphiQL interface at `http://localhost:5000/graphql`

#### Query Examples

```graphql
# Get all concepts
query {
  concepts {
    id
    name
  }
}

# Query with filters
query {
  tasks(name: "n-back") {
    id
    name
  }

  publications(pmid: "12345678") {
    id
    title
  }
}

# Create a concept
mutation {
  createConcept(id: "new_concept", name: "New Concept") {
    id
    name
  }
}

# Create relationship with provenance
mutation {
  createRelationship(
    sourceId: "concept1",
    targetId: "task1",
    relType: "MEASURES",
    confidence: 0.85,
    source: "PubMed"
  ) {
    type
    confidence
    source
    timestamp
  }
}
```

### Bulk Loading

Load data from NDJSON files:

```bash
# Load a single file
python -m brain_researcher.services.br_kg.bulk_loader data.ndjson

# Load with options
python -m brain_researcher.services.br_kg.bulk_loader \
  data.ndjson \
  --batch-size 1000 \
  --workers 4 \
  --verbose

# Load directory of files
python -m brain_researcher.services.br_kg.bulk_loader data_dir/
```

#### NDJSON Format

```json
{"type": "Concept", "id": "c1", "name": "memory", "definition": "..."}
{"type": "Task", "id": "t1", "name": "n-back", "description": "..."}
{"type": "MEASURES", "source_id": "c1", "target_id": "t1", "confidence": 0.9}
```

### Persisted Queries

List available queries:
```bash
curl http://localhost:5000/api/queries
```

Execute a persisted query:
```bash
curl -X POST http://localhost:5000/api/queries/Q1_TASK_TO_REGION \
  -H "Content-Type: application/json" \
  -d '{"taskId": "n-back"}'
```

Available queries include:
- `Q1_TASK_TO_REGION` - Find brain regions for a task
- `Q2_PUB_TO_COORDS` - Get coordinates from publication
- `Q3_CONCEPT_NETWORK` - Related concepts within N hops
- `Q4_REGION_TASKS` - Tasks activating a region
- ... and 16 more

## API Reference

### REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/queries` | GET | List persisted queries |
| `/api/queries/<id>` | POST | Execute persisted query |
| `/graphql` | POST | GraphQL endpoint |

### Node Types

- **Concept** - Cognitive concepts (id, name, definition)
- **Task** - Experimental tasks (id, name, description)
- **BrainRegion** - Canonical public brain region node for substrate readiness
- **Region** - Compatibility / future-enrichment atlas region node
- **Dataset** - Study datasets (id, name, accession, subject_count)
- **Publication** - Scientific papers (id, pmid, title, year)

### Relationship Types

- `MEASURES` - Concept measured by task
- `ACTIVATES` - Task activates region-like target (`Region` or `BrainRegion`)
- `DERIVED_FROM` - Data derivation
- `RELATED_TO` - General relationship
- `PART_OF` - Canonical anatomy hierarchy is `BrainRegion -> BrainRegion`
- `SUBCLASS_OF` - Ontological relationship
- `CITES`/`CITED_BY` - Citation network
- `COACTIVATES_WITH` - Co-activation
- `SIMILAR_TO` - Similarity relationship
- `CONTRASTS_WITH` - Contrast relationship
- `USES_TASK` - Dataset uses task
- `IN_REGION` - Canonical substrate path is `StatsMap -> BrainRegion`; `Coordinate -> Region` is future enrichment
- `HAS_COORDINATE` - Has spatial coordinate

## Database Configuration

Neo4j is now the default (and required) backend. Configure it via environment variables:

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
```

## Performance

- **Bulk Loading**: 121+ entities/second
- **GraphQL Queries**: <100ms p95
- **Persisted Queries**: Cached with TTL
- **Batch Processing**: 1000 entities default
- **Memory**: Streaming for large datasets

## Testing

```bash
# Run all BR-KG tests
pytest tests/services/br-kg/ -v

# Specific test suites
pytest tests/services/br-kg/test_graphql_comprehensive.py
pytest tests/services/br-kg/test_bulk_loader.py
pytest tests/services/br-kg/test_persisted_queries.py
pytest tests/services/br-kg/test_integration.py
```

### Test Coverage
- GraphQL: 90.7% (39/43 tests passing)
- Bulk Loader: 100% (5/5 tests passing)
- Persisted Queries: 92.3% (12/13 tests passing)
- Integration: 83.3% (5/6 tests passing)

## Development

### Adding New Node Types

1. Update schema in `gql_schema/schema_simple.py`
2. Add validation in `bulk_loader.py`
3. Update persisted queries if needed
4. Add tests

### Adding New Queries

1. Add to `persisted_queries.py`
2. Define in appropriate category
3. Include parameters and description
4. Test with executor

## Architecture

```
br-kg/
├── app.py                    # Flask application
├── gql_schema/              # GraphQL schemas
│   ├── schema_simple.py    # Main schema
│   └── relationships.py    # Relationship types
├── bulk_loader.py           # NDJSON bulk loader
├── persisted_queries.py     # Pre-defined queries
├── graph/                   # Database adapters
│   ├── graph_database.py   # Base implementation
│   └── neo4j_graph_database.py  # Neo4j adapter
└── scripts/                 # Utility scripts
    └── seed_neo4j.py       # Database seeding
```

## Troubleshooting

### Port Already in Use
```bash
# Find process using port 5000
lsof -i :5000
# Kill if needed
kill <PID>
```

### Database Connection Issues
- Check environment variables
- Verify Neo4j is running (if using)
- Check file permissions for SQLite

### GraphQL Errors
- Verify strawberry-graphql is installed
- Check schema syntax
- Review error messages in response

## License

Part of the Brain Researcher project.
