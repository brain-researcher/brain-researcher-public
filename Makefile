SHELL := /bin/bash

REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PYTHON ?= python3

KG_CYPHER_SHELL ?= cypher-shell
NEO4J_URI ?= bolt://localhost:7687
NEO4J_USER ?= neo4j
KG_INGEST_ARGS ?=

.PHONY: help download-neurosynth check-neurosynth kg-ingest kg-show health-check

help:
	@printf '%s\n' \
		'download-neurosynth  Download and verify the pinned Neurosynth v0.7 bundle' \
		'check-neurosynth     Verify the pinned bundle without network access' \
		'kg-ingest            Ingest the tool catalog (requires NEO4J_PASSWORD)' \
		'kg-show              Run read-only KG summaries (requires NEO4J_PASSWORD)' \
		'health-check         Probe an already-running local service stack'

download-neurosynth:
	@cd "$(REPO_ROOT)" && "$(PYTHON)" scripts/data/download_neurosynth_data.py

check-neurosynth:
	@cd "$(REPO_ROOT)" && "$(PYTHON)" scripts/data/download_neurosynth_data.py --check-only

kg-ingest:
	@if [[ -z "$${NEO4J_PASSWORD:-}" ]]; then \
		echo 'NEO4J_PASSWORD must be exported in the environment' >&2; \
		exit 1; \
	fi
	@cd "$(REPO_ROOT)" && \
		PYTHONPATH="$(REPO_ROOT)/src:$(REPO_ROOT)" \
		NEO4J_URI="$(NEO4J_URI)" NEO4J_USER="$(NEO4J_USER)" \
		"$(PYTHON)" scripts/tools/etl/kg_ingest_tools.py $(KG_INGEST_ARGS)

kg-show:
	@if [[ -z "$${NEO4J_PASSWORD:-}" ]]; then \
		echo 'NEO4J_PASSWORD must be exported in the environment' >&2; \
		exit 1; \
	fi
	@"$(KG_CYPHER_SHELL)" -a "$(NEO4J_URI)" -u "$(NEO4J_USER)" \
		'MATCH (o:Operation {id:"dmri_tractography"})<-[:IMPLEMENTS]-(f:ToolFamily) RETURN f.id, f.runtime_kinds;'
	@"$(KG_CYPHER_SHELL)" -a "$(NEO4J_URI)" -u "$(NEO4J_USER)" \
		'MATCH (o:Operation {id:"skull_strip_mri"})<-[:IMPLEMENTS]-(t:Tool) RETURN t.id, t.runtime_kind ORDER BY t.is_niwrap DESC, t.id LIMIT 20;'
	@"$(KG_CYPHER_SHELL)" -a "$(NEO4J_URI)" -u "$(NEO4J_USER)" \
		'MATCH (f:ToolFamily)-[r:IMPLEMENTS]->(o:Operation) RETURN o.id AS operation, f.id AS family, r.tool_count AS tools ORDER BY operation, family LIMIT 30;'

health-check:
	@cd "$(REPO_ROOT)" && bash scripts/smoke/health_smoke.sh
