# Coding Agent Quickstart (dev / lab use)

This is the shortest path to run the real coding agent end-to-end and know what is expected.

## 1) Start the services

```bash
# Agent (non-smoke)
FLASK_APP=brain_researcher.services.agent.web_service \
SMOKE_TEST_MODE=0 \
DISABLE_AUTH_FOR_DEV=1 \
USE_GEMINI_CLI=false \
DEFAULT_LLM_MODEL=gemini-2.5-flash \
CODE_AGENT_MODEL_HINT=gemini-2.5-flash \
flask run -p 8000

# Web UI
cd apps/web-ui
corepack pnpm install --ignore-scripts
corepack pnpm dev  # http://localhost:3000
```

## 2) Three workflows to try

1. **T1 → MNI (pipeline preview)**  
   In Chat, mode = “neuro”, run: `preprocess my T1 to MNI` with your T1 path, `use_planning_engine=true`, `pipeline_preview=true`.

2. **ICA + FIX preview**  
   Similar flow (neuro mode), trigger ICA/FIX pipeline to see NiWrap preview commands.

3. **Coding agent (the important one)**  
   - Switch to **coding** tab  
   - Repo root: `${BR_REPO_ROOT}`  
   - Files: `brain_researcher/services/agent/chat_orchestrator.py`  
   - Prompt: `Add a concise docstring to _delegate_to_code_orchestrator describing the coding flow.`  
   - Expect streaming events (plan/patch/test/result) under the assistant message; metadata.type will be `coding_tool`.

## 3) Safety expectations (what is intentionally blocked)

- `python -c '...'` or `python3   -c '...'` → rejected.  
- `pytest --rootdir=/tmp` / `pytest --rootdir /tmp` → rejected (escape).  
- `pytest --junitxml=~/out.xml` → rejected.  
- `pytest --rootdir=<repo_root> tests/` → allowed to run (may pass/fail normally).  
Default coding settings: `apply=false`, `dry_run=true`, `preview=true`; “Explain only” forces LLM-only path.

## 4) Quick curl checks

Non-UI sanity for coding stream:

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{
    "messages":[{"role":"user","content":"Add a concise docstring to _delegate_to_code_orchestrator describing the coding flow."}],
    "thread_id":"dev",
    "tools":{"mode":"coding"},
    "ctx":{
      "tools":{"mode":"coding"},
      "repo_root":"${BR_REPO_ROOT}",
      "file_paths":["brain_researcher/services/agent/chat_orchestrator.py"]
    }
  }'
```
Expect SSE events; final `runCard.execution.tool_mode` should be `coding` with `code_agent` selected.

## 5) Tests to rerun quickly

```bash
pytest tests/unit/agent/test_code_tools.py \
       tests/unit/agent/test_chat_orchestrator_coding.py \
       tests/unit/agent/test_chat_coding_mode.py \
       tests/unit/agent/test_ui_api_coding_stream.py -v
```

If these pass and the curl above streams, the coding path is good to go for internal checks.
