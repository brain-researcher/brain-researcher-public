import os

import pytest

CONTRACT_PATH = os.path.join("docs", "UI_CONTENT_CONTRACT.md")
README_PATH = "README.md"


def test_contract_file_exists():
    """Ensure the UI content contract markdown exists."""
    assert os.path.exists(CONTRACT_PATH), "UI content contract missing"


def test_readme_links_contract():
    """README should link to the UI content contract for contributor visibility."""
    with open(README_PATH) as f:
        readme = f.read()
    assert "UI_CONTENT_CONTRACT.md" in readme


@pytest.mark.skip(reason="UI contract acceptance test placeholder")
def test_landing_page_contract():
    """Landing page shows search bar, stats, and recently added datasets."""
    pass


@pytest.mark.skip(reason="UI contract acceptance test placeholder")
def test_search_results_contract():
    """Results list and graph preview behave per contract."""
    pass


@pytest.mark.skip(reason="UI contract acceptance test placeholder")
def test_node_details_panel_contract():
    """Node details panel shows required fields for each node type."""
    pass
