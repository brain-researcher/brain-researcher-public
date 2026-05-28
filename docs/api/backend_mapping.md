# Backend Mapping for Canonical Tools

- Canonical (semantic) tools live in families like `fmri.preproc`, `fmri.glm`, `ai.coding`, `neurokg.client`, etc.
- Backend providers (containers, neurodesk, niwrap, mcp) are treated as internal implementations and are not exposed to chat.
- Each canonical leaf may specify a backend block in its ToolSpec / capabilities:

```yaml
backend:
  kind: container|python|cli
  provider: container.bidsapp_fmriprep  # or neurodesk, niwrap, gemini_cli, etc.
```

- Router/Planner should surface only canonical tools; backend families (container.*, neurodesk.*, niwrap.*, mcp.*) remain internal.
- Validation rule: every backend tool is either marked internal or referenced by at least one canonical leaf backend.
