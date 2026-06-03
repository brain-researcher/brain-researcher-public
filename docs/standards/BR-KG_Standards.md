# BR-KG Standards Starter Pack — v0 Skeleton

> Drop these files into your repo to lock down IDs, mappings, thresholds, scoring, and validation. All files are **skeletons** with comments and examples — edit freely.

---

## docs/standards/ids.md

### Purpose

Define global identifiers, idempotent keys, and entity merge strategy so every loader/linker behaves consistently.

### ID Conventions

* **CURIE**: `<namespace>:<external_id>` (examples below)
* **Canonical ID**: `canonical_id` (stable across merges)
* **Idempotent Key**: `id_hash = sha1(type | source | external_id)`
* **Namespaces**: `pmid:`, `doi:`, `cogat:`, `nv:`, `ns:`, `bm:`, `openneuro:`, `hcp:`, `abcd:`, `schaefer400-7n:`, `yeo17:`, etc.

### Examples

* Publication: `pmid:31234567`, `doi:10.1038/s41562-020-0890-6`
* Task: `cogat:TRM_4a3fd79d0a5c8`
* StatisticalMap: `nv:collection_123/image_456`
* Region: `schaefer400-7n:L_Cont_7`

### Generation Rules

1. Prefer trusted external IDs (DOI/PMID/Atlas IDs).
2. If absent, create `id_hash` using deterministic fields.
3. All loaders **must upsert** by `(type, curie) OR id_hash`.

### SAME\_AS & Aliases

* Merge duplicates by writing `SAME_AS` to canonical node and storing `aliases[]`.
* Canonical selection priority: external authority > older canonical > higher evidence score.

### Versioning

* Nodes/edges: `valid_from`, `valid_to`, `updated_at`, `loader_version`.

---

## docs/standards/merge\_policies.md

### When to Auto‑Merge

* Exact DOI/PMID match.
* Task/Concept names with **string\_sim ≥ thresholds.linker.string\_similarity\_min** and same source context.

### When to Queue for Review

* Conflicting titles/authors/year.
* Cross‑language or transliterated names.

### Merge Procedure

1. Compute candidate set (blocking by year/journal/source).
2. Score with features (exact IDs, title sim, author Jaccard, venue, NiCLIP text sim).
3. If score ≥ auto threshold → merge; else → **curation queue**.
4. On merge: keep canonical node; attach `SAME_AS` edges; unify properties; append `aliases[]`; write PROV.

### Split/Undo

* Maintain audit log; support **graph snapshot** restore; provide split UI to detach `SAME_AS` and revert properties.

---

## docs/standards/provenance.md

### EdgeProvInput (contract)

```json
{
  "source": "brainmap|neurosynth|cognitive_atlas|neurovault|openneuro|wikidata|manual",
  "method": "exact_id|string_match|embedding_match|spatial_overlap|rule|manual",
  "confidence": 0.0,
  "evidence_components": {
    "literature_count": 0,
    "z_overlap": 0.0,
    "niclip_cos": 0.0,
    "user_feedback": 0.0
  },
  "loader_version": "v0.0",
  "params_hash": "sha1(...)",
  "timestamp": "ISO-8601"
}
```

### Node/Edge Common PROV

* `created_by`, `updated_by`, `activity_id`, `input_hash`, `notes`.

---

## mappings/task\_synonyms.yaml

```yaml
# Map source/alias names to a canonical Task label.
# Add more entries as needed.
- canonical: "n-back"
  cognitive_atlas_id: "cogat:TRM_4a3fd79d0a5c8"
  task_id: "task:n-back"
  synonyms: ["N back", "Nback", "working memory n-back"]
  source_aliases:
    brainmap: ["N-BACK WM"]
    neurosynth: ["nback"]

- canonical: "Sternberg memory"
  cognitive_atlas_id: "cogat:TRM_5535dd0a8e4ce"
  task_id: "task:sternberg_memory"
  synonyms: ["Sternberg", "Sternberg WM"]
  source_aliases:
    brainmap: ["STERNBERG"]

- canonical: "Go/No-Go"
  cognitive_atlas_id: "cogat:TRM_4d559bcd67c18"
  task_id: "task:go_no-go"
  synonyms: ["Go-NoGo", "Go No Go", "GNG"]

- canonical: "Flanker"
  cognitive_atlas_id: "cogat:TRM_4d559bcd67c19"
  task_id: "task:flanker"
  synonyms: ["Eriksen Flanker", "Flanker Task"]
```

