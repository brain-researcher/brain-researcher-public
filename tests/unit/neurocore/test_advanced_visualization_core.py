from __future__ import annotations

import numpy as np

from brain_researcher.services.tools.params import (
    AdvancedVisualizationParameters,
    run_advanced_visualization,
)


def test_run_advanced_visualization(tmp_path):
    data = np.random.randn(10, 10)
    data_file = tmp_path / "data.npy"
    np.save(data_file, data)

    params = AdvancedVisualizationParameters(
        data_file=str(data_file),
        output_dir=str(tmp_path / "viz"),
        data_type="matrix",
        plot_type="matrix",
        figure_format="png",
        interactive_backend="plotly",
        glass_display_mode=None,
        seed=123,
    )

    result = run_advanced_visualization(params)
    assert "visualization" in result["outputs"]

