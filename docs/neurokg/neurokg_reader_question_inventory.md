# NeuroKG Reader-Question Documentation Inventory

This is the master inventory for writing about NeuroKG across the main paper,
Methods, Supplementary Methods, data card, release notes, and companion
benchmark paper.

Organize every NeuroKG claim by reader question. A downstream manuscript slice
can then quote or compress one section without inventing a parallel account.

Status vocabulary:

- `verified-current`: checked against a current graph dump, code path, or run
  artifact.
- `artifact-needs-refresh`: supported by an existing artifact, but the artifact
  may not be the latest production snapshot.
- `partial`: implemented or documented for only some sources, labels, or
  relationships.
- `spec-only`: described as a desired contract, but not verified as live
  behavior.
- `missing`: not found yet.

Do not promote `artifact-needs-refresh`, `partial`, or `spec-only` entries into
paper claims without a current evidence path.

## Current Anchor Artifacts

Use these as starting points, not as final manuscript truth until refreshed:

| Artifact | What it anchors | Current note |
|---|---|---|
| `docs/neurokg/neurokg_reader_question_live_values_20260503.json.txt` | Raw live values used to fill this inventory | Generated from production Neo4j and source/property profile queries on 2026-05-03. The `.txt` suffix avoids the repo-wide `*.json` ignore rule for new files. |
| `docs/operations/prod_neurokg_plot_probe_20260502/SUMMARY.md` | Production schema/plot probe | Bounded production queries through `brain-researcher-vm` and `brain-researcher-neurokg-0`; useful but not a full data export. |
| `docs/operations/prod_neurokg_plot_probe_20260502/tables/neurokg_schema_inventory_data_dictionary.md` | Schema inventory file layout | Lists generated CSV/HTML inventory tables and recommended comprehensive table. |
| `docs/operations/prod_neurokg_plot_probe_20260502/tables/neurokg_schema_triples_comprehensive.csv` | Canonical source-label / relationship / target-label triples | 151 schema triples in the existing artifact. |
| `docs/operations/prod_neurokg_plot_probe_20260502/tables/neurokg_node_labels_inventory.csv` | Node-label counts and surfaces | 75 node labels in the existing artifact; multi-label endpoints need careful interpretation. |
| `docs/operations/prod_neurokg_plot_probe_20260502/tables/neurokg_relationship_types_inventory.csv` | Relationship-type counts and dominant schema triples | 85 relationship types in the existing artifact. |
| `docs/operations/prod_neurokg_plot_probe_20260502/tables/neurokg_schema_inventory_summary.json` | Schema inventory summary | `total_edges=2,423,334`, `top1_share=44.4%`, `top3_share=77.6%`, `top10_share=93.4%`. |
| `docs/specs/neurokg_structural_quality_benchmark_v1.md` | KG structural-quality framing | Evaluation should be a versioned quality card, not only node/edge counts. |
| `docs/neurokg/gabriel_full_pipeline.md` | Gabriel paper-mining generation/ingest lane | Anchors LLM/heuristic extraction, review queues, candidate lanes, and KGGen evaluation. |
| `docs/standards/NeuroKG_Standards.md` | Standards skeleton | Useful for ID/provenance/merge-policy intent; verify before citing as implemented. |
| `docs/standards/neurokg_graph_schema.md` | Historical sparse snapshot | Explicitly historical; do not use for current live graph claims. |

Verified live headline for this fill pass:

- Live production query on 2026-05-03 reports `694,135` unique nodes and `2,423,334` edges.
- The earlier `726K nodes / 2.4M edges` wording is not current for this checked snapshot; use `694K nodes / 2.423M edges` unless a later refresh supersedes it.
- All counts below are snapshot-specific and should be refreshed before final manuscript or public data release.

## Live Numeric Fill - 2026-05-03

These values were filled from a live production Neo4j query against `brain-researcher-neurokg-0` plus existing repo benchmark artifacts. Counts are snapshot-specific; update this section before manuscript submission or public release.

### Headline Values
| Metric | Value | Evidence / caveat |
|---|---|---|
| Snapshot date | 2026-05-03 | Live query against production Neo4j pod |
| Unique nodes | 694,135 | MATCH (n) RETURN count(n) |
| Edges | 2,423,334 | MATCH ()-[r]->() RETURN count(r) |
| Active node labels | 75 | labels present on at least one node |
| Token-store node labels | 87 | includes 12 zero-node labels: `CognitiveConcept`, `DiseaseTrait`, `Gene`, `ONVOC`, `Operation`, `Population`, `RiskLocus`, `TemporalNode`, `Tenant`, `TenantQuota`, `TenantUser`, `UsageEvent` |
| Active relationship types | 85 | types present on at least one edge |
| Token-store relationship types | 86 | includes 1 zero-edge type: `TEMPORAL_REL` |
| Canonical schema triples | 151 | source-label-set / relationship / target-label-set triples |
| Property keys | 626 | CALL db.propertyKeys() |
| Indexes | 87 | SHOW INDEXES |
| Constraints | 27 | SHOW CONSTRAINTS |
| Neo4j | 5.22.0 community | CALL dbms.components() |
| K3s NeuroKG replicas | 1 ready / 1 desired | pod `brain-researcher-neurokg-0`, restart_count=0 |
| Node `id` coverage | 693,919/694,135 (99.97%) | all node labels |
| Node `source` coverage | 687,246/694,135 (99.01%) | all node labels |
| Edge source-like coverage | 2,381,941/2,423,334 (98.29%) | `source` or `edge_source` |
| Edge confidence coverage | 318,609/2,423,334 (13.15%) | `confidence` property |
| Edge weight coverage | 480,061/2,423,334 (19.81%) | `weight` property |
| Orphan nodes | 52,029/694,135 (7.50%) | undirected degree = 0 |
| Degree min / median / mean / p95 / p99 / max | 0 / 1 / 6.9740 / 25 / 71 / 36,737 | undirected degree |
| Connected components | not measured | GDS procedure unavailable in prod Neo4j; no full edge export pulled in this pass |
| StatsMap nodes / distinct runs | 35,240 / 18 | MATCH (s:StatsMap) |
| Text embeddings | 23,865, dim=4096, model=BrainGPT-7B-v0.2, source=niclip | Embedding nodes |
| Task embeddings | 44 text, 44 behavior, 44 both / 34,926 Task nodes | Task node properties |
| LLM/Gabriel live source count | 0 nodes, 0 edges with `source` containing `gabriel` or `kggen` | source-property scan only; does not prove no LLM-derived content if unmarked |

### Full Active Node-Label Counts
| Node label | Count | Share of unique nodes |
|---|---|---|
| `Coordinate` | 447,499 | 64.47% |
| `Publication` | 49,744 | 7.17% |
| `Collection` | 48,009 | 6.92% |
| `StatsMap` | 35,240 | 5.08% |
| `Task` | 34,926 | 5.03% |
| `Embedding` | 23,865 | 3.44% |
| `StatisticalMap` | 21,283 | 3.07% |
| `DataResource` | 9,282 | 1.34% |
| `OpenNeuro` | 7,619 | 1.10% |
| `ToolVersion` | 4,142 | 0.60% |
| `Term` | 3,228 | 0.47% |
| `Concept` | 2,336 | 0.34% |
| `Contrast` | 2,206 | 0.32% |
| `BrainRegion` | 2,140 | 0.31% |
| `Dataset` | 2,136 | 0.31% |
| `Tool` | 2,084 | 0.30% |
| `Phenotype` | 1,218 | 0.18% |
| `Citation` | 1,201 | 0.17% |
| `Subject` | 1,139 | 0.16% |
| `TaskCondition` | 807 | 0.12% |
| `OntologyConcept` | 752 | 0.11% |
| `OnvocClass` | 752 | 0.11% |
| `GLMContrast` | 621 | 0.09% |
| `TaskIndicator` | 584 | 0.08% |
| `SubjectGroup` | 402 | 0.06% |
| `Condition` | 310 | 0.04% |
| `GLMDesignPrior` | 216 | 0.03% |
| `Author` | 172 | 0.02% |
| `TaskFamily` | 138 | 0.02% |
| `Institution` | 119 | 0.02% |
| `TaskSpec` | 110 | 0.02% |
| `ReviewSchemaField` | 106 | 0.02% |
| `ResourceType` | 102 | 0.01% |
| `ToolFamily` | 96 | 0.01% |
| `Repository` | 88 | 0.01% |
| `BrainAnnotation` | 86 | 0.01% |
| `ReviewImplementationRule` | 80 | 0.01% |
| `ModelSpec` | 78 | 0.01% |
| `Experiment` | 76 | 0.01% |
| `Psych101Experiment` | 76 | 0.01% |
| `TaskAnalysis` | 72 | 0.01% |
| `ReviewRule` | 71 | 0.01% |
| `ReviewCalibrationCase` | 60 | 0.01% |
| `StatMap` | 60 | 0.01% |
| `Consortium` | 38 | 0.01% |
| `Study` | 33 | 0.00% |
| `Modality` | 28 | 0.00% |
| `Parcellation` | 28 | 0.00% |
| `Battery` | 27 | 0.00% |
| `Parcel` | 26 | 0.00% |
| `Finding` | 16 | 0.00% |
| `Species` | 14 | 0.00% |
| `ReviewRuleGroup` | 13 | 0.00% |
| `IngestionRun` | 12 | 0.00% |
| `ConceptClass` | 10 | 0.00% |
| `Process` | 10 | 0.00% |
| `TemplateSpace` | 10 | 0.00% |
| `Region` | 8 | 0.00% |
| `ReviewReasonTag` | 8 | 0.00% |
| `GLMVariant` | 7 | 0.00% |
| `ReviewPolicyDecision` | 6 | 0.00% |
| `ReviewLifecycleStatus` | 5 | 0.00% |
| `ReviewSensitivityTemplate` | 5 | 0.00% |
| `ReviewValidityLayer` | 5 | 0.00% |
| `ExecutionFailure` | 4 | 0.00% |
| `Run` | 4 | 0.00% |
| `Atlas` | 2 | 0.00% |
| `ReviewSeverity` | 2 | 0.00% |
| `GLMRun` | 1 | 0.00% |
| `Psych101Dataset` | 1 | 0.00% |
| `ResultSummary` | 1 | 0.00% |
| `ReviewImplementationRuleCatalog` | 1 | 0.00% |
| `ReviewPositiveModifier` | 1 | 0.00% |
| `ReviewRuleRegistry` | 1 | 0.00% |
| `ToolEvidence` | 1 | 0.00% |

### Full Active Relationship-Type Counts
| Relationship type | Count | Share of edges |
|---|---|---|
| `BELONGS_TO` | 1,077,573 | 44.47% |
| `HAS_COORDINATE` | 447,499 | 18.47% |
| `HAS_TERM` | 358,050 | 14.78% |
| `IN_REGION` | 121,261 | 5.00% |
| `ABOUT` | 75,922 | 3.13% |
| `IN_ONVOC` | 63,160 | 2.61% |
| `IN_DOMAIN` | 52,117 | 2.15% |
| `IN_SPACE` | 35,199 | 1.45% |
| `COMPUTED_WITH` | 30,880 | 1.27% |
| `GENERATED_FROM` | 30,880 | 1.27% |
| `DERIVED_FROM` | 30,163 | 1.24% |
| `MAPS_TO` | 17,667 | 0.73% |
| `HAS_RESOURCE` | 14,728 | 0.61% |
| `HAS_TEXT_EMBEDDING` | 12,958 | 0.53% |
| `MEASURES` | 10,875 | 0.45% |
| `IMPLEMENTS_FAMILY` | 4,294 | 0.18% |
| `HAS_VERSION` | 4,142 | 0.17% |
| `CITES` | 3,397 | 0.14% |
| `SUPPORTS_MODALITY` | 2,655 | 0.11% |
| `SUGGESTS_MEASURES` | 2,514 | 0.10% |
| `HAS_CONTRAST` | 2,464 | 0.10% |
| `HAS_REGION` | 2,123 | 0.09% |
| `PARTICIPATES_IN` | 1,982 | 0.08% |
| `HAS_MODALITY` | 1,839 | 0.08% |
| `HOSTED_AT` | 1,694 | 0.07% |
| `HAS_TASK` | 1,679 | 0.07% |
| `PART_OF` | 1,425 | 0.06% |
| `HASCITATION` | 1,293 | 0.05% |
| `ASSERTS` | 1,237 | 0.05% |
| `HAS_PHENOTYPE` | 1,218 | 0.05% |
| `MEASUREDBY` | 1,218 | 0.05% |
| `INVOLVES_SPECIES` | 990 | 0.04% |
| `CLASSIFIED_UNDER` | 863 | 0.04% |
| `HASCONDITION` | 807 | 0.03% |
| `USES_CONDITION` | 750 | 0.03% |
| `HASINDICATOR` | 584 | 0.02% |
| `CLASSIFIEDUNDER` | 523 | 0.02% |
| `KINDOF` | 429 | 0.02% |
| `INCLUDES` | 402 | 0.02% |
| `PRODUCES_RESOURCE` | 362 | 0.01% |
| `CONSUMES_RESOURCE` | 338 | 0.01% |
| `HAS_CONDITION` | 310 | 0.01% |
| `AFFILIATED_WITH` | 292 | 0.01% |
| `PARTOF` | 263 | 0.01% |
| `AUTHORED_BY` | 232 | 0.01% |
| `HAS_GLM_PRIOR` | 224 | 0.01% |
| `RELATED_TO` | 190 | 0.01% |
| `BELONGS_TO_FAMILY` | 176 | 0.01% |
| `REQUIRES_FIELD` | 163 | 0.01% |
| `USES_TASK` | 152 | 0.01% |
| `INBATTERY` | 134 | 0.01% |
| `HAS_VALIDITY_LAYER` | 102 | 0.00% |
| `HAS_REASON_TAG` | 81 | 0.00% |
| `CONTAINS_IMPLEMENTATION_RULE` | 80 | 0.00% |
| `HAS_EXPERIMENT` | 76 | 0.00% |
| `DESCRIBES_TASK` | 72 | 0.00% |
| `CONTAINS_RULE` | 71 | 0.00% |
| `HAS_LIFECYCLE_STATUS` | 71 | 0.00% |
| `HAS_SEVERITY` | 71 | 0.00% |
| `IN_RULE_GROUP` | 71 | 0.00% |
| `CONTAINS_CALIBRATION_CASE` | 60 | 0.00% |
| `CALIBRATES_RULE` | 55 | 0.00% |
| `CONTRAST_OF` | 53 | 0.00% |
| `CITED_BY` | 49 | 0.00% |
| `MAPPED_TO_IMPLEMENTATION` | 28 | 0.00% |
| `HAS_PARCEL` | 26 | 0.00% |
| `IN_PARCELLATION` | 17 | 0.00% |
| `VALIDATED_ON` | 13 | 0.00% |
| `HAD_FAILURE` | 7 | 0.00% |
| `HAS_VARIANT` | 7 | 0.00% |
| `ACTIVATES` | 6 | 0.00% |
| `HAS_POLICY_DECISION` | 6 | 0.00% |
| `TRIGGERS_SENSITIVITY` | 5 | 0.00% |
| `FAILED_ON` | 3 | 0.00% |
| `DOCUMENTED_IN` | 2 | 0.00% |
| `HAS_GLM_RUN` | 2 | 0.00% |
| `HAS_PARCELLATION` | 2 | 0.00% |
| `CALIBRATES_MODIFIER` | 1 | 0.00% |
| `CONTAINS_MODIFIER` | 1 | 0.00% |
| `HAS_EVIDENCE` | 1 | 0.00% |
| `HAS_SUMMARY` | 1 | 0.00% |
| `LOCATED_IN` | 1 | 0.00% |
| `MEASURED_BY` | 1 | 0.00% |
| `MENTIONS_CONCEPT` | 1 | 0.00% |
| `SIMILAR_TO` | 1 | 0.00% |

### Requested Edge Alias Presence
| Requested/manuscript alias | Live active count | Status |
|---|---|---|
| `mentions` / `MENTIONS` | 0 | not present as active relationship type |
| `mentions_concept` / `MENTIONS_CONCEPT` | 1 | present |
| `reports_activation_at` / `REPORTS_ACTIVATION_AT` | 0 | not present as active relationship type |
| `associated_with` / `ASSOCIATED_WITH` | 0 | not present as active relationship type |
| `part_of` / `PART_OF` | 1,425 | present |
| `projects_to` / `PROJECTS_TO` | 0 | not present as active relationship type |
| `shares_term` / `SHARES_TERM` | 0 | not present as active relationship type |
| `is_a` / `IS_A` | 0 | not present as active relationship type |
| `supersedes` / `SUPERSEDES` | 0 | not present as active relationship type |
| `co_occurs_with` / `CO_OCCURS_WITH` | 0 | not present as active relationship type |

### Source-Like Node And Edge Counts
| Source-like property value | Node count | Node share | Edge count | Edge share |
|---|---|---|---|---|
| `neurovault` | 37,467 | 5.40% | 1,076,839 | 44.44% |
| `neurosynth` | 464,946 | 66.98% | 358,050 | 14.78% |
| `neurosynth_v7` | 0 | 0.00% | 447,498 | 18.47% |
| `openneuro_glmfitlins` | 45,395 | 6.54% | 266,193 | 10.98% |
| `config_text_backfill` | 0 | 0.00% | 104,603 | 4.32% |
| `neurostore` | 97,238 | 14.01% | 0 | 0.00% |
| `neurostore_metadata` | 0 | 0.00% | 52,117 | 2.15% |
| `<missing>` | 6,889 | 0.99% | 41,393 | 1.71% |
| `onvoc_linker` | 0 | 0.00% | 34,445 | 1.42% |
| `niclip` | 23,865 | 3.44% | 0 | 0.00% |
| `cognitive_atlas` | 4,214 | 0.61% | 14,591 | 0.60% |
| `neurostore_taxonomy` | 0 | 0.00% | 9,143 | 0.38% |
| `openneuro_glmfitlins_inferred` | 0 | 0.00% | 6,436 | 0.27% |
| `scholarly_metadata` | 333 | 0.05% | 3,919 | 0.16% |
| `neurobagel:OpenNeuro` | 1,580 | 0.23% | 1,259 | 0.05% |
| `Allen Brain Atlas` | 1,329 | 0.19% | 1,328 | 0.05% |
| `scholarly_metadata_stub` | 2,557 | 0.37% | 0 | 0.00% |
| `capabilities.merged.yaml` | 2,073 | 0.30% | 0 | 0.00% |
| `cognitive_atlas_niclip` | 1,772 | 0.26% | 0 | 0.00% |
| `nilearn` | 816 | 0.12% | 810 | 0.03% |
| `onvoc` | 752 | 0.11% | 765 | 0.03% |
| `Allen CCFv3` | 0 | 0.00% | 1,326 | 0.05% |
| `multiverse_fitlins_runonly` | 60 | 0.01% | 1,020 | 0.04% |
| `pubmed_api` | 1,047 | 0.15% | 0 | 0.00% |
| `neurobagel:International Neuroimaging Data-sharing Initiative` | 442 | 0.06% | 361 | 0.01% |
| `cognitive_atlas_cao` | 645 | 0.09% | 0 | 0.00% |
| `taxonomy_rule` | 0 | 0.00% | 612 | 0.03% |
| `Psych-101` | 127 | 0.02% | 375 | 0.02% |
| `task_families` | 314 | 0.05% | 0 | 0.00% |
| `PubMed` | 161 | 0.02% | 5 | 0.00% |
| `task_family_enrichment` | 14 | 0.00% | 126 | 0.01% |
| `neuromaps` | 86 | 0.01% | 0 | 0.00% |
| `openneuro_glmfitlins_manual` | 0 | 0.00% | 50 | 0.00% |
| `disease_path_backfill` | 0 | 0.00% | 34 | 0.00% |
| `psych-101_taxonomy` | 0 | 0.00% | 13 | 0.00% |
| `openneuro_glmfitlins_taxonomy` | 8 | 0.00% | 0 | 0.00% |
| `CogAtlas` | 0 | 0.00% | 5 | 0.00% |
| `GraphQL API` | 0 | 0.00% | 5 | 0.00% |
| `seed` | 0 | 0.00% | 4 | 0.00% |
| `taxonomy_surface_rules` | 4 | 0.00% | 0 | 0.00% |
| `Manual` | 0 | 0.00% | 2 | 0.00% |
| `psych101_curated_registry` | 0 | 0.00% | 2 | 0.00% |
| `Integration Test` | 0 | 0.00% | 1 | 0.00% |
| `OpenNeuro` | 0 | 0.00% | 1 | 0.00% |
| `Test` | 0 | 0.00% | 1 | 0.00% |
| `Test Suite` | 0 | 0.00% | 1 | 0.00% |
| `Yeo2011` | 1 | 0.00% | 0 | 0.00% |
| `bulk_loader` | 0 | 0.00% | 1 | 0.00% |

### Upstream Source Inventory Counts
| Source/lane string | Nodes with this source | Edges with this source-like value |
|---|---|---|
| `neurosynth` | 464,946 | 358,050 |
| `neurosynth_v7` | 0 | 447,498 |
| `neurostore` | 97,238 | 0 |
| `neurovault` | 37,467 | 1,076,839 |
| `openneuro_glmfitlins` | 45,395 | 266,193 |
| `cognitive_atlas` | 4,214 | 14,591 |
| `cognitive_atlas_niclip` | 1,772 | 0 |
| `cognitive_atlas_cao` | 645 | 0 |
| `onvoc` | 752 | 765 |
| `niclip` | 23,865 | 0 |
| `neurobagel:OpenNeuro` | 1,580 | 1,259 |
| `pubmed_api` | 1,047 | 0 |
| `PubMed` | 161 | 5 |
| `scholarly_metadata` | 333 | 3,919 |
| `scholarly_metadata_stub` | 2,557 | 0 |
| `Allen Brain Atlas` | 1,329 | 1,328 |
| `nilearn` | 816 | 810 |
| `neuromaps` | 86 | 0 |
| `Psych-101` | 127 | 375 |

### Release-Ready Provenance Gap Register

This register separates live graph source values from release-ready source
provenance. The live graph already contains every source-like value listed
above, but a public data card still needs source class, snapshot, URL, license,
citation, loader path, and artifact path for each release source.

#### Configured Sources Missing A Live Source String

These sources are declared in `configs/neurokg/ingestion_modes.yaml`, but the
2026-05-03 live source scan did not find the literal configured source value in
node `source`, edge `source`, or edge `edge_source`.

| Configured source | Mode | Live graph value found | Live count | Release status | Required follow-up |
|---|---|---|---:|---|---|
| `brainmap` | spine | none | 0 nodes / 0 edges | configured but absent from live source scan | mark as not loaded, on-demand/licensed, or map to a different live source value if one exists |
| `bids` | spine | none | 0 nodes / 0 edges | configured but absent from live source scan | decide whether BIDS is represented only through `openneuro_glmfitlins` / GLM labels |
| `virtual_brain` | spine | none | 0 nodes / 0 edges | configured but absent from live source scan | mark as not loaded or on-demand only |
| `wikidata` | spine | none | 0 nodes / 0 edges | configured but absent from live source scan | confirm whether Wikidata loader is unused, failed, or writes under another source string |
| `nidm_results` | on_demand | none | 0 nodes / 0 edges | configured on-demand, no live persisted source value | document adapter status and sample artifact path |
| `neuroquery` | on_demand | none | 0 nodes / 0 edges | configured on-demand, no live persisted source value | document adapter status and whether any cached evidence is released |
| `nimare` | on_demand | none | 0 nodes / 0 edges | configured on-demand, no live persisted source value | document adapter status and whether generated priors are released |
| `neuroscout` | on_demand | none | 0 nodes / 0 edges | configured on-demand, no live persisted source value | document adapter status and whether feature summaries are released |
| `allen_hba` | spine | `Allen Brain Atlas`; `Allen CCFv3` | 1,329 nodes / 2,654 edges across mapped values | configured value is absent, semantically represented by source aliases | normalize release naming: `allen_hba` = `Allen Brain Atlas` + `Allen CCFv3` |

Configured sources with live values:

| Configured source | Mode | Live source value(s) | Live count summary | Release status |
|---|---|---|---:|---|
| `cognitive_atlas` | full | `cognitive_atlas`, `cognitive_atlas_niclip`, `cognitive_atlas_cao` | 6,631 nodes / 14,591 edges | present; aliases need release normalization |
| `nilearn_atlases` | full | `nilearn` | 816 nodes / 810 edges | present under source alias |
| `neurobagel` | full | `neurobagel:OpenNeuro`, `neurobagel:International Neuroimaging Data-sharing Initiative` | 2,022 nodes / 1,620 edges | present under source-qualified aliases |
| `onvoc` | full | `onvoc`, `onvoc_linker` | 752 nodes / 35,210 edges | present; node source and linker source should be separated in release notes |
| `openneuro_glmfitlins` | full | `openneuro_glmfitlins`, `openneuro_glmfitlins_inferred`, `openneuro_glmfitlins_manual`, `openneuro_glmfitlins_taxonomy` | 45,403 nodes / 272,679 edges | present; split measured, inferred, manual, and taxonomy lanes |
| `pubmed` | spine | `PubMed`, `pubmed_api` | 1,208 nodes / 5 edges | present under two source strings |
| `neurosynth` | spine | `neurosynth`, `neurosynth_v7` | 464,946 nodes / 805,548 edges | present; source alias should record Neurosynth snapshot/version |
| `neurovault` | spine | `neurovault` | 37,467 nodes / 1,076,839 edges | present |
| `openneuro` | spine | `OpenNeuro`, `neurobagel:OpenNeuro`, `openneuro_glmfitlins*` | 46,975+ nodes / 273,939+ edges across related values | present through several lanes; release table should avoid double counting multi-source surfaces |
| `niclip` | spine | `niclip`, `cognitive_atlas_niclip` | 25,637 nodes / 0 source-valued edges | present; distinguish embedding product from Cognitive Atlas enrichment |
| `neuromaps` | spine | `neuromaps` | 86 nodes / 0 edges | present |
| `neurostore` | spine | `neurostore`, `neurostore_metadata`, `neurostore_taxonomy` | 97,238 nodes / 61,260 edges | present across metadata and taxonomy lanes |
| `scholarly_metadata` | on_demand | `scholarly_metadata`, `scholarly_metadata_stub` | 2,890 nodes / 3,919 edges | present despite being configured on-demand; release status needs clarification |

#### Unattributed Source Values

The live graph contains unattributed source-like records. This should be treated
as a release blocker until the objects are attributed, intentionally excluded,
or explicitly documented as internal/generated.

| Source-like value | Node count | Edge count | Risk | Required audit |
|---|---:|---:|---|---|
| `<missing>` | 6,889 | 41,393 | largest provenance gap; release users cannot trace these objects to an upstream source or build lane | group by node label, relationship type, and creation/loading fields; backfill `source` / `edge_source` where possible |

#### Internal, Generated, Manual, And Test Lanes

These live source-like values should not be presented as external upstream data
sources. They should be classified as internal build lanes, generated
derivations, manual curation, or test artifacts before release.

