"""Simple test to verify testing framework works."""


def test_addition():
    """Test basic addition."""
    assert 1 + 1 == 2


def test_string():
    """Test string operations."""
    assert "brain" + "_researcher" == "brain_researcher"


def test_list():
    """Test list operations."""
    items = [1, 2, 3]
    assert len(items) == 3
    assert sum(items) == 6


class TestBasicFunctionality:
    """Test class for basic functionality."""

    def test_boolean(self):
        """Test boolean logic."""
        assert True is not False

    def test_math(self):
        """Test math operations."""
        assert 10 / 2 == 5
        assert 3**2 == 9