> **Alias map note:** `scripts/neurostore_task/taxonomy/alias_map.json` now maps
> individual lowercase aliases directly to canonical labels (e.g.,
> `"n back": "n-back"`). Remove any legacy `comment_*` rows if you maintain the
> mapping manually.

---

## mappings/paradigm\_to\_task.yaml

```yaml
# Map paradigm labels from each source to the canonical Task.
- source: brainmap
  paradigm: "Sternberg"
  maps_to_task: "Sternberg memory"

- source: brainmap
  paradigm: "N-BACK WM"
  maps_to_task: "n-back"

- source: neurosynth
  paradigm: "gng"
  maps_to_task: "Go/No-Go"
```

---

## mappings/contrast\_normalization.yaml

```yaml
# Normalize heterogeneous contrast expressions to canonical shortforms.
- pattern: "(2-back) minus (0-back)"
  canonical: "2back>0back"
  polarity: "positive"
  task_hint: "n-back"

- pattern: "Incongruent - Congruent"
  canonical: "incongruent>congruent"
  polarity: "positive"
  task_hint: "Flanker"

- pattern: "NoGo - Go"
  canonical: "nogo>go"
  polarity: "positive"
  task_hint: "Go/No-Go"
```

---

## mappings/roi\_crosswalk.yaml

```yaml
# Minimal crosswalk between atlases; expand via scriptable generator later.
- from: {atlas: "schaefer400-7n", region: "L_Cont_7"}
  to:
    - {atlas: "yeo17", network: "Control_A"}
    - {atlas: "HO", region: "Middle Frontal Gyrus"}

- from: {atlas: "schaefer400-7n", region: "R_Default_15"}
  to:
    - {atlas: "yeo17", network: "Default_C"}
```

---

## registries/coordinate\_systems.yaml

```yaml
# Register template spaces and transformation requirements.
default: "MNI152_2009c"
systems:
  - name: "MNI152_2009c"
    voxel: [2, 2, 2]
    orientation: "RAS"
    transform_chain_required: true
    notes: "Preferred analysis space."

  - name: "MNI152_2006"
    voxel: [2, 2, 2]
    orientation: "RAS"

  - name: "Talairach"
    voxel: [2, 2, 2]
    orientation: "RAS"
    transforms:
      - {from: "MNI152_2009c", method: "icbm2tal", version: "Lancaster2007"}
```

---

## configs/thresholds.yaml

```yaml
linker:
  string_similarity_min: 0.86   # cosine/Jaro-Winkler tuned via validation set
  niclip_cos_min: 0.32          # embedding similarity floor
  auto_merge_min_score: 0.92    # overall fusion score to auto-merge
  human_review_range: [0.75, 0.92]

spatial:
  roi_overlap_min_frac: 0.15    # min fractional overlap to assert IN_REGION
  peak_to_roi_max_mm: 6.0       # max distance for peak assignment
  min_voxels_overlap: 20

imports:
  max_api_qps: 5
  retry_backoff_ms: 250
```

---

## configs/edge\_scoring.yaml

```yaml
# Interpretable strength/confidence configuration.
weights:
  literature_count: 0.35
  z_overlap: 0.30
  niclip_cos: 0.25
  user_feedback: 0.10

logistic:
  intercept: -1.0
  cap_min: 0.05
  cap_max: 0.99

freshness:
  half_life_days: 720   # ~2 years
  min_factor: 0.6

# Example: strength = σ(intercept + Σ w_i * feature_i) * freshness_factor
features:
  literature_count: {transform: "log1p", scale: 1.0}
  z_overlap: {transform: "identity", scale: 1.0}
  niclip_cos: {transform: "identity", scale: 1.0}
  user_feedback: {transform: "identity", scale: 1.0}
```

---

## shacl/nodes\_shapes.ttl

