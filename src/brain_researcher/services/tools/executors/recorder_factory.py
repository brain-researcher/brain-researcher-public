"""Factory for creating RunRecorder instances with dependency injection support.

This module provides the RecorderFactory abstraction following Codex's recommendation
for clean dependency injection and support for nested recorders in workflow executors.

Moved from: services/toolhub/common/recorder_factory.py
"""

from __future__ import annotations

from typing import Optional, Protocol

from brain_researcher.config.run_artifacts import (
    RecorderConfig,
    build_run_base_dir,
    get_recorder_config,
)
from brain_researcher.services.tools.executors.run_recorder import RunRecorder


class RecorderFactory(Protocol):
    """Protocol for creating RunRecorder instances.

    This enables dependency injection and makes executors testable by allowing
    mock factories to be injected during tests.
    """

    def create_recorder(
        self,
        run_id: str,
        resolver_mode: str,
        parent_run_id: Optional[str] = None,
        step_id: Optional[str] = None,
        attempt: Optional[int] = None,
    ) -> RunRecorder:
        """Create a new RunRecorder instance.

        Args:
            run_id: Unique run identifier
            resolver_mode: Container resolution mode (best_effort, pinned, etc.)
            parent_run_id: Parent run ID for nested recorders (optional)
            step_id: Step identifier within parent workflow (optional)

        Returns:
            Configured RunRecorder instance
        """
        ...

    def create_child_recorder(
        self,
        parent_run_id: str,
        step_id: str,
        resolver_mode: str,
    ) -> RunRecorder:
        """Create a child recorder for a workflow step.

        This is a convenience method that generates a child run_id and sets up
        the nested directory structure (parent_run_dir/steps/step_id/).

        Args:
            parent_run_id: Parent workflow's run ID
            step_id: Unique identifier for this step
            resolver_mode: Container resolution mode (inherited from parent)

        Returns:
            RunRecorder configured as a child of parent_run_id
        """
        ...


class DefaultRecorderFactory:
    """Default implementation of RecorderFactory.

    Uses the global RecorderConfig and creates recorders with proper
    parent/child relationships.
    """

    def __init__(self, config: Optional[RecorderConfig] = None):
        """Initialize factory.

        Args:
            config: Optional config override. If None, uses global config.
        """
        self.config = config or get_recorder_config()

    def create_recorder(
        self,
        run_id: str,
        resolver_mode: str,
        parent_run_id: Optional[str] = None,
        step_id: Optional[str] = None,
        attempt: Optional[int] = None,
    ) -> RunRecorder:
        """Create a new RunRecorder instance.

        Args:
            run_id: Unique run identifier
            resolver_mode: Container resolution mode
            parent_run_id: Parent run ID for nested recorders (optional)
            step_id: Step identifier within parent workflow (optional)
            attempt: Attempt number for re-runs (None auto-selects next available)

        Returns:
            Configured RunRecorder instance
        """
        # Determine attempt number and avoid clobbering existing runs
        chosen_attempt = attempt

        if parent_run_id:
            # Nested recorders inherit parent path; default attempt is 1
            if chosen_attempt is None:
                chosen_attempt = 1
        else:
            base_dir = build_run_base_dir(self.config.root, run_id)
            if chosen_attempt is None:
                chosen_attempt = 1
                if base_dir.exists():
                    attempt_index = 2
                    while (base_dir / f"attempt-{attempt_index}").exists():
                        attempt_index += 1
                    chosen_attempt = attempt_index

        if chosen_attempt is None:
            chosen_attempt = 1

        return RunRecorder(
            run_id=run_id,
            resolver_mode=resolver_mode,
            cfg=self.config,
            parent_run_id=parent_run_id,
            step_id=step_id,
            attempt=chosen_attempt,
        )

    def create_child_recorder(
        self,
        parent_run_id: str,
        step_id: str,
        resolver_mode: str,
    ) -> RunRecorder:
        """Create a child recorder for a workflow step.

        Generates child run_id as {parent_run_id}_{step_id} and sets up
        nested directory structure.

        Args:
            parent_run_id: Parent workflow's run directory relative to the day root
            step_id: Unique identifier for this step
            resolver_mode: Container resolution mode

        Returns:
            RunRecorder configured as a child of parent_run_id
        """
        child_run_id = f"{parent_run_id}_{step_id}"
        return self.create_recorder(
            run_id=child_run_id,
            resolver_mode=resolver_mode,
            parent_run_id=parent_run_id,
            step_id=step_id,
        )


def create_recorder_factory(config: Optional[RecorderConfig] = None) -> RecorderFactory:
    """Factory function for creating RecorderFactory instances.

    This follows the existing pattern in the codebase for component creation
    (similar to create_system_monitor, create_adaptive_scheduler, etc.).

    Args:
        config: Optional config override. If None, uses global config.

    Returns:
        DefaultRecorderFactory instance

    Example:
        >>> factory = create_recorder_factory()
        >>> recorder = factory.create_recorder("run123", "best_effort")
        >>> with recorder:
        ...     # Execute tool
        ...     pass
    """
    return DefaultRecorderFactory(config=config)
