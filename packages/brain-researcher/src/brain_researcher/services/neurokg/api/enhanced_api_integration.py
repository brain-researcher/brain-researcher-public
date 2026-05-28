"""Enhanced BR-KG API integration module.

This module integrates all the enhanced BR-KG components into a unified API:
- Enhanced GraphQL with complexity limiting and persisted queries
- Advanced vector search with FAISS optimization
- Hybrid search combining text, vector, and graph traversal
- Multi-hop graph traversal queries
- Temporal query support for time-based analysis
- Aggregation pipelines for analytics
- Enhanced SPARQL federation
"""

import json
import logging
import time
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

from flask import Blueprint, request, jsonify, Response

# Import enhanced components
from .graphql_enhanced import EnhancedGraphQLAPI
from ..search.advanced_vector_search import AdvancedVectorSearchEngine, IndexType
from ..search.hybrid_search_engine import HybridSearchEngine, SearchMode
from ..traversal.multi_hop_queries import MultiHopQueryEngine, TraversalMode, TraversalConstraints
from ..temporal.temporal_queries import TemporalQueryEngine, TemporalWindow, TemporalGranularity
from ..analytics.aggregation_pipelines import AggregationPipeline, PipelineStage, AggregationSpec, GroupBySpec
from ..sparql.enhanced_federation import FederatedSPARQLEngine, QueryDistributionStrategy, ResultMergeStrategy

logger = logging.getLogger(__name__)


