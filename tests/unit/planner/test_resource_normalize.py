import pytest

from brain_researcher.services.shared.planner.models import ResourceType, normalize_modality


def test_resource_type_aliases_normalize():
    assert ResourceType.validate("file_path") == "file_paths"
    assert ResourceType.validate("coords") == "coordinates"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BOLD", "fmri"),
        ("structural", "smri"),
        ("diffusion", "dmri"),
        ("data_catalog", "data_catalog"),
    ],
)
def test_modality_normalize(raw, expected):
    assert normalize_modality(raw) == expected
