"""
Bio2RDF Link Enrichment for BR-KG

Enriches BR-KG entities with biological knowledge from Bio2RDF.
"""

import logging
import json
from typing import Dict, Any, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict

from .bio2rdf_client import Bio2RDFClient, create_bio2rdf_client
from .ontology_mapper import OntologyMapper, ConceptMapping, create_ontology_mapper

logger = logging.getLogger(__name__)


@dataclass
class EnrichedEntity:
    """Enriched BR-KG entity with Bio2RDF links"""
    
    entity_id: str
    entity_type: str
    entity_label: str
    bio2rdf_mappings: List[ConceptMapping]
    biological_annotations: Dict[str, Any]
    related_genes: List[Dict[str, str]]
    related_drugs: List[Dict[str, str]]
    pathways: List[Dict[str, str]]
    literature_refs: List[str]
    confidence_score: float


class LinkEnrichmentEngine:
    """
    Engine for enriching BR-KG entities with Bio2RDF biological knowledge
    """
    
    def __init__(
        self,
        bio2rdf_client: Optional[Bio2RDFClient] = None,
        ontology_mapper: Optional[OntologyMapper] = None
    ):
        """
        Initialize the enrichment engine
        
        Args:
            bio2rdf_client: Bio2RDF client instance
            ontology_mapper: Ontology mapper instance
        """
        self.bio2rdf_client = bio2rdf_client or create_bio2rdf_client()
        self.ontology_mapper = ontology_mapper or create_ontology_mapper()
        self._enrichment_cache = {}
    
    def enrich_entity(
        self,
        entity_id: str,
        entity_type: str,
        entity_label: str,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> EnrichedEntity:
        """
        Enrich a single BR-KG entity with Bio2RDF data
        
        Args:
            entity_id: BR-KG entity identifier
            entity_type: Type of entity (e.g., 'brain_region', 'task')
            entity_label: Human-readable label
            additional_context: Additional context for enrichment
            
        Returns:
            Enriched entity with Bio2RDF links and annotations
        """
        cache_key = f"{entity_id}:{entity_type}"
        if cache_key in self._enrichment_cache:
            return self._enrichment_cache[cache_key]
        
        # Map to Bio2RDF ontologies
        mappings = self.ontology_mapper.map_concept(
            entity_label,
            entity_type,
            fuzzy=True
        )
        
        # Initialize enriched entity
        enriched = EnrichedEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            entity_label=entity_label,
            bio2rdf_mappings=mappings,
            biological_annotations={},
            related_genes=[],
            related_drugs=[],
            pathways=[],
            literature_refs=[],
            confidence_score=0.0
        )
        
        # Enrich based on entity type
        if entity_type == 'brain_region':
            self._enrich_brain_region(enriched, entity_label)
        elif entity_type == 'cognitive_task':
            self._enrich_cognitive_task(enriched, entity_label)
        elif entity_type == 'disorder':
            self._enrich_disorder(enriched, entity_label)
        elif entity_type == 'neurochemical':
            self._enrich_neurochemical(enriched, entity_label)
        
        # Calculate overall confidence score
        if mappings:
            enriched.confidence_score = max(m.confidence_score for m in mappings)
        
        self._enrichment_cache[cache_key] = enriched
        return enriched
    
    def _enrich_brain_region(
        self, 
        enriched: EnrichedEntity,
        region_name: str
    ):
        """Enrich brain region with anatomical and gene expression data"""
        
        # Get anatomical hierarchy
        anatomy_query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX mesh: <http://bio2rdf.org/mesh:>
        PREFIX uberon: <http://bio2rdf.org/uberon:>
        
        SELECT ?parent ?parent_label ?child ?child_label WHERE {{
            {{
                ?region rdfs:label ?label .
                FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{region_name}")))
                ?region mesh:treeNumber ?tree .
                ?parent mesh:treeNumber ?parent_tree .
                FILTER(STRSTARTS(?tree, ?parent_tree))
                ?parent rdfs:label ?parent_label .
            }}
            UNION
            {{
                ?region rdfs:label ?label .
                FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{region_name}")))
                ?child mesh:treeNumber ?child_tree .
                ?region mesh:treeNumber ?tree .
                FILTER(STRSTARTS(?child_tree, ?tree))
                ?child rdfs:label ?child_label .
            }}
        }}
        LIMIT 20
        """
        
        try:
            anatomy_results = self.bio2rdf_client.query(anatomy_query)
            if 'results' in anatomy_results:
                enriched.biological_annotations['anatomical_hierarchy'] = {
                    'parents': [],
                    'children': []
                }
                
                for binding in anatomy_results['results'].get('bindings', []):
                    if 'parent' in binding:
                        enriched.biological_annotations['anatomical_hierarchy']['parents'].append({
                            'uri': binding['parent']['value'],
                            'label': binding.get('parent_label', {}).get('value', '')
                        })
                    if 'child' in binding:
                        enriched.biological_annotations['anatomical_hierarchy']['children'].append({
                            'uri': binding['child']['value'],
                            'label': binding.get('child_label', {}).get('value', '')
                        })
        except Exception as e:
            logger.error(f"Failed to enrich brain region anatomy: {e}")
        
        # Get associated genes
        gene_results = self.bio2rdf_client.get_gene_info(region_name)
        if 'results' in gene_results:
            for binding in gene_results['results'].get('bindings', [])[:10]:
                enriched.related_genes.append({
                    'uri': binding.get('gene', {}).get('value', ''),
                    'label': binding.get('label', {}).get('value', ''),
                    'go_term': binding.get('go_term', {}).get('value', '') if 'go_term' in binding else None
                })
    
    def _enrich_cognitive_task(
        self,
        enriched: EnrichedEntity,
        task_name: str
    ):
        """Enrich cognitive task with GO processes and neural correlates"""
        
        # Get GO biological processes
        go_query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX go: <http://bio2rdf.org/go:>
        PREFIX obo: <http://purl.obolibrary.org/obo/>
        
        SELECT ?process ?label ?definition WHERE {{
            ?process rdfs:label ?label .
            FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{task_name}")) ||
                   CONTAINS(LCASE(STR(?label)), "cognit") ||
                   CONTAINS(LCASE(STR(?label)), "behavior"))
            FILTER(CONTAINS(STR(?process), "go:"))
            
            OPTIONAL {{
                ?process obo:IAO_0000115 ?definition .
            }}
        }}
        LIMIT 15
        """
        
        try:
            go_results = self.bio2rdf_client.query(go_query)
            if 'results' in go_results:
                enriched.biological_annotations['go_processes'] = []
                
                for binding in go_results['results'].get('bindings', []):
                    enriched.biological_annotations['go_processes'].append({
                        'uri': binding.get('process', {}).get('value', ''),
                        'label': binding.get('label', {}).get('value', ''),
                        'definition': binding.get('definition', {}).get('value', '') if 'definition' in binding else None
                    })
        except Exception as e:
            logger.error(f"Failed to enrich cognitive task: {e}")
    
    def _enrich_disorder(
        self,
        enriched: EnrichedEntity,
        disorder_name: str
    ):
        """Enrich neurological/psychiatric disorder with clinical data"""
        
        # Get associated genes and drugs
        disorder_results = self.bio2rdf_client.federated_search(
            disorder_name,
            endpoints=['drugbank', 'omim', 'kegg']
        )
        
        # Process DrugBank results for treatments
        if 'drugbank' in disorder_results and 'results' in disorder_results['drugbank']:
            for binding in disorder_results['drugbank']['results'].get('bindings', [])[:10]:
                if 'object' in binding and 'drug' in binding['object']['value']:
                    enriched.related_drugs.append({
                        'uri': binding['object']['value'],
                        'type': 'treatment',
                        'source': 'drugbank'
                    })
        
        # Process KEGG results for pathways
        if 'kegg' in disorder_results and 'results' in disorder_results['kegg']:
            for binding in disorder_results['kegg']['results'].get('bindings', [])[:5]:
                if 'object' in binding and 'pathway' in binding['object']['value']:
                    enriched.pathways.append({
                        'uri': binding['object']['value'],
                        'type': 'disease_pathway',
                        'source': 'kegg'
                    })
        
        # Get literature references
        pubmed_query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX pubmed: <http://bio2rdf.org/pubmed:>
        
        SELECT ?article WHERE {{
            ?article rdfs:label ?label .
            FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{disorder_name}")))
            FILTER(CONTAINS(STR(?article), "pubmed:"))
        }}
        LIMIT 10
        """
        
        try:
            pubmed_results = self.bio2rdf_client.query(pubmed_query)
            if 'results' in pubmed_results:
                for binding in pubmed_results['results'].get('bindings', []):
                    enriched.literature_refs.append(binding['article']['value'])
        except Exception as e:
            logger.error(f"Failed to get literature references: {e}")
    
    def _enrich_neurochemical(
        self,
        enriched: EnrichedEntity,
        chemical_name: str
    ):
        """Enrich neurochemical with receptor and drug interaction data"""
        
        # Get drug interactions
        drug_results = self.bio2rdf_client.get_drug_target_interactions(chemical_name)
        if 'results' in drug_results:
            for binding in drug_results['results'].get('bindings', [])[:10]:
                enriched.related_drugs.append({
                    'uri': binding.get('drug', {}).get('value', ''),
                    'name': binding.get('drug_name', {}).get('value', ''),
                    'target': binding.get('target_name', {}).get('value', ''),
                    'action': binding.get('action', {}).get('value', '') if 'action' in binding else None
                })
        
        # Get associated pathways
        pathway_results = self.bio2rdf_client.get_pathway_info(chemical_name)
        if 'results' in pathway_results:
            for binding in pathway_results['results'].get('bindings', [])[:5]:
                enriched.pathways.append({
                    'uri': binding.get('pathway', {}).get('value', ''),
                    'name': binding.get('name', {}).get('value', ''),
                    'type': 'metabolic_pathway'
                })
    
    def batch_enrich(
        self,
        entities: List[Tuple[str, str, str]],
        max_workers: int = 5
    ) -> List[EnrichedEntity]:
        """
        Enrich multiple entities in parallel
        
        Args:
            entities: List of (entity_id, entity_type, entity_label) tuples
            max_workers: Maximum number of parallel workers
            
        Returns:
            List of enriched entities
        """
        enriched_entities = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for entity_id, entity_type, entity_label in entities:
                future = executor.submit(
                    self.enrich_entity,
                    entity_id,
                    entity_type,
                    entity_label
                )
                futures[future] = (entity_id, entity_type, entity_label)
            
            for future in as_completed(futures):
                try:
                    enriched = future.result()
                    enriched_entities.append(enriched)
                except Exception as e:
                    entity_info = futures[future]
                    logger.error(f"Failed to enrich entity {entity_info[0]}: {e}")
        
        return enriched_entities
    
    def export_enrichment_graph(
        self,
        enriched_entities: List[EnrichedEntity],
        format: str = 'json'
    ) -> str:
        """
        Export enriched entities as a graph
        
        Args:
            enriched_entities: List of enriched entities
            format: Export format ('json', 'turtle', 'ntriples')
            
        Returns:
            Serialized graph data
        """
        if format == 'json':
            # Export as JSON-LD
            graph_data = {
                '@context': {
                    'neurokg': 'https://neurokg.org/',
                    'bio2rdf': 'http://bio2rdf.org/',
                    'owl': 'http://www.w3.org/2002/07/owl#',
                    'skos': 'http://www.w3.org/2004/02/skos/core#'
                },
                '@graph': []
            }
            
            for entity in enriched_entities:
                node = {
                    '@id': entity.entity_id,
                    '@type': entity.entity_type,
                    'label': entity.entity_label,
                    'confidence': entity.confidence_score,
                    'mappings': []
                }
                
                for mapping in entity.bio2rdf_mappings:
                    node['mappings'].append({
                        '@id': mapping.bio2rdf_uri,
                        'namespace': mapping.bio2rdf_namespace.value,
                        'label': mapping.bio2rdf_label,
                        'mapping_type': mapping.mapping_type
                    })
                
                if entity.related_genes:
                    node['genes'] = entity.related_genes
                if entity.related_drugs:
                    node['drugs'] = entity.related_drugs
                if entity.pathways:
                    node['pathways'] = entity.pathways
                if entity.literature_refs:
                    node['references'] = entity.literature_refs
                
                graph_data['@graph'].append(node)
            
            return json.dumps(graph_data, indent=2)
        
        else:
            # For other formats, build RDF graph
            from rdflib import Graph, Namespace, URIRef, Literal
            
            g = Graph()
            neurokg = Namespace('https://neurokg.org/')
            bio2rdf = Namespace('http://bio2rdf.org/')
            owl = Namespace('http://www.w3.org/2002/07/owl#')
            skos = Namespace('http://www.w3.org/2004/02/skos/core#')
            
            g.bind('neurokg', neurokg)
            g.bind('bio2rdf', bio2rdf)
            g.bind('owl', owl)
            g.bind('skos', skos)
            
            for entity in enriched_entities:
                entity_uri = URIRef(entity.entity_id)
                
                for mapping in entity.bio2rdf_mappings:
                    bio2rdf_uri = URIRef(mapping.bio2rdf_uri)
                    
                    if mapping.mapping_type == 'exact':
                        g.add((entity_uri, owl.sameAs, bio2rdf_uri))
                        g.add((entity_uri, skos.exactMatch, bio2rdf_uri))
                    elif mapping.mapping_type == 'narrow':
                        g.add((entity_uri, skos.narrowMatch, bio2rdf_uri))
                    elif mapping.mapping_type == 'broad':
                        g.add((entity_uri, skos.broadMatch, bio2rdf_uri))
                    else:
                        g.add((entity_uri, skos.relatedMatch, bio2rdf_uri))
            
            if format == 'turtle':
                return g.serialize(format='turtle')
            elif format == 'ntriples':
                return g.serialize(format='ntriples')
            else:
                return g.serialize(format='xml')


def create_link_enrichment_engine(**kwargs) -> LinkEnrichmentEngine:
    """Factory function to create link enrichment engine"""
    return LinkEnrichmentEngine(**kwargs)