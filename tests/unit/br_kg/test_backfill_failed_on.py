import os

import pytest

# This test only verifies query assembly best-effort; it does not hit a live Neo4j.
from brain_researcher.services.br_kg.graph import backfill_failed_on


def test_backfill_mode_values():
    assert backfill_failed_on.backfill.__defaults__[0] == "replace"
    assert set(backfill_failed_on.__all_modes__) == {"replace", "accumulate"}


def test_driver_env_missing():
    # ensure missing password raises
    orig = os.environ.pop("NEO4J_PASSWORD", None)
    try:
        with pytest.raises(RuntimeError):
            backfill_failed_on.get_driver()
    finally:
        if orig is not None:
            os.environ["NEO4J_PASSWORD"] = orig
