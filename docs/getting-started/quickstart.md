# Quick Start

Get up and running with Brain Researcher in minutes!

If you opened this file from an exported analysis bundle, start from the files in
`.bundle_support/`:

- `docker-compose.yml`: primary launch path for BR end users
- `.env.example`: copy to `.env` and fill in required keys
- `quickstart.md`: this file
- `installation.md`: fuller setup and troubleshooting
- `environment.yml`: fallback only if you cannot use Docker

For most users, use the Docker path rather than the Conda path.

## 1. Basic Setup

After [installation](installation.md), initialize the system:

```bash
# Initialize database
brain-researcher db init

# Start services (optional, for API access)
brain-researcher serve kg &     # BR-KG on port 5000 (requires Neo4j)
brain-researcher serve agent &  # Agent on port 8000
brain-researcher serve web &    # Web UI (Next.js) on port 3000
```

## 2. Interactive Chat

The easiest way to use Brain Researcher is through the interactive chat:

```bash
brain-researcher chat
```

Example interactions:

```
You: Load the Neurovault collection 8836 and show me the brain regions with highest activation
