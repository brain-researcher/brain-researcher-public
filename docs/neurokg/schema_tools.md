# Tool / Planner Layer Schema (BR-KG)

This schema captures the agent’s tool + intent layer inside Neo4j.
It is populated by:

- `configs/catalog/intents.yaml`
- `configs/legacy/mappings/intent_synonyms.yaml`
- Catalog capabilities (curated + python-generated + NiWrap + MCP)
- `scripts/tools/etl/kg_extract_tools.py` + `scripts/tools/etl/kg_ingest_tools.py`

---

## Node Labels

### :Operation
- `id` (string) – intent id, e.g., `"dmri_tractography"`
- `name`
- `description`
- `domains`
- `modalities`
- `analysis_level`
- `source` (e.g., `"agent_intents/v1"`)

### :OperationSynonym
- `text` (lowercased phrase)
- `lang` (e.g., `"en"`, `"mixed"`)
- `kind` (e.g., `"natural_language"`, `"tool_name"`)
- `source` (e.g., `"intent_synonyms.yaml"`)

### :ToolFamily
- `id` (e.g., `fsl`, `afni`, `mrtrix3`, `bidsapps`, `niwrap_generic`)
- `name`
- `runtime_kinds` (list of `"python"`, `"container"`, `"mcp"`)
- `packages` (list of package prefixes)
- `source` (e.g., `"catalog_capabilities/v1"`)

### :Tool
- `id` (capability id, e.g., `"container.mrtrix.tckgen.run"`)
- `name`
- `package`
- `runtime_kind` (`"python"`, `"container"`, `"mcp"`)
- `entrypoint` (NiWrap command, if container)
- `modality`
- `is_niwrap` (bool)
- `is_curated` (bool)
- `source` (e.g., `"catalog_capabilities/v1"`)

### :PipelineTemplate
- `id` (e.g., `"pipeline.fmriprep"`)
- `name`
- `description`
- `source` (e.g., `"kg_mapping_pipeline_templates"`)

---

## Relationships

- `(:OperationSynonym)-[:ALIAS_OF]->(:Operation)`
- `(:Operation)-[:PARENT_OF]->(:Operation)`
- `(:Tool)-[:BELONGS_TO_FAMILY]->(:ToolFamily)`
- `(:Tool)-[:IMPLEMENTS]->(:Operation)`
- `(:ToolFamily)-[:IMPLEMENTS]->(:Operation)` with `tool_count`
- `(:PipelineTemplate)-[:HAS_STEP]->(:Operation)`
- `(:PipelineTemplate)-[:USES_FAMILY]->(:ToolFamily)`

---

## Example Cypher Queries

### Families implementing a given operation
```cypher
MATCH (o:Operation {id:"dmri_tractography"})<- [r:IMPLEMENTS]-(f:ToolFamily)
RETURN o.id AS operation, f.id AS family, f.runtime_kinds AS runtimes, r.tool_count AS tool_count
ORDER BY family;
```

### Concrete tools for skull stripping
```cypher
MATCH (o:Operation {id:"skull_strip_mri"})<-[:IMPLEMENTS]-(t:Tool)
MATCH (t)-[:BELONGS_TO_FAMILY]->(f:ToolFamily)
RETURN t.id, t.runtime_kind, f.id AS family, t.package, t.is_niwrap, t.is_curated
ORDER BY t.is_niwrap DESC, family, t.id
LIMIT 50;
```

### Pipelines that include an operation
```cypher
MATCH (p:PipelineTemplate)-[:HAS_STEP]->(o:Operation {id:"dmri_tractography"})
OPTIONAL MATCH (p)-[:USES_FAMILY]->(f:ToolFamily)
RETURN p.id AS pipeline, p.name AS pipeline_name, collect(DISTINCT f.id) AS preferred_families;
```

### Skeleton of a pipeline template
```cypher
MATCH (p:PipelineTemplate {id:"pipeline.tractography"})
OPTIONAL MATCH (p)-[:HAS_STEP]->(o:Operation)
OPTIONAL MATCH (p)-[:USES_FAMILY]->(f:ToolFamily)
RETURN p.id AS pipeline, p.name AS name,
       collect(DISTINCT o.id) AS operations,
       collect(DISTINCT f.id) AS preferred_families;
```

### Phrase → operations → families
```cypher
MATCH (s:OperationSynonym)-[:ALIAS_OF]->(o:Operation)
WHERE toLower(s.text) CONTAINS "tckgen"
OPTIONAL MATCH (f:ToolFamily)-[:IMPLEMENTS]->(o)
RETURN s.text AS synonym, o.id AS operation, collect(DISTINCT f.id) AS families;
```

### Operation × family coverage
```cypher
MATCH (f:ToolFamily)-[r:IMPLEMENTS]->(o:Operation)
RETURN o.id AS operation, f.id AS family, r.tool_count AS tools
ORDER BY operation, family;
```
