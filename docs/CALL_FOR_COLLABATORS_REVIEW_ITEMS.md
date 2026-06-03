# Brain Researcher — Call for Collaborators: Review & Evaluation Task Breakdown

## Overview

Brain Researcher is an AI-powered neuroimaging research platform that integrates:
- **BrainResearcherBenchmark**: 389 tasks across 4 evaluation suites
- **BR-KG**: Large-scale knowledge graph with 355+ retrieval benchmark entries
- **75+ analysis tools**: Organized into hierarchical workflows
- **Automated hypothesis generation**: Grounded in BR-KG with structured evidence
- **8+ demo traces**: End-to-end research workflows in Anthropic Cookbook style
- **350+ UI components**: Web-based interface with MCP integration

We have more content requiring manual review than our core team can handle alone. Contributors who meet the item threshold below will be offered co-authorship on the associated paper(s).

**Expected workload: 3–4 hours per person.** You choose which category fits your background — no need to cover everything.

---

## Co-authorship Thresholds

The threshold depends on whether your contribution requires running experiments or is review/evaluation only:

| Track | Items required | Est. time/item | Total time |
|-------|---------------|----------------|------------|
| Review / Eval only (no experiments) | 20 items | ~10 min | ~3.5 hours |
| Includes experiments (new data) | 10 items | ~20–25 min | ~3.5–4 hours |

Items can be mixed across categories within the same track.

---

## Task Categories

### 1. Benchmark (Questions & Answers)

**Items: 389 tasks across 4 suites**

| Suite | Tasks | Description |
|-------|-------|-------------|
| NeuroimageQABench | 137 | Multiple-choice QA tasks (concept-level understanding, distractor discrimination) |
| NeuroimageQARubric | 94 | Rubric-scored freeform QA with JSON schema constraints |
| NeuroimageMetaAnalysis | 63 | Evidence retrieval, screening, extraction with provenance |
| NeuroimageCodeBench | 95 | Executable analysis with artifact generation + scientific validation |

**Category breakdown (QARubric example):**
- NEUROSCIENTIFIC_KNOWLEDGE: 13 tasks
- METHODS: 13 tasks
- PREPROCESSING: 13 tasks
- STATS: 14 tasks
- INTERPRETATION: 13 tasks
- TROUBLESHOOTING: 14 tasks
- BEST_PRACTICES: 14 tasks

**What reviewers check:**
- Is the question unambiguous and neuroimaging-accurate?
- Is the reference answer correct and complete?
- Is the rubric fair — does it reward good reasoning, not just keywords?
- For code tasks: does expected output match correct analysis?

**File locations:**
- `apps/web-ui/public/benchmarks/neuroimage-theory-rubric.harbor.json` (94 tasks)
- `manuscript/paper1_brainresearcherbenchmark.md` (benchmark design docs)

---

### 2. Workflow & Tools

**Items: 75+ tools + multiple workflow templates**

**Tool catalog:**
- 16 core tools in agent_tools_catalog (smri, fmri, meg, pet, eeg modalities)
- 90+ tool intents and families
- 18 task superfamilies with 20 family files

**Workflow templates:**
- workflow_preprocessing_qc (validate_bids → fmriprep → mriqc → qc_table → detect_outliers → qc_aggregator → dashboard)
- workflow_data_harmonization (load_dataset → harmonize_data(ComBat) → regenerate features)
- workflow_multiverse_analysis (multiple presets → compare outcomes → stability report)
- workflow_rest_connectome_e2e (end-to-end resting-state pipeline)
- workflow_seed_based_connectivity (seed-based FC workflow)

**What reviewers check:**
- Are pipeline steps in a sensible order for the stated research goal?
- Are parameter choices reasonable defaults (or are dangerous defaults exposed without warning)?
- Does described output match what the tool actually produces?
- Are input/output types correctly specified (consumes/produces)?

**File locations:**
- `data/br-kg_exports/agent_tools_catalog.json` (16 tools)
- `configs/workflows/workflow_catalog.yaml` (workflow definitions)
- `configs/grandmaster/toolset_vfinal.yaml` (tool surface definitions)
- `configs/workflow_templates/template_library.yaml` (workflow templates)
- `configs/taxonomy/` (18 superfamilies, 20 family files)

