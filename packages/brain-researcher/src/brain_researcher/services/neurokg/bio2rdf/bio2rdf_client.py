"""
Bio2RDF SPARQL Federation Client

Provides integration with Bio2RDF linked data endpoints for enriching
neuroimaging data with biological and biomedical knowledge.
"""

import logging
import time
from typing import Dict, Any, List, Optional, Set, Tuple
from urllib.parse import urlencode
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from SPARQLWrapper import SPARQLWrapper, JSON, XML
from rdflib import Graph, Namespace, URIRef, Literal

logger = logging.getLogger(__name__)


class Bio2RDFClient:
    """
    Client for querying Bio2RDF endpoints and enriching BR-KG data
    
    Bio2RDF provides linked data for biological databases including:
    - Gene Ontology (GO)
    - Protein Data Bank (PDB)
    - UniProt
    - ChEMBL
    - DrugBank
    - KEGG
    - Reactome
    """
    
    # Bio2RDF endpoint configuration
    BIO2RDF_ENDPOINTS = {
        'main': 'https://bio2rdf.org/sparql',
        'drugbank': 'https://drugbank.bio2rdf.org/sparql',
        'uniprot': 'https://uniprot.bio2rdf.org/sparql',
        'go': 'https://go.bio2rdf.org/sparql',
        'kegg': 'https://kegg.bio2rdf.org/sparql',
        'chembl': 'https://chembl.bio2rdf.org/sparql'
    }
    
    # Bio2RDF namespaces
    NAMESPACES = {
        'bio2rdf': Namespace('http://bio2rdf.org/'),
        'drugbank': Namespace('http://bio2rdf.org/drugbank:'),
        'uniprot': Namespace('http://bio2rdf.org/uniprot:'),
        'go': Namespace('http://bio2rdf.org/go:'),
        'kegg': Namespace('http://bio2rdf.org/kegg:'),
        'chembl': Namespace('http://bio2rdf.org/chembl:'),
        'mesh': Namespace('http://bio2rdf.org/mesh:'),
        'pubmed': Namespace('http://bio2rdf.org/pubmed:')
    }
    
    def __init__(
        self,
        default_endpoint: str = 'main',
        timeout: int = 30,
        max_retries: int = 3,
        cache_ttl: int = 3600
    ):
        """
        Initialize Bio2RDF client
        
        Args:
            default_endpoint: Default Bio2RDF endpoint to use
            timeout: Query timeout in seconds
            max_retries: Maximum retry attempts for failed queries
            cache_ttl: Cache time-to-live in seconds
        """
        self.default_endpoint = self.BIO2RDF_ENDPOINTS.get(
            default_endpoint, 
            self.BIO2RDF_ENDPOINTS['main']
        )
        self.timeout = timeout
        self.max_retries = max_retries
        self.cache_ttl = cache_ttl
        self._cache = {}
        self._cache_timestamps = {}
        
    def query(
        self, 
        sparql_query: str,
        endpoint: Optional[str] = None,
        format: str = 'json'
    ) -> Dict[str, Any]:
        """
        Execute SPARQL query against Bio2RDF endpoint
        
        Args:
            sparql_query: SPARQL query string
            endpoint: Specific endpoint to use (optional)
            format: Result format ('json' or 'xml')
            
        Returns:
            Query results as dictionary
        """
        endpoint_url = endpoint or self.default_endpoint
        
        # Check cache
        cache_key = f"{endpoint_url}:{sparql_query}"
        if cache_key in self._cache:
            if time.time() - self._cache_timestamps[cache_key] < self.cache_ttl:
                logger.debug(f"Cache hit for Bio2RDF query")
                return self._cache[cache_key]
        
        # Execute query with retries
        for attempt in range(self.max_retries):
            try:
                sparql = SPARQLWrapper(endpoint_url)
                sparql.setQuery(sparql_query)
                sparql.setReturnFormat(JSON if format == 'json' else XML)
                sparql.setTimeout(self.timeout)
                
                results = sparql.query().convert()
                
                # Cache results
                self._cache[cache_key] = results
                self._cache_timestamps[cache_key] = time.time()
                
                return results
                
            except Exception as e:
                logger.warning(f"Bio2RDF query attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff
                
        return {}
    
    def get_gene_info(self, gene_symbol: str) -> Dict[str, Any]:
        """
        Get gene information from Bio2RDF
        
        Args:
            gene_symbol: Gene symbol (e.g., 'BDNF', 'DRD2')
            
        Returns:
            Gene information including GO terms, pathways, etc.
        """
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX bio2rdf: <http://bio2rdf.org/>
        PREFIX go: <http://bio2rdf.org/go:>
        PREFIX uniprot: <http://bio2rdf.org/uniprot:>
        
        SELECT ?gene ?label ?go_term ?go_label ?pathway WHERE {{
            ?gene rdfs:label ?label .
            FILTER(CONTAINS(UCASE(STR(?label)), UCASE("{gene_symbol}")))
            
            OPTIONAL {{
                ?gene bio2rdf:go ?go_term .
                ?go_term rdfs:label ?go_label .
            }}
            
            OPTIONAL {{
                ?gene bio2rdf:pathway ?pathway .
            }}
        }}
        LIMIT 100
        """
        
        return self.query(query)
    
    def get_drug_target_interactions(self, drug_name: str) -> Dict[str, Any]:
        """
        Get drug-target interaction data from Bio2RDF
        
        Args:
            drug_name: Drug name or identifier
            
        Returns:
            Drug targets and interaction information
        """
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX drugbank: <http://bio2rdf.org/drugbank:>
        PREFIX bio2rdf: <http://bio2rdf.org/>
        
        SELECT ?drug ?drug_name ?target ?target_name ?action WHERE {{
            ?drug rdfs:label ?drug_name .
            FILTER(CONTAINS(LCASE(STR(?drug_name)), LCASE("{drug_name}")))
            
            ?drug drugbank:target ?target .
            ?target rdfs:label ?target_name .
            
            OPTIONAL {{
                ?drug drugbank:action ?action .
            }}
        }}
        LIMIT 50
        """
        
        return self.query(query, endpoint='drugbank')
    
    def get_protein_info(self, protein_id: str) -> Dict[str, Any]:
        """
        Get protein information from UniProt via Bio2RDF
        
        Args:
            protein_id: UniProt ID or protein name
            
        Returns:
            Protein information including function, structure, etc.
        """
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX uniprot: <http://bio2rdf.org/uniprot:>
        PREFIX bio2rdf: <http://bio2rdf.org/>
        
        SELECT ?protein ?name ?function ?go_term ?pdb WHERE {{
            {{
                ?protein uniprot:id "{protein_id}" .
            }} UNION {{
                ?protein rdfs:label ?name .
                FILTER(CONTAINS(LCASE(STR(?name)), LCASE("{protein_id}")))
            }}
            
            ?protein rdfs:label ?name .
            
            OPTIONAL {{
                ?protein uniprot:function ?function .
            }}
            
            OPTIONAL {{
                ?protein bio2rdf:go ?go_term .
            }}
            
            OPTIONAL {{
                ?protein bio2rdf:pdb ?pdb .
            }}
        }}
        LIMIT 20
        """
        
        return self.query(query, endpoint='uniprot')
    
    def get_pathway_info(self, pathway_name: str) -> Dict[str, Any]:
        """
        Get pathway information from KEGG/Reactome via Bio2RDF
        
        Args:
            pathway_name: Pathway name or identifier
            
        Returns:
            Pathway components and related information
        """
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX kegg: <http://bio2rdf.org/kegg:>
        PREFIX bio2rdf: <http://bio2rdf.org/>
        
        SELECT ?pathway ?name ?gene ?compound WHERE {{
            ?pathway rdfs:label ?name .
            FILTER(CONTAINS(LCASE(STR(?name)), LCASE("{pathway_name}")))
            
            OPTIONAL {{
                ?pathway kegg:gene ?gene .
            }}
            
            OPTIONAL {{
                ?pathway kegg:compound ?compound .
            }}
        }}
        LIMIT 100
        """
        
        return self.query(query, endpoint='kegg')
    
    def federated_search(
        self, 
        search_term: str,
        endpoints: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Search across multiple Bio2RDF endpoints
        
        Args:
            search_term: Term to search for
            endpoints: List of endpoints to search (default: all)
            
        Returns:
            Combined results from all endpoints
        """
        if endpoints is None:
            endpoints = list(self.BIO2RDF_ENDPOINTS.keys())
        
        results = {}
        
        # Basic search query template
        query_template = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX bio2rdf: <http://bio2rdf.org/>
        
        SELECT ?subject ?predicate ?object WHERE {{
            {{
                ?subject ?predicate ?object .
                FILTER(CONTAINS(LCASE(STR(?object)), LCASE("{term}")))
            }} UNION {{
                ?subject rdfs:label ?label .
                FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{term}")))
                ?subject ?predicate ?object .
            }}
        }}
        LIMIT 20
        """
        
        query = query_template.format(term=search_term)
        
        # Execute queries in parallel
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            for endpoint_name in endpoints:
                if endpoint_name in self.BIO2RDF_ENDPOINTS:
                    endpoint_url = self.BIO2RDF_ENDPOINTS[endpoint_name]
                    future = executor.submit(
                        self.query, 
                        query, 
                        endpoint_url
                    )
                    futures[future] = endpoint_name
            
            for future in as_completed(futures):
                endpoint_name = futures[future]
                try:
                    result = future.result()
                    results[endpoint_name] = result
                except Exception as e:
                    logger.error(f"Failed to query {endpoint_name}: {e}")
                    results[endpoint_name] = {'error': str(e)}
        
        return results
    
    def enrich_neuroimaging_concept(
        self, 
        concept: str,
        concept_type: str = 'brain_region'
    ) -> Dict[str, Any]:
        """
        Enrich neuroimaging concept with Bio2RDF biological data
        
        Args:
            concept: Neuroimaging concept (e.g., 'hippocampus', 'BOLD')
            concept_type: Type of concept ('brain_region', 'task', 'modality')
            
        Returns:
            Enriched concept information from Bio2RDF
        """
        enrichment = {
            'concept': concept,
            'type': concept_type,
            'bio2rdf_links': []
        }
        
        # Map concept types to Bio2RDF searches
        if concept_type == 'brain_region':
            # Search for anatomical terms and related genes
            anatomy_query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX mesh: <http://bio2rdf.org/mesh:>
            PREFIX go: <http://bio2rdf.org/go:>
            
            SELECT ?term ?label ?gene WHERE {{
                ?term rdfs:label ?label .
                FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{concept}")))
                FILTER(CONTAINS(STR(?term), "mesh") || CONTAINS(STR(?term), "go"))
                
                OPTIONAL {{
                    ?gene bio2rdf:anatomicalLocation ?term .
                }}
            }}
            LIMIT 10
            """
            
            results = self.query(anatomy_query)
            if 'results' in results and 'bindings' in results['results']:
                for binding in results['results']['bindings']:
                    enrichment['bio2rdf_links'].append({
                        'uri': binding.get('term', {}).get('value'),
                        'label': binding.get('label', {}).get('value'),
                        'type': 'anatomical_term',
                        'related_gene': binding.get('gene', {}).get('value') if 'gene' in binding else None
                    })
        
        elif concept_type == 'task':
            # Search for cognitive/behavioral terms
            cognitive_query = f"""
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX go: <http://bio2rdf.org/go:>
            
            SELECT ?term ?label WHERE {{
                ?term rdfs:label ?label .
                FILTER(CONTAINS(LCASE(STR(?label)), LCASE("{concept}")))
                FILTER(CONTAINS(STR(?term), "go"))
                FILTER(CONTAINS(LCASE(STR(?label)), "cognit") || 
                       CONTAINS(LCASE(STR(?label)), "behavior") ||
                       CONTAINS(LCASE(STR(?label)), "memory") ||
                       CONTAINS(LCASE(STR(?label)), "attention"))
            }}
            LIMIT 10
            """
            
            results = self.query(cognitive_query)
            if 'results' in results and 'bindings' in results['results']:
                for binding in results['results']['bindings']:
                    enrichment['bio2rdf_links'].append({
                        'uri': binding.get('term', {}).get('value'),
                        'label': binding.get('label', {}).get('value'),
                        'type': 'cognitive_process'
                    })
        
        # Get related drugs if applicable
        drug_results = self.get_drug_target_interactions(concept)
        if 'results' in drug_results and 'bindings' in drug_results['results']:
            for binding in drug_results['results']['bindings'][:5]:
                enrichment['bio2rdf_links'].append({
                    'uri': binding.get('drug', {}).get('value'),
                    'label': binding.get('drug_name', {}).get('value'),
                    'type': 'drug',
                    'target': binding.get('target_name', {}).get('value')
                })
        
        return enrichment


def create_bio2rdf_client(**kwargs) -> Bio2RDFClient:
    """Factory function to create Bio2RDF client"""
    return Bio2RDFClient(**kwargs)