| Source-like value | Node count | Edge count | Proposed release class | Release treatment |
|---|---:|---:|---|---|
| `config_text_backfill` | 0 | 104,603 | internal generated enrichment | document generation rule and upstream fields; do not list as external source |
| `capabilities.merged.yaml` | 2,073 | 0 | internal tool/capability catalog | document as BR capability registry, not neuroimaging upstream data |
| `taxonomy_rule` | 0 | 612 | internal generated taxonomy rule | document rule source and version |
| `taxonomy_surface_rules` | 4 | 0 | internal generated taxonomy surface | document rule source and version |
| `task_families` | 314 | 0 | internal/generated task-family catalog | document source file and curation status |
| `task_family_enrichment` | 14 | 126 | internal generated enrichment | document enrichment script and confidence semantics |
| `disease_path_backfill` | 0 | 34 | internal generated backfill | document backfill rule and affected relationship types |
| `seed` | 0 | 4 | seed/manual bootstrap | document seed artifact or remove from public dump if test-only |
| `bulk_loader` | 0 | 1 | loader artifact | classify as operational provenance or remove if accidental |
| `GraphQL API` | 0 | 5 | runtime/API-created records | audit whether these are production user actions, tests, or seed data |
| `Manual` | 0 | 2 | manual curation | document curator workflow and source evidence |
| `openneuro_glmfitlins_manual` | 0 | 50 | manual OpenNeuro/GLMFitLins lane | document manual decision criteria |
| `psych101_curated_registry` | 0 | 2 | curated registry | document registry artifact and curator status |
| `Integration Test` | 0 | 1 | test artifact | exclude from release or mark internal-test-only |
| `Test` | 0 | 1 | test artifact | exclude from release or mark internal-test-only |
| `Test Suite` | 0 | 1 | test artifact | exclude from release or mark internal-test-only |

#### Release Field Coverage Gaps

The live count pass verifies source-like counts, but it does not establish a
release-ready license/citation/provenance contract.

| Release field | Current state in this document | Required release action |
|---|---|---|
| Snapshot date | not stored consistently in live source fields | record source-specific snapshot date or API pull date for every external source |
| Upstream URL | not measured from live graph | add canonical upstream URL per source in Section 2.1 and data card |
| License | not measured from live graph | fill source license and redistribution/commercial-use constraints from upstream license pages |
| Required citation | not measured from live graph | add citation strings or citation keys and propagate them into release notes |
| Loader path | partially inferable from repo loader names, not release-ready | map each source to exact loader/module/script path and command |
| Data artifact path | partially present for Gabriel/KGGen and benchmark artifacts, not complete | map each source to raw/staged/build artifact paths or mark on-demand-only |
| Source class | mixed in live graph | classify each source-like value as external upstream, ontology, internal generated, manual, runtime, or test |

#### All-Source Release Audit Table

Counts in this table are from the 2026-05-03 live source-like scan unless a row
explicitly says otherwise. A row may group multiple live source strings when
they are aliases or build lanes for the same release source. The purpose is to
make release disposition explicit: external upstream, ontology/catalog,
internal/generated, manual/runtime/test, candidate-only, or unresolved.

| Audit source or lane | Live source value(s) covered | Class | Config mode / source state | Nodes | Edges | Snapshot / version evidence | URL / artifact evidence | Loader / builder evidence | License / citation status | Release disposition |
|---|---|---|---|---:|---:|---|---|---|---|---|
| Neurosynth | `neurosynth`; `neurosynth_v7` | external upstream meta-analysis corpus | configured `spine`; live | 464,946 | 805,548 | live graph snapshot counted on 2026-05-03; local files encode `version-7`; source-specific pull date not stored in live graph | upstream homepage `https://neurosynth.org`; local artifacts include `data/neurosynth_nimare/neurosynth/data-neurosynth_version-7_*` and `data/neurosynth_maps` | `src/brain_researcher/core/ingestion/loaders/neurosynth_unified.py`; `src/brain_researcher/services/neurokg/etl/loaders/neurosynth_loader.py`; `scripts/tools/ingest/download_neurosynth_dataset.py`; `scripts/tools/ingest/neurosynth_spine.py` | license and required citation not release-verified in repo; citation must include Neurosynth/NiMARE source used for v7 assets | releasable only after source-specific snapshot, license, and citation are pinned |
| NeuroVault | `neurovault` | external upstream image/stat-map repository | configured `spine`; live | 37,467 | 1,076,839 | live graph snapshot counted on 2026-05-03; source-specific API pull date not stored in live graph | upstream homepage `https://neurovault.org`; local scripts reference collection downloads; no complete raw artifact path measured in current pass | `src/brain_researcher/core/ingestion/loaders/neurovault_unified.py`; `src/brain_researcher/services/neurokg/etl/loaders/neurovault_loader.py`; `scripts/tools/etl/neurovault_fetch_inventory.py`; `scripts/tools/etl/neurovault_ingest_filtered.py` | license and required citation not release-verified in repo; per-image licenses may vary | releasable only after collection/image license matrix and pull date are pinned |
| Neurostore | `neurostore`; `neurostore_metadata`; `neurostore_taxonomy` | external upstream study/analysis metadata plus taxonomy lane | configured `spine`; live | 97,238 | 61,260 | live graph snapshot counted on 2026-05-03; source-specific snapshot not stored in live graph | upstream homepage `https://neurostore.org`; no complete raw artifact path measured in current pass | `src/brain_researcher/core/ingestion/loaders/neurostore_unified.py`; `src/brain_researcher/services/neurokg/evidence/connectors/neurostore.py`; `scripts/ingest_neurostore_tasks.py` | license and citation not release-verified in repo | releasable after Neurostore snapshot/version, license, and citation are pinned |
| Cognitive Atlas | `cognitive_atlas`; `cognitive_atlas_cao`; `CogAtlas` | external ontology/task/concept catalog | configured `full`; live | 4,859 | 14,596 | live graph snapshot counted on 2026-05-03; source-specific pull date not stored in live graph | upstream homepage `https://www.cognitiveatlas.org`; local artifacts include `data/cognitive_atlas` when present | `src/brain_researcher/core/ingestion/loaders/cognitive_atlas_unified.py`; `src/brain_researcher/services/neurokg/etl/loaders/cognitive_atlas_loader.py`; `src/brain_researcher/services/neurokg/etl/loaders/cogatlas_loader.py`; `scripts/tools/etl/ingest_cogatlas.py`; `scripts/tools/once/parse_cogat_owl.py` | license and citation not release-verified in repo | releasable after snapshot and citation pin; normalize `CogAtlas` alias |
| NiCLIP / Cognitive Atlas enrichment | `niclip`; `cognitive_atlas_niclip` | derived embedding/enrichment lane | configured `spine` for `niclip`; live | 25,637 | 0 | live graph snapshot counted on 2026-05-03; embedding asset version not stored in live graph | local docs `docs/NICLIP_CONFIGURATION.md`; `docs/services/neurokg/niclip_integration_features.md`; local vector caches under `data/neurokg/vector_cache/niclip` and `data/atlases/niclip` | `src/brain_researcher/services/neurokg/etl/loaders/niclip_loader.py`; `src/brain_researcher/services/neurokg/etl/integrate_niclip_mappings.py`; `scripts/neurokg/materialize_niclip_similarity.py` | release license/citation depends on NiCLIP model/assets and underlying Cognitive Atlas/Neurosynth sources; not release-verified in repo | publish as derived lane only after model, asset, and upstream-source citations are pinned |
| ONVOC | `onvoc`; `onvoc_linker` | local/open ontology and linker lane | configured `full`; live | 752 | 35,210 | live graph snapshot counted on 2026-05-03; ontology build/version not stored in live graph | repo artifacts include `docs/vocab/ONVOC.md`, `configs/onvoc_tree.yaml`, `docs/proposals/onvoc_*` | `src/brain_researcher/core/ingestion/loaders/onvoc_unified.py`; `scripts/tools/once/parse_onvoc_owl.py`; `scripts/tools/ontologies/build_onvoc_tree.py`; `scripts/tools/etl/backfill_onvoc_links.py`; `scripts/link_tasks_onvoc.py`; `scripts/link_terms_onvoc.py` | local ontology/license and citation propagation not release-verified | releasable after ONVOC version, ontology license, and linker-rule provenance are pinned |
| OpenNeuro GLMFitLins / BIDS-derived maps | `openneuro_glmfitlins`; `openneuro_glmfitlins_inferred`; `openneuro_glmfitlins_manual`; `openneuro_glmfitlins_taxonomy`; `OpenNeuro` | external datasets plus derived GLM/stat-map lane | configured `full` for `openneuro_glmfitlins`, `spine` for `openneuro`; live | 45,403 | 272,680 | live graph snapshot counted on 2026-05-03; `data/openneuro_glmfitlins/README.md` says statsmodel specs copied on 2025-10-27; map mount paths external to repo | upstream homepage `https://openneuro.org`; local artifacts include `data/openneuro_glmfitlins/statsmodel_specs`, `data/openneuro_glmfitlins/summaries/yeo17_summary.csv`, and manifest paths described in `docs/runbooks/openneuro_glmfitlins_ingest.md` | `src/brain_researcher/core/ingestion/loaders/openneuro_glm_loader.py`; `src/brain_researcher/services/neurokg/etl/glmfitlins_ingest/load_to_neurokg.py`; `scripts/ingest/run_openneuro_glmfitlins_ingest_neo4j.sh`; `scripts/tools/once/build_openneuro_glm_manifest.py`; `scripts/neurokg/load_openneuro_fitlins.py` | OpenNeuro dataset licenses are dataset-specific; GLMFitLins derivative license/citation not release-verified in repo | releasable only with per-dataset license matrix, statsmodel copy date, manifest hash, and derivative citation policy |
| BIDS literal source | none for literal `bids` | schema/metadata standard, represented indirectly | configured `spine`; absent as live source value | 0 | 0 | configured source absent in 2026-05-03 live scan | upstream homepage `https://bids.neuroimaging.io`; BIDS-derived metadata appears through OpenNeuro/GLMFitLins lanes | `src/brain_researcher/core/ingestion/loaders/bids_unified.py`; `src/brain_researcher/services/neurokg/extractors/bids_events.py`; `src/brain_researcher/services/tools/bids_tools.py` | BIDS standard citation/license and dataset-specific licenses not release-verified in repo | document as standard/format dependency, not a separate persisted upstream source unless source markers are added |
| Multiverse FitLins run-only | `multiverse_fitlins_runonly` | internal derived analysis-run lane | live, not configured as upstream source | 60 | 1,020 | live graph snapshot counted on 2026-05-03; run-specific snapshot not stored in source field | repo docs `docs/multiverse_glmfitlins.md`; artifact paths not fully measured in current pass | `src/brain_researcher/services/neurokg/etl/glm_runs/ingest_glm_run.py`; `scripts/ingest_openneuro_glmfitlins_yeo17.py` | inherits OpenNeuro/GLMFitLins and local analysis provenance; not independently release-verified | classify as derived internal lane; include only with run manifests and upstream licenses |
| Neurobagel | `neurobagel:OpenNeuro`; `neurobagel:International Neuroimaging Data-sharing Initiative` | external federated dataset metadata | configured `full`; live | 2,022 | 1,620 | live graph snapshot counted on 2026-05-03; `data/neurokg/raw/neurobagel_public/summary.json` records node API URLs and dataset counts | upstream homepage `https://neurobagel.org`; local artifacts include `data/neurokg/raw/neurobagel_public/*/datasets.json` and metadata files | `src/brain_researcher/services/neurokg/etl/loaders/neurobagel_loader.py`; `src/brain_researcher/services/neurokg/etl/loaders/neurobagel_public_loader.py`; `scripts/ingest_neurobagel_datasets.py` | Neurobagel and source-node licenses/citations not release-verified in repo | releasable after node-level snapshot dates and source-node attribution/license matrix are pinned |
| PubMed | `PubMed`; `pubmed_api` | external bibliographic metadata | configured `spine` as `pubmed`; live | 1,208 | 5 | live graph snapshot counted on 2026-05-03; source-specific API pull date not stored in live graph | upstream homepage `https://pubmed.ncbi.nlm.nih.gov`; local marker `data/knowledge/db/pubmed_last_run.txt` exists | `src/brain_researcher/core/ingestion/loaders/pubmed_unified.py`; `src/brain_researcher/services/neurokg/etl/loaders/pubmed_loader.py`; `src/brain_researcher/services/neurokg/evidence/connectors/pubmed.py` | NCBI/PubMed citation and API policy not release-verified in repo | releasable after API pull date, NCBI attribution, and citation policy are pinned |
| PubMed Central / PMC | none | external full-text repository, currently inventory-only | listed as source target; not found in live source scan | 0 | 0 | no persisted live source value in 2026-05-03 scan | upstream homepage `https://pmc.ncbi.nlm.nih.gov`; no repo artifact measured in current pass | no dedicated PMC loader identified in current pass | license varies by article; not release-verified | mark absent unless PMC full-text artifacts are intentionally ingested and licensed |
| Scholarly metadata / Crossref / OpenAlex | `scholarly_metadata`; `scholarly_metadata_stub` | external bibliographic metadata and stub lane | configured `on_demand`; live persisted values exist | 2,890 | 3,919 | live graph snapshot counted on 2026-05-03; source-specific API pull dates not stored in live graph | local artifacts include many `data/neurokg/raw/scholarly_metadata/openalex_*.json` and `crossref_*.json` files | `src/brain_researcher/services/neurokg/etl/loaders/scholarly_metadata_loader.py` | Crossref/OpenAlex terms, citation, and redistribution policy not release-verified in repo | keep as bibliographic metadata lane; release after per-provider attribution and cache snapshot policy are pinned |
| Allen Human Brain Atlas / Allen CCF | `Allen Brain Atlas`; `Allen CCFv3` | external atlas/expression resource plus atlas alias | configured `spine` as `allen_hba`; live under aliases | 1,329 | 2,654 | live graph snapshot counted on 2026-05-03; local `data/neurokg/raw/allen_hba/manifest.json` contains synthetic sample marker rather than confirmed full HBA snapshot | upstream homepage `https://human.brain-map.org`; local artifacts include `data/neurokg/raw/allen_hba`, `data/allen_hba`, and `data/neurokg/raw/evidence/allen_hba_sample.json` | `src/brain_researcher/core/ingestion/loaders/allen_hba_loader.py`; `src/brain_researcher/core/ingestion/loaders/allen_brain_unified.py`; `src/brain_researcher/services/neurokg/etl/adapters/allen_hba_adapter.py` | Allen license/citation not release-verified; synthetic/sample marker must be clarified before claims | normalize alias to `allen_hba`; audit whether records are real upstream, CCF atlas, or synthetic/sample before release |
| Nilearn atlases / Yeo2011 | `nilearn`; `Yeo2011` | external atlas definitions bundled/fetched through Nilearn | configured `full` as `nilearn_atlases`; live under aliases | 817 | 810 | live graph snapshot counted on 2026-05-03; local README says folder is Nilearn download cache; per-atlas versions not stored in live source field | upstream docs `https://nilearn.github.io`; local artifacts include `data/neurokg/raw/nilearn_atlases`, `data/atlases/nilearn`, and `data/neurokg/raw/Yeo_JNeurophysiol11_FreeSurfer.zip` | `src/brain_researcher/core/ingestion/loaders/nilearn_atlas_unified.py`; `scripts/neurokg/load_neuromaps_parcellations.py` for related parcellation loading | Nilearn software license and per-atlas licenses/citations not release-verified in repo | releasable after per-atlas license/citation/version matrix is pinned |
| Neuromaps | `neuromaps` | external annotation/atlas map library | configured `spine`; live | 86 | 0 | live graph snapshot counted on 2026-05-03; source-specific fetch date not stored in live graph | upstream docs `https://netneurolab.github.io/neuromaps`; local artifacts include `data/neurokg/raw/neuromaps` and `data/atlases/neuromaps` | `src/brain_researcher/core/ingestion/loaders/neuromaps_unified.py`; `scripts/neurokg/fetch_all_neuromaps.py`; `scripts/neurokg/load_neuromaps_parcellations.py` | neuromaps and annotation-specific licenses/citations not release-verified in repo | releasable after annotation-level license/citation table is pinned |
| NeuroQuery | none for literal `neuroquery` | external/on-demand evidence source | configured `on_demand`; absent as persisted live source | 0 | 0 | no persisted live source value in 2026-05-03 scan | upstream homepage `https://neuroquery.org`; sample path configured as `data/neurokg/raw/evidence/neuroquery_sample.json` | `src/brain_researcher/services/neurokg/etl/adapters/neuroquery_adapter.py`; adapter configured in `configs/neurokg/ingestion_modes.yaml` | license/citation not release-verified in repo | document as on-demand adapter unless cached outputs are released |
| NiMARE | none for literal `nimare` | software-derived meta-analysis evidence lane | configured `on_demand`; absent as persisted live source | 0 | 0 | no persisted live source value in 2026-05-03 scan; local Neurosynth assets use NiMARE fetch wrappers | upstream docs `https://nimare.readthedocs.io`; sample path configured as `data/neurokg/raw/evidence/nimare_sample.json`; local artifacts include `data/neurosynth_nimare` | `src/brain_researcher/services/neurokg/etl/adapters/nimare_adapter.py`; `scripts/data_processing/train_nimare_lda.py`; `scripts/neurokg/install_nimare_templates.py` | NiMARE software citation/license and upstream dataset licenses not release-verified | document as software/derived evidence dependency; release only generated priors with inputs and method version |
| NeuroScout | none for literal `neuroscout` | external/on-demand feature source | configured `on_demand`; absent as persisted live source | 0 | 0 | no persisted live source value in 2026-05-03 scan | upstream homepage `https://neuroscout.org`; sample path configured as `data/neurokg/raw/evidence/neuroscout_features.json` | `src/brain_researcher/services/neurokg/etl/adapters/neuroscout_adapter.py`; adapter configured in `configs/neurokg/ingestion_modes.yaml` | license/citation not release-verified in repo | document as on-demand adapter unless feature summaries are released |
| NIDM results | none for literal `nidm_results` | external/standardized results metadata | configured `on_demand`; absent as persisted live source | 0 | 0 | no persisted live source value in 2026-05-03 scan | upstream project URL not release-verified; local artifacts include `data/neurokg/raw/nidm` | `src/brain_researcher/services/neurokg/etl/loaders/nidm_results_loader.py` | license/citation not release-verified in repo | mark adapter/source configured but not persisted; release only with NIDM artifact manifest |
| BrainMap | none for literal `brainmap` | external/licensed coordinate database/tooling lane | configured `spine`; absent as persisted live source | 0 | 0 | no persisted live source value in 2026-05-03 scan | upstream homepage `https://brainmap.org`; local directories/scripts include `data/brainmap` and `scripts/brainmap/*` | `src/brain_researcher/core/ingestion/loaders/brainmap_unified.py`; `src/brain_researcher/core/ingestion/parsers/brainmap_parser.py`; `src/brain_researcher/services/tools/meta_brainmap_tool.py` | BrainMap license/redistribution terms not release-verified and likely require explicit review | do not release as KG source unless licensed data and citation obligations are confirmed |
| Wikidata | none for literal `wikidata` | external linked-data ontology/entity source | configured `spine`; absent as persisted live source | 0 | 0 | no persisted live source value in 2026-05-03 scan | upstream homepage `https://www.wikidata.org`; no raw artifact path measured in current pass | `src/brain_researcher/core/ingestion/loaders/wikidata_unified.py`; `src/brain_researcher/services/neurokg/etl/loaders/wikidata_loader.py`; `scripts/neurokg/load_wikidata_brain_regions.py` | Wikidata license/citation not release-verified in repo | mark configured but absent unless source markers or artifacts are added |
| Virtual Brain | none for literal `virtual_brain` | external software/simulation lane | configured `spine`; absent as persisted live source | 0 | 0 | no persisted live source value in 2026-05-03 scan | upstream homepage `https://www.thevirtualbrain.org`; local service paths under `src/brain_researcher/services/virtual_brain` | `src/brain_researcher/core/ingestion/loaders/virtual_brain_loader.py`; `src/brain_researcher/services/neurokg/etl/adapters/virtual_brain_adapter.py`; `scripts/virtual_brain/create_simulation_links.py` | software/data license and citation not release-verified in repo | document as configured/adapter lane, not released KG content unless simulation reports are included |
| GWAS Catalog / OpenMed / PGC | none in 2026-05-03 source-like scan under OpenMed/PGC/GWAS source names | external genetics metadata and top-loci lane | documented ingest, but not visible in current source scan | 0 in current source scan | 0 in current source scan | `docs/neurokg/openmed_pgc_gwas_ingest.md` reports validation counts as of 2026-04-08, but those source strings are absent from the current source scan | upstream sources are Hugging Face `OpenMed/pgc-*` repos and GWAS Catalog REST API; artifact paths not measured in current pass | `src/brain_researcher/services/neurokg/etl/loaders/openmed_pgc_hf_loader.py`; `src/brain_researcher/services/neurokg/etl/loaders/gwas_catalog_top_loci_loader.py`; `scripts/neurokg/run_openmed_pgc_live_ingest.py` | OpenMed/HF and GWAS Catalog license/citation not release-verified in repo | reconcile current live graph with 2026-04-08 validation counts before release claims |
| Psych-101 / psychology task registry | `Psych-101`; `psych-101_taxonomy`; `psych101_curated_registry` | external/curated behavioral task registry and taxonomy lane | live, not in `ingestion_modes.yaml` source list | 127 | 390 | live graph snapshot counted on 2026-05-03; source-specific snapshot not stored in live source field | local docs/runbooks include `docs/runbooks/workflow_psych101_*`; artifacts not fully measured in current pass | `src/brain_researcher/services/neurokg/etl/loaders/psych101_loader.py`; `src/brain_researcher/services/neurokg/etl/loaders/psych101_hf_loader.py`; `scripts/neurokg/audit_psych101_task_fmri_bridge.py` | upstream and curated-registry license/citation not release-verified in repo | release as curated registry only after source snapshot, curator status, and license are pinned |
| Tool/capability catalog | `capabilities.merged.yaml` | internal BR capability registry | live internal source lane | 2,073 | 0 | live graph snapshot counted on 2026-05-03; config version not embedded in source string | repo config `configs/catalog/capabilities.generated.yaml`; source config `configs/neurokg/sources/tools_catalog.yaml` | `src/brain_researcher/services/neurokg/loader/tools_catalog_loader.py` | internal repo artifact, not external data license; citation not applicable except BR software/data card | include only if public KG intentionally includes BR runtime/tool nodes; otherwise split from NeuroKG public dump |
| Config text backfill | `config_text_backfill` | internal generated enrichment | live internal source lane | 0 | 104,603 | live graph snapshot counted on 2026-05-03; rule version not embedded in source string | artifact path not measured in current pass | loader/script path not mapped in current pass | inherits upstream/source-node licenses; generated rule citation not applicable | keep as internal generated lane; release only with rule definition and affected edge-type audit |
| Taxonomy rules | `taxonomy_rule`; `taxonomy_surface_rules` | internal generated taxonomy/rule lane | live internal source lane | 4 | 612 | live graph snapshot counted on 2026-05-03; rule version not embedded in source string | local configs include `configs/taxonomy/*` and `configs/neurokg/scientific_review_rule_registry.yaml` | `src/brain_researcher/services/neurokg/etl/linkers/taxonomy_linker.py`; `src/brain_researcher/services/neurokg/etl/loaders/scientific_review_rule_registry_loader.py` | internal/generated; cite local method/config version, not external upstream | release with rule/version manifest or exclude from upstream-source table |
| Task family enrichment | `task_families`; `task_family_enrichment` | internal/generated task-family catalog | live internal source lane | 328 | 126 | live graph snapshot counted on 2026-05-03; family registry version not embedded in source string | local configs include `configs/taxonomy/families` and related crosswalks | `src/brain_researcher/services/neurokg/task_family_matcher.py`; taxonomy/linker scripts under `scripts/analysis` and `scripts/tools/ontologies` | internal/generated; cite local curation/method version | release with task-family registry version and curator/source evidence |
| Disease path backfill | `disease_path_backfill` | internal generated backfill | live internal source lane | 0 | 34 | live graph snapshot counted on 2026-05-03; backfill version not embedded in source string | artifact path not measured in current pass | script path not mapped in current pass | inherits upstream disease/source licenses; no separate external citation | audit before release; document rule or remove accidental backfill edges |
| Seed/bootstrap lane | `seed` | seed/manual bootstrap | live internal source lane | 0 | 4 | live graph snapshot counted on 2026-05-03; seed artifact not mapped | artifact path not measured in current pass | builder path not mapped in current pass | internal/manual; no upstream license without seed evidence | audit and either attribute seed rows or exclude from public dump |
| Bulk loader operational lane | `bulk_loader` | operational loader marker | live internal source lane | 0 | 1 | live graph snapshot counted on 2026-05-03 | artifact path not measured in current pass | `src/brain_researcher/services/neurokg/bulk_loader.py` | internal operational marker | audit whether this should be provenance metadata or excluded |
| GraphQL API runtime lane | `GraphQL API` | runtime/API-created records | live runtime lane | 0 | 5 | live graph snapshot counted on 2026-05-03 | artifact path not measured in current pass | `src/brain_researcher/services/neurokg/api/graphql_enhanced.py`; `src/brain_researcher/services/neurokg/api/graphql_optimized.py` | runtime/manual; upstream evidence unknown | audit as possible production mutation/test residue before release |
| Manual lane | `Manual` | manual curation lane | live manual lane | 0 | 2 | live graph snapshot counted on 2026-05-03 | manual artifact path not measured in current pass | curation API exists under `src/brain_researcher/services/neurokg/api/curation.py` and `src/brain_researcher/services/neurokg/curation/curation_api.py` | manual curation must cite underlying evidence, not just curator action | release only after curator workflow and evidence provenance are documented |
| Test lanes | `Integration Test`; `Test`; `Test Suite` | test artifacts | live test lane | 0 | 3 | live graph snapshot counted on 2026-05-03 | artifact path not measured in current pass | test source not mapped in current pass | not release data | exclude from public dump or mark internal-test-only |
| Unattributed source | `<missing>` | unresolved provenance gap | live source-like missing value | 6,889 | 41,393 | live graph snapshot counted on 2026-05-03 | not applicable until attributed | audit by label/type and loader-created fields | not releasable as-is | release blocker: backfill, exclude, or explicitly document each bucket |
| Gabriel paper-mining lane | no live `gabriel` source marker | LLM/heuristic candidate extraction lane | repo artifacts exist; absent as live source marker | 0 | 0 | 32 run manifests and 12 review queues found under `data/neurokg/raw/gabriel/runs` | local docs `docs/neurokg/gabriel_full_pipeline.md`; raw artifacts under `data/neurokg/raw/gabriel` | `src/brain_researcher/services/neurokg/etl/gabriel_generator.py`; `src/brain_researcher/services/neurokg/etl/loaders/gabriel_loader.py`; `scripts/deep_research_to_gabriel_manifest.py` | upstream paper licenses, model/prompt versions, and validation/citation status not release-verified | candidate-only unless accepted records are explicitly ingested with source markers and validation evidence |
| KGGen comparison/generation lane | no live `kggen` source marker | LLM/generated comparison/candidate lane | repo artifacts exist; absent as live source marker | 0 | 0 | 75 `*.summary.json` files and 81 `*.jsonl` files found under `data/neurokg/raw/kggen` | raw artifacts under `data/neurokg/raw/kggen`; linked from `docs/neurokg/gabriel_full_pipeline.md` | `src/brain_researcher/services/neurokg/etl/evaluation/gabriel_kggen_eval.py`; `scripts/kggen_generate_from_manifest.py`; `scripts/neurokg/build_kggen_task_mapping_salvage_pack.py` | model/prompt/license/citation and validation status not release-verified | keep as comparison/candidate lane unless promoted records are validated and source-marked |
| Scientific review / governance registry | no live source string identified in current scan | internal governance/rule registry | repo source exists; not detected in source-like scan | 0 | 0 | current source-like scan did not find a registry source value | local config `configs/neurokg/scientific_review_rule_registry.yaml` | `src/brain_researcher/services/neurokg/etl/loaders/scientific_review_rule_registry_loader.py` | internal policy/config, not external upstream data | document separately from NeuroKG upstream source list unless records are included in public dump |

