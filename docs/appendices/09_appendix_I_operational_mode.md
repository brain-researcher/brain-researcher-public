# Appendix I. Operational-Mode Card

Records how the episode was controlled: gates, budgets, action vocabulary, validation ladder, supervisor/critic decisions, and escalations.

## I.1 Card identity

| Field | Value |
|-------|-------|
| Card ID | I-<episode-id>-001 |
| Episode ID | |
| Operational mode | autonomous / interactive / supervised / bounded campaign |
| Date | |
| Prepared by | |
| Review status | draft / reviewed / final |

## I.2 Interactive gates

| Gate ID | Trigger | Authority | Decision | Timestamp | Notes |
|---------|---------|-----------|----------|-----------|-------|
| G-001 | preflight / pre-run / pre-commit / pre-claim | user / reviewer / system | proceed / hold / abort | | |

## I.3 Bounded instruction file

| Field | Value |
|-------|-------|
| Instruction file path | |
| Instruction file hash | |
| Allowed action set | |
| Disallowed action set | |
| Effective at episode open? | yes / no |

## I.4 Action vocabulary

| Action | Allowed? | Authority required | Notes |
|--------|----------|--------------------|-------|
| `tool_search` | yes / no | none / supervisor | |
| `get_execution_recipe` | yes / no | | |
| `pipeline_execute` | yes / no | approval phrase | |
| `tool_execute` | yes / no | allowlist | |
| `memory_write` | yes / no | | |
| BR-KG promotion | yes / no | reviewer | |

## I.5 Budget

| Resource | Limit | Consumed | Remaining | Hard cap? |
|----------|------:|---------:|----------:|-----------|
| Wall-clock minutes | | | | yes / no |
| Tool calls | | | | |
| LLM tokens (in / out) | | | | |
| Run-launches | | | | |
| Cluster CPU-hours | | | | |
| Cluster GPU-hours | | | | |

## I.6 Stopping criteria

| Criterion | Threshold | Triggered? | Notes |
|-----------|-----------|------------|-------|
| Budget exhaustion | | yes / no | |
| Verdict reached | accept / block | yes / no | |
| Operator stop | | yes / no | |
| Error class | fatal / persistent | yes / no | |

## I.7 Validation ladder

| Layer | Validator | Inputs | Verdict | Notes |
|-------|-----------|--------|---------|-------|
| L1 schema | schema validator | tool args / outputs | pass / fail | |
| L2 deterministic checks | rule registry | review_context | pass / warn / block | |
| L3 robustness | sensitivity templates | artifacts | pass / fail / inconclusive | |
| L4 supervisor | reviewer / Harbor | bundle | pass / fail | |

## I.8 Supervisor decisions

| Decision ID | Authority | Stage | Decision | Rationale |
|-------------|-----------|-------|----------|-----------|
| SUP-001 | human / system | plan / run / claim | approve / revise / block | |

## I.9 Critic decisions

| Decision ID | Critic identity | Stage | Output | Effect |
|-------------|------------------|-------|--------|--------|
| CRIT-001 | code reviewer / scientific reviewer / judgment critic | review | accept / revise / block | |

## I.10 Harbor verifier

| Field | Value |
|-------|-------|
| Verifier invoked? | yes / no |
| Verifier version | |
| Inputs | |
| Output verdict | pass / fail |
| Output artifact | |

## I.11 Reward and partial credit

| Field | Value |
|-------|-------|
| Reward function ID | |
| Reward score | |
| Components | (correctness, completeness, novelty, etc.) |
| Partial-credit allowance | yes / no |
| Tie-breaker | |

## I.12 Escalations

| Escalation ID | Trigger | Escalated to | Outcome | Timestamp |
|---------------|---------|--------------|---------|-----------|
| ESC-001 | budget overrun / blocking error / unresolved review | oncall / reviewer / user | | |

## I.13 Mode summary

| Field | Value |
|-------|-------|
| Mode-consistent throughout episode? | yes / no |
| Mode transitions | (list with timestamps) |
| Final mode at close | |

## I.14 Cross-references

| Pointer | Target |
|---------|--------|
| Episode card | Appendix A card ID |
| Constraint card | Appendix E card ID |
| Review card | Appendix G card ID |
| Evaluation card (if benchmark) | Appendix J card ID |
