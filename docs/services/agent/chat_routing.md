# Coding / Neuro / Chat Modes – Unified Routing (Agent‑First)

## Current Status

- **Pipeline / Viz**: `/api/chat` already has a fast-path; `preview/skip_summary` directly returns NiWrap results without relying on LLM; pipelines like T1→MNI have been synchronized to Neo4j.
- **Coding**: ChatOrchestrator coding branch has been changed to default to `execute_tool("code_agent")` (when either: `tools.mode="coding"` with `repo_root`, or `force_code_agent`); `explain_only` goes through LLM, falls back to LLM on failure. New regression test `tests/unit/agent/test_chat_orchestrator_coding.py` covers agent/LLM branches.
- **Default Model**: Recommended `DEFAULT_LLM_MODEL=gemini-2.5-flash`, `CODE_AGENT_MODEL_HINT=gemini-2.5-flash`, `USE_GEMINI_CLI=false`.

## TODO (Priority)
1. **Frontend Mode Switch** (ChatWorkspace)
   - "Chat / Coding / Neuro" mode switching.
2. **ctx Wrapper (use-chat)**
   - Coding mode automatically includes:
     ```ts
     tools = { mode: "coding" }
     ctx = {
       repo_root: currentProjectRoot,
       file_paths: selectedFiles,   // Currently edited/selected files
       apply: false,
       dry_run: true,
       preview: true,
     }
     ```
   - "Explain only" toggle → `ctx.explain_only = true` (forces coding_llm).
3. **Neuro Presets**
   - Preprocess T1→MNI: `use_planning_engine=true`, `pipeline_preview=true`, `preview=true`, `t1w_image`, `work_dir`, `output_dir`.
   - Visualize stat map: `stat_map`, `display_mode`, `preview=true`, `use_planning_engine=true`.
4. **Regression Test Matrix (CI Optional)**
   - `test_chat_orchestrator_coding.py`
   - `test_chat_pipeline_fastpath.py` / `test_chat_viz_fastpath.py`
   - `test_pipeline_first.py`, `test_chat_orchestrator_pipeline.py`
   - `tests/eval/test_brain_tool_eval.py`
   - (Optional) `RUN_NIWRAP_INTEGRATION=1 pytest tests/unit/tools/test_executor.py -k niwrap`

## Real Usage Examples

### Coding + repo-edit (Frontend should automatically construct ctx)
```bash
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
        "messages":[{"role":"user","content":"Add a Make target named demo-echo that echoes hello"}],
        "tools":{"mode":"coding"},
        "ctx":{
          "repo_root": "<repo>",
          "file_paths": ["Makefile"],
          "apply": false,
          "dry_run": true,
          "preview": true
        }
      }'
```

### T1→MNI Preview
```bash
curl -s -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
        "messages":[{"role":"user","content":"preprocess my T1 to MNI"}],
        "ctx":{
          "use_planning_engine": true,
          "pipeline_preview": true,
          "preview": true,
          "t1w_image": "/app/data/openneuro/ds000117/sub-01/ses-mri/anat/sub-01_ses-mri_acq-mprage_T1w.nii.gz",
          "work_dir": "/tmp/br_work",
          "output_dir": "/tmp/br_out"
        }
      }'
```

## Running Recommendations (Agent)

```bash
FLASK_APP=brain_researcher.services.agent.web_service \
SMOKE_TEST_MODE=0 DISABLE_AUTH_FOR_DEV=1 \
DEFAULT_LLM_MODEL=gemini-2.5-flash CODE_AGENT_MODEL_HINT=gemini-2.5-flash \
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=password \
flask run -p 8000 --host 0.0.0.0
```
