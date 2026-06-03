# Prod BR-KG Plot Probe

Generated from bounded prod queries through `${GCE_VM_NAME}` and `brain-researcher-br-kg-0`.

## Generated Figures

- `figures/fig01_node_and_edge_counts.png`: label and relationship count imbalance.
- `figures/fig02_schema_triple_network.png`: top source-label / edge / target-label structure.
- `figures/fig03_task_pair_disagreements.png`: task pairs where text and behavior embeddings disagree.
- `figures/fig04_tool_and_runtime_surfaces.png`: tool families plus job/studio runtime telemetry.
- `figures/fig05_spatial_and_storage_surfaces.png`: StatsMap region/concept load plus bounded storage files.
- `figures/fig06_panel_c_analytic_decision_space.png`: Panel C embedding of prod episode states.
- `figures/fig07_panel_d_feature_signatures.png`: Panel D small multiples of feature signatures over Panel C.
- `figures/fig08_kg_schema_triple_heatmap.png`: source-label x relationship / target-label schema triple heatmaps.
- `figures/fig09_full_schema_triple_atlas.png`: full canonical schema-triple concentration and source/target surface atlas.
- `figures/fig10_br_kg_3d_schema_browser.html`: interactive Neo4j/Bloom-style 3D schema graph browser.
- `figures/fig10_br_kg_3d_schema_browser_desktop.png`: desktop preview of the interactive schema graph.
- `figures/fig10_br_kg_3d_schema_browser_mobile.png`: mobile preview of the interactive schema graph.
- `figures/fig11_node_circle_pack.png`: node-type circle packing overview.
- `figures/fig12_edge_circle_pack.png`: relationship-type circle packing overview.
- `figures/fig13_schema_meta_graph.png`: dominant schema meta-graph over top canonical schema triples.
- `figures/fig14_edge_density_matrix.png`: top-label source x target edge density matrix.
- `figures/fig15_source_provenance_sankey.png`: measured upstream source/provenance flow into node labels.
- `figures/fig16a_brkg_literature_peak.png`: instance example, literature peak with coordinates/term/author anchors.
- `figures/fig16b_brkg_saved_statmap.png`: instance example, saved OpenNeuro statistical map with file/contrast/region/model anchors.
- `figures/fig16c_brkg_neurovault_asset.png`: instance example, NeuroVault map asset with collection/concept/file anchors.
- `figures/fig16d_brkg_task_construct.png`: instance example, task-to-construct and contrast links.
- `figures/fig16e_brkg_dataset_coverage.png`: instance example, dataset-to-repository/modality/task links.
- `figures/fig16f_brkg_tool_contract.png`: instance example, tool contract with version/family/modality/source anchors.
- `figures/fig17_brkg_multihop_query_path.png`: multi-hop BR-KG traversal example.
- `tables/br-kg_schema_inventory.html`: searchable comprehensive schema inventory tables.
- `tables/br-kg_schema_triples_comprehensive.csv`: main source/relationship/target schema-triple table.

## What To Separate

1. **Scientific KG structure**: labels, edge types, and schema triples. Do not mix this with job telemetry.
2. **Embedding maps**: task text/behavior embeddings and publication embeddings. Treat these as vector-space views, not graph-count views.
3. **Tool capability surface**: Tool, ToolVersion, ToolFamily, modality/resource edges. This is a capability taxonomy view.
4. **Spatial/statmap surface**: StatsMap, BrainRegion, Concept, TemplateSpace, Coordinate, NIfTI/map assets.
5. **Runtime/jobstore surface**: jobs, audit events, MCP runs, studio runtime sessions.

## Key Counts

- Top node label: `Coordinate` = 447,499.
- Top edge type: `BELONGS_TO` = 1,077,573.
- Embedding inventory: 23,865 `text` embeddings, model `BrainGPT-7B-v0.2`, dim 4096.
- StatsMap run surface: 35,240 statmaps across 18 distinct run values.
- Job states: succeeded=444, failed=193.
- MCP run directories: 2,338.

## KG Schema Triple Heatmap