Coverage check: the table above covers all 48 live source-like values in the
2026-05-03 source scan, plus configured-but-absent sources and repo-visible
candidate/governance lanes. No live source-like value is intentionally left
unassigned; unresolved rows are marked as internal, candidate-only, absent, or
release blockers.

#### Gabriel And KGGen Status

Gabriel/KGGen artifacts exist in the repo, but the 2026-05-03 live graph source
scan found `0` nodes and `0` edges whose source-like value contains `gabriel`
or `kggen`.

| Lane | Repo artifacts found | Live source count | Current interpretation | Required follow-up |
|---|---:|---:|---|---|
| Gabriel manifests | 32 `data/neurokg/raw/gabriel/runs/*/manifest.json` files | 0 source-marked nodes/edges | Gabriel exists as raw/run artifacts, but is not visible as a marked live KG source in this scan | decide whether Gabriel was not ingested, was candidate-only, or was ingested without a `source=gabriel` marker |
| Gabriel review queues | 12 `data/neurokg/raw/gabriel/runs/*/review_queue*.jsonl` files | 0 source-marked nodes/edges | review/candidate artifacts exist outside live source counts | document accepted vs candidate-only vs rejected lanes before release |
| KGGen summaries | 75 `data/neurokg/raw/kggen/**/*.summary.json` files | 0 source-marked nodes/edges | KGGen exists as comparison/generation artifacts, not as a marked live KG source | keep KGGen as research/comparison lane unless accepted records are explicitly ingested and marked |
| KGGen JSONL outputs | 81 `data/neurokg/raw/kggen/**/*.jsonl` files | 0 source-marked nodes/edges | generated candidate files exist | document model/prompt/validation before any public KG claim |

### Full Canonical Schema-Triple Counts
| Rank | Source label set | Relationship | Target label set | Edge count | Share of edges |
|---|---|---|---|---|---|
| 1 | `StatisticalMap` | `BELONGS_TO` | `Collection` | 1,075,385 | 44.38% |
| 2 | `Publication` | `HAS_COORDINATE` | `Coordinate` | 447,499 | 18.47% |
| 3 | `Publication` | `HAS_TERM` | `Term` | 358,050 | 14.78% |
| 4 | `StatsMap` | `IN_REGION` | `BrainRegion` | 121,261 | 5.00% |
| 5 | `Publication` | `ABOUT` | `Concept\|OntologyConcept\|OnvocClass` | 67,785 | 2.80% |
| 6 | `Task` | `IN_DOMAIN` | `Process\|ConceptClass` | 52,117 | 2.15% |
| 7 | `StatsMap` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 43,958 | 1.81% |
| 8 | `StatsMap` | `IN_SPACE` | `TemplateSpace` | 35,180 | 1.45% |
| 9 | `StatsMap` | `COMPUTED_WITH` | `ModelSpec` | 30,880 | 1.27% |
| 10 | `StatsMap` | `GENERATED_FROM` | `TaskAnalysis` | 30,880 | 1.27% |
| 11 | `StatsMap` | `DERIVED_FROM` | `Contrast\|GLMContrast` | 30,120 | 1.24% |
| 12 | `StatsMap` | `HAS_RESOURCE` | `DataResource\|OpenNeuro` | 14,146 | 0.58% |
| 13 | `Publication` | `HAS_TEXT_EMBEDDING` | `Embedding` | 12,958 | 0.53% |
| 14 | `Task` | `MAPS_TO` | `Task` | 11,062 | 0.46% |
| 15 | `Task` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 10,894 | 0.45% |
| 16 | `StatisticalMap` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 7,331 | 0.30% |
| 17 | `StatsMap` | `MEASURES` | `Concept` | 4,502 | 0.19% |
| 18 | `Tool` | `HAS_VERSION` | `ToolVersion` | 4,142 | 0.17% |
| 19 | `DataResource\|OpenNeuro` | `ABOUT` | `Concept\|OntologyConcept\|OnvocClass` | 3,689 | 0.15% |
| 20 | `Task` | `MEASURES` | `Task` | 3,560 | 0.15% |
| 21 | `Publication` | `CITES` | `Publication` | 3,395 | 0.14% |
| 22 | `Concept` | `MAPS_TO` | `Concept` | 3,145 | 0.13% |
| 23 | `Dataset\|DataResource` | `ABOUT` | `Concept\|OntologyConcept\|OnvocClass` | 2,807 | 0.12% |
| 24 | `Task` | `MEASURES` | `Concept` | 2,773 | 0.11% |
| 25 | `Tool` | `SUPPORTS_MODALITY` | `Modality` | 2,655 | 0.11% |
| 26 | `Tool` | `IMPLEMENTS_FAMILY` | `TaskFamily` | 2,167 | 0.09% |
| 27 | `Tool` | `IMPLEMENTS_FAMILY` | `ToolFamily` | 2,127 | 0.09% |
| 28 | `Subject` | `PARTICIPATES_IN` | `TaskAnalysis` | 1,982 | 0.08% |
| 29 | `StatsMap` | `SUGGESTS_MEASURES` | `Concept` | 1,902 | 0.08% |
| 30 | `Dataset\|DataResource` | `HAS_MODALITY` | `Modality` | 1,839 | 0.08% |
| 31 | `Dataset\|DataResource` | `HOSTED_AT` | `Repository` | 1,694 | 0.07% |
| 32 | `Task` | `HAS_CONTRAST` | `Contrast` | 1,585 | 0.07% |
| 33 | `Dataset\|DataResource` | `HAS_TASK` | `Task` | 1,569 | 0.06% |
| 34 | `StatisticalMap` | `BELONGS_TO` | `StatisticalMap` | 1,454 | 0.06% |
| 35 | `Tool` | `ABOUT` | `Concept\|OntologyConcept\|OnvocClass` | 1,337 | 0.06% |
| 36 | `Atlas` | `HAS_REGION` | `BrainRegion` | 1,327 | 0.05% |
| 37 | `BrainRegion` | `PART_OF` | `BrainRegion` | 1,326 | 0.05% |
| 38 | `Concept` | `MAPS_TO` | `Task` | 1,312 | 0.05% |
| 39 | `Task` | `MAPS_TO` | `Concept` | 1,289 | 0.05% |
| 40 | `Task` | `ASSERTS` | `Concept` | 1,237 | 0.05% |
| 41 | `SubjectGroup` | `HAS_PHENOTYPE` | `Phenotype` | 1,218 | 0.05% |
| 42 | `Concept` | `MEASUREDBY` | `Task` | 1,218 | 0.05% |
| 43 | `Task` | `HASCITATION` | `Citation` | 1,091 | 0.05% |
| 44 | `Dataset\|DataResource` | `INVOLVES_SPECIES` | `Species` | 990 | 0.04% |
| 45 | `Task` | `HASCONDITION` | `TaskCondition` | 807 | 0.03% |
| 46 | `Parcellation` | `HAS_REGION` | `BrainRegion` | 796 | 0.03% |
| 47 | `Concept\|OntologyConcept\|OnvocClass` | `CLASSIFIED_UNDER` | `Concept\|OntologyConcept\|OnvocClass` | 765 | 0.03% |
| 48 | `Contrast\|GLMContrast` | `USES_CONDITION` | `Condition` | 750 | 0.03% |
| 49 | `Contrast\|GLMContrast` | `MAPS_TO` | `Contrast\|GLMContrast` | 621 | 0.03% |
| 50 | `Task` | `SUGGESTS_MEASURES` | `Task` | 612 | 0.03% |
| 51 | `Task` | `HASINDICATOR` | `TaskIndicator` | 584 | 0.02% |
| 52 | `Concept` | `CLASSIFIEDUNDER` | `Process\|ConceptClass` | 523 | 0.02% |
| 53 | `Contrast\|GLMContrast` | `BELONGS_TO` | `Publication` | 517 | 0.02% |
| 54 | `Contrast` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 468 | 0.02% |
| 55 | `TaskAnalysis` | `HAS_RESOURCE` | `DataResource\|OpenNeuro` | 432 | 0.02% |
| 56 | `Concept` | `KINDOF` | `Concept` | 429 | 0.02% |
| 57 | `Dataset` | `INCLUDES` | `SubjectGroup` | 402 | 0.02% |
| 58 | `ModelSpec` | `HAS_CONTRAST` | `Contrast\|GLMContrast` | 393 | 0.02% |
| 59 | `Dataset\|DataResource` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 367 | 0.02% |
| 60 | `ToolVersion` | `PRODUCES_RESOURCE` | `ResourceType` | 362 | 0.01% |
| 61 | `ToolVersion` | `CONSUMES_RESOURCE` | `ResourceType` | 338 | 0.01% |
| 62 | `TaskAnalysis` | `HAS_CONDITION` | `Condition` | 310 | 0.01% |
| 63 | `Author` | `AFFILIATED_WITH` | `Institution` | 292 | 0.01% |
| 64 | `Concept` | `PARTOF` | `Concept` | 263 | 0.01% |
| 65 | `Dataset` | `ABOUT` | `Concept\|OntologyConcept\|OnvocClass` | 254 | 0.01% |
| 66 | `Dataset\|OpenNeuro` | `HAS_CONTRAST` | `Contrast\|GLMContrast` | 243 | 0.01% |
| 67 | `TaskSpec` | `HAS_CONTRAST` | `Contrast\|GLMContrast` | 243 | 0.01% |
| 68 | `Publication` | `AUTHORED_BY` | `Author` | 232 | 0.01% |
| 69 | `Contrast\|GLMContrast` | `BELONGS_TO` | `Study` | 217 | 0.01% |
| 70 | `Concept` | `HASCITATION` | `Citation` | 202 | 0.01% |
| 71 | `Task` | `RELATED_TO` | `Concept` | 185 | 0.01% |
| 72 | `Task` | `BELONGS_TO_FAMILY` | `TaskFamily` | 176 | 0.01% |
| 73 | `ReviewRule` | `REQUIRES_FIELD` | `ReviewSchemaField` | 162 | 0.01% |
| 74 | `Experiment\|Psych101Experiment` | `USES_TASK` | `Task` | 151 | 0.01% |
| 75 | `TaskSpec` | `HAS_GLM_PRIOR` | `GLMDesignPrior` | 148 | 0.01% |
| 76 | `ModelSpec` | `HAS_RESOURCE` | `DataResource\|OpenNeuro` | 144 | 0.01% |
| 77 | `Task` | `INBATTERY` | `Battery` | 134 | 0.01% |
| 78 | `ReviewRule` | `HAS_VALIDITY_LAYER` | `ReviewValidityLayer` | 102 | 0.00% |
| 79 | `Dataset\|DataResource` | `PART_OF` | `Consortium` | 99 | 0.00% |
| 80 | `Experiment\|Psych101Experiment` | `CLASSIFIED_UNDER` | `TaskFamily` | 98 | 0.00% |
| 81 | `ReviewRule` | `HAS_REASON_TAG` | `ReviewReasonTag` | 81 | 0.00% |
| 82 | `ReviewImplementationRuleCatalog` | `CONTAINS_IMPLEMENTATION_RULE` | `ReviewImplementationRule` | 80 | 0.00% |
| 83 | `Dataset\|Psych101Dataset` | `HAS_EXPERIMENT` | `Experiment\|Psych101Experiment` | 76 | 0.00% |
| 84 | `ModelSpec` | `DESCRIBES_TASK` | `TaskAnalysis` | 72 | 0.00% |
| 85 | `Dataset\|OpenNeuro` | `HAS_GLM_PRIOR` | `GLMDesignPrior` | 72 | 0.00% |
| 86 | `Dataset\|DataResource` | `HAS_TASK` | `TaskSpec` | 72 | 0.00% |
| 87 | `ReviewRuleRegistry` | `CONTAINS_RULE` | `ReviewRule` | 71 | 0.00% |
| 88 | `ReviewRule` | `HAS_LIFECYCLE_STATUS` | `ReviewLifecycleStatus` | 71 | 0.00% |
| 89 | `ReviewRule` | `HAS_SEVERITY` | `ReviewSeverity` | 71 | 0.00% |
| 90 | `ReviewRule` | `IN_RULE_GROUP` | `ReviewRuleGroup` | 71 | 0.00% |
| 91 | `Collection` | `MAPS_TO` | `Dataset\|DataResource` | 61 | 0.00% |
| 92 | `ReviewRuleRegistry` | `CONTAINS_CALIBRATION_CASE` | `ReviewCalibrationCase` | 60 | 0.00% |
| 93 | `Concept` | `MAPS_TO` | `Concept\|OntologyConcept\|OnvocClass` | 60 | 0.00% |
| 94 | `ReviewCalibrationCase` | `CALIBRATES_RULE` | `ReviewRule` | 55 | 0.00% |
| 95 | `Contrast\|GLMContrast` | `CONTRAST_OF` | `Concept` | 52 | 0.00% |
| 96 | `Dataset\|DataResource` | `CITED_BY` | `Publication` | 49 | 0.00% |
| 97 | `Dataset\|OpenNeuro` | `ABOUT` | `Concept\|OntologyConcept\|OnvocClass` | 40 | 0.00% |
| 98 | `Contrast\|GLMContrast` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 40 | 0.00% |
| 99 | `StatMap` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 40 | 0.00% |
| 100 | `Dataset\|OpenNeuro` | `HAS_TASK` | `TaskSpec` | 38 | 0.00% |
| 101 | `Dataset\|OpenNeuro` | `MAPS_TO` | `Dataset\|OpenNeuro` | 38 | 0.00% |
| 102 | `StatMap` | `DERIVED_FROM` | `Contrast` | 37 | 0.00% |
| 103 | `TaskAnalysis` | `MEASURES` | `Concept` | 32 | 0.00% |
| 104 | `ReviewRule` | `MAPPED_TO_IMPLEMENTATION` | `ReviewImplementationRule` | 28 | 0.00% |
| 105 | `Parcellation` | `HAS_PARCEL` | `Parcel` | 26 | 0.00% |
| 106 | `TaskAnalysis` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 23 | 0.00% |
| 107 | `Concept` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 22 | 0.00% |
| 108 | `TaskAnalysis` | `MAPS_TO` | `Task` | 19 | 0.00% |
| 109 | `StatisticalMap` | `MAPS_TO` | `Dataset\|DataResource` | 19 | 0.00% |
| 110 | `Contrast` | `MAPS_TO` | `Contrast\|GLMContrast` | 19 | 0.00% |
| 111 | `Parcellation` | `IN_SPACE` | `TemplateSpace` | 18 | 0.00% |
| 112 | `TaskSpec` | `IN_ONVOC` | `Concept\|OntologyConcept\|OnvocClass` | 17 | 0.00% |
| 113 | `BrainRegion` | `IN_PARCELLATION` | `Parcellation` | 17 | 0.00% |
| 114 | `Collection` | `MAPS_TO` | `Dataset` | 14 | 0.00% |
| 115 | `Tool` | `VALIDATED_ON` | `Dataset\|DataResource` | 11 | 0.00% |
| 116 | `Study` | `ABOUT` | `Concept\|OntologyConcept\|OnvocClass` | 10 | 0.00% |
| 117 | `Concept` | `MEASURES` | `Task` | 8 | 0.00% |
| 118 | `GLMRun` | `HAS_VARIANT` | `GLMVariant` | 7 | 0.00% |
| 119 | `StatMap` | `DERIVED_FROM` | `Contrast\|GLMContrast` | 6 | 0.00% |
| 120 | `ReviewRuleRegistry` | `HAS_POLICY_DECISION` | `ReviewPolicyDecision` | 6 | 0.00% |
| 121 | `Parcellation` | `HAS_RESOURCE` | `DataResource` | 6 | 0.00% |
| 122 | `Task` | `ACTIVATES` | `Region` | 5 | 0.00% |
| 123 | `StatisticalMap` | `MAPS_TO` | `Dataset` | 5 | 0.00% |
| 124 | `ReviewRule` | `TRIGGERS_SENSITIVITY` | `ReviewSensitivityTemplate` | 5 | 0.00% |
| 125 | `Run` | `HAD_FAILURE` | `ExecutionFailure` | 4 | 0.00% |
| 126 | `Task` | `HAS_GLM_PRIOR` | `GLMDesignPrior` | 4 | 0.00% |
| 127 | `Tool` | `FAILED_ON` | `Dataset\|DataResource` | 3 | 0.00% |
| 128 | `Tool` | `HAD_FAILURE` | `ExecutionFailure` | 3 | 0.00% |
| 129 | `TaskAnalysis` | `MAPS_TO` | `Concept` | 3 | 0.00% |
| 130 | `Concept` | `RELATED_TO` | `Task` | 3 | 0.00% |
| 131 | `Tool` | `DOCUMENTED_IN` | `Publication` | 2 | 0.00% |
| 132 | `Atlas` | `HAS_PARCELLATION` | `Parcellation` | 2 | 0.00% |
| 133 | `Concept` | `RELATED_TO` | `Concept` | 2 | 0.00% |
| 134 | `Tool` | `VALIDATED_ON` | `DataResource` | 2 | 0.00% |
| 135 | `Concept` | `ACTIVATES` | `Task` | 1 | 0.00% |
| 136 | `ReviewCalibrationCase` | `CALIBRATES_MODIFIER` | `ReviewPositiveModifier` | 1 | 0.00% |
| 137 | `Atlas` | `CITES` | `Publication` | 1 | 0.00% |
| 138 | `Concept` | `CITES` | `Task` | 1 | 0.00% |
| 139 | `ReviewRuleRegistry` | `CONTAINS_MODIFIER` | `ReviewPositiveModifier` | 1 | 0.00% |
| 140 | `Contrast\|GLMContrast` | `CONTRAST_OF` | `Concept\|OntologyConcept\|OnvocClass` | 1 | 0.00% |
| 141 | `Tool` | `HAS_EVIDENCE` | `ToolEvidence` | 1 | 0.00% |
| 142 | `Dataset\|OpenNeuro` | `HAS_GLM_RUN` | `GLMRun` | 1 | 0.00% |
| 143 | `TaskSpec` | `HAS_GLM_RUN` | `GLMRun` | 1 | 0.00% |
| 144 | `GLMRun` | `HAS_SUMMARY` | `ResultSummary` | 1 | 0.00% |
| 145 | `Atlas` | `IN_SPACE` | `TemplateSpace` | 1 | 0.00% |
| 146 | `Coordinate` | `LOCATED_IN` | `Region` | 1 | 0.00% |
| 147 | `Concept` | `MEASURED_BY` | `Task` | 1 | 0.00% |
| 148 | `Publication` | `MENTIONS_CONCEPT` | `Concept` | 1 | 0.00% |
| 149 | `ReviewPositiveModifier` | `REQUIRES_FIELD` | `ReviewSchemaField` | 1 | 0.00% |
| 150 | `Concept` | `SIMILAR_TO` | `Task` | 1 | 0.00% |
| 151 | `Dataset` | `USES_TASK` | `Task` | 1 | 0.00% |

