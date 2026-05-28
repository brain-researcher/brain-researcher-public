# Public KG dump (GitHub Release artifact)

Brain Researcher ships a sanitized Neo4j snapshot alongside each release
of `brain-researcher-public`. The dump is attached to the GitHub Release
(not committed to the repo because of size) and produced via
`scripts/oss/extract_public_kg.py` → `EXTRACT_PUBLIC_KG.md`.

## What's in the dump

- Scientific reference nodes: Atlas, Author, Concept, Construct,
  Contrast, DiseaseTrait, Gene, Phenotype, Population, Publication,
  Region (incl. BrainRegion), RiskLocus, Study, Task, TaskFamily.
- Coordinate facts (rounded to 1mm per PII-02).
- Claim / EvidenceSpan / MeasurementRun / Assumption from the
  GABRIEL extraction pipeline.
- Review machinery catalogs (rule/severity/schema-field/positive-modifier/
  reason-tag/validity-layer/sensitivity-template).

## What's NOT in the dump

- Subject identifiers beyond hashed `id` (per PII-01).
- Per-session agent state (AgentSession, TaskSurface,
  ValidationEvidence, OpenRisk, Outcome, Lesson, NextAction).
- Internal review policy decisions (ReviewPolicyDecision).
- Properties on shipped nodes that are credential-shaped or path-shaped
  (see `ALWAYS_STRIP_PROPERTIES` in the extractor).
- Edges (v0.1.0 ships nodes only — edge filter lands in v0.2; see the
  extractor runbook).

## How to load the dump

### Option A: `docker compose` with the bundled `neo4j` service

```bash
# 1. Download the dump (after the v0.1.0 GitHub Release is published).
mkdir -p data/neo4j-dumps
curl -L -o data/neo4j-dumps/kg-public-v0.1.0.dump \
  https://github.com/zjc062/brain-researcher-public/releases/download/v0.1.0/kg-public-v0.1.0.dump

# 2. Stop the running neo4j to allow load.
docker compose stop neo4j

# 3. Load the dump into the volume.
docker run --rm \
  -v "$(pwd)/data/neo4j:/data" \
  -v "$(pwd)/data/neo4j-dumps:/dumps:ro" \
  neo4j:5.20 \
  neo4j-admin database load --from-path=/dumps --overwrite-destination=true neo4j

# 4. Restart and verify.
docker compose start neo4j
sleep 15
docker compose exec neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC LIMIT 10;"
```

### Option B: standalone Neo4j

```bash
neo4j-admin database load --from-path=/path/to/dumps neo4j
```

Then point `NEO4J_URI` / `NEO4J_PASSWORD` env vars at it.

## Provenance + integrity

Each release artifact ships with a manifest:

- `kg-public-vX.Y.Z.dump`         — the Neo4j dump
- `kg-public-vX.Y.Z.manifest.json` — per-label counts, redaction policy
  applied, sha256 of the dump, extractor version, source `pii_redaction`
  profile name
- `kg-public-vX.Y.Z.dump.sha256`  — checksum file for verification

Verify:
```bash
sha256sum -c kg-public-v0.1.0.dump.sha256
```

## Building your own dump

If you want to build the dump from your own Neo4j (or contribute an
updated public snapshot), follow `scripts/oss/EXTRACT_PUBLIC_KG.md`.
The pipeline is reproducible: same Neo4j input + same script version =
identical `kg_public.cypher` output.

## License

The dump aggregates derived content from multiple upstream sources
(Neurosynth CC0, Cognitive Atlas CC-BY, ChEMBL CC-BY-SA, PMC OA
[various], NeuroVault [mixed per-image], OpenNeuro [mixed]). Each
release's manifest lists the per-source compliance audit. Downstream
redistribution must honor the most-restrictive upstream license among
nodes touched by the user's queries.
