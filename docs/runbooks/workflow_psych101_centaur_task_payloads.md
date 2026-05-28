# workflow_psych101_centaur_task_payloads

## Purpose

`workflow_psych101_centaur_task_payloads` is the non-GPU bridge from the current
Psych-101 ingestion work into later Centaur/Minitaur integration. It fetches the
official Hugging Face snapshot with `psych101_fetch_hf_snapshot`, then converts
the resulting graph-plan artifact into structured task and experiment payloads
using `centaur_prepare_task_payloads`.

This workflow does **not** run Centaur or Minitaur inference. It prepares the
artifacts needed for later offline batch embedding, retrieval evaluation, or an
external behavior-model adapter.

## Inputs

- `output_dir` (required): directory where all artifacts are written
- `repo_id`: Hugging Face dataset id, defaults to `marcelbinz/Psych-101`
- `dataset_id`: local dataset id, defaults to `psych101`
- `source_name`: display name, defaults to `Psych-101`
- `sample_text`: capture sample text during snapshot aggregation, defaults to `true`
- `write_to_neo4j`: optional direct HF snapshot ingest, defaults to `false`
- `neo4j_database`: optional Neo4j database override
- `include_unmapped`: keep unmapped payloads for curation or abstaining models, defaults to `true`
- `include_experiments`: emit experiment-level payloads, defaults to `true`
- `recommended_model`: informational label stamped into payloads, defaults to `minitaur`

## Outputs

- `psych101_hf_metadata.json`
- `psych101_hf_metadata_experiments.json`
- `psych101_hf_metadata_graph_plan.json`
- `psych101_hf_metadata_neo4j_ingest.json`
- `psych101_centaur_task_payloads.json`
- `psych101_centaur_task_prompts.jsonl`
- `psych101_centaur_experiment_prompts.jsonl`

## Workflow

1. `psych101_fetch_hf_snapshot`
   - fetches the official Hugging Face metadata/parquet summary
   - writes the normalized graph-plan artifact
   - optionally writes the snapshot into Neo4j

2. `centaur_prepare_task_payloads`
   - reads `psych101_hf_metadata_graph_plan.json`
   - emits task-level and experiment-level payload records
   - writes JSONL prompt sidecars suitable for later offline model batching

## Example

```bash
br tool run workflow_psych101_centaur_task_payloads \
  --params '{"output_dir":"/tmp/psych101_centaur","dataset_id":"psych101","write_to_neo4j":false}'
```

## Notes

- Treat the payload pack as a staging artifact, not as a truth source.
- `text_v1` and Centaur/Minitaur should remain separate embedding spaces.
- If a task is still unmapped, keep it in the payload pack and let the later
  model or curation layer abstain rather than forcing a canonical task link.
