import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from brain_researcher.core.ingestion.table_utils import read_tsv


def test_read_tsv_stub():
    assert callable(read_tsv)


def test_table_utils_lazy_import():
    import sys

    assert "pandas" not in sys.modules
    try:
        read_tsv("dummy.tsv")
    except Exception:
        pass
