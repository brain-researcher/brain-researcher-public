"""CLI wrapper for FAILED_ON aggregate backfill."""

from brain_researcher.services.br_kg.graph.backfill_failed_on import (
    __all_modes__,
    backfill,
    get_driver,
    main,
)

__all__ = ["__all_modes__", "backfill", "get_driver", "main"]


if __name__ == "__main__":
    main()
