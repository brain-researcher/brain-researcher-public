# CLI Usage Guide

The Brain Researcher CLI provides a unified interface for all functionality.

## Command Structure

```bash
brain-researcher [OPTIONS] COMMAND [ARGS]...
# or use the short alias
br [OPTIONS] COMMAND [ARGS]...
```

## Core Commands

### Database Management

```bash
# Initialize database
br db init

# Check database status
br db status

# Optimize database performance
br db optimize

# Validate database integrity
br db validate

# Merge duplicate nodes
br db merge-duplicates
```

### Data Ingestion

```bash
# Load PubMed data
br data load-pubmed --input pubmed_data.json

# Load brain regions from Wikidata
br data load-regions --input wikidata_regions.json

# Load OpenNeuro dataset
br data load-openneuro --dataset ds000001

# Alternative ingestion commands
br ingest pubmed pubmed_data.json
br ingest openneuro ds000001 --participants 10
```

### Query and Search

```bash
# Search for brain regions or concepts
br query search "motor cortex"
br query search "memory consolidation" --limit 10

# Execute Cypher queries (NetworkX)
br query cypher "MATCH (n:BrainRegion) RETURN n LIMIT 5"

# Get database statistics
br query stats
```

### Analysis

```bash
# Run contrast analysis
br analyze contrast --data scan.nii.gz --output results.json

# Statistical analysis
br analyze statistical --data study_dir/ --params '{"threshold": 0.05}'

# Create visualizations
br analyze visualize --data results.nii.gz --type glass-brain
```

### Interactive Chat

For notebook workflows, see [Marimo + Claude Code / Codex](marimo.md).

```bash
# Start interactive chat with default model
br chat

# Use specific model
br chat --model gpt-4
br chat --model deepseek-chat

# Set custom temperature
br chat --temperature 0.7
```

### Service Management

```bash
# Start individual services
br serve kg          # BR-KG API on port 5000 (Neo4j required)
br serve agent       # LLM Agent on port 8000
br serve orchestrator  # Orchestrator API on port 3001
br serve web         # Next.js Web UI on port 3000

# Custom ports
br serve agent --port 8001
br serve kg --host 0.0.0.0 --port 5002
br serve orchestrator --host 0.0.0.0 --port 3101
br serve web --port 4000
```

### Remote Sessions

```bash
# List wrapped sessions
br sessions ls

# Attach an MCP run and immediately bind it to Slack
br sessions attach mcp_run run_demo \
  --display-name "Demo MCP Run" \
  --slack-channel C0123456789

# Attach a coding thread
br sessions attach coding_session thread_abc123 \
  --thread-id thread_abc123 \
  --display-name "Repo Fix" \
  --slack-channel C0123456789

# Render a Slack app manifest for your public tunnel/deployment URL
br sessions slack-manifest --public-base-url https://your-public-url.example.com
```

## Advanced Usage

### Combining Commands

Chain commands for complex workflows:

```bash
# Load data and immediately query
br data load-pubmed --input data.json && br query search "fMRI"

# Initialize and populate database
br db init && br ingest openneuro ds000001
```

### Output Formats

Control output format:

```bash
# JSON output for scripting
br query stats --format json

# Detailed debug output
br --verbose analyze contrast --data scan.nii.gz

# Quiet mode
br --quiet db optimize
```

### Configuration

Set persistent options:

```bash
# Set default model
export BRAIN_RESEARCHER_MODEL="gpt-4"

# Set service endpoints
export AGENT_URL="http://localhost:8000"
export NEUROKG_API_URL="http://localhost:5000"
export BR_ORCHESTRATOR_URL="http://localhost:3001"
```

Notes:
- Use `AGENT_URL` for CLI commands that talk directly to the agent service.
- `br serve orchestrator` starts the standalone orchestrator service on port 3001.
- Set `BR_ORCHESTRATOR_URL` explicitly when another service or the Web UI needs to reach Orchestrator.
- `NEUROKG_API_URL` is the canonical BR-KG endpoint for agent-side integrations; some older service code still also accepts `NEUROKG_URL`.
- Use the agent service for `/act`, `/chat`, and the legacy `/api/runs*` compatibility facade.
- Use the orchestrator service for `/run`, `/api/jobs`, `/api/analyses`, `/api/cache/*`, canonical analysis submit/list APIs, and job inspection APIs.
- The Web UI owns the public browser-facing `/api/*` surface and proxies those routes to Agent or Orchestrator as needed.
## Docker Usage

Run CLI commands in Docker:

```bash
# Using docker-compose
docker-compose -f docker-compose.dev.yml run --rm cli version
docker-compose -f docker-compose.dev.yml run --rm cli db status

# Direct Docker
docker run --rm brain-researcher:cli brain-researcher --help
```

## Examples

### Example 1: Complete Analysis Workflow

```bash
# 1. Initialize system
br db init

# 2. Load neuroimaging data
br ingest openneuro ds000030

# 3. Search for relevant studies
br query search "visual processing"

# 4. Run analysis
br analyze statistical --data ds000030/ --params '{"task": "visual"}'

# 5. Visualize results
br analyze visualize --data results/spmT_0001.nii --type slices
```

### Example 2: Knowledge Graph Exploration

```bash
# Find all motor-related brain regions
br query cypher "MATCH (n:BrainRegion) WHERE n.name CONTAINS 'motor' RETURN n"

# Get relationships between regions
br query cypher "MATCH (a:BrainRegion)-[r]->(b:BrainRegion) RETURN a.name, type(r), b.name LIMIT 20"

# Search publications about a region
br query search "primary motor cortex fMRI" --type publication
```

### Example 3: Batch Processing

```bash
# Process multiple datasets
for dataset in ds000001 ds000002 ds000003; do
    br ingest openneuro $dataset --participants 20
done

# Bulk query execution
cat queries.txt | while read query; do
    br query search "$query" --format json >> results.jsonl
done
```

## Tips and Tricks

1. **Use aliases**: Create shell aliases for common commands
   ```bash
   alias brc="brain-researcher chat"
   alias brdb="brain-researcher db"
   ```

2. **Tab completion**: Install shell completions
   ```bash
   br --install-completion bash  # or zsh, fish
   ```

3. **Debug mode**: Use `-v` or `--verbose` for detailed output
   ```bash
   br -v analyze contrast --data scan.nii.gz
   ```

4. **Help for any command**: Add `--help` to any command
   ```bash
   br query --help
   br analyze contrast --help
   ```

## See Also

- [CLI Reference](../api/cli-reference.md) - Complete command reference
- [Configuration Guide](../getting-started/configuration.md) - Advanced configuration
- [API Documentation](../api/python.md) - Using Brain Researcher as a Python library