### Node Property Coverage
Format: `property present/label_count (missing; present%)`.
| Node label | Nodes | Property count | Property coverage values |
|---|---|---|---|
| `Coordinate` | 447,499 | 8 | `id` 447,499/447,499 (0 missing; 100.00%); `labels` 447,499/447,499 (0 missing; 100.00%); `space` 447,499/447,499 (0 missing; 100.00%); `x` 447,499/447,499 (0 missing; 100.00%); `y` 447,499/447,499 (0 missing; 100.00%); `z` 447,499/447,499 (0 missing; 100.00%); `round_mm` 447,498/447,499 (1 missing; 100.00%); `source` 447,498/447,499 (1 missing; 100.00%) |
| `Publication` | 49,744 | 23 | `source` 49,738/49,744 (6 missing; 99.99%); `id` 49,580/49,744 (164 missing; 99.67%); `labels` 49,580/49,744 (164 missing; 99.67%); `doi` 48,499/49,744 (1,245 missing; 97.50%); `title` 47,042/49,744 (2,702 missing; 94.57%); `pmid` 32,873/49,744 (16,871 missing; 66.08%); `journal` 15,324/49,744 (34,420 missing; 30.81%); `year` 14,223/49,744 (35,521 missing; 28.59%); `authors` 14,222/49,744 (35,522 missing; 28.59%); `neurosynth_id` 14,222/49,744 (35,522 missing; 28.59%); `space` 14,222/49,744 (35,522 missing; 28.59%); `abstract` 493/49,744 (49,251 missing; 0.99%); `concepts` 493/49,744 (49,251 missing; 0.99%); `mesh_terms` 493/49,744 (49,251 missing; 0.99%); `issn` 57/49,744 (49,687 missing; 0.11%); `keywords` 57/49,744 (49,687 missing; 0.11%); `openalex_id` 57/49,744 (49,687 missing; 0.11%); `publication_date` 57/49,744 (49,687 missing; 0.11%); `publication_year` 57/49,744 (49,687 missing; 0.11%); `dataset_id` 49/49,744 (49,695 missing; 0.10%); `reference` 49/49,744 (49,695 missing; 0.10%); `is_dataset_doi` 6/49,744 (49,738 missing; 0.01%); `url` 1/49,744 (49,743 missing; 0.00%) |
| `Collection` | 48,009 | 114 | `id` 48,009/48,009 (0 missing; 100.00%); `labels` 48,009/48,009 (0 missing; 100.00%); `name` 48,009/48,009 (0 missing; 100.00%); `source` 48,009/48,009 (0 missing; 100.00%); `publication_id` 31,885/48,009 (16,124 missing; 66.41%); `study_id` 31,885/48,009 (16,124 missing; 66.41%); `modalities` 31,884/48,009 (16,125 missing; 66.41%); `study_objective` 31,729/48,009 (16,280 missing; 66.09%); `title` 31,729/48,009 (16,280 missing; 66.09%); `owner_name` 16,124/48,009 (31,885 missing; 33.59%); `url` 16,124/48,009 (31,885 missing; 33.59%); `add_date` 15,991/48,009 (32,018 missing; 33.31%); `communities` 15,991/48,009 (32,018 missing; 33.31%); `contributors` 15,991/48,009 (32,018 missing; 33.31%); `download_url` 15,991/48,009 (32,018 missing; 33.31%); `modify_date` 15,991/48,009 (32,018 missing; 33.31%); `number_of_images` 15,991/48,009 (32,018 missing; 33.31%); `owner` 15,991/48,009 (32,018 missing; 33.31%); `private` 15,991/48,009 (32,018 missing; 33.31%); `full_dataset_url` 10,845/48,009 (37,164 missing; 22.59%); `description` 6,784/48,009 (41,225 missing; 14.13%); `paper_url` 2,710/48,009 (45,299 missing; 5.64%); `journal_name` 2,705/48,009 (45,304 missing; 5.63%); `authors` 2,696/48,009 (45,313 missing; 5.62%); `software_package` 2,650/48,009 (45,359 missing; 5.52%); `scanner_make` 2,645/48,009 (45,364 missing; 5.51%); `scanner_model` 2,641/48,009 (45,368 missing; 5.50%); `intrasubject_model_type` 2,637/48,009 (45,372 missing; 5.49%); `software_version` 2,637/48,009 (45,372 missing; 5.49%); `intersubject_registration_software` 2,635/48,009 (45,374 missing; 5.49%); `pulse_sequence` 2,635/48,009 (45,374 missing; 5.49%); `hemodynamic_response_function` 2,633/48,009 (45,376 missing; 5.48%); `smoothing_type` 2,633/48,009 (45,376 missing; 5.48%); `group_description` 2,632/48,009 (45,377 missing; 5.48%); `intrasubject_modeling_software` 2,631/48,009 (45,378 missing; 5.48%); `acquisition_orientation` 2,630/48,009 (45,379 missing; 5.48%); `group_model_type` 2,630/48,009 (45,379 missing; 5.48%); `group_modeling_software` 2,630/48,009 (45,379 missing; 5.48%); `inclusion_exclusion_criteria` 2,630/48,009 (45,379 missing; 5.48%); `high_pass_filter_method` 2,629/48,009 (45,380 missing; 5.48%); `order_of_preprocessing_operations` 2,625/48,009 (45,384 missing; 5.47%); `autocorrelation_model` 2,624/48,009 (45,385 missing; 5.47%); `motion_correction_software` 2,624/48,009 (45,385 missing; 5.47%); `intrasubject_estimation_type` 2,623/48,009 (45,386 missing; 5.46%); `object_image_type` 2,623/48,009 (45,386 missing; 5.46%); `parallel_imaging` 2,622/48,009 (45,387 missing; 5.46%); `group_estimation_type` 2,621/48,009 (45,388 missing; 5.46%); `quality_control` 2,620/48,009 (45,389 missing; 5.46%); `functional_coregistration_method` 2,619/48,009 (45,390 missing; 5.46%); `motion_correction_reference` 2,619/48,009 (45,390 missing; 5.46%); `b0_unwarping_software` 2,618/48,009 (45,391 missing; 5.45%); `group_repeated_measures_method` 2,616/48,009 (45,393 missing; 5.45%); `nonlinear_transform_type` 2,615/48,009 (45,394 missing; 5.45%); `slice_timing_correction_software` 2,615/48,009 (45,394 missing; 5.45%); `group_model_multilevel` 2,614/48,009 (45,395 missing; 5.44%); `interpolation_method` 2,614/48,009 (45,395 missing; 5.44%); `motion_correction_interpolation` 2,614/48,009 (45,395 missing; 5.44%); `motion_correction_metric` 2,614/48,009 (45,395 missing; 5.44%); `optimization_method` 2,614/48,009 (45,395 missing; 5.44%); `orthogonalization_description` 2,614/48,009 (45,395 missing; 5.44%); `transform_similarity_metric` 2,612/48,009 (45,397 missing; 5.44%); `target_template_image` 2,611/48,009 (45,398 missing; 5.44%); `length_of_trials` 2,498/48,009 (45,511 missing; 5.20%); `nutbrain_food_viewing_conditions` 1,576/48,009 (46,433 missing; 3.28%); `nutbrain_food_choice_type` 1,574/48,009 (46,435 missing; 3.28%); `nutbrain_odor_conditions` 1,574/48,009 (46,435 missing; 3.28%); `nutbrain_taste_conditions` 1,572/48,009 (46,437 missing; 3.27%); `doi_add_date` 931/48,009 (47,078 missing; 1.94%); `DOI` 924/48,009 (47,085 missing; 1.92%); `group_comparison` 463/48,009 (47,546 missing; 0.96%); `type_of_design` 441/48,009 (47,568 missing; 0.92%); `handedness` 396/48,009 (47,613 missing; 0.82%); `subject_age_mean` 348/48,009 (47,661 missing; 0.72%); `field_strength` 330/48,009 (47,679 missing; 0.69%); `used_intersubject_registration` 325/48,009 (47,684 missing; 0.68%); `proportion_male_subjects` 322/48,009 (47,687 missing; 0.67%); `publication_status` 303/48,009 (47,706 missing; 0.63%); `subject_age_min` 303/48,009 (47,706 missing; 0.63%); `coordinate_space` 301/48,009 (47,708 missing; 0.63%); `subject_age_max` 300/48,009 (47,709 missing; 0.62%); `used_smoothing` 299/48,009 (47,710 missing; 0.62%); `used_motion_correction` 287/48,009 (47,722 missing; 0.60%); `functional_coregistered_to_structural` 280/48,009 (47,729 missing; 0.58%); `used_slice_timing_correction` 266/48,009 (47,743 missing; 0.55%); `repetition_time` 263/48,009 (47,746 missing; 0.55%); `number_of_imaging_runs` 261/48,009 (47,748 missing; 0.54%); `used_motion_regressors` 255/48,009 (47,754 missing; 0.53%); `intersubject_transformation_type` 253/48,009 (47,756 missing; 0.53%); `order_of_acquisition` 239/48,009 (47,770 missing; 0.50%); `echo_time` 232/48,009 (47,777 missing; 0.48%); `number_of_rejected_subjects` 230/48,009 (47,779 missing; 0.48%); `group_inference_type` 226/48,009 (47,783 missing; 0.47%); `used_reaction_time_regressor` 222/48,009 (47,787 missing; 0.46%); `flip_angle` 220/48,009 (47,789 missing; 0.46%); `smoothing_fwhm` 217/48,009 (47,792 missing; 0.45%); `used_temporal_derivatives` 216/48,009 (47,793 missing; 0.45%); `used_b0_unwarping` 215/48,009 (47,794 missing; 0.45%); `group_repeated_measures` 214/48,009 (47,795 missing; 0.45%); `slice_thickness` 213/48,009 (47,796 missing; 0.44%); `number_of_experimental_units` 204/48,009 (47,805 missing; 0.42%); `used_orthogonalization` 192/48,009 (47,817 missing; 0.40%); `optimization` 190/48,009 (47,819 missing; 0.40%); `used_dispersion_derivatives` 190/48,009 (47,819 missing; 0.40%); `field_of_view` 184/48,009 (47,825 missing; 0.38%); `used_high_pass_filter` 167/48,009 (47,842 missing; 0.35%); `matrix_size` 157/48,009 (47,852 missing; 0.33%); `length_of_runs` 149/48,009 (47,860 missing; 0.31%); `resampled_voxel_size` 149/48,009 (47,860 missing; 0.31%); `skip_distance` 137/48,009 (47,872 missing; 0.29%); `used_motion_susceptibiity_correction` 125/48,009 (47,884 missing; 0.26%); `target_resolution` 111/48,009 (47,898 missing; 0.23%); `length_of_blocks` 51/48,009 (47,958 missing; 0.11%); `nutbrain_hunger_state` 26/48,009 (47,983 missing; 0.05%); `preprint_DOI` 15/48,009 (47,994 missing; 0.03%) |
| `StatsMap` | 35,240 | 26 | `id` 35,240/35,240 (0 missing; 100.00%); `source` 35,240/35,240 (0 missing; 100.00%); `analysis_level` 35,180/35,240 (60 missing; 99.83%); `contrast` 35,180/35,240 (60 missing; 99.83%); `dataset_id` 35,180/35,240 (60 missing; 99.83%); `format` 35,180/35,240 (60 missing; 99.83%); `ingested_at` 35,180/35,240 (60 missing; 99.83%); `is_symlink` 35,180/35,240 (60 missing; 99.83%); `labels` 35,180/35,240 (60 missing; 99.83%); `metadata_json` 35,180/35,240 (60 missing; 99.83%); `node_name` 35,180/35,240 (60 missing; 99.83%); `path` 35,180/35,240 (60 missing; 99.83%); `provided_by` 35,180/35,240 (60 missing; 99.83%); `relative_path` 35,180/35,240 (60 missing; 99.83%); `space` 35,180/35,240 (60 missing; 99.83%); `stat_type` 35,180/35,240 (60 missing; 99.83%); `task` 35,180/35,240 (60 missing; 99.83%); `file_size_bytes` 35,178/35,240 (62 missing; 99.82%); `subject` 34,156/35,240 (1,084 missing; 96.92%); `primary_onvoc_confidence` 32,020/35,240 (3,220 missing; 90.86%); `primary_onvoc_id` 32,020/35,240 (3,220 missing; 90.86%); `symlink_target` 29,045/35,240 (6,195 missing; 82.42%); `run` 25,558/35,240 (9,682 missing; 72.53%); `session` 2,640/35,240 (32,600 missing; 7.49%); `dataset_folder` 2,048/35,240 (33,192 missing; 5.81%); `template_space` 1,910/35,240 (33,330 missing; 5.42%) |
| `Task` | 34,926 | 60 | `id` 34,926/34,926 (0 missing; 100.00%); `labels` 34,926/34,926 (0 missing; 100.00%); `name` 34,926/34,926 (0 missing; 100.00%); `source` 34,914/34,926 (12 missing; 99.97%); `aliases` 34,870/34,926 (56 missing; 99.84%); `alias` 1,167/34,926 (33,759 missing; 3.34%); `batteries` 853/34,926 (34,073 missing; 2.44%); `citations` 853/34,926 (34,073 missing; 2.44%); `concept_relations` 853/34,926 (34,073 missing; 2.44%); `conditions` 853/34,926 (34,073 missing; 2.44%); `contrasts` 853/34,926 (34,073 missing; 2.44%); `creation_time` 853/34,926 (34,073 missing; 2.44%); `definition` 853/34,926 (34,073 missing; 2.44%); `disorders` 853/34,926 (34,073 missing; 2.44%); `external_datasets` 853/34,926 (34,073 missing; 2.44%); `implementations` 853/34,926 (34,073 missing; 2.44%); `indicators` 853/34,926 (34,073 missing; 2.44%); `last_updated` 853/34,926 (34,073 missing; 2.44%); `metadata` 853/34,926 (34,073 missing; 2.44%); `family_id` 470/34,926 (34,456 missing; 1.35%); `family_label` 470/34,926 (34,456 missing; 1.35%); `subfamily_id` 470/34,926 (34,456 missing; 1.35%); `subfamily_label` 470/34,926 (34,456 missing; 1.35%); `created_at` 314/34,926 (34,612 missing; 0.90%); `created_from` 314/34,926 (34,612 missing; 0.90%); `label` 314/34,926 (34,612 missing; 0.90%); `updated_at` 314/34,926 (34,612 missing; 0.90%); `primary_onvoc_confidence` 147/34,926 (34,779 missing; 0.42%); `primary_onvoc_id` 147/34,926 (34,779 missing; 0.42%); `paradigm_name` 126/34,926 (34,800 missing; 0.36%); `task_family_match_method` 126/34,926 (34,800 missing; 0.36%); `task_family_match_score` 126/34,926 (34,800 missing; 0.36%); `task_family_match_source` 126/34,926 (34,800 missing; 0.36%); `description` 48/34,926 (34,878 missing; 0.14%); `description_source` 44/34,926 (34,882 missing; 0.13%); `embedding_centaur_behavior_v1` 44/34,926 (34,882 missing; 0.13%); `embedding_centaur_behavior_v1_backend` 44/34,926 (34,882 missing; 0.13%); `embedding_centaur_behavior_v1_dim` 44/34,926 (34,882 missing; 0.13%); `embedding_centaur_behavior_v1_model` 44/34,926 (34,882 missing; 0.13%); `embedding_centaur_behavior_v1_pooling` 44/34,926 (34,882 missing; 0.13%); `embedding_centaur_behavior_v1_source` 44/34,926 (34,882 missing; 0.13%); `embedding_centaur_behavior_v1_updated_at` 44/34,926 (34,882 missing; 0.13%); `embedding_text_v1` 44/34,926 (34,882 missing; 0.13%); `embedding_text_v1_backend` 44/34,926 (34,882 missing; 0.13%); `embedding_text_v1_dim` 44/34,926 (34,882 missing; 0.13%); `embedding_text_v1_model` 44/34,926 (34,882 missing; 0.13%); `embedding_text_v1_pooling` 44/34,926 (34,882 missing; 0.13%); `embedding_text_v1_source` 44/34,926 (34,882 missing; 0.13%); `embedding_text_v1_template_version` 44/34,926 (34,882 missing; 0.13%); `embedding_text_v1_updated_at` 44/34,926 (34,882 missing; 0.13%); `schema_version` 44/34,926 (34,882 missing; 0.13%); `canonical_name` 39/34,926 (34,887 missing; 0.11%); `ontology_match_method` 39/34,926 (34,887 missing; 0.11%); `ontology_match_score` 39/34,926 (34,887 missing; 0.11%); `canonical_task_id` 16/34,926 (34,910 missing; 0.05%); `canonical_task_name` 16/34,926 (34,910 missing; 0.05%); `links_json` 8/34,926 (34,918 missing; 0.02%); `canonical_task_cogat_id` 7/34,926 (34,919 missing; 0.02%); `canonical_definition` 6/34,926 (34,920 missing; 0.02%); `canonical_id` 4/34,926 (34,922 missing; 0.01%) |
| `Embedding` | 23,865 | 12 | `dimension` 23,865/23,865 (0 missing; 100.00%); `id` 23,865/23,865 (0 missing; 100.00%); `kind` 23,865/23,865 (0 missing; 100.00%); `labels` 23,865/23,865 (0 missing; 100.00%); `model` 23,865/23,865 (0 missing; 100.00%); `normalization` 23,865/23,865 (0 missing; 100.00%); `owner_id` 23,865/23,865 (0 missing; 100.00%); `source` 23,865/23,865 (0 missing; 100.00%); `storage_index` 23,865/23,865 (0 missing; 100.00%); `storage_path` 23,865/23,865 (0 missing; 100.00%); `text_section` 23,865/23,865 (0 missing; 100.00%); `vector_norm` 23,865/23,865 (0 missing; 100.00%) |
| `StatisticalMap` | 21,283 | 43 | `add_date` 21,283/21,283 (0 missing; 100.00%); `brain_coverage` 21,283/21,283 (0 missing; 100.00%); `collection` 21,283/21,283 (0 missing; 100.00%); `collection_id` 21,283/21,283 (0 missing; 100.00%); `data_origin` 21,283/21,283 (0 missing; 100.00%); `file` 21,283/21,283 (0 missing; 100.00%); `file_size` 21,283/21,283 (0 missing; 100.00%); `id` 21,283/21,283 (0 missing; 100.00%); `image_type` 21,283/21,283 (0 missing; 100.00%); `is_valid` 21,283/21,283 (0 missing; 100.00%); `map_type` 21,283/21,283 (0 missing; 100.00%); `modify_date` 21,283/21,283 (0 missing; 100.00%); `name` 21,283/21,283 (0 missing; 100.00%); `not_mni` 21,283/21,283 (0 missing; 100.00%); `perc_bad_voxels` 21,283/21,283 (0 missing; 100.00%); `source` 21,283/21,283 (0 missing; 100.00%); `target_template_image` 21,283/21,283 (0 missing; 100.00%); `url` 21,283/21,283 (0 missing; 100.00%); `qa_score` 21,282/21,283 (1 missing; 100.00%); `qa_status` 21,282/21,283 (1 missing; 100.00%); `labels` 21,281/21,283 (2 missing; 99.99%); `modality` 21,139/21,283 (144 missing; 99.32%); `perc_voxels_outside` 21,115/21,283 (168 missing; 99.21%); `is_thresholded` 20,203/21,283 (1,080 missing; 94.93%); `thumbnail` 17,237/21,283 (4,046 missing; 80.99%); `analysis_level` 16,782/21,283 (4,501 missing; 78.85%); `qa_reasons` 15,783/21,283 (5,500 missing; 74.16%); `surface_left_file` 15,543/21,283 (5,740 missing; 73.03%); `surface_right_file` 15,531/21,283 (5,752 missing; 72.97%); `cognitive_paradigm_cogatlas` 9,868/21,283 (11,415 missing; 46.37%); `cognitive_paradigm_cogatlas_id` 9,868/21,283 (11,415 missing; 46.37%); `number_of_subjects` 5,574/21,283 (15,709 missing; 26.19%); `description` 5,364/21,283 (15,919 missing; 25.20%); `reduced_representation` 4,753/21,283 (16,530 missing; 22.33%); `cognitive_contrast_cogatlas` 3,529/21,283 (17,754 missing; 16.58%); `cognitive_contrast_cogatlas_id` 3,529/21,283 (17,754 missing; 16.58%); `qa_is_primary` 2,108/21,283 (19,175 missing; 9.90%); `contrast_definition` 1,127/21,283 (20,156 missing; 5.30%); `figure` 836/21,283 (20,447 missing; 3.93%); `subject_species` 69/21,283 (21,214 missing; 0.32%); `contrast_definition_cogatlas` 63/21,283 (21,220 missing; 0.30%); `smoothness_fwhm` 5/21,283 (21,278 missing; 0.02%); `statistic_parameters` 1/21,283 (21,282 missing; 0.00%) |
| `DataResource` | 9,282 | 46 | `id` 9,280/9,282 (2 missing; 99.98%); `labels` 9,280/9,282 (2 missing; 99.98%); `name` 9,274/9,282 (8 missing; 99.91%); `format` 7,587/9,282 (1,695 missing; 81.74%); `path` 7,587/9,282 (1,695 missing; 81.74%); `source` 7,587/9,282 (1,695 missing; 81.74%); `file_size_bytes` 7,581/9,282 (1,701 missing; 81.67%); `is_symlink` 7,581/9,282 (1,701 missing; 81.67%); `relative_path` 7,581/9,282 (1,701 missing; 81.67%); `access_type` 1,693/9,282 (7,589 missing; 18.24%); `acquisitions` 1,693/9,282 (7,589 missing; 18.24%); `alias` 1,693/9,282 (7,589 missing; 18.24%); `aliases` 1,693/9,282 (7,589 missing; 18.24%); `category` 1,693/9,282 (7,589 missing; 18.24%); `category_source` 1,693/9,282 (7,589 missing; 18.24%); `created_from` 1,693/9,282 (7,589 missing; 18.24%); `dataset_id` 1,693/9,282 (7,589 missing; 18.24%); `description` 1,693/9,282 (7,589 missing; 18.24%); `disease_flags` 1,693/9,282 (7,589 missing; 18.24%); `has_derivatives` 1,693/9,282 (7,589 missing; 18.24%); `is_openneuro` 1,693/9,282 (7,589 missing; 18.24%); `license` 1,693/9,282 (7,589 missing; 18.24%); `modalities` 1,693/9,282 (7,589 missing; 18.24%); `preview_media` 1,693/9,282 (7,589 missing; 18.24%); `primary_url` 1,693/9,282 (7,589 missing; 18.24%); `search_blob` 1,693/9,282 (7,589 missing; 18.24%); `short_name` 1,693/9,282 (7,589 missing; 18.24%); `source_repo` 1,693/9,282 (7,589 missing; 18.24%); `source_repo_bucket` 1,693/9,282 (7,589 missing; 18.24%); `source_repo_id` 1,693/9,282 (7,589 missing; 18.24%); `species` 1,693/9,282 (7,589 missing; 18.24%); `tags` 1,693/9,282 (7,589 missing; 18.24%); `tasks` 1,693/9,282 (7,589 missing; 18.24%); `modalities_notes` 1,595/9,282 (7,687 missing; 17.18%); `source_version` 1,594/9,282 (7,688 missing; 17.17%); `subjects_count` 713/9,282 (8,569 missing; 7.68%); `age_range` 541/9,282 (8,741 missing; 5.83%); `sessions_count` 356/9,282 (8,926 missing; 3.84%); `primary_onvoc_confidence` 355/9,282 (8,927 missing; 3.82%); `primary_onvoc_id` 355/9,282 (8,927 missing; 3.82%); `center` 100/9,282 (9,182 missing; 1.08%); `consortium` 99/9,282 (9,183 missing; 1.07%); `principal_investigator` 99/9,282 (9,183 missing; 1.07%); `size_human` 99/9,282 (9,183 missing; 1.07%); `atlas_slug` 6/9,282 (9,276 missing; 0.06%); `resource_id` 3/9,282 (9,279 missing; 0.03%) |
| `OpenNeuro` | 7,619 | 12 | `id` 7,619/7,619 (0 missing; 100.00%); `labels` 7,619/7,619 (0 missing; 100.00%); `name` 7,619/7,619 (0 missing; 100.00%); `source` 7,619/7,619 (0 missing; 100.00%); `file_size_bytes` 7,581/7,619 (38 missing; 99.50%); `format` 7,581/7,619 (38 missing; 99.50%); `is_symlink` 7,581/7,619 (38 missing; 99.50%); `path` 7,581/7,619 (38 missing; 99.50%); `relative_path` 7,581/7,619 (38 missing; 99.50%); `dataset_id` 38/7,619 (7,581 missing; 0.50%); `doi` 38/7,619 (7,581 missing; 0.50%); `spec_hash` 38/7,619 (7,581 missing; 0.50%) |
| `ToolVersion` | 4,142 | 10 | `id` 4,142/4,142 (0 missing; 100.00%); `tool_id` 4,142/4,142 (0 missing; 100.00%); `version_id` 4,142/4,142 (0 missing; 100.00%); `labels` 2,581/4,142 (1,561 missing; 62.31%); `op` 2,084/4,142 (2,058 missing; 50.31%); `software` 2,084/4,142 (2,058 missing; 50.31%); `container_image` 1,974/4,142 (2,168 missing; 47.66%); `version` 1,905/4,142 (2,237 missing; 45.99%); `python_module` 182/4,142 (3,960 missing; 4.39%); `python_function` 98/4,142 (4,044 missing; 2.37%) |
| `Term` | 3,228 | 4 | `id` 3,228/3,228 (0 missing; 100.00%); `labels` 3,228/3,228 (0 missing; 100.00%); `name` 3,228/3,228 (0 missing; 100.00%); `source` 3,228/3,228 (0 missing; 100.00%) |
| `Concept` | 2,336 | 23 | `id` 2,336/2,336 (0 missing; 100.00%); `name` 2,336/2,336 (0 missing; 100.00%); `labels` 2,331/2,336 (5 missing; 99.79%); `aliases` 2,321/2,336 (15 missing; 99.36%); `definition` 2,320/2,336 (16 missing; 99.32%); `source` 2,316/2,336 (20 missing; 99.14%); `label` 2,264/2,336 (72 missing; 96.92%); `concept_classes` 1,564/2,336 (772 missing; 66.95%); `synonyms` 1,505/2,336 (831 missing; 64.43%); `alias` 919/2,336 (1,417 missing; 39.34%); `citations` 919/2,336 (1,417 missing; 39.34%); `concept_class` 919/2,336 (1,417 missing; 39.34%); `contrast_links` 919/2,336 (1,417 missing; 39.34%); `creation_time` 919/2,336 (1,417 missing; 39.34%); `last_updated` 919/2,336 (1,417 missing; 39.34%); `metadata` 919/2,336 (1,417 missing; 39.34%); `related_concepts` 919/2,336 (1,417 missing; 39.34%); `is_top_concept` 752/2,336 (1,584 missing; 32.19%); `scheme` 752/2,336 (1,584 missing; 32.19%); `top_schemes` 752/2,336 (1,584 missing; 32.19%); `uri` 752/2,336 (1,584 missing; 32.19%); `primary_onvoc_confidence` 22/2,336 (2,314 missing; 0.94%); `primary_onvoc_id` 22/2,336 (2,314 missing; 0.94%) |
| `Contrast` | 2,206 | 19 | `id` 2,206/2,206 (0 missing; 100.00%); `labels` 2,206/2,206 (0 missing; 100.00%); `name` 2,206/2,206 (0 missing; 100.00%); `source` 2,206/2,206 (0 missing; 100.00%); `conditions` 1,585/2,206 (621 missing; 71.85%); `creation_time` 1,585/2,206 (621 missing; 71.85%); `last_updated` 1,585/2,206 (621 missing; 71.85%); `task_id` 1,585/2,206 (621 missing; 71.85%); `event_stamp` 1,476/2,206 (730 missing; 66.91%); `id_user` 1,476/2,206 (730 missing; 66.91%); `dataset_id` 621/2,206 (1,585 missing; 28.15%); `condition_list` 393/2,206 (1,813 missing; 17.82%); `ingested_at` 393/2,206 (1,813 missing; 17.82%); `task` 393/2,206 (1,813 missing; 17.82%); `test` 393/2,206 (1,813 missing; 17.82%); `weights` 393/2,206 (1,813 missing; 17.82%); `task_label` 228/2,206 (1,978 missing; 10.34%); `primary_onvoc_confidence` 3/2,206 (2,203 missing; 0.14%); `primary_onvoc_id` 3/2,206 (2,203 missing; 0.14%) |
| `BrainRegion` | 2,140 | 34 | `atlas` 2,140/2,140 (0 missing; 100.00%); `id` 2,140/2,140 (0 missing; 100.00%); `name` 2,140/2,140 (0 missing; 100.00%); `space` 2,140/2,140 (0 missing; 100.00%); `atlas_slug` 2,123/2,140 (17 missing; 99.21%); `labels` 2,123/2,140 (17 missing; 99.21%); `source` 2,123/2,140 (17 missing; 99.21%); `label_index` 1,344/2,140 (796 missing; 62.80%); `abbreviation` 1,327/2,140 (813 missing; 62.01%); `acronym` 1,327/2,140 (813 missing; 62.01%); `depth` 1,327/2,140 (813 missing; 62.01%); `graph_order` 1,327/2,140 (813 missing; 62.01%); `species` 1,327/2,140 (813 missing; 62.01%); `structure_id` 1,327/2,140 (813 missing; 62.01%); `structure_id_path` 1,327/2,140 (813 missing; 62.01%); `parent_structure_id` 1,326/2,140 (814 missing; 61.96%); `index` 796/2,140 (1,344 missing; 37.20%); `label_original` 796/2,140 (1,344 missing; 37.20%); `modality` 796/2,140 (1,344 missing; 37.20%); `parcellation_id` 796/2,140 (1,344 missing; 37.20%); `parcellation_slug` 796/2,140 (1,344 missing; 37.20%); `region_id` 796/2,140 (1,344 missing; 37.20%); `map_file` 727/2,140 (1,413 missing; 33.97%); `scale` 538/2,140 (1,602 missing; 25.14%); `space_resolution_mm` 524/2,140 (1,616 missing; 24.49%); `space_variant` 457/2,140 (1,683 missing; 21.36%); `hemisphere` 408/2,140 (1,732 missing; 19.07%); `n_rois` 300/2,140 (1,840 missing; 14.02%); `network` 300/2,140 (1,840 missing; 14.02%); `resolution_mm` 300/2,140 (1,840 missing; 14.02%); `yeo_network_set` 300/2,140 (1,840 missing; 14.02%); `yeo_networks` 300/2,140 (1,840 missing; 14.02%); `atlas_variant` 191/2,140 (1,949 missing; 8.93%); `roi_number` 56/2,140 (2,084 missing; 2.62%) |
| `Dataset` | 2,136 | 53 | `id` 2,136/2,136 (0 missing; 100.00%); `labels` 2,136/2,136 (0 missing; 100.00%); `name` 2,136/2,136 (0 missing; 100.00%); `aliases` 2,095/2,136 (41 missing; 98.08%); `dataset_id` 1,732/2,136 (404 missing; 81.09%); `description` 1,694/2,136 (442 missing; 79.31%); `license` 1,694/2,136 (442 missing; 79.31%); `tags` 1,694/2,136 (442 missing; 79.31%); `access_type` 1,693/2,136 (443 missing; 79.26%); `acquisitions` 1,693/2,136 (443 missing; 79.26%); `alias` 1,693/2,136 (443 missing; 79.26%); `category` 1,693/2,136 (443 missing; 79.26%); `category_source` 1,693/2,136 (443 missing; 79.26%); `created_from` 1,693/2,136 (443 missing; 79.26%); `disease_flags` 1,693/2,136 (443 missing; 79.26%); `has_derivatives` 1,693/2,136 (443 missing; 79.26%); `is_openneuro` 1,693/2,136 (443 missing; 79.26%); `modalities` 1,693/2,136 (443 missing; 79.26%); `preview_media` 1,693/2,136 (443 missing; 79.26%); `primary_url` 1,693/2,136 (443 missing; 79.26%); `search_blob` 1,693/2,136 (443 missing; 79.26%); `short_name` 1,693/2,136 (443 missing; 79.26%); `source_repo` 1,693/2,136 (443 missing; 79.26%); `source_repo_bucket` 1,693/2,136 (443 missing; 79.26%); `source_repo_id` 1,693/2,136 (443 missing; 79.26%); `species` 1,693/2,136 (443 missing; 79.26%); `tasks` 1,693/2,136 (443 missing; 79.26%); `modalities_notes` 1,595/2,136 (541 missing; 74.67%); `source_version` 1,594/2,136 (542 missing; 74.63%); `subjects_count` 713/2,136 (1,423 missing; 33.38%); `age_range` 541/2,136 (1,595 missing; 25.33%); `source` 441/2,136 (1,695 missing; 20.65%); `dataset_uuid` 402/2,136 (1,734 missing; 18.82%); `portal_uri` 402/2,136 (1,734 missing; 18.82%); `total_subjects_reported` 402/2,136 (1,734 missing; 18.82%); `sessions_count` 356/2,136 (1,780 missing; 16.67%); `primary_onvoc_confidence` 355/2,136 (1,781 missing; 16.62%); `primary_onvoc_id` 355/2,136 (1,781 missing; 16.62%); `openneuro_id` 321/2,136 (1,815 missing; 15.03%); `center` 100/2,136 (2,036 missing; 4.68%); `consortium` 99/2,136 (2,037 missing; 4.63%); `principal_investigator` 99/2,136 (2,037 missing; 4.63%); `size_human` 99/2,136 (2,037 missing; 4.63%); `doi` 38/2,136 (2,098 missing; 1.78%); `spec_hash` 38/2,136 (2,098 missing; 1.78%); `accession` 2/2,136 (2,134 missing; 0.09%); `subject_count` 2/2,136 (2,134 missing; 0.09%); `n_experiments` 1/2,136 (2,135 missing; 0.05%); `n_participants` 1/2,136 (2,135 missing; 0.05%); `provenance` 1/2,136 (2,135 missing; 0.05%); `resource_id` 1/2,136 (2,135 missing; 0.05%); `schema_version` 1/2,136 (2,135 missing; 0.05%); `url` 1/2,136 (2,135 missing; 0.05%) |
| `Tool` | 2,084 | 22 | `category` 2,084/2,084 (0 missing; 100.00%); `default_group_id` 2,084/2,084 (0 missing; 100.00%); `description` 2,084/2,084 (0 missing; 100.00%); `domain` 2,084/2,084 (0 missing; 100.00%); `exposed` 2,084/2,084 (0 missing; 100.00%); `exposure_group` 2,084/2,084 (0 missing; 100.00%); `id` 2,084/2,084 (0 missing; 100.00%); `is_default` 2,084/2,084 (0 missing; 100.00%); `name` 2,084/2,084 (0 missing; 100.00%); `op` 2,084/2,084 (0 missing; 100.00%); `op_key` 2,084/2,084 (0 missing; 100.00%); `primary_intent` 2,084/2,084 (0 missing; 100.00%); `runtime_kind` 2,084/2,084 (0 missing; 100.00%); `software` 2,084/2,084 (0 missing; 100.00%); `tool_id` 2,084/2,084 (0 missing; 100.00%); `intents` 2,078/2,084 (6 missing; 99.71%); `display_name` 2,073/2,084 (11 missing; 99.47%); `runtime` 2,073/2,084 (11 missing; 99.47%); `source` 2,073/2,084 (11 missing; 99.47%); `labels` 2,070/2,084 (14 missing; 99.33%); `version` 1,905/2,084 (179 missing; 91.41%); `kind` 1,154/2,084 (930 missing; 55.37%) |
| `Phenotype` | 1,218 | 10 | `category` 1,218/1,218 (0 missing; 100.00%); `dataset_uuid` 1,218/1,218 (0 missing; 100.00%); `id` 1,218/1,218 (0 missing; 100.00%); `labels` 1,218/1,218 (0 missing; 100.00%); `measurement_type` 1,218/1,218 (0 missing; 100.00%); `name` 1,218/1,218 (0 missing; 100.00%); `source` 1,218/1,218 (0 missing; 100.00%); `total_observations` 1,218/1,218 (0 missing; 100.00%); `value_counts` 885/1,218 (333 missing; 72.66%); `numeric_summary` 333/1,218 (885 missing; 27.34%) |
| `Citation` | 1,201 | 19 | `citation_authors` 1,201/1,201 (0 missing; 100.00%); `citation_comment` 1,201/1,201 (0 missing; 100.00%); `citation_desc` 1,201/1,201 (0 missing; 100.00%); `citation_pmid` 1,201/1,201 (0 missing; 100.00%); `citation_pubdate` 1,201/1,201 (0 missing; 100.00%); `citation_pubname` 1,201/1,201 (0 missing; 100.00%); `citation_source` 1,201/1,201 (0 missing; 100.00%); `citation_type` 1,201/1,201 (0 missing; 100.00%); `citation_url` 1,201/1,201 (0 missing; 100.00%); `id` 1,201/1,201 (0 missing; 100.00%); `labels` 1,201/1,201 (0 missing; 100.00%); `relationship` 1,201/1,201 (0 missing; 100.00%); `source` 1,201/1,201 (0 missing; 100.00%); `event_stamp` 1,116/1,201 (85 missing; 92.92%); `id_user` 1,116/1,201 (85 missing; 92.92%); `creation_time` 85/1,201 (1,116 missing; 7.08%); `doi` 85/1,201 (1,116 missing; 7.08%); `last_updated` 85/1,201 (1,116 missing; 7.08%); `name` 85/1,201 (1,116 missing; 7.08%) |
| `Subject` | 1,139 | 5 | `dataset_id` 1,139/1,139 (0 missing; 100.00%); `id` 1,139/1,139 (0 missing; 100.00%); `labels` 1,139/1,139 (0 missing; 100.00%); `source` 1,139/1,139 (0 missing; 100.00%); `subject_code` 1,139/1,139 (0 missing; 100.00%) |
| `TaskCondition` | 807 | 12 | `creation_time` 807/807 (0 missing; 100.00%); `id` 807/807 (0 missing; 100.00%); `labels` 807/807 (0 missing; 100.00%); `last_updated` 807/807 (0 missing; 100.00%); `name` 807/807 (0 missing; 100.00%); `source` 807/807 (0 missing; 100.00%); `task_id` 807/807 (0 missing; 100.00%); `relationship` 791/807 (16 missing; 98.02%); `condition_description` 662/807 (145 missing; 82.03%); `condition_text` 662/807 (145 missing; 82.03%); `event_stamp` 662/807 (145 missing; 82.03%); `id_user` 662/807 (145 missing; 82.03%) |
| `OntologyConcept` | 752 | 12 | `aliases` 752/752 (0 missing; 100.00%); `definition` 752/752 (0 missing; 100.00%); `id` 752/752 (0 missing; 100.00%); `is_top_concept` 752/752 (0 missing; 100.00%); `label` 752/752 (0 missing; 100.00%); `labels` 752/752 (0 missing; 100.00%); `name` 752/752 (0 missing; 100.00%); `scheme` 752/752 (0 missing; 100.00%); `source` 752/752 (0 missing; 100.00%); `synonyms` 752/752 (0 missing; 100.00%); `top_schemes` 752/752 (0 missing; 100.00%); `uri` 752/752 (0 missing; 100.00%) |
| `OnvocClass` | 752 | 12 | `aliases` 752/752 (0 missing; 100.00%); `definition` 752/752 (0 missing; 100.00%); `id` 752/752 (0 missing; 100.00%); `is_top_concept` 752/752 (0 missing; 100.00%); `label` 752/752 (0 missing; 100.00%); `labels` 752/752 (0 missing; 100.00%); `name` 752/752 (0 missing; 100.00%); `scheme` 752/752 (0 missing; 100.00%); `source` 752/752 (0 missing; 100.00%); `synonyms` 752/752 (0 missing; 100.00%); `top_schemes` 752/752 (0 missing; 100.00%); `uri` 752/752 (0 missing; 100.00%) |
| `GLMContrast` | 621 | 13 | `dataset_id` 621/621 (0 missing; 100.00%); `id` 621/621 (0 missing; 100.00%); `labels` 621/621 (0 missing; 100.00%); `name` 621/621 (0 missing; 100.00%); `source` 621/621 (0 missing; 100.00%); `condition_list` 393/621 (228 missing; 63.28%); `ingested_at` 393/621 (228 missing; 63.28%); `task` 393/621 (228 missing; 63.28%); `test` 393/621 (228 missing; 63.28%); `weights` 393/621 (228 missing; 63.28%); `task_label` 228/621 (393 missing; 36.72%); `primary_onvoc_confidence` 3/621 (618 missing; 0.48%); `primary_onvoc_id` 3/621 (618 missing; 0.48%) |
| `TaskIndicator` | 584 | 9 | `id` 584/584 (0 missing; 100.00%); `labels` 584/584 (0 missing; 100.00%); `relationship` 584/584 (0 missing; 100.00%); `source` 584/584 (0 missing; 100.00%); `task_id` 584/584 (0 missing; 100.00%); `type` 584/584 (0 missing; 100.00%); `creation_time` 2/584 (582 missing; 0.34%); `last_updated` 2/584 (582 missing; 0.34%); `name` 2/584 (582 missing; 0.34%) |
| `SubjectGroup` | 402 | 9 | `dataset_uuid` 402/402 (0 missing; 100.00%); `id` 402/402 (0 missing; 100.00%); `imaging_sessions` 402/402 (0 missing; 100.00%); `labels` 402/402 (0 missing; 100.00%); `name` 402/402 (0 missing; 100.00%); `phenotypic_sessions` 402/402 (0 missing; 100.00%); `records_protected` 402/402 (0 missing; 100.00%); `source` 402/402 (0 missing; 100.00%); `unique_subjects` 402/402 (0 missing; 100.00%) |
| `Condition` | 310 | 8 | `dataset_id` 310/310 (0 missing; 100.00%); `id` 310/310 (0 missing; 100.00%); `ingested_at` 310/310 (0 missing; 100.00%); `labels` 310/310 (0 missing; 100.00%); `name` 310/310 (0 missing; 100.00%); `order_index` 310/310 (0 missing; 100.00%); `source` 310/310 (0 missing; 100.00%); `task` 310/310 (0 missing; 100.00%) |
| `GLMDesignPrior` | 216 | 12 | `axes` 216/216 (0 missing; 100.00%); `confounds` 216/216 (0 missing; 100.00%); `coverage` 216/216 (0 missing; 100.00%); `high_pass` 216/216 (0 missing; 100.00%); `hrf_basis` 216/216 (0 missing; 100.00%); `id` 216/216 (0 missing; 100.00%); `labels` 216/216 (0 missing; 100.00%); `n_specs` 216/216 (0 missing; 100.00%); `source` 216/216 (0 missing; 100.00%); `support` 216/216 (0 missing; 100.00%); `task` 216/216 (0 missing; 100.00%); `dataset_id` 110/216 (106 missing; 50.93%) |
| `Author` | 172 | 6 | `id` 172/172 (0 missing; 100.00%); `labels` 172/172 (0 missing; 100.00%); `name` 172/172 (0 missing; 100.00%); `roles` 172/172 (0 missing; 100.00%); `source` 172/172 (0 missing; 100.00%); `orcid` 141/172 (31 missing; 81.98%) |
| `TaskFamily` | 138 | 11 | `id` 138/138 (0 missing; 100.00%); `name` 138/138 (0 missing; 100.00%); `labels` 43/138 (95 missing; 31.16%); `source` 20/138 (118 missing; 14.49%); `family_id` 15/138 (123 missing; 10.87%); `family_label` 15/138 (123 missing; 10.87%); `family_description` 14/138 (124 missing; 10.14%); `schema_version` 14/138 (124 missing; 10.14%); `ontology_source` 9/138 (129 missing; 6.52%); `subfamily_id` 9/138 (129 missing; 6.52%); `subfamily_label` 9/138 (129 missing; 6.52%) |
| `Institution` | 119 | 6 | `country` 119/119 (0 missing; 100.00%); `id` 119/119 (0 missing; 100.00%); `labels` 119/119 (0 missing; 100.00%); `name` 119/119 (0 missing; 100.00%); `ror` 119/119 (0 missing; 100.00%); `source` 119/119 (0 missing; 100.00%) |
| `TaskSpec` | 110 | 16 | `dataset` 110/110 (0 missing; 100.00%); `id` 110/110 (0 missing; 100.00%); `labels` 110/110 (0 missing; 100.00%); `name` 110/110 (0 missing; 100.00%); `source` 110/110 (0 missing; 100.00%); `aliases` 72/110 (38 missing; 65.45%); `bids_model_version` 72/110 (38 missing; 65.45%); `column_names` 72/110 (38 missing; 65.45%); `dummy_volumes` 72/110 (38 missing; 65.45%); `group_by` 72/110 (38 missing; 65.45%); `ingested_at` 72/110 (38 missing; 65.45%); `model_name` 72/110 (38 missing; 65.45%); `n_subjects` 72/110 (38 missing; 65.45%); `task_metadata_json` 72/110 (38 missing; 65.45%); `bold_volumes` 70/110 (40 missing; 63.64%); `cite_links` 64/110 (46 missing; 58.18%) |
| `ReviewSchemaField` | 106 | 3 | `field_path` 106/106 (0 missing; 100.00%); `id` 106/106 (0 missing; 100.00%); `labels` 106/106 (0 missing; 100.00%) |
| `ResourceType` | 102 | 3 | `id` 102/102 (0 missing; 100.00%); `name` 102/102 (0 missing; 100.00%); `labels` 83/102 (19 missing; 81.37%) |
| `ToolFamily` | 96 | 3 | `id` 96/96 (0 missing; 100.00%); `labels` 96/96 (0 missing; 100.00%); `name` 96/96 (0 missing; 100.00%) |
| `Repository` | 88 | 3 | `id` 88/88 (0 missing; 100.00%); `labels` 88/88 (0 missing; 100.00%); `name` 88/88 (0 missing; 100.00%) |
| `BrainAnnotation` | 86 | 20 | `dataset` 86/86 (0 missing; 100.00%); `density` 86/86 (0 missing; 100.00%); `description` 86/86 (0 missing; 100.00%); `files` 86/86 (0 missing; 100.00%); `formats` 86/86 (0 missing; 100.00%); `id` 86/86 (0 missing; 100.00%); `labels` 86/86 (0 missing; 100.00%); `primary_references` 86/86 (0 missing; 100.00%); `restricted` 86/86 (0 missing; 100.00%); `source` 86/86 (0 missing; 100.00%); `space` 86/86 (0 missing; 100.00%); `summary` 86/86 (0 missing; 100.00%); `tags` 86/86 (0 missing; 100.00%); `urls` 86/86 (0 missing; 100.00%); `sample_size` 78/86 (8 missing; 90.70%); `age_mean` 54/86 (32 missing; 62.79%); `age_sd` 54/86 (32 missing; 62.79%); `resolution` 47/86 (39 missing; 54.65%); `hemispheres` 39/86 (47 missing; 45.35%); `secondary_references` 10/86 (76 missing; 11.63%) |
| `ReviewImplementationRule` | 80 | 20 | `action` 80/80 (0 missing; 100.00%); `applies_to` 80/80 (0 missing; 100.00%); `description` 80/80 (0 missing; 100.00%); `id` 80/80 (0 missing; 100.00%); `labels` 80/80 (0 missing; 100.00%); `message` 80/80 (0 missing; 100.00%); `reason_tags` 80/80 (0 missing; 100.00%); `review_mode` 80/80 (0 missing; 100.00%); `rule_id` 80/80 (0 missing; 100.00%); `severity` 80/80 (0 missing; 100.00%); `source_path` 80/80 (0 missing; 100.00%); `stage` 80/80 (0 missing; 100.00%); `suggested_fix` 80/80 (0 missing; 100.00%); `tags` 80/80 (0 missing; 100.00%); `check_fn` 61/80 (19 missing; 76.25%); `comparator` 26/80 (54 missing; 32.50%); `metric` 26/80 (54 missing; 32.50%); `threshold` 26/80 (54 missing; 32.50%); `tool_filter` 9/80 (71 missing; 11.25%); `kg_lookup` 1/80 (79 missing; 1.25%) |
| `ModelSpec` | 78 | 18 | `dataset_id` 78/78 (0 missing; 100.00%); `hash` 78/78 (0 missing; 100.00%); `id` 78/78 (0 missing; 100.00%); `labels` 78/78 (0 missing; 100.00%); `path` 78/78 (0 missing; 100.00%); `source` 78/78 (0 missing; 100.00%); `task` 78/78 (0 missing; 100.00%); `bids_model_version` 72/78 (6 missing; 92.31%); `convolve_input` 72/78 (6 missing; 92.31%); `fitlins_params_json` 72/78 (6 missing; 92.31%); `group_by` 72/78 (6 missing; 92.31%); `hrf_model` 72/78 (6 missing; 92.31%); `ingested_at` 72/78 (6 missing; 92.31%); `model_name` 72/78 (6 missing; 92.31%); `model_type` 72/78 (6 missing; 92.31%); `confounds_terms` 71/78 (7 missing; 91.03%); `hrf_derivative` 15/78 (63 missing; 19.23%); `hrf_dispersion` 7/78 (71 missing; 8.97%) |
| `Experiment` | 76 | 34 | `dataset_id` 76/76 (0 missing; 100.00%); `description` 76/76 (0 missing; 100.00%); `experiment_id` 76/76 (0 missing; 100.00%); `experiment_name` 76/76 (0 missing; 100.00%); `experiment_path` 76/76 (0 missing; 100.00%); `experiment_slug` 76/76 (0 missing; 100.00%); `id` 76/76 (0 missing; 100.00%); `labels` 76/76 (0 missing; 100.00%); `n_participants` 76/76 (0 missing; 100.00%); `n_trials` 76/76 (0 missing; 100.00%); `name` 76/76 (0 missing; 100.00%); `provenance` 76/76 (0 missing; 100.00%); `raw` 76/76 (0 missing; 100.00%); `schema_version` 76/76 (0 missing; 100.00%); `source` 76/76 (0 missing; 100.00%); `task_label` 76/76 (0 missing; 100.00%); `task_labels` 76/76 (0 missing; 100.00%); `task_ontology` 76/76 (0 missing; 100.00%); `task_ontology_evidence` 76/76 (0 missing; 100.00%); `task_families` 62/76 (14 missing; 81.58%); `task_family_id` 35/76 (41 missing; 46.05%); `task_family_label` 35/76 (41 missing; 46.05%); `task_ontology_match_field` 35/76 (41 missing; 46.05%); `task_ontology_match_method` 35/76 (41 missing; 46.05%); `task_ontology_match_score` 35/76 (41 missing; 46.05%); `task_ontology_match_text` 35/76 (41 missing; 46.05%); `task_paradigm_name` 35/76 (41 missing; 46.05%); `task_paradigms` 35/76 (41 missing; 46.05%); `task_subfamilies` 35/76 (41 missing; 46.05%); `task_subfamily_id` 35/76 (41 missing; 46.05%); `task_subfamily_label` 35/76 (41 missing; 46.05%); `canonical_task_cogat_id` 5/76 (71 missing; 6.58%); `canonical_task_id` 5/76 (71 missing; 6.58%); `canonical_task_label` 5/76 (71 missing; 6.58%) |
| `Psych101Experiment` | 76 | 34 | `dataset_id` 76/76 (0 missing; 100.00%); `description` 76/76 (0 missing; 100.00%); `experiment_id` 76/76 (0 missing; 100.00%); `experiment_name` 76/76 (0 missing; 100.00%); `experiment_path` 76/76 (0 missing; 100.00%); `experiment_slug` 76/76 (0 missing; 100.00%); `id` 76/76 (0 missing; 100.00%); `labels` 76/76 (0 missing; 100.00%); `n_participants` 76/76 (0 missing; 100.00%); `n_trials` 76/76 (0 missing; 100.00%); `name` 76/76 (0 missing; 100.00%); `provenance` 76/76 (0 missing; 100.00%); `raw` 76/76 (0 missing; 100.00%); `schema_version` 76/76 (0 missing; 100.00%); `source` 76/76 (0 missing; 100.00%); `task_label` 76/76 (0 missing; 100.00%); `task_labels` 76/76 (0 missing; 100.00%); `task_ontology` 76/76 (0 missing; 100.00%); `task_ontology_evidence` 76/76 (0 missing; 100.00%); `task_families` 62/76 (14 missing; 81.58%); `task_family_id` 35/76 (41 missing; 46.05%); `task_family_label` 35/76 (41 missing; 46.05%); `task_ontology_match_field` 35/76 (41 missing; 46.05%); `task_ontology_match_method` 35/76 (41 missing; 46.05%); `task_ontology_match_score` 35/76 (41 missing; 46.05%); `task_ontology_match_text` 35/76 (41 missing; 46.05%); `task_paradigm_name` 35/76 (41 missing; 46.05%); `task_paradigms` 35/76 (41 missing; 46.05%); `task_subfamilies` 35/76 (41 missing; 46.05%); `task_subfamily_id` 35/76 (41 missing; 46.05%); `task_subfamily_label` 35/76 (41 missing; 46.05%); `canonical_task_cogat_id` 5/76 (71 missing; 6.58%); `canonical_task_id` 5/76 (71 missing; 6.58%); `canonical_task_label` 5/76 (71 missing; 6.58%) |
| `TaskAnalysis` | 72 | 21 | `bids_model_version` 72/72 (0 missing; 100.00%); `convolve_input` 72/72 (0 missing; 100.00%); `dataset_id` 72/72 (0 missing; 100.00%); `fitlins_params_json` 72/72 (0 missing; 100.00%); `group_by` 72/72 (0 missing; 100.00%); `hrf_model` 72/72 (0 missing; 100.00%); `id` 72/72 (0 missing; 100.00%); `ingested_at` 72/72 (0 missing; 100.00%); `labels` 72/72 (0 missing; 100.00%); `model_name` 72/72 (0 missing; 100.00%); `model_type` 72/72 (0 missing; 100.00%); `n_subjects` 72/72 (0 missing; 100.00%); `source` 72/72 (0 missing; 100.00%); `subjects` 72/72 (0 missing; 100.00%); `task` 72/72 (0 missing; 100.00%); `task_metadata_json` 72/72 (0 missing; 100.00%); `confounds_terms` 71/72 (1 missing; 98.61%); `hrf_derivative` 15/72 (57 missing; 20.83%); `primary_onvoc_confidence` 10/72 (62 missing; 13.89%); `primary_onvoc_id` 10/72 (62 missing; 13.89%); `hrf_dispersion` 7/72 (65 missing; 9.72%) |
| `ReviewRule` | 71 | 10 | `description` 71/71 (0 missing; 100.00%); `detection` 71/71 (0 missing; 100.00%); `exemptions` 71/71 (0 missing; 100.00%); `id` 71/71 (0 missing; 100.00%); `implementation_rule_ids` 71/71 (0 missing; 100.00%); `labels` 71/71 (0 missing; 100.00%); `lifecycle_status` 71/71 (0 missing; 100.00%); `rule_id` 71/71 (0 missing; 100.00%); `severity` 71/71 (0 missing; 100.00%); `novelty` 3/71 (68 missing; 4.23%) |
| `ReviewCalibrationCase` | 60 | 6 | `case_id` 60/60 (0 missing; 100.00%); `id` 60/60 (0 missing; 100.00%); `labels` 60/60 (0 missing; 100.00%); `scenario` 60/60 (0 missing; 100.00%); `severity` 60/60 (0 missing; 100.00%); `novelty` 4/60 (56 missing; 6.67%) |
| `StatMap` | 60 | 13 | `cognitive_paradigm_cogatlas` 60/60 (0 missing; 100.00%); `collection_id` 60/60 (0 missing; 100.00%); `collection_name` 60/60 (0 missing; 100.00%); `description` 60/60 (0 missing; 100.00%); `doi` 60/60 (0 missing; 100.00%); `file_url` 60/60 (0 missing; 100.00%); `id` 60/60 (0 missing; 100.00%); `labels` 60/60 (0 missing; 100.00%); `map_type` 60/60 (0 missing; 100.00%); `name` 60/60 (0 missing; 100.00%); `source` 60/60 (0 missing; 100.00%); `analysis_level` 36/60 (24 missing; 60.00%); `cognitive_contrast_cogatlas` 9/60 (51 missing; 15.00%) |
| `Consortium` | 38 | 3 | `id` 38/38 (0 missing; 100.00%); `labels` 38/38 (0 missing; 100.00%); `name` 38/38 (0 missing; 100.00%) |
| `Study` | 33 | 4 | `doi` 33/33 (0 missing; 100.00%); `id` 33/33 (0 missing; 100.00%); `labels` 33/33 (0 missing; 100.00%); `title` 33/33 (0 missing; 100.00%) |
| `Modality` | 28 | 3 | `id` 28/28 (0 missing; 100.00%); `name` 28/28 (0 missing; 100.00%); `labels` 24/28 (4 missing; 85.71%) |
| `Parcellation` | 28 | 15 | `id` 26/28 (2 missing; 92.86%); `name` 11/28 (17 missing; 39.29%); `space` 10/28 (18 missing; 35.71%); `labels` 8/28 (20 missing; 28.57%); `modality` 8/28 (20 missing; 28.57%); `slug` 8/28 (20 missing; 28.57%); `source` 8/28 (20 missing; 28.57%); `map_files` 6/28 (22 missing; 21.43%); `space_resolution_mm` 6/28 (22 missing; 21.43%); `space_variant` 5/28 (23 missing; 17.86%); `scale` 4/28 (24 missing; 14.29%); `variant` 3/28 (25 missing; 10.71%); `resolution_mm` 2/28 (26 missing; 7.14%); `sha256` 2/28 (26 missing; 7.14%); `source_path` 2/28 (26 missing; 7.14%) |
| `Battery` | 27 | 15 | `collection_alias` 27/27 (0 missing; 100.00%); `collection_date_introduced` 27/27 (0 missing; 100.00%); `collection_description` 27/27 (0 missing; 100.00%); `collection_publisher` 27/27 (0 missing; 100.00%); `creation_time` 27/27 (0 missing; 100.00%); `event_stamp` 27/27 (0 missing; 100.00%); `flag_for_curator` 27/27 (0 missing; 100.00%); `id` 27/27 (0 missing; 100.00%); `id_user` 27/27 (0 missing; 100.00%); `labels` 27/27 (0 missing; 100.00%); `last_updated` 27/27 (0 missing; 100.00%); `name` 27/27 (0 missing; 100.00%); `relationship` 27/27 (0 missing; 100.00%); `source` 27/27 (0 missing; 100.00%); `website` 27/27 (0 missing; 100.00%) |
| `Parcel` | 26 | 4 | `index` 26/26 (0 missing; 100.00%); `label_raw` 26/26 (0 missing; 100.00%); `name` 26/26 (0 missing; 100.00%); `parcellation` 26/26 (0 missing; 100.00%) |
| `Finding` | 16 | 4 | `confidence` 16/16 (0 missing; 100.00%); `created_at` 16/16 (0 missing; 100.00%); `description` 16/16 (0 missing; 100.00%); `source_tool` 16/16 (0 missing; 100.00%) |
| `Species` | 14 | 3 | `id` 14/14 (0 missing; 100.00%); `labels` 14/14 (0 missing; 100.00%); `name` 14/14 (0 missing; 100.00%) |
| `ReviewRuleGroup` | 13 | 5 | `id` 13/13 (0 missing; 100.00%); `key` 13/13 (0 missing; 100.00%); `label` 13/13 (0 missing; 100.00%); `labels` 13/13 (0 missing; 100.00%); `section` 13/13 (0 missing; 100.00%) |
| `IngestionRun` | 12 | 15 | `config_hash` 12/12 (0 missing; 100.00%); `db_name` 12/12 (0 missing; 100.00%); `db_uri` 12/12 (0 missing; 100.00%); `duration_sec` 12/12 (0 missing; 100.00%); `errors` 12/12 (0 missing; 100.00%); `finished_at` 12/12 (0 missing; 100.00%); `git_sha` 12/12 (0 missing; 100.00%); `id` 12/12 (0 missing; 100.00%); `labels` 12/12 (0 missing; 100.00%); `run_id` 12/12 (0 missing; 100.00%); `sources` 12/12 (0 missing; 100.00%); `started_at` 12/12 (0 missing; 100.00%); `total_entities` 12/12 (0 missing; 100.00%); `total_relationships` 12/12 (0 missing; 100.00%); `neurovault_summary` 9/12 (3 missing; 75.00%) |
| `ConceptClass` | 10 | 9 | `creation_time` 10/10 (0 missing; 100.00%); `description` 10/10 (0 missing; 100.00%); `display_order` 10/10 (0 missing; 100.00%); `id` 10/10 (0 missing; 100.00%); `labels` 10/10 (0 missing; 100.00%); `last_updated` 10/10 (0 missing; 100.00%); `name` 10/10 (0 missing; 100.00%); `relationship` 10/10 (0 missing; 100.00%); `source` 10/10 (0 missing; 100.00%) |
| `Process` | 10 | 9 | `creation_time` 10/10 (0 missing; 100.00%); `description` 10/10 (0 missing; 100.00%); `display_order` 10/10 (0 missing; 100.00%); `id` 10/10 (0 missing; 100.00%); `labels` 10/10 (0 missing; 100.00%); `last_updated` 10/10 (0 missing; 100.00%); `name` 10/10 (0 missing; 100.00%); `relationship` 10/10 (0 missing; 100.00%); `source` 10/10 (0 missing; 100.00%) |
| `TemplateSpace` | 10 | 11 | `id` 10/10 (0 missing; 100.00%); `name` 10/10 (0 missing; 100.00%); `labels` 8/10 (2 missing; 80.00%); `source` 8/10 (2 missing; 80.00%); `modality` 6/10 (4 missing; 60.00%); `variant` 5/10 (5 missing; 50.00%); `resolution_mm` 4/10 (6 missing; 40.00%); `atlas` 1/10 (9 missing; 10.00%); `atlas_slug` 1/10 (9 missing; 10.00%); `space` 1/10 (9 missing; 10.00%); `species` 1/10 (9 missing; 10.00%) |
| `Region` | 8 | 4 | `id` 8/8 (0 missing; 100.00%); `labels` 8/8 (0 missing; 100.00%); `name` 8/8 (0 missing; 100.00%); `abbreviation` 6/8 (2 missing; 75.00%) |
| `ReviewReasonTag` | 8 | 4 | `description` 8/8 (0 missing; 100.00%); `id` 8/8 (0 missing; 100.00%); `key` 8/8 (0 missing; 100.00%); `labels` 8/8 (0 missing; 100.00%) |
| `GLMVariant` | 7 | 15 | `contrast` 7/7 (0 missing; 100.00%); `decision_points` 7/7 (0 missing; 100.00%); `fitlins_params` 7/7 (0 missing; 100.00%); `id` 7/7 (0 missing; 100.00%); `labels` 7/7 (0 missing; 100.00%); `model_id` 7/7 (0 missing; 100.00%); `model_x` 7/7 (0 missing; 100.00%); `spec_path` 7/7 (0 missing; 100.00%); `spec_sha256` 7/7 (0 missing; 100.00%); `status` 7/7 (0 missing; 100.00%); `literature_evidence` 6/7 (1 missing; 85.71%); `rationale` 6/7 (1 missing; 85.71%); `references` 6/7 (1 missing; 85.71%); `selection_reason` 6/7 (1 missing; 85.71%); `variant_id` 6/7 (1 missing; 85.71%) |
| `ReviewPolicyDecision` | 6 | 6 | `decision` 6/6 (0 missing; 100.00%); `id` 6/6 (0 missing; 100.00%); `key` 6/6 (0 missing; 100.00%); `labels` 6/6 (0 missing; 100.00%); `question` 6/6 (0 missing; 100.00%); `rationale` 6/6 (0 missing; 100.00%) |
| `ReviewLifecycleStatus` | 5 | 4 | `description` 5/5 (0 missing; 100.00%); `id` 5/5 (0 missing; 100.00%); `key` 5/5 (0 missing; 100.00%); `labels` 5/5 (0 missing; 100.00%) |
| `ReviewSensitivityTemplate` | 5 | 5 | `choice` 5/5 (0 missing; 100.00%); `id` 5/5 (0 missing; 100.00%); `key` 5/5 (0 missing; 100.00%); `labels` 5/5 (0 missing; 100.00%); `minimum_requirement` 5/5 (0 missing; 100.00%) |
| `ReviewValidityLayer` | 5 | 5 | `id` 5/5 (0 missing; 100.00%); `key` 5/5 (0 missing; 100.00%); `label` 5/5 (0 missing; 100.00%); `labels` 5/5 (0 missing; 100.00%); `scope` 5/5 (0 missing; 100.00%) |
| `ExecutionFailure` | 4 | 17 | `created_at` 4/4 (0 missing; 100.00%); `error_category` 4/4 (0 missing; 100.00%); `error_message` 4/4 (0 missing; 100.00%); `failure_id` 4/4 (0 missing; 100.00%); `plan_id` 4/4 (0 missing; 100.00%); `run_id` 4/4 (0 missing; 100.00%); `step_id` 4/4 (0 missing; 100.00%); `tool_id` 4/4 (0 missing; 100.00%); `updated_at` 4/4 (0 missing; 100.00%); `dataset_id` 3/4 (1 missing; 75.00%); `task_family` 3/4 (1 missing; 75.00%); `error_taxonomy` 1/4 (3 missing; 25.00%); `is_retryable` 1/4 (3 missing; 25.00%); `recovered` 1/4 (3 missing; 25.00%); `recovery_action` 1/4 (3 missing; 25.00%); `recovery_actions` 1/4 (3 missing; 25.00%); `tool_version_id` 1/4 (3 missing; 25.00%) |
| `Run` | 4 | 1 | `id` 4/4 (0 missing; 100.00%) |
| `Atlas` | 2 | 10 | `name` 2/2 (0 missing; 100.00%); `source` 2/2 (0 missing; 100.00%); `atlas` 1/2 (1 missing; 50.00%); `atlas_slug` 1/2 (1 missing; 50.00%); `id` 1/2 (1 missing; 50.00%); `labels` 1/2 (1 missing; 50.00%); `modality` 1/2 (1 missing; 50.00%); `short_name` 1/2 (1 missing; 50.00%); `space` 1/2 (1 missing; 50.00%); `species` 1/2 (1 missing; 50.00%) |
| `ReviewSeverity` | 2 | 5 | `default_action` 2/2 (0 missing; 100.00%); `description` 2/2 (0 missing; 100.00%); `id` 2/2 (0 missing; 100.00%); `key` 2/2 (0 missing; 100.00%); `labels` 2/2 (0 missing; 100.00%) |
| `GLMRun` | 1 | 13 | `analysis_level` 1/1 (0 missing; 100.00%); `bids_root` 1/1 (0 missing; 100.00%); `created_at` 1/1 (0 missing; 100.00%); `dataset_id` 1/1 (0 missing; 100.00%); `derivatives_root` 1/1 (0 missing; 100.00%); `execute` 1/1 (0 missing; 100.00%); `id` 1/1 (0 missing; 100.00%); `k` 1/1 (0 missing; 100.00%); `labels` 1/1 (0 missing; 100.00%); `provenance_path` 1/1 (0 missing; 100.00%); `runtime` 1/1 (0 missing; 100.00%); `seed` 1/1 (0 missing; 100.00%); `task` 1/1 (0 missing; 100.00%) |
| `Psych101Dataset` | 1 | 13 | `dataset_id` 1/1 (0 missing; 100.00%); `description` 1/1 (0 missing; 100.00%); `id` 1/1 (0 missing; 100.00%); `labels` 1/1 (0 missing; 100.00%); `license` 1/1 (0 missing; 100.00%); `n_experiments` 1/1 (0 missing; 100.00%); `n_participants` 1/1 (0 missing; 100.00%); `name` 1/1 (0 missing; 100.00%); `provenance` 1/1 (0 missing; 100.00%); `schema_version` 1/1 (0 missing; 100.00%); `source` 1/1 (0 missing; 100.00%); `tags` 1/1 (0 missing; 100.00%); `url` 1/1 (0 missing; 100.00%) |
| `ResultSummary` | 1 | 7 | `edges_cypher` 1/1 (0 missing; 100.00%); `edges_path` 1/1 (0 missing; 100.00%); `id` 1/1 (0 missing; 100.00%); `labels` 1/1 (0 missing; 100.00%); `robustness_json` 1/1 (0 missing; 100.00%); `robustness_md` 1/1 (0 missing; 100.00%); `summary_path` 1/1 (0 missing; 100.00%) |
| `ReviewImplementationRuleCatalog` | 1 | 6 | `catalog_id` 1/1 (0 missing; 100.00%); `id` 1/1 (0 missing; 100.00%); `labels` 1/1 (0 missing; 100.00%); `rule_count` 1/1 (0 missing; 100.00%); `source_path` 1/1 (0 missing; 100.00%); `title` 1/1 (0 missing; 100.00%) |
| `ReviewPositiveModifier` | 1 | 6 | `description` 1/1 (0 missing; 100.00%); `effect` 1/1 (0 missing; 100.00%); `id` 1/1 (0 missing; 100.00%); `key` 1/1 (0 missing; 100.00%); `labels` 1/1 (0 missing; 100.00%); `metadata_fields` 1/1 (0 missing; 100.00%) |
| `ReviewRuleRegistry` | 1 | 9 | `document_version` 1/1 (0 missing; 100.00%); `execution_boundary` 1/1 (0 missing; 100.00%); `id` 1/1 (0 missing; 100.00%); `labels` 1/1 (0 missing; 100.00%); `registry_id` 1/1 (0 missing; 100.00%); `scope` 1/1 (0 missing; 100.00%); `source_document_type` 1/1 (0 missing; 100.00%); `title` 1/1 (0 missing; 100.00%); `version` 1/1 (0 missing; 100.00%) |
| `ToolEvidence` | 1 | 11 | `created_at` 1/1 (0 missing; 100.00%); `dataset_family` 1/1 (0 missing; 100.00%); `dataset_id` 1/1 (0 missing; 100.00%); `fail_count` 1/1 (0 missing; 100.00%); `failure_categories` 1/1 (0 missing; 100.00%); `latency_ms_samples` 1/1 (0 missing; 100.00%); `success_count` 1/1 (0 missing; 100.00%); `task_family` 1/1 (0 missing; 100.00%); `tool_id` 1/1 (0 missing; 100.00%); `tool_version` 1/1 (0 missing; 100.00%); `updated_at` 1/1 (0 missing; 100.00%) |

