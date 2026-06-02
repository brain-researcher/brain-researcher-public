from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


def default_session_id(cwd: Path | None = None) -> str:
    """Generate a stable session id based on the current working directory."""
    cwd = cwd or Path.cwd()
    resolved = cwd.resolve()
    home = Path.home()
    try:
        resolved = Path("~") / resolved.relative_to(home)
    except ValueError:  # cwd not under home
        pass
    raw = str(resolved).replace(os.sep, "-").replace(" ", "-")
    return (
        "".join(ch for ch in raw if ch.isalnum() or ch in "-_.").strip("-_.")
        or "session"
    )


@dataclass
class ConversationStore:
    session_id: str
    root: Path = Path.home() / ".brainr" / "sessions"
    messages: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path = self.root / f"{self.session_id}.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self) -> None:
        """Load previous messages if they exist."""
        if not self.path.exists():
            self.messages = []
            return
        with self.path.open("r", encoding="utf-8") as fh:
            self.messages = [json.loads(line) for line in fh]

    def append(self, message: Dict[str, Any]) -> None:
        """Append a message and persist it."""

        def _jsonable(obj: Any) -> Any:
            if obj is None or isinstance(obj, (str, int, float, bool)):
                return obj
            if isinstance(obj, dict):
                return {k: _jsonable(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple, set)):
                return [_jsonable(v) for v in obj]
            if hasattr(obj, "model_dump"):
                try:
                    return _jsonable(obj.model_dump())
                except Exception:
                    pass
            if hasattr(obj, "__dict__"):
                return _jsonable(obj.__dict__)
            return str(obj)

        safe_message = _jsonable(message)
        self.messages.append(safe_message)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(safe_message, ensure_ascii=False) + "\n")

    def clear(self) -> None:
        """Remove session history."""
        self.messages = []
        if self.path.exists():
            self.path.unlink(missing_ok=True)
