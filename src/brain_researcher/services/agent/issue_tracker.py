"""External issue tracker backends for plan logging.

The core agent flow should not depend on any single vendor integration.
This module provides a provider-neutral interface plus a Linear backend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Callable
from typing import Any, Protocol

from brain_researcher.services.agent.mcp_caller import create_linear_mcp_caller

logger = logging.getLogger(__name__)


PII_PATTERNS = [
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL]"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]"),
    (r"\b(?:sub|subject)[-_]?\d+\b", "[SUBJECT_ID]", re.IGNORECASE),
    (r"\b(?:ses|session)[-_]?\d+\b", "[SESSION_ID]", re.IGNORECASE),
    (r"/home/[a-zA-Z0-9_]+/", "/home/[USER]/"),
    (r"/Users/[a-zA-Z0-9_]+/", "/Users/[USER]/"),
    (r"C:\\Users\\[a-zA-Z0-9_]+\\", "[WIN_USER_PATH]"),
]


def redact_pii(text: str) -> str:
    """Best-effort PII redaction for outbound tracker content."""
    if os.getenv("BR_PLAN_LOG_DISABLE_REDACTION", "").lower() == "true":
        return text

    out = text
    for pattern_tuple in PII_PATTERNS:
        if len(pattern_tuple) == 3:
            pattern, replacement, flags = pattern_tuple
            out = re.sub(pattern, replacement, out, flags=flags)
        else:
            pattern, replacement = pattern_tuple
            out = re.sub(pattern, replacement, out)
    return out


def _resolve_env(new_key: str, legacy_key: str) -> tuple[str | None, bool]:
    """Resolve env with one-release compatibility."""
    new_val = os.getenv(new_key)
    if new_val:
        return new_val, False

    legacy_val = os.getenv(legacy_key)
    if legacy_val:
        logger.info("Using deprecated env var %s; migrate to %s.", legacy_key, new_key)
        return legacy_val, True

    return None, False


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


class IssueTrackerBackend(Protocol):
    """Provider-neutral issue tracker contract."""

    provider: str

    @property
    def available(self) -> bool:
        """Whether backend is configured and callable."""

    async def create_issue(
        self,
        plan_id: str,
        title: str,
        description: str,
        state: Any,
    ) -> str | None:
        """Create an issue and return provider issue id."""

    async def update_issue_state(
        self,
        issue_id: str,
        state: Any,
        comment: str | None = None,
    ) -> bool:
        """Update issue state and optionally add comment."""


class LinearIssueTrackerBackend:
    """Linear MCP-backed tracker backend."""

    provider = "linear"
    DEFAULT_TIMEOUT = 5.0

    def __init__(
        self,
        mcp_caller: Callable | None = None,
        team_id: str | None = None,
        project_id: str | None = None,
        labels: list[str] | None = None,
    ) -> None:
        team_env, _ = _resolve_env("BR_PLAN_TRACKER_LINEAR_TEAM_ID", "LINEAR_TEAM_ID")
        project_env, _ = _resolve_env(
            "BR_PLAN_TRACKER_LINEAR_PROJECT_ID", "LINEAR_PROJECT_ID"
        )
        labels_env, _ = _resolve_env("BR_PLAN_TRACKER_LINEAR_LABELS", "LINEAR_LABELS")

        self.mcp_caller = mcp_caller
        self.team_id = team_id or team_env
        self.project_id = project_id or project_env
        self.labels = labels if labels is not None else _parse_csv(labels_env)

        state_backlog, _ = _resolve_env(
            "BR_PLAN_TRACKER_LINEAR_STATE_BACKLOG", "LINEAR_STATE_BACKLOG"
        )
        state_in_progress, _ = _resolve_env(
            "BR_PLAN_TRACKER_LINEAR_STATE_IN_PROGRESS", "LINEAR_STATE_IN_PROGRESS"
        )
        state_done, _ = _resolve_env(
            "BR_PLAN_TRACKER_LINEAR_STATE_DONE", "LINEAR_STATE_DONE"
        )
        state_cancelled, _ = _resolve_env(
            "BR_PLAN_TRACKER_LINEAR_STATE_CANCELLED", "LINEAR_STATE_CANCELLED"
        )

        self.state_mapping = {
            "backlog": state_backlog or "Backlog",
            "in_progress": state_in_progress or "In Progress",
            "done": state_done or "Done",
            "cancelled": state_cancelled or "Cancelled",
        }

        self._available: bool | None = None
        self._state_ids: dict[str, str] = {}

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = bool(self.mcp_caller and self.team_id)
            if self._available:
                logger.info("Issue tracker backend enabled: linear")
            else:
                logger.info("Linear tracker backend not configured")
        return self._available

    def _normalize_state(self, state: Any) -> str:
        value = getattr(state, "value", state)
        return str(value).lower().strip()

    async def _call_mcp(self, tool_name: str, params: dict[str, Any]) -> dict | None:
        if not self.mcp_caller:
            return None

        safe_params = {k: v for k, v in params.items() if v is not None}

        try:
            return await self.mcp_caller(tool_name, safe_params)
        except Exception as exc:
            logger.warning("MCP call %s failed: %s", tool_name, exc)
            return None

    async def _get_state_id(self, state_name: str) -> str | None:
        if state_name in self._state_ids:
            return self._state_ids[state_name]

        try:
            result = await self._call_mcp(
                "mcp__linear__get_team",
                {"teamId": self.team_id},
            )
            nodes = (
                result.get("team", {}).get("states", {}).get("nodes", [])
                if result
                else []
            )
            for state in nodes:
                name = state.get("name")
                state_id = state.get("id")
                if name and state_id:
                    self._state_ids[name] = state_id
        except Exception as exc:
            logger.warning("Failed to fetch Linear states: %s", exc)

        return self._state_ids.get(state_name)

    async def create_issue(
        self,
        plan_id: str,
        title: str,
        description: str,
        state: Any,
    ) -> str | None:
        del state  # Initial state for Linear is controlled by workflow config.

        if not self.available:
            return None

        safe_title = redact_pii(title)[:100]
        safe_description = redact_pii(description)

        try:
            result = await asyncio.wait_for(
                self._call_mcp(
                    "mcp__linear__create_issue",
                    {
                        "teamId": self.team_id,
                        "title": f"[Plan] {safe_title}",
                        "description": safe_description,
                        "projectId": self.project_id,
                        "labelNames": self.labels if self.labels else None,
                    },
                ),
                timeout=self.DEFAULT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("Linear create_issue timed out for plan %s", plan_id)
            return None
        except Exception as exc:
            logger.warning("Linear create_issue failed for %s: %s", plan_id, exc)
            return None

        if not result or not result.get("success"):
            error = result.get("error") if result else "unknown"
            logger.warning("Failed to create Linear issue for %s: %s", plan_id, error)
            return None

        issue_id = result.get("issue", {}).get("id")
        if issue_id:
            logger.info("Created linear issue %s for plan %s", issue_id, plan_id)
        return issue_id

    async def update_issue_state(
        self,
        issue_id: str,
        state: Any,
        comment: str | None = None,
    ) -> bool:
        if not self.available or not issue_id:
            return False

        state_key = self._normalize_state(state)
        state_name = self.state_mapping.get(state_key, self.state_mapping["backlog"])
        state_updated = False

        try:
            state_id = await self._get_state_id(state_name)
            if state_id:
                result = await asyncio.wait_for(
                    self._call_mcp(
                        "mcp__linear__update_issue",
                        {"issueId": issue_id, "stateId": state_id},
                    ),
                    timeout=self.DEFAULT_TIMEOUT,
                )
                state_updated = bool(result and result.get("success"))
                if not state_updated:
                    logger.warning(
                        "Failed to update linear issue state for %s: %s",
                        issue_id,
                        result.get("error") if result else "unknown",
                    )
            else:
                logger.warning("Could not resolve linear state id for %s", state_name)
        except asyncio.TimeoutError:
            logger.warning("Linear state update timed out for issue %s", issue_id)
        except Exception as exc:
            logger.warning("Linear state update failed for %s: %s", issue_id, exc)

        if comment:
            await self._add_comment(issue_id, comment)

        return state_updated

    async def _add_comment(self, issue_id: str, comment: str) -> bool:
        safe_comment = redact_pii(comment)
        try:
            result = await asyncio.wait_for(
                self._call_mcp(
                    "mcp__linear__add_comment",
                    {"issueId": issue_id, "body": safe_comment},
                ),
                timeout=self.DEFAULT_TIMEOUT,
            )
            return bool(result and result.get("success"))
        except Exception as exc:
            logger.debug("Failed to add linear comment for %s: %s", issue_id, exc)
            return False


def create_issue_tracker_backend(
    provider: str | None = None,
    mcp_caller: Callable | None = None,
) -> IssueTrackerBackend | None:
    """Create configured issue tracker backend.

    Env:
      - BR_PLAN_TRACKER_PROVIDER: auto|none|linear (default: auto)
    """
    selected = (
        (provider or os.getenv("BR_PLAN_TRACKER_PROVIDER", "auto")).strip().lower()
    )
    disabled_values = {"none", "off", "disabled", "false", "0"}

    if selected in disabled_values:
        return None

    if selected in {"auto", "linear"}:
        caller = mcp_caller or create_linear_mcp_caller()
        backend = LinearIssueTrackerBackend(mcp_caller=caller)
        if backend.available:
            return backend
        return None

    logger.warning(
        "Unknown tracker provider '%s'; external tracker disabled.", selected
    )
    return None
