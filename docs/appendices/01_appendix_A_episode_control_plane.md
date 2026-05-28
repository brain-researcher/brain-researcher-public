# Appendix A. Episode and Control-Plane Card

Records the fixed identity and configuration of a research episode. This card pins down everything that future replays and audits need.

## A.1 Card identity

| Field | Value |
|-------|-------|
| Card ID | A-<episode-id>-001 |
| Episode ID | |
| Episode mode | autonomous / interactive / supervised / benchmark |
| Scientific question | |
| Date opened | |
| Date closed | |
| Prepared by | |
| Review status | draft / reviewed / final |

## A.2 Snapshots and versions

| Component | Identifier | Hash / digest | Notes |
|-----------|-----------|---------------|-------|
| Model version | | | LLM identity and provider |
| Prompt-template version | | | |
| Registry snapshot | | | BR tool registry |
| BR-KG snapshot | | | |
| MCP server version | | | |
| Repository commit | | | git SHA |
| Configs hash | | | merged effective config |

## A.3 Policy flags (effective at episode open)

| Flag | Value | Source |
|------|-------|--------|
| Network access | true / false | |
| Dangerous tools | true / false | |
| `tool_execute` enabled | true / false | |
| Allowed roots | | |
| Allowed hosts / origins | | |
| Default loop profile | | |
| Approval phrase required | | |

## A.4 MCP operation summary

| Field | Value |
|-------|-------|
| Transport | stdio / sse / streamable-http |
| Run root | |
| Session ID | |
| Loop profile | |
| Total MCP tool calls | |
| Background runs launched | |
| Connector calls (KG / literature / grounding) | |

## A.5 Memory namespace

| Field | Value |
|-------|-------|
| Memory namespace | |
| Write policy | append-only / curated / per-episode |
| Carryover from prior episodes | episode IDs or `none` |
| Memory partitions used | |

## A.6 Checkpoint and recovery events

| Event ID | Timestamp | Kind | Trigger | Outcome | Notes |
|----------|-----------|------|---------|---------|-------|
| | | checkpoint / recovery / cancel / pause | | | |

## A.7 Operator interventions

| Intervention ID | Timestamp | Actor | Action | Reason | Effect on episode |
|-----------------|-----------|-------|--------|--------|-------------------|
| | | user / reviewer / oncall | unblock / override / abort | | |

## A.8 Stopping and closure

| Field | Value |
|-------|-------|
| Stopping criterion fired | budget / verdict / operator / error |
| Final state | completed / aborted / blocked |
| Closing summary | |

## A.9 Cross-references

| Pointer | Target |
|---------|--------|
| Evidence bundle | Appendix B card ID |
| Datasets/resources | Appendix C card IDs |
| Tool ledger | Appendix D card ID |
| Constraints / commitments | Appendix E card ID |
| Run bundles | Appendix F card IDs |
| Review verdicts | Appendix G card IDs |
| Memory writebacks | Appendix H card IDs |
| Operational-mode card | Appendix I card ID |
| Evaluation card (if benchmark) | Appendix J card ID |
