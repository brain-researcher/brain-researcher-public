# NeuroKG Schema Inventory Data Dictionary

These tables are generated from the full prod NeuroKG schema-triple export.
Canonical schema triples preserve graph edge cardinality exactly; unwound node-label tables count multi-label endpoints once per component label.

## Files

- `neurokg_schema_triples_comprehensive.csv`: one row per canonical schema triple.
- `neurokg_labelset_nodes_inventory.csv`: one row per canonical label-set node used in the schema graph.
- `neurokg_node_labels_inventory.csv`: one row per Neo4j node label.
- `neurokg_relationship_types_inventory.csv`: one row per Neo4j relationship type.
- `neurokg_source_target_surfaces.csv`: one row per source-label-set / target-label-set surface block.
- `neurokg_schema_inventory.html`: searchable browser version of the same tables.

## Recommended Main Supplement Table

Use `neurokg_schema_triples_comprehensive.csv` as the main comprehensive table. Key columns:

- `schema_triple_id`, `rank`: stable row identifiers sorted by edge mass.
- `source_node_type`, `source_surface`: source label-set and coarse scientific surface.
- `relationship_type`, `relationship_edge_count_total`: edge type and total edge count for that relationship.
- `target_node_type`, `target_surface`: target label-set and coarse scientific surface.
- `edge_count`, `schema_triple_share_of_graph`: edge mass for this exact schema triple.
- `schema_triple_share_of_relationship`: how much of that relationship type is explained by this source-target pair.
- `source_component_node_counts`, `target_component_node_counts`: component label counts for interpreting multi-label label sets.

## Table Shapes

- `schema_triples`: 151 rows x 31 columns.
- `labelset_nodes`: 71 rows x 17 columns.
- `node_labels`: 75 rows x 12 columns.
- `relationship_types`: 85 rows x 12 columns.
- `source_target_surfaces`: 129 rows x 10 columns.