```ttl
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix kg: <http://br-kg.org/schema#> .

# Node Shapes (minimal)
kg:TaskShape a sh:NodeShape ;
  sh:targetClass kg:Task ;
  sh:property [ sh:path kg:id ; sh:datatype xsd:string ; sh:minCount 1 ; sh:pattern "^[a-z]+:.+" ] ;
  sh:property [ sh:path kg:name ; sh:datatype xsd:string ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:synonyms ; sh:datatype xsd:string ; sh:minCount 0 ] .

kg:ConceptShape a sh:NodeShape ;
  sh:targetClass kg:Concept ;
  sh:property [ sh:path kg:id ; sh:datatype xsd:string ; sh:minCount 1 ; sh:pattern "^[a-z]+:.+" ] ;
  sh:property [ sh:path kg:label ; sh:datatype xsd:string ; sh:minCount 1 ] .

kg:RegionShape a sh:NodeShape ;
  sh:targetClass kg:Region ;
  sh:property [ sh:path kg:id ; sh:datatype xsd:string ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:atlas ; sh:datatype xsd:string ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:name ; sh:datatype xsd:string ; sh:minCount 1 ] .

kg:PublicationShape a sh:NodeShape ;
  sh:targetClass kg:Publication ;
  sh:property [ sh:path kg:id ; sh:datatype xsd:string ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:title ; sh:datatype xsd:string ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:year ; sh:datatype xsd:integer ; sh:minCount 0 ] .

kg:CoordinateShape a sh:NodeShape ;
  sh:targetClass kg:Coordinate ;
  sh:property [ sh:path kg:x ; sh:datatype xsd:integer ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:y ; sh:datatype xsd:integer ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:z ; sh:datatype xsd:integer ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:space ; sh:datatype xsd:string ; sh:minCount 1 ] .

kg:StatisticalMapShape a sh:NodeShape ;
  sh:targetClass kg:StatisticalMap ;
  sh:property [ sh:path kg:id ; sh:datatype xsd:string ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:space ; sh:datatype xsd:string ; sh:minCount 1 ] ;
  sh:property [ sh:path kg:modality ; sh:datatype xsd:string ; sh:minCount 1 ] .
```

---

## shacl/edges\_shapes.ttl

```ttl
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix kg: <http://br-kg.org/schema#> .

# Relationship constraints (RDF-style). Adjust predicates to your export mapping.

kg:TaskMeasuresConcept a sh:NodeShape ;
  sh:targetClass kg:Task ;
  sh:property [ sh:path kg:MEASURES ; sh:class kg:Concept ; sh:minCount 1 ] .

kg:TaskActivatesSpatialTarget a sh:NodeShape ;
  sh:targetClass kg:Task ;
  sh:property [ sh:path kg:ACTIVATES ; sh:class kg:BrainRegion ; sh:minCount 0 ] .

kg:PublicationHasCoordinate a sh:NodeShape ;
  sh:targetClass kg:Publication ;
  sh:property [ sh:path kg:HAS_COORDINATE ; sh:class kg:Coordinate ; sh:minCount 0 ] .

kg:StatsMapInBrainRegion a sh:NodeShape ;
  sh:targetClass kg:StatsMap ;
  sh:property [ sh:path kg:IN_REGION ; sh:class kg:BrainRegion ; sh:minCount 0 ] .

kg:BrainRegionPartOfBrainRegion a sh:NodeShape ;
  sh:targetClass kg:BrainRegion ;
  sh:property [ sh:path kg:PART_OF ; sh:class kg:BrainRegion ; sh:minCount 0 ] .

kg:CoordinateInRegionLegacy a sh:NodeShape ;
  sh:targetClass kg:Coordinate ;
  sh:property [ sh:path kg:IN_REGION ; sh:class kg:Region ; sh:minCount 0 ] .

kg:MapDerivedFromPub a sh:NodeShape ;
  sh:targetClass kg:StatisticalMap ;
  sh:property [ sh:path kg:DERIVED_FROM ; sh:class kg:Publication ; sh:minCount 0 ] .
```

---

## tests/golden\_queries.json

