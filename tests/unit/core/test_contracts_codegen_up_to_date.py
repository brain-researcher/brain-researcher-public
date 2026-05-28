import os

os.environ.setdefault("BR_DISABLE_TOOL_RUNNER_IMPORT", "1")


def test_contract_schemas_up_to_date():
    from scripts.contracts.generate_schemas import main

    assert main(["--check"]) == 0


def test_web_ui_contract_types_up_to_date():
    from scripts.contracts.generate_web_ui_types import main

    assert main(["--check"]) == 0
