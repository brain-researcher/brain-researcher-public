"""
Result Formatter Agent for Natural Language Query Processing

Formats query results for user consumption with natural language explanations.
"""

import logging
import json
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum

from .parser_agent import ParsedQuery

logger = logging.getLogger(__name__)


class VisualizationType(str, Enum):
    """Types of visualizations for results"""
    TABLE = "table"
    GRAPH = "graph"
    BRAIN_MAP = "brain_map"
    CHART = "chart"
    HEATMAP = "heatmap"
    TIMELINE = "timeline"
    NETWORK = "network"


@dataclass
class FormattedResult:
    """Formatted query result for user consumption"""
    summary: str
    data: List[Dict[str, Any]]
    visualization_hints: Dict[str, Any]
    explanation: Optional[str] = None
    confidence_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ResultFormatterAgent:
    """
    Agent responsible for formatting query results for user consumption.
    
    Handles:
    - Natural language summarization
    - Result transformation and structuring
    - Visualization recommendations
    - Explanation generation
    """
    
    def __init__(self):
        """Initialize the result formatter agent"""
        self.summary_templates = self._load_summary_templates()
        self.visualization_rules = self._load_visualization_rules()
    
    def _load_summary_templates(self) -> Dict[str, str]:
        """Load natural language summary templates"""
        return {
            'single_result': "Found {entity_type}: {entity_name}",
            'multiple_results': "Found {count} {entity_type}s matching your query",
            'activation_results': "The {task} task activates {count} brain regions, primarily in {regions}",
            'connectivity_results': "{region1} shows connectivity with {count} regions, strongest with {top_regions}",
            'disorder_results': "{disorder} is associated with alterations in {count} brain regions",
            'no_results': "No results found matching your query criteria",
            'aggregation_result': "The {metric} is {value} across {count} items",
            'comparison_result': "Comparing {entity1} and {entity2}: {comparison_summary}"
        }
    
    def _load_visualization_rules(self) -> Dict[str, Dict[str, Any]]:
        """Load rules for visualization selection"""
        return {
            'brain_region': {
                'primary': VisualizationType.BRAIN_MAP,
                'secondary': VisualizationType.TABLE,
                'requires': ['coordinates', 'activation_values']
            },
            'connectivity': {
                'primary': VisualizationType.NETWORK,
                'secondary': VisualizationType.HEATMAP,
                'requires': ['source_regions', 'target_regions', 'weights']
            },
            'temporal': {
                'primary': VisualizationType.TIMELINE,
                'secondary': VisualizationType.CHART,
                'requires': ['timestamps', 'values']
            },
            'comparison': {
                'primary': VisualizationType.CHART,
                'secondary': VisualizationType.TABLE,
                'requires': ['entities', 'values']
            }
        }
    
    def format_results(
        self,
        raw_results: Dict[str, Any],
        parsed_query: Optional[ParsedQuery] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> FormattedResult:
        """
        Format raw query results for user consumption
        
        Args:
            raw_results: Raw results from query execution
            parsed_query: Original parsed query for context
            context: Optional user context
            
        Returns:
            FormattedResult with summary, data, and visualization hints
        """
        # Extract and structure data
        structured_data = self._structure_results(raw_results)
        
        # Generate natural language summary
        summary = self._generate_summary(
            structured_data,
            parsed_query
        )
        
        # Determine visualization type and parameters
        visualization_hints = self._determine_visualization(
            structured_data,
            parsed_query
        )
        
        # Generate explanation if needed
        explanation = None
        if parsed_query and 'explain' in parsed_query.intent.lower():
            explanation = self._generate_explanation(
                structured_data,
                parsed_query
            )
        
        # Calculate formatting confidence
        confidence = self._calculate_confidence(
            structured_data,
            summary,
            parsed_query
        )
        
        # Add metadata
        metadata = self._generate_metadata(
            raw_results,
            structured_data,
            parsed_query
        )
        
        return FormattedResult(
            summary=summary,
            data=structured_data,
            visualization_hints=visualization_hints,
            explanation=explanation,
            confidence_score=confidence,
            metadata=metadata
        )
    
    def _structure_results(
        self,
        raw_results: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Structure raw results into consistent format"""
        structured = []
        
        # Handle different result formats
        if 'results' in raw_results:
            if isinstance(raw_results['results'], list):
                # Cypher-style results
                for item in raw_results['results']:
                    structured_item = self._structure_cypher_result(item)
                    if structured_item:
                        structured.append(structured_item)
            elif isinstance(raw_results['results'], dict):
                # SPARQL-style results
                if 'bindings' in raw_results['results']:
                    for binding in raw_results['results']['bindings']:
                        structured_item = self._structure_sparql_binding(binding)
                        if structured_item:
                            structured.append(structured_item)
        
        return structured
    
    def _structure_cypher_result(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Structure a Cypher query result item"""
        structured = {}
        
        for key, value in item.items():
            if isinstance(value, dict):
                # Neo4j node or relationship
                if 'labels' in value:
                    # Node
                    structured[key] = {
                        'type': 'node',
                        'labels': value.get('labels', []),
                        'properties': value.get('properties', {}),
                        'id': value.get('id')
                    }
                elif 'type' in value:
                    # Relationship
                    structured[key] = {
                        'type': 'relationship',
                        'relationship_type': value.get('type'),
                        'properties': value.get('properties', {}),
                        'start': value.get('startNode'),
                        'end': value.get('endNode')
                    }
                else:
                    structured[key] = value
            else:
                # Scalar value
                structured[key] = value
        
        return structured
    
    def _structure_sparql_binding(self, binding: Dict[str, Any]) -> Dict[str, Any]:
        """Structure a SPARQL query result binding"""
        structured = {}
        
        for var, value_obj in binding.items():
            if isinstance(value_obj, dict):
                value_type = value_obj.get('type', 'literal')
                value = value_obj.get('value', '')
                
                if value_type == 'uri':
                    # Extract meaningful part from URI
                    structured[var] = {
                        'type': 'uri',
                        'value': value,
                        'label': value.split('/')[-1].split('#')[-1]
                    }
                else:
                    structured[var] = value
            else:
                structured[var] = value_obj
        
        return structured
    
    def _generate_summary(
        self,
        data: List[Dict[str, Any]],
        parsed_query: Optional[ParsedQuery]
    ) -> str:
        """Generate natural language summary of results"""
        if not data:
            return self.summary_templates['no_results']
        
        # Analyze result structure
        result_count = len(data)
        
        # Determine primary entity type
        entity_types = self._extract_entity_types(data)
        primary_type = entity_types[0] if entity_types else 'result'
        
        # Generate appropriate summary based on query intent
        if parsed_query:
            intent = parsed_query.intent.value
            
            if 'aggregate' in intent or 'count' in intent:
                # Aggregation summary
                if data and 'count' in data[0]:
                    return f"Count: {data[0]['count']} items"
            
            elif 'compare' in intent:
                # Comparison summary
                return self._generate_comparison_summary(data, parsed_query)
            
            elif 'correlate' in intent or 'activate' in intent:
                # Activation/correlation summary
                return self._generate_activation_summary(data, parsed_query)
        
        # Default summary
        if result_count == 1:
            # Single result
            main_entity = self._extract_main_entity(data[0])
            return self.summary_templates['single_result'].format(
                entity_type=primary_type,
                entity_name=main_entity
            )
        else:
            # Multiple results
            return self.summary_templates['multiple_results'].format(
                count=result_count,
                entity_type=primary_type
            )
    
    def _generate_comparison_summary(
        self,
        data: List[Dict[str, Any]],
        parsed_query: ParsedQuery
    ) -> str:
        """Generate summary for comparison queries"""
        if len(data) < 2:
            return "Insufficient data for comparison"
        
        # Extract entities being compared
        entities = []
        for item in data[:2]:
            entity = self._extract_main_entity(item)
            entities.append(entity)
        
        # Find differences
        differences = []
        if all('properties' in item for item in data[:2]):
            props1 = data[0].get('properties', {})
            props2 = data[1].get('properties', {})
            
            for key in set(props1.keys()) | set(props2.keys()):
                if key in props1 and key in props2:
                    if props1[key] != props2[key]:
                        differences.append(f"{key}: {props1[key]} vs {props2[key]}")
        
        comparison_summary = "; ".join(differences[:3]) if differences else "similar profiles"
        
        return self.summary_templates['comparison_result'].format(
            entity1=entities[0],
            entity2=entities[1],
            comparison_summary=comparison_summary
        )
    
    def _generate_activation_summary(
        self,
        data: List[Dict[str, Any]],
        parsed_query: ParsedQuery
    ) -> str:
        """Generate summary for activation/correlation queries"""
        # Extract task and regions
        task = None
        regions = []
        
        for entity in parsed_query.entities:
            if entity.type.value == 'cognitive_task':
                task = entity.text
            elif entity.type.value == 'brain_region':
                regions.append(entity.text)
        
        # Extract regions from results
        result_regions = []
        for item in data:
            if 'region' in item:
                if isinstance(item['region'], dict):
                    region_name = item['region'].get('properties', {}).get('name', '')
                else:
                    region_name = str(item['region'])
                if region_name:
                    result_regions.append(region_name)
        
        if task and result_regions:
            top_regions = ', '.join(result_regions[:3])
            return self.summary_templates['activation_results'].format(
                task=task,
                count=len(result_regions),
                regions=top_regions
            )
        
        return f"Found {len(data)} activation results"
    
    def _determine_visualization(
        self,
        data: List[Dict[str, Any]],
        parsed_query: Optional[ParsedQuery]
    ) -> Dict[str, Any]:
        """Determine appropriate visualization for results"""
        viz_hints = {
            'type': VisualizationType.TABLE,  # Default
            'parameters': {}
        }
        
        # Analyze data structure
        has_coordinates = any('coordinates' in str(item) for item in data)
        has_connections = any('connected' in str(item).lower() for item in data)
        has_temporal = any('year' in str(item) or 'date' in str(item) for item in data)
        
        # Determine visualization based on data and query
        if has_coordinates:
            viz_hints['type'] = VisualizationType.BRAIN_MAP
            viz_hints['parameters'] = {
                'coordinate_field': 'coordinates',
                'value_field': 'activation_value',
                'colormap': 'hot'
            }
        
        elif has_connections:
            viz_hints['type'] = VisualizationType.NETWORK
            viz_hints['parameters'] = {
                'node_field': 'region',
                'edge_field': 'connection',
                'weight_field': 'strength',
                'layout': 'force-directed'
            }
        
        elif has_temporal:
            viz_hints['type'] = VisualizationType.TIMELINE
            viz_hints['parameters'] = {
                'time_field': 'year',
                'value_field': 'count',
                'grouping': 'category'
            }
        
        elif parsed_query and 'compare' in parsed_query.intent.value:
            viz_hints['type'] = VisualizationType.CHART
            viz_hints['parameters'] = {
                'chart_type': 'bar',
                'x_axis': 'entity',
                'y_axis': 'value'
            }
        
        elif len(data) > 10:
            # Large result set - suggest table with pagination
            viz_hints['type'] = VisualizationType.TABLE
            viz_hints['parameters'] = {
                'paginate': True,
                'page_size': 10,
                'sortable': True
            }
        
        return viz_hints
    
    def _generate_explanation(
        self,
        data: List[Dict[str, Any]],
        parsed_query: ParsedQuery
    ) -> str:
        """Generate explanation of results"""
        explanation_parts = []
        
        # Explain what was searched
        explanation_parts.append(
            f"Searched for: {parsed_query.original_query}"
        )
        
        # Explain entities found
        entities_found = []
        for entity in parsed_query.entities:
            entities_found.append(f"{entity.type.value}: {entity.text}")
        
        if entities_found:
            explanation_parts.append(
                f"Identified entities: {', '.join(entities_found)}"
            )
        
        # Explain result structure
        if data:
            data_structure = self._analyze_data_structure(data[0])
            explanation_parts.append(
                f"Result contains: {', '.join(data_structure)}"
            )
        
        # Explain relationships if present
        relationships = self._extract_relationships(data)
        if relationships:
            explanation_parts.append(
                f"Relationships found: {', '.join(relationships[:3])}"
            )
        
        return "\n".join(explanation_parts)
    
    def _generate_metadata(
        self,
        raw_results: Dict[str, Any],
        structured_data: List[Dict[str, Any]],
        parsed_query: Optional[ParsedQuery]
    ) -> Dict[str, Any]:
        """Generate metadata about the results"""
        metadata = {
            'result_count': len(structured_data),
            'has_more_results': False
        }
        
        # Add query metadata
        if parsed_query:
            metadata['query_intent'] = parsed_query.intent.value
            metadata['entity_count'] = len(parsed_query.entities)
            metadata['constraint_count'] = len(parsed_query.constraints)
        
        # Add data statistics
        if structured_data:
            metadata['data_types'] = list(self._extract_entity_types(structured_data))
            metadata['has_properties'] = any('properties' in item for item in structured_data)
            metadata['has_relationships'] = any('relationship' in str(item) for item in structured_data)
        
        # Check if results are truncated
        if 'count' in raw_results:
            total_count = raw_results['count']
            if total_count > len(structured_data):
                metadata['has_more_results'] = True
                metadata['total_count'] = total_count
        
        return metadata
    
    def _extract_entity_types(self, data: List[Dict[str, Any]]) -> List[str]:
        """Extract entity types from structured data"""
        entity_types = set()
        
        for item in data:
            for value in item.values():
                if isinstance(value, dict):
                    if 'type' in value:
                        entity_types.add(value['type'])
                    elif 'labels' in value:
                        entity_types.update(value['labels'])
        
        return list(entity_types)
    
    def _extract_main_entity(self, item: Dict[str, Any]) -> str:
        """Extract the main entity name from a result item"""
        # Try to find a name property
        for key, value in item.items():
            if isinstance(value, dict):
                props = value.get('properties', {})
                if 'name' in props:
                    return props['name']
                elif 'title' in props:
                    return props['title']
                elif 'label' in props:
                    return props['label']
            elif isinstance(value, str) and key in ['name', 'title', 'label']:
                return value
        
        # Fallback to first string value
        for value in item.values():
            if isinstance(value, str):
                return value
        
        return "Unknown"
    
    def _analyze_data_structure(self, item: Dict[str, Any]) -> List[str]:
        """Analyze the structure of a data item"""
        structure = []
        
        for key, value in item.items():
            if isinstance(value, dict):
                if 'type' in value:
                    structure.append(f"{key} ({value['type']})")
                else:
                    structure.append(key)
            else:
                structure.append(f"{key} (value)")
        
        return structure
    
    def _extract_relationships(self, data: List[Dict[str, Any]]) -> List[str]:
        """Extract relationship types from data"""
        relationships = set()
        
        for item in data:
            for value in item.values():
                if isinstance(value, dict):
                    if 'relationship_type' in value:
                        relationships.add(value['relationship_type'])
                    elif 'type' in value and value.get('type') == 'relationship':
                        rel_type = value.get('relationship_type', 'unknown')
                        relationships.add(rel_type)
        
        return list(relationships)
    
    def _calculate_confidence(
        self,
        data: List[Dict[str, Any]],
        summary: str,
        parsed_query: Optional[ParsedQuery]
    ) -> float:
        """Calculate confidence in formatting"""
        confidence = 0.5  # Base confidence
        
        # Increase confidence if we have results
        if data:
            confidence += 0.2
        
        # Increase confidence if summary is informative
        if summary and summary != self.summary_templates['no_results']:
            confidence += 0.1
        
        # Increase confidence based on parsed query confidence
        if parsed_query:
            confidence += parsed_query.confidence_score * 0.2
        
        # Decrease confidence for ambiguous results
        if data and len(data) > 100:
            confidence -= 0.1  # Too many results might indicate poor specificity
        
        return min(1.0, max(0.0, confidence))