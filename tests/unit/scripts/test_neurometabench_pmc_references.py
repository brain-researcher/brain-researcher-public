from __future__ import annotations

import csv
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module():
    """Load neurometabench_screening_pipeline without executing side-effectful code."""
    script_path = REPO_ROOT / "scripts" / "neurometabench_screening_pipeline.py"
    spec = importlib.util.spec_from_file_location(
        "neurometabench_screening_pipeline_pmc_test", script_path
    )
    assert spec is not None and spec.loader is not None

    # Stub google.genai so the optional import doesn't fail in constrained envs.
    fake_genai = types.ModuleType("google.genai")
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai  # type: ignore[attr-defined]
    fake_genai_types = types.ModuleType("google.genai.types")

    prev_google = sys.modules.get("google")
    prev_genai = sys.modules.get("google.genai")
    prev_genai_types = sys.modules.get("google.genai.types")
    sys.modules["google"] = fake_google
    sys.modules["google.genai"] = fake_genai
    sys.modules["google.genai.types"] = fake_genai_types

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for key, prev in [
            ("google", prev_google),
            ("google.genai", prev_genai),
            ("google.genai.types", prev_genai_types),
        ]:
            if prev is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = prev

    return module


_module = _load_module()

_parse_pmc_reference_records = _module._parse_pmc_reference_records
_resolve_pmids_from_pmc_refs = _module._resolve_pmids_from_pmc_refs
load_pmc_reference_candidates = _module.load_pmc_reference_candidates


# ── XML fixtures ──────────────────────────────────────────────────────────────

_XML_WITH_PMIDS = """<?xml version="1.0"?>
<article>
  <back>
    <ref-list>
      <ref id="r1">
        <element-citation>
          <pub-id pub-id-type="pmid">11111111</pub-id>
          <pub-id pub-id-type="doi">10.1000/test.1</pub-id>
          <article-title>Title One</article-title>
          <year>2005</year>
        </element-citation>
      </ref>
      <ref id="r2">
        <element-citation>
          <pub-id pub-id-type="pmid">22222222</pub-id>
          <article-title>Title Two</article-title>
          <year>2010</year>
        </element-citation>
      </ref>
    </ref-list>
  </back>
</article>"""

_XML_DOI_ONLY = """<?xml version="1.0"?>
<article>
  <back>
    <ref-list>
      <ref id="r1">
        <element-citation>
          <pub-id pub-id-type="doi">10.1234/doi.only.1</pub-id>
          <article-title>DOI Only Paper</article-title>
          <year>2015</year>
        </element-citation>
      </ref>
      <ref id="r2">
        <mixed-citation>
          <pub-id pub-id-type="doi">10.9999/mixed.doi</pub-id>
          <article-title>Mixed Citation Paper</article-title>
          <year>2018</year>
        </mixed-citation>
      </ref>
    </ref-list>
  </back>
</article>"""

