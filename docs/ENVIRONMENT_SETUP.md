# Environment Setup for Brain Researcher Services

## Quick Start

The Brain Researcher services require API keys for LLM providers. The `br serve`
command automatically loads the nearest `.env` file unless
`BRAIN_RESEARCHER_SKIP_DOTENV=1` is set, but shell profile or `direnv` setup is
still the most reliable way to make keys available across new terminals and
non-CLI processes.

### Option 1: Shell Profile (Recommended)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
export GEMINI_API_KEY="your-api-key-here"
export DEFAULT_LLM_MODEL="gemini-2.5-pro"
```

Then reload:
```bash
source ~/.bashrc  # or source ~/.zshrc
```

### Option 2: direnv (Project-Scoped)

1. Install direnv:
   ```bash
   # Ubuntu/Debian
   sudo apt install direnv

   # macOS
   brew install direnv
   ```

2. Add to shell profile (`~/.bashrc` or `~/.zshrc`):
   ```bash
   eval "$(direnv hook bash)"  # or zsh
   ```

3. Create `.envrc` in project root (git-ignored):
```bash
export GEMINI_API_KEY="your-api-key-here"
export DEFAULT_LLM_MODEL="gemini-2.5-pro"
```

4. Allow direnv:
   ```bash
   direnv allow
   ```

### Option 3: Manual Export (Per Session)

```bash
set -a && source .env && set +a
br serve agent --port 8000
```

## Supported LLM Providers

| Provider | Environment Variable | Example Model |
|----------|---------------------|---------------|
| Google Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-2.5-pro` |
| OpenAI | `OPENAI_API_KEY` | `gpt-4` or `gpt-3.5-turbo` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-20241022` |

Set the model with:
```bash
export DEFAULT_LLM_MODEL="gemini-2.5-pro"  # or your preferred model
```

## Troubleshooting

### Agent Returns 500 Errors

**Symptom**: `/chat` or `/act` endpoints return 500 Internal Server Error

**Cause**: LLM initialization fails because API keys are still missing after
`.env` loading or shell exports

**Fix**:
1. Verify keys are exported: `echo $GEMINI_API_KEY`
2. If empty, export the key: `export GEMINI_API_KEY="your-key"`
3. Restart the agent: `pkill -f "br serve agent" && br serve agent --port 8000`
4. Test: `curl http://localhost:8000/health` should show `"status": "healthy"`

### Keys Not Persisting

**Symptom**: Keys work in current shell but disappear in new terminals

**Cause**: Keys only exported in current session

**Fix**: Add export commands to shell profile (`~/.bashrc` or `~/.zshrc`) - see Option 1 above

## Security Best Practices

- **Never commit API keys** to git
- Add `.envrc` to `.gitignore` if using direnv
- Use shell profiles for development, secrets managers for production
- Rotate keys periodically

## Service Startup

After setting up environment variables:

```bash
# Start agent (requires API keys)
br serve agent --port 8000

# Start BR-KG (Neo4j required)
br serve kg --port 5000

# Start Orchestrator
br serve orchestrator --port 3001

# Start Web UI (Next.js)
br serve web --port 3000
```

### Endpoint Map

- **Agent service (port 8000)**: `/act`, `/chat`, legacy `/api/runs*` compatibility facade, `/api/tools`, `/api/files`
- **BR-KG service (port 5000)**: `/api/kg/*`, `/api/neurokg/*`, `/health`
- **Orchestrator service (port 3001)**: `/run`, `/health`, `/docs`, `/api/jobs`, `/api/analyses`, `/api/cache/*`
- **Web UI public proxy (port 3000)**: browser-facing `/api/*` routes. `/api/runs*` is compatibility-only and still proxies to Agent for legacy callers; submit/list now go through `/api/analyses*`, which is the canonical public analysis facade over Orchestrator `/run` + `/api/analyses`; detail/share/stream data comes from Orchestrator job/analysis endpoints.

Set `BR_ORCHESTRATOR_URL` explicitly when another service or the Web UI needs
to reach the standalone orchestrator service.
## Verification

Test that everything is working:

```bash
# Check agent health
curl http://localhost:8000/health

# Check orchestrator health
curl http://localhost:3001/health

# Test simple chat
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "Hello, can you help me?"}' \
  | jq '.message.content'
```

Expected: You should see a helpful response from the LLM.
