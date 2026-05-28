import json
import zipfile
from pathlib import Path

import pytest


def _make_minimal_bids_dataset(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset_description.json").write_text(
        json.dumps({"Name": "Example", "BIDSVersion": "1.9.0"}, indent=2),
        encoding="utf-8",
    )
    (root / "sub-01" / "anat").mkdir(parents=True, exist_ok=True)
    (root / "sub-01" / "anat" / "sub-01_T1w.nii.gz").write_bytes(b"not-a-real-nifti")


def test_import_bids_zip_writes_manifest_and_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_LOCAL_DATASET_REGISTRY", str(tmp_path / "registry.json"))

    src = tmp_path / "src"
    _make_minimal_bids_dataset(src)

    zip_path = tmp_path / "ds.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for p in src.rglob("*"):
            if p.is_dir():
                continue
            zf.write(p, p.relative_to(src).as_posix())

    from brain_researcher.core.datasets.bids_import import import_bids_zip

    dest_root = tmp_path / "bids"
    result = import_bids_zip(
        zip_path=zip_path, dataset_id="bids-test", dest_root=dest_root, validate=False
    )

    bids_root = Path(result.bids_root)
    assert bids_root.exists()
    assert (bids_root / "dataset_description.json").is_file()
    assert (bids_root / "dataset_manifest.json").is_file()

    manifest = json.loads(
        (bids_root / "dataset_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.get("manifest_sha256")

    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert any(d.get("dataset_id") == "bids-test" for d in registry.get("datasets", []))


def test_import_bids_zip_rejects_zip_slip(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_LOCAL_DATASET_REGISTRY", str(tmp_path / "registry.json"))

    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.txt", "nope")

    from brain_researcher.core.datasets.bids_import import import_bids_zip

    with pytest.raises(ValueError):
        import_bids_zip(
            zip_path=zip_path, dataset_id="bids-bad", dest_root=tmp_path / "bids"
        )
