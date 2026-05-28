from __future__ import annotations

import pytest
import typer

from brain_researcher.cli.commands.services import gateway_launcher


def test_launch_gateway_exits_with_deprecation_guidance() -> None:
    with pytest.raises(typer.Exit) as excinfo:
        gateway_launcher.launch_gateway(
            host="127.0.0.1",
            port=8123,
            reload=False,
            workers=2,
        )

    assert excinfo.value.exit_code == 1
