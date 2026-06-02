"""
Natural Language Query Interface for BR-KG

Provides natural language to graph query translation using a 4-subagent system.
"""

from .agents import (
    ExecutableQuery,
    FormattedResult,
    MappedQuery,
    ParsedQuery,
    QueryBuilderAgent,
    QueryParserAgent,
    ResultFormatterAgent,
    SchemaMapperAgent,
)
from .nl_query_orchestrator import (
    NaturalLanguageQueryOrchestrator,
    QueryExecutionContext,
    QueryExecutionPhase,
    QueryTypeNotSupportedError,
    create_nl_query_orchestrator,
)

__all__ = [
    # Orchestrator
    "NaturalLanguageQueryOrchestrator",
    "QueryExecutionContext",
    "QueryExecutionPhase",
    "QueryTypeNotSupportedError",
    "create_nl_query_orchestrator",
    # Agents
    "QueryParserAgent",
    "SchemaMapperAgent",
    "QueryBuilderAgent",
    "ResultFormatterAgent",
    # Data Classes
    "ParsedQuery",
    "MappedQuery",
    "ExecutableQuery",
    "FormattedResult",
]