### Relationship Property Coverage
Format: `property present/edge_count (missing; present%)`.
| Relationship type | Edges | Property count | Property coverage values |
|---|---|---|---|
| `BELONGS_TO` | 1,077,573 | 1 | `source` 1,077,356/1,077,573 (217 missing; 99.98%) |
| `HAS_COORDINATE` | 447,499 | 1 | `source` 447,499/447,499 (0 missing; 100.00%) |
| `HAS_TERM` | 358,050 | 4 | `rank` 358,050/358,050 (0 missing; 100.00%); `section` 358,050/358,050 (0 missing; 100.00%); `source` 358,050/358,050 (0 missing; 100.00%); `weight` 358,050/358,050 (0 missing; 100.00%) |
| `IN_REGION` | 121,261 | 8 | `atlas` 121,261/121,261 (0 missing; 100.00%); `edge_source` 121,261/121,261 (0 missing; 100.00%); `etl_version` 121,261/121,261 (0 missing; 100.00%); `measure` 121,261/121,261 (0 missing; 100.00%); `n_vox` 121,261/121,261 (0 missing; 100.00%); `pct_active` 121,261/121,261 (0 missing; 100.00%); `weight` 121,261/121,261 (0 missing; 100.00%); `z_thr` 121,261/121,261 (0 missing; 100.00%) |
| `ABOUT` | 75,922 | 9 | `confidence` 75,922/75,922 (0 missing; 100.00%); `created_at` 75,922/75,922 (0 missing; 100.00%); `source` 75,922/75,922 (0 missing; 100.00%); `match_terms` 75,888/75,922 (34 missing; 99.96%); `path_modes` 1,025/75,922 (74,897 missing; 1.35%); `path_support` 1,025/75,922 (74,897 missing; 1.35%); `updated_at` 1,025/75,922 (74,897 missing; 1.35%); `confidence_tier` 34/75,922 (75,888 missing; 0.04%); `method` 34/75,922 (75,888 missing; 0.04%) |
| `IN_ONVOC` | 63,160 | 6 | `confidence` 63,160/63,160 (0 missing; 100.00%); `source` 63,160/63,160 (0 missing; 100.00%); `evidence_json` 34,445/63,160 (28,715 missing; 54.54%); `method` 34,445/63,160 (28,715 missing; 54.54%); `created_at` 28,715/63,160 (34,445 missing; 45.46%); `match_terms` 28,715/63,160 (34,445 missing; 45.46%) |
| `IN_DOMAIN` | 52,117 | 3 | `confidence` 52,117/52,117 (0 missing; 100.00%); `method` 52,117/52,117 (0 missing; 100.00%); `source` 52,117/52,117 (0 missing; 100.00%) |
| `IN_SPACE` | 35,199 | 2 | `source` 35,189/35,199 (10 missing; 99.97%); `atlas` 1/35,199 (35,198 missing; 0.00%) |
| `COMPUTED_WITH` | 30,880 | 12 | `computed_at` 30,880/30,880 (0 missing; 100.00%); `confidence` 30,880/30,880 (0 missing; 100.00%); `confidence_components` 30,880/30,880 (0 missing; 100.00%); `confidence_version` 30,880/30,880 (0 missing; 100.00%); `evidence_type` 30,880/30,880 (0 missing; 100.00%); `evidence_type_diversity` 30,880/30,880 (0 missing; 100.00%); `prov_base_conf` 30,880/30,880 (0 missing; 100.00%); `prov_source` 30,880/30,880 (0 missing; 100.00%); `source` 30,880/30,880 (0 missing; 100.00%); `source_diversity` 30,880/30,880 (0 missing; 100.00%); `support_count_raw` 30,880/30,880 (0 missing; 100.00%); `support_count_unique` 30,880/30,880 (0 missing; 100.00%) |
| `GENERATED_FROM` | 30,880 | 12 | `computed_at` 30,880/30,880 (0 missing; 100.00%); `confidence` 30,880/30,880 (0 missing; 100.00%); `confidence_components` 30,880/30,880 (0 missing; 100.00%); `confidence_version` 30,880/30,880 (0 missing; 100.00%); `evidence_type` 30,880/30,880 (0 missing; 100.00%); `evidence_type_diversity` 30,880/30,880 (0 missing; 100.00%); `prov_base_conf` 30,880/30,880 (0 missing; 100.00%); `prov_source` 30,880/30,880 (0 missing; 100.00%); `source` 30,880/30,880 (0 missing; 100.00%); `source_diversity` 30,880/30,880 (0 missing; 100.00%); `support_count_raw` 30,880/30,880 (0 missing; 100.00%); `support_count_unique` 30,880/30,880 (0 missing; 100.00%) |
| `DERIVED_FROM` | 30,163 | 15 | `computed_at` 30,163/30,163 (0 missing; 100.00%); `confidence` 30,163/30,163 (0 missing; 100.00%); `confidence_components` 30,163/30,163 (0 missing; 100.00%); `confidence_version` 30,163/30,163 (0 missing; 100.00%); `evidence_type` 30,163/30,163 (0 missing; 100.00%); `evidence_type_diversity` 30,163/30,163 (0 missing; 100.00%); `prov_base_conf` 30,163/30,163 (0 missing; 100.00%); `source_diversity` 30,163/30,163 (0 missing; 100.00%); `support_count_raw` 30,163/30,163 (0 missing; 100.00%); `support_count_unique` 30,163/30,163 (0 missing; 100.00%); `prov_source` 30,120/30,163 (43 missing; 99.86%); `source` 30,120/30,163 (43 missing; 99.86%); `method` 43/30,163 (30,120 missing; 0.14%); `prov_method` 43/30,163 (30,120 missing; 0.14%); `provenance` 43/30,163 (30,120 missing; 0.14%) |
| `MAPS_TO` | 17,667 | 30 | `confidence` 17,667/17,667 (0 missing; 100.00%); `computed_at` 17,652/17,667 (15 missing; 99.92%); `evidence_type` 17,652/17,667 (15 missing; 99.92%); `evidence_type_diversity` 17,652/17,667 (15 missing; 99.92%); `prov_base_conf` 17,652/17,667 (15 missing; 99.92%); `source_diversity` 17,652/17,667 (15 missing; 99.92%); `support_count_raw` 17,652/17,667 (15 missing; 99.92%); `support_count_unique` 17,652/17,667 (15 missing; 99.92%); `confidence_components` 12,020/17,667 (5,647 missing; 68.04%); `confidence_version` 12,020/17,667 (5,647 missing; 68.04%); `prov_source` 9,368/17,667 (8,299 missing; 53.03%); `source` 9,180/17,667 (8,487 missing; 51.96%); `canonical_id` 9,158/17,667 (8,509 missing; 51.84%); `match_method` 9,158/17,667 (8,509 missing; 51.84%); `prov_method` 8,509/17,667 (9,158 missing; 48.16%); `method` 8,306/17,667 (9,361 missing; 47.01%); `created_at` 8,284/17,667 (9,383 missing; 46.89%); `created_by` 8,284/17,667 (9,383 missing; 46.89%); `source_load` 8,284/17,667 (9,383 missing; 46.89%); `match_config_hash` 7,917/17,667 (9,750 missing; 44.81%); `match_profile` 7,917/17,667 (9,750 missing; 44.81%); `match_version` 7,917/17,667 (9,750 missing; 44.81%); `strategy` 7,606/17,667 (10,061 missing; 43.05%); `timestamp` 7,606/17,667 (10,061 missing; 43.05%); `match_provenance` 4,219/17,667 (13,448 missing; 23.88%); `link_type` 678/17,667 (16,989 missing; 3.84%); `normalized_name` 203/17,667 (17,464 missing; 1.15%); `canonical_label` 15/17,667 (17,652 missing; 0.08%); `experiment_id` 15/17,667 (17,652 missing; 0.08%); `parameters_json` 7/17,667 (17,660 missing; 0.04%) |
| `HAS_RESOURCE` | 14,728 | 1 | `source` 14,728/14,728 (0 missing; 100.00%) |
| `HAS_TEXT_EMBEDDING` | 12,958 | 3 | `kind` 12,958/12,958 (0 missing; 100.00%); `model` 12,958/12,958 (0 missing; 100.00%); `text_section` 12,958/12,958 (0 missing; 100.00%) |
| `MEASURES` | 10,875 | 17 | `computed_at` 10,875/10,875 (0 missing; 100.00%); `confidence` 10,875/10,875 (0 missing; 100.00%); `confidence_components` 10,875/10,875 (0 missing; 100.00%); `confidence_version` 10,875/10,875 (0 missing; 100.00%); `evidence_type` 10,875/10,875 (0 missing; 100.00%); `evidence_type_diversity` 10,875/10,875 (0 missing; 100.00%); `prov_base_conf` 10,875/10,875 (0 missing; 100.00%); `prov_source` 10,875/10,875 (0 missing; 100.00%); `source` 10,875/10,875 (0 missing; 100.00%); `source_diversity` 10,875/10,875 (0 missing; 100.00%); `support_count_raw` 10,875/10,875 (0 missing; 100.00%); `support_count_unique` 10,875/10,875 (0 missing; 100.00%); `method` 5,961/10,875 (4,914 missing; 54.81%); `prov_method` 5,961/10,875 (4,914 missing; 54.81%); `relationship` 1,422/10,875 (9,453 missing; 13.08%); `contrasts` 1,218/10,875 (9,657 missing; 11.20%); `timestamp` 8/10,875 (10,867 missing; 0.07%) |
| `IMPLEMENTS_FAMILY` | 4,294 | 10 | `computed_at` 2,127/4,294 (2,167 missing; 49.53%); `confidence` 2,127/4,294 (2,167 missing; 49.53%); `confidence_components` 2,127/4,294 (2,167 missing; 49.53%); `confidence_version` 2,127/4,294 (2,167 missing; 49.53%); `evidence_type` 2,127/4,294 (2,167 missing; 49.53%); `evidence_type_diversity` 2,127/4,294 (2,167 missing; 49.53%); `prov_base_conf` 2,127/4,294 (2,167 missing; 49.53%); `source_diversity` 2,127/4,294 (2,167 missing; 49.53%); `support_count_raw` 2,127/4,294 (2,167 missing; 49.53%); `support_count_unique` 2,127/4,294 (2,167 missing; 49.53%) |
| `HAS_VERSION` | 4,142 | 0 | no properties observed |
| `CITES` | 3,397 | 2 | `source` 3,396/3,397 (1 missing; 99.97%); `timestamp` 1/3,397 (3,396 missing; 0.03%) |
| `SUPPORTS_MODALITY` | 2,655 | 0 | no properties observed |
| `SUGGESTS_MEASURES` | 2,514 | 17 | `computed_at` 2,514/2,514 (0 missing; 100.00%); `confidence` 2,514/2,514 (0 missing; 100.00%); `confidence_components` 2,514/2,514 (0 missing; 100.00%); `confidence_version` 2,514/2,514 (0 missing; 100.00%); `evidence_type` 2,514/2,514 (0 missing; 100.00%); `evidence_type_diversity` 2,514/2,514 (0 missing; 100.00%); `method` 2,514/2,514 (0 missing; 100.00%); `prov_base_conf` 2,514/2,514 (0 missing; 100.00%); `prov_method` 2,514/2,514 (0 missing; 100.00%); `prov_source` 2,514/2,514 (0 missing; 100.00%); `source` 2,514/2,514 (0 missing; 100.00%); `source_diversity` 2,514/2,514 (0 missing; 100.00%); `support_count_raw` 2,514/2,514 (0 missing; 100.00%); `support_count_unique` 2,514/2,514 (0 missing; 100.00%); `canonical_id` 612/2,514 (1,902 missing; 24.34%); `evidence_json` 612/2,514 (1,902 missing; 24.34%); `match_label` 612/2,514 (1,902 missing; 24.34%) |
| `HAS_CONTRAST` | 2,464 | 2 | `source` 1,978/2,464 (486 missing; 80.28%); `task` 486/2,464 (1,978 missing; 19.72%) |
| `HAS_REGION` | 2,123 | 2 | `source` 2,123/2,123 (0 missing; 100.00%); `atlas` 1,327/2,123 (796 missing; 62.51%) |
| `PARTICIPATES_IN` | 1,982 | 1 | `source` 1,982/1,982 (0 missing; 100.00%) |
| `HAS_MODALITY` | 1,839 | 0 | no properties observed |
| `HOSTED_AT` | 1,694 | 0 | no properties observed |
| `HAS_TASK` | 1,679 | 20 | `computed_at` 1,679/1,679 (0 missing; 100.00%); `confidence` 1,679/1,679 (0 missing; 100.00%); `confidence_components` 1,679/1,679 (0 missing; 100.00%); `confidence_version` 1,679/1,679 (0 missing; 100.00%); `evidence_type` 1,679/1,679 (0 missing; 100.00%); `evidence_type_diversity` 1,679/1,679 (0 missing; 100.00%); `prov_base_conf` 1,679/1,679 (0 missing; 100.00%); `source_diversity` 1,679/1,679 (0 missing; 100.00%); `support_count_raw` 1,679/1,679 (0 missing; 100.00%); `support_count_unique` 1,679/1,679 (0 missing; 100.00%); `prov_source` 1,641/1,679 (38 missing; 97.74%); `mapping_method` 1,569/1,679 (110 missing; 93.45%); `mapping_version` 1,569/1,679 (110 missing; 93.45%); `match_score` 1,569/1,679 (110 missing; 93.45%); `normalized_task` 1,569/1,679 (110 missing; 93.45%); `prov_method` 1,569/1,679 (110 missing; 93.45%); `raw_task` 1,569/1,679 (110 missing; 93.45%); `needs_measures` 1,241/1,679 (438 missing; 73.91%); `source` 72/1,679 (1,607 missing; 4.29%); `task_name` 38/1,679 (1,641 missing; 2.26%) |
| `PART_OF` | 1,425 | 3 | `atlas` 1,326/1,425 (99 missing; 93.05%); `hierarchy_type` 1,326/1,425 (99 missing; 93.05%); `source` 1,326/1,425 (99 missing; 93.05%) |
| `HASCITATION` | 1,293 | 1 | `source` 1,293/1,293 (0 missing; 100.00%) |
| `ASSERTS` | 1,237 | 2 | `source` 1,237/1,237 (0 missing; 100.00%); `contrasts` 1,033/1,237 (204 missing; 83.51%) |
| `HAS_PHENOTYPE` | 1,218 | 2 | `aggregation_level` 1,218/1,218 (0 missing; 100.00%); `source` 1,218/1,218 (0 missing; 100.00%) |
| `MEASUREDBY` | 1,218 | 3 | `contrast_id` 1,218/1,218 (0 missing; 100.00%); `name` 1,218/1,218 (0 missing; 100.00%); `source` 1,218/1,218 (0 missing; 100.00%) |
| `INVOLVES_SPECIES` | 990 | 0 | no properties observed |
| `CLASSIFIED_UNDER` | 863 | 8 | `source` 863/863 (0 missing; 100.00%); `relation` 765/863 (98 missing; 88.64%); `scheme` 765/863 (98 missing; 88.64%); `confidence` 98/863 (765 missing; 11.36%); `ontology_match_method` 61/863 (802 missing; 7.07%); `ontology_match_score` 61/863 (802 missing; 7.07%); `subfamily_id` 35/863 (828 missing; 4.06%); `subfamily_label` 35/863 (828 missing; 4.06%) |
| `HASCONDITION` | 807 | 1 | `source` 807/807 (0 missing; 100.00%) |
| `USES_CONDITION` | 750 | 3 | `order` 750/750 (0 missing; 100.00%); `source` 750/750 (0 missing; 100.00%); `weight` 750/750 (0 missing; 100.00%) |
| `HASINDICATOR` | 584 | 1 | `source` 584/584 (0 missing; 100.00%) |
| `CLASSIFIEDUNDER` | 523 | 1 | `source` 523/523 (0 missing; 100.00%) |
| `KINDOF` | 429 | 3 | `definition_text` 429/429 (0 missing; 100.00%); `source` 429/429 (0 missing; 100.00%); `alias` 46/429 (383 missing; 10.72%) |
| `INCLUDES` | 402 | 1 | `source` 402/402 (0 missing; 100.00%) |
| `PRODUCES_RESOURCE` | 362 | 0 | no properties observed |
| `CONSUMES_RESOURCE` | 338 | 0 | no properties observed |
| `HAS_CONDITION` | 310 | 2 | `order` 310/310 (0 missing; 100.00%); `source` 310/310 (0 missing; 100.00%) |
| `AFFILIATED_WITH` | 292 | 1 | `source` 292/292 (0 missing; 100.00%) |
| `PARTOF` | 263 | 3 | `definition_text` 263/263 (0 missing; 100.00%); `source` 263/263 (0 missing; 100.00%); `alias` 39/263 (224 missing; 14.83%) |
| `AUTHORED_BY` | 232 | 1 | `source` 232/232 (0 missing; 100.00%) |
| `HAS_GLM_PRIOR` | 224 | 2 | `scope` 224/224 (0 missing; 100.00%); `dataset_id` 78/224 (146 missing; 34.82%) |
| `RELATED_TO` | 190 | 14 | `computed_at` 190/190 (0 missing; 100.00%); `confidence` 190/190 (0 missing; 100.00%); `confidence_components` 190/190 (0 missing; 100.00%); `confidence_version` 190/190 (0 missing; 100.00%); `evidence_type` 190/190 (0 missing; 100.00%); `evidence_type_diversity` 190/190 (0 missing; 100.00%); `prov_base_conf` 190/190 (0 missing; 100.00%); `prov_source` 190/190 (0 missing; 100.00%); `source` 190/190 (0 missing; 100.00%); `source_diversity` 190/190 (0 missing; 100.00%); `support_count_raw` 190/190 (0 missing; 100.00%); `support_count_unique` 190/190 (0 missing; 100.00%); `contrasts` 185/190 (5 missing; 97.37%); `timestamp` 5/190 (185 missing; 2.63%) |
| `BELONGS_TO_FAMILY` | 176 | 7 | `source` 176/176 (0 missing; 100.00%); `subfamily_id` 176/176 (0 missing; 100.00%); `subfamily_label` 176/176 (0 missing; 100.00%); `match_method` 126/176 (50 missing; 71.59%); `match_score` 126/176 (50 missing; 71.59%); `paradigm_name` 126/176 (50 missing; 71.59%); `confidence` 50/176 (126 missing; 28.41%) |
| `REQUIRES_FIELD` | 163 | 0 | no properties observed |
| `USES_TASK` | 152 | 13 | `confidence` 152/152 (0 missing; 100.00%); `source` 152/152 (0 missing; 100.00%); `computed_at` 1/152 (151 missing; 0.66%); `confidence_components` 1/152 (151 missing; 0.66%); `confidence_version` 1/152 (151 missing; 0.66%); `evidence_type` 1/152 (151 missing; 0.66%); `evidence_type_diversity` 1/152 (151 missing; 0.66%); `prov_base_conf` 1/152 (151 missing; 0.66%); `prov_source` 1/152 (151 missing; 0.66%); `source_diversity` 1/152 (151 missing; 0.66%); `support_count_raw` 1/152 (151 missing; 0.66%); `support_count_unique` 1/152 (151 missing; 0.66%); `timestamp` 1/152 (151 missing; 0.66%) |
| `INBATTERY` | 134 | 1 | `source` 134/134 (0 missing; 100.00%) |
| `HAS_VALIDITY_LAYER` | 102 | 0 | no properties observed |
| `HAS_REASON_TAG` | 81 | 0 | no properties observed |
| `CONTAINS_IMPLEMENTATION_RULE` | 80 | 1 | `implementation_rule_id` 80/80 (0 missing; 100.00%) |
| `HAS_EXPERIMENT` | 76 | 2 | `confidence` 76/76 (0 missing; 100.00%); `source` 76/76 (0 missing; 100.00%) |
| `DESCRIBES_TASK` | 72 | 1 | `source` 72/72 (0 missing; 100.00%) |
| `CONTAINS_RULE` | 71 | 0 | no properties observed |
| `HAS_LIFECYCLE_STATUS` | 71 | 0 | no properties observed |
| `HAS_SEVERITY` | 71 | 0 | no properties observed |
| `IN_RULE_GROUP` | 71 | 0 | no properties observed |
| `CONTAINS_CALIBRATION_CASE` | 60 | 0 | no properties observed |
| `CALIBRATES_RULE` | 55 | 0 | no properties observed |
| `CONTRAST_OF` | 53 | 3 | `confidence` 53/53 (0 missing; 100.00%); `method` 53/53 (0 missing; 100.00%); `source` 53/53 (0 missing; 100.00%) |
| `CITED_BY` | 49 | 1 | `source` 49/49 (0 missing; 100.00%) |
| `MAPPED_TO_IMPLEMENTATION` | 28 | 1 | `implementation_rule_id` 28/28 (0 missing; 100.00%) |
| `HAS_PARCEL` | 26 | 0 | no properties observed |
| `IN_PARCELLATION` | 17 | 0 | no properties observed |
| `VALIDATED_ON` | 13 | 0 | no properties observed |
| `HAD_FAILURE` | 7 | 0 | no properties observed |
| `HAS_VARIANT` | 7 | 0 | no properties observed |
| `ACTIVATES` | 6 | 4 | `source` 6/6 (0 missing; 100.00%); `timestamp` 6/6 (0 missing; 100.00%); `confidence` 5/6 (1 missing; 83.33%); `source_id` 2/6 (4 missing; 33.33%) |
| `HAS_POLICY_DECISION` | 6 | 0 | no properties observed |
| `TRIGGERS_SENSITIVITY` | 5 | 0 | no properties observed |
| `FAILED_ON` | 3 | 5 | `error_category` 3/3 (0 missing; 100.00%); `fail_count` 3/3 (0 missing; 100.00%); `last_run_id` 3/3 (0 missing; 100.00%); `last_seen` 3/3 (0 missing; 100.00%); `task_family` 3/3 (0 missing; 100.00%) |
| `DOCUMENTED_IN` | 2 | 0 | no properties observed |
| `HAS_GLM_RUN` | 2 | 0 | no properties observed |
| `HAS_PARCELLATION` | 2 | 0 | no properties observed |
| `CALIBRATES_MODIFIER` | 1 | 0 | no properties observed |
| `CONTAINS_MODIFIER` | 1 | 0 | no properties observed |
| `HAS_EVIDENCE` | 1 | 0 | no properties observed |
| `HAS_SUMMARY` | 1 | 0 | no properties observed |
| `LOCATED_IN` | 1 | 1 | `source` 1/1 (0 missing; 100.00%) |
| `MEASURED_BY` | 1 | 1 | `source` 1/1 (0 missing; 100.00%) |
| `MENTIONS_CONCEPT` | 1 | 1 | `source` 1/1 (0 missing; 100.00%) |
| `SIMILAR_TO` | 1 | 3 | `confidence` 1/1 (0 missing; 100.00%); `source` 1/1 (0 missing; 100.00%); `timestamp` 1/1 (0 missing; 100.00%) |

