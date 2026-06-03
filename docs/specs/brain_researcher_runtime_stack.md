# Brain Researcher Runtime Stack

## Overview

Brain Researcher uses a three-layer runtime contract that works identically
in local development and on GCP. The orchestrator is the **control plane only**
— it schedules work but never hosts the execution environment itself.

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1 — Jupyter kernel                               │
│  Notebook cell execution protocol                       │
│  kernel name: "brain_researcher"                        │
├─────────────────────────────────────────────────────────┤
│  Layer 2 — conda env: brain_researcher                  │
│  Python runtime: nilearn, nibabel, brain_researcher,    │
│  langchain, neo4j, numpy, scipy, ...                    │
│  Spec: environment.brain_researcher.yml                 │
├─────────────────────────────────────────────────────────┤
│  Layer 3 — Neurodesk modules (CVMFS)                    │
│  Heavy neuroimaging CLI tools                           │
│  Access: module load fsl/6.0.7.18                       │
│  Path:   /cvmfs/neurodesk.ardc.edu.au                   │
└─────────────────────────────────────────────────────────┘
```

---

## Layer 1 — Jupyter Kernel

**Role:** Notebook cell execution protocol. Every `.ipynb` cell that runs
code goes through a Jupyter kernel — never through the orchestrator directly.

**Kernel name:** `brain_researcher`

**Configuration variables:**

| Variable | Description |
|----------|-------------|
| `BR_STUDIO_JUPYTER_BASE_URL` | Base URL of the Jupyter server (no trailing slash) |
| `BR_STUDIO_JUPYTER_BASE_URL_TEMPLATE` | Template for multi-user JupyterHub (`{jupyter_user_name}`, `{owner_user_id}`, etc.) |
| `BR_STUDIO_JUPYTER_TOKEN` | Authentication token |
| `BR_STUDIO_JUPYTER_KERNEL_NAME` | Kernel name to bind for Studio execution (`brain_researcher` locally) |

**Local:** A Jupyter server started from the `brain_researcher` conda env.
Run `bash scripts/setup/setup_local_runtime.sh` — it starts the server and prints
the exact env vars to add to `.env.local`.

**GCP:** JupyterHub per-user server. `BR_STUDIO_JUPYTER_BASE_URL_TEMPLATE`
expands to `https://hub.example.com/user/{jupyter_user_name}`.
The kernel image is the `brain_researcher` singleuser Docker image (built from
`environment.brain_researcher.yml`).

**Why not orchestrator-direct?**
The orchestrator's local fallback (`shell_command` tool path) has no registered
handler and will fail. Jupyter kernel is the correct and only execution
protocol for notebook cells.

---

## Layer 2 — conda env: brain_researcher

**Role:** The Python runtime for all BR analysis code, agent logic, and
neuroimaging Python packages. Shared by the Jupyter kernel, CLI scripts,
and batch Python jobs.

**Canonical spec:** `environment.brain_researcher.yml` (repo root)

**Contents (explicit runtime packages + `pip install -e .`):**
- Neuroimaging Python: `nilearn`, `nibabel`, `nimare`, `neuromaps`, `templateflow`
- Agent stack: `langchain`, `langgraph`, `langchain-openai`, `langchain-anthropic`
- MCP: `mcp`, `sequential-thinking-mcp`
- Knowledge graph: `neo4j`, `SPARQLWrapper`, `rdflib`
- Brain Researcher package itself (`brain_researcher.*`)
- Supporting: `numpy`, `scipy`, `pandas`, `matplotlib`, `redis`, `fastapi`, ...

**Not included** (by design):
- `apache-airflow` — infra-only, not needed for analysis
- `pytest`, `black`, `ruff`, `mypy` — dev tooling only
- `mkdocs` — docs build only
- `genetics`, `pet`, `optical` extras — domain-specific, install separately

**Local setup:**
```bash
conda env create -f environment.brain_researcher.yml  # env name: brain_researcher
conda activate brain_researcher
python -m ipykernel install --user --name brain_researcher --display-name "Brain Researcher"
```

Or use the setup script: `bash scripts/setup/setup_local_runtime.sh`

**GCP:** Bake into the singleuser Docker image. Because the package uses an
editable install (`-e .`), the source must be present at image-build time:
```dockerfile
FROM jupyter/base-notebook:python-3.11

# Copy the full source (needed for -e . in environment.brain_researcher.yml)
COPY . /opt/brain_researcher/
WORKDIR /opt/brain_researcher

# Create the execution runtime env from the canonical spec
COPY environment.brain_researcher.yml /tmp/
RUN conda env create -n brain_researcher -f /tmp/environment.brain_researcher.yml \
 && conda run -n brain_researcher \
      python -m ipykernel install --sys-prefix \
        --name brain_researcher --display-name "Brain Researcher"

# Set default kernel
ENV JUPYTER_KERNEL_NAME=brain_researcher
```

