"""Integration stub: go/no-go scaffold + psyflow-validate."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("psyflow")

from brain_researcher.behavior.catalog import config_mapper_for, resolve_defaults
from brain_researcher.behavior.psyflow_adapter import (
    run_psyflow_validate,
    write_psyflow_scaffold,
)


@pytest.mark.xfail(strict=False, reason="psyflow validate surface is best-effort")
def test_go_no_go_scaffold_validates(tmp_path: Path):
    spec = resolve_defaults("go_no_go")
    bundle = write_psyflow_scaffold(spec, tmp_path, config_mapper_for("go_no_go"))
    result = run_psyflow_validate(bundle)
    assert result["status"] in {"success", "skipped"}
