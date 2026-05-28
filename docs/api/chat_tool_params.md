# Chat Tool Parameters (Chat-safe whitelist)

This doc summarizes the parameters expected by the chat-exposed tools/families. Use these in selection prompts and ToolSpec schemas.

## gemini.fs (family)
- op_param: `op`
- Ops
  - list_dir: `{op: "list_dir", path?: ".", max_entries?: 200}`
  - read: `{op: "read", path: "path/to/file", start_line?: 1, end_line?: 200}`
  - search: `{op: "search", query: "pattern", path_glob?: "**/*.py", max_results?: 50}`
- Notes: write/replace exist but are dangerous; keep filtered in chat.

## gemini.net (family)
- op_param: `op`
- fetch: `{op: "fetch", url: "https://..."}`
- google: `{op: "google", query: "search terms", num_results?: 5}`

## code_agent (tool)
- Params: `{instruction: string, code_context?: string, file_paths?: [string], test_command?: string, model_hint?: string}`
- Example: `{"instruction":"fix failing test","file_paths":["parser.py","tests/test_parser.py"],"test_command":"pytest -q tests/test_parser.py"}`

## neurokg.client (family)
- op_param: `op`
- search_concepts: `{op:"search_concepts", query:string}`
- coordinate_lookup: `{op:"coordinate_lookup", x:float, y:float, z:float, space?:"MNI152", top_k?:int}`
- literature: `{op:"literature", concept:string}`
- graph_query: `{op:"graph_query", cypher:string, limit?:int}`
- task_map: `{op:"task_map", task:string}`

## find_related_concepts (leaf)
- `{query:string, top_k?:int}`

## coordinate_to_concept (leaf)
- `{x:float, y:float, z:float, space?:"MNI152", top_k?:int}`

## graph_query (leaf)
- `{cypher:string, limit?:int}`

## task_to_concept_mapping (leaf)
- `{task:string, top_k?:int}`

## concept_literature_search (leaf)
- `{concept:string, top_k?:int}`

## datasets.client (family)
- op_param: `op`
- list_resources: `{op:"list_resources", provider?:"openneuro|dandi|local", limit?:int}`
- search: `{op:"search", query:string, provider?:string, limit?:int}`
- describe: `{op:"describe", id:string}`

## datasets.list_resources (leaf)
- `{provider?:"openneuro|dandi|local", limit?:int}`

## jobs.client (family)
- op_param: `op`
- list: `{op:"list", user?:string}`
- status: `{op:"status", job_id:string}`
- logs: `{op:"logs", job_id:string, tail_lines?:int}`

## fmri.connectivity_client.light (family)
- op_param: `op`
- fetch_atlas: `{op:"fetch_atlas", atlas:string}`
- extract_timeseries: `{op:"extract_timeseries", fmri_path:string, mask_path?:string, atlas?:string, strategy?:"mean"}`
- connectivity_matrix: `{op:"connectivity_matrix", timeseries_path:string, kind?:"correlation|partial|tangent"}`

## viz.client (family)
- op_param: `op`
- surface_viz: `{op:"surface_viz", surf_file:string, overlay_file?:string, threshold?:number}`
- generic_viz: `{op:"generic_viz", stat_map:string, bg_img?:string, display_mode?:"ortho"}`
