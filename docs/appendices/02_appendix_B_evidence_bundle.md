# Appendix B. Evidence Bundle / BR-KG Card

This appendix has two parts.

- **Part 1 — BR-KG System Data Card.** System-level inventory, provenance, contribution protocol, and release-audit detail for the BR-KG knowledge graph. Use this part as a stable reference. Re-issue when the BR-KG snapshot changes.
- **Part 2 — Per-episode evidence bundle template.** Fillable card recording the evidence substrate used during planning and review for one episode. Every accepted claim in Appendix G must trace back to rows in this card.

---

# Part 1 — BR-KG System Data Card

## Document map

This document is designed for two linked uses: explaining what BR-KG is today, and preparing a practical contribution mechanism for the people who will help maintain it. The main body avoids unnecessary jargon; appendices keep the exact labels, counts, source values, and release-audit details.

1. Executive summary and plain-language glossary
2. Current BR-KG contents, sources, build path, quality gaps, and release-readiness notes
3. Visual atlas figures for graph composition, schema topology, source provenance, and representative query paths
4. Community contribution mechanism: raw sources → wiki layer → compiled graph
5. Appendices with full counts, schema triples, source audit, property coverage, quality artifacts, and original reader-question checklist tables

## Executive summary

BR-KG is a production knowledge graph for neuroscience research. It links papers, activation coordinates, statistical maps, tasks, concepts, datasets, tools, brain regions, embeddings, and review/governance records. The graph is stored in Neo4j and is used as a structured evidence layer for Brain Researcher workflows.

The checked production snapshot is large but uneven: core identifiers and source fields are mostly present, while edge confidence, edge weights, licenses, and source-specific release metadata still need cleanup before a public release. The community-contribution mechanism proposed here is meant to make long-term maintenance easier without weakening schema control.

| Metric | Value | Notes |
|--------|------:|-------|
| Unique nodes | 694,135 | snapshot-specific |
| Edges | 2,423,334 | directed relationships |
| Active node labels | 75 | labels with at least one node |
| Active relationship types | 85 | types with at least one edge |
| Canonical schema triples | 151 | source-label / edge / target-label patterns |
| Orphan nodes | 52,029 | 7.50% have degree 0 |

### Top node labels

The full 75-label table is preserved in Appendix B (below).

| Node label | Count | Share |
|------------|------:|------:|
| Coordinate | 447,499 | 64.47% |
| Publication | 49,744 | 7.17% |
| Collection | 48,009 | 6.92% |
| StatsMap | 35,240 | 5.08% |
| Task | 34,926 | 5.03% |
| Embedding | 23,865 | 3.44% |
| StatisticalMap | 21,283 | 3.07% |
| DataResource | 9,282 | 1.34% |
| OpenNeuro | 7,619 | 1.10% |
| ToolVersion | 4,142 | 0.60% |
| Term | 3,228 | 0.47% |
| Concept | 2,336 | 0.34% |

### Top relationship types

The full 85-relationship table is preserved in Appendix C (below).

| Relationship type | Count | Share |
|-------------------|------:|------:|
| BELONGS_TO | 1,077,573 | 44.47% |
| HAS_COORDINATE | 447,499 | 18.47% |
| HAS_TERM | 358,050 | 14.78% |
| IN_REGION | 121,261 | 5.00% |
| ABOUT | 75,922 | 3.13% |
| IN_ONVOC | 63,160 | 2.61% |
| IN_DOMAIN | 52,117 | 2.15% |
| IN_SPACE | 35,199 | 1.45% |
| COMPUTED_WITH | 30,880 | 1.27% |
| GENERATED_FROM | 30,880 | 1.27% |
| DERIVED_FROM | 30,163 | 1.24% |
| MAPS_TO | 17,667 | 0.73% |

### Largest node source-like values

Full node/edge source counts and source-by-label coverage are in Appendix D (below).

| Source-like value | Node count | Edge count with same source-like value |
|-------------------|-----------:|---------------------------------------:|
| neurosynth | 464,946 | 358,050 |
| neurostore | 97,238 | 0 |
| openneuro_glmfitlins | 45,395 | 266,193 |
| neurovault | 37,467 | 1,076,839 |
| niclip | 23,865 | 0 |
| `<missing>` | 6,889 | 41,393 |
| cognitive_atlas | 4,214 | 14,591 |
| scholarly_metadata_stub | 2,557 | 0 |
| capabilities.merged.yaml | 2,073 | 0 |
| cognitive_atlas_niclip | 1,772 | 0 |
| neurobagel:OpenNeuro | 1,580 | 1,259 |
| Allen Brain Atlas | 1,329 | 1,328 |

### Provenance and scoring coverage

| Coverage item | Present | Total | Coverage |
|---------------|--------:|------:|---------:|
| Nodes with id | 693,919 | 694,135 | 99.97% |
| Nodes with source | 687,246 | 694,135 | 99.01% |
| Edges with source-like value | 2,381,941 | 2,423,334 | 98.29% |
| Edges with confidence | 318,609 | 2,423,334 | 13.15% |
| Edges with weight | 480,061 | 2,423,334 | 19.81% |

## 6. Maintenance and contribution protocol: v0 plan

### Purpose

NeuroKG should not be treated as a static graph dump. It is a maintained scientific knowledge system whose reliability depends on three processes working together:

- **Source refresh**: external sources such as OpenNeuro, NeuroVault, Neurostore, PubMed, Cognitive Atlas, ONVOC, atlases, and tool registries need explicit refresh schedules and source-specific provenance.
- **Human contribution**: domain experts should be able to submit corrections, mappings, evidence links, and workflow notes without writing Cypher or directly editing Neo4j.
- **Agent contribution**: automated agents should be able to propose structured graph changes, but those proposals must remain candidate records until validated and reviewed.

The goal is to make NeuroKG easy to improve while keeping the compiled graph schema-strict, provenance-aware, and scientifically conservative.

### Three-layer contribution architecture

| Layer | Plain-language role | What can change? | Release implication |
|------|--------------------|-------------------|--------------------|
| 1. Raw sources | Publications, datasets, ontology trees, and other upstream materials. | Immutable in this workflow. Update only through source refreshes or new source versions. | Cite upstream sources directly; do not let community edits rewrite raw evidence. |
| 2. Wiki layer | Human-friendly Markdown files, one template per entity type, with YAML frontmatter for structured fields. | Community edits through GitHub PRs; schema validation gates each change. | Best place for domain expertise, corrections, relation proposals, and documentation. |
| 3. Compiled graph | Validated, machine-readable Neo4j graph built periodically from raw sources plus accepted wiki records. | Changes only after validation and review. Rebuild cadence should be explicit. | Public KG claims should reference compiled graph snapshot, source provenance, and accepted wiki revisions. |

### Contribution flow

| Step | What happens | Quality gate |
|------|---------------|---------------|
| Edit Markdown | Contributor edits a wiki file or creates a new file from an entity-type template. | File path and YAML frontmatter must match a supported template. |
| Open GitHub PR | The PR contains the human-readable rationale plus machine-readable YAML fields. | CI runs schema checks, identifier normalization, and graph-diff preview. |
| Validation queue | Valid PRs are classified by risk: small correction, new finding, schema change, or source/governance change. | Invalid relation types, unresolved evidence, or missing required fields block merge. |
| Review queue | Human reviewers and optional LLM-assisted triage review evidence and fit with existing KG. | LLMs can triage/summarize, but high-impact scientific assertions need human review. |
| Compile to graph | Accepted records are compiled into Neo4j nodes/edges with provenance back to the wiki commit. | Graph update includes source marker, contributor metadata, review status, and snapshot date. |

## 8. V0 schema strawman and worked example

The v0 schema should be deliberately small. A practical default is to pilot only finding and correction records first, while drafting evidence, workflow, and pipeline templates so the repo structure is ready for expansion. A schema change should require a separate PR, not be smuggled into an ordinary contribution.

### Entity-type templates for the wiki layer

