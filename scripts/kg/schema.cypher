// BR-KG schema/index plan generated 2025-11-09
// Apply via: cypher-shell -a bolt://localhost:7687 -u neo4j -p password -f scripts/kg/schema.cypher

// === 0) Cleanup legacy indexes that block constraints ===
// (safe to run even if they never existed)
DROP INDEX index_25c2773a IF EXISTS;  // old Concept(id) range index
DROP INDEX index_47d0629b IF EXISTS;  // old Task(id) range index

// === 1) Constraints (PKs) ===
CREATE CONSTRAINT onvoc_id        IF NOT EXISTS FOR (o:ONVOC)         REQUIRE o.id     IS UNIQUE;
CREATE CONSTRAINT task_id         IF NOT EXISTS FOR (t:Task)          REQUIRE t.id     IS UNIQUE;
CREATE CONSTRAINT concept_id      IF NOT EXISTS FOR (c:Concept)       REQUIRE c.id     IS UNIQUE;
CREATE CONSTRAINT dataset_id      IF NOT EXISTS FOR (d:Dataset)       REQUIRE d.id     IS UNIQUE;
CREATE CONSTRAINT contrast_key    IF NOT EXISTS FOR (c:Contrast)      REQUIRE c.key    IS UNIQUE;
CREATE CONSTRAINT statmap_sha256  IF NOT EXISTS FOR (m:StatMap)       REQUIRE m.sha256 IS UNIQUE;
CREATE CONSTRAINT templatespace_id IF NOT EXISTS FOR (s:TemplateSpace) REQUIRE s.id     IS UNIQUE;
CREATE CONSTRAINT run_id          IF NOT EXISTS FOR (r:Run)           REQUIRE r.id     IS UNIQUE;
CREATE CONSTRAINT tool_id         IF NOT EXISTS FOR (t:Tool)          REQUIRE t.tool_id IS UNIQUE;
CREATE CONSTRAINT tool_version_id IF NOT EXISTS FOR (tv:ToolVersion)  REQUIRE tv.version_id IS UNIQUE;

// === 2) Supporting indexes ===
CREATE INDEX task_name_idx        IF NOT EXISTS FOR (t:Task)          ON (t.name);
CREATE INDEX concept_name_idx     IF NOT EXISTS FOR (c:Concept)       ON (c.name);
CREATE INDEX onvoc_label_idx      IF NOT EXISTS FOR (o:ONVOC)         ON (o.label);
CREATE INDEX dataset_name_idx     IF NOT EXISTS FOR (d:Dataset)       ON (d.name);
CREATE INDEX contrast_props_idx   IF NOT EXISTS FOR (c:Contrast)      ON (c.stat, c.level, c.space);
CREATE INDEX statmap_props_idx    IF NOT EXISTS FOR (m:StatMap)       ON (m.stat, m.space);
CREATE INDEX statmap_created_idx  IF NOT EXISTS FOR (m:StatMap)       ON (m.created_at);
CREATE INDEX dataset_source_idx   IF NOT EXISTS FOR (d:Dataset)       ON (d.source);
CREATE INDEX statmap_dataset_idx  IF NOT EXISTS FOR (m:StatMap)       ON (m.dataset_id);
CREATE INDEX tool_primary_intent_idx IF NOT EXISTS FOR (t:Tool)       ON (t.primary_intent);
CREATE INDEX tool_software_idx       IF NOT EXISTS FOR (t:Tool)       ON (t.software);
CREATE INDEX tool_op_key_idx         IF NOT EXISTS FOR (t:Tool)       ON (t.op_key);
CREATE INDEX tool_is_default_idx     IF NOT EXISTS FOR (t:Tool)       ON (t.is_default);
CREATE INDEX tool_exposed_idx        IF NOT EXISTS FOR (t:Tool)       ON (t.exposed);
CREATE INDEX tool_default_group_idx  IF NOT EXISTS FOR (t:Tool)       ON (t.default_group_id);
CREATE INDEX tool_exposure_group_idx IF NOT EXISTS FOR (t:Tool)       ON (t.exposure_group);
CREATE INDEX tool_version_idx        IF NOT EXISTS FOR (t:Tool)       ON (t.version);

// === 3) Fulltext index for search entry point ===
CREATE FULLTEXT INDEX kgFulltext IF NOT EXISTS
FOR (n:Task|Concept|ONVOC|Dataset)
ON EACH [n.name, n.label, n.aliases];

// Expanded fulltext index for KG search (preferred by query_service)
CREATE FULLTEXT INDEX kgNodeFulltext IF NOT EXISTS
FOR (n:Task|Concept|CognitiveConcept|OntologyConcept|Term|ONVOC|Dataset|Publication|Region|BrainRegion|Tool|Atlas|TemplateSpace|Parcellation|Parcel)
ON EACH [
  n.name,
  n.label,
  n.title,
  n.aliases,
  n.synonyms,
  n.keywords,
  n.description,
  n.definition,
  n.id,
  n.dataset_id,
  n.uid,
  n.identifier,
  n.tool_id,
  n.op_key,
  n.atlas,
  n.journal,
  n.authors,
  n.pmid,
  n.doi
];

// === 4) Optional seed TemplateSpace entries ===
MERGE (:TemplateSpace {id:'MNI152_2mm', name:'MNI152 (2mm)'})
MERGE (:TemplateSpace {id:'fsaverage', name:'FreeSurfer fsaverage'});

// === 5) Validation: list constraints/indexes ===
SHOW CONSTRAINTS;
SHOW INDEXES;
SHOW INDEXES YIELD name, type, state
WHERE type = 'FULLTEXT'
RETURN name, type, state
ORDER BY name;
