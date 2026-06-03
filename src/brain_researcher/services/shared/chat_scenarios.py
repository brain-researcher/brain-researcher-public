"""Shared chat scenario definitions for orchestrator and agent services."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PlannerHints:
    """Hints for downstream planners/tool selection."""

    pipeline_kind: str | None = None
    runtime_kind: str | None = None
    tool_allowlist: list[str] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.pipeline_kind:
            payload["pipeline_kind"] = self.pipeline_kind
        if self.runtime_kind:
            payload["runtime_kind"] = self.runtime_kind
        if self.tool_allowlist:
            payload["tool_allowlist"] = list(self.tool_allowlist)
        return payload


@dataclass(frozen=True)
class ChatScenario:
    """Chat scenario definition loaded from config."""

    id: str
    title: str
    description: str
    system_prompt: str
    starter_user_message: str
    planner_hints: PlannerHints | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "starter_user_message": self.starter_user_message,
        }
        if self.planner_hints:
            payload["planner_hints"] = self.planner_hints.to_payload()
        return payload


def _config_path() -> Path:
    default_root = Path(__file__).resolve().parents[3]
    repo_root = Path(os.environ.get("BRAIN_RESEARCHER_ROOT", default_root))
    return Path(
        os.environ.get(
            "CHAT_SCENARIO_CONFIG", repo_root / "configs" / "chat_scenarios.json"
        )
    )


@lru_cache(maxsize=1)
def _load_raw_scenarios() -> dict[str, dict[str, Any]]:
    config_file = _config_path()
    if not config_file.exists():
        return {}
    with config_file.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {}
    return data


def _build_scenario(key: str, raw: dict[str, Any]) -> ChatScenario:
    planner_raw = raw.get("planner_hints") or {}
    planner = None
    if isinstance(planner_raw, dict) and any(planner_raw.values()):
        planner = PlannerHints(
            pipeline_kind=planner_raw.get("pipeline_kind"),
            runtime_kind=planner_raw.get("runtime_kind"),
            tool_allowlist=planner_raw.get("tool_allowlist"),
        )

    return ChatScenario(
        id=key,
        title=raw.get("title", key),
        description=raw.get("description", ""),
        system_prompt=raw.get("system_prompt", ""),
        starter_user_message=raw.get("starter_user_message", ""),
        planner_hints=planner,
    )


@lru_cache(maxsize=1)
def get_chat_scenarios() -> dict[str, ChatScenario]:
    raw_map = _load_raw_scenarios()
    scenarios: dict[str, ChatScenario] = {}
    for key, raw in raw_map.items():
        if isinstance(raw, dict):
            scenarios[key] = _build_scenario(key, raw)
    return scenarios


def get_chat_scenario(scenario_id: str | None) -> ChatScenario | None:
    if not scenario_id:
        return None
    return get_chat_scenarios().get(scenario_id)


def get_chat_scenario_payload(scenario_id: str | None) -> dict[str, Any] | None:
    scenario = get_chat_scenario(scenario_id)
    if not scenario:
        return None
    return scenario.to_payload()
