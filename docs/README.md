# Documentation

This directory contains active documentation, release checks, and historical reference material for Brain Researcher. Public readers should start from [`docs/index.md`](index.md); archived files are retained for provenance and are not part of the shipped public surface.

## Directory Structure

- **/api/**: API, CLI, MCP, and tool metadata references.

- **/architecture/**: Houses high-level design documents, architectural decision records (ADRs), and diagrams that explain the overall structure of the system.
  - Tool KG schema: see `docs/services/neurokg/kg_tool_schema.md` for Tool/ToolVersion/ToolRun nodes and ingest command.
  - Code graph folder order: see `docs/architecture/code_graph_folder_order.md` for the dependency-aware package ordering and cycle-breaking plan.

- **/services/**: Service-specific implementation notes and integration runbooks.
  - BR-KG OpenMed GWAS ingest: see `docs/services/neurokg/openmed_gwas_metadata_ingest.md` for the metadata-only Hugging Face ingest, normalized Population nodes, and live Neo4j status.

- **/guides/**: Includes practical, step-by-step guides for developers and users on topics like installation, local development setup, deployment, and testing procedures.

- **/issues/**: Historical or task-specific issue notes when present. Current repository guidance lives in [`../AGENTS.md`](../AGENTS.md); active roadmap material lives in `docs/planning/` and `configs/planning/`.

- **/planning/**: Contains documents related to current and future work, such as project roadmaps, feature specifications, and sprint plans.
  - Active roadmap: see `docs/planning/roadmap.md` and `configs/planning/active_tracks.yaml` for the current cross-session priority view.

- **/release/**: Release-gate reports and public-surface status summaries.
- **/review/**: Review packets, failure-mode registries, and cleanup ledgers.

- **/archive/**: A central archive for all other types of documentation that are outdated but kept for historical reference.
- **Checklists**: Operational runbooks for critical paths.
  - UI wiring checklist: see `docs/UI_WIRING_CHECKLIST.md` for Next <-> Agent <-> BR-KG connectivity expectations.
