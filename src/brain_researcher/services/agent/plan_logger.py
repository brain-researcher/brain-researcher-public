"""Plan logger with optional external issue tracker integration."""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from brain_researcher.services.agent.issue_tracker import (
    IssueTrackerBackend,
    LinearIssueTrackerBackend,
    create_issue_tracker_backend,
)

logger = logging.getLogger(__name__)


class PlanState(str, Enum):
    """Plan execution state workflow."""
    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


# Map outcome to state
OUTCOME_TO_STATE = {
    "pending": PlanState.BACKLOG,
    "running": PlanState.IN_PROGRESS,
    "succeeded": PlanState.DONE,
    "failed": PlanState.CANCELLED,
    "cancelled": PlanState.CANCELLED,
}

# State display info
STATE_INFO = {
    PlanState.BACKLOG: {"emoji": "\u23f3", "label": "Backlog"},      # hourglass
    PlanState.IN_PROGRESS: {"emoji": "\u25b6\ufe0f", "label": "In Progress"},  # play
    PlanState.DONE: {"emoji": "\u2705", "label": "Done"},            # checkmark
    PlanState.CANCELLED: {"emoji": "\u274c", "label": "Cancelled"},  # X mark
}


# PII patterns to redact
PII_PATTERNS = [
    # Email addresses
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
    # SSN-like patterns
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),
    # Subject/participant IDs (common in neuroimaging)
    (r'\b(?:sub|subject)[-_]?\d+\b', '[SUBJECT_ID]', re.IGNORECASE),
    # Session IDs
    (r'\b(?:ses|session)[-_]?\d+\b', '[SESSION_ID]', re.IGNORECASE),
    # Home directory paths (Unix)
    (r'/home/[a-zA-Z0-9_]+/', '/home/[USER]/'),
    (r'/Users/[a-zA-Z0-9_]+/', '/Users/[USER]/'),
    # Windows user paths
    (r'C:\\Users\\[a-zA-Z0-9_]+\\', '[WIN_USER_PATH]'),
]


def redact_pii(text: str, enable: bool = True) -> str:
    """
    Redact PII from text.

    Args:
        text: Text to redact
        enable: Whether to apply redaction

    Returns:
        Redacted text
    """
    if not enable:
        return text

    if os.getenv("BR_PLAN_LOG_DISABLE_REDACTION", "").lower() == "true":
        return text

    for pattern_tuple in PII_PATTERNS:
        if len(pattern_tuple) == 3:
            pattern, replacement, flags = pattern_tuple
            text = re.sub(pattern, replacement, text, flags=flags)
        else:
            pattern, replacement = pattern_tuple
            text = re.sub(pattern, replacement, text)

    return text


# Backward-compatible alias for callers importing LinearIntegration.
LinearIntegration = LinearIssueTrackerBackend