| Template | Purpose | Required fields | Controlled vocabulary / validation |
|----------|---------|-----------------|-------------------------------------|
| evidence | A source-backed evidence record (paper, dataset, or documented source artifact). | type, id, title/label, references, source, evidence_kind, status, schema_version | references must normalize to DOI/PMID/URL/dataset ID; evidence_kind from allowed list. |
| finding | A scientific assertion linking entities (task activating a region, map measuring a concept). | type, id, title, claim.subject, claim.relation_type, claim.object, evidence, confidence, status, schema_version | relation_type must be in the allowed graph relationship set or a schema-change PR. |
| correction | A proposed fix to a label, alias, mapping, relation, or source attribution. | type, id, target, correction_kind, proposed_change, rationale, evidence, status, schema_version | target must resolve to an existing graph entity or accepted wiki record. |
| workflow | A human-readable workflow note for curation, validation, or review. | type, id, title, steps, inputs, outputs, owner, status, schema_version | workflow status from draft/active/deprecated; inputs/outputs checked against supported artifact classes. |
| pipeline | A build or ingestion pipeline description. | type, id, title, source, loader, inputs, outputs, schedule, validation, status, schema_version | loader and source must map to known release/source registry rows. |

### Worked example: finding

```yaml
---
type: finding
id: finding-working-memory-dlpfc-001
schema_version: BR-KG-wiki-v0.1

status: proposed
title: Working-memory task activates a dorsolateral prefrontal cortex region
aliases:
  - working memory dlPFC activation
claim:
  subject:
    type: Task
    id: task:working_memory
    label: working memory task
  relation_type: ACTIVATES
  object:
    type: BrainRegion
    id: region:dlpfc_placeholder
    label: dorsolateral prefrontal cortex
  qualifiers:
    modality: fMRI
    coordinate_space: MNI
confidence:
  value: null
  tier: needs_review
  rationale: Example-only record; evidence must be reviewed before graph merge.
evidence:
  - type: publication
    doi: TODO
    pmid: TODO
    support_text: TODO short paraphrase or evidence pointer
provenance:
  contributor: github:example-user
  created_at: 2026-05-04
review:
  required: human
  suggested_reviewers:
    - cognitive-neuroscience
    - neuroimaging
---
```

Plain-language note: this file is a proposed scientific finding. It should not become an accepted KG edge until evidence IDs resolve and a reviewer approves the relation, region mapping, and confidence tier.

### Worked example: compiled graph diff preview

Graph diff preview generated by CI, not executed automatically:

```cypher
CREATE (:Finding {
  id: "finding-working-memory-dlpfc-001",
  title: "Working-memory task activates a dorsolateral prefrontal cortex region",
  status: "proposed",
  source: "wiki_contribution",
  schema_version: "BR-KG-wiki-v0.1"
})

MATCH (task:Task {id: "task:working_memory"})
MATCH (region:BrainRegion {id: "region:dlpfc_placeholder"})
CREATE (task)-[:ACTIVATES {
  source: "wiki_contribution",
  source_file: "findings/finding-working-memory-dlpfc-001.md",
  status: "proposed",
  confidence_tier: "needs_review",
  created_at: "2026-05-04"
}]->(region)
```

Expected validation warnings:

- region:dlpfc_placeholder must resolve to an atlas-backed BrainRegion or be replaced.
- DOI/PMID fields are TODO and must be filled before merge.
- confidence.value is null; human review required.

### Schema validation example: bad PR rejection

Bad PR frontmatter snippet:

```yaml
claim:
  subject: {type: Task, id: task:working_memory}
  relation_type: causes_increase_in
  object: {type: BrainRegion, id: region:dlpfc_placeholder}
```

CI result:

```
FAIL: relation_type "causes_increase_in" is not in the v0 allowed relation vocabulary.
Suggested fixes:
  1. Use an existing relation type such as ACTIVATES, MEASURES, RELATED_TO, or SUGGESTS_MEASURES when semantically appropriate.
  2. Open a separate schema-change PR proposing causes_increase_in, including directionality, allowed node types, evidence requirements, and review policy.
```

## Appendix A (system card). Snapshot anchors and status vocabulary

### Current anchor artifacts

| Artifact | What it anchors | Current note |
|----------|-----------------|---------------|
| `docs/BR-KG/BR-KG_reader_question_live_values_20260503.json.txt` | Raw live values used to fill this inventory | Generated from production Neo4j and source/property profile queries on 2026-05-03. The `.txt` suffix avoids the repo-wide `*.json` ignore rule for new files. |
| `docs/operations/prod_BR-KG_plot_probe_20260502/SUMMARY.md` | Production schema/plot probe | Bounded production queries through brain-researcher-vm and brain-researcher-BR-KG-0; useful but not a full data export. |
| `docs/operations/prod_BR-KG_plot_probe_20260502/tables/BR-KG_schema_inventory_data_dictionary.md` | Schema inventory file layout | Lists generated CSV/HTML inventory tables and recommended comprehensive table. |
| `docs/operations/prod_BR-KG_plot_probe_20260502/tables/BR-KG_schema_triples_comprehensive.csv` | Canonical source-label / relationship / target-label triples | 151 schema triples in the existing artifact. |
| `docs/operations/prod_BR-KG_plot_probe_20260502/tables/BR-KG_node_labels_inventory.csv` | Node-label counts and surfaces | 75 node labels; multi-label endpoints need careful interpretation. |
| `docs/operations/prod_BR-KG_plot_probe_20260502/tables/BR-KG_relationship_types_inventory.csv` | Relationship-type counts and dominant schema triples | 85 relationship types. |
| `docs/operations/prod_BR-KG_plot_probe_20260502/tables/BR-KG_schema_inventory_summary.json` | Schema inventory summary | total_edges=2,423,334, top1_share=44.4%, top3_share=77.6%, top10_share=93.4%. |
| `docs/specs/BR-KG_structural_quality_benchmark_v1.md` | KG structural-quality framing | Evaluation should be a versioned quality card, not only node/edge counts. |
| `docs/BR-KG/gabriel_full_pipeline.md` | Gabriel paper-mining generation/ingest lane | Anchors LLM/heuristic extraction, review queues, candidate lanes, and KGGen evaluation. |
| `docs/standards/BR-KG_Standards.md` | Standards skeleton | Useful for ID/provenance/merge-policy intent; verify before citing as implemented. |
| `docs/standards/BR-KG_graph_schema.md` | Historical sparse snapshot | Explicitly historical; do not use for current live graph claims. |

### Status vocabulary

| Status label | Plain-language meaning |
|--------------|-------------------------|
| verified-current | Checked against a current graph dump, code path, or run artifact. |
| artifact-needs-refresh | Supported by an artifact, but the artifact may not be the latest production snapshot. |
| partial | Implemented or documented only for some sources, labels, or relationships. |
| spec-only | Described as the desired contract, but not verified as live behavior. |
| missing | Not found yet. |

## Appendix B (system card). Full headline and node-label counts

### Headline values

| Metric | Value | Evidence / caveat |
|--------|------:|--------------------|
| Snapshot date | 2026-05-03 | Live query against production Neo4j pod |
| Query target | production Neo4j via brain-researcher-BR-KG-0 | Production connection target |
| Unique nodes | 694,135 | `MATCH (n) RETURN count(n)` |
| Edges | 2,423,334 | `MATCH ()-[r]->() RETURN count(r)` |
| Active node labels | 75 | Labels present on at least one node |
| Token-store node labels | 87 | Includes zero-node labels |
| Active relationship types | 85 | Types present on at least one edge |
| Token-store relationship types | 86 | Includes zero-edge relationship types |
| Canonical schema triples | 151 | Source-label / relationship / target-label patterns |
| Property keys | 626 | `CALL db.propertyKeys()` |
| Indexes | 87 | `SHOW INDEXES` |
| Constraints | 27 | `SHOW CONSTRAINTS` |
| Degree min / median / mean / p95 / p99 / max | 0 / 1 / 6.9740 / 25 / 71 / 36,737 | Undirected degree summary |
| StatsMap nodes / distinct runs | 35,240 / 18 | `MATCH (s:StatsMap)` |
| Text embeddings | 23,865; dim=4096; model=BrainGPT-7B-v0.2; source=niclip | Embedding nodes |
| Task embeddings | 44 text, 44 behavior, 44 both / 34,926 Task nodes | Task node properties |

### Full active node-label counts

