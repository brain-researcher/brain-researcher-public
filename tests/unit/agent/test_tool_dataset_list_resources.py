from brain_researcher.core.datasets.catalog import DatasetRecord
from brain_researcher.services.agent.kg_resolution import DatasetResources
from brain_researcher.services.tools.dataset_resources_tool import (
    DatasetDescribeTool,
    DatasetResourcesTool,
)


def test_dataset_resources_tool(monkeypatch, tmp_path):
    dummy = DatasetResources(
        bids_path=tmp_path / "ds000114",
        derivatives={"fmriprep": "/deriv/fmriprep"},
        remote_urls={"openneuro": "https://openneuro.org/datasets/ds000114"},
        size_bytes=123,
        is_bids_available=True,
        available_derivatives=["fmriprep"],
        analysis_goal="fmri-glm",
        readiness={"status": "partial", "notes": ["validator note"]},
        source_access={"provider": "openneuro"},
    )

    captured = {}

    def fake_collect(dataset_ref, **kwargs):
        captured["dataset_ref"] = dataset_ref
        captured.update(kwargs)
        return dummy

    monkeypatch.setattr(
        "brain_researcher.services.tools.dataset_resources_tool.collect_dataset_resources",
        fake_collect,
    )

    tool = DatasetResourcesTool()
    result = tool.run(
        dataset_ref="ds000114",
        analysis_goal="fmri-glm",
        check_source_access=False,
    )

    assert result["status"] == "success"
    assert captured["check_source_access"] is False
    assert result["data"]["is_bids_available"] is True
    assert "fmriprep" in result["data"]["derivatives"]
    assert result["data"]["remote_urls"]["openneuro"].endswith("ds000114")
    assert result["data"]["analysis_goal"] == "fmri-glm"
    assert result["data"]["readiness"]["status"] == "partial"
    assert result["data"]["readiness"]["notes"] == ["validator note"]
    assert result["data"]["source_access"]["provider"] == "openneuro"
    assert result["data"]["resolved_dataset_id"] == "ds000114"
    assert result["data"]["resolution_mode"] == "unknown"
    assert result["data"]["resolver_warnings"] == []


def test_dataset_describe_tool(monkeypatch, tmp_path):
    dummy = DatasetResources(
        bids_path=tmp_path / "ds000114",
        derivatives={"fmriprep": "/deriv/fmriprep"},
        remote_urls={"openneuro": "https://openneuro.org/datasets/ds000114"},
        size_bytes=123,
        is_bids_available=True,
        available_derivatives=["fmriprep"],
        analysis_goal="fmri-glm",
        source_trace=[{"stage": "mount", "kind": "raw", "hit": True}],
        required_files={
            "analysis_goal": "fmri-glm",
            "required_total": 2,
            "required_passed": 1,
            "all_required_passed": False,
            "missing_patterns": ["sub-*/func/*_bold.nii.gz"],
            "groups": [
                {
                    "name": "bold",
                    "patterns": ["sub-*/func/*_bold.nii.gz"],
                    "counts": {"sub-*/func/*_bold.nii.gz": 1},
                    "min_matches": 1,
                    "optional": False,
                    "passed": True,
                }
            ],
        },
        readiness={"status": "ready"},
    )
    dataset_record = DatasetRecord(
        dataset_id="ds:openneuro:ds000114",
        name="ds000114",
        modalities=["fMRI"],
        acquisitions=["BOLD"],
        subjects_count=20,
        sessions_count=2,
        source_repo="OpenNeuro",
        source_repo_id="ds000114",
        primary_url="https://openneuro.org/datasets/ds000114",
        access_type="public",
        tasks=["nback"],
    )

    monkeypatch.setattr(
        "brain_researcher.services.tools.dataset_resources_tool.collect_dataset_resources",
        lambda dataset_ref, **kwargs: dummy,
    )
    monkeypatch.setattr(
        "brain_researcher.services.tools.dataset_resources_tool._match_catalog_record",
        lambda dataset_ref: dataset_record,
    )

    tool = DatasetDescribeTool()
    result = tool.run(dataset_ref="ds000114", include_sensitive_paths=False)

    assert result["status"] == "success"
    assert result["data"]["subjects_count"] == 20
    assert result["data"]["storage"]["bids_path_available"] is True
    assert result["data"]["storage"]["bids_path"] is None
    assert result["data"]["files"]["required_total"] == 2
    assert result["data"]["files"]["total_matched_files"] == 1
