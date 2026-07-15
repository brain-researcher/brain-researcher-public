# Create `ACTIVATES` edges from coordinate evidence

`create_activation_edges.py` reads coordinate evidence from BR-KG's Neo4j
database and creates missing `ACTIVATES` relationships from `Task` or `Concept`
nodes to `BrainRegion` nodes.

The script is a database maintenance command. A normal run writes to Neo4j;
`--dry-run` performs the reads and reports what would be created without writing
relationships.

Run every command below from the **repository root**, the directory containing
`pyproject.toml` and `scripts/`.

## Prerequisites

1. Install the Python package using the
   [root setup guide](../../README.md#install-as-a-python-package).
2. Start or select the Neo4j database you intend to inspect.
3. Put its connection settings in your untracked root `.env`:
   `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and optionally
   `NEO4J_DATABASE`.
4. Confirm that this is the intended database before running without
   `--dry-run`. The command does not create a backup.

Load the environment into the current shell:

```bash
cd "$(git rev-parse --show-toplevel)"
set -a
source .env
set +a

python scripts/br-kg/create_activation_edges.py --help
```

The command requires `NEO4J_URI` and `NEO4J_PASSWORD`. `NEO4J_USER` defaults to
`neo4j`; Neo4j chooses its default database when `NEO4J_DATABASE` is unset.

## Recommended sequence

Preview first:

```bash
python scripts/br-kg/create_activation_edges.py \
  --threshold 5 \
  --dry-run \
  --verbose
```

Inspect the reported candidates and errors. In dry-run output,
`edges_created` means “edges that would be created”; no relationships are
written.

When the preview is correct, run the mutation explicitly:

```bash
python scripts/br-kg/create_activation_edges.py --threshold 5
```

Available options:

- `--threshold N`: require at least `N` distinct supporting coordinates;
  default `5`
- `--dry-run`: collect and count evidence without writing relationships
- `--verbose`: enable debug logging

The optional positional `db_path` shown by `--help` is deprecated and ignored.
Connection details always come from the `NEO4J_*` environment variables.

## Required graph shape

The validation step requires all of these labels:

- `Task`
- `Concept`
- `Coordinate`
- `BrainRegion`
- at least one of `Study` or `Publication`

Evidence is collected along these directed paths:

```text
(Study|Publication)-[:STUDIES|MENTIONS_CONCEPT]->(Task|Concept)
(Study|Publication)-[:HAS_COORDINATE]->(Coordinate)
(Coordinate)-[:LOCATED_IN]->(BrainRegion)
```

Missing expected relationship types are reported as warnings because a
partially loaded database may legitimately have no rows for one type. If no
coordinate evidence is found, that label produces no candidate edges.

## Edge behavior

For each `(Task|Concept, BrainRegion)` pair, the script de-duplicates coordinate
IDs and applies the threshold. It skips an `ACTIVATES` relationship that already
exists; it does not update or replace that edge.

New relationships contain:

- `evidence_count`: number of distinct supporting coordinates
- `coordinate_ids`: up to 10 supporting coordinate IDs
- `confidence`: `min(evidence_count / 10, 1.0)`
- `method`: `coordinate_aggregation`
- `threshold`: threshold used for this run

## Illustrative output

Exact counts depend on the selected database. A run ends with a summary shaped
like this:

```text
SUMMARY
Total edges created: 73
Total skipped (threshold): 38
Total skipped (exists): 13
Total errors: 0
Database growth: 12000 -> 12073 relationships
```

These numbers are examples, not expected values for a fresh checkout or another
Neo4j database.

## Test without Neo4j

The focused unit test uses an in-memory graph helper and does not connect to the
configured Neo4j database:

```bash
python -m pytest -q -p no:cacheprovider \
  --confcutdir=tests/unit/br_kg \
  tests/unit/br_kg/test_create_activation_edges.py
```

Passing this unit test checks threshold, dry-run, existing-edge, and empty-graph
behavior. It does not prove that a particular Neo4j database has the required
data or credentials.