| Node label | Count | Share of unique nodes |
|------------|------:|----------------------:|
| Coordinate | 447,499 | 64.47% |
| Publication | 49,744 | 7.17% |
| Collection | 48,009 | 6.92% |
| StatsMap | 35,240 | 5.08% |
| Task | 34,926 | 5.03% |
| Embedding | 23,865 | 3.44% |
| StatisticalMap | 21,283 | 3.07% |
| DataResource | 9,282 | 1.34% |
| OpenNeuro | 7,619 | 1.10% |
| ToolVersion | 4,142 | 0.60% |
| Term | 3,228 | 0.47% |
| Concept | 2,336 | 0.34% |
| Contrast | 2,206 | 0.32% |
| BrainRegion | 2,140 | 0.31% |
| Dataset | 2,136 | 0.31% |
| Tool | 2,084 | 0.30% |
| Phenotype | 1,218 | 0.18% |
| Citation | 1,201 | 0.17% |
| Subject | 1,139 | 0.16% |
| TaskCondition | 807 | 0.12% |
| OntologyConcept | 752 | 0.11% |
| OnvocClass | 752 | 0.11% |
| GLMContrast | 621 | 0.09% |
| TaskIndicator | 584 | 0.08% |
| SubjectGroup | 402 | 0.06% |
| Condition | 310 | 0.04% |
| GLMDesignPrior | 216 | 0.03% |
| Author | 172 | 0.02% |
| TaskFamily | 138 | 0.02% |
| Institution | 119 | 0.02% |
| TaskSpec | 110 | 0.02% |
| ReviewSchemaField | 106 | 0.02% |
| ResourceType | 102 | 0.01% |
| ToolFamily | 96 | 0.01% |
| Repository | 88 | 0.01% |
| BrainAnnotation | 86 | 0.01% |
| ReviewImplementationRule | 80 | 0.01% |
| ModelSpec | 78 | 0.01% |
| Experiment | 76 | 0.01% |
| Psych101Experiment | 76 | 0.01% |
| TaskAnalysis | 72 | 0.01% |
| ReviewRule | 71 | 0.01% |
| ReviewCalibrationCase | 60 | 0.01% |
| StatMap | 60 | 0.01% |
| Consortium | 38 | 0.01% |
| Study | 33 | 0.00% |
| Modality | 28 | 0.00% |
| Parcellation | 28 | 0.00% |
| Battery | 27 | 0.00% |
| Parcel | 26 | 0.00% |
| Finding | 16 | 0.00% |
| Species | 14 | 0.00% |
| ReviewRuleGroup | 13 | 0.00% |
| IngestionRun | 12 | 0.00% |
| ConceptClass | 10 | 0.00% |
| Process | 10 | 0.00% |
| TemplateSpace | 10 | 0.00% |
| Region | 8 | 0.00% |
| ReviewReasonTag | 8 | 0.00% |
| GLMVariant | 7 | 0.00% |
| ReviewPolicyDecision | 6 | 0.00% |
| ReviewLifecycleStatus | 5 | 0.00% |
| ReviewSensitivityTemplate | 5 | 0.00% |
| ReviewValidityLayer | 5 | 0.00% |
| ExecutionFailure | 4 | 0.00% |
| Run | 4 | 0.00% |
| Atlas | 2 | 0.00% |
| ReviewSeverity | 2 | 0.00% |
| GLMRun | 1 | 0.00% |
| Psych101Dataset | 1 | 0.00% |
| ResultSummary | 1 | 0.00% |
| ReviewImplementationRuleCatalog | 1 | 0.00% |
| ReviewPositiveModifier | 1 | 0.00% |
| ReviewRuleRegistry | 1 | 0.00% |
| ToolEvidence | 1 | 0.00% |

## Appendix C (system card). Full relationship counts and aliases

### Full active relationship-type counts

| Relationship type | Count | Share of edges |
|-------------------|------:|---------------:|
| BELONGS_TO | 1,077,573 | 44.47% |
| HAS_COORDINATE | 447,499 | 18.47% |
| HAS_TERM | 358,050 | 14.78% |
| IN_REGION | 121,261 | 5.00% |
| ABOUT | 75,922 | 3.13% |
| IN_ONVOC | 63,160 | 2.61% |
| IN_DOMAIN | 52,117 | 2.15% |
| IN_SPACE | 35,199 | 1.45% |
| COMPUTED_WITH | 30,880 | 1.27% |
| GENERATED_FROM | 30,880 | 1.27% |
| DERIVED_FROM | 30,163 | 1.24% |
| MAPS_TO | 17,667 | 0.73% |
| HAS_RESOURCE | 14,728 | 0.61% |
| HAS_TEXT_EMBEDDING | 12,958 | 0.53% |
| MEASURES | 10,875 | 0.45% |
| IMPLEMENTS_FAMILY | 4,294 | 0.18% |
| HAS_VERSION | 4,142 | 0.17% |
| CITES | 3,397 | 0.14% |
| SUPPORTS_MODALITY | 2,655 | 0.11% |
| SUGGESTS_MEASURES | 2,514 | 0.10% |
| HAS_CONTRAST | 2,464 | 0.10% |
| HAS_REGION | 2,123 | 0.09% |
| PARTICIPATES_IN | 1,982 | 0.08% |
| HAS_MODALITY | 1,839 | 0.08% |
| HOSTED_AT | 1,694 | 0.07% |
| HAS_TASK | 1,679 | 0.07% |
| PART_OF | 1,425 | 0.06% |
| HASCITATION | 1,293 | 0.05% |
| ASSERTS | 1,237 | 0.05% |
| HAS_PHENOTYPE | 1,218 | 0.05% |
| MEASUREDBY | 1,218 | 0.05% |
| INVOLVES_SPECIES | 990 | 0.04% |
| CLASSIFIED_UNDER | 863 | 0.04% |
| HASCONDITION | 807 | 0.03% |
| USES_CONDITION | 750 | 0.03% |
| HASINDICATOR | 584 | 0.02% |
| CLASSIFIEDUNDER | 523 | 0.02% |
| KINDOF | 429 | 0.02% |
| INCLUDES | 402 | 0.02% |
| PRODUCES_RESOURCE | 362 | 0.01% |
| CONSUMES_RESOURCE | 338 | 0.01% |
| HAS_CONDITION | 310 | 0.01% |
| AFFILIATED_WITH | 292 | 0.01% |
| PARTOF | 263 | 0.01% |
| AUTHORED_BY | 232 | 0.01% |
| HAS_GLM_PRIOR | 224 | 0.01% |
| RELATED_TO | 190 | 0.01% |
| BELONGS_TO_FAMILY | 176 | 0.01% |
| REQUIRES_FIELD | 163 | 0.01% |
| USES_TASK | 152 | 0.01% |
| INBATTERY | 134 | 0.01% |
| HAS_VALIDITY_LAYER | 102 | 0.00% |
| HAS_REASON_TAG | 81 | 0.00% |
| CONTAINS_IMPLEMENTATION_RULE | 80 | 0.00% |
| HAS_EXPERIMENT | 76 | 0.00% |
| DESCRIBES_TASK | 72 | 0.00% |
| CONTAINS_RULE | 71 | 0.00% |
| HAS_LIFECYCLE_STATUS | 71 | 0.00% |
| HAS_SEVERITY | 71 | 0.00% |
| IN_RULE_GROUP | 71 | 0.00% |
| CONTAINS_CALIBRATION_CASE | 60 | 0.00% |
| CALIBRATES_RULE | 55 | 0.00% |
| CONTRAST_OF | 53 | 0.00% |
| CITED_BY | 49 | 0.00% |
| MAPPED_TO_IMPLEMENTATION | 28 | 0.00% |
| HAS_PARCEL | 26 | 0.00% |
| IN_PARCELLATION | 17 | 0.00% |
| VALIDATED_ON | 13 | 0.00% |
| HAD_FAILURE | 7 | 0.00% |
| HAS_VARIANT | 7 | 0.00% |
| ACTIVATES | 6 | 0.00% |
| HAS_POLICY_DECISION | 6 | 0.00% |
| TRIGGERS_SENSITIVITY | 5 | 0.00% |
| FAILED_ON | 3 | 0.00% |
| DOCUMENTED_IN | 2 | 0.00% |
| HAS_GLM_RUN | 2 | 0.00% |
| HAS_PARCELLATION | 2 | 0.00% |
| CALIBRATES_MODIFIER | 1 | 0.00% |
| CONTAINS_MODIFIER | 1 | 0.00% |
| HAS_EVIDENCE | 1 | 0.00% |
| HAS_SUMMARY | 1 | 0.00% |
| LOCATED_IN | 1 | 0.00% |
| MEASURED_BY | 1 | 0.00% |
| MENTIONS_CONCEPT | 1 | 0.00% |
| SIMILAR_TO | 1 | 0.00% |

