from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _run(
    cmd: list[str],
    env: dict | None = None,
    log: Path | None = None,
) -> subprocess.CompletedProcess:
    """Run a command and raise if it fails."""
    if log:
        log = Path(log).resolve()
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as lf:
            proc = subprocess.run(
                cmd,
                stdout=lf,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                env=env,
            )
    else:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "cmd failed")
    return proc
