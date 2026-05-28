"""Intent and Operation data classes.

These are runtime-agnostic descriptors of *what* the user wants to do
(Intent) and a concrete planned step that binds that intent to inputs/outputs
(Operation). Runtime selection is handled later by the implementation router.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Intent:
    """Logical “what to do” unit (runtime-agnostic)."""

    id: str
    name: str
    description: str
    domains: List[str] = field(default_factory=list)
    modalities: List[str] = field(default_factory=list)
    analysis_level: Optional[str] = None
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    parents: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Operation:
    """Concrete planned step bound to an Intent."""

    op_id: str
    intent: Intent
    inputs: Dict[str, str] = field(default_factory=dict)
    outputs: Dict[str, str] = field(default_factory=dict)
    preferences: Dict[str, Any] = field(default_factory=dict)
