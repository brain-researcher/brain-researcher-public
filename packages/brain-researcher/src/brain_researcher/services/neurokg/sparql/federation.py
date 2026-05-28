"""
SPARQL Federation Query Handler

Handles federated queries that combine data from BR-KG with external
SPARQL endpoints like Wikidata and DBpedia.
"""

import logging
import json
import requests
import time
from typing import Dict, Any, List, Optional, Set
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed

from SPARQLWrapper import SPARQLWrapper, JSON, XML
from rdflib import Graph, URIRef
from rdflib.plugins.sparql.parser import parseQuery

logger = logging.getLogger(__name__)


class FederationQueryHandler:
    """
    Handles federated SPARQL queries across multiple endpoints
    
    Supports:
    - Query decomposition across endpoints
    - Result merging and deduplication
    - Caching of external results
    - Error handling and fallbacks
    - Performance optimization
    """
    
    def __init__(self):
        self.external_endpoints = {
            'wikidata': {
                'url': 'https://query.wikidata.org/sparql',
                'timeout': 30,
                'max_retries': 3,
                'cache_ttl': 3600,  # 1 hour
                'rate_limit': 10,  # queries per minute
                'prefixes': {
                    'wd': 'http://www.wikidata.org/entity/',
                    'wdt': 'http://www.wikidata.org/prop/direct/',
                    'rdfs': 'http://www.w3.org/2000/01/rdf-schema#'
                }
            },
            'dbpedia': {
                'url': 'https://dbpedia.org/sparql',
                'timeout': 20,
                'max_retries': 2,
                'cache_ttl': 1800,  # 30 minutes
                'rate_limit': 20,  # queries per minute
                'prefixes': {
                    'dbo': 'http://dbpedia.org/ontology/',
                    'dbp': 'http://dbpedia.org/property/',
                    'dbr': 'http://dbpedia.org/resource/',
                    'rdfs': 'http://www.w3.org/2000/01/rdf-schema#'
                }
            }
        }
        
        # Query cache for external endpoints
        self.federation_cache: Dict[str, Dict[str, Any]] = {}
        
        # Rate limiting tracking
        self.last_query_time: Dict[str, float] = {}
        self.query_count: Dict[str, List[float]] = {}
        
        # Performance metrics
        self.federation_metrics = {
            'total_federated_queries': 0,
            'successful_federations': 0,
            'failed_federations': 0,
            'cache_hits': 0,
            'avg_federation_time': 0.0
        }
        
        logger.info("Federation query handler initialized")
    
    def execute_federated_query(
        self,
        query: str,
        default_graphs: Optional[List[str]] = None,
        named_graphs: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Execute a federated SPARQL query
        
        Decomposes the query, executes parts on appropriate endpoints,
        and merges the results.
        """
        start_time = time.time()
        self.federation_metrics['total_federated_queries'] += 1
        
        try:
            # Parse and decompose query
            parsed_query = parseQuery(query)
            query_plan = self._create_federation_plan(parsed_query)
            
            # Execute query plan
            results = self._execute_query_plan(query_plan)
            
            # Merge and deduplicate results
            merged_result = self._merge_federated_results(results, query_plan)
            
            # Update metrics
            execution_time = time.time() - start_time
            self._update_federation_metrics(execution_time, success=True)
            
            logger.info("Federated query executed successfully in %.2fs", execution_time)
            return merged_result
            
        except Exception as e:
            self._update_federation_metrics(time.time() - start_time, success=False)
            logger.error("Federated query execution failed: %s", str(e))
            raise
    
    def _create_federation_plan(self, parsed_query) -> Dict[str, Any]:
        """
        Create execution plan for federated query
        
        Analyzes the query and determines which parts should be executed
        on which endpoints.
        """
        plan = {
            'local_query': None,
            'external_queries': {},
            'merge_strategy': 'union',
            'join_variables': set()
        }
        
        query_str = str(parsed_query).lower()
        
        # Detect SERVICE clauses
        services = self._extract_service_clauses(query_str)
        for service_url, service_query in services.items():
            endpoint_name = self._url_to_endpoint_name(service_url)
            if endpoint_name:
                plan['external_queries'][endpoint_name] = service_query
        
        # Detect implicit federation patterns
        if 'wikidata' in query_str or 'wd:' in query_str or 'wdt:' in query_str:
            wikidata_query = self._extract_wikidata_patterns(query_str)
            if wikidata_query:
                plan['external_queries']['wikidata'] = wikidata_query
        
        if 'dbpedia' in query_str or 'dbr:' in query_str or 'dbo:' in query_str:
            dbpedia_query = self._extract_dbpedia_patterns(query_str)  
            if dbpedia_query:
                plan['external_queries']['dbpedia'] = dbpedia_query
        
        # Extract local part of query
        local_query = self._extract_local_query_part(query_str, plan['external_queries'])
        if local_query:
            plan['local_query'] = local_query
        
        # Determine merge strategy and join variables
        plan['join_variables'] = self._extract_join_variables(query_str)
        plan['merge_strategy'] = 'join' if plan['join_variables'] else 'union'
        
        logger.debug("Created federation plan: %s", plan)
        return plan
    
    def _execute_query_plan(self, query_plan: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the federation query plan"""
        results = {}
        
        # Execute external queries in parallel
        if query_plan['external_queries']:
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_endpoint = {}
                
                for endpoint_name, query in query_plan['external_queries'].items():
                    future = executor.submit(
                        self._execute_external_query,
                        endpoint_name, 
                        query
                    )
                    future_to_endpoint[future] = endpoint_name
                
                for future in as_completed(future_to_endpoint):
                    endpoint_name = future_to_endpoint[future]
                    try:
                        result = future.result()
                        results[endpoint_name] = result
                    except Exception as e:
                        logger.error("External query failed for %s: %s", endpoint_name, str(e))
                        results[endpoint_name] = {'bindings': []}
        
        # Execute local query if present
        if query_plan['local_query']:
            # This would be executed against the local Neo4j database
            # For now, return empty result
            results['local'] = {'bindings': []}
        
        return results
    
    def _execute_external_query(self, endpoint_name: str, query: str) -> Dict[str, Any]:
        """Execute query against external SPARQL endpoint"""
        
        if endpoint_name not in self.external_endpoints:
            raise ValueError(f"Unknown endpoint: {endpoint_name}")
        
        endpoint_config = self.external_endpoints[endpoint_name]
        
        # Check cache first
        cache_key = self._get_cache_key(endpoint_name, query)
        cached_result = self._get_cached_result(cache_key, endpoint_config['cache_ttl'])
        if cached_result:
            self.federation_metrics['cache_hits'] += 1
            return cached_result
        
        # Rate limiting check
        self._check_rate_limit(endpoint_name)
        
        # Prepare query with prefixes
        full_query = self._add_prefixes(query, endpoint_config['prefixes'])
        
        # Execute query with retries
        for attempt in range(endpoint_config['max_retries']):
            try:
                result = self._execute_sparql_request(
                    endpoint_config['url'],
                    full_query,
                    endpoint_config['timeout']
                )
                
                # Cache successful result
                self._cache_result(cache_key, result)
                
                return result
                
            except Exception as e:
                logger.warning("Attempt %d failed for %s: %s", attempt + 1, endpoint_name, str(e))
                if attempt < endpoint_config['max_retries'] - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    raise
        
        return {'bindings': []}
    
    def _execute_sparql_request(self, endpoint_url: str, query: str, timeout: int) -> Dict[str, Any]:
        """Execute SPARQL request against endpoint"""
        
        try:
            sparql = SPARQLWrapper(endpoint_url)
            sparql.setQuery(query)
            sparql.setReturnFormat(JSON)
            sparql.setTimeout(timeout)
            
            result = sparql.query().convert()
            
            # Extract bindings from result
            if 'results' in result and 'bindings' in result['results']:
                return {'bindings': result['results']['bindings']}
            else:
                return {'bindings': []}
                
        except Exception as e:
            logger.error("SPARQL request failed: %s", str(e))
            raise
    
    def _merge_federated_results(self, results: Dict[str, Any], query_plan: Dict[str, Any]) -> Dict[str, Any]:
        """Merge results from different endpoints"""
        
        if query_plan['merge_strategy'] == 'join':
            return self._join_results(results, query_plan['join_variables'])
        else:
            return self._union_results(results)
    
    def _union_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Union results from all endpoints"""
        all_bindings = []
        
        for endpoint_name, result in results.items():
            if 'bindings' in result:
                # Add source information to each binding
                for binding in result['bindings']:
                    binding['_source'] = {'type': 'literal', 'value': endpoint_name}
                all_bindings.extend(result['bindings'])
        
        # Remove duplicates
        unique_bindings = self._deduplicate_bindings(all_bindings)
        
        return {
            'head': {'vars': self._extract_all_variables(unique_bindings)},
            'results': {'bindings': unique_bindings}
        }
    
    def _join_results(self, results: Dict[str, Any], join_variables: Set[str]) -> Dict[str, Any]:
        """Join results on common variables"""
        
        if len(results) < 2:
            return self._union_results(results)
        
        # Simple join implementation (would need optimization for production)
        result_list = list(results.values())
        joined_bindings = result_list[0].get('bindings', [])
        
        for i in range(1, len(result_list)):
            joined_bindings = self._join_binding_sets(
                joined_bindings,
                result_list[i].get('bindings', []),
                join_variables
            )
        
        return {
            'head': {'vars': self._extract_all_variables(joined_bindings)},
            'results': {'bindings': joined_bindings}
        }
    
    def _join_binding_sets(
        self, 
        bindings1: List[Dict[str, Any]], 
        bindings2: List[Dict[str, Any]], 
        join_vars: Set[str]
    ) -> List[Dict[str, Any]]:
        """Join two sets of bindings on common variables"""
        
        joined = []
        
        for binding1 in bindings1:
            for binding2 in bindings2:
                # Check if join variables match
                matches = True
                for var in join_vars:
                    if var in binding1 and var in binding2:
                        if binding1[var] != binding2[var]:
                            matches = False
                            break
                
                if matches:
                    # Merge bindings
                    merged = {**binding1, **binding2}
                    joined.append(merged)
        
        return joined
    
    def _deduplicate_bindings(self, bindings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate bindings"""
        seen = set()
        unique = []
        
        for binding in bindings:
            # Create hashable representation
            binding_key = json.dumps({
                k: v for k, v in binding.items() 
                if k != '_source'  # Exclude source info from dedup
            }, sort_keys=True)
            
            if binding_key not in seen:
                seen.add(binding_key)
                unique.append(binding)
        
        return unique
    
    def _extract_all_variables(self, bindings: List[Dict[str, Any]]) -> List[str]:
        """Extract all variable names from bindings"""
        variables = set()
        for binding in bindings:
            variables.update(binding.keys())
        
        # Remove internal variables
        variables.discard('_source')
        
        return sorted(list(variables))
    
    # Query parsing and extraction methods
    def _extract_service_clauses(self, query: str) -> Dict[str, str]:
        """Extract SERVICE clauses from query"""
        # Simplified regex-based extraction
        import re
        services = {}
        
        service_pattern = r'SERVICE\s*<([^>]+)>\s*\{([^}]+)\}'
        matches = re.findall(service_pattern, query, re.IGNORECASE | re.DOTALL)
        
        for url, subquery in matches:
            services[url] = subquery.strip()
        
        return services
    
    def _extract_wikidata_patterns(self, query: str) -> Optional[str]:
        """Extract Wikidata-specific patterns from query"""
        # Look for Wikidata prefixes and entities
        if any(prefix in query for prefix in ['wd:', 'wdt:', 'wikidata']):
            # Return a simplified Wikidata query
            return "SELECT ?item ?itemLabel WHERE { ?item wdt:P31 wd:Q5 . SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\" . } } LIMIT 10"
        return None
    
    def _extract_dbpedia_patterns(self, query: str) -> Optional[str]:
        """Extract DBpedia-specific patterns from query"""
        # Look for DBpedia prefixes and entities
        if any(prefix in query for prefix in ['dbr:', 'dbo:', 'dbpedia']):
            # Return a simplified DBpedia query
            return "SELECT ?resource ?label WHERE { ?resource rdfs:label ?label . FILTER(LANG(?label) = 'en') } LIMIT 10"
        return None
    
    def _extract_local_query_part(self, query: str, external_queries: Dict[str, str]) -> Optional[str]:
        """Extract the part of query that should be executed locally"""
        # Remove external service clauses and return the rest
        local_query = query
        
        for external_query in external_queries.values():
            local_query = local_query.replace(external_query, "")
        
        # Clean up the query
        local_query = re.sub(r'SERVICE\s*<[^>]+>\s*\{[^}]*\}', '', local_query, flags=re.IGNORECASE)
        
        return local_query.strip() if local_query.strip() else None
    
    def _extract_join_variables(self, query: str) -> Set[str]:
        """Extract variables that should be used for joining"""
        # Simple extraction of variables that appear in multiple contexts
        import re
        variables = set(re.findall(r'\?(\w+)', query))
        
        # Return common variables (simplified)
        return variables if len(variables) > 1 else set()
    
    # Utility methods
    def _url_to_endpoint_name(self, url: str) -> Optional[str]:
        """Convert service URL to endpoint name"""
        if 'wikidata' in url:
            return 'wikidata'
        elif 'dbpedia' in url:
            return 'dbpedia'
        return None
    
    def _add_prefixes(self, query: str, prefixes: Dict[str, str]) -> str:
        """Add namespace prefixes to query"""
        prefix_lines = []
        for prefix, uri in prefixes.items():
            prefix_lines.append(f"PREFIX {prefix}: <{uri}>")
        
        return "\n".join(prefix_lines) + "\n" + query
    
    def _get_cache_key(self, endpoint_name: str, query: str) -> str:
        """Generate cache key for query"""
        import hashlib
        return f"{endpoint_name}:{hashlib.md5(query.encode()).hexdigest()}"
    
    def _get_cached_result(self, cache_key: str, ttl: int) -> Optional[Dict[str, Any]]:
        """Get cached result if still valid"""
        if cache_key in self.federation_cache:
            cached = self.federation_cache[cache_key]
            if time.time() - cached['timestamp'] < ttl:
                return cached['result']
            else:
                del self.federation_cache[cache_key]
        return None
    
    def _cache_result(self, cache_key: str, result: Dict[str, Any]):
        """Cache query result"""
        self.federation_cache[cache_key] = {
            'result': result,
            'timestamp': time.time()
        }
    
    def _check_rate_limit(self, endpoint_name: str):
        """Check and enforce rate limits"""
        endpoint_config = self.external_endpoints[endpoint_name]
        rate_limit = endpoint_config['rate_limit']
        
        current_time = time.time()
        
        # Initialize tracking if needed
        if endpoint_name not in self.query_count:
            self.query_count[endpoint_name] = []
        
        # Clean old queries (older than 1 minute)
        self.query_count[endpoint_name] = [
            query_time for query_time in self.query_count[endpoint_name]
            if current_time - query_time < 60
        ]
        
        # Check if we're over the rate limit
        if len(self.query_count[endpoint_name]) >= rate_limit:
            sleep_time = 60 - (current_time - min(self.query_count[endpoint_name]))
            if sleep_time > 0:
                logger.info("Rate limit reached for %s, sleeping for %.1fs", endpoint_name, sleep_time)
                time.sleep(sleep_time)
        
        # Record this query
        self.query_count[endpoint_name].append(current_time)
        self.last_query_time[endpoint_name] = current_time
    
    def _update_federation_metrics(self, execution_time: float, success: bool):
        """Update federation performance metrics"""
        if success:
            self.federation_metrics['successful_federations'] += 1
        else:
            self.federation_metrics['failed_federations'] += 1
        
        # Update average execution time
        total_queries = self.federation_metrics['total_federated_queries']
        current_avg = self.federation_metrics['avg_federation_time']
        self.federation_metrics['avg_federation_time'] = (
            (current_avg * (total_queries - 1) + execution_time) / total_queries
        )