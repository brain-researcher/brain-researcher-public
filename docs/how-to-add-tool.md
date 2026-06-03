# How to add a new MCP tool

Workflow for adding an analysis or service tool to Brain Researcher's MCP surface, including the contract layer that governs the OSS-published subset.

## 1. Implement the tool

Place the implementation under `src/brain_researcher/services/tools/` (or the appropriate service module). Decorate with `@mcp.tool()`:

```python
@mcp.tool()
def my_new_tool(arg1: str, arg2: int = 10) -> dict[str, Any]:
    """One-line description; appears in tool_search and contracts/tools/."""
    ...
    return {"ok": True, "result": ...}
```

The function signature defines the input schema; the docstring's first line becomes the contract's `description`.

## 2. Tag with tier metadata

Add an entry to `_MCP_SURFACE_METADATA_BY_NAME` in `src/brain_researcher/services/mcp/server.py`:

```python
"my_new_tool": {
    "surface_tier": "default",       # ops | default | advanced
    "capability_family": "planning", # see existing families
},
```

`surface_tier` controls agent-facing complexity; **stability** is a separate axis tracked at the contract layer (see step 4).

## 3. Add catalog + test wiring

1. Add to `configs/tools_catalog.json` (validated by `configs/schemas/tools_catalog.schema.json` in CI).
2. Add the tool name to `configs/catalog/exposed_tools.yaml`.
3. Add an example invocation in `configs/catalog/chat_tool_schemas.yaml`.
4. Add a unit test under `tests/unit/tools/`.
5. Document public MCP-facing behavior in `docs/mcp.md` or the relevant `contracts/` entry.

## 4. (Optional) Add to the OSS stable tier

Only if the tool is meant to be part of the API-stability promise:

1. Bump `contracts/VERSION` to today's date (`date +%Y-%m-%d`).
2. Add the tool name to `STABLE_TIER` in `scripts/oss/extract_tool_contracts.py`.
3. Run `python scripts/oss/extract_tool_contracts.py` — emits `contracts/tools/<name>.json`.
4. Verify the new contract is reproducible: `python scripts/oss/extract_tool_contracts.py --check` (CI also runs this).
5. Update `docs/contract-tiers.md` so users see what stability means for the tool.

## 5. (Optional) Add a deprecated alias

If renaming an existing tool, add the old name to `DEPRECATED_ALIASES` in `scripts/oss/extract_tool_contracts.py`:

```python
DEPRECATED_ALIASES = {
    "old_name": "my_new_tool",
    ...
}
```

The aggregate `docs/mcp_tools.schema.json` keeps both entries; `server_info.deprecated_tools` lists the alias and tells callers what to migrate to. Plan to remove the alias after one release cycle.

## 6. Run boundary checks

```bash
python scripts/analyze_code_import_graph.py \
  --src-root src/brain_researcher \
  --markdown-out /tmp/codegraph_local.md \
  --boundary core:services --boundary llmcore:services
```

PRs must not introduce new cross-boundary violations beyond the ratchet in
`tests/architecture/test_import_boundaries.py` and
`tests/architecture/services_layer_baseline.txt`.

## 7. Verify before pushing

```bash
ruff check src/ tests/
mypy src/brain_researcher --ignore-missing-imports
pytest tests/unit/tools/test_my_new_tool.py -x
pytest tests/contracts -x                               # if stable-tier
python scripts/oss/extract_tool_contracts.py --check    # if stable-tier
```
