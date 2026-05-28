import os
import sys

# import pdb; pdb.set_trace()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from brain_researcher.core.ingestion.datalad_git import datalad_get


def test_datalad_get_stub():
    assert callable(datalad_get)


def test_datalad_lazy_import():
    import sys

    assert "datalad" not in sys.modules
    try:
        datalad_get("url", "path")
    except Exception:
        pass
