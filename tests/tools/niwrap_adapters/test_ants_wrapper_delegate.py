"""Ensure ANTs wrapper delegates to NiWrap executor."""
from unittest.mock import patch

from brain_researcher.services.tools.ants_tool import ANTsRegistrationTool


def test_ants_wrapper_delegate():
    kwargs = {
        "fixed_image": "fixed.nii.gz",
        "moving_image": "moving.nii.gz",
        "output_prefix": "out",
        "transform_type": "SyN",
        "metric": "MI",
        "convergence": "[1000x500,1e-6,10]",
        "shrink_factors": "4x2",
        "smoothing_sigmas": "2x1vox",
        "interpolation": "Linear",
        "use_histogram_matching": True,
        "dimension": 3,
        "float_precision": False,
        "verbose": False,
        "num_threads": 1,
        "extra_args": (),
    }
    with patch("brain_researcher.services.tools.ants_tool.execute_niwrap_tool") as m:
        m.return_value = {"ok": True}
        tool = ANTsRegistrationTool()
        result = tool._run(**kwargs)
        assert result.status == "success"
        assert result.data == {"ok": True}
        m.assert_called_once()
        assert m.call_args.kwargs["tool_name"] == "ants.antsRegistration.run"
        assert all(item in m.call_args.kwargs["parameters"].items() for item in kwargs.items())
