# Appendix G. Review Card

Records the scientific review outcome over a run bundle. Every revise / block decision must cite at least one rule from the S4 registry.

## G.1 Card identity

| Field | Value |
|-------|-------|
| Card ID | G-<episode-id>-<run-id>-001 |
| Episode ID | |
| Run ID | |
| Reviewer(s) | system / human / hybrid |
| Date | |
| Review status | draft / reviewed / final |

## G.2 Review inputs

| Input | Pointer |
|-------|---------|
| Run bundle | Appendix F card ID |
| Constraint card | Appendix E card ID |
| Evidence bundle | Appendix B card ID |
| Dataset card | Appendix C card ID |
| Tool ledger | Appendix D card ID |

## G.3 Deterministic checks

| Check ID | Rule ID | Layer | Verdict | Evidence pointer |
|----------|---------|-------|---------|------------------|
| DC-001 | | statistical / measurement / construct / generalization / claim | pass / warn / block | trace event / artifact path |

## G.4 BLOCK findings

| Finding ID | Rule ID | Reason tags | Description | Required revision |
|------------|---------|-------------|-------------|-------------------|
| B-001 | | leakage / circularity / confound / null_mismatch / claim_inflation | | |

## G.5 WARN findings

| Finding ID | Rule ID | Reason tags | Description | Required sensitivity analysis / caveat |
|------------|---------|-------------|-------------|----------------------------------------|
| W-001 | | | | |

## G.6 Soft warnings (advisory)

| Finding ID | Description | Caveat suggested | Action |
|------------|-------------|------------------|--------|
| S-001 | | | logged only / discussion required |

## G.7 Robustness and sensitivity checks

| Check ID | Triggered by | Protocol | Result | Verdict |
|----------|--------------|----------|--------|---------|
| R-001 | controversial choice / prior conflict / extreme effect | (template ID from S4 §8) | | pass / fail / inconclusive |

## G.8 Claim families

| Claim ID | Claim text | Family | Polarity | Eligibility |
|----------|------------|--------|----------|-------------|
| C-001 | | statistical / measurement / construct / generalization / mechanism / clinical | positive / null / mixed | eligible / blocked / caveated |

## G.9 Verdict

| Field | Value |
|-------|-------|
| Overall verdict | accept / revise / block |
| Decision rationale | |
| Verdict authority | system / reviewer |
| Verdict timestamp | |

## G.10 Caveat language

| Caveat ID | Claim ID | Caveat text to attach | Source rule |
|-----------|----------|------------------------|-------------|
| CV-001 | | | |

## G.11 Revision routing

| Field | Value |
|-------|-------|
| Routed to | planner / executor / data engineer / human |
| Revision scope | re-run / re-plan / re-collect / re-claim |
| Revision instructions | |
| Revision target run ID (when produced) | |

## G.12 Claim eligibility for memory and BR-KG

| Claim ID | Memory writeback eligible? | BR-KG promotion eligible? | Gate decision |
|----------|----------------------------|----------------------------|---------------|
| | yes / no | yes / no | accept / hold / reject |

## G.13 Artifact-completeness ratio

| Field | Value |
|-------|-------|
| Produced / expected | from Appendix F |
| Acceptable threshold | |
| Verdict | pass / fail |

## G.14 Cross-references

| Pointer | Target |
|---------|--------|
| Run bundle | Appendix F card ID |
| Constraint card | Appendix E card ID |
| Memory writebacks (if any) | Appendix H card IDs |
| Evaluation card (if benchmark) | Appendix J card ID |
