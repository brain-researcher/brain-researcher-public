"""CLI entry point for the bounded autoresearch supervisor.

Constructs the concrete LLMRouter (a services-tier dependency) and
injects it into BoundedSupervisor. Kept in cli/commands/ so that the
autoresearch/ package stays free of service-tier imports.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.autoresearch.supervisor import (
    BoundedSupervisor,
    SupervisorConfig,
)
from brain_researcher.services.agent.router import LLMRouter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded autoresearch supervisor from a JSON config."
    )
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    payload = json.loads(
        Path(args.config).expanduser().resolve().read_text(encoding="utf-8")
    )
    config = SupervisorConfig.from_dict(payload)
    supervisor = BoundedSupervisor(config, router=LLMRouter())
    supervisor.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