```json
[
  {
    "id": "GQ-001",
    "title": "Working memory → prefrontal regions",
    "query_type": "cypher",
    "query": "MATCH (t:Task {name:'n-back'})-[:MEASURES]->(c:Concept)<-[:MEASURES]-(t2) OPTIONAL MATCH (t)-[:ACTIVATES]->(r:Region) RETURN t,c,collect(DISTINCT r) AS rois LIMIT 200",
    "expected": {
      "must_include_nodes": [
        {"label": "Task", "name": "n-back"}
      ],
      "min_nodes": 5,
      "max_latency_ms": 300
    }
  },
  {
    "id": "GQ-002",
    "title": "StatsMap → BrainRegion canonical spatial path",
    "query_type": "cypher",
    "query": "MATCH (m:StatsMap)-[:IN_REGION]->(r:BrainRegion) RETURN m, r LIMIT 200",
    "expected": {"min_edges": 10, "max_latency_ms": 400}
  },
  {
    "id": "GQ-003",
    "title": "Dataset→Contrast implements canonical task",
    "query_type": "cypher",
    "query": "MATCH (d:Dataset)-[:IMPLEMENTS_TASK]->(t:Task) RETURN d,t LIMIT 200",
    "expected": {"min_nodes": 4}
  },
  {
    "id": "GQ-004",
    "title": "Top regions for n-back (by strength)",
    "query_type": "cypher",
    "query": "MATCH (:Task {name:'n-back'})-[e:ACTIVATES]->(r) WHERE r:BrainRegion OR r:Region RETURN r, e.strength AS s ORDER BY s DESC LIMIT 20",
    "expected": {"min_nodes": 5}
  },
  {
    "id": "GQ-005",
    "title": "Crosswalk sanity: ROI mapping exists",
    "query_type": "graphQL",
    "query": "{ crosswalk(from:{atlas:\"schaefer400-7n\", region:\"L_Cont_7\"}) { to { atlas name network } } }",
    "expected": {"must_include_text": ["yeo17"]}
  }
]
```

---

## NL Query Orchestrator Query-Type Support

`NaturalLanguageQueryOrchestrator` is **Cypher-first** by default.

- `query_type=cypher`: supported and executed against the configured graph backend.
- `query_type=sparql`: requires a configured production `sparql_executor`.
- `create_nl_query_orchestrator(neo4j_db=...)` auto-wires a production SPARQL executor by default.
  - `BR_NLQ_SPARQL_ENABLE_FEDERATION` controls SPARQL federation for this auto-wired path (`1` default).
- If no `sparql_executor` is configured, the orchestrator returns an explicit unsupported response:

```json
{
  "success": false,
  "error_code": "not_supported",
  "not_supported": {
    "query_type": "sparql",
    "supported_query_types": ["cypher"],
    "message": "query_type=sparql is not supported in NaturalLanguageQueryOrchestrator without a configured sparql_executor"
  }
}
```

---

## Quick Integration Notes

* Put YAML/TTL/JSON exactly under the listed paths.
* Wire `configs/thresholds.yaml` & `configs/edge_scoring.yaml` into your linker and strength calculators.
* Add CI step: run SHACL validation + Golden Queries; fail build on violations.
* Evolve `mappings/*` continuously — treat them as **versioned data contracts**.

---

## mappings/roi\_synonyms.yaml

```yaml
# Canonical ROI names with multilingual and stylistic variants.
# Used by CrossSourceLinker and ROI resolvers before atlas crosswalk.
# Normalize using configs/string_normalization.yaml first, then match.

- canonical: "insula"
  synonyms: ["insular cortex", "insulae", "岛叶", "島葉"]
  notes: "Left/right handled by atlas label; keep bare canonical generic."

- canonical: "anterior cingulate cortex"
  synonyms: ["ACC", "rostral cingulate", "前扣带皮层"]

- canonical: "posterior cingulate cortex"
  synonyms: ["PCC", "后扣带皮层"]

- canonical: "precuneus"
  synonyms: ["pre-cuneus", "楔前叶"]

- canonical: "middle frontal gyrus"
  synonyms: ["MFG", "中额回", "mid frontal gyrus"]

- canonical: "inferior parietal lobule"
  synonyms: ["IPL", "下顶叶", "angular/supramarginal complex"]

- canonical: "angular gyrus"
  synonyms: ["ANG", "角回"]

- canonical: "supramarginal gyrus"
  synonyms: ["SMG", "缘上回"]

- canonical: "superior temporal gyrus"
  synonyms: ["STG", "上颞回"]

- canonical: "fusiform gyrus"
  synonyms: ["FG", "梭状回", "occipitotemporal gyrus"]

- canonical: "amygdala"
  synonyms: ["AMY", "扁桃体", "amygdaloid complex"]

- canonical: "hippocampus"
  synonyms: ["HPC", "海马", "hippocampal formation"]

# Add more as needed; prefer lowercase canonical English with precise anatomical term.
```

---

## mappings/concept\_synonyms.yaml