_XML_WITH_NAMESPACE = (
    'xmlns="https://jats.nlm.nih.gov/ns/archiving/1.3" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)
_XML_NAMESPACE_WRAPPED = f"""<?xml version="1.0"?>
<article {_XML_WITH_NAMESPACE}>
  <back>
    <ref-list>
      <ref id="r1">
        <element-citation>
          <pub-id pub-id-type="pmid">33333333</pub-id>
          <article-title>Namespace Paper</article-title>
          <year>2020</year>
        </element-citation>
      </ref>
    </ref-list>
  </back>
</article>"""

_XML_NO_REF_LIST = """<?xml version="1.0"?>
<article>
  <body><p>No references here.</p></body>
</article>"""


# ── _parse_pmc_reference_records ──────────────────────────────────────────────


def test_parse_pmc_ref_list_direct_pmids() -> None:
    refs = _parse_pmc_reference_records(_XML_WITH_PMIDS)
    assert len(refs) == 2
    assert refs[0]["pmid"] == "11111111"
    assert refs[0]["doi"] == "10.1000/test.1"
    assert refs[0]["title"] == "Title One"
    assert refs[0]["year"] == "2005"
    assert refs[1]["pmid"] == "22222222"


def test_parse_pmc_ref_list_doi_only() -> None:
    refs = _parse_pmc_reference_records(_XML_DOI_ONLY)
    assert len(refs) == 2
    assert refs[0]["pmid"] == ""
    assert refs[0]["doi"] == "10.1234/doi.only.1"
    assert refs[0]["title"] == "DOI Only Paper"
    assert refs[0]["year"] == "2015"
    # Second ref uses mixed-citation
    assert refs[1]["doi"] == "10.9999/mixed.doi"
    assert refs[1]["title"] == "Mixed Citation Paper"


def test_parse_pmc_ref_list_namespace() -> None:
    """Namespace-wrapped XML must still parse — namespace stripping is required."""
    refs = _parse_pmc_reference_records(_XML_NAMESPACE_WRAPPED)
    assert len(refs) == 1
    assert refs[0]["pmid"] == "33333333"
    assert refs[0]["title"] == "Namespace Paper"


def test_parse_pmc_ref_list_empty() -> None:
    """No <ref-list> element → empty list returned."""
    refs = _parse_pmc_reference_records(_XML_NO_REF_LIST)
    assert refs == []


# ── _resolve_pmids_from_pmc_refs ──────────────────────────────────────────────


def test_resolve_pmids_direct() -> None:
    """Direct PMIDs should be collected without any HTTP calls."""
    refs = [
        {"pmid": "11111111", "doi": "", "title": "T1", "year": "2005"},
        {"pmid": "22222222", "doi": "", "title": "T2", "year": "2010"},
    ]
    with patch.object(_module, "pubmed_esearch") as mock_esearch:
        mock_esearch.side_effect = AssertionError("No HTTP calls expected for direct PMIDs")
        # No title-only refs either, so pubmed_esearch must never be called.
        result = _resolve_pmids_from_pmc_refs(refs, api_key=None)

    assert "11111111" in result
    assert "22222222" in result
    mock_esearch.assert_not_called()


def test_resolve_pmids_doi_batch() -> None:
    """3 DOIs (no PMIDs) → exactly 1 batched esearch call (all fit in one batch)."""
    refs = [
        {"pmid": "", "doi": "10.1000/a", "title": "A", "year": "2001"},
        {"pmid": "", "doi": "10.1000/b", "title": "B", "year": "2002"},
        {"pmid": "", "doi": "10.1000/c", "title": "C", "year": "2003"},
    ]
    with patch.object(_module, "pubmed_esearch", return_value=["99", "88", "77"]) as mock_esearch:
        with patch.object(_module.time, "sleep"):
            result = _resolve_pmids_from_pmc_refs(refs, api_key=None)

    # All three DOIs → one batched call (3 < DOI_BATCH_SIZE=50)
    doi_batch_calls = [
        call
        for call in mock_esearch.call_args_list
        if "[doi]" in str(call)
    ]
    assert len(doi_batch_calls) == 1, f"Expected 1 DOI batch call, got {len(doi_batch_calls)}"
    assert set(result) >= {"99", "88", "77"}


# ── _lookup_pmcid via load_pmc_reference_candidates ───────────────────────────
# The script embeds pmcid lookup in load_pmc_reference_candidates via the row dict.


def test_lookup_pmcid_found(tmp_path: Path) -> None:
    """When row has a valid pmcid, function attempts to fetch the article."""
    row: dict[str, Any] = {"pmcid": "7127964"}
    with patch.object(_module, "_load_local_pmc_article_xml", return_value=None):
        with patch.object(_module, "_fetch_remote_pmc_article_xml", return_value=None) as mock_fetch:
            pmids, details = load_pmc_reference_candidates(
                data_dir=tmp_path,
                meta_pmid="32078973",
                row=row,
                api_key=None,
            )
    # fetch was attempted with the PMCID from the row
    mock_fetch.assert_called_once_with("7127964")
    assert pmids == []
    assert details["pmc_source_detail"] == "pmc_article_unavailable"


def test_lookup_pmcid_missing(tmp_path: Path) -> None:
    """When row has blank pmcid, function returns early with no HTTP calls."""
    row: dict[str, Any] = {"pmcid": ""}
    with patch.object(_module, "_fetch_remote_pmc_article_xml") as mock_fetch:
        pmids, details = load_pmc_reference_candidates(
            data_dir=tmp_path,
            meta_pmid="32078973",
            row=row,
            api_key=None,
        )
    mock_fetch.assert_not_called()
    assert pmids == []
    assert details["pmc_source_detail"] == "missing_pmcid"


# ── load_pmc_reference_candidates: failure paths ──────────────────────────────


def test_load_pmc_no_pmcid(tmp_path: Path) -> None:
    """Missing PMCID → returns empty list, no HTTP requests."""
    row: dict[str, Any] = {}
    with patch.object(_module, "_fetch_remote_pmc_article_xml") as mock_fetch:
        pmids, details = load_pmc_reference_candidates(
            data_dir=tmp_path,
            meta_pmid="00000000",
            row=row,
            api_key=None,
        )
    assert pmids == []
    assert details["n_reference_records"] == 0
    mock_fetch.assert_not_called()


def test_load_pmc_fetch_failure(tmp_path: Path) -> None:
    """Both local and remote fetch fail → returns empty list."""
    row: dict[str, Any] = {"pmcid": "9999999"}
    with patch.object(_module, "_load_local_pmc_article_xml", return_value=None):
        with patch.object(_module, "_fetch_remote_pmc_article_xml", return_value=None):
            pmids, details = load_pmc_reference_candidates(
                data_dir=tmp_path,
                meta_pmid="12345678",
                row=row,
                api_key=None,
            )
    assert pmids == []
    assert details["pmc_source_detail"] == "pmc_article_unavailable"
    assert details["n_reference_records"] == 0
