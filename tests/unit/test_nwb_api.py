import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from brain_researcher.core.ingestion.nwb_api import read_nwb


def test_read_nwb_stub():
    assert callable(read_nwb)


def test_nwb_lazy_import():
    import sys

    assert "pynwb" not in sys.modules
    try:
        read_nwb("file")
    except Exception:
        pass
