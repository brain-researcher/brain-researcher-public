# workflow_psych101_centaur_behavior_embeddings

## Purpose

`workflow_psych101_centaur_behavior_embeddings` extends the non-GPU Psych-101
Centaur payload pack into an actual offline embedding pass. It:

1. fetches the official Psych-101 snapshot
2. prepares Centaur/Minitaur prompt JSONL sidecars
3. runs offline behavioral embedding extraction
4. optionally writes a sibling KG feature space such as
   `embedding_centaur_behavior_v1`

This is still an offline batch workflow, not a hosted model service.

## Inputs

- `output_dir` (required): directory where all artifacts are written
- `model_name_or_path` (required): local or HF model path for offline embedding
- `embedding_backend`: `hf_hidden_state` for real models or `hash` for deterministic dry runs/tests
- `pooling`: hidden-state pooling method, defaults to `mean`
- `batch_size`: embedding batch size, defaults to `4`
- `max_length`: tokenizer max length, defaults to `512`
- `normalize`: L2-normalize resulting embeddings, defaults to `true`
- `device`: optional torch device override
- `trust_remote_code`: forward to HF model loading, defaults to `false`
- `repo_id`, `dataset_id`, `source_name`, `sample_text`: snapshot controls
- `include_unmapped`, `include_experiments`: payload controls
- `write_snapshot_to_neo4j`: optional HF snapshot ingest, defaults to `false`
- `write_embeddings_to_neo4j`: write embedding properties into Neo4j, defaults to `true`
- `write_experiment_embeddings`: also update experiment nodes, defaults to `false`
- `neo4j_database`: optional Neo4j database override
- `embedding_property`: KG node property for the sibling space, defaults to `embedding_centaur_behavior_v1`

## Outputs

- `psych101_hf_metadata.json`
- `psych101_hf_metadata_experiments.json`
- `psych101_hf_metadata_graph_plan.json`
- `psych101_hf_metadata_neo4j_ingest.json`
- `psych101_centaur_task_payloads.json`
- `psych101_centaur_task_prompts.jsonl`
- `psych101_centaur_experiment_prompts.jsonl`
- `psych101_centaur_behavior_embeddings.json`
- `psych101_centaur_task_embeddings.jsonl`
- `psych101_centaur_experiment_embeddings.jsonl`
- `psych101_centaur_neo4j_ingest.json`

## Workflow

1. `psych101_fetch_hf_snapshot`
2. `centaur_prepare_task_payloads`
3. `centaur_offline_behavior_embeddings`

The final step consumes the prompt JSONL sidecars and writes embedding records.
If Neo4j credentials are configured and `write_embeddings_to_neo4j=true`, the
workflow merges properties such as:

- `embedding_centaur_behavior_v1`
- `embedding_centaur_behavior_v1_model`
- `embedding_centaur_behavior_v1_backend`
- `embedding_centaur_behavior_v1_pooling`
- `embedding_centaur_behavior_v1_dim`
- `embedding_centaur_behavior_v1_updated_at`

## Examples

Real offline model:

```bash
br tool run workflow_psych101_centaur_behavior_embeddings \
  --params '{"output_dir":"/tmp/psych101_centaur","model_name_or_path":"/models/minitaur","write_embeddings_to_neo4j":true}'
```

Deterministic dry run:

```bash
br tool run workflow_psych101_centaur_behavior_embeddings \
  --params '{"output_dir":"/tmp/psych101_centaur","model_name_or_path":"hash-test","embedding_backend":"hash","write_embeddings_to_neo4j":false}'
```

## Notes

- `hash` is only for dry runs and tests; it is not a Centaur substitute.
- The workflow writes a sibling behavioral feature space and does not replace
  `embedding_text_v1`.
- Default Neo4j writes target Task nodes; experiment-node writes stay opt-in.
