# `workflow_psych101_hf_snapshot`

Non-GPU intake path for the official `marcelbinz/Psych-101` dataset on Hugging Face.

## Inputs
- `output_dir`: Directory for snapshot artifacts.
- Optional: `repo_id`, `dataset_id`, `source_name`, `sample_text`, `write_to_neo4j`, `neo4j_database`.

## What It Does
1. Fetches dataset metadata from the Hugging Face dataset API.
2. Reads split/parquet metadata from datasets-server.
3. Aggregates experiment-level summaries from official parquet files.
4. Normalizes experiment paths against the local task-family taxonomy.
5. Emits graph-ready artifacts and attempts a direct Neo4j ingest.

## Expected Outputs
- `psych101_hf_metadata.json`
- `psych101_hf_metadata_experiments.json`
- `psych101_hf_metadata_graph_plan.json`
- `psych101_hf_metadata_neo4j_ingest.json`

## Notes
- This workflow avoids GPU serving and does not require the `datasets` Python package.
- Participant identifiers in Psych-101 are treated as experiment-local during summary generation.
- The workflow now defaults to carrying a sample text field forward when one is available, so local Psych-101 task nodes can inherit lightweight descriptions.
- If Neo4j is not configured, the workflow still succeeds and records `skipped_missing_config` in the Neo4j ingest summary artifact.
- The workflow currently uses one lightweight step tool: `psych101_fetch_hf_snapshot`.
