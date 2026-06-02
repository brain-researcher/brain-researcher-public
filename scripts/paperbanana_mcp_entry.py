"""
Entry-point wrapper for the PaperBanana MCP server.

Why this exists:
- PaperBanana sometimes returns VLM-generated matplotlib code with an opening code fence
  (```python) but without a closing fence. Upstream VisualizerAgent._extract_code used
  str.index() and would crash with ValueError("substring not found"), causing flaky MCP calls.

This wrapper monkey-patches _extract_code to be robust to missing closing fences, and keeps
logging on stderr so stdout stays clean for JSON-RPC over stdio.
"""

from __future__ import annotations

import sys

import structlog


def _patch_paperbanana_extract_code() -> None:
    try:
        from paperbanana.agents.visualizer import VisualizerAgent
    except Exception:
        # If imports change upstream, fail open: the MCP server may still work.
        return

    def _extract_code(self, response: str) -> str:  # type: ignore[override]
        # Match upstream behavior but never raise if the closing fence is missing.
        if "```python" in response:
            start = response.find("```python")
            if start == -1:
                return response.strip()
            start += len("```python")
            end = response.find("```", start)
            if end == -1:
                end = len(response)
            return response[start:end].strip()
        if "```" in response:
            start = response.find("```")
            if start == -1:
                return response.strip()
            start += 3
            end = response.find("```", start)
            if end == -1:
                end = len(response)
            return response[start:end].strip()
        return response.strip()

    VisualizerAgent._extract_code = _extract_code  # type: ignore[assignment]
    print("[paperbanana_mcp_entry] Patched VisualizerAgent._extract_code to be fence-robust.", file=sys.stderr)


def main() -> None:
    # Keep structlog on stderr so MCP stdio JSON is not polluted.
    print("[paperbanana_mcp_entry] starting PaperBanana MCP wrapper.", file=sys.stderr)
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    _patch_paperbanana_extract_code()

    import mcp_server.server as s

    s.main()


if __name__ == "__main__":
    main()
