from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scripts.tools.etl import backfill_onvoc_text_links as script

CFS_TERMS = [
    "chronic fatigue syndrome",
    "cfs",
    "myalgic encephalomyelitis",
    "me",
    "me/cfs",
]

DISEASE_ALIAS_MAP = Path("configs/legacy/mappings/disease_alias_overrides.yaml")
RISKY_SHORT_TEXT_ALIASES = {
    "ONVOC_0000143": "oa",
    "ONVOC_0000153": "me",
    "ONVOC_0000176": "ad",
    "ONVOC_0000178": "pd",
    "ONVOC_0000179": "ms",
    "ONVOC_0000184": "ds",
    "ONVOC_0000197": "hd",
}


class FakeResult:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    def single(self) -> dict[str, Any]:
        return self._row


class FakeSession:
    def __init__(self, driver: "FakeDriver") -> None:
        self.driver = driver

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def run(self, cypher: str, params: dict[str, Any]) -> FakeResult:
        self.driver.last_cypher = cypher
        self.driver.last_params = params
        term_regex = params.get("term_regex") or ""
        acronym_regex = params.get("acronym_regex") or ""
        matched = 0
        for text in self.driver.texts:
            txt = str(text or "").lower()
            if (term_regex and re.match(term_regex, txt)) or (
                acronym_regex and re.match(acronym_regex, txt)
            ):
                matched += 1
        return FakeResult({"matched": matched})


class FakeDriver:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.last_cypher = ""
        self.last_params: dict[str, Any] = {}

    def session(self, database: str | None = None) -> FakeSession:
        return FakeSession(self)


def _dry_run_cfs_task_match(text: str) -> tuple[dict[str, Any], FakeDriver]:
    terms = script._normalize_terms(CFS_TERMS)
    driver = FakeDriver([text])

    result = script._run_for_category(
        driver=driver,
        database=None,
        concept_id="ONVOC_0000153",
        spec=script.ENTITY_SPECS["tasks"],
        terms=terms,
        acronym_regex="",
        source="config_text_backfill",
        confidence=0.5,
        dry_run=True,
    )
    return result, driver


def test_cfs_short_me_does_not_link_working_memory_task() -> None:
    result, driver = _dry_run_cfs_task_match("working memory task")

    assert result["matched"] == 0
    assert "me" not in driver.last_params["terms"]
    assert "CONTAINS" not in driver.last_cypher
    assert "txt =~ $term_regex" in driver.last_cypher


def test_cfs_phrase_links_chronic_fatigue_syndrome_study() -> None:
    result, driver = _dry_run_cfs_task_match("chronic fatigue syndrome study")

    assert result["matched"] == 1
    assert "chronic fatigue syndrome" in driver.last_params["terms"]


def test_disease_alias_overrides_filter_short_text_aliases_for_backfill() -> None:
    for concept_id, alias in RISKY_SHORT_TEXT_ALIASES.items():
        terms, _acronyms = script._load_alias_overrides(DISEASE_ALIAS_MAP, concept_id)
        normalized_terms = script._normalize_terms(terms)

        assert alias in {term.lower() for term in terms}
        assert alias not in normalized_terms