### Requested manuscript-facing alias presence

| Requested/manuscript alias | Live active count | Status |
|-----------------------------|-------------------:|--------|
| mentions / MENTIONS | 0 | not present as active relationship type |
| mentions_concept / MENTIONS_CONCEPT | 1 | present |
| reports_activation_at / REPORTS_ACTIVATION_AT | 0 | not present as active relationship type |
| associated_with / ASSOCIATED_WITH | 0 | not present as active relationship type |
| part_of / PART_OF | 1,425 | present |
| projects_to / PROJECTS_TO | 0 | not present as active relationship type |
| shares_term / SHARES_TERM | 0 | not present as active relationship type |
| is_a / IS_A | 0 | not present as active relationship type |
| supersedes / SUPERSEDES | 0 | not present as active relationship type |
| co_occurs_with / CO_OCCURS_WITH | 0 | not present as active relationship type |

## Appendix D (system card). Source-like values and source-by-label coverage

### Combined source-like node and edge counts

| Source-like property value | Node count | Node share | Edge count | Edge share |
|----------------------------|-----------:|-----------:|-----------:|-----------:|
| neurovault | 37,467 | 5.40% | 1,076,839 | 44.44% |
| neurosynth | 464,946 | 66.98% | 358,050 | 14.78% |
| neurosynth_v7 | 0 | 0.00% | 447,498 | 18.47% |
| openneuro_glmfitlins | 45,395 | 6.54% | 266,193 | 10.98% |
| config_text_backfill | 0 | 0.00% | 104,603 | 4.32% |
| neurostore | 97,238 | 14.01% | 0 | 0.00% |
| neurostore_metadata | 0 | 0.00% | 52,117 | 2.15% |
| `<missing>` | 6,889 | 0.99% | 41,393 | 1.71% |
| onvoc_linker | 0 | 0.00% | 34,445 | 1.42% |
| niclip | 23,865 | 3.44% | 0 | 0.00% |
| cognitive_atlas | 4,214 | 0.61% | 14,591 | 0.60% |
| neurostore_taxonomy | 0 | 0.00% | 9,143 | 0.38% |
| openneuro_glmfitlins_inferred | 0 | 0.00% | 6,436 | 0.27% |
| scholarly_metadata | 333 | 0.05% | 3,919 | 0.16% |
| neurobagel:OpenNeuro | 1,580 | 0.23% | 1,259 | 0.05% |
| Allen Brain Atlas | 1,329 | 0.19% | 1,328 | 0.05% |
| scholarly_metadata_stub | 2,557 | 0.37% | 0 | 0.00% |
| capabilities.merged.yaml | 2,073 | 0.30% | 0 | 0.00% |
| cognitive_atlas_niclip | 1,772 | 0.26% | 0 | 0.00% |
| nilearn | 816 | 0.12% | 810 | 0.03% |
| onvoc | 752 | 0.11% | 765 | 0.03% |
| Allen CCFv3 | 0 | 0.00% | 1,326 | 0.05% |
| multiverse_fitlins_runonly | 60 | 0.01% | 1,020 | 0.04% |
| pubmed_api | 1,047 | 0.15% | 0 | 0.00% |
| neurobagel:International Neuroimaging Data-sharing Initiative | 442 | 0.06% | 361 | 0.01% |
| cognitive_atlas_cao | 645 | 0.09% | 0 | 0.00% |
| taxonomy_rule | 0 | 0.00% | 612 | 0.03% |
| Psych-101 | 127 | 0.02% | 375 | 0.02% |
| task_families | 314 | 0.05% | 0 | 0.00% |
| PubMed | 161 | 0.02% | 5 | 0.00% |
| task_family_enrichment | 14 | 0.00% | 126 | 0.01% |
| neuromaps | 86 | 0.01% | 0 | 0.00% |
| openneuro_glmfitlins_manual | 0 | 0.00% | 50 | 0.00% |
| disease_path_backfill | 0 | 0.00% | 34 | 0.00% |
| psych-101_taxonomy | 0 | 0.00% | 13 | 0.00% |
| openneuro_glmfitlins_taxonomy | 8 | 0.00% | 0 | 0.00% |
| GraphQL API | 0 | 0.00% | 5 | 0.00% |
| CogAtlas | 0 | 0.00% | 5 | 0.00% |
| seed | 0 | 0.00% | 4 | 0.00% |
| taxonomy_surface_rules | 4 | 0.00% | 0 | 0.00% |
| Manual | 0 | 0.00% | 2 | 0.00% |
| psych101_curated_registry | 0 | 0.00% | 2 | 0.00% |
| bulk_loader | 0 | 0.00% | 1 | 0.00% |
| OpenNeuro | 0 | 0.00% | 1 | 0.00% |
| Test Suite | 0 | 0.00% | 1 | 0.00% |
| Test | 0 | 0.00% | 1 | 0.00% |
| Integration Test | 0 | 0.00% | 1 | 0.00% |
| Yeo2011 | 1 | 0.00% | 0 | 0.00% |

### Source-by-label rows (selected; full table in source artifact `BR-KG_reader_question_live_values_20260503.json.txt`)

> **Note.** The full `node label × source value` matrix has ~120 rows. The full enumeration is preserved verbatim in the raw artifact referenced above; the table below records the highest-volume rows. To regenerate the full matrix, query the production graph:
> `MATCH (n) RETURN labels(n)[0] AS label, n.source AS source, count(*) ORDER BY count(*) DESC`.

| Node label | Source-like value | Count |
|------------|--------------------|------:|
| Coordinate | neurosynth | 447,498 |
| Publication | neurostore | 31,662 |
| Publication | neurosynth | 14,220 |
| Publication | scholarly_metadata_stub | 2,557 |
| Publication | pubmed_api | 1,047 |
| Publication | PubMed | 161 |
| Publication | openneuro_glmfitlins | 49 |
| Publication | scholarly_metadata | 42 |
| Collection | neurostore | 31,885 |
| Collection | neurovault | 16,124 |
| StatisticalMap | neurovault | 21,283 |
| StatsMap | openneuro_glmfitlins | 35,180 |
| StatsMap | multiverse_fitlins_runonly | 60 |
| Task | neurostore | 33,691 |
| Task | cognitive_atlas_niclip | 853 |
| Task | task_families | 314 |
| Task | Psych-101 | 44 |
| Task | openneuro_glmfitlins_taxonomy | 8 |
| Task | taxonomy_surface_rules | 4 |
| Term | neurosynth | 3,228 |
| Embedding | niclip | 23,865 |
| Concept | cognitive_atlas_niclip | 919 |
| Concept | onvoc | 752 |
| Concept | cognitive_atlas_cao | 645 |
| Tool | capabilities.merged.yaml | 2,073 |
| OnvocClass | onvoc | 752 |
| OntologyConcept | onvoc | 752 |
| ToolVersion | `<missing>` | 4,142 |
| OpenNeuro | openneuro_glmfitlins | 7,619 |
| DataResource | openneuro_glmfitlins | 7,581 |
| DataResource | `<missing>` | 1,695 |
| BrainRegion | Allen Brain Atlas | 1,327 |
| BrainRegion | nilearn | 796 |
| Citation | cognitive_atlas | 1,201 |
| Phenotype | neurobagel:OpenNeuro | 938 |
| Phenotype | neurobagel:International Neuroimaging Data-sharing Initiative | 280 |

## Appendix E (system card). Release-ready provenance gap register

### Configured sources missing a literal live source string

