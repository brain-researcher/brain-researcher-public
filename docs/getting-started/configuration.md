# Configuration

Brain Researcher can be configured through environment variables, configuration files, and command-line options.

## Configuration Hierarchy

Configuration values are resolved in the following order (highest priority first):

1. Command-line arguments
2. Environment variables
3. `.env` file
4. Configuration files
5. Default values

## Environment Variables

### Core Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `BRAIN_RESEARCHER_MODEL` | Default LLM model | `gemini-2.5-pro` |
| `BRAIN_RESEARCHER_TEMPERATURE` | Model temperature | `0.7` |
| `BRAIN_RESEARCHER_MAX_TOKENS` | Max response tokens | `2000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `CACHE_DIR` | Cache directory | `~/.cache/brain_researcher` |

### API Keys

| Variable | Description | Required |
|----------|-------------|----------|
| `DEEPSEEK_API_KEY` | DeepSeek API key | Yes |
| `OPENAI_API_KEY` | OpenAI API key | No |
| `ANTHROPIC_API_KEY` | Anthropic API key | No |
| `HUGGINGFACE_TOKEN` | HuggingFace token | No |

### Service URLs

| Variable | Description | Default |
|----------|-------------|---------|
| `NEUROKG_API_URL` | BR-KG API endpoint | `http://localhost:5000` |
| `AGENT_URL` | Agent API endpoint for CLI/direct clients | `http://localhost:8000` |
| `BR_ORCHESTRATOR_URL` | Orchestrator API endpoint for services/Web UI | `http://localhost:3001` |
| `UI_URL` | Web UI URL | `http://localhost:3000` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |

### Database Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_PATH` | Database file path | *deprecated* (Neo4j is required) |
| `DB_POOL_SIZE` | Connection pool size | `5` |
| `DB_TIMEOUT` | Query timeout (seconds) | `30` |

## Configuration Files

### `.env` File

Create a `.env` file in the project root:

```bash
# API Keys
DEEPSEEK_API_KEY=your-deepseek-key
OPENAI_API_KEY=your-openai-key

# Model Settings
BRAIN_RESEARCHER_MODEL=gpt-4
BRAIN_RESEARCHER_TEMPERATURE=0.8

# Service Configuration
NEUROKG_API_URL=http://localhost:5000
AGENT_URL=http://localhost:8000
BR_ORCHESTRATOR_URL=http://localhost:3001

# Logging
LOG_LEVEL=DEBUG
```

Notes:
- `AGENT_URL` is what the CLI chat/files/datasets commands use today.
- `BR_ORCHESTRATOR_URL` is the preferred explicit orchestrator setting for cross-service wiring.
- Some older components still accept `NEUROKG_URL` in addition to `NEUROKG_API_URL`.

### `config.yaml` (Optional)

For more complex configurations:

```yaml
# config.yaml
model:
  default: gpt-4
  temperature: 0.7
  max_tokens: 2000
  available:
    - deepseek-chat
    - gpt-4
    - claude-3

services:
  neurokg:
    host: 0.0.0.0
    port: 5000
    workers: 4
  agent:
    host: 0.0.0.0
    port: 8000
    workers: 2

database:
  # BR-KG uses Neo4j (configured via env vars); no local *.db file is used.
  neo4j_uri: ${NEO4J_URI}
  neo4j_user: ${NEO4J_USER}
  neo4j_password: ${NEO4J_PASSWORD}
  neo4j_database: ${NEO4J_DATABASE}

cache:
  backend: redis
  redis_url: redis://localhost:6379
  ttl: 3600

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: logs/brain_researcher.log
```

## Per-User Configuration

Create user-specific settings in `~/.config/brain_researcher/config.yaml`:

```yaml
# User preferences
preferences:
  default_model: gpt-4
  output_format: json
  verbose: true

# Custom shortcuts
aliases:
  qm: "query search motor cortex"
  stats: "query stats --detailed"
```

## Model Configuration

### Model Selection

Configure available models and their parameters:

```python
# src/brain_researcher/config/
MODELS = {
    "deepseek-chat": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "max_tokens": 4000,
        "supports_functions": True,
    },
    "gpt-4": {
        "api_key_env": "OPENAI_API_KEY",
        "max_tokens": 8000,
        "supports_functions": True,
    },
    "claude-3": {
        "api_key_env": "ANTHROPIC_API_KEY",
        "max_tokens": 100000,
        "supports_functions": False,
    },
}
```

### Model Parameters

Fine-tune model behavior:

```bash
# Conservative responses
export BRAIN_RESEARCHER_TEMPERATURE=0.3

# Creative responses
export BRAIN_RESEARCHER_TEMPERATURE=1.2

# Detailed responses
export BRAIN_RESEARCHER_MAX_TOKENS=4000
```

