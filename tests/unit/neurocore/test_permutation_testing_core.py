from __future__ import annotations

from pathlib import Path

import numpy as np

from brain_researcher.services.tools.params import (
    PermutationTestParameters,
    run_permutation_test,
)


def test_run_permutation_test(tmp_path):
    data = np.random.randn(8, 4)
    data_file = tmp_path / "data.npy"
    np.save(data_file, data)

    params = PermutationTestParameters(
        data_file=str(data_file),
        output_dir=str(tmp_path / "perm"),
        n_permutations=128,
    )

    result = run_permutation_test(params)
    summary_path = Path(result["outputs"]["summary"])
    assert summary_path.exists()
    assert result["summary"]["n_subjects"] == 8
