"""
SPARQL endpoint module for BR-KG

Provides W3C SPARQL 1.1 compliant endpoint with integration to Neo4j backend.
"""

from .endpoint import SPARQLEndpoint
from .translator import SPARQLToCypherTranslator
from .federation import FederationQueryHandler

__all__ = ['SPARQLEndpoint', 'SPARQLToCypherTranslator', 'FederationQueryHandler']