"""
Enhanced Evidence Collection and Aggregation System

This module extends the base evidence collection with advanced aggregation,
confidence scoring, provenance tracking, and visualization capabilities.
"""

import asyncio
import json
import logging
import numpy as np
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import uuid4

import networkx as nx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from brain_researcher.services.agent.evidence_collection import (
    EvidenceCollector, Evidence, EvidenceChain, EvidenceType, ConfidenceLevel
)

logger = logging.getLogger(__name__)


@dataclass
class EvidenceAggregation:
    """Aggregated evidence from multiple sources."""
    aggregation_id: str
    evidence_ids: List[str]
    aggregation_method: str
    aggregated_content: Dict[str, Any]
    confidence_score: float
    consensus_level: float
    conflicting_evidence: List[str] = field(default_factory=list)
    supporting_evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProvenanceNode:
    """Node in the provenance graph."""
    node_id: str
    node_type: str  # 'evidence', 'tool', 'dataset', 'user', 'inference'
    content: Dict[str, Any]
    timestamp: float
    confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'node_id': self.node_id,
            'node_type': self.node_type,
            'content': self.content,
            'timestamp': self.timestamp,
            'confidence': self.confidence
        }


@dataclass
class ProvenanceEdge:
    """Edge in the provenance graph."""
    edge_id: str
    source_id: str
    target_id: str
    edge_type: str  # 'derivedFrom', 'usedBy', 'generatedBy', 'influencedBy'
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'edge_id': self.edge_id,
            'source_id': self.source_id,
            'target_id': self.target_id,
            'edge_type': self.edge_type,
            'metadata': self.metadata
        }


