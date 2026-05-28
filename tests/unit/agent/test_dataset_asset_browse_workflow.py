from __future__ import annotations

from brain_researcher.services.agent.planner.models import ArtifactSpec, StepSpec
from brain_researcher.services.agent.web_service import _maybe_add_resolvers


def test_maybe_add_resolvers_prepends_dataset_browse_for_ambiguous_dataset_inputs():
    steps: list[StepSpec] = []
    artifacts: list[ArtifactSpec] = []
    inputs = {"dataset_ref": "ds000114", "subject_id": "01", "task": "emotion"}

    _maybe_add_resolvers(steps, artifacts, inputs, requires_bids=False)

    assert steps
    assert steps[0].tool == "list_dataset_assets"
    assert artifacts[0].name == "dataset_asset_inventory"


def test_maybe_add_resolvers_skips_dataset_browse_for_exact_paths():
    steps: list[StepSpec] = []
    artifacts: list[ArtifactSpec] = []
    inputs = {
        "dataset_ref": "ds000114",
        "subject_id": "01",
        "t1w_image": "/data/sub-01_T1w.nii.gz",
    }

    _maybe_add_resolvers(steps, artifacts, inputs, requires_bids=False)

    assert steps == []
    assert artifacts == []
