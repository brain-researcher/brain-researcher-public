"""Shared dataset-resolution facade for BR-KG callers.

BR-KG needs dataset resource summaries, but it must not import the agent layer.
This module keeps the small provider hook introduced for BR-KG callers while
defaulting to the real shared dataset-resolution implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from brain_researcher.services.shared import dataset_resource_resolution

DatasetResourceCollector = Callable[..., Any | None]
DatasetReferenceResolver = Callable[..., Any | None]

_dataset_resource_collector: DatasetResourceCollector | None = None
_dataset_reference_resolver: DatasetReferenceResolver | None = None


def register_dataset_resource_resolvers(
    *,
    collect_dataset_resources: DatasetResourceCollector,
    resolve_dataset_reference: DatasetReferenceResolver,
) -> None:
    """Register concrete dataset-resource resolvers.

    Runtime entrypoints may call this to inject test or custom implementations.
    If no resolver has been registered, this module uses the shared resolver
    implementation.
    """

    global _dataset_resource_collector, _dataset_reference_resolver
    _dataset_resource_collector = collect_dataset_resources
    _dataset_reference_resolver = resolve_dataset_reference


def has_dataset_resource_resolvers() -> bool:
    """Whether both dataset resolver callables have been registered."""

    return (
        _dataset_resource_collector is not None
        and _dataset_reference_resolver is not None
    )


def _call_kwargs(
    *,
    catalog_path: Path | str | None = None,
    mounts_path: Path | str | None = None,
    manual_catalog_path: Path | str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    if catalog_path is not None:
        kwargs["catalog_path"] = catalog_path
    if mounts_path is not None:
        kwargs["mounts_path"] = mounts_path
    if manual_catalog_path is not None:
        kwargs["manual_catalog_path"] = manual_catalog_path
    return kwargs


def collect_dataset_resources(
    dataset_id_or_alias: str,
    *,
    catalog_path: Path | str | None = None,
    mounts_path: Path | str | None = None,
    manual_catalog_path: Path | str | None = None,
    dataset_version: str | None = None,
    analysis_goal: str = "generic",
    semantic_intent: str | None = None,
    auto_heal: bool = False,
    run_bids_validation: bool = True,
    enforce_semantic_gate: bool = True,
    check_source_access: bool = True,
) -> Any | None:
    """Collect local/remote resources for a dataset reference."""

    collector = _dataset_resource_collector
    if collector is None:
        collector = dataset_resource_resolution.collect_dataset_resources
    return collector(
        dataset_id_or_alias,
        **_call_kwargs(
            catalog_path=catalog_path,
            mounts_path=mounts_path,
            manual_catalog_path=manual_catalog_path,
            dataset_version=dataset_version,
            analysis_goal=analysis_goal,
            semantic_intent=semantic_intent,
            auto_heal=auto_heal,
            run_bids_validation=run_bids_validation,
            enforce_semantic_gate=enforce_semantic_gate,
            check_source_access=check_source_access,
        ),
    )


def resolve_dataset_reference(
    user_text: str,
    *,
    catalog_path: Path | str | None = None,
    mounts_path: Path | str | None = None,
    manual_catalog_path: Path | str | None = None,
) -> Any | None:
    """Resolve free text to a dataset-resolution object."""

    resolver = _dataset_reference_resolver
    if resolver is None:
        resolver = dataset_resource_resolution.resolve_dataset_reference
    return resolver(
        user_text,
        **_call_kwargs(
            catalog_path=catalog_path,
            mounts_path=mounts_path,
            manual_catalog_path=manual_catalog_path,
        ),
    )


__all__ = [
    "DatasetResourceCollector",
    "DatasetReferenceResolver",
    "register_dataset_resource_resolvers",
    "has_dataset_resource_resolvers",
    "collect_dataset_resources",
    "resolve_dataset_reference",
]