| Configured source | Mode | Live graph value found | Live count | Release status | Required follow-up |
|-------------------|------|------------------------|-----------:|----------------|---------------------|
| brainmap | spine | none | 0 nodes / 0 edges | configured but absent from live source scan | mark as not loaded, on-demand/licensed, or map to a different live source value if one exists |
| bids | spine | none | 0 nodes / 0 edges | configured but absent from live source scan | decide whether BIDS is represented only through openneuro_glmfitlins / GLM labels |
| virtual_brain | spine | none | 0 nodes / 0 edges | configured but absent from live source scan | mark as not loaded or on-demand only |
| wikidata | spine | none | 0 nodes / 0 edges | configured but absent from live source scan | confirm whether Wikidata loader is unused, failed, or writes under another source string |
| nidm_results | on_demand | none | 0 nodes / 0 edges | configured on-demand, no live persisted source value | document adapter status and sample artifact path |
| neuroquery | on_demand | none | 0 nodes / 0 edges | configured on-demand, no live persisted source value | document adapter status and whether any cached evidence is released |
| nimare | on_demand | none | 0 nodes / 0 edges | configured on-demand, no live persisted source value | document adapter status and whether generated priors are released |
| neuroscout | on_demand | none | 0 nodes / 0 edges | configured on-demand, no live persisted source value | document adapter status and whether feature summaries are released |
| allen_hba | spine | Allen Brain Atlas; Allen CCFv3 | 1,329 nodes / 2,654 edges | configured value absent, semantically present via aliases | normalize release naming: `allen_hba = Allen Brain Atlas + Allen CCFv3` |

### Configured sources with live values

| Configured source | Mode | Live source value(s) | Live count summary | Release status |
|-------------------|------|-----------------------|---------------------|----------------|
| cognitive_atlas | full | cognitive_atlas, cognitive_atlas_niclip, cognitive_atlas_cao | 6,631 nodes / 14,591 edges | present; aliases need release normalization |
| nilearn_atlases | full | nilearn | 816 nodes / 810 edges | present under source alias |
| neurobagel | full | neurobagel:OpenNeuro, neurobagel:International Neuroimaging Data-sharing Initiative | 2,022 nodes / 1,620 edges | present under source-qualified aliases |
| onvoc | full | onvoc, onvoc_linker | 752 nodes / 35,210 edges | present; node source and linker source should be separated in release notes |
| openneuro_glmfitlins | full | openneuro_glmfitlins (+ `_inferred`, `_manual`, `_taxonomy`) | 45,403 nodes / 272,679 edges | present; split measured, inferred, manual, and taxonomy lanes |
| pubmed | spine | PubMed, pubmed_api | 1,208 nodes / 5 edges | present under two source strings |
| neurosynth | spine | neurosynth, neurosynth_v7 | 464,946 nodes / 805,548 edges | present; source alias should record Neurosynth snapshot/version |
| neurovault | spine | neurovault | 37,467 nodes / 1,076,839 edges | present |
| openneuro | spine | OpenNeuro, neurobagel:OpenNeuro, openneuro_glmfitlins* | 46,975+ nodes / 273,939+ edges | present through several lanes; release table should avoid double counting |
| niclip | spine | niclip, cognitive_atlas_niclip | 25,637 nodes / 0 source-valued edges | present; distinguish embedding product from Cognitive Atlas enrichment |
| neuromaps | spine | neuromaps | 86 nodes / 0 edges | present |
| neurostore | spine | neurostore, neurostore_metadata, neurostore_taxonomy | 97,238 nodes / 61,260 edges | present across metadata and taxonomy lanes |
| scholarly_metadata | on_demand | scholarly_metadata, scholarly_metadata_stub | 2,890 nodes / 3,919 edges | present despite being configured on-demand; release status needs clarification |

### Unattributed source values

| Source-like value | Node count | Edge count | Risk | Required audit |
|--------------------|-----------:|-----------:|------|-----------------|
| `<missing>` | 6,889 | 41,393 | largest provenance gap; release users cannot trace these objects to an upstream source or build lane | group by node label, relationship type, and creation/loading fields; backfill `source` / `edge_source` where possible |

### Internal, generated, manual, and test lanes

| Source-like value | Node count | Edge count | Proposed release class | Release treatment |
|--------------------|-----------:|-----------:|--------------------------|--------------------|
| config_text_backfill | 0 | 104,603 | internal generated enrichment | document generation rule and upstream fields; do not list as external source |
| capabilities.merged.yaml | 2,073 | 0 | internal tool/capability catalog | document as BR capability registry, not neuroimaging upstream data |
| taxonomy_rule | 0 | 612 | internal generated taxonomy rule | document rule source and version |
| taxonomy_surface_rules | 4 | 0 | internal generated taxonomy surface | document rule source and version |
| task_families | 314 | 0 | internal/generated task-family catalog | document source file and curation status |
| task_family_enrichment | 14 | 126 | internal generated enrichment | document enrichment script and confidence semantics |
| disease_path_backfill | 0 | 34 | internal generated backfill | document backfill rule and affected relationship types |
| seed | 0 | 4 | seed/manual bootstrap | document seed artifact or remove from public dump if test-only |
| bulk_loader | 0 | 1 | loader artifact | classify as operational provenance or remove if accidental |
| GraphQL API | 0 | 5 | runtime/API-created records | audit whether these are production user actions, tests, or seed data |
| Manual | 0 | 2 | manual curation | document curator workflow and source evidence |
| openneuro_glmfitlins_manual | 0 | 50 | manual OpenNeuro/GLMFitLins lane | document manual decision criteria |
| psych101_curated_registry | 0 | 2 | curated registry | document registry artifact and curator status |
| Integration Test | 0 | 1 | test artifact | exclude from release or mark internal-test-only |
| Test | 0 | 1 | test artifact | exclude from release or mark internal-test-only |
| Test Suite | 0 | 1 | test artifact | exclude from release or mark internal-test-only |

### Release field coverage gaps

| Release field | Current state | Required release action |
|---------------|----------------|--------------------------|
| Snapshot date | not stored consistently in live source fields | record source-specific snapshot date or API pull date for every external source |
| Upstream URL | not measured from live graph | add canonical upstream URL per source in §2.1 and data card |
| License | not measured from live graph | fill source license and redistribution/commercial-use constraints from upstream license pages |
| Required citation | not measured from live graph | add citation strings or citation keys and propagate into release notes |
| Loader path | partially inferable from repo loader names | map each source to exact loader/module/script path and command |
| Data artifact path | partially present | map each source to raw/staged/build artifact paths or mark on-demand-only |
| Source class | mixed in live graph | classify each source-like value as external upstream, ontology, internal generated, manual, runtime, or test |

### Gabriel and KGGen status

| Lane | Repo artifacts found | Live source count | Current interpretation | Required follow-up |
|------|-----------------------|--------------------:|--------------------------|---------------------|
| Gabriel manifests | 32 `data/BR-KG/raw/gabriel/runs/*/manifest.json` files | 0 source-marked nodes/edges | Gabriel exists as raw/run artifacts, not visible as a marked live KG source | decide whether Gabriel was not ingested, was candidate-only, or was ingested without `source=gabriel` |
| Gabriel review queues | 12 `data/BR-KG/raw/gabriel/runs/*/review_queue*.jsonl` files | 0 source-marked nodes/edges | review/candidate artifacts exist outside live source counts | document accepted vs candidate-only vs rejected lanes before release |
| KGGen summaries | 75 `data/BR-KG/raw/kggen/**/*.summary.json` files | 0 source-marked nodes/edges | KGGen exists as comparison/generation artifacts, not as a marked live KG source | keep KGGen as research/comparison lane unless accepted records are explicitly ingested and marked |
| KGGen JSONL outputs | 81 `data/BR-KG/raw/kggen/**/*.jsonl` files | 0 source-marked nodes/edges | generated candidate files exist | document model/prompt/validation before any public KG claim |

## Appendix F (system card). All-source release audit (summary)

> **Note.** The detailed two-part audit (lane summary + evidence/artifact/loader/license matrix) is preserved in the source `BR-KG_reader_question_live_values_20260503.json.txt` artifact. The condensed disposition table below records each lane's release status; cross-reference the artifact for the full evidence, loader paths, and per-license narratives.

