"""
External Graph Federation for BR-KG

Provides integration with external knowledge graphs like Wikidata and DBpedia.
"""

from .wikidata import WikidataConnector
from .dbpedia import DBpediaConnector
from .merger import FederationResultMerger

__all__ = ['WikidataConnector', 'DBpediaConnector', 'FederationResultMerger']