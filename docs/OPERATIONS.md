# Brain Researcher — Operations Guide

Detailed dev / ops content moved out of `README.md` to keep the top-level
file focused on the academic-audience intro. This page consolidates:

- Service-by-service local run instructions
- Neo4j / KG setup
- CLI command reference
- Neurodesk / CVMFS / module-system integration
- Docker stack usage
- Troubleshooting

For a quick `docker compose up` onboarding flow, see the root [README](../README.md).
For HPC / SLURM use, see [`hpc.md`](hpc.md).

---

## Service layout (local dev)

The recommended local layout runs each service on its canonical port:

| Service | Port | Command |
|---|---|---|
| BR-KG API | 5000 | `br serve kg` |
| Agent API | 8000 | `br serve agent` |
| Orchestrator | 3001 | `br serve orchestrator --port 3001` |
| Web UI | 3000 | `br serve web` |

Or run the full local stack wrapper:

```bash
./scripts/services/start_services.sh
```

**Frontend dev env** (`apps/web-ui/.env.local`):

```env
NEXT_PUBLIC_USE_API_PROXY=true
BR_AGENT_URL=http://127.0.0.1:8000
BR_ORCHESTRATOR_URL=http://127.0.0.1:3001
BR_KG_URL=http://127.0.0.1:5000
# Optional only when you need a custom browser WebSocket route:
# NEXT_PUBLIC_WS_URL=ws://127.0.0.1:3001/ws
```

The default browser-safe setup is same-origin proxy mode. Only set
direct browser-facing `NEXT_PUBLIC_*` service URLs if you intentionally
want the Web UI to bypass its proxy layer.

---

## Neo4j (BR-KG backend)

The BR-KG service requires Neo4j (no SQLite fallback).

- Start a local Neo4j instance via Docker Compose (`docker compose up neo4j`)
  or standalone `docker run`.
- Seed local test data only when you have an authorized local mini dump:

  ```bash
  scripts/tools/dev/seed_from_dump.sh    # defaults to data/neo4j/mini_dump
  ```

- Env vars used by services and tests:
  - `NEO4J_URI` (default `bolt://localhost:7687`)
  - `NEO4J_USER` (default `neo4j`)
  - `NEO4J_PASSWORD`

The full compiled BR-KG graph and Neo4j dumps are private. This public
repository does not ship a full KG dump and does not publish one as a GitHub
Release attachment.

---

## CLI command reference

```bash
# Database management
br db init                              # initialize databases
br db status                            # check status
br db optimize                          # rebuild indexes

# Data ingestion
br data load-pubmed --input file.json
br data load-openneuro --dataset ds000001
br ingest openneuro ds000001

# Query and search
br query search "motor cortex"
br query cypher "MATCH (n:BrainRegion) RETURN n LIMIT 10"
br query stats

# Analysis
br analyze contrast --data scan.nii.gz --output results.json
br analyze statistical --data study/ --params '{"threshold": 0.05}'

# Interactive chat
br chat
br chat --model gpt-4

# Demo case studies (5 bundled)
br demo run case1
```

---

## MCP tool schema

- Machine-readable MCP tool schema + examples: `docs/mcp_tools.schema.json`
- Human-readable notes: `docs/mcp.md`

### Planner autorun and cache smoke test

To exercise the full plan→execute→cache flow locally:

1. Copy `.env.local.example` to `.env.local` (or export the same vars in
   your shell). The defaults pin `BR_PLANNER_MODE=autorun`,
   `BR_PLANNER_SOURCE=catalog`, `AGENT_TOOL_ALLOWLIST=*`,
   `BR_SANDBOX_ENABLED=true`, `BR_DAG_MAX_CONCURRENCY=2`,
   `BR_CACHE_ENABLED=true`, and `BR_CACHE_MODE=fast`.
2. Launch services:
   ```bash
   PORT=8000 gunicorn -w 1 -b 0.0.0.0:8000 \
     "brain_researcher.services.agent.web_service:app"
   uvicorn brain_researcher.services.orchestrator.main_enhanced:app --port 3001
   ```
