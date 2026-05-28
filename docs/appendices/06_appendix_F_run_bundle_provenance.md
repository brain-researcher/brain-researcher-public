# Appendix F. Run Bundle and Provenance Card

Records what actually happened during execution and produces the auditable trail needed by Appendix G review.

## F.1 Card identity

| Field | Value |
|-------|-------|
| Card ID | F-<episode-id>-<run-id> |
| Episode ID | |
| Run ID | |
| Date | |
| Prepared by | |
| Review status | draft / reviewed / final |

## F.2 Execution envelope

| Field | Value |
|-------|-------|
| Target runtime | python / neurodesk / container / slurm / mcp admin exec |
| Cluster profile (if HPC) | |
| Backend image / module | |
| Software versions | |
| Container digest | |
| Slurm job ID(s) | |
| Recipe hash | |
| Random seed | |

## F.3 Event trace

| Field | Value |
|-------|-------|
| Trace path | trace.jsonl / tool_trace.jsonl |
| Event count | |
| First event timestamp | |
| Last event timestamp | |
| Trace integrity | unbroken / gaps |

## F.4 Trajectory document

| Field | Value |
|-------|-------|
| Trajectory path | trajectory.json |
| Step count | |
| Branch points | |
| Backtracks / retries | |

## F.5 Observation record

| Field | Value |
|-------|-------|
| Observation path | observation.json |
| Metrics captured | |
| Key results summary | |

## F.6 Analysis bundle

| Field | Value |
|-------|-------|
| Analysis bundle path | analysis_bundle.json |
| Contrasts / models referenced | |
| Linked dataset (Appendix C) | |
| Linked tool (Appendix D) | |

## F.7 Run card

| Field | Value |
|-------|-------|
| Status | running / succeeded / failed / cancelled |
| Start time | |
| End time | |
| Wall-clock duration | |
| Exit code | |
| Failure category (if any) | |

## F.8 Expected vs produced artifacts

| Artifact | Expected path | Produced? | Checksum | Size | Notes |
|----------|---------------|-----------|----------|------|-------|
| | | yes / no | sha256 | bytes | |

| Field | Value |
|-------|-------|
| Artifact-completeness ratio | n_produced / n_expected |
| Missing artifacts | |

## F.9 Logs

| Log | Path | Notes |
|-----|------|-------|
| stdout | | |
| stderr | | |
| Slurm out | | |
| Slurm err | | |
| Tool internal log | | |

## F.10 Provenance fields

| Field | Value |
|-------|-------|
| Provenance path | provenance.json |
| Inputs hash | |
| Recipe hash | |
| Container digest | |
| Software versions | |
| Module identifiers | |
| Reproducibility flag (BIDS validator, stats models, seed, etc.) | |

## F.11 Failures and recoveries

| Failure ID | Step | Error category | Error message | Retryable? | Recovery action | Outcome |
|------------|------|----------------|---------------|------------|------------------|---------|
| | | timeout / oom / dependency / data-missing / logic | | yes / no | | |

## F.12 Metrics and scorecards

| Metric | Value | Source | Threshold | Pass/fail |
|--------|------:|--------|-----------|-----------|
| | | | | |

| Field | Value |
|-------|-------|
| Run scorecard | computed / not computed |
| Comparison baseline run | run ID or `none` |
| Comparison verdict | improved / regressed / unchanged |

## F.13 Cross-references

| Pointer | Target |
|---------|--------|
| Episode card | Appendix A card ID |
| Evidence bundle | Appendix B card ID |
| Dataset card | Appendix C card ID |
| Tool ledger | Appendix D card ID |
| Constraint card | Appendix E card ID |
| Review card | Appendix G card ID |
| Memory writebacks | Appendix H card IDs |
