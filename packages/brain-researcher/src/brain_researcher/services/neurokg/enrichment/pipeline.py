"""Graph enrichment pipeline for external data integration."""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import aiohttp
from enum import Enum
import hashlib
import json

logger = logging.getLogger(__name__)


class DataSource(str, Enum):
    """External data sources for enrichment."""
    WIKIDATA = "wikidata"
    PUBMED = "pubmed"
    UNIPROT = "uniprot"
    MESH = "mesh"
    ONTOBEE = "ontobee"
    BIOPORTAL = "bioportal"


class ConflictResolution(str, Enum):
    """Conflict resolution strategies."""
    KEEP_EXISTING = "keep_existing"
    OVERWRITE = "overwrite"
    MERGE = "merge"
    HIGHEST_CONFIDENCE = "highest_confidence"
    MOST_RECENT = "most_recent"


class EntityMatcher:
    """Matches entities across different sources."""
    
    def __init__(self):
        self.match_cache = {}
        self.confidence_threshold = 0.7
    
    def match_entities(self, 
                      source_entity: Dict[str, Any],
                      target_entities: List[Dict[str, Any]]) -> List[Tuple[Dict, float]]:
        """Match source entity to target entities with confidence scores.
        
        Args:
            source_entity: Entity to match
            target_entities: Potential matches
            
        Returns:
            List of (entity, confidence) tuples
        """
        matches = []
        
        for target in target_entities:
            confidence = self._calculate_confidence(source_entity, target)
            if confidence >= self.confidence_threshold:
                matches.append((target, confidence))
        
        # Sort by confidence
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches
    
    def _calculate_confidence(self, 
                            source: Dict[str, Any],
                            target: Dict[str, Any]) -> float:
        """Calculate matching confidence between entities.
        
        Args:
            source: Source entity
            target: Target entity
            
        Returns:
            Confidence score (0-1)
        """
        scores = []
        
        # Check identifiers
        if 'id' in source and 'id' in target:
            if source['id'] == target['id']:
                return 1.0  # Exact match
        
        # Check names
        if 'name' in source and 'name' in target:
            name_sim = self._string_similarity(source['name'], target['name'])
            scores.append(name_sim * 0.4)  # 40% weight
        
        # Check aliases
        if 'aliases' in source and 'aliases' in target:
            alias_matches = set(source['aliases']) & set(target['aliases'])
            if alias_matches:
                scores.append(0.3)  # 30% weight for alias match
        
        # Check properties
        common_props = set(source.keys()) & set(target.keys())
        if len(common_props) > 2:  # More than just id and name
            prop_matches = sum(1 for p in common_props 
                             if source[p] == target[p])
            prop_score = prop_matches / len(common_props)
            scores.append(prop_score * 0.3)  # 30% weight
        
        return min(sum(scores), 1.0)
    
    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using Jaccard index.
        
        Args:
            s1, s2: Strings to compare
            
        Returns:
            Similarity score (0-1)
        """
        s1_lower = s1.lower()
        s2_lower = s2.lower()
        
        # Exact match
        if s1_lower == s2_lower:
            return 1.0
        
        # Token-based similarity
        tokens1 = set(s1_lower.split())
        tokens2 = set(s2_lower.split())
        
        if not tokens1 or not tokens2:
            return 0.0
        
        intersection = tokens1 & tokens2
        union = tokens1 | tokens2
        
        return len(intersection) / len(union)


class ExternalAPIClient:
    """Client for external API integration."""
    
    def __init__(self):
        self.session = None
        self.rate_limits = {
            DataSource.WIKIDATA: 100,  # requests per minute
            DataSource.PUBMED: 180,
            DataSource.UNIPROT: 50,
            DataSource.MESH: 100,
            DataSource.ONTOBEE: 60,
            DataSource.BIOPORTAL: 150
        }
        self.last_request_time = {}
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def fetch_data(self, 
                        source: DataSource,
                        entity_id: str,
                        entity_type: str) -> Optional[Dict[str, Any]]:
        """Fetch data from external source.
        
        Args:
            source: Data source
            entity_id: Entity identifier
            entity_type: Type of entity
            
        Returns:
            Fetched data or None
        """
        # Rate limiting
        await self._rate_limit(source)
        
        try:
            if source == DataSource.WIKIDATA:
                return await self._fetch_wikidata(entity_id)
            elif source == DataSource.PUBMED:
                return await self._fetch_pubmed(entity_id)
            elif source == DataSource.UNIPROT:
                return await self._fetch_uniprot(entity_id)
            elif source == DataSource.MESH:
                return await self._fetch_mesh(entity_id)
            else:
                logger.warning(f"Unsupported source: {source}")
                return None
        except Exception as e:
            logger.error(f"Error fetching from {source}: {e}")
            return None
    
    async def _rate_limit(self, source: DataSource):
        """Apply rate limiting for source.
        
        Args:
            source: Data source
        """
        if source in self.last_request_time:
            elapsed = datetime.now() - self.last_request_time[source]
            min_interval = timedelta(minutes=1) / self.rate_limits[source]
            
            if elapsed < min_interval:
                wait_time = (min_interval - elapsed).total_seconds()
                await asyncio.sleep(wait_time)
        
        self.last_request_time[source] = datetime.now()
    
    async def _fetch_wikidata(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Fetch from Wikidata."""
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
        
        async with self.session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return self._parse_wikidata(data)
        return None
    
    async def _fetch_pubmed(self, pmid: str) -> Optional[Dict[str, Any]]:
        """Fetch from PubMed."""
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "json"
        }
        
        async with self.session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return self._parse_pubmed(data)
        return None
    
    async def _fetch_uniprot(self, uniprot_id: str) -> Optional[Dict[str, Any]]:
        """Fetch from UniProt."""
        url = f"https://rest.uniprot.org/uniprotkb/{uniprot_id}.json"
        
        async with self.session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return self._parse_uniprot(data)
        return None
    
    async def _fetch_mesh(self, mesh_id: str) -> Optional[Dict[str, Any]]:
        """Fetch from MeSH."""
        # Simplified - actual implementation would use MeSH API
        return {
            "id": mesh_id,
            "source": "mesh",
            "name": f"MeSH Term {mesh_id}",
            "category": "medical_subject_heading"
        }
    
    def _parse_wikidata(self, data: Dict) -> Dict[str, Any]:
        """Parse Wikidata response."""
        # Simplified parsing
        entities = data.get('entities', {})
        if not entities:
            return None
        
        entity = list(entities.values())[0]
        return {
            "id": entity.get('id'),
            "source": "wikidata",
            "labels": entity.get('labels', {}),
            "descriptions": entity.get('descriptions', {}),
            "aliases": entity.get('aliases', {}),
            "claims": entity.get('claims', {})
        }
    
    def _parse_pubmed(self, data: Dict) -> Dict[str, Any]:
        """Parse PubMed response."""
        # Simplified parsing
        return {
            "source": "pubmed",
            "data": data
        }
    
    def _parse_uniprot(self, data: Dict) -> Dict[str, Any]:
        """Parse UniProt response."""
        return {
            "id": data.get('primaryAccession'),
            "source": "uniprot",
            "name": data.get('proteinDescription', {}).get('recommendedName', {}),
            "organism": data.get('organism', {}),
            "sequence": data.get('sequence', {})
        }