- Top schema-triple rows used: n=100 bounded prod triples.
- Edge count represented in those rows: 2,422,891.
- Dominant triple: `StatisticalMap -[BELONGS_TO]-> Collection` = 1,075,385 edges (44.4% of represented top-triple edges).
- Heatmap table: `data/kg_schema_triple_heatmap.csv`.
- Interpretation: BR-KG is not a homogeneous graph; its largest surfaces are source-specific schema blocks such as map membership, publication terms/coordinates, and StatsMap spatial/model relations.
- Top source labels by represented edges: StatisticalMap=1,084,170, Publication=889,919, StatsMap=312,829, Task=88,106, Tool=12,428.
- Top relationship types by represented edges: BELONGS_TO=1,077,573, HAS_COORDINATE=447,499, HAS_TERM=358,050, IN_REGION=121,261, ABOUT=75,912.

## Full KG Schema Triple Atlas

- Canonical label-set schema triples: n=151, edge sum=2,423,334.
- Edge concentration: top-1=44.4%, top-3=77.6%, top-10=93.4%.
- Triples needed to cover graph mass: 90%=8, 95%=12, 99%=36.
- Atlas metrics: `data/kg_schema_full_atlas_metrics.json`.
- Canonical export: `data/kg_schema_triples_full_labelsets.csv`.
- Heatmap-friendly export: `data/kg_schema_triples_full_unwound_labels.csv`.
- Interpretation: the full graph is dominated by a small number of typed schema surfaces, so paper figures should use schema blocks and Pareto concentration rather than a node-link network.

## Interactive 3D BR-KG Schema Graph

- Browser artifact: `figures/fig10_br_kg_3d_schema_browser.html`.
- Graph data: `data/fig10_br_kg_3d_schema_graph_data.json`.
- Visual encoding: node size = incident schema edge mass; node color = schema surface; edge width, arrows, and particles = canonical schema-triple edge count.
- Default view: top 80 schema triples with slider support from 12 to 151 triples.
- Validation: rendered with Playwright at 1600x1000 and 390x844; both screenshots had nonblank canvas/content pixel checks.
- Interpretation: this gives a polished graph-exploration view while still avoiding a raw millions-edge hairball.

## Comprehensive Schema Inventory Tables

- Searchable table browser: `tables/br-kg_schema_inventory.html`.
- Main supplement-style table: `tables/br-kg_schema_triples_comprehensive.csv`.
- Supporting tables: `tables/br-kg_labelset_nodes_inventory.csv`, `tables/br-kg_node_labels_inventory.csv`, `tables/br-kg_relationship_types_inventory.csv`, and `tables/br-kg_source_target_surfaces.csv`.
- Data dictionary: `tables/br-kg_schema_inventory_data_dictionary.md`.
- Shape: 151 canonical schema triples, 71 label-set nodes, 75 single node labels, 85 relationship types, and 129 source-target surface blocks.
- Interpretation: use the schema triple table as the comprehensive source -> relationship -> target inventory, and use the node/relationship tables as dictionaries for node type and edge type interpretation.
- Caveat: these are schema-level tables. A raw instance-level edge export would contain 2,423,334 rows and should be produced separately only if needed for auditing.

## Fancy BR-KG Overview Panels

- Node circle pack: 75 node labels grouped by broad source/category; area encodes prod node count; sidebar shows total mass, dominant label, category share, and top surfaces.
- Edge circle pack: 85 relationship types grouped by semantic role; area encodes prod edge count; sidebar shows total mass, dominant relation, category share, and top surfaces.
- Schema meta-graph: 27 canonical label-set nodes and top 38 schema triples by edge mass.
- Edge density matrix: top 18 node labels by count, with cells as unwound source-label x target-label edge counts.
- Source provenance Sankey: 25 grouped source -> node-label flows from measured prod `source`/`provenance`/`data_origin`-like properties.
- Overview data: `data/br-kg_overview_panel_data.json`.
- Source/provenance probe: `data/br-kg_source_values_probe.json`.
- Interpretation: use the circle packs as "what is inside", the meta-graph as "how the dominant schema connects", the matrix as "where edge mass concentrates", and the Sankey as "where the KG comes from".
- Caveat: Sankey source names are canonicalized from multiple source/provenance-like properties; this is provenance-structure evidence, not a full raw node export.

## BR-KG Instance Example Gallery