| Audit source or lane | Class | Live counts (approx.) | Release disposition |
|----------------------|-------|------------------------|----------------------|
| Neurosynth | external upstream meta-analysis | 464,946 nodes / 805,548 edges | release after snapshot, license, citation pin |
| NeuroVault | external upstream image/stat-map | 37,467 nodes / 1,076,839 edges | release after license matrix + pull date |
| Neurostore | external study/analysis metadata | 97,238 nodes / 61,260 edges | release after snapshot, license, citation |
| Cognitive Atlas | external ontology/task/concept | 4,859 nodes / 14,596 edges | release after snapshot and citation pin; normalize CogAtlas alias |
| NiCLIP / CogAtlas enrichment | derived embedding/enrichment | 25,637 nodes / 0 edges | release as derived lane after model + upstream citations |
| ONVOC | local ontology + linker | 752 nodes / 35,210 edges | release after ONVOC version, ontology license, linker-rule provenance |
| OpenNeuro GLMFitLins / BIDS-derived | external + derived GLM/stat-map | 45,403 nodes / 272,680 edges | release with per-dataset license matrix and manifest hash |
| BIDS literal source | schema/format standard | 0 / 0 | document as standard dependency |
| Multiverse FitLins run-only | internal derived analysis-run | 60 / 1,020 | release with run manifests + upstream licenses |
| Neurobagel | external federated dataset metadata | 2,022 / 1,620 | release after snapshot dates + license matrix |
| PubMed | external bibliographic metadata | 1,208 / 5 | release after API pull date, NCBI attribution, citation policy |
| PubMed Central / PMC | external full-text repository | 0 / 0 | mark absent unless intentionally ingested and licensed |
| Scholarly metadata (Crossref/OpenAlex) | external bibliographic | 2,890 / 3,919 | release after per-provider attribution + cache snapshot |
| Allen HBA / Allen CCF | external atlas/expression | 1,329 / 2,654 | normalize alias `allen_hba`; audit synthetic/sample marker |
| Nilearn atlases / Yeo2011 | external atlas definitions | 817 / 810 | release after per-atlas license/citation/version |
| Neuromaps | external annotation library | 86 / 0 | release after annotation-level license/citation |
| NeuroQuery | external/on-demand evidence | 0 / 0 | document as on-demand adapter |
| NiMARE | software-derived meta-analysis | 0 / 0 | document as software/derived evidence dependency |
| NeuroScout | external/on-demand feature | 0 / 0 | document as on-demand adapter |
| NIDM results | external/standardized results metadata | 0 / 0 | configured but not persisted |
| BrainMap | external/licensed coordinate database | 0 / 0 | do not release unless licensed and cited |
| Wikidata | external linked-data ontology | 0 / 0 | configured but absent |
| Virtual Brain | external software/simulation | 0 / 0 | document as configured/adapter lane |
| GWAS Catalog / OpenMed / PGC | external genetics metadata | 0 in current scan | reconcile with 2026-04-08 validation counts |
| Psych-101 / psychology task registry | external/curated behavioral task registry | 127 / 390 | release as curated registry after snapshot + license |
| Tool/capability catalog (`capabilities.merged.yaml`) | internal BR capability registry | 2,073 / 0 | include only if public KG intentionally includes BR runtime/tool nodes |
| `config_text_backfill` | internal generated enrichment | 0 / 104,603 | release only with rule definition and edge-type audit |
| Taxonomy rules | internal generated taxonomy | 4 / 612 | release with rule/version manifest or exclude |
| Task family enrichment | internal/generated task-family catalog | 328 / 126 | release with version + curator/source evidence |
| Disease path backfill | internal generated backfill | 0 / 34 | audit before release |
| Seed/bootstrap | internal/manual bootstrap | 0 / 4 | attribute or exclude |
| Bulk loader operational lane | operational loader marker | 0 / 1 | audit as operational provenance |
| GraphQL API runtime lane | runtime/API-created records | 0 / 5 | audit as production mutation/test residue |
| Manual lane | manual curation | 0 / 2 | release only after curator workflow and evidence documentation |
| Test lanes (`Integration Test`, `Test`, `Test Suite`) | test artifacts | 0 / 3 | exclude from public dump |
| Unattributed `<missing>` | unresolved provenance gap | 6,889 / 41,393 | release blocker: backfill, exclude, or document |
| Gabriel paper-mining lane | LLM/heuristic candidate extraction | 0 / 0 (live source marker) | candidate-only unless promoted records are source-marked |
| KGGen comparison/generation lane | LLM/generated comparison/candidate | 0 / 0 (live source marker) | comparison/candidate lane unless promoted |
| Scientific review / governance registry | internal governance/rule registry | 0 / 0 | document separately from BR-KG upstream source list |

## Appendix G (system card). Canonical schema-triple counts (top 30)

> **Note.** The full 151-triple table is preserved in the source artifact `BR-KG_schema_triples_comprehensive.csv`. The condensed top-30 table below covers the schema triples that together account for >97% of edges.

| Rank | Source label set | Relationship | Target label set | Edge count | Share of edges |
|-----:|-------------------|---------------|-------------------|-----------:|---------------:|
| 1 | StatisticalMap | BELONGS_TO | Collection | 1,075,385 | 44.38% |
| 2 | Publication | HAS_COORDINATE | Coordinate | 447,499 | 18.47% |
| 3 | Publication | HAS_TERM | Term | 358,050 | 14.78% |
| 4 | StatsMap | IN_REGION | BrainRegion | 121,261 | 5.00% |
| 5 | Publication | ABOUT | Concept / OntologyConcept / OnvocClass | 67,785 | 2.80% |
| 6 | Task | IN_DOMAIN | Process / ConceptClass | 52,117 | 2.15% |
| 7 | StatsMap | IN_ONVOC | Concept / OntologyConcept / OnvocClass | 43,958 | 1.81% |
| 8 | StatsMap | IN_SPACE | TemplateSpace | 35,180 | 1.45% |
| 9 | StatsMap | COMPUTED_WITH | ModelSpec | 30,880 | 1.27% |
| 10 | StatsMap | GENERATED_FROM | TaskAnalysis | 30,880 | 1.27% |
| 11 | StatsMap | DERIVED_FROM | Contrast / GLMContrast | 30,120 | 1.24% |
| 12 | StatsMap | HAS_RESOURCE | DataResource / OpenNeuro | 14,146 | 0.58% |
| 13 | Publication | HAS_TEXT_EMBEDDING | Embedding | 12,958 | 0.53% |
| 14 | Task | MAPS_TO | Task | 11,062 | 0.46% |
| 15 | Task | IN_ONVOC | Concept / OntologyConcept / OnvocClass | 10,894 | 0.45% |
| 16 | StatisticalMap | IN_ONVOC | Concept / OntologyConcept / OnvocClass | 7,331 | 0.30% |
| 17 | StatsMap | MEASURES | Concept | 4,502 | 0.19% |
| 18 | Tool | HAS_VERSION | ToolVersion | 4,142 | 0.17% |
| 19 | DataResource / OpenNeuro | ABOUT | Concept / OntologyConcept / OnvocClass | 3,689 | 0.15% |
| 20 | Task | MEASURES | Task | 3,560 | 0.15% |
| 21 | Publication | CITES | Publication | 3,395 | 0.14% |
| 22 | Concept | MAPS_TO | Concept | 3,145 | 0.13% |
| 23 | Dataset / DataResource | ABOUT | Concept / OntologyConcept / OnvocClass | 2,807 | 0.12% |
| 24 | Task | MEASURES | Concept | 2,773 | 0.11% |
| 25 | Tool | SUPPORTS_MODALITY | Modality | 2,655 | 0.11% |
| 26 | Tool | IMPLEMENTS_FAMILY | TaskFamily | 2,167 | 0.09% |
| 27 | Tool | IMPLEMENTS_FAMILY | ToolFamily | 2,127 | 0.09% |
| 28 | Subject | PARTICIPATES_IN | TaskAnalysis | 1,982 | 0.08% |
| 29 | StatsMap | SUGGESTS_MEASURES | Concept | 1,902 | 0.08% |
| 30 | Dataset / DataResource | HAS_MODALITY | Modality | 1,839 | 0.08% |

## Appendix H (system card). Node-property coverage (high-volume labels)

> **Note.** The full per-label-per-property coverage matrix (all 75 active labels, 626 property keys) is preserved verbatim in the source artifact `BR-KG_reader_question_live_values_20260503.json.txt`. The summary below records coverage for the highest-volume labels.

### Coordinate (447,499 nodes)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| id | 447,499 | 0 | 100.00% |
| labels | 447,499 | 0 | 100.00% |
| space | 447,499 | 0 | 100.00% |
| x | 447,499 | 0 | 100.00% |
| y | 447,499 | 0 | 100.00% |
| z | 447,499 | 0 | 100.00% |
| round_mm | 447,498 | 1 | 99.9998% |
| source | 447,498 | 1 | 99.9998% |

