import json


def test_local_registry_upsert_list_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_LOCAL_DATASET_REGISTRY", str(tmp_path / "registry.json"))

    from brain_researcher.core.datasets.local_registry import (
        LocalDatasetRecord,
        delete_local_dataset,
        get_local_dataset,
        list_local_datasets,
        upsert_local_dataset,
    )

    rec = LocalDatasetRecord(
        dataset_id="ds000001",
        bids_root=str(tmp_path / "bids" / "ds000001"),
        source="local",
        name="Test dataset",
    )
    upsert_local_dataset(rec)

    got = get_local_dataset("ds000001")
    assert got is not None
    assert got.dataset_id == "ds000001"
    assert got.name == "Test dataset"

    # Upsert should preserve created_at
    created_at = got.created_at
    rec2 = LocalDatasetRecord(
        dataset_id="ds000001",
        bids_root=str(tmp_path / "bids" / "ds000001"),
        source="local",
        name="Updated name",
    )
    upsert_local_dataset(rec2)

    got2 = get_local_dataset("ds000001")
    assert got2 is not None
    assert got2.created_at == created_at
    assert got2.name == "Updated name"

    # List returns our dataset
    items = list_local_datasets()
    assert [i.dataset_id for i in items] == ["ds000001"]

    # Underlying JSON is valid
    payload = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "local-dataset-registry-v1"

    assert delete_local_dataset("ds000001") is True
    assert get_local_dataset("ds000001") is None
