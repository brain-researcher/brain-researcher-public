# Appendix J. Evaluation Card

Records benchmark and campaign configuration, primary/secondary metrics, ablations, and with-BR / without-BR protocols. One card per campaign or benchmark slice.

## J.1 Card identity

| Field | Value |
|-------|-------|
| Card ID | J-<campaign-id>-001 |
| Campaign / benchmark ID | |
| Episodes covered | Appendix A card IDs |
| Date | |
| Prepared by | |
| Review status | draft / reviewed / final |

## J.2 Benchmark suite list

| Suite ID | Name | Domain | Tasks | Source / version |
|----------|------|--------|-------|------------------|
| BS-001 | | meta-bench / neuroimaging task / KG audit | | |

## J.3 Task manifests

| Task ID | Suite | Inputs | Expected outputs | Scoring contract ID |
|---------|-------|--------|------------------|---------------------|
| T-001 | | | | SC-001 |

## J.4 Scoring contracts

| Contract ID | Metric(s) | Aggregation | Thresholds | Tie-breaker |
|-------------|-----------|-------------|------------|-------------|
| SC-001 | | mean / median / pass-rate | accept / warn / block | |

## J.5 Model list

| Model ID | Provider | Version | Prompt-template version | Role |
|----------|----------|---------|--------------------------|------|
| M-001 | | | | system-under-test / baseline / ablation |

## J.6 With-BR / Without-BR protocol

| Arm | BR enabled? | BR-KG access | Memory access | Tool registry access | MCP gates |
|-----|-------------|--------------|---------------|----------------------|-----------|
| with-BR | yes | full | full | full | as configured |
| without-BR | no | none | none | none | none |
| ablation-A | partial | | | | |

## J.7 Memory partition policy

| Field | Value |
|-------|-------|
| Partition strategy | per-task / per-model / shared / isolated |
| Carryover between tasks | allowed / blocked |
| Carryover between models | allowed / blocked |
| Snapshot reset cadence | per task / per campaign / never |

## J.8 Collaborator case table

| Case ID | Source collaborator | Scientific question | Dataset | Expected output | Acceptance criterion |
|---------|---------------------|---------------------|---------|------------------|----------------------|
| CC-001 | | | | | |

## J.9 Bounded campaign contract

| Field | Value |
|-------|-------|
| Total budget | wall-clock / tokens / runs |
| Per-episode budget | |
| Allowed action set | |
| Disallowed action set | |
| Escalation policy | |
| Stop conditions | |

## J.10 Primary metrics

| Metric | Definition | Direction (↑ / ↓ is better) | Threshold | Owner |
|--------|------------|------------------------------|-----------|-------|
| | | | | |

## J.11 Secondary metrics

| Metric | Definition | Direction | Notes |
|--------|------------|-----------|-------|
| | | | |

## J.12 Ablation protocols

| Ablation ID | Component removed / replaced | Hypothesis | Expected effect | Measurement |
|-------------|------------------------------|------------|------------------|-------------|
| AB-001 | BR-KG / memory / tool registry / review layer | | | |

## J.13 Results ledger

| Result ID | Arm | Task ID | Metric | Value | Verdict |
|-----------|-----|---------|--------|------:|---------|
| R-001 | with-BR / without-BR / ablation-A | | | | pass / fail |

## J.14 Episode-to-campaign mapping

| Episode ID (Appendix A) | Arm | Task ID | Result ID | Notes |
|-------------------------|-----|---------|-----------|-------|
| | | | | |

## J.15 Caveats and limitations

- Population coverage:
- Modality coverage:
- Known leakage risks across arms:
- Generalization claims permitted:
- Generalization claims explicitly excluded:

## J.16 Cross-references

| Pointer | Target |
|---------|--------|
| Episode cards | Appendix A card IDs |
| Constraint cards | Appendix E card IDs |
| Run bundles | Appendix F card IDs |
| Review cards | Appendix G card IDs |
| Operational-mode cards | Appendix I card IDs |
