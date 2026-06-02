harmonise_concepts:
	python semantics/ensemble_match/exact_fuzzy_match.py contrasts_raw.csv concept_aliases.tsv matches_exact_fuzzy.csv
	python semantics/ensemble_match/embed_match.py --enable-embed --input contrasts_raw.csv --output matches_embed.csv
	python semantics/ensemble_match/merge_candidates.py matches_exact_fuzzy.csv matches_embed.csv llm_annotations merged_candidates.csv
	python semantics/ensemble_match/cal_score.py merged_candidates.csv scored_candidates.csv
	python semantics/ensemble_match/prune_rank.py scored_candidates.csv pruned_candidates.csv
	python semantics/ensemble_match/write_edges.py pruned_candidates.csv measures_edges_FINAL.csv
	python semantics/ensemble_match/qa_report.py

update_concepts:
	python scripts/data_processing/update_concepts.py

.PHONY: ingest_glmfitlins

STATS_DIR=llm_cogitive_function/openneuro_glmfitlins/statsmodel_specs
ANNOT_DIR=llm_cogitive_function/data/processed_with_direction
INGEST_DIR=data/etl_cache/glmfitlins_ingest

ingest_glmfitlins:
	mkdir -p $(INGEST_DIR)
	PYTHONPATH=src python -m brain_researcher.services.br_kg.etl.glmfitlins_ingest.discover_specs --stats-dir $(STATS_DIR) --annot-dir $(ANNOT_DIR) --manifest $(INGEST_DIR)/dataset_manifest.csv
	PYTHONPATH=src python -m brain_researcher.services.br_kg.etl.glmfitlins_ingest.parse_statsmodel --manifest $(INGEST_DIR)/dataset_manifest.csv --out $(INGEST_DIR)/contrasts_raw.csv
	PYTHONPATH=src python -m brain_researcher.services.br_kg.etl.glmfitlins_ingest.annotate_constructs --manifest $(INGEST_DIR)/dataset_manifest.csv --contrasts $(INGEST_DIR)/contrasts_raw.csv --annot-dir $(ANNOT_DIR)
	PYTHONPATH=src python -m brain_researcher.services.br_kg.etl.glmfitlins_ingest.make_edges --manifest $(INGEST_DIR)/dataset_manifest.csv --contrasts $(INGEST_DIR)/contrasts_raw.csv --out-dir $(INGEST_DIR)
	bash scripts/br-kg/neo4j_import_glmfitlins.sh $(INGEST_DIR)
	PYTHONPATH=src python -m brain_researcher.services.br_kg.etl.glmfitlins_ingest.qa_report --out-dir $(INGEST_DIR)

.PHONY: download-neurosynth

download-neurosynth:
	@echo "Downloading Neurosynth dataset..."
	python cli/neurosynth_fetch.py

check-neurosynth:
	@echo "Checking Neurosynth dataset..."
	python cli/neurosynth_fetch.py --check-only

# -----------------------------
# BR-KG tool ingest helpers
# -----------------------------
.PHONY: kg-ingest kg-show

KG_CYPHER_SHELL ?= cypher-shell
NEO4J_URI ?= bolt://localhost:7687
NEO4J_USER ?= neo4j
NEO4J_PASSWORD ?= $(shell grep -E '^NEO4J_PASSWORD=' .env | head -n1 | cut -d= -f2)

kg-ingest:
	@if [ -z "$(NEO4J_PASSWORD)" ]; then echo "NEO4J_PASSWORD not set (set in env or .env)"; exit 1; fi
	PYTHONPATH=. NEO4J_URI=$(NEO4J_URI) NEO4J_USER=$(NEO4J_USER) NEO4J_PASSWORD=$(NEO4J_PASSWORD) \
		python scripts/tools/etl/kg_ingest_tools.py

kg-show:
	@if [ -z "$(NEO4J_PASSWORD)" ]; then echo "NEO4J_PASSWORD not set (set in env or .env)"; exit 1; fi; \
	$(KG_CYPHER_SHELL) -a $(NEO4J_URI) -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) \
	'MATCH (o:Operation {id:"dmri_tractography"})<-[:IMPLEMENTS]-(f:ToolFamily) RETURN f.id, f.runtime_kinds;' ; \
	$(KG_CYPHER_SHELL) -a $(NEO4J_URI) -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) \
	'MATCH (o:Operation {id:"skull_strip_mri"})<-[:IMPLEMENTS]-(t:Tool) RETURN t.id, t.runtime_kind ORDER BY t.is_niwrap DESC, t.id LIMIT 20;' ; \
	$(KG_CYPHER_SHELL) -a $(NEO4J_URI) -u $(NEO4J_USER) -p $(NEO4J_PASSWORD) \
	'MATCH (f:ToolFamily)-[r:IMPLEMENTS]->(o:Operation) RETURN o.id AS operation, f.id AS family, r.tool_count AS tools ORDER BY operation, family LIMIT 30;'

# -----------------------------
# Ops helpers
# -----------------------------
.PHONY: backup-neo4j health-check

# Dump the neo4j database to ./backups/neo4j (container must be running)
backup-neo4j:
	bash scripts/neo4j_backup_daily.sh

# Quick smoke of running services (agent / br-kg / web-ui)
health-check:
	bash scripts/smoke/health_smoke.sh
