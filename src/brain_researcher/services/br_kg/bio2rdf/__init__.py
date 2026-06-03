"""
Bio2RDF Integration Module for BR-KG

Provides federation with Bio2RDF linked data endpoints to enrich
neuroimaging knowledge with biological and biomedical data.
"""

from .bio2rdf_client import (
    Bio2RDFClient,
    create_bio2rdf_client
)

from .ontology_mapper import (
    OntologyMapper,
    OntologyNamespace,
    ConceptMapping,
    create_ontology_mapper
)

from .link_enrichment import (
    LinkEnrichmentEngine,
    EnrichedEntity,
    create_link_enrichment_engine
)

__all__ = [
    # Client
    'Bio2RDFClient',
    'create_bio2rdf_client',

    # Mapper
    'OntologyMapper',
    'OntologyNamespace',
    'ConceptMapping',
    'create_ontology_mapper',

    # Enrichment
    'LinkEnrichmentEngine',
    'EnrichedEntity',
    'create_link_enrichment_engine'
]