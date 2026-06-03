# Brain Researcher — Call for Contributors (Expanded)

> Beyond reviewing existing content, we need contributors to **build new capabilities**, **run end-to-end research pipelines**, and **curate domain knowledge**. This document covers both **review/eval** tracks and **creative contribution** tracks.

---

## Part A: Review & Evaluation (existing items)

> See [REVIEW_GITHUB_ISSUES.md](file://<repo>/docs/REVIEW_GITHUB_ISSUES.md) for the full breakdown of **~189 review issues** covering **960+ items** across benchmark, tools, workflows, KG, hypotheses, demos, and UI/UX.

---

## Part B: Creative Contributions (new items)

These are **new contribution tracks** that go beyond reviewing existing content. Contributors create something new that extends the platform's capabilities.

---

### B1. New Tool Integration (2,339 tools waiting)

**The gap**: We have **2,380 tools** in the [tool universe](file://<repo>/tool_universe.tsv) but only **41 integrated** into the [tools catalog](file://<repo>/configs/tools_catalog.json). That's a **98% integration gap**.

**Tool suites available for wrapping** (via [niwrap](file://<repo>/external/niwrap)):

| Suite | Domain | Priority |
|---|---|---|
| AFNI | fMRI analysis | High |
| FSL | Multi-modal | High |
| FreeSurfer | Surface/sMRI | High |
| ANTs | Registration | High |
| MRtrix / MRtrix3Tissue | Diffusion | High |
| Workbench | HCP/CIFTI | Medium |
| FastSurfer | Fast surface recon | Medium |
| NiftyReg | Registration | Medium |
| C3D | Image conversion | Low |
| Greedy | Registration | Low |
| dcm2niix | DICOM conversion | Low |

**24 tool categories** await population:

`data_management`, `preprocessing`, `quality_control`, `registration`, `segmentation`, `statistical_analysis`, `connectivity`, `electrophysiology`, `diffusion`, `surface`, `machine_learning`, `deep_learning`, `knowledge_graph`, `meta_analysis`, `statistical_inference`, `clinical`, `realtime`, `simulation`, `visualization`, `workflow`, `feature_selection`, `advanced_analysis`, `data_harmonization`, `specialized_processing`

**Issue template:**

```
Title: [New Tool] Integrate {tool_name} from {suite} into tool catalog
Labels: contribution, new-tool, {suite}

## Description
Wrap {tool_name} from {suite} as a Brain Researcher tool.

## Files to modify/create
- `configs/tools_catalog.json` — add tool entry
- `src/brain_researcher/services/tools/` — add executor
- `configs/tool_categories.yaml` — add to appropriate category

## Checklist
- [ ] Tool spec: name, domain, modality, runtime_kind
- [ ] consumes/produces types correctly defined
- [ ] Parameter defaults are safe
- [ ] Basic test passes
- [ ] Documentation added
```

**Co-authorship threshold**: 10 new tools integrated

---

### B2. New Workflow Design (42 exist, many more possible)

**42 workflows** exist in [workflow_catalog.yaml](file://<repo>/configs/workflows/workflow_catalog.yaml), but many common neuroimaging pipelines are missing.

**Missing workflow ideas** (high-value):

| Workflow | Description | Issue |
|---|---|---|
| Resting-state ReHo + fALFF | Regional homogeneity + fractional ALFF | `contribute/wf-reho-falff` |
| Multi-echo fMRI denoising | TEDANA / ME-ICA pipeline | `contribute/wf-multi-echo` |
| BIDS-App integration | Generic BIDS-App wrapper | `contribute/wf-bids-app` |
| Cortical thickness analysis | FreeSurfer-based thickness | `contribute/wf-cortical-thickness` |
| DTI TBSS pipeline | Tract-based spatial statistics | `contribute/wf-dti-tbss` |
| Resting-state temporal dynamics | Sliding-window + k-means | `contribute/wf-temporal-dynamics` |
| Bayesian GLM analysis | BayesianGroupAna / BRMS | `contribute/wf-bayesian-glm` |
| Cross-study harmonization | ComBat + leave-one-site-out | `contribute/wf-cross-study-harmonize` |
| Multivariate pattern analysis | Searchlight RSA / MVPA | `contribute/wf-mvpa-searchlight` |
| Structural covariance network | SCN from cortical thickness | `contribute/wf-scn` |

**Issue template:**

```
Title: [New Workflow] {workflow_name}
Labels: contribution, new-workflow

## Description
Design and implement a new workflow for {description}.

## Files to create/modify
- `configs/workflows/workflow_catalog.yaml` — add workflow definition
- Define steps, parameters, defaults, input/output types

## Checklist
- [ ] Steps are in correct scientific order
- [ ] All required tools exist (or new tools added)
- [ ] Parameter defaults are safe and documented
- [ ] Input/output compatibility between steps verified
- [ ] Example invocation works end-to-end
```

**Co-authorship threshold**: 5 new workflows

---

### B3. End-to-End Paper Generation (Hypothesis → Results → Publication)

Use Brain Researcher to produce a **complete research output** — from hypothesis to methods draft. This is the **highest-impact contribution** and demonstrates the platform's end-to-end capability.

**7 existing chat scenarios** provide templates:

| Scenario | Description | File |
|---|---|---|
| `encoding_model_designer` | Design encoding model from construct + dataset | [`chat_scenarios.json`](file://<repo>/configs/chat_scenarios.json) |
| `model_size_suggester` | Recommend model families given sample size | ↑ |
| `construct_to_task_dataset` | Map construct → tasks + public datasets | ↑ |
| `study_design_sanity_check` | Qualitative sanity check on proposed design | ↑ |
| `paper_to_pipeline` | Methods blurb → Brain Researcher pipeline | ↑ |
| `run_card_to_methods` | Run Card → draft Methods paragraphs | ↑ |
| `graph_analysis_designer` | Design graph/GNN analysis from connectome data | ↑ |

**The R0–R5 research pipeline**:

```
R0 (Query Planner) → R1 (Conflict Mapping) → R2 (Robustness Audit)
    → R3 (Design Recommendation) → R4 (Execution) → R5 (Loop Closure)
```

**Issue template:**

```
Title: [Paper Generation] E2E research — {topic}
Labels: contribution, paper-generation, e2e

## Description
Run a complete R0 → R5 research pipeline on {topic} using Brain Researcher.

## Deliverables
1. Research prompt (starting question)
2. R0–R5 stage outputs (YAML/JSON)
3. Figures / visualizations generated
4. Draft Methods paragraph (via run_card_to_methods)
5. Executive summary
6. Reproduction script / notebook

## Suggested topics
- Replication of a known fMRI finding (e.g., Stroop conflict in dACC)
- Novel hypothesis from KG (use Hypothesis Explorer)
- Cross-modal comparison (fMRI vs EEG for same task)
- Clinical prediction (e.g., MDD biomarker search)
- Meta-analytic review of a brain region
```

**Co-authorship threshold**: 3 end-to-end papers

---

### B4. Top Questions in Neuroimaging (Curated Research Questions)

Create a **curated list of top research questions** that Brain Researcher should be able to answer. These become both demo cases and benchmark items.

**Existing query infrastructure**: 50 basic queries + 22 science queries in [`benchmarks/br-kg/`](file://<repo>/benchmarks/br-kg/)

**What we need**:

| Category | Example questions | Issue |
|---|---|---|
| Methods controversies | "Should I use cluster-level vs voxel-level correction?" | `contribute/top-q-methods` |
| Open scientific questions | "What is the neural basis of individual differences in WM capacity?" | `contribute/top-q-open-science` |
| Reproducibility challenges | "Which fMRI findings have failed to replicate, and why?" | `contribute/top-q-reproducibility` |
| Clinical translation | "Can resting-state FC predict treatment response in MDD?" | `contribute/top-q-clinical` |
| Multi-modal integration | "How to jointly analyze fMRI + EEG for the same paradigm?" | `contribute/top-q-multimodal` |
| Best practices debates | "fMRIPrep vs custom pipelines: when does each win?" | `contribute/top-q-best-practices` |
| Emerging techniques | "When should I use graph neural networks vs CPM?" | `contribute/top-q-emerging` |
| Dataset recommendations | "Best public dataset for studying working memory?" | `contribute/top-q-datasets` |
| Statistical methods | "Fixed-effects vs mixed-effects for group-level fMRI?" | `contribute/top-q-stats` |
| Tool selection | "FSL vs FreeSurfer vs ANTs for registration?" | `contribute/top-q-tool-selection` |

**Issue template:**

```
Title: [Top Questions] {category} — curate {N} questions
Labels: contribution, top-questions, {category}

## Description
Curate {N} important research questions in {category} that Brain Researcher should handle well.

## Requirements per question
- Clear, unambiguous question text
- Expected answer approach (which tools/workflows to use)
- Reference answer (what a domain expert would say)
- Difficulty level (beginner / intermediate / expert)
- Tags (modalities, methods, topics)

## Deliverable
YAML file added to `benchmarks/br-kg/queries_{category}.yaml`
```

**Co-authorship threshold**: 20 curated questions

---

### B5. Manuscript Figures & Content

**3 manuscripts** are in preparation:

| Paper | File | Status |
|---|---|---|
| Paper 1: BrainResearcherBenchmark | [`paper1_brainresearcherbenchmark.md`](file://<repo>/manuscript/paper1_brainresearcherbenchmark.md) (37KB) | Draft |
| Paper 2: Brain Researcher System | [`paper2_brain_researcher.md`](file://<repo>/manuscript/paper2_brain_researcher.md) (44KB) | Draft |
| Paper 3: BR-KG as RL Env | [`paper3_br_kg_gym.md`](file://<repo>/manuscript/paper3_br_kg_gym.md) (14KB) | Skeleton |

**8 placeholder figures** need real implementations:

| Figure | Description | Issue |
|---|---|---|
| `fig1_graphical_abstract` | Graphical abstract / system overview | `contribute/fig-graphical-abstract` |
| `fig2_capability_decomposition` | Capability decomposition diagram | `contribute/fig-capability` |
| `fig3_suite_composition` | Benchmark suite composition | `contribute/fig-suite-composition` |
| `fig4_curation_workflow` | Curation workflow diagram | `contribute/fig-curation-workflow` |
| `fig5_baseline_coverage` | Baseline model coverage | `contribute/fig-baseline-coverage` |
| `fig6_cross_suite_dissociation` | Cross-suite performance dissociation | `contribute/fig-cross-suite` |
| `fig7_software_science_quadrant` | Software vs science quadrant | `contribute/fig-sw-science-quadrant` |
| `fig8_failure_taxonomy` | Failure taxonomy visualization | `contribute/fig-failure-taxonomy` |

**Issue template:**

```
Title: [Figure] {figure_name} for Paper {N}
Labels: contribution, manuscript, figure

## Description
Create publication-quality figure for {figure_description}.

## Requirements
- Vector format (PDF/SVG) + high-res PNG (300 DPI)
- Consistent color scheme with other figures
- Clear labels and legends
- Accessible to color-blind readers
```

**Co-authorship threshold**: 3 figures + minor text contributions

---

### B6. New Benchmark Tasks

Add new benchmark tasks to any of the 4 existing suites, or create new evaluation dimensions.

**Existing suites and gaps**:

| Suite | Current | Gap / need |
|---|---|---|
| QABench | 137 | More NEUROSCIENTIFIC_KNOWLEDGE (only 14 vs 27 STATS) |
| QARubric | 94 | Balance across categories |
| MetaAnalysis | 63 | More meta_screening (only 12) |
| CodeBench | 95 | Only 2 Real-time/Streaming, 2 Workflow tasks |

**New suite ideas**:

| Suite | Description | Issue |
|---|---|---|
| NeuroimageDebugBench | Debugging broken pipelines / bad outputs | `contribute/suite-debug-bench` |
| NeuroimageEthicsBench | Ethical considerations in neuroimaging research | `contribute/suite-ethics-bench` |
| NeuroimageReproducibilityBench | Can the agent reproduce published findings? | `contribute/suite-repro-bench` |
| NeuroimageClinicalBench | Clinical decision support scenarios | `contribute/suite-clinical-bench` |

**Issue template:**

```
Title: [New Benchmark] {task_title}
Labels: contribution, benchmark, {suite}

## Task spec (Harbor format)
- id: {unique_id}
- title: {title}
- instruction: {clear instructions}
- input: {context/data}
- expected_outputs: [{expected answers}]
- category: {category}
- difficulty: {easy|medium|hard}
- tags: [{relevant tags}]
```

**Co-authorship threshold**: 15 new benchmark tasks

---

### B7. KG Expansion (New Nodes & Edges)

Expand BR-KG beyond the current 355 retrieval entries + 90 taxonomy entities.

**Priority areas**:

| Area | Description | Issue |
|---|---|---|
| New datasets | Add OpenNeuro datasets released in 2025–2026 | `contribute/kg-new-datasets` |
| Clinical ontology | Add clinical disorder nodes + edges | `contribute/kg-clinical-ontology` |
| Method provenance | Connect methods → papers → datasets | `contribute/kg-method-provenance` |
| Cognitive atlas sync | Ensure alignment with latest Cognitive Atlas | `contribute/kg-cogat-sync` |
| Genetics/imaging links | Add gene-brain-behavior nodes | `contribute/kg-gene-brain` |
| Longitudinal metadata | Add time-series / developmental trajectory edges | `contribute/kg-longitudinal` |

**Co-authorship threshold**: 30 new validated nodes+edges

---

### B8. Tutorial & Example Scripts

Expand the **10 existing examples** into comprehensive tutorials:

| Existing Script | Size | Issue |
|---|---|---|
| `api_demo_example.py` | 10 KB | `contribute/tutorial-api-demo` |
| `comprehensive_demo.py` | 16 KB | `contribute/tutorial-comprehensive` |
| `nilearn_decoding_example.py` | 6 KB | `contribute/tutorial-decoding` |
| `parameter_inference_example.py` | 12 KB | `contribute/tutorial-param-inference` |
| `smart_search_workflow.py` | 10 KB | `contribute/tutorial-smart-search` |
| `spatial_roi_search_example.py` | 6 KB | `contribute/tutorial-spatial-roi` |
| `tool_executor_example.py` | 11 KB | `contribute/tutorial-tool-executor` |

**New tutorials needed**:

| Tutorial | Description | Issue |
|---|---|---|
| Getting Started | 5-minute quickstart for new users | `contribute/tutorial-quickstart` |
| First GLM Analysis | Step-by-step task-based fMRI GLM | `contribute/tutorial-first-glm` |
| KG Exploration | How to navigate BR-KG | `contribute/tutorial-kg-explore` |
| Custom Pipeline | Build your own workflow from scratch | `contribute/tutorial-custom-pipeline` |
| Hypothesis to Analysis | Full cycle with hypothesis explorer | `contribute/tutorial-hypothesis` |
| MCP Integration | Using BR tools from Claude/Cursor | `contribute/tutorial-mcp` |

**Co-authorship threshold**: 5 tutorials

---

### B9. Data Ingestion (New Data Sources)

**Existing ingestion infrastructure** supports: BIDS, NeuroStore, OpenNeuro, PubMed, ENIGMA, BrainMap, NWB.

**New sources to add**:

| Source | Description | Issue |
|---|---|---|
| ABCD Study | Adolescent Brain Cognitive Development | `contribute/ingest-abcd` |
| UK Biobank | Large-scale population imaging | `contribute/ingest-ukb` |
| HCP datasets | Human Connectome Project | `contribute/ingest-hcp` |
| NeuroVault collections | Statistical maps | `contribute/ingest-neurovault` |
| BALSA | Brain Analysis Library of Spatial Maps | `contribute/ingest-balsa` |
| NITRC | Neuroimaging Informatics Tools & Resources | `contribute/ingest-nitrc` |

**Co-authorship threshold**: 2 new data sources integrated

---

## Summary (All Tracks)

### Review/Eval Track (no experiments)

| Category | Items | Issues | Threshold |
|---|---|---|---|
| Benchmark Review | 389 | 41 | 20 items |
| Tool/Workflow Review | 83 | 83 | 20 items |
| KG Review | 445 | 24 | 20 items |
| Hypothesis/Demo/UI Review | 40 | 40 | 20 items |
| **Subtotal** | **957** | **188** | |

### Creative Contribution Track (new work)

| Category | Potential | Issues | Threshold |
|---|---|---|---|
| B1. New Tool Integration | 2,339 tools | open | 10 tools |
| B2. New Workflow Design | unlimited | open | 5 workflows |
| B3. E2E Paper Generation | unlimited | open | 3 papers |
| B4. Top Questions | unlimited | 10 categories | 20 questions |
| B5. Manuscript Figures | 8 figures | 8 | 3 figures |
| B6. New Benchmark Tasks | unlimited | open | 15 tasks |
| B7. KG Expansion | unlimited | 6 areas | 30 nodes+edges |
| B8. Tutorials | 13+ | 13+ | 5 tutorials |
| B9. Data Ingestion | 6+ sources | 6+ | 2 sources |

---

## Co-authorship Summary

| Track | What you do | Threshold | Est. time |
|---|---|---|---|
| Review only | Evaluate existing items | 20 items | ~3.5 hrs |
| New tools | Integrate tools from tool universe | 10 tools | ~4 hrs |
| New workflows | Design analysis pipelines | 5 workflows | ~5 hrs |
| E2E papers | Run full research pipeline | 3 papers | ~6 hrs |
| Top questions | Curate research questions | 20 questions | ~4 hrs |
| Figures | Create publication figures | 3 figures | ~4 hrs |
| Benchmarks | Write new evaluation tasks | 15 tasks | ~4 hrs |
| KG expansion | Add new knowledge | 30 items | ~5 hrs |
| Tutorials | Write example scripts | 5 tutorials | ~5 hrs |
| Data ingestion | Connect new data sources | 2 sources | ~6 hrs |

---

*Brain Researcher · Stanford University · February 2026*
