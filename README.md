# Brain Researcher

**An LLM-driven research assistant for neuroimaging.** Brain Researcher combines a large-language-model planning loop with a neuroscience knowledge graph (Neo4j), a curated catalog of fMRI / diffusion / EEG analysis tools, and an evidence-grounded scientific-review system. It turns natural-language research questions into reproducible analyses, with every step traceable to its plan, inputs, and primary literature.

> **Status — v0.1.0 OSS preview.** Stable surface (10 closed-loop MCP tools, contract_version `2026-05-27`) + companion agent-kit. The canonical citation, Zenodo DOI, and arXiv preprint will be linked here at the v1.0 launch.

📦 **Companion kit** (skills, AGENTS templates, demos, eval rubrics): [`brain-researcher-agent-kit`](https://github.com/zjc062/brain-researcher-agent-kit)
🗂️ **Public KG snapshot** (sanitized Neo4j dump): attached to each GitHub Release — see [`docs/neurokg/public_dump.md`](docs/neurokg/public_dump.md)
📊 **Benchmark scope:** the task corpus is not shipped in this repo — see [`docs/release/benchmark.md`](docs/release/benchmark.md)

<p align="center">
  <img src="docs/assets/doraemon/0.png" alt="Brain Researcher Doraemon frame 1" width="620"><br>
  <img src="docs/assets/doraemon/1.png" alt="Brain Researcher Doraemon frame 2" width="620"><br>
  <img src="docs/assets/doraemon/2.png" alt="Brain Researcher Doraemon frame 3" width="620"><br>
  <img src="docs/assets/doraemon/3.png" alt="Brain Researcher Doraemon frame 4" width="620"><br>
  <img src="docs/assets/doraemon/4.png" alt="Brain Researcher Doraemon frame 5" width="620"><br>
  <img src="docs/assets/doraemon/5.png" alt="Brain Researcher Doraemon frame 6" width="620">
</p>

---

## What it does

- **Plan → Recipe → Verify loop.** Natural-language research questions become typed plans, MCP recipes, local/agent handoff prompts, and evidence-grounded reports. Hosted execution is surfaced only when runtime readiness, auth, and credits pass.
- **Brain-researcher knowledge graph (BR-KG).** Neo4j-backed graph linking concepts, brain regions, datasets, tasks, methods, papers, and tools. Supports multi-hop QA, hypothesis-candidate retrieval, behavior↔fMRI cross-modal queries.
- **MCP tool surface.** Planning, KG search, workflow recipes, run inspection, scientific review, deep research, and hypothesis workflows exposed via the [Model Context Protocol](https://modelcontextprotocol.io/) — usable from Claude Code, Codex, Cursor, or any MCP client. v0.1.0 ships **10 stable-tier tools** with versioned JSON contracts under [`contracts/tools/`](contracts/tools/); 89 additional tools are exposed as `experimental`.
- **Neuroimaging toolchain.** Workflow recipes target [Neurodesk](https://www.neurodesk.org/) containers (FSL, MRtrix3, SPM, ANTs, FreeSurfer, fMRIPrep, MRIQC, …) and Python packages such as Nilearn, MNE, NiMARE, and custom pipelines.
- **SLURM-ready.** Pluggable cluster profiles (`configs/slurm/profiles/*.yaml`) — easy to add your own.

---

## Architecture (high level)

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              Web UI  (Next.js)                              │
│  chat · studio · KG · dataset explorer · hypothesis · 3D brain viewer       │
└────────────┬──────────────────────────┬─────────────────────────────────────┘
             │                          │
             ▼                          ▼
   ┌────────────────────┐    ┌────────────────────┐     ┌───────────────────┐
   │   Orchestrator     │◀──▶│       Agent        │◀───▶│   MCP Server      │
   │  (FastAPI / SSE)   │    │ (LLM router +      │     │ 10 stable + ~90   │
   │ plans, runs, jobs  │    │   tool executor)   │     │ experimental tools│
   └────────┬───────────┘    └────────┬───────────┘     └─────────┬─────────┘
            │                         │                           │
            ▼                         ▼                           │
   ┌────────────────────┐    ┌────────────────────┐               │
   │     BR-KG API      │    │   Tool catalog     │◀──────────────┘
   │  (Neo4j-backed,    │    │ Nilearn / MNE /    │
   │ concepts · regions │    │ NiMARE / fMRIPrep /│
   │ · papers · tools)  │    │ Neurodesk modules  │
   └────────────────────┘    └────────────────────┘
```

For a deeper dive see [`docs/architecture/`](docs/architecture/) (incl. `codegraph_baseline.md` for the import-graph baseline that CI enforces, and `contract-tiers.md` for the two axes — stability and surface_tier — that govern the MCP surface).

---

## Quick start (local Docker)

Brings up the full 5-service stack: Neo4j + Redis + BR-KG + agent + web UI.

```bash
git clone https://github.com/zjc062/brain-researcher-public.git
cd brain-researcher-public

# 1. Set required env vars (at least: NEO4J_PASSWORD, JWT_SECRET_KEY, NEXTAUTH_SECRET, one LLM API key).
cp .env.example .env
$EDITOR .env

# 2. Start the stack (5 services).
docker compose up -d

# 3. Verify: all 5 services healthy in ~30s.
docker compose ps
# → neo4j, redis, neurokg, agent, web-ui   (Status: healthy)

# 4. Open the web UI.
xdg-open http://localhost:3000   # or just navigate in your browser
```

**Port collision?** Override defaults via env vars:

```bash
BR_NEO4J_HTTP_PORT=7484 BR_NEO4J_BOLT_PORT=7697 BR_NEUROKG_PORT=5010 \
  AGENT_PORT=8010 WEB_UI_PORT=3010 \
  docker compose -p brpub up -d
```

**Minimal env vars** (see [`docs/ENVIRONMENT_SETUP.md`](docs/ENVIRONMENT_SETUP.md) for full reference):

| Variable | Purpose | Notes |
|---|---|---|
| `NEO4J_PASSWORD` | KG password | ≥ 8 chars |
| `JWT_SECRET_KEY` | service auth signing | ≥ 32 chars |
| `NEXTAUTH_SECRET` | web UI session signing | ≥ 32 chars |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` | LLM access (any one) | — |

### Optional: load the public KG snapshot

The first boot brings up an empty Neo4j. To populate it with the sanitized public KG snapshot (~50K nodes spanning Atlas / Author / Concept / Dataset / Publication / Region / Task / GABRIEL claims / review catalog):

```bash
./scripts/oss/download_public_kg.sh v0.1.0
# → curls dump + sha256 + manifest from the GitHub Release,
#   verifies integrity, loads into the running compose neo4j.
```

See [`docs/neurokg/public_dump.md`](docs/neurokg/public_dump.md) for what's in vs out of the dump and license-aggregation notes.

---

## Install as a Python package

The MCP server + CLI live under `packages/brain-researcher/`:

```bash
pip install -e packages/brain-researcher[all]
brain-researcher --help
```

Core CLI surfaces (`br` is a short alias; on systems where `br` is shadowed, use `brain-researcher`):

```bash
brain-researcher chat                            # interactive chat with the agent
brain-researcher serve agent | kg | mcp | web    # individual services
brain-researcher db init                         # initialize databases
brain-researcher data load-openneuro --dataset ds000114
```

For HPC / SLURM usage, see [`docs/hpc.md`](docs/hpc.md). For the contract layer that governs which tool names are stable across releases, see [`docs/contract-tiers.md`](docs/contract-tiers.md) and inspect `contracts/tools/*.json`.

---

## Kubernetes / Helm

Two deployment paths under [`infrastructure/k8s/`](infrastructure/k8s/):

```bash
# Helm chart (recommended)
helm template brain-researcher infrastructure/k8s/helm/brain-researcher/ \
  -f your-values.yaml | kubectl apply -f -

# Or raw manifests
kubectl apply -f infrastructure/k8s/manifests/
# (08-ingress.yaml requires Istio CRDs — see infrastructure/k8s/helm/brain-researcher-istio/README.md)
```

The main helm chart renders 26 K8s resources cleanly; the istio overlay subchart is experimental (see its README for known template bugs).

---

## What's in the repo

| Directory | Purpose |
|---|---|
| `packages/brain-researcher/src/brain_researcher/` | Python package: CLI, core, services (agent / MCP / BR-KG / orchestrator), semantics, autoresearch |
| `packages/brain-researcher/src/brain_researcher/br/` | Stable re-export namespace: `br.retry`, `br.provenance`, `br.artifact`, `br.http`, `br.redaction` |
| `packages/cli/` | Auxiliary CLI package |
| `apps/web-ui/` | Next.js 14 frontend (chat, studio, demo replay, KG explorer) |
| `contracts/` | OSS API stability surface: `VERSION`, `br-tool-contract.schema.json`, `tools/*.json` (10 stable-tier tool schemas) |
| `configs/` | Tool catalogs, mappings, taxonomy, demo bundles, SLURM profiles |
| `docs/` | Architecture, operations, MCP, neurokg, how-to-add-tool, contract-tiers, migration |
| `tests/` | Unit + integration + contracts (Pact) + e2e (Playwright) |
| `infrastructure/` | docker-compose, Helm chart, K8s manifests, monitoring, nginx, haproxy |
| `scripts/` | ETL / analysis / build / CI helpers; OSS-specific tools under `scripts/oss/` |

For the full source-tree layout and import-graph baseline, see [`docs/architecture/codegraph_baseline.md`](docs/architecture/codegraph_baseline.md). For the agent-kit (skills + AGENTS templates + adapters + demos + eval rubrics), see the companion repo [`brain-researcher-agent-kit`](https://github.com/zjc062/brain-researcher-agent-kit).

---

## Citation

If you use Brain Researcher in published work, please cite:

```bibtex
@misc{brain_researcher_2026,
  author       = {Chen, Zijiao and {Brain Researcher contributors}},
  title        = {Brain Researcher: An LLM-driven Research Assistant for Neuroimaging},
  year         = {2026},
  howpublished = {\url{https://github.com/zjc062/brain-researcher-public}},
  note         = {arXiv:XXXX.XXXXX (preprint pending); Zenodo DOI pending}
}
```

A machine-readable citation lives in [`CITATION.cff`](CITATION.cff) and will be updated with the arXiv ID and Zenodo DOI at v1.0 release.

---

## Contributing

We welcome bug reports, feature ideas, case studies, and code contributions.

- **Read first:** [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev workflow, codegraph-accelerated review, test conventions.
- **Code of conduct:** [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
- **Security:** report vulnerabilities privately per [`SECURITY.md`](SECURITY.md); see also [`THREAT_MODEL.md`](THREAT_MODEL.md) for the MCP server attack surface and [`REDACTION_POLICY.md`](REDACTION_POLICY.md) for the redaction rules applied by `br.redaction`.
- **Adding a new tool:** see [`docs/how-to-add-tool.md`](docs/how-to-add-tool.md) for the workflow from `@mcp.tool` decoration through contract-layer inclusion.

For agent-policy templates (research / code-review / brain-researcher), see [`brain-researcher-agent-kit/agents/`](https://github.com/zjc062/brain-researcher-agent-kit).

---

## Acknowledgments

Brain Researcher builds on the work of many open-source neuroscience projects:

- **Datasets and ontologies:** [OpenNeuro](https://openneuro.org/), [BIDS](https://bids.neuroimaging.io/), [Cognitive Atlas](https://www.cognitiveatlas.org/), [NeuroSynth](https://neurosynth.org/), [NeuroBagel](https://neurobagel.org/), [Allen Brain Atlas](https://portal.brain-map.org/)
- **Toolchains:** [Nilearn](https://nilearn.github.io/), [MNE-Python](https://mne.tools/), [NiMARE](https://nimare.readthedocs.io/), [fMRIPrep](https://fmriprep.org/), [MRIQC](https://mriqc.readthedocs.io/), [FSL](https://fsl.fmrib.ox.ac.uk/), [Neurodesk](https://www.neurodesk.org/)
- **Infrastructure:** [Model Context Protocol](https://modelcontextprotocol.io/), [Neo4j](https://neo4j.com/), [Next.js](https://nextjs.org/), [FastAPI](https://fastapi.tiangolo.com/)

---

## License

[MIT](LICENSE) — © 2026 Brain Researcher Team