```yaml
# Canonical cognitive/affective constructs with common aliases.
# Align these to Cognitive Atlas IDs when available via `id`.

- id: "cogat:WM"
  canonical: "working memory"
  synonyms: ["WM", "短时工作记忆", "active maintenance"]

- id: "cogat:CC"
  canonical: "cognitive control"
  synonyms: ["executive control", "认知控制", "cognitive flexibility"]

- id: "cogat:INHIB"
  canonical: "response inhibition"
  synonyms: ["inhibitory control", "抑制控制", "impulse control"]

- id: "cogat:ATTN"
  canonical: "attention"
  synonyms: ["selective attention", "注意", "attentional focus"]

- id: "cogat:LANGCOMP"
  canonical: "language comprehension"
  synonyms: ["sentence processing", "语言理解"]

- id: "cogat:REWARD"
  canonical: "reward processing"
  synonyms: ["valuation", "奖励加工", "reinforcement"]

- id: "cogat:EMOREG"
  canonical: "emotion regulation"
  synonyms: ["reappraisal", "情绪调节"]

- id: "cogat:VISATTN"
  canonical: "visual attention"
  synonyms: ["covert attention", "视觉注意"]
```

---

## mappings/journal\_abbrev.yaml

```yaml
# Journal abbreviations → metadata. Use ISSN-L where possible.
# Keys are primary abbreviations; `alt_abbrevs` provides matching variants.

"PNAS":
  full: "Proceedings of the National Academy of Sciences"
  issn_print: "0027-8424"
  issn_electronic: "1091-6490"
  alt_abbrevs: ["Proc Natl Acad Sci USA", "Proc Natl Acad Sci U S A"]

"J Neurosci":
  full: "The Journal of Neuroscience"
  issn_print: "0270-6474"
  issn_electronic: "1529-2401"
  alt_abbrevs: ["J. Neurosci."]

"NeuroImage":
  full: "NeuroImage"
  issn_print: "1053-8119"
  issn_electronic: "1095-9572"
  alt_abbrevs: ["Neuroimage"]

"Hum Brain Mapp":
  full: "Human Brain Mapping"
  issn_print: "1065-9471"
  issn_electronic: "1097-0193"
  alt_abbrevs: ["Hum. Brain Mapp.", "Human Brain Mapp"]

"Nat Neurosci":
  full: "Nature Neuroscience"
  issn_print: "1097-6256"
  issn_electronic: "1546-1726"
  alt_abbrevs: ["Nat. Neurosci."]

"Nat Commun":
  full: "Nature Communications"
  issn_electronic: "2041-1723"
  alt_abbrevs: ["Nat. Commun."]

"Cereb Cortex":
  full: "Cerebral Cortex"
  issn_print: "1047-3211"
  issn_electronic: "1460-2199"

"Front Hum Neurosci":
  full: "Frontiers in Human Neuroscience"
  issn_electronic: "1662-5161"
  alt_abbrevs: ["Front. Hum. Neurosci."]

# Extend as needed; source authoritative ISSN from CrossRef/ISSN portal when available.
```

---

## docs/standards/data\_contracts.md

### Purpose

Define **idempotent, verifiable** I/O contracts for loaders and linkers to ensure stable incremental builds and safe replays.

### File Format

* **NDJSON** per dataset/source. One JSON object per line.
* UTF‑8, newline‑terminated. Max line size configurable; recommend ≤ 2MB.

### Record Types

1. **NodeRecord**

```json
{
  "record_type": "node",
  "entity_type": "Publication|Task|Concept|Region|Coordinate|Dataset|Subject|StatisticalMap|Contrast|SubjectGroup",
  "curie": "pmid:31234567",
  "id_hash": "sha1(type|source|external_id)",
  "properties": { "title": "...", "year": 2020, "name": "..." },
  "prov": { "source": "pubmed", "loader_version": "v0.0", "timestamp": "..." }
}
```

2. **EdgeRecord**

```json
{
  "record_type": "edge",
  "edge_type": "MEASURES|ACTIVATES|HAS_COORDINATE|IN_REGION|DERIVED_FROM|IMPLEMENTS_TASK|MAPS_TO|SAME_AS",
  "source_curie": "pmid:31234567",
  "target_curie": "schaefer400-7n:L_Cont_7",
  "properties": { "strength": 0.72, "confidence": 0.81, "evidence_components": {"literature_count": 12} },
  "prov": { "source": "brainmap", "method": "spatial_overlap", "timestamp": "..." }
}
```

