from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from ._utils import _run, tool

logger = logging.getLogger(__name__)


@tool
def datalad_get(url: str, path: str) -> str:
    """Get a dataset with DataLad."""
    cmd = ["datalad", "clone", url, Path(path).resolve().as_posix()]
    _run(cmd)
    return Path(path).resolve().as_posix()


@tool
def datalad_save(path: str, message: str) -> str:
    """Save a dataset with DataLad."""
    cmd = ["datalad", "save", "-m", message, Path(path).resolve().as_posix()]
    _run(cmd)
    return Path(path).resolve().as_posix()


@tool
def datalad_run(cmd: str, dataset: str) -> dict[str, str | int]:
    """Run a command within a DataLad dataset."""
    log = Path(tempfile.mkstemp(suffix=".log")[1]).resolve()
    proc = _run(
        ["datalad", "run", "-d", Path(dataset).resolve().as_posix(), cmd],
        log=log,
    )
    return {"returncode": proc.returncode, "log": log.as_posix()}


@tool
def datalad_create_sibling_s3(bucket: str, dataset: str) -> str:
    """Create S3 sibling for dataset."""
    cmd = [
        "datalad",
        "create-sibling-s3",
        bucket,
        "-d",
        Path(dataset).resolve().as_posix(),
    ]
    _run(cmd)
    return bucket


@tool
def git_annex_get(file: str) -> None:
    """Get file content via git-annex."""
    _run(["git", "annex", "get", Path(file).resolve().as_posix()])


@tool
def git_annex_drop(file: str) -> None:
    """Drop file content via git-annex."""
    _run(["git", "annex", "drop", Path(file).resolve().as_posix()])
