from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.lesion_detection_tool import LesionDetectionTool


def test_agent_lesion_detection(tmp_path):
    tool = LesionDetectionTool()
    flair = np.random.randn(26, 26, 26)
    flair_file = tmp_path / "flair.npy"
    np.save(flair_file, flair)

    result = tool._run(
        flair_image=str(flair_file),
        output_dir=str(tmp_path / "lesions"),
        lesion_type="wmh",
    )

    assert result.status == "success"