class EvidenceAggregator:
    """Advanced evidence aggregation with confidence assessment."""
    
    def __init__(self):
        """Initialize evidence aggregator."""
        self.aggregation_methods = {
            'consensus': self._consensus_aggregation,
            'weighted_average': self._weighted_average_aggregation,
            'majority_vote': self._majority_vote_aggregation,
            'bayesian_fusion': self._bayesian_fusion_aggregation,
            'meta_analysis': self._meta_analysis_aggregation
        }
        
        logger.info("Evidence aggregator initialized")
    
    def aggregate_evidence(
        self,
        evidence_list: List[Evidence],
        method: str = 'consensus',
        domain_knowledge: Dict[str, Any] = None
    ) -> EvidenceAggregation:
        """
        Aggregate multiple pieces of evidence using specified method.
        
        Args:
            evidence_list: List of evidence to aggregate
            method: Aggregation method to use
            domain_knowledge: Domain-specific knowledge for aggregation
            
        Returns:
            Aggregated evidence result
        """
        if method not in self.aggregation_methods:
            raise ValueError(f"Unknown aggregation method: {method}")
        
        if not evidence_list:
            raise ValueError("Cannot aggregate empty evidence list")
        
        # Group evidence by type for better aggregation
        evidence_by_type = defaultdict(list)
        for evidence in evidence_list:
            evidence_by_type[evidence.type].append(evidence)
        
        # Apply aggregation method
        aggregation_func = self.aggregation_methods[method]
        result = aggregation_func(evidence_list, domain_knowledge or {})
        
        return result
    
    def _consensus_aggregation(
        self, 
        evidence_list: List[Evidence], 
        domain_knowledge: Dict[str, Any]
    ) -> EvidenceAggregation:
        """Aggregate evidence using consensus-based approach."""
        
        # Calculate content similarity matrix
        contents = [json.dumps(e.content, sort_keys=True, default=str) for e in evidence_list]
        
        if len(set(contents)) == 1:
            # Perfect consensus
            consensus_content = evidence_list[0].content
            consensus_level = 1.0
            supporting_evidence = [e.evidence_id for e in evidence_list]
            conflicting_evidence = []
        else:
            # Find common elements
            consensus_content = self._extract_consensus_content(evidence_list)
            consensus_level = self._calculate_consensus_level(evidence_list)
            supporting_evidence, conflicting_evidence = self._classify_evidence_support(
                evidence_list, consensus_content
            )
        
        # Calculate overall confidence
        confidence_scores = [self._confidence_to_numeric(e.confidence) for e in evidence_list]
        weighted_confidence = np.average(confidence_scores, weights=[1.0] * len(confidence_scores))
        
        # Adjust confidence based on consensus
        overall_confidence = weighted_confidence * consensus_level
        
        return EvidenceAggregation(
            aggregation_id=f"agg_{uuid4().hex[:8]}",
            evidence_ids=[e.evidence_id for e in evidence_list],
            aggregation_method='consensus',
            aggregated_content=consensus_content,
            confidence_score=overall_confidence,
            consensus_level=consensus_level,
            supporting_evidence=supporting_evidence,
            conflicting_evidence=conflicting_evidence
        )
    
    def _weighted_average_aggregation(
        self, 
        evidence_list: List[Evidence], 
        domain_knowledge: Dict[str, Any]
    ) -> EvidenceAggregation:
        """Aggregate evidence using weighted averaging."""
        
        # Extract numerical values from evidence content
        numerical_data = []
        weights = []
        
        for evidence in evidence_list:
            numeric_values = self._extract_numerical_values(evidence.content)
            if numeric_values:
                numerical_data.append(numeric_values)
                weight = self._confidence_to_numeric(evidence.confidence)
                
                # Apply domain knowledge weights
                source_weight = domain_knowledge.get('source_weights', {}).get(evidence.source, 1.0)
                weights.append(weight * source_weight)
        
        if not numerical_data:
            # Fallback to consensus aggregation
            return self._consensus_aggregation(evidence_list, domain_knowledge)
        
        # Calculate weighted averages
        aggregated_values = {}
        for key in numerical_data[0].keys():
            values = [data.get(key, 0) for data in numerical_data]
            if values:
                weighted_avg = np.average(values, weights=weights)
                aggregated_values[key] = float(weighted_avg)
        
        # Calculate confidence
        overall_confidence = np.average(weights) if weights else 0.5
        
        return EvidenceAggregation(
            aggregation_id=f"agg_{uuid4().hex[:8]}",
            evidence_ids=[e.evidence_id for e in evidence_list],
            aggregation_method='weighted_average',
            aggregated_content=aggregated_values,
            confidence_score=overall_confidence,
            consensus_level=self._calculate_consensus_level(evidence_list),
            supporting_evidence=[e.evidence_id for e in evidence_list]
        )
    
    def _majority_vote_aggregation(
        self, 
        evidence_list: List[Evidence], 
        domain_knowledge: Dict[str, Any]
    ) -> EvidenceAggregation:
        """Aggregate evidence using majority voting."""
        
        # Extract categorical decisions from evidence
        decisions = []
        weights = []
        
        for evidence in evidence_list:
            decision = self._extract_decision(evidence.content)
            if decision:
                decisions.append(decision)
                weights.append(self._confidence_to_numeric(evidence.confidence))
        
        if not decisions:
            return self._consensus_aggregation(evidence_list, domain_knowledge)
        
        # Perform weighted majority vote
        decision_scores = defaultdict(float)
        for decision, weight in zip(decisions, weights):
            decision_scores[decision] += weight
        
        # Get majority decision
        majority_decision = max(decision_scores.items(), key=lambda x: x[1])
        
        # Calculate support
        supporting_count = sum(1 for d in decisions if d == majority_decision[0])
        consensus_level = supporting_count / len(decisions)
        
        aggregated_content = {
            'decision': majority_decision[0],
            'score': majority_decision[1],
            'vote_distribution': dict(decision_scores),
            'total_votes': len(decisions)
        }
        
        return EvidenceAggregation(
            aggregation_id=f"agg_{uuid4().hex[:8]}",
            evidence_ids=[e.evidence_id for e in evidence_list],
            aggregation_method='majority_vote',
            aggregated_content=aggregated_content,
            confidence_score=majority_decision[1] / sum(weights),
            consensus_level=consensus_level,
            supporting_evidence=[
                e.evidence_id for e, d in zip(evidence_list, decisions) 
                if d == majority_decision[0]
            ]
        )
    
    def _bayesian_fusion_aggregation(
        self, 
        evidence_list: List[Evidence], 
        domain_knowledge: Dict[str, Any]
    ) -> EvidenceAggregation:
        """Aggregate evidence using Bayesian fusion."""
        
        # Simplified Bayesian fusion for binary decisions
        prior_prob = domain_knowledge.get('prior_probability', 0.5)
        
        likelihood_positive = []
        likelihood_negative = []
        
        for evidence in evidence_list:
            confidence = self._confidence_to_numeric(evidence.confidence)
            decision = self._extract_decision(evidence.content)
            
            if decision == 'positive' or decision == True:
                likelihood_positive.append(confidence)
                likelihood_negative.append(1 - confidence)
            elif decision == 'negative' or decision == False:
                likelihood_positive.append(1 - confidence)
                likelihood_negative.append(confidence)
            else:
                # Neutral evidence
                likelihood_positive.append(0.5)
                likelihood_negative.append(0.5)
        
        # Calculate posterior probabilities
        pos_likelihood = np.prod(likelihood_positive) if likelihood_positive else 0.5
        neg_likelihood = np.prod(likelihood_negative) if likelihood_negative else 0.5
        
        posterior_positive = (pos_likelihood * prior_prob) / (
            pos_likelihood * prior_prob + neg_likelihood * (1 - prior_prob)
        )
        
        aggregated_content = {
            'posterior_probability': float(posterior_positive),
            'prior_probability': prior_prob,
            'likelihood_positive': float(pos_likelihood),
            'likelihood_negative': float(neg_likelihood),
            'evidence_count': len(evidence_list)
        }
        
        return EvidenceAggregation(
            aggregation_id=f"agg_{uuid4().hex[:8]}",
            evidence_ids=[e.evidence_id for e in evidence_list],
            aggregation_method='bayesian_fusion',
            aggregated_content=aggregated_content,
            confidence_score=max(posterior_positive, 1 - posterior_positive),
            consensus_level=abs(posterior_positive - 0.5) * 2,
            supporting_evidence=[e.evidence_id for e in evidence_list]
        )
    
    def _meta_analysis_aggregation(
        self, 
        evidence_list: List[Evidence], 
        domain_knowledge: Dict[str, Any]
    ) -> EvidenceAggregation:
        """Aggregate evidence using meta-analysis approach."""
        
        # Extract effect sizes and standard errors
        effect_sizes = []
        standard_errors = []
        sample_sizes = []
        
        for evidence in evidence_list:
            effect_size = evidence.content.get('effect_size')
            std_error = evidence.content.get('standard_error')
            sample_size = evidence.content.get('sample_size', 1)
            
            if effect_size is not None and std_error is not None:
                effect_sizes.append(float(effect_size))
                standard_errors.append(float(std_error))
                sample_sizes.append(int(sample_size))
        
        if not effect_sizes:
            return self._weighted_average_aggregation(evidence_list, domain_knowledge)
        
        # Calculate inverse-variance weights
        variances = [se**2 for se in standard_errors]
        weights = [1/var if var > 0 else 1.0 for var in variances]
        
        # Calculate pooled effect size
        pooled_effect = np.average(effect_sizes, weights=weights)
        pooled_variance = 1 / sum(weights) if sum(weights) > 0 else 1.0
        pooled_se = np.sqrt(pooled_variance)
        
        # Calculate heterogeneity statistics
        q_statistic = sum(w * (es - pooled_effect)**2 for w, es in zip(weights, effect_sizes))
        i_squared = max(0, (q_statistic - len(effect_sizes) + 1) / q_statistic) if q_statistic > 0 else 0
        
        aggregated_content = {
            'pooled_effect_size': float(pooled_effect),
            'pooled_standard_error': float(pooled_se),
            'confidence_interval_95': [
                float(pooled_effect - 1.96 * pooled_se),
                float(pooled_effect + 1.96 * pooled_se)
            ],
            'q_statistic': float(q_statistic),
            'i_squared': float(i_squared),
            'total_sample_size': sum(sample_sizes),
            'study_count': len(effect_sizes)
        }
        
        # Confidence based on precision and heterogeneity
        precision = 1 / pooled_se if pooled_se > 0 else 1.0
        heterogeneity_penalty = 1 - min(0.5, i_squared)
        confidence = min(1.0, precision * 0.1 * heterogeneity_penalty)
        
        return EvidenceAggregation(
            aggregation_id=f"agg_{uuid4().hex[:8]}",
            evidence_ids=[e.evidence_id for e in evidence_list],
            aggregation_method='meta_analysis',
            aggregated_content=aggregated_content,
            confidence_score=confidence,
            consensus_level=heterogeneity_penalty,
            supporting_evidence=[e.evidence_id for e in evidence_list]
        )
    
    def _extract_consensus_content(self, evidence_list: List[Evidence]) -> Dict[str, Any]:
        """Extract consensus content from evidence list."""
        all_keys = set()
        for evidence in evidence_list:
            all_keys.update(evidence.content.keys())
        
        consensus_content = {}
        for key in all_keys:
            values = [e.content.get(key) for e in evidence_list if key in e.content]
            
            if values:
                # Find most common value
                value_counts = {}
                for value in values:
                    value_str = str(value)
                    value_counts[value_str] = value_counts.get(value_str, 0) + 1
                
                most_common_value = max(value_counts.items(), key=lambda x: x[1])
                if most_common_value[1] >= len(values) * 0.5:  # Majority threshold
                    # Try to convert back to original type
                    try:
                        consensus_content[key] = json.loads(most_common_value[0])
                    except:
                        consensus_content[key] = most_common_value[0]
        
        return consensus_content
    
    def _calculate_consensus_level(self, evidence_list: List[Evidence]) -> float:
        """Calculate level of consensus among evidence."""
        if len(evidence_list) <= 1:
            return 1.0
        
        # Compare evidence content pairwise
        similarities = []
        for i in range(len(evidence_list)):
            for j in range(i + 1, len(evidence_list)):
                sim = self._calculate_content_similarity(
                    evidence_list[i].content, 
                    evidence_list[j].content
                )
                similarities.append(sim)
        
        return np.mean(similarities) if similarities else 0.0
    
    def _calculate_content_similarity(self, content1: Dict[str, Any], content2: Dict[str, Any]) -> float:
        """Calculate similarity between two content dictionaries."""
        # Convert to JSON strings for comparison
        str1 = json.dumps(content1, sort_keys=True, default=str)
        str2 = json.dumps(content2, sort_keys=True, default=str)
        
        if str1 == str2:
            return 1.0
        
        # Use Jaccard similarity for sets of key-value pairs
        items1 = set(str1.split())
        items2 = set(str2.split())
        
        intersection = len(items1 & items2)
        union = len(items1 | items2)
        
        return intersection / union if union > 0 else 0.0
    
    def _classify_evidence_support(
        self, 
        evidence_list: List[Evidence], 
        consensus_content: Dict[str, Any]
    ) -> Tuple[List[str], List[str]]:
        """Classify evidence as supporting or conflicting with consensus."""
        supporting = []
        conflicting = []
        
        for evidence in evidence_list:
            similarity = self._calculate_content_similarity(evidence.content, consensus_content)
            if similarity >= 0.7:  # Threshold for support
                supporting.append(evidence.evidence_id)
            elif similarity <= 0.3:  # Threshold for conflict
                conflicting.append(evidence.evidence_id)
            # Evidence in between is neither strongly supporting nor conflicting
        
        return supporting, conflicting
    
    def _confidence_to_numeric(self, confidence: ConfidenceLevel) -> float:
        """Convert confidence level to numeric value."""
        mapping = {
            ConfidenceLevel.HIGH: 0.9,
            ConfidenceLevel.MEDIUM: 0.7,
            ConfidenceLevel.LOW: 0.4,
            ConfidenceLevel.UNKNOWN: 0.5
        }
        return mapping.get(confidence, 0.5)
    
    def _extract_numerical_values(self, content: Dict[str, Any]) -> Dict[str, float]:
        """Extract numerical values from content."""
        numerical = {}
        for key, value in content.items():
            if isinstance(value, (int, float)):
                numerical[key] = float(value)
            elif isinstance(value, str):
                try:
                    numerical[key] = float(value)
                except ValueError:
                    continue
        return numerical
    
    def _extract_decision(self, content: Dict[str, Any]) -> Optional[str]:
        """Extract a categorical decision from content."""
        # Look for common decision fields
        decision_fields = ['decision', 'result', 'conclusion', 'significant', 'positive', 'negative']
        
        for field in decision_fields:
            if field in content:
                value = content[field]
                if isinstance(value, bool):
                    return 'positive' if value else 'negative'
                elif isinstance(value, str):
                    value_lower = value.lower()
                    if value_lower in ['true', 'yes', 'positive', 'significant']:
                        return 'positive'
                    elif value_lower in ['false', 'no', 'negative', 'non-significant']:
                        return 'negative'
                    else:
                        return value_lower
        
        return None


