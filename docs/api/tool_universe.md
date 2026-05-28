# Tool Universe (Semantic + Backend Families)

This document fixes the taxonomy used across chat/planner/router and backend execution. Treat it as the “universe law” — avoid renaming families unless absolutely necessary.

Canonical runtime tool IDs are specified separately in [canonical_runtime_tool_ids.md](<repo>/docs/specs/canonical_runtime_tool_ids.md). Public planner/runtime surfaces should use those canonical IDs, while backend families remain internal.

## Semantic (Chat/Planner) Families
- ai.llm
- ai.coding
- gemini.fs
- gemini.net
- jobs
- datasets (covers datasets.*, openneuro.*, dandi.*)
- neurokg.client
- neurokg.datasets
- kg.admin
- literature/meta (concept_literature_search, literature_mining, meta_analysis ops)
- fmri.preproc
- fmri.glm
- fmri.connectivity
- fmri.light
- dmri
- smri/surface
- eeg
- ieeg
- pet/clinical
- realtime/neurofeedback
- visualization/report (viz)
- ml.decoding
- meta_analysis
- harmonization/qc
- advanced_analysis
- specialized
- simulation.stub
- misc.client (catch-all minimal set only if needed)

## Backend (Internal) Families
- container.afni
- container.ants
- container.fsl
- container.bidsapp
- container.mrtrix
- container.palm
- neurodesk.client
- niwrap.client
- mcp.client

Principles:
- Chat surfaces only semantic families (via chat_tools.yaml). Backend/internal families stay hidden unless explicitly exposed for power/CLI use.
- Each runtime tool must belong to a semantic family or be explicitly marked standalone/misc.
- Each backend tool must be referenced by a canonical leaf `backend` block or marked internal.
- ToolSpec metadata should include at least: domain, runtime_kind, function, risk, backend (optional), and family.
