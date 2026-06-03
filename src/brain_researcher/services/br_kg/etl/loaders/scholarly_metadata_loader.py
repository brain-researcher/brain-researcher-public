#!/usr/bin/env python3
"""
Scholarly Metadata Loader
-------------------------

Harvests metadata from Crossref/OpenAlex (with optional ORCID/ROR resolution) and
upserts Publications, Authors, Institutions, and citation edges into NeoKG.

The loader prefers cached JSON/NDJSON files but can also download the metadata
directly from public APIs given a DOI list or filter configuration.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/br-kg/raw/scholarly_metadata")
DEFAULT_HTTP_TIMEOUT = 20


def _read_metadata_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Metadata file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def _slugify(text: str) -> str:
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "unknown"


class ScholarlyMetadataLoader:
    """Loader for Crossref/OpenAlex/ORCID/ROR style payloads."""

    def __init__(
        self,
        cache_dir: str | None = None,
        http_timeout: int = DEFAULT_HTTP_TIMEOUT,
        crossref_mailto: str | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.http_timeout = http_timeout
        self.crossref_mailto = crossref_mailto

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_records(
        self,
        *,
        metadata_path: str | None = None,
        dois: Sequence[str] | None = None,
        openalex_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        if metadata_path:
            records = _read_metadata_file(Path(metadata_path))
            logger.info(
                "Loaded %d scholarly records from %s", len(records), metadata_path
            )
            return records

        if not dois and not openalex_filter:
            raise ValueError(
                "ScholarlyMetadataLoader requires either `metadata_path`, `dois`, or `openalex_filter`."
            )

        harvested: list[dict[str, Any]] = []
        if dois:
            for doi in dois:
                try:
                    record = self._harvest_for_doi(doi)
                    harvested.append(record)
                except Exception as exc:
                    logger.error("Failed to harvest metadata for DOI %s: %s", doi, exc)
        if openalex_filter:
            harvested.extend(self._harvest_openalex_filter(openalex_filter))

        logger.info("Harvested %d scholarly records from remote APIs", len(harvested))
        return harvested

    def ingest(
        self,
        db,
        records: Iterable[dict[str, Any]] | None = None,
        **load_kwargs: Any,
    ) -> dict[str, Any]:
        payloads = (
            list(records) if records is not None else self.load_records(**load_kwargs)
        )
        stats = {
            "publications_upserted": 0,
            "authors_upserted": 0,
            "institutions_upserted": 0,
            "authorship_edges": 0,
            "affiliation_edges": 0,
            "citation_edges": 0,
            "errors": [],
        }

        for record in payloads:
            try:
                self._ingest_single(db, record, stats)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception(
                    "Failed to ingest scholarly record (%s)", record.get("doi")
                )
                stats["errors"].append({"doi": record.get("doi"), "error": str(exc)})

        return stats

    def make_adapter(self, base_kwargs: dict[str, Any] | None = None):
        """Return an on-demand adapter that fetches metadata without writes."""
        return ScholarlyMetadataAdapter(self, base_kwargs or {})

    # ------------------------------------------------------------------
    # Harvest helpers
    # ------------------------------------------------------------------
    def _harvest_for_doi(self, doi: str) -> dict[str, Any]:
        crossref_json = self._fetch_crossref_work(doi)
        openalex_json = self._fetch_openalex_for_doi(doi)
        return self._merge_crossref_openalex(crossref_json, openalex_json)

    def _harvest_openalex_filter(self, filter_expr: str) -> list[dict[str, Any]]:
        endpoint = "https://api.openalex.org/works"
        params = {"filter": filter_expr, "per-page": 200}
        harvested: list[dict[str, Any]] = []
        cursor = "*"

        while cursor:
            params["cursor"] = cursor
            data = self._http_get_json(endpoint, params=params)
            results = data.get("results", [])
            for result in results:
                doi = (result.get("doi") or "").lower().replace("https://doi.org/", "")
                crossref_json = self._fetch_crossref_work(doi) if doi else None
                record = self._merge_crossref_openalex(crossref_json, result)
                harvested.append(record)

            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(0.5)  # be gentle with the API

        return harvested

    def _fetch_crossref_work(self, doi: str) -> dict[str, Any] | None:
        if not doi:
            return None
        cache_path = self.cache_dir / f"crossref_{_slugify(doi)}.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return cached
            logger.debug(
                "Discarding cached Crossref payload for %s; expected dict, got %s",
                doi,
                type(cached).__name__,
            )
            return None

        headers = {}
        if self.crossref_mailto:
            headers["mailto"] = self.crossref_mailto
        url = f"https://api.crossref.org/works/{doi}"
        try:
            data = self._http_get_json(url, headers=headers)
        except requests.HTTPError as exc:
            logger.warning("Crossref lookup failed for %s: %s", doi, exc)
            return None

        message = data.get("message") if isinstance(data, dict) else None

        if isinstance(message, dict):
            cache_path.write_text(
                json.dumps(message, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return message

        if message:
            logger.warning(
                "Crossref returned non-dict message for %s: %s", doi, str(message)[:200]
            )
        else:
            logger.warning("Crossref response for %s lacked message payload", doi)

        cache_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return None

    def _fetch_openalex_for_doi(self, doi: str) -> dict[str, Any] | None:
        if not doi:
            return None
        cache_path = self.cache_dir / f"openalex_{_slugify(doi)}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        url = "https://api.openalex.org/works"
        params = {"filter": f"doi:{doi}"}
        data = self._http_get_json(url, params=params)
        results = data.get("results") or []
        if results:
            record = results[0]
            cache_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return record
        return None

    def _http_get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = requests.get(
            url, params=params, headers=headers, timeout=self.http_timeout
        )
        response.raise_for_status()
        return response.json()

    def _merge_crossref_openalex(
        self,
        crossref_json: dict[str, Any] | None,
        openalex_json: dict[str, Any] | None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {}

        if crossref_json:
            record["doi"] = (crossref_json.get("DOI") or "").lower()
            record["title"] = " ".join(
                (crossref_json.get("title") or [""])[0:1]
            ).strip()
            record["journal"] = " ".join(
                (crossref_json.get("container-title") or [""])[0:1]
            ).strip()
            record["issn"] = crossref_json.get("ISSN")
            record["publication_year"] = (
                (crossref_json.get("issued") or {}).get("date-parts") or [[None]]
            )[0][0]
            record["publication_date"] = crossref_json.get("created", {}).get(
                "date-time"
            )
            record["keywords"] = crossref_json.get("subject")
            record["authors"] = []
            for auth in crossref_json.get("author", []) or []:
                affiliations = []
                for aff in auth.get("affiliation", []) or []:
                    affiliations.append(
                        {
                            "name": aff.get("name"),
                            "ror": None,
                            "country": aff.get("country"),
                        }
                    )
                record["authors"].append(
                    {
                        "name": " ".join(
                            filter(None, [auth.get("given"), auth.get("family")])
                        ).strip(),
                        "orcid": auth.get("ORCID"),
                        "roles": None,
                        "institutions": affiliations,
                    }
                )
            record["citations"] = [
                ref.get("DOI")
                for ref in crossref_json.get("reference", [])
                if ref.get("DOI")
            ]

        if openalex_json:
            record.setdefault("doi", openalex_json.get("doi"))
            record.setdefault("title", openalex_json.get("title"))
            host_venue = openalex_json.get("host_venue") or {}
            record.setdefault("journal", host_venue.get("display_name"))
            record.setdefault("publication_year", openalex_json.get("publication_year"))
            record.setdefault("publication_date", openalex_json.get("publication_date"))
            record.setdefault("openalex_id", openalex_json.get("id"))
            record.setdefault(
                "keywords",
                [
                    topic.get("display_name")
                    for topic in openalex_json.get("topics", [])
                ],
            )
            authorships = openalex_json.get("authorships") or []
            if authorships:
                record["authors"] = []
                for authorship in authorships:
                    author = authorship.get("author", {})
                    institutions = []
                    for inst in authorship.get("institutions", []) or []:
                        institutions.append(
                            {
                                "name": inst.get("display_name"),
                                "ror": inst.get("ror"),
                                "country": inst.get("country_code"),
                            }
                        )
                    record["authors"].append(
                        {
                            "name": author.get("display_name"),
                            "orcid": author.get("orcid"),
                            "roles": authorship.get("author_position"),
                            "institutions": institutions,
                        }
                    )
            if not record.get("citations"):
                record["citations"] = [
                    cited.get("cited_work")
                    for cited in openalex_json.get("referenced_works", []) or []
                ]

        return record

    # ------------------------------------------------------------------
    # Graph ingestion helpers
    # ------------------------------------------------------------------
    def _ingest_single(self, db, record: dict[str, Any], stats: dict[str, Any]) -> None:
        doi = record.get("doi")
        if not doi:
            logger.debug("Skipping scholarly record without DOI: %s", record)
            return

        publication_props = {
            "id": doi,
            "doi": doi,
            "title": record.get("title"),
            "journal": record.get("journal"),
            "issn": record.get("issn"),
            "publication_year": record.get("publication_year"),
            "publication_date": record.get("publication_date"),
            "openalex_id": record.get("openalex_id"),
            "keywords": record.get("keywords"),
            "source": "scholarly_metadata",
        }
        pub_id = db.create_node("Publication", publication_props, node_id=doi)
        stats["publications_upserted"] += 1

        for author in record.get("authors", []):
            author_name = (author.get("name") or "").strip()
            if not author_name:
                continue
            author_id = author.get("orcid") or f"author:{_slugify(author_name)}"
            author_props = {
                "id": author_id,
                "name": author_name,
                "orcid": author.get("orcid"),
                "roles": author.get("roles"),
                "source": "scholarly_metadata",
            }
            db.create_node("Author", author_props, node_id=author_id)
            stats["authors_upserted"] += 1

            rel_props = {"source": "scholarly_metadata"}
            db.create_relationship(pub_id, author_id, "AUTHORED_BY", rel_props)
            stats["authorship_edges"] += 1

            for institution in author.get("institutions", []) or []:
                inst_name = (institution.get("name") or "").strip()
                if not inst_name:
                    continue
                inst_id = institution.get("ror") or f"institution:{_slugify(inst_name)}"
                inst_props = {
                    "id": inst_id,
                    "name": inst_name,
                    "ror": institution.get("ror"),
                    "country": institution.get("country"),
                    "source": "scholarly_metadata",
                }
                db.create_node("Institution", inst_props, node_id=inst_id)
                stats["institutions_upserted"] += 1

                aff_props = {"source": "scholarly_metadata"}
                db.create_relationship(author_id, inst_id, "AFFILIATED_WITH", aff_props)
                stats["affiliation_edges"] += 1

        for cited in record.get("citations", []) or []:
            cited = cited.strip()
            if not cited:
                continue
            if cited.lower().startswith("https://doi.org/"):
                cited = cited.split("https://doi.org/")[-1]
            fallback_props = {
                "id": cited,
                "doi": cited,
                "source": "scholarly_metadata_stub",
            }
            cited_id = db.create_node("Publication", fallback_props, node_id=cited)
            rel_props = {"source": "scholarly_metadata"}
            db.create_relationship(pub_id, cited_id, "CITES", rel_props)
            stats["citation_edges"] += 1


class ScholarlyMetadataAdapter:
    """Callable adapter for on-demand metadata retrieval."""

    def __init__(
        self, loader: ScholarlyMetadataLoader, base_kwargs: dict[str, Any]
    ) -> None:
        self.loader = loader
        self.base_kwargs = base_kwargs

    def __call__(self, **kwargs: Any) -> list[dict[str, Any]]:
        params = {**self.base_kwargs, **kwargs}
        return self.loader.load_records(
            metadata_path=params.get("metadata_path"),
            dois=params.get("dois"),
            openalex_filter=params.get("openalex_filter"),
        )