### Structural Quality Artifact Values
These are existing March 2026 benchmark artifacts, not rerun against the 2026-05-03 full graph.
| Run | Slice nodes | Slice edges | Structure consistency score | Report path |
|---|---|---|---|---|
| `claim_spine_main_20260323` | 579 | 300 | 0.3766 | data/neurokg/benchmarks/structural_quality/claim_spine_main_20260323/graph_diagnostic_report.json |
| `live_smoke_20260323` | 1,154 | 1,083 | 0.4795 | data/neurokg/benchmarks/structural_quality/live_smoke_20260323/graph_diagnostic_report.json |
| `live_smoke_20260323_v2` | 873 | 798 | 0.5206 | data/neurokg/benchmarks/structural_quality/live_smoke_20260323_v2/graph_diagnostic_report.json |
| `live_smoke_20260323_v3_clean` | 895 | 626 | 0.4862 | data/neurokg/benchmarks/structural_quality/live_smoke_20260323_v3_clean/graph_diagnostic_report.json |
| `live_smoke_20260323_v4_encoder_text_v1` | 895 | 626 | 0.4572 | data/neurokg/benchmarks/structural_quality/live_smoke_20260323_v4_encoder_text_v1/graph_diagnostic_report.json |
| `live_smoke_20260323_v5_auto_text_v1` | 895 | 626 | 0.4420 | data/neurokg/benchmarks/structural_quality/live_smoke_20260323_v5_auto_text_v1/graph_diagnostic_report.json |
| `task_structure_cogat_external_20260323` | 294 | 410 | 0.4744 | data/neurokg/benchmarks/structural_quality/task_structure_cogat_external_20260323/graph_diagnostic_report.json |
| `task_structure_neurostore_strict_20260323` | 167 | 150 | 0.5532 | data/neurokg/benchmarks/structural_quality/task_structure_neurostore_strict_20260323/graph_diagnostic_report.json |
| `task_structure_neurostore_strict_20260323_v2` | 167 | 150 | 0.5532 | data/neurokg/benchmarks/structural_quality/task_structure_neurostore_strict_20260323_v2/graph_diagnostic_report.json |

