# @brainr/cli

Lightweight CLI wrapper for Brain Researcher that provides two execution modes:
- **Gemini mode**: Use Google's official Gemini CLI with your free OAuth credits
- **Proxy mode**: Forward to Brain Researcher core service for full functionality

## Installation

```bash
npm install -g @brainr/cli
```

## Usage

### Gemini Mode (Free Credits)
Use the official Gemini CLI with your personal OAuth login:

```bash
# First login to Gemini (one-time)
gemini login

# Then use brainr with --gemini flag
brainr --gemini -p "Explain quantum computing"
brainr --gemini -m gemini-2.5-flash -p "Write a Python function"
```

### Proxy Mode (Default)
Forward commands to Brain Researcher core service:

```bash
# Uses local br CLI if installed
brainr chat
brainr ask -p "What is fMRI?"

# Or proxy to remote core service
export BR_URL=http://localhost:8000
brainr chat
```

## Modes

| Mode | Flag | Description | Use Case |
|------|------|-------------|----------|
| Proxy | `--proxy` or default | Forwards to `br` CLI or HTTP service | Full Brain Researcher features |
| Gemini | `--gemini` | Spawns official Gemini CLI | Free daily credits via OAuth |

Notes:
- You can set `BRAINR_DEFAULT_MODE=gemini` to make Gemini mode the default.
- Heuristic: If you run `brainr` with only prompt/model flags (e.g., `-p`, `--prompt`, `-m`, `--model`) and no subcommand, it will automatically choose Gemini mode.

## Environment Variables

- `GEMINI_CLI`: Path to Gemini CLI executable (auto-detected by default)
- `BR_CLI`: Path to br CLI executable (default: `br`)
- `BR_URL` or `BRAINR_CORE_URL`: HTTP endpoint for core service
- `BRAINR_DEFAULT_MODE`: Set to `gemini` or `proxy` to override the default
- Standard API keys: `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, etc.

## Command Compatibility

`brainr` maintains full compatibility with `br` CLI commands:

```bash
# These are equivalent
br chat --model gemini-2.5-pro
brainr chat --model gemini-2.5-pro

# JSON output
br ask -p "test" --json
brainr ask -p "test" --json
```

## Architecture

```
User → brainr CLI → { --gemini → Official Gemini CLI (OAuth)
                    { --proxy  → br CLI (local) or HTTP API (remote)
```

This design ensures:
- Zero business logic duplication
- Perfect command compatibility
- Choose between free credits (Gemini) or full features (proxy)

## Development

```bash
# Clone and install
git clone https://github.com/brain-researcher/brain-researcher.git
cd brain-researcher/packages/cli
npm install

# Build
npm run build

# Link for local testing
npm link
```

## License

Apache-2.0
