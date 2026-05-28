# CLI Reference

Complete reference for all Brain Researcher CLI commands.

## Global Options

```bash
br [OPTIONS] COMMAND [ARGS]...
```

| Option | Short | Description |
|---|---|---|
| `--verbose` | `-v` | Enable verbose output. |
| `--quiet` | `-q` | Suppress non-essential output. |
| `--help` | | Show help message for a command. |
| `--version` | | Show the version of the CLI. |
| `--install-completion` | | Install shell completion for the CLI. |

## Commands

### `br chat`

Start an interactive chat session with the Brain Researcher agent.

```bash
br chat [OPTIONS]
```

**Options:**
- `--model TEXT`: LLM model to use (e.g., `deepseek-chat`, `gpt-4`).
- `--temperature FLOAT`: Set the model's temperature (0.0-2.0).
- `--max-tokens INT`: Maximum number of tokens in the response.
- `--system-prompt TEXT`: Use a custom system prompt.

### `br copilot`

Get assistance with tool selection and parameter completion.

- **`suggest`**: Suggests tools based on a natural language query.
- **`autocomplete`**: Autocompletes parameters for a given tool.
- **`learn`**: Records user feedback to improve suggestions.
- **`demo`**: Demos suggestions via the Orchestrator copilot API.

### `br data`

Load and manage data.

- **`load-pubmed`**: Loads PubMed publications from a JSON file.
- **`load-wikidata`**: Loads entities from a WikiData JSON file.
- **`load-openneuro`**: Loads metadata for an OpenNeuro dataset.
- **`add-samples`**: Adds sample datasets for testing.
- **`export`**: Exports data from the database.
- **`validate-bids`**: Validates BIDS datasets.
- **`list-sources`**: Lists available data sources.

### `br db`

Manage the BR-KG database.

- **`init`**: Initializes the database.
- **`status`**: Checks the database status and shows statistics.
- **`optimize`**: Optimizes database performance.
- **`validate`**: Validates database integrity.
- **`merge-duplicates`**: Merges duplicate nodes in the graph.

### `br migrate`

Manage database migrations.

- **`create`**: Creates a new migration file.
- **`up`**: Applies pending migrations.
- **`down`**: Rolls back migrations.
- **`status`**: Shows the current migration status.
- **`verify`**: Verifies migration checksums.
- **`list`**: Lists all migrations.

### `br niclip`

Run NICLIP neuroimaging analysis.

- **`analyze`**: Analyzes a brain image to predict cognitive processes.
- **`search`**: Searches for similar cognitive concepts or tasks.
- **`load`**: Loads NICLIP data into the BR-KG database.
- **`info`**: Displays information about available NICLIP data.

### `br query`

Query and search the knowledge graph.

- **`interactive`**: Starts an interactive query mode.
- **`search`**: Searches the knowledge graph using a query string.
- **`cypher`**: Executes a Cypher query directly against the database.
- **`concepts`**: Searches for concepts.
- **`coordinates`**: Finds concepts near specified brain coordinates.
- **`stats`**: Shows database statistics.

### `br service`

Manage Brain Researcher services.

- **`docker`**: Helpers for Docker Compose.
  - `start`: Starts dockerized services.
  - `stop`: Stops dockerized services.
  - `status`: Shows Docker Compose status.
  - `logs`: Shows logs for services.
  - `seed`: Seeds the database in the container.
- **`status`**: Shows the status of all services.
- **`stop`**: Stops a running service.
- **`restart`**: Restarts a service.
- **`ports`**: Lists all ports used by services.
- **`cleanup`**: Cleans up orphaned processes.
- **`logs`**: Shows logs for a service.

### `br standards`

Validate and manage BR-KG standards.

- **`validate`**: Validates compliance with BR-KG standards.
- **`check-id`**: Checks how an entity ID would be generated.
- **`show-config`**: Displays configuration settings.
- **`export-schema`**: Exports the BR-KG schema.
- **`list-invariants`**: Lists all defined data invariants.

### `br tools`

Generate and manage neuroimaging tool commands.

- **`list`**: Lists available Neurodesk tools.
- **`gen`**: Generates a Neurodesk command for a tool.
- **`batch`**: Generates a batch script for multiple commands.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BRAIN_RESEARCHER_MODEL` | Default LLM for the `chat` command. | `deepseek-chat` |
| `NEUROKG_API_URL` | URL for the BR-KG API service. | `http://localhost:5000` |
| `AGENT_URL` | URL for the Agent service used by direct CLI clients. | `http://localhost:8000` |
| `BR_ORCHESTRATOR_URL` | URL for the Orchestrator service used by cross-service integrations. | `http://localhost:3001` |
| `DEEPSEEK_API_KEY` | API key for DeepSeek. | (required) |
| `OPENAI_API_KEY` | API key for OpenAI. | (optional) |
| `LOG_LEVEL` | The logging level. | `INFO` |

## Exit Codes

| Code | Description |
|---|---|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Database error |
| 4 | Network error |
| 5 | File not found |
| 6 | Permission denied |

## Examples

### Quick Start

```bash
# Initialize the database
br db init

# Load sample data
br data add-samples

# Start a chat session
br chat

# Query the knowledge graph
br query search "motor cortex activation"
```

### Working with Services

```bash
# Start all services with Docker
br service docker start

# Check service status
br service status

# View logs for a specific service
br service logs agent
```

### Data Management

```bash
# Load PubMed data
br data load-pubmed --input pubmed_data.json

# Load an OpenNeuro dataset
br data load-openneuro ds000114

# Validate a BIDS dataset
br data validate-bids /path/to/dataset
```

See the [User Guide](../guides/getting-started.md) for more detailed examples and workflows.
