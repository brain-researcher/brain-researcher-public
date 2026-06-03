# Task Matchers

This repository includes a hybrid matcher that resolves task strings to
Cognitive Atlas task labels. The matcher first queries a NiCLIP embedding index,
then falls back to SBERT and finally RapidFuzz string matching.

Default thresholds:

- **NiCLIP**: similarity ≥ 0.85
- **SBERT**: similarity ≥ 0.80
- **Fuzzy**: ratio ≥ 85

The vocabulary is derived from Cognitive Atlas task definitions
(`br-kg/data/br-kg/raw/cognitive_tasks.json`) plus custom synonyms listed in
`data/ca_task_synonyms.tsv`.

```
from utils.task_matcher import TaskMatcher

matcher = TaskMatcher()
print(matcher.match_candidates("BART", top_k=3))
```

To extend the synonym list, edit `data/ca_task_synonyms.tsv` and rebuild the
indices with `python scripts/build/build_task_indices.py`.
