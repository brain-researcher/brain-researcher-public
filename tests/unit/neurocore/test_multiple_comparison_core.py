from __future__ import annotations

from pathlib import Path

import numpy as np

from brain_researcher.services.tools.params import (
    MultipleComparisonParameters,
    run_multiple_comparison,
)


def test_run_multiple_comparison(tmp_path):
    pvals = np.random.rand(10, 5)
    pvals_file = tmp_path / "pvals.npy"
    np.save(pvals_file, pvals)

    params = MultipleComparisonParameters(
        p_values_file=str(pvals_file),
        output_dir=str(tmp_path / "mc"),
    )

    result = run_multiple_comparison(params)
    summary_path = Path(result["outputs"]["summary"])
    assert summary_path.exists()
    assert result["summary"]["n_tests"] == 50