---

### 3. Dataset / Knowledge Graph Nodes & Edges

**Items: 355+ retrieval benchmark entries + 90 taxonomy entities**

**KG retrieval benchmark:**
- 355 entries in `2B_retrieval_benchmark.jsonl`
- Dataset entries (OpenNeuro, Neurobagel)
- Concept mappings with evidence

**Taxonomy entities:**
- 90 total entities (68 Tasks, 17 Constructs, 5 Domains)
- Task entities include alt_labels, source_aliases, measures, domains
- Example: `task:n-back` with 14 aliases, cognitive atlas links, construct mappings

**Node types to validate:**
- Task nodes (n-back, go/no-go, stroop, etc.)
- Construct nodes (working-memory, inhibition, etc.)
- Domain nodes (executive-function, attention, etc.)
- Dataset nodes (OpenNeuro ds000001, etc.)

**Edge types to validate:**
- MAPS_TO relationships (task → construct)
- PART_OF relationships (task → domain)
- MEASURED_BY relationships (construct → task)
- Dataset → concept mappings

**What reviewers check:**
- Nodes: Is factual description accurate (title, year, key claims)?
- Edges: Is relationship correctly typed and directionally accurate?
- Are missing or incorrect relationships flagged?

**File locations:**
- `data/br-kg_exports/2B_retrieval_benchmark.jsonl` (355 entries)
- `src/brain_researcher/semantics/taxonomy/entities.json` (90 entities)
- `configs/taxonomy/exports/` (master exports)

---

### 4. Generated Hypotheses

**Items: Hypothesis examples + explorer UI**

**Components:**
- 10 hypothesis UI components (explorer, artifact panel, list panel, etc.)
- Current curated report evidence in `docs/use_cases/brain_researcher_hybrid/reports/`
- Evidence-first examples with KG grounding

**What reviewers check:**
- **Novelty**: Is this a genuinely open question, or well-established?
- **Feasibility**: Can this be tested with standard methods/public datasets?
- **Specificity**: Does it name concrete variables, regions, mechanisms — or vague?
- **KG grounding**: Are supporting nodes/edges actually relevant to the claim?

**File locations:**
- `apps/web-ui/src/components/hypothesis/` (10 UI components)
- `docs/use_cases/brain_researcher_hybrid/reports/` (curated report evidence)
- `apps/web-ui/src/app/hypothesis/` (hypothesis pages)

---

### 5. Demo Traces

**Items: 6 curated PDF report demos**

**Demo index:**
1. case1-neuromark-schizophrenia-multiverse
2. case2-cocaine-network-segregation
3. case3-connectome-hubness-decoding
4. case4-ingroup-outgroup-cultural-boundaries
5. bounded-self-evolving-discovery
6. bounded-self-evolving-predictive

**What reviewers check:**
- Does the curated report artifact open from the demo?
- Is PDF-only evidence clearly labeled as curated?
- Any surprising failures, hallucinations, or tool errors?

**File locations:**
- `configs/demo/demo_index.json` (6 demo definitions)
- `configs/demo/run_bundles/` (curated replay bundles)
- `docs/use_cases/brain_researcher_hybrid/reports/` (6 curated PDF reports)

---

### 6. UI/UX Interaction & MCP Integration

**Items: 350+ UI components + MCP server tools**

**UI components:**
- 350+ React/TypeScript components
- 75+ component directories (chat, kg, hypothesis, dashboard, etc.)
- 75 app page components

**MCP integration:**
- 13+ MCP tools (tool_search, tool_get, pipeline_execute, kg_search_nodes, etc.)
- File system tools (artifact_list, artifact_read_text, etc.)
- KG read-only helpers (kg_search_nodes, kg_get_node, kg_neighbors, etc.)

**What reviewers check:**
- **Friction points**: Anything requiring re-reading or feeling confusing
- **Bugs**: Unexpected behavior, crashes, incorrect outputs
- **MCP integration**: Tool calls that failed or returned unexpected formats
- **Suggestions**: What would you want to see that isn't there?

