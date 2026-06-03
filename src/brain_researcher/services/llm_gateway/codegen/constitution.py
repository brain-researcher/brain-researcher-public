"""Codegen constitution loader and prompt formatter."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_CONSTITUTION_PATH = REPO_ROOT / "configs" / "codegen" / "constitution.yaml"


@lru_cache(maxsize=4)
def _load_constitution_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"missing codegen constitution: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid constitution payload: {path}")
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        raise RuntimeError(f"constitution must define non-empty sections: {path}")
    return data


def load_codegen_constitution(path: str | Path | None = None) -> dict[str, Any]:
    """Return the configured codegen constitution payload."""

    resolved = Path(path or DEFAULT_CONSTITUTION_PATH).resolve()
    return _load_constitution_cached(str(resolved))


def format_codegen_constitution_for_prompt(
    constitution: dict[str, Any] | None = None,
) -> str:
    """Render the constitution into a prompt-friendly markdown block."""

    payload = constitution or load_codegen_constitution()
    title = str(payload.get("title") or "Codegen Constitution").strip()
    summary = str(payload.get("summary") or "").strip()
    sections = payload.get("sections")
    lines: list[str] = []
    if summary:
        lines.append(summary)
        lines.append("")
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_title = str(section.get("title") or "").strip()
            if section_title:
                lines.append(f"### {section_title}")
            instructions = section.get("instructions")
            if isinstance(instructions, list):
                for item in instructions:
                    text = str(item or "").strip()
                    if text:
                        lines.append(f"- {text}")
            lines.append("")
    body = "\n".join(lines).strip()
    if not body:
        raise RuntimeError(f"{title} rendered to empty prompt text")
    return body