**Consistency guarantee:** Local and GCP use the same `environment.brain_researcher.yml`.
The only difference is how the Jupyter server URL is configured.

---

## Layer 3 — Neurodesk Modules (CVMFS)

**Role:** Heavy neuroimaging CLI tools that require compiled binaries and
dedicated containers: FSL, ANTs, CAT12, FreeSurfer, MRtrix3, fMRIPrep, etc.

**Access mechanism:**
```bash
# In any script or notebook cell (after module system init):
module load fsl/6.0.7.18
bet /data/T1.nii.gz /out/brain.nii.gz -f 0.5
```

**CVMFS path:** `/cvmfs/neurodesk.ardc.edu.au`

**Module versions** (see `configs/runtime/execution_recipes.yaml` for full list):

| Tool | Module spec |
|------|-------------|
| FSL | `fsl/6.0.7.18` |
| ANTs | `ants/2.6.0` |
| CAT12 | `cat12/12.9` |
| FreeSurfer | `freesurfer/8.1.0` |
| fMRIPrep | `fmriprep/23.2.3` |
| MRtrix3 | `mrtrix3/3.0.7` |
| mriqc | `mriqc/24.0.2` |
| dcm2niix | `dcm2niix/v1.0.20240202` |

**Local:** Install Neurodesk or neurocommand; CVMFS mounted at
`/cvmfs/neurodesk.ardc.edu.au`. Verify: `module avail fsl`.

**GCP (k3s):** CVMFS hostPath mounted at `/cvmfs` on every k3s node. The
`NeurodeskDispatcher` (k8s mode) mounts it as a read-only `hostPath` volume
into each job Pod.

**Bridge to Layers 1–2:** `NeurodeskCompiler` compiles a WorkflowStep into
an `analysis_NN_tool.sh` script that:
1. Initializes Lmod: `source /etc/profile.d/lmod.sh`
2. Loads the module: `module load fsl/6.0.7.18`
3. Runs the CLI: `bet {input} {output} {flags}`

The compiled script is dispatched via `NeurodeskDispatcher` (handoff / k8s /
local mode). The Jupyter kernel in Layer 1 can call this script via
`subprocess` or `!sbatch` in a notebook cell.

---

## MCP Service Runtime vs Execution Runtime

These are **two separate, independent environments**. Do not conflate them.

```
MCP service runtime                  Execution runtime (this doc)
─────────────────────────────────    ────────────────────────────────────
Purpose: run MCP tools + agent       Purpose: run notebook cells + scripts
Env: whatever br/agent services use  Env: conda brain_researcher
Jupyter: not involved                Jupyter: required (Layer 1)
Config: BR_MCP_*, agent env vars     Config: BR_STUDIO_JUPYTER_BASE_URL
Changed by: this doc? NO             Changed by: this doc? YES
```

**Rule:** changes to `environment.brain_researcher.yml` affect notebook
execution only. They do not affect MCP services, the orchestrator, or the
agent web service — those run in their own Python environments and are not
started from this conda spec.

If you need to add a package to MCP/agent services, add it to `pyproject.toml`
(the relevant extra) and reinstall the dev environment. Do **not** add it here.

---

## Orchestrator Role

The orchestrator is the **control plane only**:
- Receives requests from the Studio UI
- Schedules jobs to Layer 1 (Jupyter kernel) or Layer 3 (NeurodeskCompiler)
- Never runs Python analysis code inline
- Never owns execution state for heavy jobs (fMRIPrep, FreeSurfer, etc.)

```
Studio UI
  ├── Cell execute  →  Layer 1 (Jupyter kernel)
  └── Assistant     →  Orchestrator plans → Layer 1 or Layer 3
                                              (never both in same process)
```

---

## Local Quick-Start

```bash
# 1. Create env + start Jupyter
bash scripts/setup/setup_local_runtime.sh

# 2. Copy output vars to .env.local
# BR_STUDIO_JUPYTER_BASE_URL=http://127.0.0.1:8888
# BR_STUDIO_JUPYTER_TOKEN=<token>
# BR_STUDIO_JUPYTER_KERNEL_NAME=brain_researcher
# BR_CONDA_ENV=brain_researcher

# 3. Restart orchestrator
br serve orchestrator

# 4. Open Studio UI → run a cell → no more "shell_command not found"
```

---

## GCP Deployment (follow-up, not yet implemented)

- `infrastructure/docker/Dockerfile.jupyter-singleuser`: builds from
  `environment.brain_researcher.yml`, installs brain_researcher kernel
- `infrastructure/jupyterhub/values.mvp.yaml`: sets
  `BR_STUDIO_JUPYTER_BASE_URL_TEMPLATE` to `https://hub.{domain}/user/{jupyter_user_name}`
- CVMFS provisioner: hostPath mount or CSI driver on k3s nodes

See `infrastructure/jupyterhub/` for in-progress Helm values.
