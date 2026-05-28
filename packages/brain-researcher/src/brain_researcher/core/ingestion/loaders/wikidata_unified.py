"""
Unified WikiData Loader for Brain Regions

This module provides a unified interface for loading brain region data from WikiData,
including anatomical hierarchies, coordinates, and cross-references to other atlases.

Features:
- SPARQL query interface
- Brain region ontology extraction
- Anatomical hierarchies (part-of relationships)
- MNI coordinates where available
- Cross-references to other atlases
- Local caching of query results
- Multi-language support

Author: Brain Researcher Team
"""

import json
import logging
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import requests
from SPARQLWrapper import SPARQLWrapper, JSON

logger = logging.getLogger(__name__)

# WikiData SPARQL endpoint
WIKIDATA_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
DEFAULT_CACHE_DURATION = timedelta(days=30)  # Brain regions don't change often

# Common WikiData properties for brain regions
PROPERTIES = {
    "instance_of": "P31",
    "part_of": "P361",
    "has_part": "P527",
    "coordinate_location": "P625",
    "MNI_coordinates": "P6758",
    "TA98_ID": "P1323",
    "NeuroLex_ID": "P696",
    "FMA_ID": "P1402",
    "MeSH_ID": "P486",
    "UBERON_ID": "P1554",
    "image": "P18",
    "adjacent_to": "P47"
}

# Common brain region classes in WikiData
BRAIN_REGION_CLASSES = [
    "Q101405097",  # brain region
    "Q4936952",    # anatomical structure
    "Q10376724",   # neuroanatomical structure
]


