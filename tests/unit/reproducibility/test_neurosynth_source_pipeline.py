from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str, relative_path: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, content: bytes, *, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.closed = False

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def iter_content(self, chunk_size: int):
        yield self.content

    def close(self) -> None:
        self.closed = True


def _spec(module, content: bytes):
    return module.SourceFile(
        filename="source.bin",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_downloader_verifies_existing_file_without_network(tmp_path: Path) -> None:
    module = _load_script(
        "download_neurosynth_existing_test", "scripts/data/download_neurosynth_data.py"
    )
    content = b"verified source"
    spec = _spec(module, content)
    (tmp_path / spec.filename).write_bytes(content)

    def no_network(*args, **kwargs):
        raise AssertionError("verified files must not be downloaded again")

    assert (
        module.ensure_file(spec, tmp_path, request_get=no_network)
        == "verified existing file"
    )


def test_downloader_replaces_corrupt_file_only_with_verified_content(
    tmp_path: Path,
) -> None:
    module = _load_script(
        "download_neurosynth_replace_test", "scripts/data/download_neurosynth_data.py"
    )
    content = b"verified source"
    spec = _spec(module, content)
    target = tmp_path / spec.filename
    target.write_bytes(b"stale")
    response = FakeResponse(content)

    outcome = module.ensure_file(
        spec, tmp_path, request_get=lambda *args, **kwargs: response
    )

    assert outcome == "downloaded and verified"
    assert target.read_bytes() == content
    assert response.closed


def test_downloader_fails_closed_and_removes_partial_content(tmp_path: Path) -> None:
    module = _load_script(
        "download_neurosynth_failure_test", "scripts/data/download_neurosynth_data.py"
    )
    spec = _spec(module, b"expected")

    with pytest.raises(ValueError, match="failed verification"):
        module.ensure_file(
            spec,
            tmp_path,
            request_get=lambda *args, **kwargs: FakeResponse(b"wrong"),
        )

    assert not (tmp_path / spec.filename).exists()
    assert not (tmp_path / f"{spec.filename}.part").exists()


def test_downloader_main_returns_nonzero_on_any_failure(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_script(
        "download_neurosynth_main_test", "scripts/data/download_neurosynth_data.py"
    )
    monkeypatch.setattr(module, "SOURCE_FILES", (_spec(module, b"source"),))
    monkeypatch.setattr(
        module,
        "ensure_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert module.main(["--target-dir", str(tmp_path)]) == 1


def _write_converter_inputs(module, root: Path) -> None:
    for filename in (
        module.COORDINATES,
        module.METADATA,
        module.FEATURES,
        module.VOCABULARY,
    ):
        (root / filename).write_bytes(b"input")


def test_converter_failure_removes_stale_canonical_pickle(tmp_path: Path) -> None:
    module = _load_script(
        "convert_neurosynth_failure_test", "scripts/data/convert_neurosynth.py"
    )
    data_dir = tmp_path / "inputs"
    data_dir.mkdir()
    _write_converter_inputs(module, data_dir)
    output = tmp_path / "dataset.pkl"
    output.write_bytes(b"stale pickle")

    class FailingIO:
        @staticmethod
        def convert_neurosynth_to_dataset(**kwargs):
            raise RuntimeError("conversion failed")

    with pytest.raises(RuntimeError, match="conversion failed"):
        module.convert_dataset(data_dir, output, io_module=FailingIO)

    assert not output.exists()
    assert not (tmp_path / ".dataset.incomplete.pkl").exists()


def test_converter_publishes_only_complete_new_pickle(tmp_path: Path) -> None:
    module = _load_script(
        "convert_neurosynth_success_test", "scripts/data/convert_neurosynth.py"
    )
    data_dir = tmp_path / "inputs"
    data_dir.mkdir()
    _write_converter_inputs(module, data_dir)
    output = tmp_path / "dataset.pkl"
    output.write_bytes(b"stale pickle")

    class Dataset:
        @staticmethod
        def save(path: str) -> None:
            Path(path).write_bytes(b"new pickle")

    class SuccessfulIO:
        @staticmethod
        def convert_neurosynth_to_dataset(**kwargs):
            return Dataset()

    module.convert_dataset(data_dir, output, io_module=SuccessfulIO)
    assert output.read_bytes() == b"new pickle"
