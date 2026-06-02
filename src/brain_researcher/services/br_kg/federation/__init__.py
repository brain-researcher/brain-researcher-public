"""
External Graph Federation for BR-KG

Provides integration with external knowledge graphs like Wikidata and DBpedia.
"""

from .dbpedia import DBpediaConnector
from .merger import FederationResultMerger
from .wikidata import WikidataConnector

__all__ = ["WikidataConnector", "DBpediaConnector", "FederationResultMerger"]