**File locations:**
- `apps/web-ui/src/components/` (350+ components)
- `apps/web-ui/src/app/` (75 page components)
- `src/brain_researcher/services/mcp/server.py` (MCP server)
- `docs/mcp.md` (MCP documentation)

---

### 7. Experiments (New Data Contribution)

**Items: Run analysis on your own dataset**

If you have access to a research cluster and neuroimaging data, contribute by:
1. Running a provided analysis protocol on your own dataset
2. Submitting results in structured JSON + summary format

**We provide:**
- Specific prompt / analysis template to follow
- Expected output format
- Submission form

**This track counts toward co-authorship at 10 completed experiments.**

---

## Who Should Contribute What

| Your background | Best-fit tasks |
|-----------------|----------------|
| Neuroimaging methods (fMRI, FSL, FreeSurfer, etc.) | Benchmark QA, Workflow validation, KG nodes/edges, Experiments |
| Cognitive neuroscience / domain knowledge | Hypothesis rating, Benchmark QA, KG edges (relationship accuracy) |
| ML / AI / software engineering | Demo traces, UI/UX & MCP integration, Workflow tools |
| Research cluster experience | Experiments (running analysis pipelines) |
| Any of the above — reviewer role | Any review/eval category (no experiments needed for co-authorship) |

---

## Evaluation Rubric

Each item you submit will be spot-checked using the following rubric. Items rated 1 (needs revision) may be returned for revision.

| Dimension | 1 — Needs revision | 2 — Acceptable | 3 — High quality |
|-----------|-------------------|----------------|------------------|
| **Correctness** | Factual errors present | Mostly correct, minor gaps | Verified accurate |
| **Specificity** | Too vague to act on | Partially actionable | Concrete and actionable |
| **Coverage** | Key aspects missing | Covers most aspects | Thorough and complete |
| **Reproducibility** (traces/demo) | Cannot reproduce | Partial reproduction | Fully reproducible |

For review tasks, we will check inter-rater agreement on a subset (10%) to calibrate standards.

---

## Summary Table

| Category | Items for co-authorship | Time estimate |
|----------|------------------------|---------------|
| Benchmark (QA) | 20 items | ~10 min/item → 3.5 hrs |
| Workflow & Tools | 20 items | ~10 min/item → 3.5 hrs |
| KG Nodes & Edges | 20 items | ~10 min/item → 3.5 hrs |
| Generated Hypotheses | 20 items | ~10 min/item → 3.5 hrs |
| Demo Traces | 10 traces | ~20 min/trace → 3.5 hrs |
| UI/UX & MCP Integration | 10 sessions | ~20 min/session → 3.5 hrs |
| Experiments (new data) | 10 experiments | ~25 min avg → 4 hrs |

---

## How to Get Started

1. **Contact us** and indicate which category you are interested in
2. **We assign** you a batch of items with a standardized review form
3. **Submit** completed items within 2 weeks of receiving your batch
4. **Items are reviewed** and counted. You'll be notified when you reach the threshold
5. **Co-authorship** is offered on the associated paper based on your contribution area

---

## File Reference Summary

| Category | Primary Files |
|----------|---------------|
| Benchmark | `apps/web-ui/public/benchmarks/neuroimage-theory-rubric.harbor.json`, `manuscript/paper1_brainresearcherbenchmark.md` |
| Workflows/Tools | `configs/workflows/workflow_catalog.yaml`, `configs/grandmaster/toolset_vfinal.yaml`, `data/br-kg_exports/agent_tools_catalog.json` |
| KG Data | `data/br-kg_exports/2B_retrieval_benchmark.jsonl`, `src/brain_researcher/semantics/taxonomy/entities.json` |
| Hypotheses | `apps/web-ui/src/components/hypothesis/`, `docs/use_cases/brain_researcher_hybrid/reports/` |
| Demos | `configs/demo/demo_index.json`, `docs/use_cases/brain_researcher_hybrid/` |
| UI/UX/MCP | `apps/web-ui/src/components/`, `src/brain_researcher/services/mcp/server.py` |

---

Brain Researcher | Stanford University | February 2026
