# Tool Metadata Schema

This document defines the minimal metadata fields every ToolSpec must carry. The
same schema is used across entrypoints (chat, pipeline builder, CLI, MCP
bridge), so tools can be filtered and ranked consistently.

## Required fields per tool

- `domain` (string, one of):
  - fMRI: `fmri`, `fmri.preproc`, `fmri.glm`, `fmri.connectivity`, `fmri.qc`, `fmri.viz`
  - dMRI: `dmri`, `dmri.preproc`, `dmri.modeling`, `dmri.tractography`, `dmri.connectome`, `dmri.qc`
  - Surface/sMRI: `smri`, `surface`, `surface.recon`, `surface.parcellation`, `surface.workbench`, `surface.viz`, `surface.registration`
  - Other: `eeg`, `ieeg`, `pet`, `clinical`, `kg`, `datasets`, `jobs`, `coding`, `fs`, `net`, `viz`, `meta`, `realtime`, `advanced`, `specialized`, `container`, `mcp`, `niwrap`.

- `function` (string, one of): `preproc`, `glm`, `connectivity`, `qc`,
  `decoding`, `meta`, `visualization`, `ingest`, `search`, `infer`, `admin`,
  `backend`, `routing`, `conversion`, `report`, `analysis`, `simulation`.

- `runtime_kind` (string, one of): `python`, `container`, `mcp`, `llm`.

- `risk` (string, one of): `safe`, `dangerous`, `external_net`, `high_cost`.

- `exposure` (string, one of): `chat`, `pipeline`, `cli`, `advanced`, `internal`.
  Multiple risk aspects should be reflected in `tags` (e.g., `dangerous`,
  `external_net`). If none apply, use `safe`.

- `tags` (list of strings): Should include the above fields and any additional
  flags, e.g., `backend`, `internal`, `chat_safe`, `advanced`, `external_net`,
  `high_cost`.

## Defaults / conventions

- If `risk` missing → treat as `safe` (filled by spec merge).
- Backends (container./niwrap./mcp./neurodesk) must include `backend` in tags
  and typically `internal: true`; domain = `container|mcp|niwrap`, function =
  `backend`.
- Chat-exposed tools should include `chat_safe` tag; dangerous tools must not
  be chat-exposed.

## Validation

`scripts/tools/validate_metadata.py` checks:
- All tools have domain/function/runtime_kind/risk/tags.
- Values are within the allowed vocab.
- Warns on missing tags or empty tag lists.

## Router / CLI usage

- Chat/Tool Router: rank/filter by domain/function; deprioritize `dangerous` or
  `high_cost` unless explicitly allowed; hide `internal` for chat.
- CLI: allow `--domain`, `--function`, `--risk` filters once metadata is
  populated.
