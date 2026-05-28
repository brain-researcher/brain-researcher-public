"""
Wikidata Connector for External Graph Federation

Provides integration with Wikidata SPARQL endpoint for neuroimaging-related entities.
"""

import logging
import time
import hashlib
from typing import Dict, Any, List, Optional, Set
from urllib.parse import quote
import requests

from SPARQLWrapper import SPARQLWrapper, JSON
from .merger import FederationResultMerger

logger = logging.getLogger(__name__)


class WikidataConnector:
    """
    Connector for Wikidata SPARQL endpoint
    
    Provides specialized queries for neuroimaging-related entities:
    - Brain regions and anatomy
    - Neurological conditions and diseases
    - Neuroscientists and researchers
    - Neuroimaging techniques and methods
    - Publications and studies
    """
    
    def __init__(self, cache_ttl: int = 3600, max_results: int = 1000):
        self.endpoint_url = "https://query.wikidata.org/sparql"
        self.cache_ttl = cache_ttl
        self.max_results = max_results
        
        # Query cache
        self.query_cache: Dict[str, Dict[str, Any]] = {}
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 1.0  # 1 second between requests
        
        # Common prefixes for neuroimaging queries
        self.prefixes = """
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX wikibase: <http://wikiba.se/ontology#>
        PREFIX bd: <http://www.bigdata.com/rdf#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX schema: <http://schema.org/>
        """
        
        # Neuroimaging-specific entity mappings
        self.neuro_entities = {
            'brain': 'Q1073',
            'neuroscience': 'Q9281',
            'brain_region': 'Q864805',
            'neurological_disorder': 'Q10737',
            'fmri': 'Q207921',
            'neuroimaging': 'Q1575726',
            'cognitive_science': 'Q207011',
            'neurology': 'Q83353',
            'psychiatry': 'Q39201',
            'human_brain': 'Q1073'
        }
        
        logger.info("Wikidata connector initialized")
    
    def search_brain_regions(
        self, 
        query: str, 
        limit: int = 50,
        include_anatomy: bool = True
    ) -> List[Dict[str, Any]]:
        """Search for brain regions and anatomical structures"""
        
        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?item ?itemLabel ?description ?anatomyLabel ?partOf ?partOfLabel WHERE {{
            ?item wdt:P31/wdt:P279* wd:Q864805 .  # Instance of brain region
            ?item rdfs:label ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
            
            OPTIONAL {{ ?item wdt:P361 ?partOf . }}  # Part of
            OPTIONAL {{ ?item schema:description ?description . }}
            
            {'''OPTIONAL { ?item wdt:P1995 ?anatomy . }''' if include_anatomy else ''}
            
            SERVICE wikibase:label {{ 
                bd:serviceParam wikibase:language "en" . 
            }}
        }}
        LIMIT {min(limit, self.max_results)}
        """
        
        return self._execute_query(sparql_query, "brain_regions")
    
    def search_neurological_conditions(
        self,
        query: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search for neurological conditions and diseases"""
        
        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?item ?itemLabel ?description ?icd10 ?symptoms ?treatments WHERE {{
            {{
                ?item wdt:P31/wdt:P279* wd:Q10737 .  # Neurological disorder
            }} UNION {{
                ?item wdt:P31/wdt:P279* wd:Q12136 .  # Disease
                ?item wdt:P828/wdt:P279* wd:Q1073 .  # Has cause related to brain
            }}
            
            ?item rdfs:label ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
            
            OPTIONAL {{ ?item wdt:P494 ?icd10 . }}  # ICD-10 code
            OPTIONAL {{ ?item wdt:P780 ?symptoms . }}  # Symptoms
            OPTIONAL {{ ?item wdt:P2176 ?treatments . }}  # Medical treatment
            OPTIONAL {{ ?item schema:description ?description . }}
            
            SERVICE wikibase:label {{ 
                bd:serviceParam wikibase:language "en" . 
            }}
        }}
        LIMIT {min(limit, self.max_results)}
        """
        
        return self._execute_query(sparql_query, "neurological_conditions")
    
    def search_neuroimaging_methods(
        self,
        query: str,
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """Search for neuroimaging techniques and methods"""
        
        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?item ?itemLabel ?description ?inventor ?inventorLabel ?year WHERE {{
            {{
                ?item wdt:P31/wdt:P279* wd:Q1575726 .  # Neuroimaging technique
            }} UNION {{
                ?item wdt:P31/wdt:P279* wd:Q3910275 .  # Medical imaging
                ?item wdt:P2283/wdt:P279* wd:Q1073 .  # Uses brain
            }}
            
            ?item rdfs:label ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
            
            OPTIONAL {{ ?item wdt:P61 ?inventor . }}  # Inventor
            OPTIONAL {{ ?item wdt:P571 ?year . }}  # Inception
            OPTIONAL {{ ?item schema:description ?description . }}
            
            SERVICE wikibase:label {{ 
                bd:serviceParam wikibase:language "en" . 
            }}
        }}
        ORDER BY ?year
        LIMIT {min(limit, self.max_results)}
        """
        
        return self._execute_query(sparql_query, "neuroimaging_methods")
    
    def search_neuroscientists(
        self,
        query: str,
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """Search for neuroscientists and researchers"""
        
        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?item ?itemLabel ?description ?birthDate ?deathDate ?affiliation ?affiliationLabel WHERE {{
            ?item wdt:P31 wd:Q5 .  # Human
            {{
                ?item wdt:P106 wd:Q3126128 .  # Neuroscientist
            }} UNION {{
                ?item wdt:P106/wdt:P279* wd:Q901 .  # Scientist
                ?item wdt:P101 wd:Q9281 .  # Field of work: neuroscience
            }}
            
            ?item rdfs:label ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
            
            OPTIONAL {{ ?item wdt:P569 ?birthDate . }}  # Birth date
            OPTIONAL {{ ?item wdt:P570 ?deathDate . }}  # Death date
            OPTIONAL {{ ?item wdt:P1416 ?affiliation . }}  # Affiliation
            OPTIONAL {{ ?item schema:description ?description . }}
            
            SERVICE wikibase:label {{ 
                bd:serviceParam wikibase:language "en" . 
            }}
        }}
        ORDER BY DESC(?birthDate)
        LIMIT {min(limit, self.max_results)}
        """
        
        return self._execute_query(sparql_query, "neuroscientists")
    
    def get_brain_region_hierarchy(
        self,
        region_id: str,
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """Get hierarchical structure of brain regions"""
        
        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?item ?itemLabel ?level ?parent ?parentLabel WHERE {{
            {{
                wd:{region_id} wdt:P361* ?item .  # Start from given region
                BIND(0 as ?level)
            }} UNION {{
                wd:{region_id} wdt:P361+ ?parent .
                ?item wdt:P361 ?parent .
                BIND(1 as ?level)
            }} UNION {{
                wd:{region_id} wdt:P527* ?item .  # Has parts
                BIND(-1 as ?level)
            }}
            
            OPTIONAL {{ ?item wdt:P361 ?parent . }}  # Part of
            
            SERVICE wikibase:label {{ 
                bd:serviceParam wikibase:language "en" . 
            }}
        }}
        ORDER BY ?level ?itemLabel
        LIMIT {self.max_results}
        """
        
        results = self._execute_query(sparql_query, f"brain_hierarchy_{region_id}")
        
        return self._build_hierarchy_structure(results)
    
    def find_related_concepts(
        self,
        concept_id: str,
        relation_types: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Find concepts related to a given concept"""
        
        if not relation_types:
            relation_types = ['P361', 'P527', 'P31', 'P279', 'P1542', 'P828']  # Common relations
        
        relation_filter = ' '.join([f'wdt:{rel}' for rel in relation_types])
        
        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?related ?relatedLabel ?relation ?relationLabel ?description WHERE {{
            {{
                wd:{concept_id} ?relation ?related .
                FILTER(?relation IN ({relation_filter}))
            }} UNION {{
                ?related ?relation wd:{concept_id} .
                FILTER(?relation IN ({relation_filter}))
            }}
            
            ?related wdt:P31 ?type .
            FILTER(?type IN (wd:Q864805, wd:Q10737, wd:Q1575726, wd:Q12136))  # Relevant types
            
            OPTIONAL {{ ?related schema:description ?description . }}
            
            SERVICE wikibase:label {{ 
                bd:serviceParam wikibase:language "en" . 
            }}
        }}
        LIMIT {min(limit, self.max_results)}
        """
        
        return self._execute_query(sparql_query, f"related_{concept_id}")
    
    def search_publications(
        self,
        query: str,
        publication_type: str = "scientific_article",
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """Search for scientific publications"""
        
        type_mapping = {
            'scientific_article': 'Q13442814',
            'review': 'Q7318358',
            'book': 'Q571',
            'thesis': 'Q1266946'
        }
        
        type_id = type_mapping.get(publication_type, 'Q13442814')
        
        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?item ?itemLabel ?authors ?journal ?journalLabel ?year ?doi WHERE {{
            ?item wdt:P31 wd:{type_id} .  # Publication type
            {{
                ?item wdt:P921/wdt:P279* wd:Q9281 .  # Main subject: neuroscience
            }} UNION {{
                ?item wdt:P921/wdt:P279* wd:Q1575726 .  # Main subject: neuroimaging
            }}
            
            {{
                ?item rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
            }} UNION {{
                ?item wdt:P1476 ?title .
                FILTER(CONTAINS(LCASE(?title), LCASE("{query}")))
            }}
            
            OPTIONAL {{ ?item wdt:P50 ?authors . }}  # Authors
            OPTIONAL {{ ?item wdt:P1433 ?journal . }}  # Published in
            OPTIONAL {{ ?item wdt:P577 ?year . }}  # Publication date
            OPTIONAL {{ ?item wdt:P356 ?doi . }}  # DOI
            
            SERVICE wikibase:label {{ 
                bd:serviceParam wikibase:language "en" . 
            }}
        }}
        ORDER BY DESC(?year)
        LIMIT {min(limit, self.max_results)}
        """
        
        return self._execute_query(sparql_query, "publications")
    
    def get_entity_details(self, entity_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific entity"""
        
        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?property ?propertyLabel ?value ?valueLabel WHERE {{
            wd:{entity_id} ?property ?value .
            ?prop wikibase:directClaim ?property .
            
            # Filter for important properties
            FILTER(?property IN (
                wdt:P31, wdt:P279, wdt:P361, wdt:P527,  # Basic classification
                wdt:P1995, wdt:P828, wdt:P780,  # Medical properties
                wdt:P61, wdt:P571, wdt:P1416,  # Inventor, date, affiliation
                wdt:P50, wdt:P577, wdt:P356,  # Publication properties
                wdt:P494, wdt:P2176  # ICD-10, treatment
            ))
            
            SERVICE wikibase:label {{ 
                bd:serviceParam wikibase:language "en" . 
            }}
        }}
        LIMIT {self.max_results}
        """
        
        results = self._execute_query(sparql_query, f"entity_details_{entity_id}")
        
        return self._structure_entity_details(results)
    
    def _execute_query(
        self, 
        query: str, 
        cache_key: str,
        timeout: int = 30
    ) -> List[Dict[str, Any]]:
        """Execute SPARQL query with caching and rate limiting"""
        
        # Check cache
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            return cached_result
        
        # Rate limiting
        self._enforce_rate_limit()
        
        try:
            sparql = SPARQLWrapper(self.endpoint_url)
            sparql.setQuery(query)
            sparql.setReturnFormat(JSON)
            sparql.setTimeout(timeout)
            
            # Set user agent
            sparql.addCustomHttpHeader("User-Agent", "BR-KG/1.0 (https://neurokg.org)")
            
            result = sparql.query().convert()
            
            # Extract bindings
            bindings = result.get('results', {}).get('bindings', [])
            
            # Process results
            processed_results = self._process_wikidata_results(bindings)
            
            # Cache results
            self._cache_result(cache_key, processed_results)
            
            logger.info("Wikidata query executed: %d results", len(processed_results))
            return processed_results
            
        except Exception as e:
            logger.error("Wikidata query failed: %s", str(e))
            return []
    
    def _process_wikidata_results(self, bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process Wikidata SPARQL results"""
        
        processed = []
        
        for binding in bindings:
            result = {}
            
            for var, value in binding.items():
                if value.get('type') == 'uri':
                    # Extract entity ID from URI
                    uri = value['value']
                    if 'wikidata.org/entity/' in uri:
                        entity_id = uri.split('/')[-1]
                        result[var] = {
                            'id': entity_id,
                            'uri': uri,
                            'type': 'entity'
                        }
                    else:
                        result[var] = {
                            'uri': uri,
                            'type': 'uri'
                        }
                elif value.get('type') == 'literal':
                    result[var] = {
                        'value': value['value'],
                        'type': 'literal',
                        'datatype': value.get('datatype', 'string')
                    }
                else:
                    result[var] = value
            
            processed.append(result)
        
        return processed
    
    def _build_hierarchy_structure(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build hierarchical structure from flat results"""
        
        hierarchy = {
            'root': None,
            'children': {},
            'parents': {},
            'levels': {}
        }
        
        for result in results:
            item_data = result.get('item', {})
            level = result.get('level', {}).get('value', 0)
            
            if item_data and 'id' in item_data:
                item_id = item_data['id']
                hierarchy['levels'][item_id] = {
                    'level': int(level),
                    'data': result
                }
                
                # Build parent-child relationships
                parent_data = result.get('parent', {})
                if parent_data and 'id' in parent_data:
                    parent_id = parent_data['id']
                    if parent_id not in hierarchy['children']:
                        hierarchy['children'][parent_id] = []
                    hierarchy['children'][parent_id].append(item_id)
                    hierarchy['parents'][item_id] = parent_id
        
        return hierarchy
    
    def _structure_entity_details(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Structure entity details into organized format"""
        
        details = {
            'properties': {},
            'classifications': [],
            'relationships': {},
            'attributes': {}
        }
        
        for result in results:
            prop_data = result.get('property', {})
            value_data = result.get('value', {})
            
            if prop_data and 'uri' in prop_data:
                prop_uri = prop_data['uri']
                prop_id = prop_uri.split('/')[-1] if '/' in prop_uri else prop_uri
                
                # Categorize properties
                if prop_id in ['P31', 'P279']:  # Instance of, Subclass of
                    details['classifications'].append({
                        'property': prop_id,
                        'value': value_data
                    })
                elif prop_id in ['P361', 'P527']:  # Part of, Has parts
                    if 'structure' not in details['relationships']:
                        details['relationships']['structure'] = []
                    details['relationships']['structure'].append({
                        'property': prop_id,
                        'value': value_data
                    })
                else:
                    if prop_id not in details['properties']:
                        details['properties'][prop_id] = []
                    details['properties'][prop_id].append(value_data)
        
        return details
    
    def _enforce_rate_limit(self):
        """Enforce rate limiting between requests"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def _get_cache_key(self, query: str) -> str:
        """Generate cache key for query"""
        return hashlib.md5(query.encode()).hexdigest()
    
    def _get_cached_result(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        """Get cached query result"""
        if cache_key in self.query_cache:
            cached = self.query_cache[cache_key]
            if time.time() - cached['timestamp'] < self.cache_ttl:
                return cached['results']
            else:
                del self.query_cache[cache_key]
        return None
    
    def _cache_result(self, cache_key: str, results: List[Dict[str, Any]]):
        """Cache query results"""
        self.query_cache[cache_key] = {
            'results': results,
            'timestamp': time.time()
        }
        
        # Limit cache size
        if len(self.query_cache) > 1000:
            # Remove oldest entries
            oldest_keys = sorted(
                self.query_cache.keys(),
                key=lambda k: self.query_cache[k]['timestamp']
            )[:100]
            for key in oldest_keys:
                del self.query_cache[key]