# workflow_behavior_to_fmri_retrieval

`workflow_behavior_to_fmri_retrieval` is the minimal user-facing workflow for the
behavior-to-brain bridge. It resolves a behavioral seed such as a Psych-101 task,
runs BR-KG behavior-to-fMRI retrieval, and writes a workflow-friendly JSON
artifact.

## What It Runs

Single-step declarative workflow:

1. `behavior_to_fmri_retrieval_export`

The runtime wrapper calls BR-KG retrieval directly, then writes:

- `behavior_to_fmri_retrieval.json`

## Typical Inputs

- `output_dir`: directory for the retrieval artifact
- `seed_id`: preferred KG seed identifier such as `psych101:task:go-no-go`
- `label` / `name`: optional fallback seed resolution fields
- `limit`
- `max_maps`
- `max_paths`
- `max_regions_per_map`
- `max_behavior_neighbors`
- `min_behavior_similarity`
- `neo4j_database`

## Example

```bash
python - <<'PY'
from brain_researcher.services.tools.runner import execute_tool

res = execute_tool(
    "workflow_behavior_to_fmri_retrieval",
    {
        "output_dir": "/tmp/behavior_to_fmri_out",
        "seed_id": "psych101:task:go-no-go",
        "limit": 5,
    },
)
print(res.status)
print(res.data)
PY
```

## Expected Artifact

`behavior_to_fmri_retrieval.json` contains:

- workflow input parameters
- retrieval payload from BR-KG
- ranked `items`
- retrieval `summary`

## Notes

- `seed_id` is preferred over `name` because it avoids ontology-resolution ambiguity.
- The workflow does not run Centaur/Minitaur inference. It consumes the existing
  BR-KG bridges, including family-aware and behavior-similar retrieval paths.
