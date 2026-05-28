import os
import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from brain_researcher.core.ingestion.loaders.openneuro_study_links import (
    link_openneuro_dataset_studies,
)
from brain_researcher.services.neurokg.graph.fake_graph_database import FakeGraphDB


class TestOpenNeuroStudyLinks(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeGraphDB()

    def _create_study(self, study_id: str, **props: object) -> str:
        payload = {"id": study_id, **props}
        return self.db.create_node("Study", payload, node_id=study_id)

    def _create_dataset(self, dataset_id: str, **props: object) -> str:
        payload = {"id": dataset_id, **props}
        return self.db.create_node("Dataset", payload, node_id=dataset_id)

    def test_links_via_cite_links_publication_and_fallback(self) -> None:
        cite_study = self._create_study(
            "study-cite",
            doi="10.1016/j.neuroimage.2005.08.010",
            title="https://doi.org/10.1016/j.neuroimage.2005.08.010",
        )
        publication_study = self._create_study(
            "study-pub",
            doi="10.3389/fnins.2012.00080",
            title="https://doi.org/10.3389/fnins.2012.00080",
        )
        fallback_study = self._create_study(
            "study-fallback",
            doi="10.1017/S1355617720000302",
            title="https://doi.org/10.1017/S1355617720000302",
        )

        dataset_cite = self._create_dataset(
            "ds:openneuro:ds000001",
            source_repo_id="ds000001",
            description="OpenNeuro dataset",
        )
        taskspec = self.db.create_node(
            "TaskSpec",
            {
                "id": "ds000001_task-a",
                "dataset": "ds000001",
                "cite_links": ["https://doi.org/10.1016/j.neuroimage.2005.08.010"],
            },
            node_id="ds000001_task-a",
        )
        self.db.create_relationship(dataset_cite, taskspec, "HAS_TASK", {"source": "t"})

        dataset_pub = self._create_dataset(
            "ds:openneuro:ds000002",
            source_repo_id="ds000002",
            description="Another dataset",
        )
        pub = self.db.create_node(
            "Publication",
            {
                "id": "10.3389/fnins.2012.00080",
                "doi": "10.3389/fnins.2012.00080",
                "title": "Schonberg study",
            },
            node_id="10.3389/fnins.2012.00080",
        )
        self.db.create_relationship(dataset_pub, pub, "CITED_BY", {"source": "t"})

        dataset_fallback = self._create_dataset(
            "ds:openneuro:ds000003",
            source_repo_id="ds000003",
            description=(
                "This dataset cites https://doi.org/10.1017/s1355617720000302 "
                "in the description."
            ),
            url="https://openneuro.org/datasets/ds000003",
        )

        stats = link_openneuro_dataset_studies(self.db)

        self.assertEqual(stats["datasets_seen"], 3)
        self.assertEqual(stats["study_links_created"], 3)
        self.assertEqual(stats["cite_links_matched"], 1)
        self.assertEqual(stats["publication_bridge_matched"], 1)
        self.assertEqual(stats["dataset_fallback_matched"], 1)

        cite_links = self.db.find_relationships(
            start_node=dataset_cite, end_node=cite_study, rel_type="CITED_BY"
        )
        pub_links = self.db.find_relationships(
            start_node=dataset_pub, end_node=publication_study, rel_type="CITED_BY"
        )
        fallback_links = self.db.find_relationships(
            start_node=dataset_fallback, end_node=fallback_study, rel_type="CITED_BY"
        )

        self.assertEqual(len(cite_links), 1)
        self.assertEqual(len(pub_links), 1)
        self.assertEqual(len(fallback_links), 1)

    def test_skips_ambiguous_matches_and_is_idempotent(self) -> None:
        study_one = self._create_study(
            "study-1",
            doi="10.1000/ambiguous",
            title="Ambiguous Study",
        )
        study_two = self._create_study(
            "study-2",
            doi="10.1000/ambiguous",
            title="Ambiguous Study",
        )
        dataset = self._create_dataset(
            "ds:openneuro:ds000010",
            source_repo_id="ds000010",
            description="Ambiguous dataset",
        )
        taskspec = self.db.create_node(
            "TaskSpec",
            {
                "id": "ds000010_task-a",
                "dataset": "ds000010",
                "cite_links": ["https://doi.org/10.1000/ambiguous"],
            },
            node_id="ds000010_task-a",
        )
        self.db.create_relationship(dataset, taskspec, "HAS_TASK", {"source": "t"})

        stats_first = link_openneuro_dataset_studies(self.db)
        stats_second = link_openneuro_dataset_studies(self.db)

        self.assertEqual(stats_first["cite_links_unresolved"], 1)
        self.assertEqual(stats_first["study_links_created"], 0)
        self.assertEqual(stats_second["study_links_created"], 0)
        self.assertEqual(
            self.db.find_relationships(start_node=dataset, rel_type="CITED_BY"),
            [],
        )
        self.assertEqual({study_one, study_two}, {"study-1", "study-2"})

    def test_skips_non_openneuro_datasets(self) -> None:
        study_id = self._create_study(
            "study-generic",
            doi="10.1000/example",
            title="https://doi.org/10.1000/example",
        )
        dataset = self._create_dataset(
            "dataset:generic:001",
            source="dandi",
            source_repo_id="DANDI:001",
            description="This dataset cites https://doi.org/10.1000/example",
        )

        stats = link_openneuro_dataset_studies(self.db)

        self.assertEqual(stats["datasets_seen"], 0)
        self.assertEqual(stats["study_links_created"], 0)
        self.assertEqual(
            self.db.find_relationships(
                start_node=dataset, end_node=study_id, rel_type="CITED_BY"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