## Service Configuration

### BR-KG Service

```bash
# Performance tuning
export NEUROKG_CACHE_SIZE=1000
export NEUROKG_QUERY_TIMEOUT=60
export NEUROKG_MAX_RESULTS=100

# Database optimization
export NEUROKG_ENABLE_QUERY_CACHE=true
export NEUROKG_VACUUM_ON_STARTUP=true
```

### Agent Service

```bash
# Agent behavior
export AGENT_MAX_RETRIES=3
export AGENT_TIMEOUT=300
export AGENT_MEMORY_SIZE=10

# Tool configuration
export AGENT_ENABLE_ALL_TOOLS=true
export AGENT_TOOL_TIMEOUT=60
```

## Docker Configuration

### Docker Compose Override

Create `docker-compose.override.yml` for local settings:

```yaml
version: '3.8'

services:
  neurokg:
    environment:
      - LOG_LEVEL=DEBUG
      - NEO4J_URI=${NEO4J_URI}
      - NEO4J_USER=${NEO4J_USER:-neo4j}
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
      - NEO4J_DATABASE=${NEO4J_DATABASE:-neo4j}
    volumes:
      - ./custom_data:/data/custom

  agent:
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - MODEL=gpt-4
```

### Resource Limits

Configure container resources:

```yaml
services:
  neurokg:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G
```

## Security Configuration

### API Security

```bash
# Enable API authentication
export API_AUTH_ENABLED=true
export API_KEY=your-secure-api-key

# CORS settings
export CORS_ORIGINS=["http://localhost:3000", "https://yourdomain.com"]

# Rate limiting
export RATE_LIMIT_PER_MINUTE=60
```

### Data Security

```bash
# Encryption
export ENCRYPT_SENSITIVE_DATA=true
export ENCRYPTION_KEY=your-encryption-key

# Audit logging
export ENABLE_AUDIT_LOG=true
export AUDIT_LOG_PATH=logs/audit.log
```

## Performance Tuning

### Caching

```bash
# Redis cache configuration
export CACHE_TTL=3600  # 1 hour
export CACHE_MAX_SIZE=1000
export CACHE_EVICTION_POLICY=lru

# Query result caching
export ENABLE_QUERY_CACHE=true
export QUERY_CACHE_TTL=600  # 10 minutes
```

### Concurrency

```bash
# Worker configuration
export WORKER_THREADS=4
export MAX_CONCURRENT_REQUESTS=10
export REQUEST_TIMEOUT=300

# Database connections
export DB_POOL_SIZE=20
export DB_POOL_TIMEOUT=30
```

## Logging Configuration

### Log Levels

```bash
# Set different log levels per module
export LOG_LEVEL=INFO
export LOG_LEVEL_NEUROKG=DEBUG
export LOG_LEVEL_AGENT=WARNING
export LOG_LEVEL_ANALYSIS=INFO
```

### Log Output

```bash
# File logging
export LOG_TO_FILE=true
export LOG_FILE_PATH=logs/brain_researcher.log
export LOG_FILE_MAX_SIZE=100M
export LOG_FILE_BACKUP_COUNT=5

# Structured logging
export LOG_FORMAT=json
export LOG_INCLUDE_TIMESTAMP=true
export LOG_INCLUDE_HOSTNAME=true
```

## Development Configuration

### Debug Mode

```bash
# Enable debug features
export DEBUG=true
export FLASK_ENV=development
export RELOAD=true

# Verbose output
export VERBOSE=true
export SHOW_SQL_QUERIES=true
export PROFILE_REQUESTS=true
```

### Testing

```bash
# Test configuration
export TEST_MODE=true
export TEST_DB_PATH=:memory:
export MOCK_EXTERNAL_APIS=true
```

## Troubleshooting

### Configuration Validation

Check your configuration:

```bash
# Validate configuration
brain-researcher config validate

# Show current configuration
brain-researcher config show

# Test service connections
brain-researcher config test-connections
```

### Common Issues

1. **Missing API keys**: Ensure all required API keys are set
2. **Port conflicts**: Check if ports are already in use
3. **Permission errors**: Verify file/directory permissions
4. **Memory issues**: Adjust worker counts and cache sizes

## Best Practices

1. **Use `.env` files**: Keep sensitive data out of version control
2. **Environment-specific configs**: Use different configs for dev/staging/prod
3. **Document changes**: Keep configuration documentation up to date
4. **Monitor performance**: Adjust settings based on usage patterns
5. **Security first**: Always use secure defaults
