# Appendix H. Memory Card

Records reviewed claims that are written back to durable memory and their relation to prior memory. Only claims that pass Appendix G eligibility may produce rows here.

## H.1 Card identity

| Field | Value |
|-------|-------|
| Card ID | H-<episode-id>-<claim-id> |
| Episode ID | |
| Run ID | |
| Date | |
| Prepared by | |
| Review status | draft / reviewed / final |

## H.2 Claim payload

| Field | Value |
|-------|-------|
| Claim ID | from Appendix G |
| Claim text | |
| Polarity | positive / null / mixed |
| Confidence tier | high / medium / low |
| Review verdict | accept / revise / block |
| Caveats attached | from Appendix G |

## H.3 Condition vector

| Field | Value |
|-------|-------|
| Dataset | |
| Population | |
| Task | |
| Preprocessing | |
| Feature type | |
| Model / method | |
| Metric | |
| Known caveats | |

## H.4 Provenance pointer

| Field | Value |
|-------|-------|
| Run bundle | Appendix F card ID |
| Review card | Appendix G card ID |
| Evidence bundle | Appendix B card ID |
| Constraint card | Appendix E card ID |
| Source artifact paths | |

## H.5 Relation to prior memory

| Relation ID | Prior claim ID | Relation type | Confidence | Evidence |
|-------------|----------------|---------------|------------|----------|
| R-001 | | supports / extends / contradicts / supersedes / duplicate | high / med / low | |

## H.6 Stable key

| Field | Value |
|-------|-------|
| Stable key | canonical hash / slug |
| Key components | (which fields contribute to the key) |
| Existing key collision? | yes / no |
| Collision resolution | merged / branched / rejected |

## H.7 Memory namespace and partition

| Field | Value |
|-------|-------|
| Memory namespace | |
| Partition | user / project / shared / benchmark |
| Visibility | local / org / public |

## H.8 Writeback eligibility

| Field | Value |
|-------|-------|
| Eligible per Appendix G | yes / no |
| Gating reviewer | |
| Writeback decision | accept / hold / reject |
| Writeback timestamp | |

## H.9 BR-KG promotion

| Field | Value |
|-------|-------|
| Promotion candidate? | yes / no |
| Target node / edge type | |
| Promotion tier | candidate / accepted |
| BR-KG snapshot at promotion | |
| Source markers to set | mapping_profile / mapping_profile_hash / source / etc. |

## H.10 Caveats and retraction policy

| Field | Value |
|-------|-------|
| Retraction triggers | new contradicting evidence / dataset retraction / reviewer override |
| Retraction action | rewrite / delete / mark superseded |
| Audit log location | |

## H.11 Cross-references

| Pointer | Target |
|---------|--------|
| Episode card | Appendix A card ID |
| Review card | Appendix G card ID |
| Evidence bundle | Appendix B card ID |
