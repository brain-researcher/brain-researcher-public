# Extract a sanitized public KG dump

`scripts/oss/extract_public_kg.py` produces a publishable subset of the live
Brain Researcher knowledge graph by:

1. Reading the `public` profile from `configs/br-kg/pii_redaction.yaml`.
2. Applying per-label keep/drop/transform rules from that profile.
3. For node labels not covered by the PII config, applying a
   white/blacklist policy declared in the script itself
   (`UNCOVERED_DEFAULT_POLICY`).
4. Stripping a fixed defense-in-depth property set (`ALWAYS_STRIP_PROPERTIES`)
   from every shipped node.

Outputs go to `<out>/kg_public.cypher` and `<out>/kg_public_manifest.json`.

## Workflow

```bash
# 1. Sanity-check the extractor with the bundled GABRIEL sample (no Neo4j).
python scripts/oss/extract_public_kg.py --dry-run --out /tmp/kg-extract-test

# 2. Inspect the manifest — confirm the label policy looks right.
jq '.labels_dropped_unknown_to_extractor,
    .labels_shipped_by_default_uncovered_whitelist,
    .labels_dropped_by_default_uncovered_blacklist' \
   /tmp/kg-extract-test/kg_public_manifest.json

# 3. Real run against your live Neo4j.
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=<your-password>
python scripts/oss/extract_public_kg.py \
  --out /tmp/kg-public-v0.1.0

# 4. Review the counts. Investigate any large kept-counts for sensitive
#    labels; if anything is unexpected, edit UNCOVERED_DEFAULT_POLICY or
#    pii_redaction.yaml and rerun.
cat /tmp/kg-public-v0.1.0/kg_public_manifest.json | jq '.counts'

# 5. Load into a fresh Neo4j to verify, then dump:
docker run -d --rm --name kg-verify -p 7497:7687 \
    -e NEO4J_AUTH=neo4j/verifypass neo4j:5.20
sleep 30
cypher-shell -a bolt://localhost:7497 -u neo4j -p verifypass \
    < /tmp/kg-public-v0.1.0/kg_public.cypher
docker exec kg-verify neo4j-admin database dump \
    --to-path=/var/lib/neo4j/dumps neo4j
docker cp kg-verify:/var/lib/neo4j/dumps/neo4j.dump \
    /tmp/kg-public-v0.1.0/kg-public.neo4j.dump
docker stop kg-verify

# 6. Ship the dump. Two reasonable hosts:
#    - GitHub Release artifact attached to the brain-researcher-public tag
#    - Zenodo deposit with a DOI (recommended for citability)
```

## Policy: which labels go where

The script's `UNCOVERED_DEFAULT_POLICY` partitions every label in
`bulk_loader.VALID_NODE_TYPES` into one of three buckets:

- **ship** — scientific reference content with no per-session or per-user
  state. Includes `Author`, `Atlas`, `Construct`, `DiseaseTrait`, `Gene`,
  most `Review*` config catalogs, etc.
- **drop** — runtime / session / internal-policy state. Includes
  `AgentSession`, `TaskSurface`, `ValidationEvidence`, `OpenRisk`,
  `Lesson`, `NextAction`, `ReviewPolicyDecision`.
- **unknown** — any label the script doesn't recognize is dropped by
  default (fail-closed). Add it explicitly to one of the two buckets if
  it should ship.

The PII config's `public` profile takes precedence over `UNCOVERED_DEFAULT_POLICY`
for the labels it covers (Publication, Task, Concept, Region, Coordinate,
Dataset, Subject, SubjectGroup, Contrast, StatisticalMap).

## When to update the script

- New node label added to `VALID_NODE_TYPES`: add it to either
  `UNCOVERED_DEFAULT_POLICY["ship"]` or `["drop"]` so it doesn't get
  silently fail-closed dropped.
- New property class identified as sensitive: add to
  `ALWAYS_STRIP_PROPERTIES`.
- Per-deployment overrides: today these live in this file; for v0.2 the
  policy will move to a separate YAML so the extractor stays vendor-
  neutral.

## What this does NOT do

- Edge filtering. v0.1.0 ships nodes only; edges (relationships) need a
  follow-up extraction with the same per-type policy. The PII config
  covers `ACTIVATES` and `MEASURES`; everything else needs explicit
  rules before edges can ship.
- License audit per data source. The extractor enforces redaction, not
  redistribution rights. Before publishing the dump, confirm each
  source (Neurosynth CC0, NeuroVault mixed, OpenNeuro mixed, PMC OA
  mostly CC-BY, etc.) allows redistribution of the derived KG content.
- Diff against previous dumps. If you publish multiple versions, add
  your own delta logic on top of the manifest's per-label counts.