### Publication (49,744 nodes; top 12 properties)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| source | 49,738 | 6 | 99.99% |
| id | 49,580 | 164 | 99.67% |
| labels | 49,580 | 164 | 99.67% |
| doi | 48,499 | 1,245 | 97.50% |
| title | 47,042 | 2,702 | 94.57% |
| pmid | 32,873 | 16,871 | 66.08% |
| journal | 15,324 | 34,420 | 30.81% |
| year | 14,223 | 35,521 | 28.59% |
| authors | 14,222 | 35,522 | 28.59% |
| neurosynth_id | 14,222 | 35,522 | 28.59% |
| space | 14,222 | 35,522 | 28.59% |
| abstract | 493 | 49,251 | 0.99% |

### Collection (48,009 nodes; required-set summary)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| id | 48,009 | 0 | 100.00% |
| labels | 48,009 | 0 | 100.00% |
| name | 48,009 | 0 | 100.00% |
| source | 48,009 | 0 | 100.00% |
| publication_id | 31,885 | 16,124 | 66.41% |
| study_id | 31,885 | 16,124 | 66.41% |
| modalities | 31,884 | 16,125 | 66.41% |

### StatsMap (35,240 nodes; required-set summary)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| id | 35,240 | 0 | 100.00% |
| source | 35,240 | 0 | 100.00% |
| contrast | 35,180 | 60 | 99.83% |
| dataset_id | 35,180 | 60 | 99.83% |
| node_name | 35,180 | 60 | 99.83% |
| path | 35,180 | 60 | 99.83% |
| primary_onvoc_id | 32,020 | 3,220 | 90.86% |
| primary_onvoc_confidence | 32,020 | 3,220 | 90.86% |

### Task (34,926 nodes; required-set summary)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| id | 34,926 | 0 | 100.00% |
| labels | 34,926 | 0 | 100.00% |
| name | 34,926 | 0 | 100.00% |
| source | 34,914 | 12 | 99.97% |
| aliases | 34,870 | 56 | 99.84% |
| family_id | 470 | 34,456 | 1.35% |
| family_label | 470 | 34,456 | 1.35% |
| primary_onvoc_id | 147 | 34,779 | 0.42% |
| embedding_text_v1 | 44 | 34,882 | 0.13% |
| embedding_centaur_behavior_v1 | 44 | 34,882 | 0.13% |

### Embedding (23,865 nodes)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| dimension | 23,865 | 0 | 100.00% |
| id | 23,865 | 0 | 100.00% |
| kind | 23,865 | 0 | 100.00% |
| model | 23,865 | 0 | 100.00% |
| owner_id | 23,865 | 0 | 100.00% |
| source | 23,865 | 0 | 100.00% |
| storage_path | 23,865 | 0 | 100.00% |
| text_section | 23,865 | 0 | 100.00% |
| vector_norm | 23,865 | 0 | 100.00% |

## Appendix I (system card). Relationship-property coverage (high-volume edges)

> **Note.** The full per-relationship-per-property coverage matrix is preserved in the source artifact. The summary below covers the highest-volume relationship types.

### BELONGS_TO (1,077,573 edges)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| source | 1,077,356 | 217 | 99.98% |

### HAS_COORDINATE (447,499 edges)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| source | 447,499 | 0 | 100.00% |

### HAS_TERM (358,050 edges)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| rank | 358,050 | 0 | 100.00% |
| section | 358,050 | 0 | 100.00% |
| source | 358,050 | 0 | 100.00% |
| weight | 358,050 | 0 | 100.00% |

### IN_REGION (121,261 edges)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| atlas | 121,261 | 0 | 100.00% |
| edge_source | 121,261 | 0 | 100.00% |
| etl_version | 121,261 | 0 | 100.00% |
| measure | 121,261 | 0 | 100.00% |
| n_vox | 121,261 | 0 | 100.00% |
| pct_active | 121,261 | 0 | 100.00% |
| weight | 121,261 | 0 | 100.00% |
| z_thr | 121,261 | 0 | 100.00% |

### ABOUT (75,922 edges)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| confidence | 75,922 | 0 | 100.00% |
| created_at | 75,922 | 0 | 100.00% |
| source | 75,922 | 0 | 100.00% |
| match_terms | 75,888 | 34 | 99.96% |
| confidence_tier | 34 | 75,888 | 0.04% |
| method | 34 | 75,888 | 0.04% |

### IN_ONVOC (63,160 edges)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| confidence | 63,160 | 0 | 100.00% |
| source | 63,160 | 0 | 100.00% |
| evidence_json | 34,445 | 28,715 | 54.54% |
| method | 34,445 | 28,715 | 54.54% |
| created_at | 28,715 | 34,445 | 45.46% |
| match_terms | 28,715 | 34,445 | 45.46% |

### MAPS_TO (17,667 edges; selected high-volume properties)

| Property | Present | Missing | Present % |
|----------|--------:|--------:|----------:|
| confidence | 17,667 | 0 | 100.00% |
| computed_at | 17,652 | 15 | 99.92% |
| evidence_type | 17,652 | 15 | 99.92% |
| confidence_components | 12,020 | 5,647 | 68.04% |
| prov_source | 9,368 | 8,299 | 53.03% |
| source | 9,180 | 8,487 | 51.96% |
| canonical_id | 9,158 | 8,509 | 51.84% |
| match_method | 9,158 | 8,509 | 51.84% |
| match_profile | 7,917 | 9,750 | 44.81% |
| timestamp | 7,606 | 10,061 | 43.05% |

## Appendix J (system card). Structural-quality and query benchmark artifacts

| Run | Slice nodes | Slice edges | Structure consistency score | Report path |
|-----|------------:|------------:|----------------------------:|--------------|
| claim_spine_main_20260323 | 579 | 300 | 0.3766 | `data/BR-KG/benchmarks/structural_quality/claim_spine_main_20260323/graph_diagnostic_report.json` |
| live_smoke_20260323 | 1,154 | 1,083 | 0.4795 | `data/BR-KG/benchmarks/structural_quality/live_smoke_20260323/graph_diagnostic_report.json` |
| live_smoke_20260323_v2 | 873 | 798 | 0.5206 | `data/BR-KG/benchmarks/structural_quality/live_smoke_20260323_v2/graph_diagnostic_report.json` |
| live_smoke_20260323_v3_clean | 895 | 626 | 0.4862 | `data/BR-KG/benchmarks/structural_quality/live_smoke_20260323_v3_clean/graph_diagnostic_report.json` |
| live_smoke_20260323_v4_encoder_text_v1 | 895 | 626 | 0.4572 | `data/BR-KG/benchmarks/structural_quality/live_smoke_20260323_v4_encoder_text_v1/graph_diagnostic_report.json` |
| live_smoke_20260323_v5_auto_text_v1 | 895 | 626 | 0.4420 | `data/BR-KG/benchmarks/structural_quality/live_smoke_20260323_v5_auto_text_v1/graph_diagnostic_report.json` |
| task_structure_cogat_external_20260323 | 294 | 410 | 0.4744 | `data/BR-KG/benchmarks/structural_quality/task_structure_cogat_external_20260323/graph_diagnostic_report.json` |
| task_structure_neurostore_strict_20260323 | 167 | 150 | 0.5532 | `data/BR-KG/benchmarks/structural_quality/task_structure_neurostore_strict_20260323/graph_diagnostic_report.json` |
| task_structure_neurostore_strict_20260323_v2 | 167 | 150 | 0.5532 | `data/BR-KG/benchmarks/structural_quality/task_structure_neurostore_strict_20260323_v2/graph_diagnostic_report.json` |

## Appendix K (system card). Reader-question checklist (canonical headers)

> **Note.** The reader-question checklist defines the column contract every release-card section should fill. The full checklist with current values is preserved in the source artifacts; the header reference below records the canonical column set for each section so contributors can fill or update it.

### 1.1 Node Type Inventory — required columns

`Node type / label · Definition · Typical instances · Source(s) · Primary identifier · Key properties · Required vs optional properties · Missingness · Multi-label behavior · Current count · Evidence path`

### 1.2 Edge Type Inventory — required columns

`Edge type · Semantics · Directionality · Weighting · Evidence · Construction method · Required properties · Optional properties · Count · Dominant schema triples · Caveats · Evidence path`

### 1.3 Property Schema — required columns

`Object type · Property · Required? · Data type · Example · Missing count · Missing percent · Source of truth`

### 1.4 Identifier Scheme — required columns

`Entity class · Primary key · Secondary IDs · Merge key · Collision handling · Evidence path`

### 1.5 Ontology Cross-References — required columns

