"""Shared test helpers for planner unit tests.

This module provides mock dataclasses used across multiple planner test files
to avoid duplication and ensure consistency.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MockContainer:
    """Mock container specification for runtime configuration.

    Used to test tools that run in container environments (Docker, Singularity, etc).

    Attributes:
        image: Container image reference (e.g., "fsl:6.0.7", "neurodesk/fsl:latest")
    """
    image: str


@dataclass(frozen=True)
class MockPython:
    """Mock Python runtime specification.

    Used to test tools that run as Python modules or scripts.

    Attributes:
        module: Python module path (e.g., "nilearn.glm", "brain_researcher.analysis")
    """
    module: str


@dataclass(frozen=True)
class MockMetadata:
    """Mock metadata structure for historical quality scoring.

    Used to test the historical_quality scoring factor which evaluates
    tool documentation, citations, and external references.

    Attributes:
        literature: Tuple of literature references (DOIs, PubMed IDs, etc)
        urls: Tuple of documentation URLs
    """
    literature: tuple = ()
    urls: tuple = ()


@dataclass(frozen=True)
class MockResources:
    """Mock resource specification for latency prediction.

    Used to test the latency_pred scoring factor which evaluates
    expected tool execution time.

    Attributes:
        time_min_default: Expected execution time in minutes (None = unknown)
        gpu: GPU requirement specification (for GPU constraint tests)
    """
    time_min_default: Optional[float] = None
    gpu: Optional[str] = None


@dataclass(frozen=True)
class MockToolCapability:
    """Mock tool capability for comprehensive selection testing.

    This is the primary mock used across all planner tests. It provides
    a lightweight, hashable (frozen) alternative to the real ToolCapability
    Pydantic model for unit testing.

    Attributes:
        id: Unique tool identifier (e.g., "fsl.bet.run", "nilearn.glm")
        name: Human-readable tool name
        description: Tool description for relevance scoring
        capabilities: Tuple of capability tags (e.g., ("skull_strip", "brain_extraction"))
        runtime_kind: Runtime type ("python", "container", "shell")
        documentation: Optional documentation string for metadata scoring
        metadata: Optional MockMetadata instance for historical quality tests
        container: Optional MockContainer for container-based tools
        python: Optional MockPython for Python-based tools
        resources: Optional MockResources for latency/GPU constraint tests
        source: Optional source identifier (e.g., "niwrap", "bids_apps")

    Example:
        >>> tool = MockToolCapability(
        ...     id="fsl.bet.run",
        ...     name="FSL BET",
        ...     description="Brain Extraction Tool",
        ...     capabilities=("skull_strip",),
        ...     runtime_kind="container",
        ...     container=MockContainer(image="fsl:6.0.7"),
        ...     resources=MockResources(time_min_default=2.5)
        ... )
    """
    id: str
    name: str
    description: str
    capabilities: tuple  # Use tuple instead of List for frozen dataclass
    runtime_kind: str
    documentation: Optional[str] = None
    metadata: Optional[object] = None
    container: Optional[MockContainer] = None
    python: Optional[MockPython] = None
    resources: Optional[object] = None
    source: Optional[str] = None
