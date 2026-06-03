"""Compatibility checks for failure-mode registry relocation."""

from brain_researcher.services.review import failure_mode_registry as review_registry
from brain_researcher.services.shared import failure_mode_registry as shared_registry


def test_review_failure_mode_registry_reexports_shared_registry() -> None:
    assert review_registry.DEFAULT_REGISTRY_PATH is shared_registry.DEFAULT_REGISTRY_PATH
    assert review_registry.FailureModeRegistry is shared_registry.FailureModeRegistry
    assert review_registry.FailureModeRule is shared_registry.FailureModeRule
    assert (
        review_registry.load_failure_mode_registry
        is shared_registry.load_failure_mode_registry
    )
    assert (
        review_registry.render_failure_mode_registry_markdown
        is shared_registry.render_failure_mode_registry_markdown
    )