`Ontology · Covered entity types · Link property or edge · Coverage numerator · Coverage denominator · Coverage percent · Caveats`

### 2.1 Source Inventory — required columns

`Source · Entity/edge types contributed · Snapshot date · Version · URL · License · Required citation · Loader path · Data artifact path · Status`

### 2.2 Provenance Granularity — required columns

`Edge type · Edge-level provenance? · Node-level provenance only? · Source row trace? · Paper/dataset trace? · Confidence trace? · Missingness · Evidence path`

### 2.3 LLM-Generated Content — required columns

`Lane · Model · Prompt version · Output schema · Nodes produced · Edges produced · Accepted count · Candidate-only count · Rejected count · Validation method · Evidence path`

### 3.1–3.7 Ingestion / Extraction / Resolution / Edge / HITL / Rejection / Reproducibility

The 3.x family captures the build pipeline. Each subsection has its own column contract; see source artifacts.

### 4.1–4.5 Evaluation columns

Sampling precision, coverage, recall spot-checks, structural-quality cards, error taxonomy. See source artifacts for full column contracts.

### 5.1–5.6 Backend, query interfaces, indexes, embeddings, MCP tools, latency

Operational and runtime descriptors. See source artifacts.

### 6.1–6.4 Downstream consumers

Runtime consumers, retrieval patterns, BR-output roles, memory interfaces.

### 7.1–7.5 Versioning, cadence, public release, license matrix, build openness

### 8 Comparison to related resources

`Resource · Approx size · Domain focus · Main entity types · Construction method · Provenance granularity · Ontology grounding · Neuroimaging coverage · Downstream use · Difference from BR-KG`

### 9.1–9.3 Ethics columns

PHI risk, citation propagation, license obligations.

## Appendix L (system card). Refresh and release checklist

| Task | What to do | Why it matters |
|------|------------|------------------|
| Refresh live counts | Rerun node, edge, label, relationship-type, schema-triple, source, and property profile queries. | Before manuscript submission and public release. |
| Resolve missing source-like values | Group the 6,889 nodes and 41,393 edges by label/type, loader fields, and creation path; backfill or exclude. | Release blocker. |
| Pin source licenses | Fill source-specific license, citation, and redistribution constraints for each external upstream source. | Release blocker. |
| Normalize source aliases | Map aliases such as `Allen Brain Atlas` / `Allen CCFv3` to release source names such as `allen_hba`. | Needed for data card clarity. |
| Separate internal lanes | Classify generated, manual, runtime, seed, `bulk_loader`, GraphQL, and test source-like values. | Needed to avoid presenting internal artifacts as external sources. |
| Decide Gabriel/KGGen treatment | Document candidate-only vs accepted records and require source markers for promoted records. | Needed before any LLM-derived KG claim. |
| Refresh structural quality | Rerun structural-quality cards on the final release graph, not only March 2026 slices. | Needed for benchmark paper claims. |
| Update connected components | Run component analysis or export edges if GDS is unavailable. | Needed before claiming component structure. |
| Pilot contribution mechanism | Create wiki repo, YAML templates, CI validator, and review queue for finding/correction records. | Needed for community maintenance. |

---

# Part 2 — Per-episode evidence bundle template

Records the evidence substrate used during planning and review for one episode. Every accepted claim in Appendix G must trace back to rows in this card.

## B.1 Card identity

| Field | Value |
|-------|-------|
| Card ID | B-<episode-id>-001 |
| Episode ID | |
| Scientific question | |
| BR-KG snapshot | |
| Registry snapshot | |
| Date | |
| Prepared by | |
| Review status | draft / reviewed / final |

## B.2 Input query

| Field | Value |
|-------|-------|
| Input query | |
| Query purpose | planning / evidence retrieval / method selection / review / claim verification |
| Expected output | |

## B.3 Resolved entities

| Raw term | Resolved entity | Entity type | Alias / synonym | Confidence | Notes |
|----------|-----------------|-------------|-----------------|------------|-------|
| | | dataset / method / brain region / disease / measure / tool / concept | | high / medium / low | |

## B.4 ONVOC normalization examples

| Original mention | Normalized entity | ONVOC ID | Rule / mapping source | Ambiguity | Decision |
|------------------|-------------------|----------|------------------------|-----------|----------|
| | | | exact / alias / curator | yes / no | accepted / flagged |

## B.5 Evidence tier definitions

- **Tier 1 — accepted graph evidence**: curated or previously reviewed BR-KG edges with stable provenance.
- **Tier 2 — batch-extracted evidence**: extracted from batch literature or dataset processing, not yet promoted.
- **Tier 3 — candidate evidence**: potentially relevant, requires manual review or replication.
- **Tier 4 — real-time retrieval evidence**: retrieved live during the episode from tools, connectors, search, or literature APIs.

## B.6 Evidence ledger

| Evidence ID | Type | Tier | Source | Supports which claim? | Status | Caveat |
|-------------|------|------|--------|------------------------|--------|--------|
| E-BKG-001 | graph edge / path | 1 | BR-KG snapshot | | accepted | |
| E-LIT-001 | literature retrieval | 4 | PubMed / Semantic Scholar | | candidate | needs review |

## B.7 Graph paths

| Path ID | Source node | Relation(s) | Target node | Hops | Tier | Provenance | Confidence | Notes |
|---------|-------------|-------------|-------------|------|------|------------|------------|-------|
| GP-001 | | associated_with / used_for / measured_by | | 1 / 2 / 3 | 1 | BR-KG snapshot | high | |

Interpretation block per path (optional):

```
Path GP-001:
[Node A] --relation--> [Node B] --relation--> [Node C]
Interpretation: ...
Limitations: ...
```

## B.8 Literature retrieval outputs

| Retrieval ID | Search query | Source / connector | Top result | DOI / URL | Relevance | Tier | Status |
|--------------|--------------|--------------------|-----------|-----------|-----------|------|--------|
| LIT-001 | | PubMed / Google Scholar / API | | | high / med / low | 4 | candidate |

Retrieval summary:
- Records retrieved:
- Screened:
- Accepted:
- Rejected:
- Main reason for rejection:

## B.9 Dataset and tool links

| Link ID | Type | Name | Identifier / URL | Role in episode | Status | Notes |
|---------|------|------|------------------|------------------|--------|-------|
| D-001 | dataset | | | candidate / used | available / missing / blocked | |
| T-001 | tool | | | retrieval / preprocessing / analysis | available / failed / rejected | |

## B.10 Connector failures

| Connector / tool | Attempted purpose | Failure type | Error summary | Impact | Recovery action |
|------------------|-------------------|--------------|---------------|--------|-----------------|
| | literature / dataset / KG query | timeout / unavailable / no result / permission | | low / med / high | retried / replaced / unresolved |

## B.11 Prior findings and condition vectors

| Finding ID | Prior claim | Condition vector | Provenance | Relation to current episode | Status |
|------------|-------------|------------------|------------|------------------------------|--------|
| PF-001 | | dataset / population / preprocessing / model / metric | memory / prior run / paper | supports / conflicts / extends | accepted / candidate |

Condition vector template:

```
Dataset:
Population:
Task:
Preprocessing:
Feature type:
Model / method:
Metric:
Known caveats:
```

## B.12 Coverage notes

Covered:
- Entities resolved:
- Evidence sources checked:
- Graph paths retrieved:
- Literature/tool outputs reviewed:

Not covered:
- Missing entities:
- Missing datasets:
- Missing tools:
- Unsupported claims:
- Evidence gaps:

| Field | Value |
|-------|-------|
| Risk of overclaiming | low / medium / high |
| Recommended follow-up | |

## B.13 Embedding lanes

| Lane | Model identity | Vector dim | Input text fields | Usage surface | Snapshot | Index state |
|------|----------------|-----------:|-------------------|---------------|----------|-------------|
| brain-text | | | | semantic search | | healthy / stale / rebuilding |
| claim-memory | | | | memory retrieval | | |
| tool-retrieval | | | | tool search | | |
| graph-storage | | | | KG embedding | | |

## B.14 Summary

| Field | Value |
|-------|-------|
| Accepted evidence | E-IDs |
| Candidate evidence | E-IDs |
| Rejected / blocked evidence | E-IDs |
| Main caveats | |
| Evidence sufficiency | sufficient / partial / insufficient |
| Recommended review action | accept / revise / block / additional retrieval |
