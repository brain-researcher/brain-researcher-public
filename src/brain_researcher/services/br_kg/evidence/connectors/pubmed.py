"""
PubMed evidence connector.

Provides async search for scientific publications via NCBI E-utilities API.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ..models import EvidenceItem, EvidenceSource, EvidenceType
from ..protocols import ConnectorError
from .base import BaseConnector


class PubMedConnector(BaseConnector):
    """
    Connector for searching PubMed publications.

    Uses NCBI E-utilities API with proper rate limiting and error handling.
    """

    ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        """
        Initialize PubMed connector.

        Args:
            api_key: Optional NCBI API key for higher rate limits
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
        """
        super().__init__(timeout=timeout, max_retries=max_retries)
        self.api_key = api_key

    @property
    def source(self) -> EvidenceSource:
        return EvidenceSource.PUBMED

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[EvidenceItem]:
        """
        Search PubMed for publications.

        Args:
            query: Search query
            limit: Maximum results
            filters: Optional filters:
                - year_from: Start year
                - year_to: End year
                - article_type: Article type filter

        Returns:
            List of evidence items
        """
        # Step 1: Search for PMIDs
        pmids = await self._search_pmids(query, limit, filters)
        if not pmids:
            return []

        # Step 2: Fetch publication details
        publications = await self._fetch_details(pmids)
        return [self._to_evidence_item(pub) for pub in publications]

    async def get_by_id(self, item_id: str) -> EvidenceItem | None:
        """Get publication by PMID."""
        # Strip "pmid:" prefix if present
        pmid = item_id.replace("pmid:", "")
        publications = await self._fetch_details([pmid])
        if publications:
            return self._to_evidence_item(publications[0])
        return None

    async def _search_pmids(
        self,
        query: str,
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[str]:
        """Search for PMIDs matching the query."""
        params = {
            "db": "pubmed",
            "term": self._build_query(query, filters),
            "retmax": limit,
            "retmode": "json",
            "sort": "relevance",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            data = await self._fetch_json(self.ESEARCH_URL, params)
            return data.get("esearchresult", {}).get("idlist", [])
        except ConnectorError:
            raise
        except Exception as e:
            raise ConnectorError(self.source, f"Search failed: {e}", e)

    def _build_query(self, query: str, filters: dict[str, Any] | None) -> str:
        """Build PubMed query with filters."""
        parts = [query]

        if filters:
            if year_from := filters.get("year_from"):
                parts.append(f"({year_from}[pdat] : 3000[pdat])")
            if year_to := filters.get("year_to"):
                parts.append(f"(1900[pdat] : {year_to}[pdat])")
            if article_type := filters.get("article_type"):
                parts.append(f"{article_type}[pt]")

        return " AND ".join(parts)

    async def _fetch_details(self, pmids: list[str]) -> list[dict[str, Any]]:
        """Fetch publication details for given PMIDs."""
        if not pmids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            xml_text = await self._fetch_xml(self.EFETCH_URL, params)
            return self._parse_pubmed_xml(xml_text)
        except ConnectorError:
            raise
        except Exception as e:
            raise ConnectorError(self.source, f"Fetch details failed: {e}", e)

    def _parse_pubmed_xml(self, xml_text: str) -> list[dict[str, Any]]:
        """Parse PubMed XML response."""
        publications = []

        try:
            root = ET.fromstring(xml_text)

            for article in root.findall(".//PubmedArticle"):
                pub = self._parse_article(article)
                if pub:
                    publications.append(pub)

        except ET.ParseError as e:
            self.logger.warning(f"Failed to parse PubMed XML: {e}")

        return publications

    def _parse_article(self, article: ET.Element) -> dict[str, Any] | None:
        """Parse a single PubMed article element."""
        medline = article.find("MedlineCitation")
        if medline is None:
            return None

        pmid_elem = medline.find("PMID")
        if pmid_elem is None:
            return None

        pmid = pmid_elem.text

        article_data = medline.find("Article")
        if article_data is None:
            return {"pmid": pmid}

        # Title
        title_elem = article_data.find("ArticleTitle")
        title = title_elem.text if title_elem is not None else ""

        # Abstract
        abstract_elem = article_data.find(".//AbstractText")
        abstract = abstract_elem.text if abstract_elem is not None else ""

        # Authors
        authors = []
        for author in article_data.findall(".//Author"):
            last_name = author.find("LastName")
            first_name = author.find("ForeName")
            if last_name is not None:
                name = last_name.text
                if first_name is not None:
                    name = f"{first_name.text} {name}"
                authors.append(name)

        # Journal
        journal_elem = article_data.find(".//Journal/Title")
        journal = journal_elem.text if journal_elem is not None else ""

        # Year
        year = None
        pub_date = article_data.find(".//PubDate/Year")
        if pub_date is not None:
            try:
                year = int(pub_date.text)
            except (ValueError, TypeError):
                pass

        # DOI
        doi = None
        for id_elem in article.findall(".//ArticleId"):
            if id_elem.get("IdType") == "doi":
                doi = id_elem.text
                break

        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": authors,
            "journal": journal,
            "year": year,
            "doi": doi,
        }

    def _to_evidence_item(self, pub: dict[str, Any]) -> EvidenceItem:
        """Convert parsed publication to EvidenceItem."""
        pmid = pub.get("pmid", "")

        # Build description from abstract
        abstract = pub.get("abstract", "")
        description = abstract[:300] + "..." if len(abstract) > 300 else abstract

        return EvidenceItem(
            id=f"pmid:{pmid}",
            source=self.source,
            item_type=EvidenceType.PUBLICATION,
            title=pub.get("title", ""),
            description=description if description else None,
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            doi=pub.get("doi"),
            score=0.8,  # Default score
            metadata={
                "authors": pub.get("authors", []),
                "journal": pub.get("journal"),
                "year": pub.get("year"),
            },
        )
