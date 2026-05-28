import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

# Provide dummy faiss to avoid optional dependency errors
faiss_module = ModuleType("faiss")
faiss_module.__spec__ = SimpleNamespace(name="faiss")
sys.modules.setdefault("faiss", faiss_module)
nimare_module = ModuleType("nimare")
dataset_module = ModuleType("nimare.dataset")
dataset_module.Dataset = SimpleNamespace(
    load=lambda p: SimpleNamespace(metadata=None, coordinates=None)
)
nimare_module.dataset = dataset_module
sys.modules.setdefault("nimare", nimare_module)
sys.modules.setdefault("nimare.dataset", dataset_module)

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

from brain_researcher.core.analysis import rag_retrieval

# Get cache from rag_retrieval module after import
cache = rag_retrieval.cache


class TestRAGCaching(unittest.TestCase):
    def setUp(self):
        cache.invalidate("pubmed")
        cache.invalidate("nimare_spatial")

    def test_pubmed_cache_hit_and_bypass(self):
        calls = {"search": 0, "fetch": 0, "read": 0}

        def fake_esearch(*args, **kwargs):
            calls["search"] += 1
            handle = MagicMock()
            handle.close = MagicMock()
            return handle

        def fake_efetch(*args, **kwargs):
            calls["fetch"] += 1
            handle = MagicMock()
            handle.close = MagicMock()
            return handle

        def fake_read(handle):
            calls["read"] += 1
            # Odd reads are for search results, even reads are for fetch results
            if calls["read"] % 2 == 1:  # Search result
                return {"IdList": ["1"], "Count": "1"}
            else:  # Fetch result
                return {
                    "PubmedArticle": [
                        {
                            "MedlineCitation": {
                                "PMID": "1",
                                "Article": {
                                    "ArticleTitle": "T",
                                    "Abstract": {"AbstractText": ["A"]},
                                },
                            }
                        }
                    ]
                }

        with (
            patch(
                "brain_researcher.core.analysis.rag_retrieval.Entrez.esearch",
                side_effect=fake_esearch,
            ),
            patch(
                "brain_researcher.core.analysis.rag_retrieval.Entrez.efetch",
                side_effect=fake_efetch,
            ),
            patch(
                "brain_researcher.core.analysis.rag_retrieval.Entrez.read",
                side_effect=fake_read,
            ),
        ):
            res1 = rag_retrieval.query_pubmed_real(
                "test", max_results=1, force_refresh=True
            )
            self.assertEqual(calls["search"], 1)
            res2 = rag_retrieval.query_pubmed_real("test", max_results=1)
            self.assertEqual(calls["search"], 1)  # cache hit
            self.assertEqual(res1, res2)
            res3 = rag_retrieval.query_pubmed_real(
                "test", max_results=1, force_refresh=True
            )
            self.assertEqual(calls["search"], 2)  # bypassed
            self.assertEqual(res3, res1)

    def test_spatial_cache_hit_and_bypass(self):
        rag = rag_retrieval.RAGKnowledgeSystem()
        rag.nimare_dataset = SimpleNamespace(metadata=pd.DataFrame({"id": ["s1"]}))
        rag.coordinates_df = pd.DataFrame({"id": ["s1"], "x": [0], "y": [0], "z": [0]})

        res1 = rag.retrieve_spatial([0, 0, 0], radius=5, top_k=1, force_refresh=True)
        rag.coordinates_df.loc[0, "x"] = 50
        res2 = rag.retrieve_spatial([0, 0, 0], radius=5, top_k=1)
        self.assertEqual(res1, res2)  # cached
        res3 = rag.retrieve_spatial([0, 0, 0], radius=5, top_k=1, force_refresh=True)
        self.assertNotEqual(res1, res3)


if __name__ == "__main__":
    unittest.main()
