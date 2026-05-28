from scripts.enrich_catalog_with_neurobagel import enrich_catalog


def _base_catalog_row() -> dict:
    return {
        "dataset_id": "ds:openneuro:ds000001",
        "name": "Demo",
        "modalities": ["fMRI"],
        "source_repo": "OpenNeuro",
        "source_repo_id": "ds000001",
        "primary_url": "https://openneuro.org/datasets/ds000001",
        "access_type": "public",
        "license": "CC0",
    }


def test_enrich_catalog_adds_unique_subjects_when_participant_id_present() -> None:
    catalog_rows = [_base_catalog_row()]
    fieldnames = ["dataset_id", "participant_id", "session_id", "age", "sex"]
    tsv_rows = [
        {
            "dataset_id": "ds000001",
            "participant_id": "sub-01",
            "session_id": "ses-1",
            "age": "20",
            "sex": "Male",
        },
        {
            "dataset_id": "ds000001",
            "participant_id": "sub-01",
            "session_id": "ses-2",
            "age": "20",
            "sex": "Male",
        },
        {
            "dataset_id": "ds000001",
            "participant_id": "sub-02",
            "session_id": "ses-1",
            "age": "25",
            "sex": "Female",
        },
    ]

    stats = enrich_catalog(
        catalog_rows,
        tsv_rows,
        fieldnames,
        mode="replace",
        annotation_source="neurobagel_tsv:test.tsv",
    )

    assert stats["updated_rows"] == 1
    assert stats["subject_id_columns"] == ["participant_id"]

    summary = {
        item["name"]: item for item in catalog_rows[0]["phenotype_summary"]
    }

    assert summary["Age"]["total_observations"] == 3
    assert summary["Age"]["unique_subjects"] == 2
    assert summary["Sex"]["total_observations"] == 3
    assert summary["Sex"]["unique_subjects"] == 2


def test_enrich_catalog_omits_unique_subjects_when_subject_id_missing() -> None:
    catalog_rows = [_base_catalog_row()]
    fieldnames = ["dataset_id", "session_id", "age"]
    tsv_rows = [
        {"dataset_id": "ds000001", "session_id": "s1", "age": "20"},
        {"dataset_id": "ds000001", "session_id": "s2", "age": "21"},
    ]

    stats = enrich_catalog(
        catalog_rows,
        tsv_rows,
        fieldnames,
        mode="replace",
        annotation_source="neurobagel_tsv:test.tsv",
    )

    assert stats["updated_rows"] == 1
    assert stats["subject_id_columns"] == []

    age_summary = catalog_rows[0]["phenotype_summary"][0]
    assert age_summary["name"] == "Age"
    assert age_summary["total_observations"] == 2
    assert "unique_subjects" not in age_summary