### NeuroKG Query Benchmark Values
| Result file | Queries | Nonzero-result queries | Mean latency sec | Median latency sec | Max latency sec | Rows with constraint score | Mean constraint satisfaction |
|---|---|---|---|---|---|---|---|
| benchmarks/neurokg/results/latest.csv | 30 | 7 | 0.0020 | 0.0019 | 0.0036 | 7 | 1.0000 |
| benchmarks/neurokg/results/science.csv | 22 | 8 | 0.0063 | 0.0062 | 0.0074 | 8 | 1.0000 |

## 1. What Is In NeuroKG?

Reader question: what scientific and operational entities are represented, how
are they typed, and what relationships connect them?

### 1.1 Node Type Inventory

For every node type, document:

| Field | Required content |
|---|---|
| Node type / label | Exact Neo4j label or canonical exported type. |
| Definition | One-sentence semantic definition. |
| Typical instances | 2-3 concrete examples from the graph. |
| Source(s) | Upstream source or loader family. |
| Primary identifier | Internal ID, external CURIE, UUID, or composite key. |
| Key properties | Human-readable label, source IDs, dates, coordinates, ontology IDs, etc. |
| Required vs optional properties | Separate required contract from enrichment fields. |
| Missingness | Count and percentage missing for each important property. |
| Multi-label behavior | Whether the label appears alone or in label sets such as `Dataset\|OpenNeuro`. |
| Current count | Latest refreshed count plus snapshot date. |
| Evidence path | Query, CSV, test, or loader path used to verify the row. |

Minimum semantic node types to enumerate:

- `Study`
- `Contrast`
- `ActivationPeak` or `Coordinate`
- `Term`
- `BrainRegion` or `Region`
- `Task`
- `CognitiveConcept` or `Concept`
- `Disorder`, `Disease`, or `Phenotype`
- `Gene`
- `Drug`
- `Dataset`
- `Paper` or `Publication`
- `Author`
- `Method`
- `Tool`
- `ToolVersion`
- `ToolFamily`
- `DataResource`
- `Collection`
- `StatisticalMap` / `StatsMap`
- `Embedding`
- `TaskSpec`
- `TaskDef`
- `TaskCondition`
- `TaskFamily`
- `Subject`
- `SubjectGroup`
- `Modality`
- `Atlas`
- `Parcellation`
- `Parcel`
- `TemplateSpace`
- `GLMRun`
- `GLMVariant`
- `GLMContrast`
- `ModelSpec`
- `TaskAnalysis`
- `Finding`
- `EvidenceSpan` or nearest evidence node, if present
- Review/governance labels such as `ReviewRule`, `ReviewSchemaField`,
  `ReviewImplementationRule`, `ReviewCalibrationCase`, `ReviewPolicyDecision`,
  and related rule-registry labels
- Every minor label present in the latest `neurokg_node_labels_inventory.csv`

Current verified-live examples from the 2026-05-03 production query:

- Top labels include `Coordinate`, `Publication`, `Collection`, `StatsMap`,
  `Task`, `Embedding`, `StatisticalMap`, `DataResource`, `OpenNeuro`,
  `ToolVersion`, `Term`, `Concept`, `Contrast`, `BrainRegion`, `Dataset`,
  `Tool`, `Phenotype`, `Citation`, and `Subject`.
- The table lists 75 node labels. Do not manually curate a shorter node list for
  Supplementary Methods; include the full exported table or a slice that links
  to it.

### 1.2 Edge Type Inventory

For every edge type, document:

| Field | Required content |
|---|---|
| Edge type | Exact Neo4j relationship type. |
| Semantics | What the relationship asserts. |
| Directionality | Source type, target type, and whether inverse traversal is meaningful. |
| Weighting | Whether edge has `weight`, strength, score, or count fields. |
| Evidence | Whether edge carries source paper, source dataset, extraction method, or confidence. |
| Construction method | Rule, structured parse, statistical association, spatial overlap, ontology mapping, LLM extraction, manual curation, or runtime provenance. |
| Required properties | Minimal property contract. |
| Optional properties | Enrichment fields and provenance fields. |
| Count | Latest refreshed edge count. |
| Dominant schema triples | Major source-label / target-label pairs for the edge. |
| Caveats | Direction ambiguity, duplicate variants, weak semantics, or legacy naming. |
| Evidence path | Query, CSV, test, or loader path used to verify the row. |

Minimum relationship types and families to cover:

- Preserve manuscript-facing aliases such as `mentions`,
  `reports_activation_at`, `associated_with`, `part_of`, `projects_to`,
  `shares_term`, `is_a`, `supersedes`, and `co_occurs_with`, even when the
  live Neo4j relationship type is uppercase or uses a different canonical name.
- Literature/content edges: `MENTIONS`, `MENTIONS_CONCEPT`, `HAS_TERM`,
  `ABOUT`, `CITES`, `CITED_BY`, `AUTHORED_BY`, `DOCUMENTED_IN`, `HASCITATION`
- Activation/spatial edges: `HAS_COORDINATE`, `REPORTS_ACTIVATION_AT`,
  `IN_REGION`, `LOCATED_IN`, `ACTIVATES`, `IN_SPACE`, `HAS_REGION`,
  `PART_OF`, `PARTOF`, `PROJECTS_TO`, `IN_PARCELLATION`,
  `HAS_PARCELLATION`, `HAS_PARCEL`
- Dataset/map edges: `BELONGS_TO`, `DERIVED_FROM`, `GENERATED_FROM`,
  `COMPUTED_WITH`, `HAS_RESOURCE`, `PRODUCES_RESOURCE`, `CONSUMES_RESOURCE`,
  `HOSTED_AT`
- Task/concept edges: `MEASURES`, `MEASURED_BY`, `MEASUREDBY`, `HAS_TASK`,
  `USES_TASK`, `USES_CONDITION`, `HAS_CONDITION`, `HASCONDITION`,
  `HAS_CONTRAST`, `CONTRAST_OF`, `IN_DOMAIN`, `MAPS_TO`, `MAPPED_TO`,
  `SIMILAR_TO`, `SUGGESTS_MEASURES`
- Ontology edges: `IS_A`, `KINDOF`, `CLASSIFIED_UNDER`, `CLASSIFIEDUNDER`,
  `IN_ONVOC`
- Association/co-occurrence edges: `ASSOCIATED_WITH`, `CO_OCCURS_WITH`,
  `SHARES_TERM`, `RELATED_TO`
- Versioning/governance edges: `SUPERSEDES`, `HAS_VERSION`,
  `IMPLEMENTS_FAMILY`, `SUPPORTS_MODALITY`, `VALIDATED_ON`, `FAILED_ON`,
  `HAD_FAILURE`, `HAS_EVIDENCE`, review-rule edges
- Every minor relationship present in the latest
  `neurokg_relationship_types_inventory.csv`

Current verified-live examples from the 2026-05-03 production query:

- Top relationship types include `BELONGS_TO`, `HAS_COORDINATE`, `HAS_TERM`,
  `IN_REGION`, `ABOUT`, `IN_ONVOC`, `IN_DOMAIN`, `IN_SPACE`, `COMPUTED_WITH`,
  `GENERATED_FROM`, `DERIVED_FROM`, `MAPS_TO`, `HAS_RESOURCE`,
  `HAS_TEXT_EMBEDDING`, and `MEASURES`.
- The table lists 85 relationship types. Supplementary Methods should include
  the full exported list or link to it.

### 1.3 Property Schema

For each node and edge type, provide a property-schema table:

| Object type | Property | Required? | Data type | Example | Missing count | Missing percent | Source of truth |
|---|---|---:|---|---|---:|---:|---|
| `Publication` | `pmid` | optional in live graph | string | PMID value | 16,871 / 49,744 | 33.92% | Live property profile, 2026-05-03 |
| `Publication` | `doi` | optional in live graph | string | DOI value | 1,245 / 49,744 | 2.50% | Live property profile, 2026-05-03 |
| `Publication` | `title` | optional in live graph | string | paper title | 2,702 / 49,744 | 5.43% | Live property profile, 2026-05-03 |
| `Coordinate` | `x`, `y`, `z` | required in live graph | number | MNI coordinate | 0 / 447,499 for each field | 0.00% | Live property profile, 2026-05-03 |
| `Coordinate` | `space` | required in live graph | string | template space | 0 / 447,499 | 0.00% | Live property profile, 2026-05-03 |
| edge `HAS_COORDINATE` | `source` | required in live graph | string | source dataset string | 0 / 447,499 | 0.00% | Live relationship-property profile, 2026-05-03 |
| edge `HAS_COORDINATE` | `source_paper` | not present in live profile | string | source paper pointer | 447,499 / 447,499 | 100.00% | Live relationship-property profile, 2026-05-03 |

Edge properties to audit explicitly:

- `weight`
- `evidence_type`
- `source_paper`
- `source_dataset`
- `confidence`
- `extraction_method`
- `loader_version`
- `model`
- `prompt_version`
- `created_at` / `updated_at`
- `snapshot_id`
- `params_hash`

### 1.4 Identifier Scheme

Document identifier hierarchy and primary-key rules:

- Internal node ID / UUID
- Internal relationship ID, if stable
- External CURIEs
- DOI
- PMID
- PubMed Central ID
- Neurosynth study ID
- NeuroVault collection ID
- NeuroVault image ID
- OpenNeuro dataset ID
- Cognitive Atlas task/concept ID
- ONVOC ID
- UBERON ID
- MeSH ID
- NIFSTD ID
- ChEBI ID
- HGNC ID
- DOID ID
- MNI coordinates and template-space identifier
- Atlas/parcellation-specific IDs

Required table:

| Entity class | Primary key | Secondary IDs | Merge key | Collision handling | Evidence path |
|---|---|---|---|---|---|
| Publication | `id` present on 49,580 / 49,744 nodes | DOI present on 48,499; PMID present on 32,873; PMCID not measured as a live property in this pass | DOI/PMID/title/source profile | Missing `id`: 164 nodes; missing DOI: 1,245; missing PMID: 16,871 | Live property profile, 2026-05-03 |
| Coordinate | `id` present on 447,499 / 447,499 nodes | MNI `x`, `y`, `z`, `space` each present on 447,499 / 447,499 | Coordinate ID plus exact spatial fields | No missing `id`, `x`, `y`, `z`, or `space` in live profile | Live property profile, 2026-05-03 |
| Task | `id` and `name` present on 34,926 / 34,926 nodes | `aliases` present on 34,870; source present on 34,914; text/behavior embeddings each present on 44 | Task ID/name plus aliases and source | Missing aliases: 56; missing source: 12; embedded Task coverage: 44 / 34,926 | Live property profile, 2026-05-03 |

### 1.5 Ontology Cross-References

For each ontology, document:

| Ontology | Covered entity types | Link property or edge | Coverage numerator | Coverage denominator | Coverage percent | Caveats |
|---|---|---|---:|---:|---:|---|
| UBERON | anatomy / regions | no live count measured | 0 measured | 2,140 `BrainRegion` nodes as denominator candidate | not measured | No `UBERON` source/property coverage query was found in this pass |
| Cognitive Atlas | tasks / concepts | source-like node counts and task/concept labels | 4,214 `cognitive_atlas` nodes; 1,772 `cognitive_atlas_niclip`; 645 `cognitive_atlas_cao` | 34,926 `Task`; 2,336 `Concept` | source-count only, not ontology-coverage percent | Live source and label counts, 2026-05-03 |
| MeSH | papers / diseases / terms | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| NIFSTD | neuro concepts / anatomy | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| ChEBI | drugs / chemicals | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| HGNC | genes | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| DOID | disorders / diseases | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| ONVOC | task / concept normalization | `IN_ONVOC` edges and ONVOC labels | 63,160 `IN_ONVOC` edges; 752 `OnvocClass`; 752 `OntologyConcept` | relevant Task/Concept/StatsMap/Contrast/Dataset surfaces | edge count, not full source coverage denominator | Live relationship and label counts, 2026-05-03 |

### 1.6 Graph-Structure Summary

Required graph-scale statistics:

- Unique node count by snapshot.
- Edge count by snapshot.
- Node count by type / label set.
- Edge count by type and by schema triple.
- Degree distribution overall and by node type.
- In-degree and out-degree skew by edge type.
- Orphan rate by node type.
- Connected component count.
- Largest connected component size and percent of graph.
- Small isolated component taxonomy.
- Schema-triple concentration: top-1, top-3, top-10 share.
- Whether `726K nodes / 2.4M edges` is current, stale, or approximate.

Current verified-live anchors from the 2026-05-03 production query:

- `schema_triples=151`
- `active_node_labels=75`; `token_store_node_labels=87`
- `active_relationship_types=85`; `token_store_relationship_types=86`
- `unique_nodes=694,135`; `total_edges=2,423,334`
- `top1_share=44.4%`
- `top3_share=77.6%`
- `top10_share=93.4%`
- `rank_for_90pct=8`, `rank_for_95pct=12`, `rank_for_99pct=36`

## 2. Where Did It Come From?

Reader question: what sources contributed the graph, under what snapshots and
licenses, and can every assertion be traced back?

### 2.1 Source Inventory

List every upstream source, including structured sources, manually imported
sets, and LLM-mined paper sets:

- Neurosynth
- NeuroVault
- Cognitive Atlas
- Neurostore
- OpenNeuro
- PubMed
- PubMed Central / PMC
- ONVOC
- Wikidata
- Neurobagel
- NeuroQuery
- NiMARE-derived assets
- NeuroScout-derived assets
- BrainMap, if licensed/available
- BIDS-derived metadata
- Allen Human Brain Atlas / Allen HBA, if present
- Nilearn atlas definitions
- Neuromaps annotations
- NIDM results
- Virtual Brain, if configured
- GWAS Catalog / OpenMed / PGC imports, if present
- Manual imports
- LLM-mined paper sets, including Gabriel and KGGen-derived candidate lanes
- Runtime/tool catalog surfaces, if included in the same graph
- Review-rule / governance registries, if included in the same graph

Required table:

For the release worklist that covers every live source-like value and every
configured-but-absent source, use the all-source audit table in the provenance
gap register above. The table below is the shorter reader-question summary for
Methods/data-card slicing.

| Source | Entity/edge types contributed | Snapshot date | Version | URL | License | Required citation | Loader path | Data artifact path | Status |
|---|---|---|---|---|---|---|---|---|---|
| Neurosynth | 464,946 nodes with `source=neurosynth`; 447,498 edges with `source=neurosynth_v7`; 358,050 edges with `source=neurosynth` | snapshot date not stored in live source fields | source string only | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | loader path not measured in current numeric pass | data artifact path not measured in current numeric pass | live graph source counts verified |
| NeuroVault | 37,467 nodes with `source=neurovault`; 1,076,839 edges with `source=neurovault` | snapshot date not stored in live source fields | source string only | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | loader path not measured in current numeric pass | data artifact path not measured in current numeric pass | live graph source counts verified |
| Cognitive Atlas | 4,214 nodes with `source=cognitive_atlas`; 14,591 edges with `source=cognitive_atlas`; plus 1,772 `cognitive_atlas_niclip` nodes and 645 `cognitive_atlas_cao` nodes | snapshot date not stored in live source fields | source string only | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | loader path not measured in current numeric pass | data artifact path not measured in current numeric pass | live graph source counts verified |
| BrainMap | 0 live nodes/edges under `brainmap` | not present in live source scan | configured spine source | upstream URL not measured in current numeric pass | license likely requires explicit check before redistribution | citation not measured in current numeric pass | `gwas` not relevant; BrainMap loader status not measured in this pass | data artifact path not measured in current numeric pass | configured but absent from live scan |
| BIDS | 0 live nodes/edges under `bids`; BIDS-derived GLM fields appear under `openneuro_glmfitlins` | not present as literal source | configured spine source | upstream URL not measured in current numeric pass | license inherited from datasets; not measured | citation not measured in current numeric pass | BIDS/OpenNeuro parser path not fully mapped in this pass | artifact path not measured in current numeric pass | represented indirectly through OpenNeuro/GLMFitLins lanes |
| Virtual Brain | 0 live nodes/edges under `virtual_brain` | not present in live source scan | configured spine source | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | loader path not measured in current numeric pass | artifact path not measured in current numeric pass | configured but absent from live scan |
| Wikidata | 0 live nodes/edges under `wikidata` | not present in live source scan | configured spine source | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | `src/brain_researcher/services/neurokg/etl/loaders/wikidata_loader.py`; `wikidata_json_loader.py` exist | artifact path not measured in current numeric pass | configured but absent from live scan |
| NIDM results | 0 live nodes/edges under `nidm_results` | on-demand configured source | configured on-demand source | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | `src/brain_researcher/services/neurokg/etl/loaders/nidm_results_loader.py` exists | artifact path not measured in current numeric pass | adapter/source configured but no persisted live source value |
| NeuroQuery | 0 live nodes/edges under `neuroquery` | on-demand configured source | configured on-demand source | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | on-demand adapter configured in `configs/neurokg/ingestion_modes.yaml` | sample path configured as `data/neurokg/raw/evidence/neuroquery_sample.json` | adapter/source configured but no persisted live source value |
| NiMARE | 0 live nodes/edges under `nimare` | on-demand configured source | configured on-demand source | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | on-demand adapter configured in `configs/neurokg/ingestion_modes.yaml` | sample path configured as `data/neurokg/raw/evidence/nimare_sample.json` | adapter/source configured but no persisted live source value |
| NeuroScout | 0 live nodes/edges under `neuroscout` | on-demand configured source | configured on-demand source | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | on-demand adapter configured in `configs/neurokg/ingestion_modes.yaml` | sample path configured as `data/neurokg/raw/evidence/neuroscout_features.json` | adapter/source configured but no persisted live source value |
| Allen HBA | no literal `allen_hba`; `Allen Brain Atlas` has 1,329 nodes / 1,328 edges and `Allen CCFv3` has 1,326 edges | source alias mismatch | configured spine source represented by source aliases | upstream URL not measured in current numeric pass | license not measured in current numeric pass | citation not measured in current numeric pass | `src/brain_researcher/services/neurokg/etl/loaders/allen_hba_adapter.py` not in loader list; `allen_hba` adapter/source config present | `data/neurokg/raw/allen_hba/manifest.json` exists | present via aliases; normalize naming |
| Unattributed / missing source | `<missing>` has 6,889 nodes and 41,393 edges | no source string | provenance gap, not an upstream source | not applicable | not releasable without audit | not applicable | audit by label/type required | audit artifact not yet created | release blocker until attributed/excluded/documented |
| Internal/generated/test lanes | includes `config_text_backfill`, `capabilities.merged.yaml`, `taxonomy_rule`, `taxonomy_surface_rules`, `task_families`, `task_family_enrichment`, `disease_path_backfill`, `seed`, `bulk_loader`, `GraphQL API`, `Manual`, `Test*` | mixed source-like strings | internal/generated/manual/test, not external upstream | not applicable | not upstream license; derive from underlying sources and local policy | not applicable | see release-ready provenance gap register | see release-ready provenance gap register | must be classified before public release |
| Gabriel / KGGen | 32 Gabriel manifests, 12 Gabriel review queues, 75 KGGen summaries, 81 KGGen JSONL files; 0 live source-marked nodes/edges | raw/run artifacts but no live `source` marker | LLM/candidate/comparison lanes | not applicable | release depends on candidate/accepted status and upstream paper licenses | citation/provenance not measured in current numeric pass | `docs/neurokg/gabriel_full_pipeline.md`; `data/neurokg/raw/gabriel`; `data/neurokg/raw/kggen` | repo artifacts present | confirm not ingested vs candidate-only vs unmarked ingestion |

### 2.2 Provenance Granularity

Answer explicitly:

- Is provenance stored at node level?
- Is provenance stored at edge level?
- Can a relationship be traced to the original upstream source row, paper,
  dataset, file, or API payload?
- Can LLM-extracted content be traced to model, prompt, raw response, and
  validation decision?
- Are provenance fields required, optional, or missing by edge type?
- Which edge types are only schema-derived or runtime-derived?
- Which edge types have evidence packs or source-paper links?

Required table:

| Edge type | Edge-level provenance? | Node-level provenance only? | Source row trace? | Paper/dataset trace? | Confidence trace? | Missingness | Evidence path |
|---|---:|---:|---:|---:|---:|---:|---|
| `HAS_COORDINATE` | yes: `source` present on 447,499 / 447,499 edges | no | source property only | indirect via Publication -> Coordinate edge; no separate `source_paper` property | no `confidence`; no `weight` | 0 missing `source`; 447,499 missing `source_paper` | Live relationship-property profile, 2026-05-03 |
| `IN_REGION` | yes: `edge_source`, `atlas`, `etl_version`, `measure`, `n_vox`, `pct_active`, `weight`, and `z_thr` each present on 121,261 / 121,261 edges | no | source/method properties only | no separate paper/dataset property measured | `weight` present on 121,261 / 121,261; no `confidence` property measured | 0 missing for the listed properties | Live relationship-property profile, 2026-05-03 |
| `ABOUT` | yes: `source`, `confidence`, `created_at` present on 75,922 / 75,922 edges | no | source property plus match terms | source entity -> concept; no source-paper property measured | `confidence` present on 75,922 / 75,922; `confidence_tier` present on 34 / 75,922 | missing `match_terms`: 34; missing `confidence_tier`: 75,888 | Live relationship-property profile, 2026-05-03 |

### 2.3 LLM-Generated Content

For every LLM-assisted lane, document:

- Node types produced.
- Edge types produced.
- Fraction of total nodes from LLM extraction.
- Fraction of total edges from LLM extraction.
- Model name and version.
- Prompt file or prompt hash.
- Prompt version.
- Structured-output schema.
- Raw response storage path.
- Deterministic fallback behavior.
- Validation gate.
- Human review queue.
- Rejected candidate handling.
- Candidate-only vs benchmark/published lane distinction.
- Whether LLM output is marked as such in graph properties.

Required table:

| Lane | Model | Prompt version | Output schema | Nodes produced | Edges produced | Accepted count | Candidate-only count | Rejected count | Validation method | Evidence path |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|
| Gabriel | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | `docs/neurokg/gabriel_full_pipeline.md` |
| KGGen comparison | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | `docs/neurokg/gabriel_full_pipeline.md` |

## 3. How Was It Built?

Reader question: what reproducible pipeline transforms upstream sources into
the graph?

### 3.1 Ingestion Path Per Source

For each source, classify the ingestion path:

- Structured file parse.
- API pull.
- Database dump.
- Web scrape.
- Cached metadata replay.
- LLM extraction.
- Manual import.
- Runtime telemetry import.

Required table:

| Source | Ingestion path | Entry command | Loader/module | Inputs | Outputs | Idempotency key | Failure handling | Status |
|---|---|---|---|---|---|---|---|---|
| PubMed | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| OpenNeuro | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Gabriel paper mining | LLM/heuristic extraction | `br gabriel generate`; `br gabriel ingest` | not measured in current numeric pass | not measured in current numeric pass | review queue, shards, Neo4j writes | not measured in current numeric pass | candidate/reject queues | partial |

### 3.2 Entity Extraction

Document which extractor is responsible for each entity family:

- Structured parser.
- NER model.
- Ontology lookup.
- Spatial parser.
- Statistical-map parser.
- BIDS/OpenNeuro parser.
- LLM extractor.
- Deterministic heuristic fallback.
- Manual annotation.

Required table:

| Entity family | Extraction method | Model/parser | Version | Input fields | Output fields | Quality gate | Evidence path |
|---|---|---|---|---|---|---|---|
| Publications | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Activation coordinates | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Task/concept mentions | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 3.3 Entity Resolution And Deduplication

Document the resolution order and thresholds:

- Exact external ID match.
- DOI/PMID/PMCID matching.
- Source-specific CURIE matching.
- Normalized string match.
- Alias table lookup.
- Ontology grounding.
- Embedding similarity.
- Spatial/template-space match.
- Manual merge queue.
- `SAME_AS` or canonical merge behavior.

Required table:

| Entity family | Blocking key | Match features | Auto-merge threshold | Review threshold | Canonical selection rule | Evidence path |
|---|---|---|---:|---:|---|---|
| Publication | not measured in current numeric pass | DOI, PMID, title, authors | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Task | not measured in current numeric pass | alias, Cognitive Atlas ID, embedding | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Brain region | not measured in current numeric pass | ontology ID, atlas, coordinate overlap | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 3.4 Edge Construction

For each edge family, specify how edges are made:

- Rule-based construction.
- Structured-source relationship.
- Statistical coactivation or co-occurrence.
- Spatial overlap or region assignment.
- Ontology parent/child import.
- Embedding similarity threshold.
- LLM-extracted relation.
- Manual curation.
- Runtime/tool telemetry.

Required table:

| Edge type | Construction method | Direction rule | Required inputs | Thresholds | Example | Evidence path |
|---|---|---|---|---|---|---|
| `HAS_COORDINATE` | structured source relationship from Neurosynth | Publication -> Coordinate | Publication nodes and Coordinate nodes | no score threshold observed in live edge properties | `Publication -[HAS_COORDINATE]-> Coordinate`, 447,499 edges | Live schema triple and relationship-property profile, 2026-05-03 |
| `IN_REGION` | spatial overlap / region assignment | StatsMap -> BrainRegion | StatsMap nodes, BrainRegion nodes, atlas/mask logic | `z_thr` present on 121,261 / 121,261; `pct_active` and `weight` present on 121,261 / 121,261 | `StatsMap -[IN_REGION]-> BrainRegion`, 121,261 edges | Live schema triple and relationship-property profile, 2026-05-03 |
| `ABOUT` | ontology/text linking to ONVOC concept surface | Source entity -> Concept | Publication/DataResource/Dataset/Tool and Concept/Onvoc nodes | `confidence` present on 75,922 / 75,922 | dominant triple `Publication -[ABOUT]-> Concept\|OntologyConcept\|OnvocClass`, 67,785 edges | Live schema triple and relationship-property profile, 2026-05-03 |

### 3.5 Human-In-The-Loop Steps

Document every human review point:

- What is reviewed.
- Who or what role reviews it.
- Annotation interface.
- Decision labels.
- Inter-annotator agreement, if applicable.
- How decisions write back into the KG.
- Whether the step is required for release or only for benchmark gold.

Required table:

| Step | Reviewed object | Interface | Reviewer role | Decision labels | Write-back target | Required for release? | Evidence path |
|---|---|---|---|---|---|---:|---|
| Gabriel review queue | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | accept/reject/candidate | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 3.6 Rejection And Unmapped Handling

Document:

- Discarded records.
- Temporary staging.
- Candidate-only lane.
- Weak links.
- Review queue.
- Backfill queue.
- Failure tags.
- Re-ingest behavior.

Required table:

| Failure/unmapped class | Action | Storage path | Reprocessable? | Promoted to graph? | Evidence path |
|---|---|---|---:|---:|---|
| No ontology match | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Low-confidence LLM relation | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Missing source ID | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 3.7 Reproducibility

Document:

- Build scripts.
- CLI commands.
- Docker image.
- Dependency lock files.
- Environment variables.
- Required secrets.
- Input data locations.
- Output dump paths.
- Build time.
- Hardware/VM requirements.
- Whether the build is full rebuild or incremental.
- Whether prod graph can be recreated from public artifacts.

Required table:

| Build target | Command | Container/image | Dependencies | Expected runtime | Inputs | Outputs | Reproducibility status |
|---|---|---|---|---|---|---|---|
| Full KG rebuild | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Schema inventory export | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | artifact-needs-refresh |

Supplementary Methods pseudo-code slot:

```text
for source in configured_sources:
    snapshot = fetch_or_resolve_snapshot(source)
    records = parse_source(snapshot)
    entities = extract_entities(records)
    canonical_entities = resolve_and_merge(entities, ontology_registry)
    candidate_edges = construct_edges(canonical_entities, records)
    accepted_edges, review_queue = validate_or_queue(candidate_edges)
    write_nodes_edges_with_provenance(canonical_entities, accepted_edges)
emit_schema_inventory()
emit_quality_card()
```

## 4. How Do We Know It Is Good?

Reader question: what evidence shows the KG is accurate, complete enough, and
honest about failure modes?

### 4.1 Sampling Precision Evaluation

Required details:

- Sample size `N`.
- Sampling frame.
- Stratification by edge type and source.
- Number of annotators.
- Annotator instructions.
- Agreement metric, such as Cohen kappa or Krippendorff alpha.
- Precision by edge type.
- Confidence intervals.
- Adjudication process.
- Released annotation artifact path.

Required table:

| Edge type | N | Annotators | Agreement | Precision | 95% CI | Main error types | Evidence path |
|---|---:|---:|---:|---:|---|---|---|
| `HAS_COORDINATE` | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| `IN_REGION` | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 4.2 Coverage Evaluation Against External References

Evaluate coverage against:

- Classic review papers.
- Known landmark studies.
- Canonical task lists.
- Cognitive Atlas tasks/concepts.
- NeuroVault/Neurosynth known study sets.
- OpenNeuro dataset/task catalogs.
- Ontology gold standards.

Required table:

| Reference set | Expected entities/findings | Matched in KG | Coverage | Matching rule | Caveats | Evidence path |
|---|---:|---:|---:|---|---|---|
| Classic review paper set | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Landmark studies | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 4.3 Recall Spot-Checks

For several landmark studies, document:

- Whether the paper is retrievable.
- Whether known regions are present.
- Whether known tasks/concepts are linked.
- Whether expected traversal paths exist.
- Whether evidence can be traced back to source.

Required table:

| Landmark study | Expected KG path | Found? | Missing pieces | Query used | Evidence path |
|---|---|---:|---|---|---|
| not measured in current numeric pass | Publication -> HAS_COORDINATE -> Coordinate -> IN_REGION -> BrainRegion | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 4.4 Structural Quality Benchmark

Use `docs/specs/neurokg_structural_quality_benchmark_v1.md` as the framing:

- Total node/edge counts are descriptive, not sufficient quality evidence.
- Report a versioned graph diagnostic report per snapshot.
- Include per-node-type coverage.
- Include per-edge-type coverage.
- Include orphan rates.
- Include degree skew.
- Include per-edge-type learnability.
- Include control-adjusted consistency buckets.
- Include `structure_consistency_score`.
- Separate KG construction QA from downstream BR utility benchmarks.

Required outputs:

| Artifact | Required? | Path | Status |
|---|---:|---|---|
| Graph diagnostic report | yes | 9 existing reports under `data/neurokg/benchmarks/structural_quality/*/graph_diagnostic_report.json` | existing March 2026 artifacts; structure consistency scores range 0.3766-0.5532 |
| Probe model comparison | supporting | 9 existing reports under `data/neurokg/benchmarks/structural_quality/*/probe_model_comparison.json` | `node2vec` skipped in these artifacts because graph-embedding dependencies were unavailable |
| Fairness/subgroup audit | optional stable | not measured in current numeric pass | no fairness/subgroup audit artifact found in this numeric pass |

### 4.5 Error Taxonomy

Track and report at least:

- Linking error.
- Duplicate merge error.
- Missed merge.
- Extraction hallucination.
- Unsupported LLM relation.
- Ontology mismatch.
- Wrong directionality.
- Stale data.
- Missing source provenance.
- Coordinate/template-space mismatch.
- Ambiguous task/concept mapping.
- License/provenance uncertainty.
- Runtime/tool surface mixed with scientific KG surface.

Required table:

| Error class | Definition | Count | Percent | Affected node/edge types | Detection method | Mitigation |
|---|---|---:|---:|---|---|---|
| Linking error | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Extraction hallucination | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 4.6 Known Limitations

Document explicitly:

- Domain bias.
- Temporal bias and coverage cutoff year.
- Language bias, especially English-only coverage.
- Modality bias, for example fMRI-heavy vs sMRI/EEG/MEG-light coverage.
- Publication bias.
- NeuroVault/Neurosynth availability bias.
- Ontology coverage gaps.
- Sparse edge families.
- Candidate-only LLM extraction not equivalent to adjudicated gold.
- Runtime/tool labels mixed with scientific labels, if using the same Neo4j
  database.
- Snapshot drift across docs, figures, and dumps.

## 5. How Is It Stored And Accessed?

Reader question: what system stores NeuroKG, how can it be queried, and what are
its performance bounds?

### 5.1 Backend

Document:

- Neo4j version.
- Database name.
- Deployment shape.
- k3s namespace, StatefulSet, service names.
- Replica count.
- Persistent volume configuration.
- Backup strategy.
- Restore procedure.
- Snapshot export procedure.
- Local/dev backend variants, if any.

Required table:

| Environment | Backend | Version | Deployment | Replicas | Backup | Restore tested? | Evidence path |
|---|---|---|---|---:|---|---:|---|
| prod | Neo4j | 5.22.0 community | k3s StatefulSet `brain-researcher-neurokg`, pod `brain-researcher-neurokg-0` | 1 ready / 1 desired | backup strategy not measured in current numeric pass | restore not measured in current numeric pass | Live prod query and k3s status, 2026-05-03 |
| local/dev | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 5.2 Query Interfaces

Document:

- Raw Cypher.
- REST wrapper.
- GraphQL, if live.
- SPARQL endpoint, if live.
- Natural-language query route, if live.
- Persisted queries.
- Finder/search APIs.
- Direct Python service APIs.

Required table:

| Interface | Route/entrypoint | Auth | Input contract | Output contract | Typical use | Relation to raw Cypher | Status |
|---|---|---|---|---|---|---|---|
| Cypher | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | direct graph query | native | not measured in current numeric pass |
| REST | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | app/tool access | wrapper | not measured in current numeric pass |
| GraphQL | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | structured app queries | wrapper | not measured in current numeric pass |

### 5.3 Index Strategy

Document:

- Property indexes.
- Uniqueness constraints.
- Full-text indexes.
- Vector indexes.
- Composite indexes.
- Relationship indexes, if used.
- Index creation scripts.
- Index health checks.

Required table:

| Index/constraint | Object | Properties | Purpose | Creation path | Verified in prod? |
|---|---|---|---|---|---:|
| not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 5.4 Embedding Layer

Document:

- Whether node embeddings exist.
- Which node types have embeddings.
- Model name.
- Model version.
- Vector dimension.
- Text template used to form embedding input.
- Vector storage location.
- Vector index backend: Neo4j native, FAISS, pgvector, or other.
- Refresh cadence.
- Coverage by node type.
- Similarity threshold usage.

Current verified-live anchor:

- Live production query reports `23,865` text embeddings, model
  `BrainGPT-7B-v0.2`, dimension `4096`, source `niclip`.

Required table:

| Embedding set | Node types | Model | Dim | Count | Coverage | Vector index | Query path | Evidence path |
|---|---|---|---:|---:|---:|---|---|---|
| text embeddings | `Embedding`; linked from `Publication` by 12,958 `HAS_TEXT_EMBEDDING` edges | BrainGPT-7B-v0.2 | 4096 | 23,865 `Embedding` nodes | 12,958 / 49,744 Publication nodes linked by `HAS_TEXT_EMBEDDING` in live graph | vector index backend not measured in current numeric pass | query path not measured in current numeric pass | Live query, 2026-05-03 |

### 5.5 MCP Tools And BR Tool Surface

For every MCP or agent tool that exposes KG access, document:

- Tool name.
- Signature.
- Input schema.
- Output schema.
- Typical use.
- Whether it emits raw KG evidence, summarized evidence, or retrieval hints.
- Whether it calls raw Cypher, service wrapper, persisted query, or hybrid
  search.
- Latency expectation.
- Failure modes.

Required table:

| Tool | Signature | Typical use | Backend path | Raw Cypher relation | Evidence returned | Status | Test path |
|---|---|---|---|---|---|---|---|
| not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 5.6 Latency And Throughput

Benchmark:

- Single-node lookup latency.
- Full-text search latency.
- Vector search latency.
- 1-hop traversal latency.
- Multi-hop traversal latency.
- Schema inventory export runtime.
- Concurrent query throughput.
- Ingest throughput.
- Worst-case query timeout behavior.

Required table:

| Operation | Query shape | P50 | P95 | P99 | Throughput | Dataset snapshot | Evidence path |
|---|---|---:|---:|---:|---:|---|---|
| Node lookup | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Multi-hop traversal | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

## 6. How Is It Used In Brain Researcher?

Reader question: what runtime behavior depends on NeuroKG, and what changes
when KG access is disabled?

### 6.1 Runtime Consumers

List every agent, service, and runtime episode step that reads the KG:

- Chat/Studio routes.
- Grounded search routes.
- Hypothesis generation.
- Planning.
- Review verdict support.
- Evidence assembly.
- Tool routing.
- Dataset/task matching.
- NeuroMetaBench or benchmark adapters.
- Claim adjudication.
- Memory enrichment.

Required table:

| Consumer | Episode step | KG query type | Required? | Fallback without KG | Evidence path |
|---|---|---|---:|---|---|
| Hypothesis generation | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Review verdict | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 6.2 Retrieval Patterns

Document proportions and examples for:

- Semantic retrieval using embeddings.
- Structural graph traversal.
- Hybrid retrieval.
- Exact ID lookup.
- Full-text search.
- Persisted query.
- Tool-mediated evidence pack.

Required table:

| Retrieval pattern | Example query | Consumer | Share of KG calls | Strength | Failure mode | Evidence path |
|---|---|---|---:|---|---|---|
| Semantic | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Structural | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Hybrid | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 6.3 Role In BR Outputs

Document specific roles in:

- Hypothesis generation.
- Planning.
- Evidence retrieval.
- Review verdicts.
- Dataset/task recommendation.
- Method compatibility.
- Failure-mode detection.
- Citation/grounding support.

Required table:

| BR output | KG contribution | Required evidence | How user sees it | Ablation expectation | Evidence path |
|---|---|---|---|---|---|
| Hypothesis | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Review verdict | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 6.4 Interface With Memory Systems

Document the relation between:

- KG / semantic memory.
- Episodic memory.
- Claim memory cards.
- Run artifacts.
- Evidence packs.
- Citation anchors.

Questions to answer:

- Do memory cards link to KG node IDs?
- Do KG nodes link back to memory cards?
- Are claims grounded in KG edges, source docs, or both?
- Are stale memory cards invalidated when KG snapshots change?
- Are KG snapshot IDs stored in memory cards?

Required table:

| Memory object | Links to KG? | KG links back? | Snapshot-aware? | Evidence path |
|---|---:|---:|---:|---|
| Claim memory card | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Episodic memory | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

## 7. How Is It Released And Maintained?

Reader question: what version should users cite, how does it change, and what
can be redistributed?

### 7.1 Versioning And Changelog

Document:

- Current KG version.
- Release date.
- Snapshot ID.
- Changelog path.
- Schema version.
- Data version.
- Build version.
- Query/tool compatibility version.
- Deprecation policy.

Required table:

| Version | Release date | Snapshot ID | Node count | Edge count | Schema changes | Data changes | Changelog |
|---|---|---|---:|---:|---|---|---|
| not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 7.2 Update Cadence

Document:

- Rebuild frequency.
- Incremental update vs full rebuild.
- Source refresh cadence by source.
- Update trigger.
- Backward compatibility guarantee.
- How stale claims are marked.
- How failed builds are handled.

Required table:

| Source/layer | Update cadence | Incremental? | Full rebuild trigger | Validation gate | Owner |
|---|---|---:|---|---|---|
| PubMed | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| OpenNeuro | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 7.3 Public Release Plan

Document:

- Whether there is a public release.
- Zenodo DOI plan.
- Dump formats.
- Cypher dump.
- JSON-LD.
- RDF/Turtle.
- CSV edge/node tables.
- Schema inventory tables.
- Data card.
- Checksums.
- Reproducible build scripts.
- Redaction/removal policy.

Required table:

| Release artifact | Format | Public? | License | Contains derived data? | Checksum | Path/URL |
|---|---|---:|---|---:|---|---|
| Full dump | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Schema inventory | CSV/HTML | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 7.4 License Compatibility Matrix

Document:

- Overall KG license.
- License per upstream source.
- Redistribution allowed?
- Commercial use allowed?
- Attribution required?
- Share-alike required?
- Data-use restrictions.
- Citation obligations.
- Whether derived LLM content changes the release obligation.

Required table:

| Source | License | Redistribution | Commercial use | Attribution | Share-alike | Citation required | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| Neurosynth | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| NeuroVault | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Cognitive Atlas | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| OpenNeuro | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| PubMed/PMC | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 7.5 Build Script Openness

Document:

- Which build scripts are open-source.
- Which require internal credentials.
- Which require mounted private data.
- Which require licensed datasets.
- Which are reproducible by third parties.
- Which are internal-only operational scripts.

Required table:

| Script/entrypoint | Open? | Requires secrets? | Requires private data? | Reproducible externally? | Notes |
|---|---:|---:|---:|---:|---|
| not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

## 8. How Does It Compare To Related Resources?

Reader question: why is NeuroKG different from existing KGs and ontologies?

Resources to compare:

- Hetionet.
- SPOKE.
- Biomni KG.
- NeuroBridge.
- NIFSTD.
- Cognitive Atlas standalone.
- Brain Knowledge Graph or similar neuroimaging KGs.
- Neurosynth/NeuroVault as source resources rather than integrated KGs.
- Neurostore.
- OpenNeuro metadata alone.

Required comparison table:

| Resource | Approx size | Domain focus | Main entity types | Construction method | Provenance granularity | Ontology grounding | Neuroimaging coverage | Downstream use | Difference from NeuroKG |
|---|---:|---|---|---|---|---|---|---|---|
| Hetionet | not measured in current numeric pass | biomedical | not measured in current numeric pass | curated/integrated | not measured in current numeric pass | not measured in current numeric pass | low? | biomedical discovery | not measured in current numeric pass |
| SPOKE | not measured in current numeric pass | biomedical | not measured in current numeric pass | integrated | not measured in current numeric pass | not measured in current numeric pass | low? | biomedical discovery | not measured in current numeric pass |
| Biomni KG | not measured in current numeric pass | biomedical agent substrate | not measured in current numeric pass | integrated | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | agent tools | not measured in current numeric pass |
| NeuroBridge | not measured in current numeric pass | neuroimaging? | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| NIFSTD | not measured in current numeric pass | neuroscience ontology | ontology terms | curated ontology | not measured in current numeric pass | high | ontology not graph substrate | terminology | not measured in current numeric pass |
| Cognitive Atlas | not measured in current numeric pass | cognitive tasks/concepts | tasks, concepts | curated ontology | not measured in current numeric pass | high for cognition | tasks/concepts only | taxonomy | not measured in current numeric pass |
| Brain Knowledge Graph | not measured in current numeric pass | neuroimaging | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

Comparison dimensions to include in prose:

- Size.
- Domain focus.
- Source breadth.
- Whether activation coordinates/statmaps are first-class.
- Whether tasks/concepts are linked to datasets and methods.
- Whether it supports BR runtime retrieval.
- Whether it has edge-level provenance.
- Whether it has LLM-mined content.
- Whether it has release/data-card governance.

## 9. Ethics And Governance

Reader question: what are the privacy, licensing, attribution, and governance
risks?

### 9.1 Human-Subject And PHI Risk

Document explicitly:

- Whether subject-level PHI is included.
- Whether subject-level public metadata is included.
- Whether all subject-level data are aggregate/public/deidentified.
- Whether OpenNeuro or other dataset metadata can include sensitive free text.
- Redaction policy.
- Data removal request process.
- Whether the release contains raw participant-level fields or only derived
  aggregate metadata.

Expected paper claim to verify:

- No PHI is intended because sources are aggregate/public/deidentified, but this
  must be explicitly audited and stated.

Required table:

| Data class | Subject-level? | PHI risk | Public source? | Released? | Mitigation |
|---|---:|---|---:|---:|---|
| Publication metadata | no | low | yes | not measured in current numeric pass | not measured in current numeric pass |
| OpenNeuro metadata | possible | not measured in current numeric pass | yes | not measured in current numeric pass | not measured in current numeric pass |
| Subject nodes | yes? | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

### 9.2 License And Redistribution Governance

Document:

- Which upstream licenses allow redistribution.
- Which require attribution.
- Which restrict commercial use.
- Which allow derived graph edges.
- Which require source-specific citation.
- How the release propagates citation obligations.
- Whether generated dumps include license metadata.

This section should be consistent with the license matrix in Section 7.4.

### 9.3 Citation Propagation

Document:

- Citation file path.
- Per-source citation list.
- Per-node/edge citation metadata.
- Release note attribution.
- Data-card attribution.
- How downstream users know what to cite.

Required table:

| Source or derived layer | Citation required | Where citation appears | Propagated in dump? | Notes |
|---|---:|---|---:|---|
| Neurosynth | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| NeuroVault | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |
| Cognitive Atlas | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass | not measured in current numeric pass |

## Deployment To Manuscript And Release Surfaces

Use this master inventory to generate slices:

| Surface | Pull from sections | Expected length | Required content |
|---|---|---:|---|
| Main text | 1.1, 1.2, 1.6 | 1 paragraph | Node/edge totals, major node/edge families, and ontological organization principle. |
| Methods | 1, 2, 3, 4 headline | 0.5-1 page | Schema summary, source list, high-level pipeline, and validation headline numbers. |
| Supplementary Methods | all sections | full tables plus pseudo-code | Complete 9-dimension inventory, full schema tables, and pipeline details. |
| Data card / release page | 2, 4, 7, 9 | full operational page | Provenance, validation, version/release, license, ethics, and citation obligations. |
| Companion benchmark paper | 4, 6 | benchmark-focused section | KG quality card plus KG-on/off utility ablation details. |

Main-text compression template:

```text
NeuroKG is a typed neuroimaging knowledge graph containing [N] nodes and [M]
edges across [major node families], organized around [ontology principle] and
linking literature, activation/spatial evidence, datasets, tasks, concepts,
methods, and runtime evidence through [major edge families].
```

Methods compression template:

```text
We built NeuroKG from [sources] using source-specific loaders, ontology-grounded
entity resolution, typed edge construction, and provenance-preserving graph
writes. We validated the graph using [precision audit], [coverage audit], and
[structural quality benchmark], reporting metrics by snapshot and edge type.
```

## Items Most Likely To Be Missed

Treat these as hard checks before manuscript or release:

- Edge-level provenance vs node-level provenance.
- LLM-extracted content ratio.
- LLM model name, model version, prompt version, raw response storage, and
  validation workflow.
- Temporal coverage cutoff year.
- Update cadence and incremental vs full rebuild policy.
- Upstream license compatibility matrix.
- Explicit known failure modes and error taxonomy.
- Snapshot identity for every count.
- Full minor node-label and relationship-type tables, not only major schema
  families.
- Separation between scientific KG structure and runtime/tool/job telemetry
  surfaces when both live in the same graph.

## Next Concrete Fill Order

1. Refresh Dimension 1 from the latest production graph:
   node labels, label sets, relationship types, schema triples, unique node
   count, edge count, degree distribution, and connected components.
2. Fill source/version/license table for every loader/source.
3. Audit edge-level provenance missingness by relationship type.
4. Audit LLM-generated content: counts, model, prompt, validation, candidate vs
   accepted lanes.
5. Emit a versioned quality card using construction QA metrics plus structural
   benchmark metrics.
