# Environment Setup for Brain Researcher Services

## Quick Start

The Brain Researcher services require API keys for LLM providers. The `br serve`
command automatically loads the nearest `.env` file unless
`BRAIN_RESEARCHER_SKIP_DOTENV=1` is set, but shell profile or `direnv` setup is
still the most reliable way to make keys available across new terminals and
non-CLI processes.

For Docker, the usual path is:

1. Create one LLM provider key.
2. Copy `.env.example` to `.env`.
3. Generate local service secrets.
4. Fill `.env` with the generated secrets and the provider key.

Never commit the filled `.env` file. Do not put secret API keys in
`NEXT_PUBLIC_*` variables because those can be exposed to the browser bundle.

## Get an LLM Provider Key

Choose one provider to start. More can be added later.

| Provider | Create/manage keys | Env var | Example `DEFAULT_LLM_MODEL` |
|---|---|---|---|
| Google Gemini | [Google AI Studio API keys](https://aistudio.google.com/app/apikey) | `GEMINI_API_KEY` | `gemini-3-flash-preview` |
| OpenAI | [OpenAI API keys](https://platform.openai.com/api-keys) | `OPENAI_API_KEY` | `gpt-4o` |
| Anthropic | [Anthropic Console keys](https://console.anthropic.com/settings/keys) | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet` |
| DeepSeek | [DeepSeek API keys](https://platform.deepseek.com/api_keys) | `DEEPSEEK_API_KEY` | `deepseek-chat` |

## Project `.env` Example

Create the local file:

```bash
cp .env.example .env
```

Generate local service secrets:

```bash
python - <<'PY'
import secrets

print("NEO4J_PASSWORD=" + secrets.token_urlsafe(24))
print("JWT_SECRET_KEY=" + secrets.token_urlsafe(48))
print("NEXTAUTH_SECRET=" + secrets.token_urlsafe(48))
PY
```

Paste the generated values into `.env`, then add one provider key. For example,
with Gemini:

```env
NEO4J_PASSWORD=replace_with_generated_value
JWT_SECRET_KEY=replace_with_generated_value
NEXTAUTH_SECRET=replace_with_generated_value

GEMINI_API_KEY=replace_with_key_from_google_ai_studio
DEFAULT_LLM_MODEL=gemini-3-flash-preview
```

Equivalent provider alternatives:

```env
OPENAI_API_KEY=replace_with_key_from_openai
DEFAULT_LLM_MODEL=gpt-4o
```

```env
ANTHROPIC_API_KEY=replace_with_key_from_anthropic
DEFAULT_LLM_MODEL=claude-3-5-sonnet
```

```env
DEEPSEEK_API_KEY=replace_with_key_from_deepseek
DEFAULT_LLM_MODEL=deepseek-chat
```

`docker compose up` automatically reads `.env` from the repository root. For
manual service runs, use one of the options below.

### Option 1: Shell Profile (Recommended)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
export GEMINI_API_KEY="replace_with_key_from_google_ai_studio"
export DEFAULT_LLM_MODEL="gemini-3-flash-preview"
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
export GEMINI_API_KEY="replace_with_key_from_google_ai_studio"
export DEFAULT_LLM_MODEL="gemini-3-flash-preview"
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
| Google Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-3-flash-preview` |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o` |
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet` |

Set the model with:
```bash
export DEFAULT_LLM_MODEL="gemini-3-flash-preview"  # or your preferred model
```

## Troubleshooting

### Agent Returns 500 Errors

**Symptom**: `/chat` or `/act` endpoints return 500 Internal Server Error

**Cause**: LLM initialization fails because API keys are still missing after
`.env` loading or shell exports

**Fix**:
1. Verify a key is present without printing it:
   ```bash
   python - <<'PY'
   import os
   keys = ["GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"]
   print({key: bool(os.getenv(key)) for key in keys})
   PY
   ```
2. If all values are `False`, add one provider key to `.env` or export it in
   the shell.
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
- **BR-KG service (port 5000)**: `/api/kg/*`, `/api/br-kg/*`, `/health`
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