class PlanLogger:
    """
    Logs execution plans to markdown files and optionally an external tracker.

    Features:
    - Human-readable markdown format with state workflow
    - External issue tracker integration (when available)
    - Date-organized directory structure
    - PII redaction on all outputs
    - Non-blocking operations with event loop safety
    """

    def __init__(
        self,
        log_dir: Optional[str] = None,
        issue_tracker: Optional[IssueTrackerBackend] = None,
        plan_memory: Optional[Any] = None,
    ):
        """
        Initialize the plan logger.

        Args:
            log_dir: Directory for plan logs (defaults to logs/plans)
            issue_tracker: Optional external issue tracker backend
            plan_memory: Optional PlanMemory instance for issue ID persistence
        """
        if log_dir is None:
            log_dir = os.getenv("BR_PLAN_LOG_DIR", "logs/plans")

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.issue_tracker = issue_tracker
        self.plan_memory = plan_memory

        # Track plan -> external issue mapping (cache + DB fallback)
        self._issue_refs: Dict[str, Dict[str, str]] = {}

        logger.info(f"PlanLogger initialized: {self.log_dir}")

    def _fire_and_forget_async(self, coro, description: str = "async task"):
        """
        Run async coroutine safely from sync context.

        Handles the case where no event loop is running by falling back
        to a daemon thread with a timeout.

        Args:
            coro: Coroutine to execute
            description: Description for logging
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # No running event loop - use thread-based approach
            logger.info(f"No running event loop, falling back to thread for: {description}")
            import threading

            def _run():
                try:
                    asyncio.run(asyncio.wait_for(coro, timeout=5.0))
                except asyncio.TimeoutError:
                    logger.warning(f"Background task timed out: {description}")
                except Exception as e:
                    logger.warning(f"Background task failed ({description}): {e}")

            threading.Thread(target=_run, daemon=True).start()

    def _get_issue_ref(self, plan_id: str) -> Optional[Dict[str, str]]:
        """
        Get tracker issue reference for a plan, checking DB first then cache.

        Args:
            plan_id: Plan identifier

        Returns:
            {"provider": str, "issue_id": str} if found, None otherwise
        """
        # Try plan_memory DB first (survives restart)
        if self.plan_memory:
            try:
                db_ref = self.plan_memory.get_tracker_issue(plan_id)
                if db_ref and db_ref.get("issue_id"):
                    # Update cache for faster subsequent lookups
                    self._issue_refs[plan_id] = db_ref
                    return db_ref
            except Exception as e:
                logger.debug(f"Could not get issue ref from plan_memory: {e}")

        # Fall back to in-memory cache
        return self._issue_refs.get(plan_id)

    def log_plan(
        self,
        plan: Dict[str, Any],
        user_id: str,
        workspace_id: Optional[str] = None,
        plan_memory_id: Optional[str] = None,
        source_plan_id: Optional[str] = None,
    ) -> str:
        """
        Log a plan to markdown (sync) and optionally tracker (async fire-and-forget).

        Args:
            plan: Plan dictionary with steps
            user_id: User who created the plan
            workspace_id: Optional workspace context
            plan_memory_id: ID from plan memory
            source_plan_id: ID of source plan if adapted

        Returns:
            Path to the created markdown file
        """
        plan_id = plan.get("plan_id", f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        timestamp = datetime.now()
        query = plan.get("query", "N/A")

        # Generate and write markdown (sync - always succeeds)
        md_content = self._generate_markdown(
            plan=plan,
            plan_id=plan_id,
            user_id=user_id,
            workspace_id=workspace_id,
            timestamp=timestamp,
            source_plan_id=source_plan_id,
            plan_memory_id=plan_memory_id,
            state=PlanState.BACKLOG,
        )

        # Apply PII redaction
        md_content = redact_pii(md_content)

        # Write file
        date_dir = self.log_dir / timestamp.strftime("%Y-%m-%d")
        date_dir.mkdir(exist_ok=True)
        filepath = date_dir / f"{plan_id}.md"
        filepath.write_text(md_content, encoding="utf-8")

        logger.info(f"Plan logged to: {filepath}")

        # Fire-and-forget external issue creation (event-loop safe)
        if self.issue_tracker and self.issue_tracker.available:
            description = self._build_issue_description(plan, user_id, workspace_id)
            tracker_name = getattr(self.issue_tracker, "provider", "tracker")
            self._fire_and_forget_async(
                self._create_issue_safe(plan_id, query, description, plan_memory_id),
                description=f"{tracker_name} issue creation for {plan_id}",
            )

        return str(filepath)

    async def _create_issue_safe(
        self,
        plan_id: str,
        title: str,
        description: str,
        plan_memory_id: Optional[str] = None,
    ):
        """Create external issue with error handling (fire-and-forget)."""
        if not self.issue_tracker:
            return

        try:
            issue_id = await self.issue_tracker.create_issue(
                plan_id=plan_id,
                title=title[:100],
                description=description,
                state=PlanState.BACKLOG,
            )
            if issue_id:
                provider = getattr(self.issue_tracker, "provider", "unknown")
                issue_ref = {"provider": provider, "issue_id": issue_id}

                # Store in cache
                self._issue_refs[plan_id] = issue_ref

                # Persist to plan_memory DB if available (survives restart)
                if self.plan_memory and plan_memory_id:
                    try:
                        self.plan_memory.update_tracker_issue(
                            plan_id=plan_memory_id,
                            provider=provider,
                            issue_id=issue_id,
                        )
                        logger.debug(
                            "Persisted tracker issue %s/%s for plan %s",
                            provider,
                            issue_id,
                            plan_memory_id,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to persist tracker issue: {e}")
        except Exception as e:
            logger.warning(f"Tracker issue creation failed for {plan_id}: {e}")

    def _build_issue_description(
        self,
        plan: Dict[str, Any],
        user_id: str,
        workspace_id: Optional[str],
    ) -> str:
        """Build tracker issue description with PII redaction."""
        steps = plan.get("steps", [])
        query = plan.get("query", "N/A")

        lines = [
            f"**Query**: {redact_pii(query)}",
            f"**User**: {redact_pii(user_id)}",
            f"**Workspace**: {redact_pii(workspace_id) if workspace_id else 'N/A'}",
            "",
            f"**Steps** ({len(steps)} total):",
        ]

        for i, step in enumerate(steps, 1):
            tool = step.get("tool_name") or step.get("tool", "unknown")
            desc = redact_pii(step.get("description", "")[:50])
            lines.append(f"{i}. `{tool}` - {desc}")

        return "\n".join(lines)

    def update_state(
        self,
        plan_id: str,
        state: PlanState,
        execution_time_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ):
        """
        Update plan state in markdown and tracker.

        Args:
            plan_id: Plan ID
            state: New state
            execution_time_ms: Execution time (for done/cancelled)
            error_message: Error message if failed
        """
        # Update markdown (sync)
        self._update_markdown_state(plan_id, state, execution_time_ms, error_message)

        # Update tracker (async fire-and-forget, event-loop safe)
        issue_ref = self._get_issue_ref(plan_id)  # Check DB first, then cache
        if self.issue_tracker and issue_ref and issue_ref.get("issue_id"):
            provider = issue_ref.get("provider")
            issue_id = issue_ref["issue_id"]

            if provider and provider != getattr(self.issue_tracker, "provider", provider):
                logger.debug(
                    "Skipping tracker state update for plan %s: provider mismatch (%s != %s)",
                    plan_id,
                    provider,
                    getattr(self.issue_tracker, "provider", "unknown"),
                )
                return

            comment = None
            if state == PlanState.DONE:
                comment = f"Execution completed in {execution_time_ms}ms" if execution_time_ms else "Execution completed"
            elif state == PlanState.CANCELLED and error_message:
                comment = f"Execution failed: {error_message}"

            self._fire_and_forget_async(
                self._update_issue_state_safe(issue_id, state, comment),
                description=f"Tracker state update for {plan_id}",
            )

    async def _update_issue_state_safe(
        self,
        issue_id: str,
        state: PlanState,
        comment: Optional[str],
    ):
        """Update tracker issue state with error handling."""
        if not self.issue_tracker:
            return

        try:
            await self.issue_tracker.update_issue_state(issue_id, state, comment)
        except Exception as e:
            logger.warning(f"Tracker state update failed for {issue_id}: {e}")

    def update_outcome(
        self,
        plan_id: str,
        outcome: str,
        execution_time_ms: int,
        error_message: Optional[str] = None,
    ):
        """
        Update plan outcome (legacy interface).

        Args:
            plan_id: Plan ID
            outcome: Execution outcome (succeeded/failed/cancelled)
            execution_time_ms: Total execution time
            error_message: Error message if failed
        """
        state = OUTCOME_TO_STATE.get(outcome, PlanState.CANCELLED)
        self.update_state(plan_id, state, execution_time_ms, error_message)

    def _update_markdown_state(
        self,
        plan_id: str,
        state: PlanState,
        execution_time_ms: Optional[int],
        error_message: Optional[str],
    ):
        """Update markdown file with new state."""
        filepath = self._find_plan_file(plan_id)
        if not filepath:
            logger.warning(f"Could not find markdown file for plan {plan_id}")
            return

        content = filepath.read_text(encoding="utf-8")
        updated_content = self._update_markdown_outcome_section(
            content, state, execution_time_ms, error_message
        )
        filepath.write_text(updated_content, encoding="utf-8")

        logger.info(f"Updated plan {plan_id} state to: {state.value}")

    def _generate_markdown(
        self,
        plan: Dict[str, Any],
        plan_id: str,
        user_id: str,
        workspace_id: Optional[str],
        timestamp: datetime,
        source_plan_id: Optional[str],
        plan_memory_id: Optional[str],
        state: PlanState,
    ) -> str:
        """Generate human-readable markdown for a plan with state workflow."""
        steps = plan.get("steps", [])
        query = plan.get("query", "N/A")
        source = plan.get("source", "generated")
        state_info = STATE_INFO[state]

        lines = [
            f"# Execution Plan: {plan_id}",
            "",
            f"**State**: {state_info['emoji']} `{state_info['label']}`",
            f"**Created**: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**User**: {user_id}",
            f"**Workspace**: {workspace_id or 'N/A'}",
            f"**Source**: {source}",
        ]

        if source_plan_id:
            lines.append(f"**Adapted From**: {source_plan_id}")

        if plan_memory_id:
            lines.append(f"**Memory ID**: {plan_memory_id}")

        lines.extend([
            "",
            "---",
            "",
            "## Query",
            "",
            f"> {query}",
            "",
            "---",
            "",
            "## Execution Steps",
            "",
        ])

        for i, step in enumerate(steps, 1):
            step_id = step.get("step_id") or step.get("id") or f"step_{i}"
            tool_name = step.get("tool_name") or step.get("tool", "unknown")
            description = step.get("description", "")
            tool_args = step.get("tool_args") or step.get("args", {})

            lines.extend([
                f"### Step {i}: {tool_name}",
                "",
                f"**ID**: `{step_id}`",
            ])

            if description:
                lines.append(f"**Description**: {description}")

            lines.extend([
                "",
                "**Arguments**:",
                "```json",
                json.dumps(tool_args, indent=2, default=str),
                "```",
                "",
            ])

            deps = step.get("dependencies", [])
            if deps:
                lines.append(f"**Depends on**: {', '.join(str(d) for d in deps)}")
                lines.append("")

            expected = step.get("expected_output", "")
            if expected:
                lines.append(f"**Expected Output**: {expected}")
                lines.append("")

        # Execution outcome section
        lines.extend([
            "---",
            "",
            "## Execution Outcome",
            "",
            f"**Status**: {state_info['emoji']} `{state_info['label']}`",
            "",
        ])

        if state == PlanState.BACKLOG:
            lines.append("_Waiting for execution to start._")
        elif state == PlanState.IN_PROGRESS:
            lines.append("_Execution in progress..._")

        lines.append("")

        # Objectives
        objectives = plan.get("objectives", [])
        if objectives:
            lines.extend(["---", "", "## Objectives", ""])
            for obj in objectives:
                lines.append(f"- {obj}")
            lines.append("")

        # Success criteria
        criteria = plan.get("success_criteria", [])
        if criteria:
            lines.extend(["---", "", "## Success Criteria", ""])
            for crit in criteria:
                lines.append(f"- {crit}")
            lines.append("")

        # Metadata
        tools_used = list(set(
            step.get("tool_name") or step.get("tool", "unknown")
            for step in steps
        ))

        metadata = {
            "plan_id": plan_id,
            "step_count": len(steps),
            "tools_used": tools_used,
            "estimated_time_ms": plan.get("total_estimated_time"),
            "confidence_score": plan.get("confidence_score"),
        }

        lines.extend([
            "---",
            "",
            "## Metadata",
            "",
            "```json",
            json.dumps(metadata, indent=2),
            "```",
        ])

        return "\n".join(lines)

    def _update_markdown_outcome_section(
        self,
        content: str,
        state: PlanState,
        execution_time_ms: Optional[int],
        error_message: Optional[str],
    ) -> str:
        """Update the outcome section in markdown content."""
        state_info = STATE_INFO[state]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        new_outcome_lines = [
            "## Execution Outcome",
            "",
            f"**Status**: {state_info['emoji']} `{state_info['label']}`",
        ]

        if state in (PlanState.DONE, PlanState.CANCELLED):
            new_outcome_lines.append(f"**Completed**: {timestamp}")
            if execution_time_ms is not None:
                new_outcome_lines.append(
                    f"**Execution Time**: {execution_time_ms}ms ({execution_time_ms/1000:.2f}s)"
                )

        if error_message:
            # Redact PII from error message
            safe_error = redact_pii(error_message)
            new_outcome_lines.extend([
                "",
                "**Error**:",
                "```",
                safe_error,
                "```",
            ])

        new_outcome_lines.append("")

        new_outcome = "\n".join(new_outcome_lines)

        # Also update the State in the header
        content = re.sub(
            r'\*\*State\*\*: [^\n]+',
            f"**State**: {state_info['emoji']} `{state_info['label']}`",
            content
        )

        # Replace the outcome section
        pattern = r"## Execution Outcome\n\n.*?(?=\n---|\Z)"
        return re.sub(pattern, new_outcome, content, flags=re.DOTALL)

    def _find_plan_file(self, plan_id: str) -> Optional[Path]:
        """Find the markdown file for a plan ID."""
        try:
            date_dirs = sorted(self.log_dir.iterdir(), reverse=True)
            for date_dir in date_dirs:
                if date_dir.is_dir():
                    filepath = date_dir / f"{plan_id}.md"
                    if filepath.exists():
                        return filepath
        except Exception as e:
            logger.warning(f"Error searching for plan file: {e}")
        return None

    def get_recent_plans(self, days: int = 7, limit: int = 50) -> list:
        """Get list of recent plan files."""
        plans = []
        try:
            date_dirs = sorted(self.log_dir.iterdir(), reverse=True)
            for date_dir in date_dirs[:days]:
                if date_dir.is_dir():
                    for filepath in sorted(date_dir.glob("*.md"), reverse=True):
                        plans.append(str(filepath))
                        if len(plans) >= limit:
                            return plans
        except Exception as e:
            logger.warning(f"Error getting recent plans: {e}")
        return plans


def create_plan_logger(
    log_dir: Optional[str] = None,
    issue_tracker: Optional[IssueTrackerBackend] = None,
    mcp_caller: Optional[Callable] = None,
    plan_memory: Optional[Any] = None,
) -> PlanLogger:
    """
    Factory function to create a PlanLogger instance.

    Args:
        log_dir: Optional log directory path
        issue_tracker: Optional tracker backend
        mcp_caller: Optional MCP caller function (deprecated compatibility path)
        plan_memory: Optional PlanMemory instance for issue ID persistence

    Returns:
        Configured PlanLogger instance
    """
    tracker = issue_tracker
    if tracker is None:
        tracker = create_issue_tracker_backend(mcp_caller=mcp_caller)

    return PlanLogger(log_dir=log_dir, issue_tracker=tracker, plan_memory=plan_memory)
