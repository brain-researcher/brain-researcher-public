"""Dependency-inversion seam for artifact-time code-review distillation.

``services/memory``'s ``distill_and_store_run`` opportunistically extracts a
code-review memory card by running the review-layer
``distill_review_records``. ``memory`` is the *lowest* services layer
(``memory < shared < ... < review < ...``), so importing
``distill_review_records`` directly is a back-edge.

This seam lives inside ``services/memory`` itself (so ``memory`` stays a true
leaf -- it does not even import ``services/shared``). It defines a tiny
registry for a review-distiller hook. The concrete ``distill_review_records``
is registered by a higher layer (the MCP server, which is the sole real caller
of ``distill_and_store_run`` and already imports ``review``); ``memory``
depends only on this in-package seam.

The hook returns a structural object exposing ``verdict`` / ``bundle`` /
``warnings`` (matching ``review.DistilledReviewMemory``). If no hook is
registered, ``get_review_distiller`` returns ``None`` and the memory distiller
simply skips review-card extraction -- which is exactly the best-effort
behaviour it already had when the review import failed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ReviewDistillResult(Protocol):
    """Structural result of the review distiller (review.DistilledReviewMemory)."""

    @property
    def verdict(self) -> Any: ...

    @property
    def bundle(self) -> Any: ...

    @property
    def warnings(self) -> list[str]: ...


# (run_id, *, run_dir) -> ReviewDistillResult
ReviewDistiller = Callable[..., ReviewDistillResult]

_review_distiller: ReviewDistiller | None = None


def register_review_distiller(distiller: ReviewDistiller) -> None:
    """Register the review-distiller hook.

    Idempotent by design: the higher layer may register on every import.
    """

    global _review_distiller
    _review_distiller = distiller


def get_review_distiller() -> ReviewDistiller | None:
    """Return the registered review-distiller hook, or ``None`` if unset."""

    return _review_distiller


def distill_review_records(
    run_id: str, *, run_dir: Path | None = None
) -> ReviewDistillResult | None:
    """Invoke the registered review distiller, or return ``None`` if unset."""

    distiller = _review_distiller
    if distiller is None:
        return None
    return distiller(run_id, run_dir=run_dir)


__all__ = [
    "ReviewDistillResult",
    "ReviewDistiller",
    "register_review_distiller",
    "get_review_distiller",
    "distill_review_records",
]
