"""
Natural Language Query Orchestrator for BR-KG

Coordinates 4 specialized subagents to translate natural language queries
into executable graph queries and format results.
"""

import logging
import time
import json
import os
from typing import Callable, Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from .agents.parser_agent import QueryParserAgent, ParsedQuery
from .agents.schema_mapper_agent import SchemaMapperAgent, MappedQuery
from .agents.query_builder_agent import QueryBuilderAgent, ExecutableQuery
from .agents.result_formatter_agent import ResultFormatterAgent, FormattedResult

logger = logging.getLogger(__name__)


class QueryExecutionPhase(str, Enum):
    """Phases of query execution"""
    PARSING = "parsing"
    MAPPING = "mapping"
    BUILDING = "building"
    EXECUTING = "executing"
    FORMATTING = "formatting"
    COMPLETE = "complete"
    ERROR = "error"


class QueryTypeNotSupportedError(ValueError):
    """Raised when a requested query type is not supported by the orchestrator."""

    def __init__(
        self,
        *,
        query_type: str,
        supported_query_types: List[str],
        message: Optional[str] = None,
    ):
        self.query_type = query_type
        self.supported_query_types = supported_query_types
        self.error_code = "not_supported"
        self.detail = (
            message
            or f"query_type={query_type} is not supported by this orchestrator"
        )
        super().__init__(self.detail)


@dataclass
class QueryExecutionContext:
    """Context passed between agents during query execution"""

    query_id: str
    original_query: str
    user_context: Dict[str, Any]
    current_phase: QueryExecutionPhase
    parsed_query: Optional[ParsedQuery] = None
    mapped_query: Optional[MappedQuery] = None
    executable_query: Optional[ExecutableQuery] = None
    raw_results: Optional[Dict[str, Any]] = None
    formatted_result: Optional[FormattedResult] = None
    errors: List[str] = field(default_factory=list)
    execution_time: Dict[str, float] = field(default_factory=dict)
    confidence_scores: Dict[str, float] = field(default_factory=dict)


