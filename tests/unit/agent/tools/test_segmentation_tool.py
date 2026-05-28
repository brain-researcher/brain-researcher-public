from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.segmentation_tool import SegmentationTool


def test_agent_segmentation(tmp_path):
    tool = SegmentationTool()
    image = np.random.randn(12, 12, 12)
    image_file = tmp_path / "image.npy"
    np.save(image_file, image)

    result = tool._run(
        input_image=str(image_file),
        output_dir=str(tmp_path / "seg"),
        segmentation_type="tissue",
        n_classes=3,
    )

    assert result.status == "success"
    outputs = result.data["outputs"]
    assert outputs["segmentation"] is not None
    assert outputs["qc_png"] is not None
    assert (tmp_path / "seg" / "segmentation_qc.png").exists()