class EnhancedNeuroKGAPI:
    """Unified enhanced BR-KG API that integrates all advanced components."""
    
    def __init__(self, neo4j_db, enable_gpu: bool = False):
        """Initialize enhanced BR-KG API.
        
        Args:
            neo4j_db: Neo4j database connection
            enable_gpu: Enable GPU acceleration for vector operations
        """
        self.neo4j_db = neo4j_db
        
        # Initialize core components
        logger.info("Initializing enhanced BR-KG components...")
        
        # Enhanced GraphQL API
        self.graphql_api = EnhancedGraphQLAPI(
            db_connection=neo4j_db,
            cache_ttl=3600,
            max_complexity=1000
        )
        
        # Advanced Vector Search Engine
        self.vector_engine = AdvancedVectorSearchEngine(
            dimension=768,
            index_type=IndexType.GPU_IVF if enable_gpu else IndexType.IVF_FLAT,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            cache_ttl=3600,
            gpu_enabled=enable_gpu
        )
        
        # Hybrid Search Engine
        self.hybrid_search = HybridSearchEngine(
            vector_engine=self.vector_engine,
            neo4j_db=neo4j_db,
            enable_graph_traversal=True
        )
        
        # Multi-hop Query Engine
        self.multi_hop_engine = MultiHopQueryEngine(
            neo4j_db=neo4j_db,
            max_concurrent_queries=5
        )
        
        # Temporal Query Engine
        self.temporal_engine = TemporalQueryEngine(
            neo4j_db=neo4j_db,
            enable_versioning=True
        )
        
        # Aggregation Pipeline
        self.aggregation_pipeline = AggregationPipeline(
            neo4j_db=neo4j_db,
            enable_caching=True,
            max_workers=4
        )
        
        # Federated SPARQL Engine
        self.federated_sparql = FederatedSPARQLEngine()
        
        # Performance tracking
        self.api_stats = {
            'requests_processed': 0,
            'avg_response_time_ms': 0.0,
            'component_usage': {
                'graphql': 0,
                'vector_search': 0,
                'hybrid_search': 0,
                'multi_hop': 0,
                'temporal': 0,
                'aggregation': 0,
                'sparql_federation': 0
            },
            'error_count': 0
        }
        
        logger.info("Enhanced BR-KG API initialized successfully")
    
    def create_blueprint(self) -> Blueprint:
        """Create Flask blueprint for enhanced API endpoints."""
        bp = Blueprint('enhanced_neurokg_api', __name__, url_prefix='/api/enhanced')
        
        # GraphQL endpoints
        @bp.route('/graphql', methods=['POST', 'GET'])
        def graphql_endpoint():
            return self._handle_graphql_request()
        
        @bp.route('/graphql/persisted', methods=['POST'])
        def store_persisted_query():
            return self._handle_store_persisted_query()
        
        @bp.route('/graphql/persisted/<query_id>', methods=['POST'])
        def execute_persisted_query(query_id):
            return self._handle_execute_persisted_query(query_id)
        
        @bp.route('/graphql/stats', methods=['GET'])
        def graphql_stats():
            return jsonify(self.graphql_api.get_enhanced_performance_stats())
        
        # Vector search endpoints
        @bp.route('/search/vector', methods=['POST'])
        def vector_search():
            return self._handle_vector_search()
        
        @bp.route('/search/hybrid', methods=['POST'])
        def hybrid_search():
            return self._handle_hybrid_search()
        
        @bp.route('/search/similarity/<doc_id>', methods=['GET'])
        def find_similar():
            return self._handle_find_similar(doc_id)
        
        @bp.route('/search/coordinate', methods=['POST'])
        def coordinate_search():
            return self._handle_coordinate_search()
        
        # Multi-hop traversal endpoints
        @bp.route('/traversal/multi-hop', methods=['POST'])
        def multi_hop_traversal():
            return self._handle_multi_hop_traversal()
        
        @bp.route('/traversal/connections', methods=['POST'])
        def find_connections():
            return self._handle_find_connections()
        
        @bp.route('/traversal/subgraphs', methods=['POST'])
        def discover_subgraphs():
            return self._handle_discover_subgraphs()
        
        # Temporal query endpoints
        @bp.route('/temporal/snapshot', methods=['POST'])
        def temporal_snapshot():
            return self._handle_temporal_snapshot()
        
        @bp.route('/temporal/evolution', methods=['POST'])
        def temporal_evolution():
            return self._handle_temporal_evolution()
        
        @bp.route('/temporal/communities', methods=['POST'])
        def temporal_communities():
            return self._handle_temporal_communities()
        
        @bp.route('/temporal/paths', methods=['POST'])
        def temporal_paths():
            return self._handle_temporal_paths()
        
        # Aggregation pipeline endpoints
        @bp.route('/analytics/aggregate', methods=['POST'])
        def aggregate_data():
            return self._handle_aggregate_data()
        
        @bp.route('/analytics/graph-metrics', methods=['POST'])
        def graph_analytics():
            return self._handle_graph_analytics()
        
        @bp.route('/analytics/correlations', methods=['POST'])
        def correlation_analysis():
            return self._handle_correlation_analysis()
        
        @bp.route('/analytics/pipeline', methods=['POST'])
        def execute_pipeline():
            return self._handle_execute_pipeline()
        
        # SPARQL federation endpoints
        @bp.route('/sparql/federated', methods=['POST'])
        def federated_sparql():
            return self._handle_federated_sparql()
        
        @bp.route('/sparql/endpoints', methods=['GET'])
        def list_endpoints():
            return self._handle_list_endpoints()
        
        @bp.route('/sparql/endpoints/<endpoint_name>/stats', methods=['GET'])
        def endpoint_stats(endpoint_name):
            return self._handle_endpoint_stats(endpoint_name)
        
        # Data ingestion endpoints
        @bp.route('/data/index', methods=['POST'])
        def index_documents():
            return self._handle_index_documents()
        
        @bp.route('/data/update/<doc_id>', methods=['PUT'])
        def update_document(doc_id):
            return self._handle_update_document(doc_id)
        
        @bp.route('/data/delete', methods=['DELETE'])
        def delete_documents():
            return self._handle_delete_documents()
        
        # System status endpoints
        @bp.route('/status', methods=['GET'])
        def system_status():
            return self._handle_system_status()
        
        @bp.route('/stats', methods=['GET'])
        def comprehensive_stats():
            return self._handle_comprehensive_stats()
        
        @bp.route('/health', methods=['GET'])
        def health_check():
            return self._handle_health_check()
        
        return bp
    
    def _handle_graphql_request(self):
        """Handle GraphQL requests with enhanced features."""
        start_time = time.time()
        self.api_stats['component_usage']['graphql'] += 1
        
        try:
            if request.method == 'GET':
                query = request.args.get('query')
                variables = json.loads(request.args.get('variables', '{}'))
                persisted_query_id = request.args.get('persisted_query_id')
            else:
                data = request.get_json()
                query = data.get('query')
                variables = data.get('variables', {})
                persisted_query_id = data.get('persisted_query_id')
            
            # Extract client ID for budgeting
            client_id = request.headers.get('X-Client-ID', 'anonymous')
            
            # Execute enhanced GraphQL query
            result = self.graphql_api.execute_query(
                query=query,
                variables=variables,
                persisted_query_id=persisted_query_id,
                client_id=client_id
            )
            
            response_time = (time.time() - start_time) * 1000
            self._update_api_stats(response_time, success=True)
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"GraphQL request failed: {e}")
            self.api_stats['error_count'] += 1
            return jsonify({'errors': [{'message': str(e)}]}), 500
    
    def _handle_store_persisted_query(self):
        """Handle storing persisted queries."""
        try:
            data = request.get_json()
            query_id = data.get('id')
            query = data.get('query')
            variables_schema = data.get('variables_schema')
            ttl = data.get('ttl')
            
            success = self.graphql_api.store_persisted_query(
                query_id, query, variables_schema, ttl
            )
            
            if success:
                return jsonify({'status': 'stored', 'id': query_id})
            else:
                return jsonify({'error': 'Failed to store query'}), 400
                
        except Exception as e:
            logger.error(f"Store persisted query failed: {e}")
            return jsonify({'error': str(e)}), 500
    
    def _handle_execute_persisted_query(self, query_id):
        """Handle executing persisted queries."""
        try:
            data = request.get_json()
            variables = data.get('variables', {})
            client_id = request.headers.get('X-Client-ID', 'anonymous')
            
            result = self.graphql_api.execute_query(
                persisted_query_id=query_id,
                variables=variables,
                client_id=client_id
            )
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Execute persisted query failed: {e}")
            return jsonify({'error': str(e)}), 500
    
    def _handle_vector_search(self):
        """Handle vector search requests."""
        start_time = time.time()
        self.api_stats['component_usage']['vector_search'] += 1
        
        try:
            data = request.get_json()
            query = data.get('query', '')
            k = data.get('k', 10)
            doc_types = data.get('doc_types')
            filters = data.get('filters')
            use_cache = data.get('use_cache', True)
            
            results = self.vector_engine.search(
                query=query,
                k=k,
                doc_types=doc_types,
                filters=filters,
                use_cache=use_cache
            )
            
            response_time = (time.time() - start_time) * 1000
            self._update_api_stats(response_time, success=True)
            
            return jsonify({
                'results': [result.to_dict() for result in results],
                'total_count': len(results),
                'response_time_ms': response_time
            })
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            self.api_stats['error_count'] += 1
            return jsonify({'error': str(e)}), 500
    
    def _handle_hybrid_search(self):
        """Handle hybrid search requests."""
        start_time = time.time()
        self.api_stats['component_usage']['hybrid_search'] += 1
        
        try:
            data = request.get_json()
            query = data.get('query', '')
            k = data.get('k', 10)
            search_mode = SearchMode(data.get('search_mode', 'auto'))
            filters = data.get('filters')
            explain = data.get('explain', False)
            
            results = self.hybrid_search.search(
                query=query,
                k=k,
                search_mode=search_mode,
                filters=filters,
                explain=explain
            )
            
            response_time = (time.time() - start_time) * 1000
            self._update_api_stats(response_time, success=True)
            
            return jsonify({
                'results': [result.result.to_dict() for result in results],
                'scoring_details': [{
                    'id': result.result.id,
                    'text_score': result.text_score,
                    'vector_score': result.vector_score,
                    'graph_score': result.graph_score,
                    'combined_score': result.combined_score,
                    'explanation': result.score_explanation
                } for result in results] if explain else None,
                'search_mode': search_mode.value,
                'response_time_ms': response_time
            })
            
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            self.api_stats['error_count'] += 1
            return jsonify({'error': str(e)}), 500
    
    def _handle_multi_hop_traversal(self):
        """Handle multi-hop graph traversal requests."""
        start_time = time.time()
        self.api_stats['component_usage']['multi_hop'] += 1
        
        try:
            data = request.get_json()
            start_node_id = data.get('start_node_id')
            constraints_data = data.get('constraints', {})
            mode = TraversalMode(data.get('mode', 'breadth_first'))
            target_node_id = data.get('target_node_id')
            
            # Build constraints
            constraints = TraversalConstraints(
                max_depth=constraints_data.get('max_depth', 5),
                max_results=constraints_data.get('max_results', 100),
                min_edge_weight=constraints_data.get('min_edge_weight'),
                allowed_edge_types=set(constraints_data.get('allowed_edge_types', [])) if constraints_data.get('allowed_edge_types') else None
            )
            
            result = self.multi_hop_engine.traverse_from_node(
                start_node_id=start_node_id,
                constraints=constraints,
                mode=mode,
                target_node_id=target_node_id
            )
            
            response_time = (time.time() - start_time) * 1000
            self._update_api_stats(response_time, success=True)
            
            return jsonify({
                'query_id': result.query_id,
                'paths': [path.to_dict() for path in result.paths],
                'total_paths': result.total_paths_found,
                'execution_time_ms': result.execution_time_ms,
                'statistics': result.statistics
            })
            
        except Exception as e:
            logger.error(f"Multi-hop traversal failed: {e}")
            self.api_stats['error_count'] += 1
            return jsonify({'error': str(e)}), 500
    
    def _handle_temporal_evolution(self):
        """Handle temporal evolution analysis requests."""
        start_time = time.time()
        self.api_stats['component_usage']['temporal'] += 1
        
        try:
            data = request.get_json()
            entity_ids = data.get('entity_ids', [])
            start_time_str = data.get('start_time')
            end_time_str = data.get('end_time')
            granularity = TemporalGranularity(data.get('granularity', 'day'))
            metrics = data.get('metrics')
            
            # Parse timestamps
            start_time_dt = datetime.fromisoformat(start_time_str)
            end_time_dt = datetime.fromisoformat(end_time_str)
            
            result = self.temporal_engine.analyze_temporal_evolution(
                entity_ids=entity_ids,
                start_time=start_time_dt,
                end_time=end_time_dt,
                granularity=granularity,
                metrics=metrics
            )
            
            response_time = (time.time() - start_time) * 1000
            self._update_api_stats(response_time, success=True)
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Temporal evolution analysis failed: {e}")
            self.api_stats['error_count'] += 1
            return jsonify({'error': str(e)}), 500
    
    def _handle_aggregate_data(self):
        """Handle data aggregation requests."""
        start_time = time.time()
        self.api_stats['component_usage']['aggregation'] += 1
        
        try:
            data = request.get_json()
            node_type = data.get('node_type')
            aggregations_data = data.get('aggregations', [])
            group_by_data = data.get('group_by')
            filters = data.get('filters')
            
            # Build aggregation specs
            aggregations = []
            for agg_data in aggregations_data:
                agg_spec = AggregationSpec(
                    function=agg_data['function'],
                    field=agg_data['field'],
                    alias=agg_data.get('alias')
                )
                aggregations.append(agg_spec)
            
            # Build group by spec
            group_by = None
            if group_by_data:
                group_by = GroupBySpec(
                    fields=group_by_data['fields'],
                    operation=group_by_data.get('operation', 'simple')
                )
            
            result = self.aggregation_pipeline.aggregate_node_properties(
                node_type=node_type,
                aggregations=aggregations,
                group_by=group_by,
                filters=filters
            )
            
            response_time = (time.time() - start_time) * 1000
            self._update_api_stats(response_time, success=True)
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Data aggregation failed: {e}")
            self.api_stats['error_count'] += 1
            return jsonify({'error': str(e)}), 500
    
    def _handle_federated_sparql(self):
        """Handle federated SPARQL requests."""
        start_time = time.time()
        self.api_stats['component_usage']['sparql_federation'] += 1
        
        try:
            data = request.get_json()
            query = data.get('query', '')
            distribution_strategy = QueryDistributionStrategy(
                data.get('distribution_strategy', 'parallel')
            )
            merge_strategy = ResultMergeStrategy(
                data.get('merge_strategy', 'union')
            )
            max_results = data.get('max_results')
            timeout_seconds = data.get('timeout_seconds', 60)
            
            result = self.federated_sparql.execute_federated_query(
                query=query,
                distribution_strategy=distribution_strategy,
                merge_strategy=merge_strategy,
                max_results=max_results,
                timeout_seconds=timeout_seconds
            )
            
            response_time = (time.time() - start_time) * 1000
            self._update_api_stats(response_time, success=True)
            
            return jsonify({
                'query_id': result.query_id,
                'merged_results': result.merged_results,
                'successful_endpoints': result.successful_endpoints,
                'total_endpoints': result.total_endpoints,
                'execution_time_ms': result.total_execution_time_ms,
                'endpoint_results': [{
                    'endpoint_name': er.endpoint_name,
                    'success': er.success,
                    'result_count': er.result_count,
                    'execution_time_ms': er.execution_time_ms,
                    'cached': er.cached,
                    'error_message': er.error_message
                } for er in result.endpoint_results],
                'metadata': result.metadata
            })
            
        except Exception as e:
            logger.error(f"Federated SPARQL failed: {e}")
            self.api_stats['error_count'] += 1
            return jsonify({'error': str(e)}), 500
    
    def _handle_index_documents(self):
        """Handle document indexing for vector search."""
        try:
            data = request.get_json()
            documents = data.get('documents', [])
            
            count = self.vector_engine.add_documents(documents)
            
            return jsonify({
                'status': 'success',
                'documents_indexed': count,
                'total_documents': self.vector_engine.stats['total_documents']
            })
            
        except Exception as e:
            logger.error(f"Document indexing failed: {e}")
            return jsonify({'error': str(e)}), 500
    
    def _handle_system_status(self):
        """Handle system status requests."""
        try:
            status = {
                'api_status': 'healthy',
                'components': {
                    'graphql_api': 'active',
                    'vector_engine': 'active',
                    'hybrid_search': 'active',
                    'multi_hop_engine': 'active',
                    'temporal_engine': 'active',
                    'aggregation_pipeline': 'active',
                    'federated_sparql': 'active'
                },
                'performance': {
                    'requests_processed': self.api_stats['requests_processed'],
                    'avg_response_time_ms': self.api_stats['avg_response_time_ms'],
                    'error_rate': self.api_stats['error_count'] / max(1, self.api_stats['requests_processed'])
                },
                'timestamp': datetime.utcnow().isoformat()
            }
            
            return jsonify(status)
            
        except Exception as e:
            logger.error(f"System status failed: {e}")
            return jsonify({'error': str(e)}), 500
    
    def _handle_comprehensive_stats(self):
        """Handle comprehensive statistics requests."""
        try:
            stats = {
                'api_stats': self.api_stats,
                'graphql_stats': self.graphql_api.get_enhanced_performance_stats(),
                'vector_search_stats': self.vector_engine.get_statistics(),
                'hybrid_search_stats': self.hybrid_search.get_search_statistics(),
                'multi_hop_stats': self.multi_hop_engine.get_query_statistics(),
                'temporal_stats': self.temporal_engine.get_temporal_statistics(),
                'aggregation_stats': self.aggregation_pipeline.get_pipeline_statistics(),
                'federation_stats': self.federated_sparql.get_federation_statistics()
            }
            
            return jsonify(stats)
            
        except Exception as e:
            logger.error(f"Comprehensive stats failed: {e}")
            return jsonify({'error': str(e)}), 500
    
    def _handle_health_check(self):
        """Handle health check requests."""
        try:
            # Quick health checks for each component
            health_status = {
                'status': 'healthy',
                'timestamp': datetime.utcnow().isoformat(),
                'components': {
                    'database': 'healthy',  # Would check neo4j connection
                    'graphql': 'healthy',
                    'vector_search': 'healthy',
                    'hybrid_search': 'healthy',
                    'multi_hop': 'healthy',
                    'temporal': 'healthy',
                    'aggregation': 'healthy',
                    'sparql_federation': 'healthy'
                }
            }
            
            return jsonify(health_status)
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({'status': 'unhealthy', 'error': str(e)}), 500
    
    def _update_api_stats(self, response_time_ms: float, success: bool = True):
        """Update API performance statistics."""
        self.api_stats['requests_processed'] += 1
        
        if not success:
            self.api_stats['error_count'] += 1
        
        # Update rolling average
        current_avg = self.api_stats['avg_response_time_ms']
        total_requests = self.api_stats['requests_processed']
        
        self.api_stats['avg_response_time_ms'] = (
            (current_avg * (total_requests - 1) + response_time_ms) / total_requests
        )
    
    # Placeholder implementations for remaining handlers
    def _handle_find_similar(self, doc_id): pass
    def _handle_coordinate_search(self): pass
    def _handle_find_connections(self): pass
    def _handle_discover_subgraphs(self): pass
    def _handle_temporal_snapshot(self): pass
    def _handle_temporal_communities(self): pass
    def _handle_temporal_paths(self): pass
    def _handle_graph_analytics(self): pass
    def _handle_correlation_analysis(self): pass
    def _handle_execute_pipeline(self): pass
    def _handle_list_endpoints(self): pass
    def _handle_endpoint_stats(self, endpoint_name): pass
    def _handle_update_document(self, doc_id): pass
    def _handle_delete_documents(self): pass