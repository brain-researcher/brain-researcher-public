from __future__ import annotations

import inspect

import pytest

from brain_researcher.services.tools import (
    tribe_biological_motion_materializer,
    tribe_closed_loop_paths,
    tribe_stimulus_library,
)


def test_stimulus_library_helpers_do_not_have_repo_defaults() -> None:
    assert (
        inspect.signature(tribe_stimulus_library.load_stimulus_library_config)
        .parameters["config_path"]
        .default
        is inspect.Signature.empty
    )
    assert (
        inspect.signature(tribe_stimulus_library.resolve_project_paths)
        .parameters["config_path"]
        .default
        is inspect.Signature.empty
    )
    assert (
        inspect.signature(tribe_stimulus_library.resolve_task_config)
        .parameters["config_path"]
        .default
        is inspect.Signature.empty
    )
    assert not hasattr(tribe_stimulus_library, "DEFAULT_TRIBE_STIMULUS_LIBRARY")


@pytest.mark.parametrize(
    "parser",
    [
        tribe_biological_motion_materializer.build_parser(),
        tribe_closed_loop_paths.build_parser(),
    ],
)
def test_tribe_cli_parsers_require_stimulus_library(parser) -> None:
    with pytest.raises(SystemExit):
        parser.parse_args([])
