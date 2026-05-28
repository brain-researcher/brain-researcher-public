from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.params import (
    MultimodalFusionParameters,
    run_multimodal_fusion,
)


def test_run_multimodal_fusion(tmp_path):
    struct = np.random.randn(30, 20)
    func = np.random.randn(30, 25)
    struct_file = tmp_path / "struct.npy"
    func_file = tmp_path / "func.npy"
    np.save(struct_file, struct)
    np.save(func_file, func)

    params = MultimodalFusionParameters(
        structural_file=str(struct_file),
        functional_file=str(func_file),
        output_dir=str(tmp_path / "fusion"),
        fusion_method="intermediate",
        n_components=15,
        random_state=0,
        save_fused=True,
        save_components=True,
    )

    result = run_multimodal_fusion(params)
    assert "correlation_before" in result["summary"]