class GraphEnrichmentPipeline:
    """Main enrichment pipeline."""
    
    def __init__(self):
        self.entity_matcher = EntityMatcher()
        self.enrichment_stats = {
            "total_processed": 0,
            "successful_enrichments": 0,
            "conflicts_resolved": 0,
            "errors": 0
        }
        self.provenance_records = []
    
    async def enrich_graph(self,
                          nodes: List[Dict[str, Any]],
                          sources: List[DataSource],
                          conflict_strategy: ConflictResolution = ConflictResolution.HIGHEST_CONFIDENCE) -> Dict[str, Any]:
        """Enrich graph nodes with external data.
        
        Args:
            nodes: Graph nodes to enrich
            sources: Data sources to use
            conflict_strategy: How to resolve conflicts
            
        Returns:
            Enrichment results
        """
        enriched_nodes = []
        
        async with ExternalAPIClient() as client:
            tasks = []
            for node in nodes:
                for source in sources:
                    task = self._enrich_node(node, source, client, conflict_strategy)
                    tasks.append(task)
            
            # Process in batches to avoid overwhelming
            batch_size = 10
            for i in range(0, len(tasks), batch_size):
                batch = tasks[i:i+batch_size]
                results = await asyncio.gather(*batch, return_exceptions=True)
                
                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"Enrichment error: {result}")
                        self.enrichment_stats["errors"] += 1
                    elif result:
                        enriched_nodes.append(result)
                        self.enrichment_stats["successful_enrichments"] += 1
        
        self.enrichment_stats["total_processed"] = len(nodes)
        
        return {
            "enriched_nodes": enriched_nodes,
            "statistics": self.enrichment_stats,
            "provenance": self.provenance_records[-100:]  # Last 100 records
        }
    
    async def _enrich_node(self,
                          node: Dict[str, Any],
                          source: DataSource,
                          client: ExternalAPIClient,
                          conflict_strategy: ConflictResolution) -> Optional[Dict[str, Any]]:
        """Enrich single node from source.
        
        Args:
            node: Node to enrich
            source: Data source
            client: API client
            conflict_strategy: Conflict resolution strategy
            
        Returns:
            Enriched node or None
        """
        # Fetch external data
        external_data = await client.fetch_data(
            source,
            node.get('id', ''),
            node.get('type', '')
        )
        
        if not external_data:
            return None
        
        # Match entities
        matches = self.entity_matcher.match_entities(
            external_data,
            [node]
        )
        
        if not matches:
            return None
        
        # Apply enrichment
        enriched_node = node.copy()
        matched_entity, confidence = matches[0]
        
        # Resolve conflicts
        merged_data = self._resolve_conflicts(
            enriched_node,
            external_data,
            conflict_strategy,
            confidence
        )
        
        enriched_node.update(merged_data)
        
        # Track provenance
        self._track_provenance(
            node['id'],
            source,
            confidence,
            conflict_strategy
        )
        
        return enriched_node
    
    def _resolve_conflicts(self,
                          existing: Dict[str, Any],
                          new_data: Dict[str, Any],
                          strategy: ConflictResolution,
                          confidence: float) -> Dict[str, Any]:
        """Resolve conflicts between existing and new data.
        
        Args:
            existing: Existing node data
            new_data: New external data
            strategy: Resolution strategy
            confidence: Match confidence
            
        Returns:
            Merged data
        """
        if strategy == ConflictResolution.KEEP_EXISTING:
            return {}  # No updates
        
        elif strategy == ConflictResolution.OVERWRITE:
            return new_data
        
        elif strategy == ConflictResolution.MERGE:
            # Merge non-conflicting fields
            merged = {}
            for key, value in new_data.items():
                if key not in existing:
                    merged[key] = value
                elif isinstance(existing[key], list) and isinstance(value, list):
                    merged[key] = list(set(existing[key] + value))
                elif isinstance(existing[key], dict) and isinstance(value, dict):
                    merged[key] = {**existing[key], **value}
            return merged
        
        elif strategy == ConflictResolution.HIGHEST_CONFIDENCE:
            # Only update if confidence is high
            if confidence >= 0.9:
                return new_data
            elif confidence >= 0.7:
                # Partial update
                return {k: v for k, v in new_data.items() 
                       if k not in existing}
            return {}
        
        elif strategy == ConflictResolution.MOST_RECENT:
            # Assume new data is more recent
            return new_data
        
        return {}
    
    def _track_provenance(self,
                         node_id: str,
                         source: DataSource,
                         confidence: float,
                         strategy: ConflictResolution):
        """Track enrichment provenance.
        
        Args:
            node_id: Node identifier
            source: Data source used
            confidence: Match confidence
            strategy: Conflict resolution used
        """
        self.provenance_records.append({
            "timestamp": datetime.now().isoformat(),
            "node_id": node_id,
            "source": source.value,
            "confidence": confidence,
            "strategy": strategy.value,
            "hash": hashlib.md5(
                f"{node_id}{source}{confidence}".encode()
            ).hexdigest()
        })
    
    def schedule_updates(self, 
                        update_interval: timedelta = timedelta(days=7)) -> Dict[str, Any]:
        """Schedule periodic enrichment updates.
        
        Args:
            update_interval: How often to update
            
        Returns:
            Update schedule
        """
        # In production, this would integrate with a scheduler
        next_update = datetime.now() + update_interval
        
        return {
            "next_update": next_update.isoformat(),
            "interval_days": update_interval.days,
            "sources": [s.value for s in DataSource],
            "last_stats": self.enrichment_stats
        }