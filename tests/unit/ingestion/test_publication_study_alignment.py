import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from brain_researcher.core.ingestion.loaders.publication_study_alignment import (
    link_publication_study_alignments,
)
from brain_researcher.services.br_kg.graph.fake_graph_database import FakeGraphDB


class _Result(list):
    def single(self):
        return self[0] if self else None

    def consume(self):
        return None


class BulkFakeGraphDB(FakeGraphDB):
    def _run(self, query, params=None):
        params = params or {}
        normalized = " ".join(query.split())

        if normalized.startswith(
            "MATCH (s:Study) RETURN s.id AS node_id, properties(s) AS props"
        ):
            rows = [
                {"node_id": node_id, "props": dict(props)}
                for node_id, props in self.find_nodes("Study")
            ]
            return _Result(rows)

        if normalized.startswith(
            "MATCH (p:Publication) WHERE (NOT $use_filter OR p.id IN $publication_ids)"
        ):
            rows = []
            use_filter = bool(params.get("use_filter"))
            allowed = set(params.get("publication_ids") or [])
            limit = params.get("limit")
            for node_id, props in sorted(
                self.find_nodes("Publication"), key=lambda item: item[0]
            ):
                if use_filter and node_id not in allowed:
                    continue
                rows.append({"node_id": node_id, "props": dict(props)})
                if limit is not None and len(rows) >= int(limit):
                    break
            return _Result(rows)

        if normalized.startswith(
            "UNWIND $rows AS row OPTIONAL MATCH (:Publication {id: row.publication_id})-[r:ALIGNS_WITH]->(:Study {id: row.study_id}) RETURN count(r) AS existing"
        ):
            existing = 0
            for row in params.get("rows", []):
                if self.find_relationships(
                    start_node=row["publication_id"],
                    end_node=row["study_id"],
                    rel_type="ALIGNS_WITH",
                ):
                    existing += 1
            return _Result([{"existing": existing}])

        if normalized.startswith(
            "UNWIND $rows AS row MATCH (p:Publication {id: row.publication_id}) MATCH (s:Study {id: row.study_id}) MERGE (p)-[r:ALIGNS_WITH]->(s) SET r += row.props RETURN count(r) AS total"
        ):
            total = 0
            for row in params.get("rows", []):
                if self.create_relationship(
                    row["publication_id"],
                    row["study_id"],
                    "ALIGNS_WITH",
                    dict(row.get("props") or {}),
                ):
                    total += 1
            return _Result([{"total": total}])

        raise AssertionError(f"Unhandled query: {query}")