### Idempotency & Upsert

* Nodes upsert by `(entity_type, curie)` or `id_hash` fallback.
* Edges upsert by `(edge_type, source_curie, target_curie, hash(properties_without_scores))`.
* Maintain **`valid_from/valid_to`** for temporal versioning; never hard‑delete in production.

### Validation (Pre‑ingest)

* **Schema**: JSON Schema validation per record type.
* **Required fields**: `record_type`, `entity_type`/`edge_type`, identifiers, `prov.source`.
* **String normalization**: apply `configs/string_normalization.yaml` before matching.

### Post‑ingest QA

* No dangling edges; unique IDs; degree sanity checks.
* SHACL validation on exported RDF view.

### Error Handling

* Write failures to `{source}.errors.ndjson` with `line`, `reason`, `payload`.
* Retries with exponential backoff; poison‑pill isolation after N failures.

### Metrics

* `nodes_created`, `nodes_updated`, `edges_created`, `edges_updated`, `duplicates_merged`, `curation_queue_size`.

---

## configs/string\_normalization.yaml

```yaml
# Deterministic text normalization pipeline applied before ER/matching.

pipeline:
  unicode: "NFC"           # NFC for stability; consider NFKC if width/compatibility issues dominate
  case_fold: true           # lower-case everything unless field override says otherwise
  trim_whitespace: true
  collapse_internal_space: true
  ascii_folding: true       # é→e, α→a (best-effort; do not fold Greek letters in math fields)
  punctuation_map:          # canonicalize common punctuation variants
    "–": "-"
    "—": "-"
    "‐": "-"
    "’": "'"
    "“": '"'
    "”": '"'
  remove_brackets_content: false

stopwords:
  generic: ["task", "test", "study", "experiment"]

overrides:
  # Field-specific rules
  title:
    stopwords: []
    ascii_folding: true
  author:
    case_fold: false        # keep original case for display; store a normalized shadow field
  roi_name:
    ascii_folding: false    # keep Greek letters; handled by roi_synonyms
  doi:
    punctuation_map: {}
    ascii_folding: false
    case_fold: false

tests:
  - input: "N–Back Task"
    expect: "n-back task"
  - input: "Eriksen  Flanker  Test"
    expect: "eriksen flanker test"
```

---

## configs/index\_plan.yaml

```yaml
# Declarative index & constraint plan for Neo4j 5.x. Used by a migrator to emit Cypher.

neo4j_version: "5.x"
apply_order: ["constraints", "node_indexes", "fulltext_indexes", "relationship_indexes"]

constraints:
  - name: "uniq_Task_id"
    type: "NODE_KEY"
    label: "Task"
    properties: ["id"]
  - name: "uniq_Concept_id"
    type: "NODE_KEY"
    label: "Concept"
    properties: ["id"]
  - name: "uniq_Publication_id"
    type: "NODE_KEY"
    label: "Publication"
    properties: ["id"]
  - name: "uniq_Region_id"
    type: "NODE_KEY"
    label: "Region"
    properties: ["id"]
  - name: "uniq_StatisticalMap_id"
    type: "NODE_KEY"
    label: "StatisticalMap"
    properties: ["id"]
  - name: "uniq_Dataset_id"
    type: "NODE_KEY"
    label: "Dataset"
    properties: ["id"]

node_indexes:
  - name: "idx_Task_name"
    label: "Task"
    properties: ["name"]
    type: "BTREE"
  - name: "idx_Concept_label"
    label: "Concept"
    properties: ["label"]
  - name: "idx_Publication_doi_pmid"
    label: "Publication"
    properties: ["doi", "pmid"]
  - name: "idx_Region_atlas_name"
    label: "Region"
    properties: ["atlas", "name"]
  - name: "idx_Coordinate_space"
    label: "Coordinate"
    properties: ["space"]
  - name: "idx_StatisticalMap_space_modality"
    label: "StatisticalMap"
    properties: ["space", "modality"]

fulltext_indexes:
  - name: "kgNodeFulltext"
    labels: ["Task", "Concept", "CognitiveConcept", "OntologyConcept", "Term", "ONVOC", "Dataset", "Publication", "Region", "BrainRegion", "Tool", "Atlas", "TemplateSpace", "Parcellation", "Parcel"]
    properties: ["name", "label", "title", "aliases", "synonyms", "keywords", "description", "definition", "id", "dataset_id", "uid", "identifier", "tool_id", "op_key", "atlas", "journal", "authors", "pmid", "doi"]
  - name: "ft_Task_Concept"
    labels: ["Task", "Concept"]
    properties: ["name", "label", "synonyms"]
  - name: "ft_Publication"
    labels: ["Publication"]
    properties: ["title", "journal", "authors"]
  - name: "ft_Region"
    labels: ["Region"]
    properties: ["name", "aliases"]

relationship_indexes:
  - name: "idx_ACTIVATES_strength"
    type: "RELATIONSHIP"
    rel_type: "ACTIVATES"
    properties: ["strength", "confidence"]
  - name: "idx_MEASURES_confidence"
    type: "RELATIONSHIP"
    rel_type: "MEASURES"
    properties: ["confidence"]

profiles:
  dev:
    create_fulltext: true
  prod:
    create_fulltext: true
    analyze_after_create: true
```

