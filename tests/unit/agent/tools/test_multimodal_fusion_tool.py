from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.multimodal_fusion import MultimodalFusionTool


def test_agent_multimodal_fusion(tmp_path):
    tool = MultimodalFusionTool()
    struct = np.random.randn(28, 7)
    func = np.random.randn(28, 8)
    struct_file = tmp_path / "struct.npy"
    func_file = tmp_path / "func.npy"
    np.save(struct_file, struct)
    np.save(func_file, func)

    result = tool._run(
        structural_file=str(struct_file),
        functional_file=str(func_file),
        output_dir=str(tmp_path / "fusion"),
        n_components=5,
    )

    assert result.status == "success"