- Individual example figures: `figures/fig16a_brkg_literature_peak.png` through `figures/fig16f_brkg_tool_contract.png`, each with matching `.svg`.
- Multi-hop path figure: `figures/fig17_brkg_multihop_query_path.png` / `.svg`.
- Example data: `data/brkg_instance_gallery_examples.json`.
- Source probes: `data/brkg_instance_property_probe.json`, `data/brkg_instance_path_probe.json`, `data/brkg_poldrack_publication_probe.json`, `data/brkg_instance_dataset_probe.json`, `data/brkg_instance_task_probe.json`, `data/brkg_instance_multihop_probe.json`, and `data/brkg_instance_multihop_alt_probe.json`.
- Included examples: literature peak, saved OpenNeuro statistical map, NeuroVault map asset, task-to-construct links, dataset coverage, and tool/workflow contract.
- Multi-hop path: `OpenNeuro -> Myconnectome -> n-back task -> updating`, selected to avoid redundant dataset/task names.
- Styling: light-background, one example per panel; the previous dark combined gallery was removed to avoid cramming multiple examples into one figure.
- Interpretation: this complements the type-level overview by showing concrete, recognizable instance paths through the graph.
- Caveat: gray nodes in the gallery are property-derived file/source callouts; the Russell Poldrack author label is derived from the publication `authors` field because prod did not expose a separate Poldrack `Author` node in the bounded probe.

## Task Embedding Diagnostic

- Task text embeddings: n=44, dim=384.
- Task behavior embeddings: n=44, dim=4096.
- Pairwise text-vs-behavior distance agreement: Spearman rho=0.666.
- Shared nearest-neighbor fraction: top-3=0.636, top-5=0.523.
- Interpretation: the useful view is task-pair disagreement, not clusters.
- Full task-pair table: `data/task_embedding_pair_disagreements.csv`.

Top text-close / behavior-far pairs:
- `Associative Recognition (Intact vs Rearranged)` <-> `Recent Probes` (rank gap 0.846)
- `Recent Probes` <-> `associative recognition` (rank gap 0.845)
- `associative recognition` <-> `recent probes task` (rank gap 0.833)
- `Associative Recognition (Intact vs Rearranged)` <-> `recent probes task` (rank gap 0.830)
- `Verbal Digit/Letter WM` <-> `associative recognition` (rank gap 0.816)

Top behavior-close / text-far pairs:
- `Unidimensional Threshold Rule` <-> `Weather Prediction Task (Cards)` (rank gap 0.577)
- `Unidimensional Threshold Rule` <-> `weather prediction task` (rank gap 0.553)
- `Contextual Bandit` <-> `Unidimensional Threshold Rule` (rank gap 0.542)
- `Two-Armed Bandit` <-> `weather prediction task` (rank gap 0.537)
- `category learning task` <-> `exp4` (rank gap 0.535)

## Panel C Analytic Decision Space

- Prod episode-state points: n=9198 across 11 inferred scientific regions.
- Sources: job_audit=6223, mcp_run=2338, job=637.
- Embedding method: UMAP; feature columns=101.
- Region structure diagnostic: silhouette=-0.059; mean top-5 same-region neighbor fraction=0.971.
- Episode-state table: `data/panel_c_prod_episode_states.csv`.
- Interpretation: this panel now uses real prod jobstore states, job-level records, and MCP run records rather than only hand-built route prototypes.
- Caveat: scientific region colors are inferred from job payload/run-artifact features; they are not human-curated labels.

## Panel D Feature Signatures

- Feature overlays: 10 signatures over 9,198 Panel C points.
- Feature table: `data/panel_d_feature_signatures.csv`.
- Included signatures: admissibility, provenance completeness, GSR sensitivity, HRF completeness, leakage risk, conflict density, review activity, memory reuse, OOD novelty, and backend robustness.
- Interpretation: feature intensity is spatially localized across the same UMAP background, so properties can be inspected independently of cluster labels.
- Caveat: these are proxy scores derived from available jobstore/run-artifact fields. GSR, HRF, leakage, and robustness should become direct route fields for a final paper panel.
- Mean proxy scores: admissibility_score=0.72, provenance_score=0.57, gsr_sensitivity_score=0.13, hrf_completeness_score=0.26, leakage_risk_score=0.16, conflict_density=0.23, review_activity=0.39, memory_reuse_score=0.25, ood_novelty_score=0.13, robustness_score=0.29.

## Caveats

- This is a bounded plot probe, not a full benchmark or a full data export.
- Publication embeddings are represented in inventory and graph links here; raw publication vector extraction was intentionally not pulled into this first pack.
- OpenNeuro paths are mounted by `s3fs`; broad recursive scans were avoided.