---

## security/pii\_redaction.yaml

```yaml
# Export whitelists & transforms by audience. Enforced by export endpoints.

default_profile: "public"

profiles:
  public:
    nodes:
      Publication: {keep: ["id", "title", "year", "journal", "doi"], drop: ["abstract"], transforms: {}}
      Task: {keep: ["id", "name", "synonyms"], drop: [], transforms: {}}
      Concept: {keep: ["id", "label", "synonyms"], drop: [], transforms: {}}
      Region: {keep: ["id", "atlas", "name"], drop: ["aliases"], transforms: {}}
      Coordinate: {keep: ["id", "space", "x", "y", "z"], transforms: {round_coordinates_mm: 1}}
      Dataset: {keep: ["id", "name", "source"], drop: ["s3_path"], transforms: {}}
      Subject: {keep: ["id"], drop: ["age", "sex", "site", "participant_label"], transforms: {hash_id: true}}
      SubjectGroup: {keep: ["id", "n"], drop: ["site"], transforms: {}}
    edges:
      ACTIVATES: {keep: ["strength", "confidence"], drop: ["evidence_components"]}
      MEASURES: {keep: ["confidence"], drop: []}
      HAS_COORDINATE: {keep: [], drop: []}
      IN_REGION: {keep: ["method"], drop: []}

  collaborator:
    inherit: "public"
    nodes:
      Publication: {keep: ["id", "title", "year", "journal", "doi", "abstract"]}
      Dataset: {keep: ["id", "name", "source", "license"]}

  internal:
    nodes:
      "*": {keep: "*"}
    edges:
      "*": {keep: "*"}

transforms:
  hash_id:
    method: "sha256"
    salt_env: "BR_KG_EXPORT_SALT"
  mask_email:
    pattern: "(^[^@])[^@]*(@.*$)"
    replace: "$1***$2"
  round_coordinates_mm: 1   # decimal places
  truncate_text:
    max_len: 1000

notes:
  - "Public profile removes direct subject attributes; keep only hashed IDs."
  - "Coordinates are rounded for public exports to mitigate re-identification risks."
```

---

## registries/ontology\_sources.yaml

```yaml
# Register external ontologies/vocabularies to sync into BR-KG.
# Each entry drives a loader (e.g., core/ingestion/loaders/ontologies/*).

ontologies:
  - acronym: "ONVOC"
    name: "OpenNeuro Vocabulary"
    prefix: "onvoc"
    source: "bioportal"
    bioportal_acronym: "ONVOC"
    format: "SKOS"        # per BioPortal summary
    base_uri: "http://purl.bioontology.org/ontology/ONVOC"
    download:
      method: "bioportal_api"
      endpoints:
        skos: "https://data.bioontology.org/ontologies/ONVOC/download?download_format=skos"
    license: "TBD"        # fill from BioPortal metadata page
    status: "alpha"       # as listed in BioPortal
    last_synced: null
    mapping_policy:
      treat_as: "vocabulary"   # do not auto-materialize as Concept/Task without mapping
      class_map:
        skos:Concept: "VocabularyTerm"
    provenance:
      homepage: "https://bioportal.bioontology.org/ontologies/ONVOC"
```

---

## mappings/ontology\_term\_maps.yaml