3. Run `scripts/dev/run_agent_e2e.sh`:
   - Submits `/run`, waits for the autorun DAG, streams job status.
   - Hits `/api/runs/resolve?key=...` when a cache key is present.
   - Replays the same `/run` to verify cache fast-path.

### Live streaming (`/run?stream=1`)

```bash
curl -N \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  'http://localhost:3001/run?stream=1' \
  -d '{
        "prompt": "compute demo connectivity",
        "pipeline": "connectivity",
        "parameters": {
          "fmri_img": "/tmp/demo_bold.nii.gz",
          "atlas_name": "Schaefer2018_200"
        }
      }'
```

The stream begins with an `accepted` event followed by `step_*` and
`plan_completed` events.

---

## Neurodesk / CVMFS integration

Brain Researcher integrates with Neurodesk for 100+ pre-built
neuroimaging containers.

```bash
# Verify setup
module avail                            # list available tools
cvmfs_config stat neurodesk.ardc.edu.au | grep CACHEMAX

# Load tools
module load fsl/6.0.7.16                # FSL 6.0.7
module load mrtrix3/3.0.7               # MRtrix3
module load physio/r7771                # SPM12 + PhysIO

# Direct container invocation
/cvmfs/neurodesk.ardc.edu.au/containers/fsl_6.0.7.16_20250131/bet input.nii output.nii
/cvmfs/neurodesk.ardc.edu.au/containers/mrtrix3_3.0.7_20250805/mrinfo dwi.mif
```

**Performance optimizations applied** (when configured via the included
`scripts/install_latest_containers.sh`):

- 300 GB CVMFS cache on NVMe for fast container access
- Apptainer cache at `/var/tmp/.apptainer-cache`
- Runtime caches (TemplateFlow, MCR) on NVMe
- First-time downloads cached for instant subsequent access

**System requirements:**
- Linux with CVMFS support
- Apptainer/Singularity runtime
- Sufficient disk space (containers can be large)
- Network access for initial downloads

---

## Docker stack

```bash
# Quick start: run default runtime services
docker compose up -d

# Include the optional orchestrator worker
docker compose --profile worker up -d

# Or use the helper script
./scripts/docker_manager.sh start

# Check status
./scripts/docker_manager.sh status
```

Compose runs `init-local-dirs` as a one-shot setup job before the Python
services. It creates writable `data/agent_outputs/`, `data/br-kg/`, and
`logs/` directories for the non-root containers and should show as exited 0 in
`docker compose ps`.

**Default service URLs:**

- BR-KG API: http://localhost:5000
- Agent API: http://localhost:8000
- Orchestrator API: http://localhost:3001
- Web UI: http://localhost:3000

---

## Testing

```bash
pytest                                  # full suite
pytest --cov=brain_researcher           # with coverage
pytest tests/unit/                      # unit only
pytest tests/integration/               # integration only
```

E2E browser tests (Playwright) live under `apps/web-ui/tests/e2e/`.

---

## Troubleshooting

### Neurodesk / CVMFS issues

```bash
# Check CVMFS mount status
ls /cvmfs/neurodesk.ardc.edu.au/

# Verify CVMFS cache and quota
cvmfs_config stat neurodesk.ardc.edu.au

# Check module system
module avail
module list

# Reset modules if needed
module purge
module load fsl/6.0.7.16
```

### Performance issues

- **Slow first-time loading**: normal for large containers (~1–2 min),
  cached thereafter
- **Module load fails**: check CVMFS connectivity with
  `cvmfs_config probe`
- **Cache full**: increase quota in `/etc/cvmfs/default.local` or clean
  cache
- **Permission errors**: verify `/var/tmp/.apptainer-cache` permissions

### Environment variables

```bash
# Key variables set automatically by setup script:
echo $APPTAINER_CACHEDIR     # should be /var/tmp/.apptainer-cache
echo $TEMPLATEFLOW_HOME      # should be ~/.cache/templateflow
echo $CVMFS_QUOTA_LIMIT      # should be 300000 (300 GB)
```
