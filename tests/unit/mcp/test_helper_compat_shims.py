from __future__ import annotations

from brain_researcher.services.mcp import loop_primitives as mcp_loop_primitives
from brain_researcher.services.mcp import param_norm as mcp_param_norm
from brain_researcher.services.shared import loop_primitives as shared_loop_primitives
from brain_researcher.services.shared import param_norm as shared_param_norm


def test_mcp_param_norm_compat_shim_reexports_shared_helpers() -> None:
    assert mcp_param_norm.coerce_enum is shared_param_norm.coerce_enum
    assert mcp_param_norm.enum_str is shared_param_norm.enum_str
    assert mcp_param_norm.as_str_list is shared_param_norm.as_str_list
    assert mcp_param_norm.resolve_enum_or_error is shared_param_norm.resolve_enum_or_error


def test_mcp_loop_primitives_compat_shim_reexports_shared_helpers() -> None:
    assert (
        mcp_loop_primitives.DEFAULT_LOOP_PROFILE_ID
        == shared_loop_primitives.DEFAULT_LOOP_PROFILE_ID
    )
    assert mcp_loop_primitives.get_loop_profile is shared_loop_primitives.get_loop_profile
    assert (
        mcp_loop_primitives.build_run_bundle_payload
        is shared_loop_primitives.build_run_bundle_payload
    )
    assert mcp_loop_primitives.build_run_scorecard is shared_loop_primitives.build_run_scorecard
    assert (
        mcp_loop_primitives.compare_run_scorecards
        is shared_loop_primitives.compare_run_scorecards
    )