```yaml
# Map external ontology/vocabulary terms to BR-KG canonical entities.
# Use when you want ONVOC (or others) to enrich Tasks/Concepts/Datasets.

onvoc:
  scheme: "openneuro"
  rules:
    - from_id: "onvoc:task-nback"   # example placeholder; replace with real ONVOC IDs
      to:
        type: "Task"
        id: "cogat:TRM_4a3fd79d0a5c8"   # Cognitive Atlas n-back
      method: "string_match|manual"
      confidence: 0.8
    - from_label: "go/no-go"
      to:
        type: "Task"
        canonical: "Go/No-Go"
      method: "string_match"
      confidence: 0.7
```

---

## configs/sheets\_sources.yaml

```yaml
# Configure Google Sheets as curated registries/mappings.
# A helper tool will fetch CSV exports and convert to YAML under targets.

sheets:
  - id: "1GaVmhH9aPgcUhhVrpmtMF75EYtkx7us7derR9eMypEc"   # your sheet ID
    owner: "Zijiao Chen"
    url: "https://docs.google.com/spreadsheets/d/1GaVmhH9aPgcUhhVrpmtMF75EYtkx7us7derR9eMypEc"
    tabs:
      - gid: "970513531"
        name: "roi_synonyms"
        target: "mappings/roi_synonyms.yaml"
        columns: ["canonical", "synonym", "lang", "notes"]
        key: ["canonical", "synonym"]
        transform: "list_group_by_canonical"   # groups rows to the YAML shape used in roi_synonyms.yaml
      # Add more tabs here if your sheet contains other mappings (concept_synonyms, journal_abbrev, etc.)
    fetch:
      method: "csv_export"           # uses the public CSV export or service account; see notes below
      auth: "service_account|public" # choose one; service account if sheet not public
    refresh:
      policy: "manual"               # or "daily" via CI
      snapshots: true                 # write dated copies under snapshots.path

snapshots:
  path: "mappings/_snapshots"
  filename_template: "{basename}.{YYYYMMDD}.yaml"
```

---

## docs/standards/ontology\_integration.md

### Goal

Make external ontologies (e.g., ONVOC) first‑class **registries** that can enrich BR-KG while keeping provenance and controlled mappings.

### Steps

1. **Register the ontology** in `registries/ontology_sources.yaml` (acronym, prefix, download, license, status).
2. **Sync the raw ontology** (SKOS/OWL) → serialize to a local cache (`data/ontologies/ONVOC.skos`), record PROV (timestamp, checksum).
3. **Decide materialization**:

   * Treat as `VocabularyTerm` nodes (lookup only), **or**
   * Map selected terms to canonical `Task/Concept/Dataset` via `mappings/ontology_term_maps.yaml`.
4. **Linking**:

   * During ingestion, the linker reads ontology maps and creates `MAPS_TO`/`ALIGNS_WITH` edges with `prov.method = ontology_map`.
5. **Versioning**:

   * Keep ONVOC version/date; if upstream updates, re‑sync and diff changed terms; update edges with `valid_to` on old mappings.
6. **Licensing**:

   * Respect license; expose only permitted fields in exports per `security/pii_redaction.yaml` & public profile.

### CLI (suggested)

```bash
# Sync ONVOC from BioPortal (SKOS)
python scripts/tools/ontologies/sync.py --acronym ONVOC --format skos --out data/ontologies/ONVOC.skos

# Build/update mapped edges
python scripts/tools/ontologies/apply_maps.py --source onvoc --maps mappings/ontology_term_maps.yaml
```

---

## tools/sheets/README.md (notes)

**Purpose:** Convert curated Google Sheets tabs to YAML/JSON under `mappings/` or `registries/`, with provenance and snapshots.

**Contract:** `configs/sheets_sources.yaml` drives what to pull and where to write.

**CLI (suggested):**

```bash
python tools/sheets/export.py \
  --config configs/sheets_sources.yaml \
  --snapshots --update-targets
```

**Behavior:**

* Uses CSV export (`https://docs.google.com/spreadsheets/d/<id>/export?format=csv&gid=<gid>`) or Google API if private.
* Validates required columns; applies `configs/string_normalization.yaml` pipeline; groups rows to target YAML shape.
* Writes dated snapshot and updates the canonical target file atomically.
* Emits PROV record (`.prov.json`) alongside output with sheet URL, gid, checksum, timestamp.