class ProvenanceTracker:
    """Advanced provenance tracking for full reproducibility."""
    
    def __init__(self):
        """Initialize provenance tracker."""
        self.provenance_graph = nx.DiGraph()
        self.nodes: Dict[str, ProvenanceNode] = {}
        self.edges: Dict[str, ProvenanceEdge] = {}
        
        logger.info("Provenance tracker initialized")
    
    def add_node(
        self, 
        node_type: str,
        content: Dict[str, Any],
        node_id: Optional[str] = None,
        confidence: float = 1.0
    ) -> str:
        """Add a node to the provenance graph."""
        if node_id is None:
            node_id = f"{node_type}_{uuid4().hex[:8]}"
        
        node = ProvenanceNode(
            node_id=node_id,
            node_type=node_type,
            content=content,
            timestamp=time.time(),
            confidence=confidence
        )
        
        self.nodes[node_id] = node
        self.provenance_graph.add_node(node_id, **node.to_dict())
        
        logger.debug(f"Added provenance node: {node_id} ({node_type})")
        return node_id
    
    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: str,
        metadata: Dict[str, Any] = None
    ) -> str:
        """Add an edge to the provenance graph."""
        edge_id = f"{edge_type}_{uuid4().hex[:8]}"
        
        edge = ProvenanceEdge(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            metadata=metadata or {}
        )
        
        self.edges[edge_id] = edge
        self.provenance_graph.add_edge(source_id, target_id, **edge.to_dict())
        
        logger.debug(f"Added provenance edge: {source_id} --{edge_type}--> {target_id}")
        return edge_id
    
    def trace_provenance(self, target_id: str, max_depth: int = 10) -> Dict[str, Any]:
        """Trace the complete provenance of a target node."""
        if target_id not in self.nodes:
            return {"error": f"Node {target_id} not found"}
        
        # Find all predecessors within max_depth
        predecessors = set()
        queue = [(target_id, 0)]
        
        while queue:
            current_id, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            
            predecessors.add(current_id)
            
            # Add all predecessors
            for pred_id in self.provenance_graph.predecessors(current_id):
                if pred_id not in predecessors:
                    queue.append((pred_id, depth + 1))
        
        # Build provenance subgraph
        subgraph = self.provenance_graph.subgraph(predecessors)
        
        # Create trace result
        trace_result = {
            "target_node": self.nodes[target_id].to_dict(),
            "provenance_nodes": [
                self.nodes[node_id].to_dict() 
                for node_id in predecessors 
                if node_id != target_id
            ],
            "provenance_edges": [
                self.edges[edge_id].to_dict()
                for edge_id in self.edges
                if (self.edges[edge_id].source_id in predecessors and 
                    self.edges[edge_id].target_id in predecessors)
            ],
            "depth": max_depth,
            "total_nodes": len(predecessors)
        }
        
        return trace_result
    
    def get_derivation_chain(self, target_id: str) -> List[Dict[str, Any]]:
        """Get the linear derivation chain for a target node."""
        chain = []
        current_id = target_id
        
        while current_id:
            if current_id in self.nodes:
                chain.append(self.nodes[current_id].to_dict())
            
            # Find the most direct predecessor (derivedFrom edge)
            predecessors = list(self.provenance_graph.predecessors(current_id))
            next_id = None
            
            for pred_id in predecessors:
                edge_data = self.provenance_graph.get_edge_data(pred_id, current_id)
                if edge_data and edge_data.get('edge_type') == 'derivedFrom':
                    next_id = pred_id
                    break
            
            if not next_id and predecessors:
                # Fallback to any predecessor
                next_id = predecessors[0]
            
            current_id = next_id
            
            # Prevent infinite loops
            if len(chain) > 50:
                break
        
        return list(reversed(chain))  # Return in chronological order
    
    def export_provenance_graph(self, format: str = 'json') -> Union[str, Dict[str, Any]]:
        """Export the provenance graph in specified format."""
        if format == 'json':
            return {
                'nodes': [node.to_dict() for node in self.nodes.values()],
                'edges': [edge.to_dict() for edge in self.edges.values()],
                'statistics': {
                    'total_nodes': len(self.nodes),
                    'total_edges': len(self.edges),
                    'node_types': list(set(node.node_type for node in self.nodes.values()))
                }
            }
        elif format == 'dot':
            # GraphViz DOT format
            lines = ['digraph provenance {']
            
            # Add nodes
            for node in self.nodes.values():
                label = f"{node.node_type}\\n{node.node_id[:8]}"
                lines.append(f'  "{node.node_id}" [label="{label}"];')
            
            # Add edges
            for edge in self.edges.values():
                lines.append(f'  "{edge.source_id}" -> "{edge.target_id}" [label="{edge.edge_type}"];')
            
            lines.append('}')
            return '\n'.join(lines)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def validate_provenance_integrity(self) -> Dict[str, Any]:
        """Validate the integrity of the provenance graph."""
        issues = []
        
        # Check for orphaned edges
        for edge in self.edges.values():
            if edge.source_id not in self.nodes:
                issues.append(f"Edge {edge.edge_id} references missing source node {edge.source_id}")
            if edge.target_id not in self.nodes:
                issues.append(f"Edge {edge.edge_id} references missing target node {edge.target_id}")
        
        # Check for cycles (shouldn't exist in proper provenance)
        if not nx.is_directed_acyclic_graph(self.provenance_graph):
            cycles = list(nx.simple_cycles(self.provenance_graph))
            issues.append(f"Found {len(cycles)} cycles in provenance graph")
        
        # Check for isolated nodes
        isolated = list(nx.isolates(self.provenance_graph))
        if isolated:
            issues.append(f"Found {len(isolated)} isolated nodes")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'statistics': {
                'nodes': len(self.nodes),
                'edges': len(self.edges),
                'connected_components': nx.number_weakly_connected_components(self.provenance_graph)
            }
        }


