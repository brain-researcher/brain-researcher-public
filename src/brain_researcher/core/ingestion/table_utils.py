from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ._utils import tool

logger = logging.getLogger(__name__)


@tool
def read_tsv(path: str) -> Any:
    """Read a TSV table."""
    import pandas as pd

    return pd.read_csv(Path(path).resolve().as_posix(), sep="\t")


@tool
def merge_tables(df_left: Any, df_right: Any, key: str) -> Any:
    """Merge two tables."""
    import pandas as pd

    return pd.merge(df_left, df_right, on=key, how="outer")


@tool
def tidy_long(df: Any, id_vars: list[str], value_vars: list[str]) -> Any:
    """Melt table to long format."""
    import pandas as pd

    return pd.melt(
        df,
        id_vars=id_vars,
        value_vars=value_vars,
        var_name="variable",
        value_name="value",
    )


@tool
def qc_missing_values(df: Any) -> dict[str, Any]:
    """Check missing values."""
    total = int(df.size)
    missing = int(df.isna().sum().sum())
    percent = float(missing) / total * 100 if total else 0.0
    return {
        "total": total,
        "missing": missing,
        "percentage": percent,
        "columns": df.isna().sum().to_dict(),
    }
