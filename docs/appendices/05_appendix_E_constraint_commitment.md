# Appendix E. Constraint and Commitment Card

Records the active validity boundary before execution and the gate decision that lets the episode proceed.

## E.1 Card identity

| Field | Value |
|-------|-------|
| Card ID | E-<episode-id>-001 |
| Episode ID | |
| Date | |
| Prepared by | |
| Review status | draft / reviewed / final |

## E.2 Active constraint set

| Constraint ID | Description | Layer | Severity | Source |
|---------------|-------------|-------|----------|--------|
| | | statistical / measurement / construct / generalization / claim | BLOCK / WARN / INFO | rule registry / policy / dataset card / reviewer |

## E.3 Hard checks

| Check ID | Description | Inputs | Verdict | Evidence |
|----------|-------------|--------|---------|----------|
| HC-001 | | review_context.* fields | pass / block | |

## E.4 Soft checks

| Check ID | Description | Inputs | Verdict | Required sensitivity / caveat |
|----------|-------------|--------|---------|--------------------------------|
| SC-001 | | | pass / warn | |

## E.5 Rule provenance

| Rule ID | Origin document | Version | Lifecycle status | Notes |
|---------|-----------------|---------|------------------|-------|
| | S4 rule registry / project policy / dataset card | | implemented / deterministic candidate / schema-dependent / NLP candidate | |

## E.6 Verdict summary

| Field | Value |
|-------|-------|
| Hard checks | n_pass / n_block |
| Soft checks | n_pass / n_warn |
| Overall verdict | pass / warn-with-caveats / block |
| Verdict rationale | |

## E.7 Soft-constraint caveats

| Caveat ID | Constraint | Caveat language to attach to downstream claims | Trigger |
|-----------|------------|-------------------------------------------------|---------|
| | | | warn fired |

## E.8 Required sensitivity analyses

| Analysis ID | Triggered by | Minimum protocol | Owner | Due before |
|-------------|--------------|------------------|-------|-----------|
| SA-001 | controversial_choice / prior_conflict / extreme_effect | (cite template) | | claim acceptance |

## E.9 Commitment-gate decision

| Field | Value |
|-------|-------|
| Gate authority | reviewer / system / operator |
| Gate decision | proceed / revise / abort |
| Decision timestamp | |
| Approval phrase (if required) | |
| Commitment scope | this run only / episode-wide / benchmark slice |

## E.10 Benchmark pass-through

| Field | Value |
|-------|-------|
| Benchmark mode? | yes / no |
| Benchmark ID | |
| Task slice | |
| Scoring contract referenced | |
| Stop-condition referenced | |

## E.11 Cross-references

| Pointer | Target |
|---------|--------|
| Episode card | Appendix A card ID |
| Evidence bundle | Appendix B card ID |
| Tool ledger | Appendix D card ID |
| Run bundle | Appendix F card ID |
| Review card | Appendix G card ID |
| Evaluation card (if benchmark) | Appendix J card ID |