class EvidenceVisualizationAPI:
    """API for creating evidence visualizations and reports."""
    
    def __init__(self, evidence_collector: EvidenceCollector):
        """Initialize evidence visualization API."""
        self.evidence_collector = evidence_collector
        logger.info("Evidence visualization API initialized")
    
    def create_evidence_timeline(self) -> Dict[str, Any]:
        """Create a timeline visualization of evidence collection."""
        all_evidence = list(self.evidence_collector.evidence.values())
        
        # Sort by timestamp
        sorted_evidence = sorted(all_evidence, key=lambda e: e.timestamp)
        
        timeline_data = []
        for evidence in sorted_evidence:
            timeline_data.append({
                'timestamp': evidence.timestamp,
                'evidence_id': evidence.evidence_id,
                'type': evidence.type.value,
                'source': evidence.source,
                'confidence': evidence.confidence.value,
                'summary': self._summarize_evidence_content(evidence.content)
            })
        
        return {
            'timeline': timeline_data,
            'total_evidence': len(timeline_data),
            'time_span': {
                'start': min(e['timestamp'] for e in timeline_data) if timeline_data else 0,
                'end': max(e['timestamp'] for e in timeline_data) if timeline_data else 0
            }
        }
    
    def create_confidence_distribution(self) -> Dict[str, Any]:
        """Create confidence score distribution visualization."""
        confidence_counts = {level.value: 0 for level in ConfidenceLevel}
        
        for evidence in self.evidence_collector.evidence.values():
            confidence_counts[evidence.confidence.value] += 1
        
        # Calculate statistics
        total_evidence = sum(confidence_counts.values())
        confidence_stats = {}
        
        if total_evidence > 0:
            for level, count in confidence_counts.items():
                confidence_stats[level] = {
                    'count': count,
                    'percentage': (count / total_evidence) * 100
                }
        
        return {
            'distribution': confidence_stats,
            'total_evidence': total_evidence
        }
    
    def create_evidence_network(self, max_nodes: int = 100) -> Dict[str, Any]:
        """Create a network visualization of evidence relationships."""
        # Get evidence chains to build network
        chains = self.evidence_collector.chains
        
        nodes = []
        edges = []
        node_ids = set()
        
        # Add evidence nodes
        evidence_list = list(self.evidence_collector.evidence.values())[:max_nodes]
        
        for evidence in evidence_list:
            if evidence.evidence_id not in node_ids:
                nodes.append({
                    'id': evidence.evidence_id,
                    'type': evidence.type.value,
                    'source': evidence.source,
                    'confidence': evidence.confidence.value,
                    'size': len(str(evidence.content)),
                    'label': f"{evidence.type.value}\\n{evidence.source}"
                })
                node_ids.add(evidence.evidence_id)
        
        # Add chain relationships as edges
        for chain in chains.values():
            for i in range(len(chain.steps) - 1):
                source_id = chain.steps[i].evidence_id
                target_id = chain.steps[i + 1].evidence_id
                
                if source_id in node_ids and target_id in node_ids:
                    edges.append({
                        'source': source_id,
                        'target': target_id,
                        'type': 'derivation',
                        'label': 'derives from'
                    })
        
        return {
            'nodes': nodes,
            'edges': edges,
            'statistics': {
                'total_nodes': len(nodes),
                'total_edges': len(edges),
                'node_types': list(set(node['type'] for node in nodes))
            }
        }
    
    def create_source_reliability_report(self) -> Dict[str, Any]:
        """Create a report on source reliability and contribution."""
        source_stats = defaultdict(lambda: {
            'total_evidence': 0,
            'confidence_distribution': defaultdict(int),
            'evidence_types': defaultdict(int)
        })
        
        # Collect statistics by source
        for evidence in self.evidence_collector.evidence.values():
            stats = source_stats[evidence.source]
            stats['total_evidence'] += 1
            stats['confidence_distribution'][evidence.confidence.value] += 1
            stats['evidence_types'][evidence.type.value] += 1
        
        # Calculate reliability scores
        source_reliability = {}
        for source, stats in source_stats.items():
            # Simple reliability score based on confidence distribution
            high_conf = stats['confidence_distribution']['high']
            medium_conf = stats['confidence_distribution']['medium']
            low_conf = stats['confidence_distribution']['low']
            unknown_conf = stats['confidence_distribution']['unknown']
            
            total = stats['total_evidence']
            if total > 0:
                reliability_score = (high_conf * 1.0 + medium_conf * 0.7 + 
                                   low_conf * 0.4 + unknown_conf * 0.5) / total
            else:
                reliability_score = 0.5
            
            source_reliability[source] = {
                'reliability_score': reliability_score,
                'total_contributions': total,
                'confidence_breakdown': dict(stats['confidence_distribution']),
                'evidence_types': dict(stats['evidence_types'])
            }
        
        # Sort by reliability
        sorted_sources = sorted(
            source_reliability.items(), 
            key=lambda x: x[1]['reliability_score'], 
            reverse=True
        )
        
        return {
            'source_rankings': sorted_sources,
            'total_sources': len(source_reliability),
            'reliability_statistics': {
                'average_reliability': np.mean([s['reliability_score'] for s in source_reliability.values()]),
                'highest_reliability': max([s['reliability_score'] for s in source_reliability.values()]) if source_reliability else 0,
                'lowest_reliability': min([s['reliability_score'] for s in source_reliability.values()]) if source_reliability else 0
            }
        }
    
    def _summarize_evidence_content(self, content: Dict[str, Any]) -> str:
        """Create a brief summary of evidence content."""
        if not content:
            return "Empty content"
        
        # Extract key information
        summary_parts = []
        
        # Look for common result fields
        result_fields = ['result', 'value', 'score', 'p_value', 'effect_size']
        for field in result_fields:
            if field in content:
                value = content[field]
                summary_parts.append(f"{field}: {value}")
                break
        
        # Add first non-result field if summary is still empty
        if not summary_parts:
            for key, value in list(content.items())[:2]:  # First 2 items
                if isinstance(value, (str, int, float)):
                    summary_parts.append(f"{key}: {str(value)[:50]}")
        
        return "; ".join(summary_parts) if summary_parts else "Complex content"
    
    def export_comprehensive_report(
        self, 
        output_path: Optional[Path] = None,
        include_visualizations: bool = True
    ) -> Path:
        """Export a comprehensive evidence report with visualizations."""
        report_data = {
            'metadata': {
                'generated_at': time.time(),
                'evidence_collector_id': getattr(self.evidence_collector, 'run_id', 'unknown'),
                'total_evidence': len(self.evidence_collector.evidence)
            },
            'summary': self.evidence_collector.generate_report(),
            'confidence_distribution': self.create_confidence_distribution(),
            'source_reliability': self.create_source_reliability_report(),
            'timeline': self.create_evidence_timeline()
        }
        
        if include_visualizations:
            report_data['network'] = self.create_evidence_network()
        
        # Determine output path
        if output_path is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = Path(f"evidence_report_{timestamp}.json")
        
        # Write report
        with open(output_path, 'w') as f:
            json.dump(report_data, f, indent=2, default=str)
        
        logger.info(f"Comprehensive evidence report exported to {output_path}")
        return output_path