class WikiDataUnifiedLoader:
    """
    Unified WikiData loader for brain regions and anatomical structures.
    
    Combines functionality from:
    - wikidata_loader.py (SPARQL queries)
    - wikidata_json_loader.py (JSON processing)
    
    Adds:
    - Comprehensive SPARQL query templates
    - Multi-language label support
    - Cross-atlas mappings
    - Coordinate extraction
    """
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        cache_duration: timedelta = DEFAULT_CACHE_DURATION,
        language: str = "en",
        endpoint: str = WIKIDATA_SPARQL_ENDPOINT
    ):
        """
        Initialize the unified WikiData loader.
        
        Args:
            cache_dir: Directory for caching query results
            cache_duration: How long to keep cached data
            language: Primary language for labels (en, de, fr, etc.)
            endpoint: SPARQL endpoint URL
        """
        # Set cache directory
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".neurokg_cache" / "wikidata"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_duration = cache_duration
        
        # Configure SPARQL
        self.endpoint = endpoint
        self.sparql = SPARQLWrapper(endpoint)
        self.sparql.setReturnFormat(JSON)
        self.language = language
        
        # Statistics
        self.stats = {
            "regions_loaded": 0,
            "hierarchies_loaded": 0,
            "coordinates_found": 0,
            "cross_references": 0,
            "cache_hits": 0,
            "sparql_queries": 0
        }
        
        logger.info(f"Initialized WikiDataUnifiedLoader (language: {language})")
    
    def load_brain_regions(
        self,
        include_hierarchy: bool = True,
        include_coordinates: bool = True,
        include_cross_refs: bool = True,
        limit: int = None
    ) -> List[Dict[str, Any]]:
        """
        Load brain regions from WikiData.
        
        Args:
            include_hierarchy: Whether to include part-of relationships
            include_coordinates: Whether to include MNI/spatial coordinates
            include_cross_refs: Whether to include cross-references to other atlases
            limit: Maximum number of regions to load
        
        Returns:
            List of brain region dictionaries
        """
        # Build SPARQL query
        query = self._build_brain_regions_query(
            include_hierarchy,
            include_coordinates,
            include_cross_refs,
            limit
        )
        
        # Check cache
        cache_key = hashlib.md5(query.encode()).hexdigest()
        cached_data = self._load_from_cache(cache_key)
        if cached_data:
            self.stats["cache_hits"] += 1
            return cached_data
        
        # Execute query
        regions = self._execute_sparql_query(query)
        
        # Process results
        processed_regions = self._process_brain_regions(regions)
        
        # Update statistics
        self.stats["regions_loaded"] += len(processed_regions)
        if include_hierarchy:
            self.stats["hierarchies_loaded"] += sum(
                1 for r in processed_regions if r.get("part_of")
            )
        if include_coordinates:
            self.stats["coordinates_found"] += sum(
                1 for r in processed_regions if r.get("coordinates")
            )
        if include_cross_refs:
            self.stats["cross_references"] += sum(
                len(r.get("cross_references", {})) for r in processed_regions
            )
        
        # Cache results
        self._save_to_cache(cache_key, processed_regions)
        
        return processed_regions
    
    def _build_brain_regions_query(
        self,
        include_hierarchy: bool,
        include_coordinates: bool,
        include_cross_refs: bool,
        limit: Optional[int]
    ) -> str:
        """Build SPARQL query for brain regions."""
        # Base query structure
        query_parts = [
            "PREFIX wd: <http://www.wikidata.org/entity/>",
            "PREFIX wdt: <http://www.wikidata.org/prop/direct/>",
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>",
            "",
            "SELECT DISTINCT ?item ?itemLabel ?itemDescription"
        ]
        
        # Add optional fields
        optional_fields = []
        optional_patterns = []
        
        if include_hierarchy:
            optional_fields.extend(["?partOf", "?partOfLabel"])
            optional_patterns.append(
                "OPTIONAL { ?item wdt:P361 ?partOf . }"
            )
        
        if include_coordinates:
            optional_fields.extend(["?mniCoords", "?coords"])
            optional_patterns.extend([
                "OPTIONAL { ?item wdt:P6758 ?mniCoords . }",
                "OPTIONAL { ?item wdt:P625 ?coords . }"
            ])
        
        if include_cross_refs:
            optional_fields.extend([
                "?ta98", "?neurolexId", "?fmaId", "?meshId", "?uberonId"
            ])
            optional_patterns.extend([
                "OPTIONAL { ?item wdt:P1323 ?ta98 . }",
                "OPTIONAL { ?item wdt:P696 ?neurolexId . }",
                "OPTIONAL { ?item wdt:P1402 ?fmaId . }",
                "OPTIONAL { ?item wdt:P486 ?meshId . }",
                "OPTIONAL { ?item wdt:P1554 ?uberonId . }"
            ])
        
        if optional_fields:
            query_parts[4] += " " + " ".join(optional_fields)
        
        # Add WHERE clause
        query_parts.extend([
            "WHERE {",
            "  VALUES ?brainClass { " + " ".join(f"wd:{c}" for c in BRAIN_REGION_CLASSES) + " }",
            "  ?item wdt:P31/wdt:P279* ?brainClass .",
        ])
        
        # Add optional patterns
        query_parts.extend(optional_patterns)
        
        # Add language service
        query_parts.extend([
            f"  SERVICE wikibase:label {{ bd:serviceParam wikibase:language '{self.language},en' . }}",
            "}"
        ])
        
        # Add limit if specified
        if limit:
            query_parts.append(f"LIMIT {limit}")
        
        return "\n".join(query_parts)
    
    def _execute_sparql_query(self, query: str) -> List[Dict[str, Any]]:
        """Execute SPARQL query and return results."""
        try:
            self.sparql.setQuery(query)
            results = self.sparql.query().convert()
            self.stats["sparql_queries"] += 1
            
            # Extract bindings
            bindings = results.get("results", {}).get("bindings", [])
            return bindings
            
        except Exception as e:
            logger.error(f"SPARQL query failed: {e}")
            return []
    
    def _process_brain_regions(self, raw_regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process raw SPARQL results into structured brain region data."""
        processed = []
        
        for region in raw_regions:
            try:
                # Extract basic information
                processed_region = {
                    "wikidata_id": self._extract_value(region, "item", "uri"),
                    "name": self._extract_value(region, "itemLabel"),
                    "description": self._extract_value(region, "itemDescription"),
                    "source": "wikidata"
                }
                
                # Extract hierarchy
                if "partOf" in region:
                    processed_region["part_of"] = {
                        "id": self._extract_value(region, "partOf", "uri"),
                        "name": self._extract_value(region, "partOfLabel")
                    }
                
                # Extract coordinates
                coordinates = []
                if "mniCoords" in region:
                    mni = self._parse_coordinates(self._extract_value(region, "mniCoords"))
                    if mni:
                        coordinates.append({
                            "type": "MNI",
                            "x": mni[0],
                            "y": mni[1],
                            "z": mni[2]
                        })
                
                if "coords" in region:
                    coords = self._parse_coordinates(self._extract_value(region, "coords"))
                    if coords:
                        coordinates.append({
                            "type": "geographic",
                            "lat": coords[0],
                            "lon": coords[1]
                        })
                
                if coordinates:
                    processed_region["coordinates"] = coordinates
                
                # Extract cross-references
                cross_refs = {}
                ref_fields = [
                    ("ta98", "TA98"),
                    ("neurolexId", "NeuroLex"),
                    ("fmaId", "FMA"),
                    ("meshId", "MeSH"),
                    ("uberonId", "UBERON")
                ]
                
                for field, name in ref_fields:
                    if field in region:
                        value = self._extract_value(region, field)
                        if value:
                            cross_refs[name] = value
                
                if cross_refs:
                    processed_region["cross_references"] = cross_refs
                
                processed.append(processed_region)
                
            except Exception as e:
                logger.debug(f"Error processing region: {e}")
                continue
        
        return processed
    
    def _extract_value(
        self,
        binding: Dict[str, Any],
        key: str,
        value_type: str = "value"
    ) -> Optional[str]:
        """Extract value from SPARQL binding."""
        if key not in binding:
            return None
        
        value_dict = binding[key]
        
        if value_type == "uri":
            # Extract WikiData ID from URI
            uri = value_dict.get("value", "")
            if "wikidata.org/entity/" in uri:
                return uri.split("/")[-1]
            return uri
        
        return value_dict.get("value")
    
    def _parse_coordinates(self, coord_string: str) -> Optional[List[float]]:
        """Parse coordinate string into numeric values."""
        if not coord_string:
            return None
        
        try:
            # Handle different coordinate formats
            # MNI format: "Point(-10 20 30)"
            if "Point(" in coord_string:
                coords_part = coord_string.replace("Point(", "").replace(")", "")
                coords = [float(x) for x in coords_part.split()]
                return coords
            
            # Geographic format: "Point(lat lon)"
            if " " in coord_string:
                parts = coord_string.split()
                return [float(parts[0]), float(parts[1])]
            
            # Comma-separated
            if "," in coord_string:
                return [float(x.strip()) for x in coord_string.split(",")]
            
        except Exception as e:
            logger.debug(f"Could not parse coordinates '{coord_string}': {e}")
        
        return None
    
    def load_hierarchy(
        self,
        root_id: str = "Q1073",  # Q1073 = brain
        max_depth: int = 5
    ) -> Dict[str, Any]:
        """
        Load anatomical hierarchy starting from a root region.
        
        Args:
            root_id: WikiData ID of root region
            max_depth: Maximum hierarchy depth to traverse
        
        Returns:
            Hierarchical structure of brain regions
        """
        hierarchy = {
            "id": root_id,
            "name": None,
            "children": []
        }
        
        # Build recursive query
        query = self._build_hierarchy_query(root_id, max_depth)
        
        # Execute and process
        results = self._execute_sparql_query(query)
        
        # Build tree structure
        hierarchy = self._build_hierarchy_tree(results, root_id)
        
        return hierarchy
    
    def _build_hierarchy_query(self, root_id: str, max_depth: int) -> str:
        """Build SPARQL query for hierarchical structure."""
        query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?item ?itemLabel ?parent ?parentLabel
        WHERE {{
          wd:{root_id} wdt:P527* ?item .
          OPTIONAL {{ ?item wdt:P361 ?parent . }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language '{self.language},en' . }}
        }}
        """
        return query
    
    def _build_hierarchy_tree(
        self,
        results: List[Dict[str, Any]],
        root_id: str
    ) -> Dict[str, Any]:
        """Build tree structure from flat results."""
        # Create lookup of all items
        items = {}
        for result in results:
            item_id = self._extract_value(result, "item", "uri")
            if item_id:
                items[item_id] = {
                    "id": item_id,
                    "name": self._extract_value(result, "itemLabel"),
                    "parent": self._extract_value(result, "parent", "uri"),
                    "children": []
                }
        
        # Build tree
        root = items.get(root_id, {"id": root_id, "name": "Unknown", "children": []})
        
        # Add children
        for item_id, item in items.items():
            if item["parent"] and item["parent"] in items:
                items[item["parent"]]["children"].append(item)
        
        return root
    
    def search_regions(
        self,
        query: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search for brain regions by name or description.
        
        Args:
            query: Search query
            limit: Maximum number of results
        
        Returns:
            List of matching brain regions
        """
        sparql_query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT DISTINCT ?item ?itemLabel ?itemDescription
        WHERE {{
          VALUES ?brainClass {{ {" ".join(f"wd:{c}" for c in BRAIN_REGION_CLASSES)} }}
          ?item wdt:P31/wdt:P279* ?brainClass .
          ?item rdfs:label ?label .
          FILTER(CONTAINS(LCASE(?label), LCASE("{query}")))
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language '{self.language},en' . }}
        }}
        LIMIT {limit}
        """
        
        results = self._execute_sparql_query(sparql_query)
        return self._process_brain_regions(results)
    
    def get_region_details(self, wikidata_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific brain region.
        
        Args:
            wikidata_id: WikiData ID (e.g., Q1073 for brain)
        
        Returns:
            Detailed region information
        """
        query = f"""
        PREFIX wd: <http://www.wikidata.org/entity/>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?property ?propertyLabel ?value ?valueLabel
        WHERE {{
          wd:{wikidata_id} ?property ?value .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language '{self.language},en' . }}
        }}
        """
        
        results = self._execute_sparql_query(query)
        
        if not results:
            return None
        
        # Process into structured format
        details = {
            "id": wikidata_id,
            "properties": {}
        }
        
        for result in results:
            prop = self._extract_value(result, "propertyLabel")
            value = self._extract_value(result, "valueLabel") or self._extract_value(result, "value")
            
            if prop and value:
                if prop not in details["properties"]:
                    details["properties"][prop] = []
                details["properties"][prop].append(value)
        
        return details
    
    def export_to_json(self, output_path: str, regions: List[Dict[str, Any]]):
        """Export brain regions to JSON file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w") as f:
            json.dump(regions, f, indent=2)
        
        logger.info(f"Exported {len(regions)} regions to {output_path}")
    
    def _load_from_cache(self, key: str) -> Optional[Any]:
        """Load data from cache if not expired."""
        cache_file = self.cache_dir / f"{key}.json"
        
        if not cache_file.exists():
            return None
        
        try:
            # Check if cache is expired
            file_age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if file_age > self.cache_duration:
                return None
            
            with open(cache_file) as f:
                return json.load(f)
                
        except Exception as e:
            logger.debug(f"Error loading cache: {e}")
            return None
    
    def _save_to_cache(self, key: str, data: Any):
        """Save data to cache."""
        cache_file = self.cache_dir / f"{key}.json"
        
        try:
            with open(cache_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"Error saving cache: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get loader statistics."""
        return self.stats.copy()


# Convenience function
def load_brain_regions(limit: int = None):
    """
    Load brain regions using the unified loader.
    
    Args:
        limit: Maximum number of regions
    
    Returns:
        List of brain region dictionaries
    """
    loader = WikiDataUnifiedLoader()
    return loader.load_brain_regions(limit=limit)


if __name__ == "__main__":
    # Example usage
    loader = WikiDataUnifiedLoader()
    
    # Load brain regions
    regions = loader.load_brain_regions(limit=10)
    print(f"Loaded {len(regions)} brain regions")
    
    # Show sample region
    if regions:
        region = regions[0]
        print(f"\nSample region: {region.get('name')}")
        print(f"  ID: {region.get('wikidata_id')}")
        print(f"  Part of: {region.get('part_of', {}).get('name', 'N/A')}")
        print(f"  Cross-refs: {list(region.get('cross_references', {}).keys())}")
    
    # Search for specific region
    results = loader.search_regions("hippocampus", limit=5)
    print(f"\nSearch results for 'hippocampus': {len(results)} found")
    
    # Get hierarchy
    hierarchy = loader.load_hierarchy("Q1073", max_depth=2)
    print(f"\nBrain hierarchy: {hierarchy.get('name')} with {len(hierarchy.get('children', []))} direct children")
    
    # Print statistics
    print(f"\nStatistics: {loader.get_statistics()}")