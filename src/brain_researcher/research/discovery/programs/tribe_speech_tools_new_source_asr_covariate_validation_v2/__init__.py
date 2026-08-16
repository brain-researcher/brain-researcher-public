"""Public new-source-v2 TRIBE speech-tools evaluation chain."""

from .contracts import (
    FROZEN_HYPOTHESIS_FAMILIES,
    FROZEN_PERMUTATION_METADATA,
    validate_source_feasibility_contract,
)
from .evaluator import evaluate_frozen_hypothesis_families

__all__ = [
    "FROZEN_HYPOTHESIS_FAMILIES",
    "FROZEN_PERMUTATION_METADATA",
    "evaluate_frozen_hypothesis_families",
    "validate_source_feasibility_contract",
]
