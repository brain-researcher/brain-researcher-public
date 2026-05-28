import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain_researcher.core.ingestion.nifti_utils import load_nifti


def test_load_nifti_stub():
    assert callable(load_nifti)


def test_load_nifti_lazy_import():
    import sys

    assert "nibabel" not in sys.modules
    try:
        load_nifti("dummy")
    except Exception:
        pass