class NaturalLanguageQueryOrchestrator:
    """
    Main orchestrator for natural language query processing.

    Coordinates 4 specialized agents:
    1. Parser Agent - Extracts intent and entities from natural language
    2. Schema Mapper Agent - Maps entities to graph schema
    3. Query Builder Agent - Constructs executable queries
    4. Result Formatter Agent - Formats results for user consumption
    """

    def __init__(
        self,
        neo4j_db=None,
        parser_agent: Optional[QueryParserAgent] = None,
        mapper_agent: Optional[SchemaMapperAgent] = None,
        builder_agent: Optional[QueryBuilderAgent] = None,
        formatter_agent: Optional[ResultFormatterAgent] = None,
        sparql_executor: Optional[Callable[[str], Dict[str, Any]]] = None,
        enable_caching: bool = True,
        max_retries: int = 3
    ):
        """
        Initialize the NL query orchestrator

        Args:
            neo4j_db: Database connection for query execution
            parser_agent: Query parser agent instance
            mapper_agent: Schema mapper agent instance
            builder_agent: Query builder agent instance
            formatter_agent: Result formatter agent instance
            sparql_executor: Optional production SPARQL executor callable
                (signature: ``(sparql_query: str) -> Dict[str, Any]``). If not
                provided, ``query_type=sparql`` returns an explicit
                ``not_supported`` error response.
            enable_caching: Whether to cache query results
            max_retries: Maximum retry attempts for failed queries
        """
        self.neo4j_db = neo4j_db

        # Initialize agents
        self.parser_agent = parser_agent or QueryParserAgent()
        self.mapper_agent = mapper_agent or SchemaMapperAgent()
        self.builder_agent = builder_agent or QueryBuilderAgent()
        self.formatter_agent = formatter_agent or ResultFormatterAgent()
        self.sparql_executor = sparql_executor

        self.enable_caching = enable_caching
        self.max_retries = max_retries

        # Query cache
        self._query_cache = {}
        self._cache_ttl = 3600  # 1 hour

        # Performance metrics
        self.metrics = {
            'queries_processed': 0,
            'successful_queries': 0,
            'failed_queries': 0,
            'cache_hits': 0,
            'average_execution_time': 0.0
        }

    def process_query(
        self,
        natural_language_query: str,
        user_context: Optional[Dict[str, Any]] = None,
        return_intermediate: bool = False
    ) -> Dict[str, Any]:
        """
        Process a natural language query through all agents

        Args:
            natural_language_query: The user's natural language query
            user_context: Additional context (user preferences, history, etc.)
            return_intermediate: Whether to return intermediate results

        Returns:
            Query results with optional intermediate processing details
        """
        start_time = time.time()
        query_id = f"nlq_{int(time.time() * 1000)}"

        # Check cache
        if self.enable_caching:
            cache_key = self._get_cache_key(natural_language_query, user_context)
            if cache_key in self._query_cache:
                cache_entry = self._query_cache[cache_key]
                if time.time() - cache_entry['timestamp'] < self._cache_ttl:
                    self.metrics['cache_hits'] += 1
                    logger.info(f"Cache hit for query: {natural_language_query[:50]}...")
                    return cache_entry['result']

        # Initialize execution context
        context = QueryExecutionContext(
            query_id=query_id,
            original_query=natural_language_query,
            user_context=user_context or {},
            current_phase=QueryExecutionPhase.PARSING
        )

        try:
            # Phase 1: Parse the natural language query
            context = self._execute_parsing(context)

            # Phase 2: Map to graph schema
            context = self._execute_mapping(context)

            # Phase 3: Build executable query
            context = self._execute_building(context)

            # Phase 4: Execute the query
            context = self._execute_query(context)

            # Phase 5: Format results
            context = self._execute_formatting(context)

            # Update metrics
            execution_time = time.time() - start_time
            self.metrics['queries_processed'] += 1
            self.metrics['successful_queries'] += 1
            self._update_average_execution_time(execution_time)

            # Build response
            response = self._build_response(context, execution_time, return_intermediate)

            # Cache successful result
            if self.enable_caching and context.formatted_result:
                cache_key = self._get_cache_key(natural_language_query, user_context)
                self._query_cache[cache_key] = {
                    'result': response,
                    'timestamp': time.time()
                }

            return response

        except Exception as e:
            logger.error(f"Query processing failed: {e}")
            context.current_phase = QueryExecutionPhase.ERROR
            context.errors.append(str(e))

            self.metrics['queries_processed'] += 1
            self.metrics['failed_queries'] += 1

            return self._build_error_response(context, str(e), error=e)

    def _execute_parsing(self, context: QueryExecutionContext) -> QueryExecutionContext:
        """Execute the parsing phase"""
        logger.info(f"[{context.query_id}] Phase 1: Parsing query")
        start_time = time.time()

        try:
            context.parsed_query = self.parser_agent.parse(
                context.original_query,
                context.user_context
            )
            context.confidence_scores['parsing'] = context.parsed_query.confidence_score
            logger.debug(f"Parsed intent: {context.parsed_query.intent}")
            logger.debug(f"Extracted entities: {context.parsed_query.entities}")
        except Exception as e:
            logger.error(f"Parsing failed: {e}")
            context.errors.append(f"Parsing error: {e}")
            raise

        context.execution_time['parsing'] = time.time() - start_time
        return context

    def _execute_mapping(self, context: QueryExecutionContext) -> QueryExecutionContext:
        """Execute the schema mapping phase"""
        logger.info(f"[{context.query_id}] Phase 2: Mapping to schema")
        start_time = time.time()
        context.current_phase = QueryExecutionPhase.MAPPING

        if not context.parsed_query:
            raise ValueError("No parsed query available for mapping")

        try:
            context.mapped_query = self.mapper_agent.map_to_schema(
                context.parsed_query,
                context.user_context
            )
            context.confidence_scores['mapping'] = context.mapped_query.confidence_score
            logger.debug(f"Mapped patterns: {len(context.mapped_query.graph_patterns)}")
        except Exception as e:
            logger.error(f"Mapping failed: {e}")
            context.errors.append(f"Mapping error: {e}")
            raise

        context.execution_time['mapping'] = time.time() - start_time
        return context

    def _execute_building(self, context: QueryExecutionContext) -> QueryExecutionContext:
        """Execute the query building phase"""
        logger.info(f"[{context.query_id}] Phase 3: Building query")
        start_time = time.time()
        context.current_phase = QueryExecutionPhase.BUILDING

        if not context.mapped_query:
            raise ValueError("No mapped query available for building")

        try:
            context.executable_query = self.builder_agent.build_query(
                context.mapped_query,
                context.user_context
            )
            context.confidence_scores['building'] = context.executable_query.confidence_score
            logger.debug(f"Built {context.executable_query.query_type} query")
        except Exception as e:
            logger.error(f"Query building failed: {e}")
            context.errors.append(f"Building error: {e}")
            raise

        context.execution_time['building'] = time.time() - start_time
        return context

    def _execute_query(self, context: QueryExecutionContext) -> QueryExecutionContext:
        """Execute the query against the database"""
        logger.info(f"[{context.query_id}] Phase 4: Executing query")
        start_time = time.time()
        context.current_phase = QueryExecutionPhase.EXECUTING

        if not context.executable_query:
            raise ValueError("No executable query available")

        try:
            # Execute based on query type
            if context.executable_query.query_type == 'cypher':
                context.raw_results = self._execute_cypher(
                    context.executable_query.query_string,
                    context.executable_query.parameters
                )
            elif context.executable_query.query_type == 'sparql':
                context.raw_results = self._execute_sparql(
                    context.executable_query.query_string
                )
            else:
                raise ValueError(f"Unsupported query type: {context.executable_query.query_type}")

            logger.debug(f"Query returned {len(context.raw_results.get('results', []))} results")
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            context.errors.append(f"Execution error: {e}")

            if isinstance(e, QueryTypeNotSupportedError):
                # Explicitly surface unsupported query types; do not mask by fallback.
                raise

            # Try fallback query if available
            if context.executable_query.fallback_query:
                logger.info("Trying fallback query")
                try:
                    context.raw_results = self._execute_cypher(
                        context.executable_query.fallback_query,
                        {}
                    )
                except Exception as fallback_error:
                    logger.error(f"Fallback query also failed: {fallback_error}")
                    raise e
            else:
                raise

        context.execution_time['execution'] = time.time() - start_time
        return context

    def _execute_formatting(self, context: QueryExecutionContext) -> QueryExecutionContext:
        """Execute the result formatting phase"""
        logger.info(f"[{context.query_id}] Phase 5: Formatting results")
        start_time = time.time()
        context.current_phase = QueryExecutionPhase.FORMATTING

        if not context.raw_results:
            # No results to format
            context.formatted_result = FormattedResult(
                summary="No results found for your query.",
                data=[],
                visualization_hints={},
                confidence_score=0.5
            )
        else:
            try:
                context.formatted_result = self.formatter_agent.format_results(
                    context.raw_results,
                    context.parsed_query,
                    context.user_context
                )
                context.confidence_scores['formatting'] = context.formatted_result.confidence_score
            except Exception as e:
                logger.error(f"Formatting failed: {e}")
                context.errors.append(f"Formatting error: {e}")
                # Provide raw results as fallback
                context.formatted_result = FormattedResult(
                    summary="Results found but formatting failed.",
                    data=context.raw_results.get('results', []),
                    visualization_hints={},
                    confidence_score=0.3
                )

        context.execution_time['formatting'] = time.time() - start_time
        context.current_phase = QueryExecutionPhase.COMPLETE
        return context

    def _execute_cypher(
        self,
        cypher_query: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a Cypher query against Neo4j"""
        if not self.neo4j_db:
            # Mock response for testing
            return {
                'results': [
                    {'node': {'id': 1, 'label': 'Test', 'properties': {}}}
                ],
                'count': 1
            }

        # Execute query
        results = []
        with self.neo4j_db.session() as session:
            result = session.run(cypher_query, parameters)
            for record in result:
                results.append(dict(record))

        return {'results': results, 'count': len(results)}

    def _execute_sparql(self, sparql_query: str) -> Dict[str, Any]:
        """Execute a SPARQL query via configured backend.

        This orchestrator is Cypher-first by default. SPARQL can be enabled by
        supplying a production executor via ``sparql_executor``.
        """
        if callable(self.sparql_executor):
            return self.sparql_executor(sparql_query)
        raise QueryTypeNotSupportedError(
            query_type="sparql",
            supported_query_types=["cypher"],
            message=(
                "query_type=sparql is not supported in NaturalLanguageQueryOrchestrator "
                "without a configured sparql_executor"
            ),
        )

    def _build_response(
        self,
        context: QueryExecutionContext,
        execution_time: float,
        return_intermediate: bool
    ) -> Dict[str, Any]:
        """Build the final response"""
        response = {
            'query_id': context.query_id,
            'success': True,
            'execution_time': execution_time,
            'result': {
                'summary': context.formatted_result.summary if context.formatted_result else '',
                'data': context.formatted_result.data if context.formatted_result else [],
                'visualization': context.formatted_result.visualization_hints if context.formatted_result else {},
                'explanation': context.formatted_result.explanation if context.formatted_result else ''
            },
            'confidence': {
                'overall': self._calculate_overall_confidence(context),
                'breakdown': context.confidence_scores
            }
        }

        if return_intermediate:
            response['intermediate'] = {
                'parsed_query': context.parsed_query.__dict__ if context.parsed_query else None,
                'mapped_query': {
                    'patterns': context.mapped_query.graph_patterns if context.mapped_query else [],
                    'constraints': context.mapped_query.constraints if context.mapped_query else []
                },
                'executable_query': {
                    'type': context.executable_query.query_type if context.executable_query else None,
                    'query': context.executable_query.query_string if context.executable_query else None
                },
                'execution_times': context.execution_time
            }

        return response

    def _build_error_response(
        self,
        context: QueryExecutionContext,
        error_message: str,
        error: Optional[Exception] = None
    ) -> Dict[str, Any]:
        """Build an error response"""
        response = {
            'query_id': context.query_id,
            'success': False,
            'error': error_message,
            'errors': context.errors,
            'phase_failed': context.current_phase.value,
            'partial_results': {
                'parsed': context.parsed_query is not None,
                'mapped': context.mapped_query is not None,
                'built': context.executable_query is not None,
                'executed': context.raw_results is not None
            }
        }
        if isinstance(error, QueryTypeNotSupportedError):
            response['error_code'] = error.error_code
            response['not_supported'] = {
                'query_type': error.query_type,
                'supported_query_types': error.supported_query_types,
                'message': str(error),
            }
        return response

    def _calculate_overall_confidence(self, context: QueryExecutionContext) -> float:
        """Calculate overall confidence score"""
        if not context.confidence_scores:
            return 0.0

        # Weighted average of phase confidences
        weights = {
            'parsing': 0.2,
            'mapping': 0.3,
            'building': 0.2,
            'formatting': 0.3
        }

        total_score = 0.0
        total_weight = 0.0

        for phase, weight in weights.items():
            if phase in context.confidence_scores:
                total_score += context.confidence_scores[phase] * weight
                total_weight += weight

        return total_score / total_weight if total_weight > 0 else 0.0

    def _get_cache_key(
        self,
        query: str,
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Generate cache key for a query"""
        context_str = json.dumps(context, sort_keys=True) if context else ""
        return f"{query.lower().strip()}:{context_str}"

    def _update_average_execution_time(self, new_time: float):
        """Update running average of execution time"""
        current_avg = self.metrics['average_execution_time']
        count = self.metrics['successful_queries']

        if count == 0:
            self.metrics['average_execution_time'] = new_time
        else:
            self.metrics['average_execution_time'] = (
                (current_avg * (count - 1) + new_time) / count
            )

    def get_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        return self.metrics.copy()

    def clear_cache(self):
        """Clear the query cache"""
        self._query_cache.clear()
        logger.info("Query cache cleared")


def _build_default_sparql_executor(
    neo4j_db: Any,
) -> Optional[Callable[[str], Dict[str, Any]]]:
    """Build a production SPARQL executor for NL query orchestration.

    Returns ``None`` when auto-wiring is unavailable, keeping SPARQL explicitly
    disabled (``not_supported``) instead of using mock behavior.
    """

    try:
        from brain_researcher.services.br_kg.sparql.endpoint import SPARQLEndpoint

        base_uri = os.getenv("BR_KG_BASE_URI", "https://br_kg.org/")
        enable_federation = (
            os.getenv("BR_NLQ_SPARQL_ENABLE_FEDERATION", "1").strip().lower()
            not in {"0", "false", "no"}
        )
        endpoint = SPARQLEndpoint(
            neo4j_db,
            base_uri=base_uri,
            enable_federation=enable_federation,
        )
        return endpoint._execute_sparql_query
    except Exception as exc:  # pragma: no cover - best effort wiring
        logger.warning(
            "Failed to auto-wire SPARQL executor for NL query orchestrator: %s", exc
        )
        return None


def create_nl_query_orchestrator(**kwargs) -> NaturalLanguageQueryOrchestrator:
    """Factory function to create NL query orchestrator.

    When ``neo4j_db`` is supplied and ``sparql_executor`` is not, the factory
    attempts to auto-wire a production SPARQL backend.
    """
    if kwargs.get("sparql_executor") is None and kwargs.get("neo4j_db") is not None:
        maybe_executor = _build_default_sparql_executor(kwargs.get("neo4j_db"))
        if maybe_executor is not None:
            kwargs["sparql_executor"] = maybe_executor

    return NaturalLanguageQueryOrchestrator(**kwargs)
