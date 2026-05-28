"""Local MCP (Model Context Protocol) server for Brain Researcher.

This package exposes Brain Researcher as a stdio MCP server so external coding
agents (Claude Code / Codex CLI / Gemini CLI) can call deterministic tools for:
- tool discovery (ToolSpec)
- plan validation + execution (sandboxed run store)
- artifact listing + reading
- KG read-only queries (optional)

The server is designed to be started via:
    python -m brain_researcher.services.mcp.server
"""

