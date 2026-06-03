## BR-KG Tool Schema (Tool / ToolVersion / ToolRun)

**Status:** Implemented (schemas live under `configs/br-kg/schema/`)

### Node Labels
- **Tool** (`tool_id`, `name`, `domain`, `runtime_kind`, `description`, `homepage_url`, `repo_url`, `status`)
- **ToolVersion** (`version_id`, `semver`, `commit_sha`, `container_image`, `container_digest`, `python_module`, `python_function`, `created_at`)
- **ToolRun** (optional) (`run_id`, `job_id`, `started_at`, `finished_at`, `status`, `parameters_json`, `runtime_kind`)

### Relationships
- `(:Tool)-[:HAS_VERSION]->(:ToolVersion)`
- `(:ToolVersion)-[:CONSUMES_RESOURCE]->(:ResourceType)`
- `(:ToolVersion)-[:PRODUCES_RESOURCE]->(:ResourceType)`
- `(:Tool)-[:SUPPORTS_MODALITY]->(:Modality)`
- `(:Tool)-[:IMPLEMENTS_FAMILY]->(:TaskFamily)`
- `(:ToolRun)-[:EXECUTED_VERSION]->(:ToolVersion)`
- `(:ToolRun)-[:USED_RESOURCE]->(:DataResource)`
- `(:ToolRun)-[:GENERATED_RESOURCE]->(:DataResource)`

### Ingestion Command
```
br br-kg ingest tools-catalog \
  --catalog configs/catalog/capabilities.yaml \
  --evidence configs/br-kg/tool_evidence.yaml
```

### File Pointers
- Schema YAMLs: `configs/br-kg/schema/tool.yaml`, `tool_version.yaml`, `tool_run.yaml`
- Source config: `configs/br-kg/sources/tools_catalog.yaml`
- Loader: `src/brain_researcher/services/br_kg/loader/tools_catalog_loader.py`
- CLI entry: `src/brain_researcher/cli/commands/br_kg_ingest.py`