class EnhancedEvidenceCollector(EvidenceCollector):
    """Enhanced evidence collector with aggregation and advanced features."""
    
    def __init__(self, *args, **kwargs):
        """Initialize enhanced evidence collector."""
        super().__init__(*args, **kwargs)
        
        # Add enhanced components
        self.aggregator = EvidenceAggregator()
        self.provenance_tracker = ProvenanceTracker()
        self.visualization_api = EvidenceVisualizationAPI(self)
        
        # Track aggregations
        self.aggregations: Dict[str, EvidenceAggregation] = {}
        
        logger.info("Enhanced evidence collector initialized")
    
    def aggregate_related_evidence(
        self,
        evidence_type: Optional[EvidenceType] = None,
        source: Optional[str] = None,
        method: str = 'consensus'
    ) -> Optional[EvidenceAggregation]:
        """
        Aggregate related evidence using specified method.
        
        Args:
            evidence_type: Type of evidence to aggregate (None for all)
            source: Source to aggregate (None for all sources)
            method: Aggregation method
            
        Returns:
            Aggregation result or None if no evidence to aggregate
        """
        # Filter evidence
        evidence_list = []
        for evidence in self.evidence.values():
            if evidence_type and evidence.type != evidence_type:
                continue
            if source and evidence.source != source:
                continue
            evidence_list.append(evidence)
        
        if len(evidence_list) < 2:
            return None
        
        # Perform aggregation
        aggregation = self.aggregator.aggregate_evidence(evidence_list, method)
        self.aggregations[aggregation.aggregation_id] = aggregation
        
        # Track in provenance
        agg_node_id = self.provenance_tracker.add_node(
            node_type='aggregation',
            content=aggregation.aggregated_content,
            confidence=aggregation.confidence_score
        )
        
        # Add edges from source evidence
        for evidence_id in aggregation.evidence_ids:
            if evidence_id in self.evidence:
                evidence_node_id = self.provenance_tracker.add_node(
                    node_type='evidence',
                    content=self.evidence[evidence_id].to_dict()
                )
                self.provenance_tracker.add_edge(
                    evidence_node_id, 
                    agg_node_id, 
                    'usedBy',
                    {'aggregation_method': method}
                )
        
        logger.info(f"Aggregated {len(evidence_list)} pieces of evidence using {method}")
        return aggregation
    
    def get_evidence_quality_score(self) -> Dict[str, Any]:
        """Calculate overall evidence quality metrics."""
        if not self.evidence:
            return {"quality_score": 0, "details": "No evidence collected"}
        
        # Calculate various quality metrics
        total_evidence = len(self.evidence)
        
        # Confidence distribution
        confidence_scores = []
        for evidence in self.evidence.values():
            score = {
                ConfidenceLevel.HIGH: 0.9,
                ConfidenceLevel.MEDIUM: 0.7,
                ConfidenceLevel.LOW: 0.4,
                ConfidenceLevel.UNKNOWN: 0.5
            }.get(evidence.confidence, 0.5)
            confidence_scores.append(score)
        
        avg_confidence = np.mean(confidence_scores)
        
        # Diversity of sources
        unique_sources = len(set(e.source for e in self.evidence.values()))
        source_diversity = min(1.0, unique_sources / max(1, total_evidence * 0.3))
        
        # Diversity of evidence types
        unique_types = len(set(e.type for e in self.evidence.values()))
        type_diversity = min(1.0, unique_types / len(EvidenceType))
        
        # Aggregation consensus (if any aggregations exist)
        consensus_score = 1.0
        if self.aggregations:
            consensus_scores = [agg.consensus_level for agg in self.aggregations.values()]
            consensus_score = np.mean(consensus_scores)
        
        # Overall quality score (weighted combination)
        quality_score = (
            0.4 * avg_confidence +
            0.2 * source_diversity +
            0.2 * type_diversity +
            0.2 * consensus_score
        )
        
        return {
            "quality_score": quality_score,
            "details": {
                "total_evidence": total_evidence,
                "average_confidence": avg_confidence,
                "source_diversity": source_diversity,
                "type_diversity": type_diversity,
                "consensus_score": consensus_score,
                "unique_sources": unique_sources,
                "unique_types": unique_types,
                "total_aggregations": len(self.aggregations)
            }
        }