"""
DBpedia Connector for External Graph Federation

Provides integration with DBpedia SPARQL endpoint for neuroimaging-related entities.
"""

import logging
import time
import hashlib
from typing import Dict, Any, List, Optional, Set
from urllib.parse import quote
import requests

from SPARQLWrapper import SPARQLWrapper, JSON

logger = logging.getLogger(__name__)


class DBpediaConnector:
    """
    Connector for DBpedia SPARQL endpoint

    Provides specialized queries for neuroimaging-related entities:
    - Brain anatomy and structures
    - Medical conditions and diseases
    - Universities and research institutions
    - Scientific journals and publications
    - Neuroscientists and medical professionals
    """

    def __init__(self, cache_ttl: int = 3600, max_results: int = 1000):
        self.endpoint_url = "https://dbpedia.org/sparql"
        self.cache_ttl = cache_ttl
        self.max_results = max_results

        # Query cache
        self.query_cache: Dict[str, Dict[str, Any]] = {}

        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 0.5  # 0.5 seconds between requests

        # Common prefixes for DBpedia queries
        self.prefixes = """
        PREFIX dbo: <http://dbpedia.org/ontology/>
        PREFIX dbp: <http://dbpedia.org/property/>
        PREFIX dbr: <http://dbpedia.org/resource/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>
        PREFIX dct: <http://purl.org/dc/terms/>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        """

        # Neuroimaging-specific categories and classes
        self.neuro_categories = {
            'brain_anatomy': [
                'dbo:AnatomicalStructure',
                'dbo:Brain'
            ],
            'diseases': [
                'dbo:Disease',
                'dbo:MentalDisorder'
            ],
            'institutions': [
                'dbo:University',
                'dbo:ResearchInstitution',
                'dbo:Hospital'
            ],
            'publications': [
                'dbo:AcademicJournal',
                'dbo:Book',
                'dbo:Article'
            ],
            'people': [
                'dbo:Scientist',
                'dbo:Physician',
                'dbo:Academic'
            ]
        }

        logger.info("DBpedia connector initialized")

    def search_brain_anatomy(
        self,
        query: str,
        limit: int = 50,
        include_description: bool = True
    ) -> List[Dict[str, Any]]:
        """Search for brain anatomy and anatomical structures"""

        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?resource ?label ?abstract ?type ?partOf WHERE {{
            {{
                ?resource a dbo:AnatomicalStructure .
                ?resource rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
                FILTER(LANG(?label) = "en")
            }} UNION {{
                ?resource dct:subject ?category .
                ?category rdfs:label ?catLabel .
                ?resource rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?catLabel), "brain") || CONTAINS(LCASE(?catLabel), "neurol"))
                FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
                FILTER(LANG(?label) = "en")
            }}

            OPTIONAL {{ ?resource rdf:type ?type . }}
            OPTIONAL {{ ?resource dbo:isPartOf ?partOf . }}

            {'''OPTIONAL { ?resource dbo:abstract ?abstract . FILTER(LANG(?abstract) = "en") }''' if include_description else ''}
        }}
        LIMIT {min(limit, self.max_results)}
        """

        return self._execute_query(sparql_query, "brain_anatomy")

    def search_neurological_conditions(
        self,
        query: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search for neurological conditions and mental disorders"""

        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?resource ?label ?abstract ?symptoms ?treatment ?icd WHERE {{
            {{
                ?resource a dbo:Disease .
                ?resource rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
                FILTER(LANG(?label) = "en")
            }} UNION {{
                ?resource a dbo:MentalDisorder .
                ?resource rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
                FILTER(LANG(?label) = "en")
            }} UNION {{
                ?resource dct:subject ?category .
                ?category rdfs:label ?catLabel .
                ?resource rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?catLabel), "neurological") ||
                       CONTAINS(LCASE(?catLabel), "brain") ||
                       CONTAINS(LCASE(?catLabel), "mental"))
                FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
                FILTER(LANG(?label) = "en")
            }}

            OPTIONAL {{ ?resource dbo:abstract ?abstract . FILTER(LANG(?abstract) = "en") }}
            OPTIONAL {{ ?resource dbo:symptoms ?symptoms . }}
            OPTIONAL {{ ?resource dbo:treatment ?treatment . }}
            OPTIONAL {{ ?resource dbp:icd ?icd . }}
        }}
        LIMIT {min(limit, self.max_results)}
        """

        return self._execute_query(sparql_query, "neurological_conditions")

    def search_research_institutions(
        self,
        query: str,
        focus_area: str = "neuroscience",
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """Search for universities and research institutions"""

        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?resource ?label ?abstract ?country ?established ?website WHERE {{
            {{
                ?resource a dbo:University .
            }} UNION {{
                ?resource a dbo:ResearchInstitution .
            }} UNION {{
                ?resource a dbo:Hospital .
                ?resource dct:subject ?category .
                FILTER(CONTAINS(LCASE(STR(?category)), "research"))
            }}

            ?resource rdfs:label ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
            FILTER(LANG(?label) = "en")

            # Focus area filter
            {{
                ?resource dbo:abstract ?abstract .
                FILTER(CONTAINS(LCASE(?abstract), "{focus_area}") ||
                       CONTAINS(LCASE(?abstract), "brain") ||
                       CONTAINS(LCASE(?abstract), "neural"))
                FILTER(LANG(?abstract) = "en")
            }} UNION {{
                ?resource dct:subject ?category .
                FILTER(CONTAINS(LCASE(STR(?category)), "{focus_area}") ||
                       CONTAINS(LCASE(STR(?category)), "brain") ||
                       CONTAINS(LCASE(STR(?category)), "neural"))
            }}

            OPTIONAL {{ ?resource dbo:country ?country . }}
            OPTIONAL {{ ?resource dbo:established ?established . }}
            OPTIONAL {{ ?resource foaf:homepage ?website . }}
        }}
        ORDER BY ?label
        LIMIT {min(limit, self.max_results)}
        """

        return self._execute_query(sparql_query, f"institutions_{focus_area}")

    def search_scientific_journals(
        self,
        query: str,
        subject_area: str = "neuroscience",
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Search for scientific journals and publications"""

        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?resource ?label ?abstract ?publisher ?issn ?impactFactor WHERE {{
            ?resource a dbo:AcademicJournal .
            ?resource rdfs:label ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
            FILTER(LANG(?label) = "en")

            # Subject area filter
            {{
                ?resource dbo:abstract ?abstract .
                FILTER(CONTAINS(LCASE(?abstract), "{subject_area}") ||
                       CONTAINS(LCASE(?abstract), "brain") ||
                       CONTAINS(LCASE(?abstract), "neural"))
                FILTER(LANG(?abstract) = "en")
            }} UNION {{
                ?resource dct:subject ?category .
                FILTER(CONTAINS(LCASE(STR(?category)), "{subject_area}") ||
                       CONTAINS(LCASE(STR(?category)), "brain") ||
                       CONTAINS(LCASE(STR(?category)), "neural"))
            }}

            OPTIONAL {{ ?resource dbo:publisher ?publisher . }}
            OPTIONAL {{ ?resource dbo:issn ?issn . }}
            OPTIONAL {{ ?resource dbp:impactFactor ?impactFactor . }}
        }}
        ORDER BY DESC(?impactFactor)
        LIMIT {min(limit, self.max_results)}
        """

        return self._execute_query(sparql_query, f"journals_{subject_area}")

    def search_neuroscientists(
        self,
        query: str,
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """Search for neuroscientists and researchers"""

        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?resource ?label ?abstract ?birthDate ?deathDate ?nationality ?almaMater ?knownFor WHERE {{
            {{
                ?resource a dbo:Scientist .
                ?resource dct:subject ?category .
                FILTER(CONTAINS(LCASE(STR(?category)), "neuroscien") ||
                       CONTAINS(LCASE(STR(?category)), "neurolog") ||
                       CONTAINS(LCASE(STR(?category)), "brain"))
            }} UNION {{
                ?resource a dbo:Physician .
                ?resource dct:subject ?category .
                FILTER(CONTAINS(LCASE(STR(?category)), "neurolog") ||
                       CONTAINS(LCASE(STR(?category)), "brain"))
            }} UNION {{
                ?resource a dbo:Academic .
                ?resource dbo:abstract ?abs .
                FILTER(CONTAINS(LCASE(?abs), "neuroscience") ||
                       CONTAINS(LCASE(?abs), "brain") ||
                       CONTAINS(LCASE(?abs), "neural"))
            }}

            ?resource rdfs:label ?label .
            FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
            FILTER(LANG(?label) = "en")

            OPTIONAL {{ ?resource dbo:abstract ?abstract . FILTER(LANG(?abstract) = "en") }}
            OPTIONAL {{ ?resource dbo:birthDate ?birthDate . }}
            OPTIONAL {{ ?resource dbo:deathDate ?deathDate . }}
            OPTIONAL {{ ?resource dbo:nationality ?nationality . }}
            OPTIONAL {{ ?resource dbo:almaMater ?almaMater . }}
            OPTIONAL {{ ?resource dbo:knownFor ?knownFor . }}
        }}
        ORDER BY ?birthDate
        LIMIT {min(limit, self.max_results)}
        """

        return self._execute_query(sparql_query, "neuroscientists")

    def get_entity_relationships(
        self,
        entity_uri: str,
        relationship_types: Optional[List[str]] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get relationships for a specific entity"""

        if not relationship_types:
            relationship_types = [
                'dbo:isPartOf', 'dbo:hasPart', 'dbo:related',
                'dbo:associatedWith', 'dbo:influences', 'dbo:influenced',
                'dbo:treatment', 'dbo:symptoms', 'dbo:cause'
            ]

        # Build relationship filter
        rel_filter = ' || '.join([f'?relation = {rel}' for rel in relationship_types])

        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?related ?relatedLabel ?relation ?direction WHERE {{
            {{
                <{entity_uri}> ?relation ?related .
                FILTER({rel_filter})
                BIND("outgoing" as ?direction)
            }} UNION {{
                ?related ?relation <{entity_uri}> .
                FILTER({rel_filter})
                BIND("incoming" as ?direction)
            }}

            ?related rdfs:label ?relatedLabel .
            FILTER(LANG(?relatedLabel) = "en")
        }}
        LIMIT {min(limit, self.max_results)}
        """

        return self._execute_query(sparql_query, f"relationships_{entity_uri}")

    def search_by_category(
        self,
        category_name: str,
        query: str = "",
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search entities within a specific category"""

        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?resource ?label ?abstract ?type WHERE {{
            ?resource dct:subject ?category .
            ?category rdfs:label ?catLabel .
            FILTER(CONTAINS(LCASE(?catLabel), LCASE("{category_name}")))

            ?resource rdfs:label ?label .
            FILTER(LANG(?label) = "en")

            {f'FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))' if query else ''}

            OPTIONAL {{ ?resource rdf:type ?type . }}
            OPTIONAL {{ ?resource dbo:abstract ?abstract . FILTER(LANG(?abstract) = "en") }}
        }}
        LIMIT {min(limit, self.max_results)}
        """

        return self._execute_query(sparql_query, f"category_{category_name}")

    def get_detailed_info(self, entity_uri: str) -> Dict[str, Any]:
        """Get detailed information about a specific entity"""

        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?property ?value ?valueLabel WHERE {{
            <{entity_uri}> ?property ?value .

            # Filter for important properties
            FILTER(?property IN (
                rdfs:label, dbo:abstract, rdf:type,
                dbo:isPartOf, dbo:hasPart, dbo:related,
                dbo:birthDate, dbo:deathDate, dbo:nationality,
                dbo:almaMater, dbo:knownFor, dbo:award,
                dbo:symptoms, dbo:treatment, dbo:cause,
                dbo:publisher, dbo:issn, foaf:homepage,
                dbo:country, dbo:established
            ))

            OPTIONAL {{
                ?value rdfs:label ?valueLabel .
                FILTER(LANG(?valueLabel) = "en")
            }}
        }}
        LIMIT {self.max_results}
        """

        results = self._execute_query(sparql_query, f"details_{entity_uri}")

        return self._structure_entity_details(results)

    def find_similar_entities(
        self,
        entity_uri: str,
        similarity_threshold: float = 0.3,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Find entities similar to the given entity"""

        # First, get the categories and properties of the source entity
        entity_info = self.get_detailed_info(entity_uri)

        # Extract categories for similarity matching
        categories = []
        if 'dct:subject' in entity_info.get('properties', {}):
            categories = entity_info['properties']['dct:subject']

        if not categories:
            return []

        # Build query to find similar entities
        category_filter = ' || '.join([f'?category = <{cat}>' for cat in categories[:5]])

        sparql_query = f"""
        {self.prefixes}
        SELECT DISTINCT ?resource ?label ?abstract ?sharedCategories WHERE {{
            ?resource dct:subject ?category .
            FILTER({category_filter})
            FILTER(?resource != <{entity_uri}>)

            ?resource rdfs:label ?label .
            FILTER(LANG(?label) = "en")

            OPTIONAL {{ ?resource dbo:abstract ?abstract . FILTER(LANG(?abstract) = "en") }}

            {{
                SELECT ?resource (COUNT(?category) as ?sharedCategories) WHERE {{
                    ?resource dct:subject ?category .
                    FILTER({category_filter})
                }}
                GROUP BY ?resource
            }}
        }}
        ORDER BY DESC(?sharedCategories)
        LIMIT {min(limit, self.max_results)}
        """

        return self._execute_query(sparql_query, f"similar_{entity_uri}")

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
            sparql.addCustomHttpHeader("User-Agent", "BR-KG/1.0 (https://br_kg.org)")

            result = sparql.query().convert()

            # Extract bindings
            bindings = result.get('results', {}).get('bindings', [])

            # Process results
            processed_results = self._process_dbpedia_results(bindings)

            # Cache results
            self._cache_result(cache_key, processed_results)

            logger.info("DBpedia query executed: %d results", len(processed_results))
            return processed_results

        except Exception as e:
            logger.error("DBpedia query failed: %s", str(e))
            return []

    def _process_dbpedia_results(self, bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process DBpedia SPARQL results"""

        processed = []

        for binding in bindings:
            result = {}

            for var, value in binding.items():
                if value.get('type') == 'uri':
                    # Extract resource name from URI
                    uri = value['value']
                    if 'dbpedia.org/resource/' in uri:
                        resource_name = uri.split('/')[-1]
                        result[var] = {
                            'name': resource_name,
                            'uri': uri,
                            'type': 'resource'
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
                        'datatype': value.get('datatype', 'string'),
                        'lang': value.get('xml:lang')
                    }
                else:
                    result[var] = value

            processed.append(result)

        return processed

    def _structure_entity_details(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Structure entity details into organized format"""

        details = {
            'properties': {},
            'basic_info': {},
            'relationships': {},
            'categories': []
        }

        for result in results:
            prop_data = result.get('property', {})
            value_data = result.get('value', {})

            if prop_data and 'uri' in prop_data:
                prop_uri = prop_data['uri']
                prop_name = prop_uri.split('/')[-1] if '/' in prop_uri else prop_uri

                # Categorize properties
                if prop_name in ['label', 'abstract', 'type']:
                    details['basic_info'][prop_name] = value_data
                elif prop_name in ['subject']:
                    details['categories'].append(value_data)
                elif prop_name in ['isPartOf', 'hasPart', 'related', 'associatedWith']:
                    if 'structural' not in details['relationships']:
                        details['relationships']['structural'] = []
                    details['relationships']['structural'].append({
                        'property': prop_name,
                        'value': value_data
                    })
                else:
                    if prop_name not in details['properties']:
                        details['properties'][prop_name] = []
                    details['properties'][prop_name].append(value_data)

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