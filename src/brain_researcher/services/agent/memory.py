"""Lightweight conversation memory for the chat orchestrator.

Persists short summaries of each exchange to markdown plus a machine readable
JSONL sidecar so that recent context can be reconstructed without relying on
LLM recall. This deliberately keeps the surface area tiny to avoid pulling in
an external vector store or MCP dependency.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    thread_id: str
    role: str
    content: str
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConversationMemory:
    """Append-only markdown + JSONL memory store.

    The markdown file is user-friendly; the JSONL file is the source of truth
    for programmatic reads. Both live under the same directory so they can be
    shipped with artifacts or inspected manually.
    """

    def __init__(
        self,
        store_path: Path | str = Path("data") / "agent_memory.md",
        max_entries_per_thread: int = 50,
    ) -> None:
        self.store_path = Path(store_path)
        self.json_path = self.store_path.with_suffix(".jsonl")
        self.max_entries_per_thread = max_entries_per_thread
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.store_path.exists():
            self.store_path.write_text("# Agent memory log\n\n", encoding="utf-8")
        if not self.json_path.exists():
            self.json_path.touch()
        self._cache: Dict[str, List[MemoryEntry]] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def append(
        self,
        thread_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        entry = MemoryEntry(
            thread_id=thread_id,
            role=role,
            content=content.strip(),
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        cache = self._load_cache()
        cache.setdefault(thread_id, []).append(entry)
        cache[thread_id] = cache[thread_id][-self.max_entries_per_thread :]
        self._persist(cache)
        return entry

    def get_recent(self, thread_id: str, limit: int = 5) -> List[MemoryEntry]:
        cache = self._load_cache()
        return list(cache.get(thread_id, [])[-limit:])

    def render_recent(self, thread_id: str, limit: int = 5) -> str:
        """Return a markdown snippet of recent turns."""

        entries = self.get_recent(thread_id, limit=limit)
        if not entries:
            return ""
        lines = ["## Recent memory"]
        for entry in entries:
            meta = f" meta={json.dumps(entry.metadata)}" if entry.metadata else ""
            lines.append(
                f"- [{entry.created_at}] ({entry.role}) {entry.content}{meta}"
            )
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _load_cache(self) -> Dict[str, List[MemoryEntry]]:
        if self._cache is not None:
            return self._cache

        cache: Dict[str, List[MemoryEntry]] = {}
        for line in self.json_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                entry = MemoryEntry(**raw)
                cache.setdefault(entry.thread_id, []).append(entry)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Skipping malformed memory line: %s", exc)
                continue
        self._cache = cache
        return cache

    def _persist(self, cache: Dict[str, List[MemoryEntry]]) -> None:
        lines: List[str] = []
        md_lines: List[str] = ["# Agent memory log", ""]
        for thread_id, entries in cache.items():
            md_lines.append(f"## Thread {thread_id}")
            for entry in entries:
                payload = entry.__dict__
                lines.append(json.dumps(payload, ensure_ascii=False))
                meta = (
                    f" meta={json.dumps(entry.metadata, ensure_ascii=False)}"
                    if entry.metadata
                    else ""
                )
                md_lines.append(
                    f"- [{entry.created_at}] ({entry.role}) {entry.content}{meta}"
                )
            md_lines.append("")

        self.json_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        self.store_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        self._cache = cache


__all__ = ["ConversationMemory", "MemoryEntry"]
