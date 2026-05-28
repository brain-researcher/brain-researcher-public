# Brain Researcher Agent Service

A LangGraph-based intelligent agent system for neuroscience research. It is the
primary downstream backend for Web UI chat, files, datasets, threads, and the
compatibility `/api/runs*` surface. Analysis execution and job inspection also involve
the standalone Orchestrator service.

## Overview

This service provides:
- **Agent-owned UI API** for chat/files/datasets/threads plus compatibility runs
- LangGraph-based tool orchestration
- Thread/message persistence (Redis-backed)
- Job/run management (JobStore-backed)
- File upload and dataset catalog search
- SSE streaming for real-time responses

## Architecture

```
[Browser]
     │
     ▼
[Next.js UI  (port 3000)]
     │
     ├─ `/api/chat`, `/api/files`, `/api/datasets`, `/api/threads`, compatibility `/api/runs*`
     │        ▼
     │   [Agent Service (port 8000)]  <-- This service
     │
     └─ `/api/analyses`, `/api/share`, `/api/dashboard`, `/api/jobs/*`
              ▼
         [Orchestrator (port 3001)]
     │
     ├─ NICLIP (:8001, internal tool)
     ├─ BR-KG (:5000, knowledge graph)
     ├─ toolhub / 150+ neuroimaging tools
     └─ Neo4j / Redis (state storage)
```

**Key principle:** Next.js owns the public browser-facing `/api/*` surface.
Agent is the primary downstream for chat/files/datasets/threads and the
compatibility `/api/runs*` surface.
Orchestrator owns `/run`, `/api/jobs/*`, and JobStore-backed analysis inspection
surfaces.

## API Endpoints

### Health & Config
- `GET /api/health` - Health check
- `GET /api/config/ui` - UI feature flags, modes

### Chat & Threads
- `POST /api/chat` - Main chat entry for the Web UI
- `POST /api/chat/stream` - SSE streaming chat
- `GET /api/threads/{thread_id}/messages` - Thread history
- `GET /api/threads/{thread_id}/stream` - SSE streaming for thread

### Tools
- `GET /api/tools` - List available tools
- `POST /api/tools/run` - Direct tool execution

### Runs
- `POST /api/runs` - Submit a compatibility Agent-backed run resource
- `GET /api/runs/{run_id}` - Compatibility run status
- `GET /api/runs/{run_id}/stream` - Compatibility SSE for run progress/logs

### Orchestrator-owned job surfaces
- `POST /run` - Canonical Orchestrator execution entrypoint
- `GET /api/jobs/{job_id}` - Canonical JobStore-backed job status
- `GET /api/jobs/{job_id}/steps` - Canonical step inspection
- `GET /api/analyses/{analysis_id}` - Canonical analysis bundle/detail surface

### Files
- `POST /api/files/upload` - Upload file (multipart)
- `GET /api/files` - List user's files
- `GET /api/files/{file_id}` - Download file
- `DELETE /api/files/{file_id}` - Delete file

### Datasets
- `POST /api/datasets/search` - Search dataset catalog
- `GET /api/datasets/{dataset_id}` - Dataset details

### Demo (proxy to Orchestrator)
- `* /api/demo/*` - Demo artifact rendering/download

## Directory Structure

```
src/brain_researcher/services/agent/
├── agents/           # LangGraph agents (neuro_agent, neuro_agent_llm)
├── ui_api.py         # Unified UI API Blueprint (/api/*)
├── agent_auth.py     # JWT authentication
├── agent_core.py     # Core chat/act functions
├── thread_store.py   # Redis-backed thread persistence
├── job_service.py    # JobStore integration
├── streaming.py      # SSE streaming utilities
├── web_service.py    # Flask app factory
├── tools/            # Tool wrappers (deprecated - use src/brain_researcher/services/tools/)
└── examples/         # Usage examples
```

## Quick Start

### 1. Start the Service

```bash
# From repository root
br serve agent  # Starts on port 8000

# Or run the WSGI app directly
PORT=8000 gunicorn -w 1 -b 0.0.0.0:8000 "brain_researcher.services.agent.web_service:app"
```

#### Optional legacy ASGI shim (/ws)
If you explicitly need the legacy Agent `/ws` compatibility shim, keep the
HTTP surface the same and start the ASGI wrapper directly:
```bash
uvicorn brain_researcher.services.agent.asgi:app --host 0.0.0.0 --port 8000
```
This serves the existing Flask routes and exposes `/ws` (bridge to `/api/analyses/{id}/events`).

### 2. Environment Variables

```bash
# Required for JWT auth (or set DISABLE_AUTH_FOR_DEV=1 for local dev)
JWT_SECRET_KEY=your-secret-key

# Optional: Redis for persistence (defaults to fakeredis in-memory)
REDIS_URL=redis://localhost:6379/0

# Optional: Dataset catalog path
BRAIN_RESEARCHER_DATASET_CATALOG=/path/to/catalog.jsonl
```

### 3. Run Tests

```bash
# Agent UI API tests
pytest tests/unit/agent/test_ui_api.py -v

# All agent tests
pytest tests/unit/agent/ -v

# Run specific test categories
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests
```

### Dependency Health Checks

The agent uses tools from `src/brain_researcher/services/tools/`. Check missing dependencies:

```bash
python -c "from brain_researcher.services.tools.dependency_inspector import collect_dependency_status; from pprint import pprint; pprint([s for s in collect_dependency_status() if not s.present])"
```

## API Usage Examples

### Chat Request

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Analyze motor cortex activation"}]}'
```

### Dataset Search

```bash
curl -X POST http://localhost:8000/api/datasets/search \
  -H "Content-Type: application/json" \
  -d '{"query": "fMRI motor task", "modalities": ["fMRI"]}'
```

### File Upload

```bash
curl -X POST http://localhost:8000/api/files/upload \
  -F "file=@brain_scan.nii.gz"
```

### Tool Execution

```bash
curl -X POST http://localhost:8000/api/tools/run \
  -H "Content-Type: application/json" \
  -d '{"tool": "glm_analysis", "params": {"dataset_id": "ds000001"}}'
```

## Python SDK Usage

```python
from brain_researcher.services.agent.agents.neuro_agent_llm import NeuroAgentLLM

# Initialize agent
agent = NeuroAgentLLM()

# Run analysis with natural language
result = agent.run("Analyze motor task activation in dataset ds000001")
print(result['content'])
```

### Complex Workflows

```python
# Multi-step analysis
query = """
1. Run GLM analysis on dataset ds000001
2. Map peak activations to cognitive concepts
3. Find related literature for those concepts
"""

result = agent.run(query)

# The agent will:
# - Understand the multi-step request
# - Select appropriate tools (glm_analysis, coordinate_to_concept, literature_search)
# - Execute them in sequence
# - Synthesize the results
```

## Available Tools

### fMRI Analysis Tools
- **glm_analysis**: Run GLM analysis on fMRI datasets
- **encoding_model**: Build encoding models for brain activity prediction
- **contrast_analysis**: Analyze contrast maps and identify clusters
- **brain_similarity**: Compare activation patterns between datasets

### BR-KG Tools
- **find_related_concepts**: Find concepts related to a given concept
- **coordinate_to_concept**: Map MNI coordinates to cognitive concepts
- **concept_literature_search**: Search literature by concepts
- **graph_query**: Execute general graph queries
- **task_to_concept_mapping**: Map task names to standardized concepts

## Key Components

### Thread Storage (`thread_store.py`)
- Redis-backed with fakeredis fallback for development
- Per-user thread isolation with ownership checks
- Message persistence with TTL (default 30 days)

### Job Service (`job_service.py`)
- Integrates with async JobStore from Orchestrator
- Provides sync wrappers for Flask endpoints
- Tracks run status, logs, and progress

### Authentication (`agent_auth.py`)
- JWT verification with PyJWT
- Supports `JWT_SECRET_KEY`, `NEXTAUTH_SECRET`, `SECRET_KEY` env vars
- Dev bypass with `DISABLE_AUTH_FOR_DEV=1`

### Streaming (`streaming.py`)
- SSE event formatting
- LangChain `.stream()` integration for token-by-token responses
- Thread message streaming utilities

## Testing

```bash
# UI API tests (30+ tests)
pytest tests/unit/agent/test_ui_api.py -v

# All agent tests
pytest tests/unit/agent/ -v

# With coverage
pytest tests/unit/agent/ --cov=brain_researcher.services.agent
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 401 Unauthorized | Set `DISABLE_AUTH_FOR_DEV=1` or configure `JWT_SECRET_KEY` |
| Empty dataset search | Check `BRAIN_RESEARCHER_DATASET_CATALOG` path |
| Redis connection error | Uses fakeredis fallback - safe for development |
| Tool not found | Run `GET /api/tools` to list available tools |

### Debug Mode

```bash
# Enable debug logging
export BR_DEBUG=1

# Or in Python
import logging
logging.getLogger("brain_researcher.services.agent").setLevel(logging.DEBUG)
```

## Contributing

1. Follow existing patterns in `ui_api.py`
2. Add tests to `tests/unit/agent/test_ui_api.py`
3. Ensure lint passes: `ruff check src/brain_researcher/services/agent/`
4. Run full test suite before submitting

## License

Same as the parent brain_researcher project.
