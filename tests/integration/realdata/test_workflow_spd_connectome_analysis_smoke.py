"""Real-data smoke placeholder for workflow_spd_connectome_analysis.

The workflow requires SPD operators that may not be available in all runtime
environments. This smoke test keeps coverage deterministic by only asserting
that the workflow id is present in the catalog.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.mark.realdata
def test_workflow_spd_connectome_analysis_catalog_reference():
    repo_root = Path(__file__).resolve().parents[3]
    catalog_path = repo_root / "configs" / "workflows" / "workflow_catalog.yaml"
    data = yaml.safe_load(catalog_path.read_text()) or {}
    workflows = data.get("workflows") or []
    ids = {str(w.get("id") or "").strip() for w in workflows if isinstance(w, dict)}
    assert "workflow_spd_connectome_analysis" in ids

