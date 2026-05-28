# Codegen Loop (Track D)

- The coding agent is a **single tool** (`code_agent`) hanging off the existing Chat Orchestrator / ToolRouter / ToolRegistry.
- The tool internally runs a LangGraph-style subgraph (generate → execute → repair) but never performs top-level tool selection or chat orchestration.
- Model routing relies on the shared `LLMRouter`; policy hints (`task_type=code`, `strict_json`, `ctx_tokens`) steer Gemini/GPT choice.
- Safety: the tool returns structured results with `requires_confirmation` when patches are present; callers should ask before applying.
- Feature flags: `BR_CODE_AGENT_ENABLED` (default true), `BR_CODE_AGENT_MAX_ITERS` (default 3).

## Codegen Constitution

- The codegen prompt now injects a repo-local constitution from `configs/codegen/constitution.yaml`.
- Loader/formatter lives in `src/brain_researcher/services/agent/codegen/constitution.py`.
- The constitution is adapted for Brain Researcher and emphasizes:
  - fail loud rather than silently degrade
  - explicit failure-mode reasoning
  - forward and backward validation
  - domain-aware testing for neuroimaging workflows
  - prioritizing failed cases and benchmark-driven regression prevention

## Execution Gate

- Local codegen execution now uses a constitution-aware verification gate from `src/brain_researcher/services/agent/codegen/execution_gate.py`.
- If no allowed `test_command` is provided, the loop requires concrete Python files to verify.
- When the model touches files, verification must target those touched Python files rather than unrelated context.
- If there is no verification evidence, execution fails explicitly instead of silently succeeding.

## Benchmark Policy

- Benchmark scoring policy now lives in `configs/codegen/benchmark_policy.yaml`.
- Scoring helpers live in `src/brain_researcher/services/agent/codegen/benchmark_scoring.py`.
- The scorer weights:
  - failure detection
  - verification evidence
  - tests and negative tests
  - backward compatibility checks
  - domain validation
  - priority on previously failed cases
- Silent failure and claiming success without evidence are explicit score penalties.
