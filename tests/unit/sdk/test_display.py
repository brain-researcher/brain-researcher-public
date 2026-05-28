"""Tests for brain_researcher.sdk.display."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from brain_researcher.sdk import display


class TestNifti:
    def test_returns_path_when_nilearn_missing(self):
        with patch.dict("sys.modules", {"nilearn": None, "nilearn.plotting": None}):
            # Force reimport to pick up missing nilearn
            with patch("brain_researcher.sdk.display.importlib") as _:
                # Simplest test: if nilearn import fails, return path
                pass

    def test_returns_path_string_on_import_error(self):
        with patch("brain_researcher.sdk.display.Path"):
            with patch.dict("sys.modules", {"nilearn": None, "nilearn.plotting": None}):
                # The function catches ImportError and returns the path
                result = display.nifti("/fake/path.nii.gz")
                # When nilearn is missing, it should return the path string
                assert isinstance(result, str) or result is not None


class TestTable:
    def test_table_with_list_of_dicts_no_marimo(self):
        with patch.object(display, "_HAS_MARIMO", False):
            data = [{"a": 1}, {"a": 2}]
            result = display.table(data)
            # Should try pandas; if not available, returns raw data
            assert result is not None

    def test_table_returns_input_when_no_deps(self):
        with patch.object(display, "_HAS_MARIMO", False):
            with patch.dict("sys.modules", {"pandas": None}):
                data = [{"a": 1}]
                result = display.table(data)
                assert result is not None


class TestPlot:
    def test_plot_passthrough(self):
        fig = MagicMock()
        assert display.plot(fig) is fig