class TestPublicationStudyAlignment(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeGraphDB()

    def _create_study(self, study_id: str, **props: object) -> str:
        payload = {"id": study_id, **props}
        return self.db.create_node("Study", payload, node_id=study_id)

    def _create_publication(self, pub_id: str, **props: object) -> str:
        payload = {"id": pub_id, **props}
        return self.db.create_node("Publication", payload, node_id=pub_id)

    def test_links_by_doi_then_pmid_then_url_and_is_idempotent(self) -> None:
        study_doi = self._create_study(
            "study-doi",
            doi="10.1016/j.neuroimage.2005.08.010",
            source="pubmed",
        )
        study_pmid = self._create_study("study-pmid", pmid="12345678", source="pubmed")
        study_url = self._create_study(
            "study-url",
            url="https://example.org/studies/resting-state",
            source="scholarly_metadata",
        )

        pub_doi = self._create_publication(
            "10.1016/j.neuroimage.2005.08.010",
            doi="10.1016/j.neuroimage.2005.08.010",
            source="scholarly_metadata",
        )
        pub_pmid = self._create_publication(
            "12345678",
            pmid="12345678",
            source="pubmed",
        )
        pub_url = self._create_publication(
            "paper:resting-state",
            url="HTTPS://EXAMPLE.ORG/STUDIES/RESTING-STATE",
            source="manual",
        )

        stats_first = link_publication_study_alignments(self.db)
        stats_second = link_publication_study_alignments(self.db)

        self.assertEqual(stats_first["publications_seen"], 3)
        self.assertEqual(stats_first["publications_with_alignment"], 3)
        self.assertEqual(stats_first["alignment_edges_created"], 3)
        self.assertEqual(stats_first["doi_matched"], 1)
        self.assertEqual(stats_first["pmid_matched"], 1)
        self.assertEqual(stats_first["url_matched"], 1)
        self.assertEqual(stats_second["alignment_edges_created"], 0)
        self.assertEqual(stats_second["alignment_edges_existing"], 3)

        doi_links = self.db.find_relationships(
            start_node=pub_doi, end_node=study_doi, rel_type="ALIGNS_WITH"
        )
        pmid_links = self.db.find_relationships(
            start_node=pub_pmid, end_node=study_pmid, rel_type="ALIGNS_WITH"
        )
        url_links = self.db.find_relationships(
            start_node=pub_url, end_node=study_url, rel_type="ALIGNS_WITH"
        )

        self.assertEqual(len(doi_links), 1)
        self.assertEqual(len(pmid_links), 1)
        self.assertEqual(len(url_links), 1)
        self.assertEqual(doi_links[0][2]["method"], "doi_exact")
        self.assertEqual(pmid_links[0][2]["method"], "pmid_exact")
        self.assertEqual(url_links[0][2]["method"], "url_exact")

    def test_doi_ambiguity_falls_back_to_pmid(self) -> None:
        self._create_study(
            "study-ambiguous-a",
            doi="10.1000/ambiguous",
            source="pubmed",
        )
        self._create_study(
            "study-ambiguous-b",
            doi="10.1000/ambiguous",
            source="pubmed",
        )
        pmid_study = self._create_study("study-pmid-fallback", pmid="87654321")

        publication = self._create_publication(
            "paper:fallback",
            doi="10.1000/ambiguous",
            pmid="87654321",
            source="pubmed",
        )

        stats = link_publication_study_alignments(self.db)

        self.assertEqual(stats["doi_ambiguous"], 1)
        self.assertEqual(stats["pmid_matched"], 1)
        links = self.db.find_relationships(
            start_node=publication, end_node=pmid_study, rel_type="ALIGNS_WITH"
        )
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][2]["match_field"], "pmid")

    def test_title_like_url_can_align_publication_to_study(self) -> None:
        study = self._create_study(
            "study-url-title",
            title="https://example.org/studies/resting-state",
        )
        publication = self._create_publication(
            "paper:url-title",
            title="https://example.org/studies/resting-state",
            source="openneuro_glmfitlins",
        )

        stats = link_publication_study_alignments(self.db)

        self.assertEqual(stats["url_matched"], 1)
        links = self.db.find_relationships(
            start_node=publication, end_node=study, rel_type="ALIGNS_WITH"
        )
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][2]["method"], "url_exact")
        self.assertEqual(
            links[0][2]["match_value"],
            "https://example.org/studies/resting-state",
        )

    def test_bulk_path_uses_run_interface(self) -> None:
        db = BulkFakeGraphDB()
        study = db.create_node(
            "Study",
            {"id": "study-bulk", "doi": "10.2000/bulk"},
            node_id="study-bulk",
        )
        publication = db.create_node(
            "Publication",
            {"id": "10.2000/bulk", "doi": "10.2000/bulk", "source": "pubmed"},
            node_id="10.2000/bulk",
        )

        stats = link_publication_study_alignments(db)

        self.assertEqual(stats["alignment_edges_created"], 1)
        self.assertEqual(
            db.find_relationships(
                start_node=publication, end_node=study, rel_type="ALIGNS_WITH"
            ),
            [
                (
                    publication,
                    study,
                    {
                        "source": "pubmed",
                        "method": "doi_exact",
                        "methods": ["doi_exact"],
                        "confidence": 1.0,
                        "confidence_tier": "imported",
                        "match_field": "doi",
                        "match_value": "10.2000/bulk",
                        "type": "ALIGNS_WITH",
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
