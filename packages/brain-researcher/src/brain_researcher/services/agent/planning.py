"""
Planning Engine for Brain Researcher Agent (AGENT-002)

This module implements an automated planning system that decomposes natural language
queries into executable workflow steps with dependencies and parameter inference.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.prompt_values import ChatPromptValue
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from brain_researcher.services.agent.dataset_browse_policy import (
    dataset_browse_instruction,
    is_exploratory_dataset_asset_request,
    reorder_tool_ids_for_dataset_browse,
)
from brain_researcher.services.agent.cot_reasoning import ReasoningTrace, get_cot_reasoner
from brain_researcher.services.agent.domain_knowledge import get_domain_knowledge
from brain_researcher.services.agent.kg_resolution import QueryUnderstandingResult
from brain_researcher.services.agent.pipeline_catalog import search_pipelines
from brain_researcher.services.agent.preflight import (
    ensure_query_understanding,
    ensure_tool_candidates,
)
from brain_researcher.services.agent.query_understanding import create_advanced_parser
from brain_researcher.services.agent.tool_metadata_bridge import get_resource_hints
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    """Status of a workflow step."""
    
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ResourceType(str, Enum):
    """Types of computational resources."""
    
    CPU = "cpu"
    GPU = "gpu"
    MEMORY = "memory"
    STORAGE = "storage"
    TIME = "time"


@dataclass
class WorkflowStep:
    """Represents a single step in the workflow plan."""
    
    step_id: str
    step_number: int
    description: str
    tool_name: str
    tool_args: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    expected_output: str = ""
    estimated_time_seconds: float = 0.0
    resource_requirements: Dict[ResourceType, float] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class PlanCheckpoint:
    """Lightweight checkpoint for incremental plan execution."""

    checkpoint_id: str
    step_id: str
    step_number: int
    status: StepStatus
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


@dataclass
class ExecutionPlan:
    """Complete execution plan for a query."""
    
    plan_id: str
    query: str
    objectives: List[str]
    steps: List[WorkflowStep]
    success_criteria: List[str]
    total_estimated_time: float
    total_resource_requirements: Dict[ResourceType, float]
    confidence_score: float = 0.0
    created_at: float = field(default_factory=time.time)
    reasoning_trace: Optional[ReasoningTrace] = None  # CoT integration
    checkpoints: List[PlanCheckpoint] = field(default_factory=list)


class QueryIntent(BaseModel):
    """Parsed intent from a natural language query."""
    
    primary_intent: str = Field(description="Main goal of the query")
    domain: str = Field(description="Domain (fMRI, connectivity, meta-analysis, etc.)")
    entities: Dict[str, Any] = Field(default_factory=dict, description="Extracted entities")
    constraints: List[str] = Field(default_factory=list, description="Query constraints")
    output_format: Optional[str] = Field(None, description="Desired output format")


class PlanningEngine:
    """
    Automated planning system for neuroscience workflows.
    
    Features:
    - Query understanding and intent extraction
    - Step generation with dependencies
    - Parameter inference from context
    - Cost estimation
    - Sub-500ms planning for typical queries
    - Plan optimization integration (AGENT-013)
    """
    
    def __init__(self, llm: Optional[BaseChatModel] = None, use_cot_reasoning: bool = True,
                 use_advanced_parsing: bool = True, enable_optimization: bool = True):
        """
        Initialize the planning engine.
        
        Args:
            llm: Language model for query understanding (optional)
            use_cot_reasoning: Whether to use Chain-of-Thought reasoning
            use_advanced_parsing: Whether to use advanced query parsing
            enable_optimization: Whether to enable plan optimization
        """
        self.tool_registry = ToolRegistry.from_env(auto_discover=True)
        self.use_cot_reasoning = use_cot_reasoning
        self.use_advanced_parsing = use_advanced_parsing
        self.enable_optimization = enable_optimization
        
        if llm:
            self.llm = llm
        else:
            try:
                from brain_researcher.services.agent.llm import get_llm
                self.llm = get_llm()
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")
                raise
        
        # Initialize Chain-of-Thought reasoner if enabled
        if self.use_cot_reasoning:
            try:
                self.cot_reasoner = get_cot_reasoner(self.llm)
                logger.info("Chain-of-Thought reasoner initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize CoT reasoner: {e}, proceeding without it")
                self.cot_reasoner = None
                self.use_cot_reasoning = False
        else:
            self.cot_reasoner = None
        
        # Initialize advanced query parser if enabled
        if self.use_advanced_parsing:
            try:
                domain_knowledge = get_domain_knowledge()
                self.advanced_parser = create_advanced_parser(
                    domain_knowledge=domain_knowledge,
                    llm=self.llm
                )
                logger.info("Advanced query parser initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize advanced parser: {e}, proceeding without it")
                self.advanced_parser = None
                self.use_advanced_parsing = False
        else:
            self.advanced_parser = None
        
        # Initialize plan optimizer if enabled
        if self.enable_optimization:
            try:
                from brain_researcher.services.agent.cost_models import CloudProvider
                from brain_researcher.services.agent.plan_optimizer import (
                    create_plan_optimizer,
                )

                self.plan_optimizer = create_plan_optimizer(cloud_provider=CloudProvider.AWS)
                logger.info("Plan optimizer initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize plan optimizer: {e}, proceeding without optimization")
                self.plan_optimizer = None
                self.enable_optimization = False
        else:
            self.plan_optimizer = None
        
        # Cache for tool capabilities
        self._tool_capabilities = self._build_tool_capabilities()
        self._tool_retriever = None

        logger.info("Planning Engine initialized")

    @staticmethod
    def _escape_prompt_json(text: str) -> str:
        """Escape braces so ChatPromptTemplate treats JSON as literal."""

        return text.replace("{", "{{").replace("}", "}}")

    async def _run_prompt(
        self,
        prompt: ChatPromptTemplate,
        values: Dict[str, Any],
    ) -> Any:
        """Format prompt and dispatch to the underlying LLM."""

        prompt_value = prompt.invoke(values)
        if isinstance(prompt_value, ChatPromptValue):
            input_data: Union[List[BaseMessage], str] = prompt_value.to_messages()
        else:
            input_data = prompt_value

        ainvoke = getattr(self.llm, "ainvoke", None)
        if callable(ainvoke):
            if asyncio.iscoroutinefunction(ainvoke):
                return await ainvoke(input_data)
            # If invoke is unavailable, try non-async ainvoke anyway.
            if not hasattr(self.llm, "invoke"):
                result = ainvoke(input_data)
                if asyncio.iscoroutine(result):
                    return await result
                return result

        invoke = getattr(self.llm, "invoke", None)
        if callable(invoke):
            result = invoke(input_data)
            if asyncio.iscoroutine(result):
                return await result
            return result
        raise TypeError("LLM must implement invoke or ainvoke")
    
    def _build_tool_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """Build a capabilities index for all available tools."""
        capabilities = {}
        
        for tool in self.tool_registry.get_all_tools():
            tool_name = tool.get_tool_name()
            capabilities[tool_name] = {
                "description": tool.get_tool_description(),
                "domains": self._extract_tool_domains(tool),
                "input_types": self._extract_input_types(tool),
                "output_types": self._extract_output_types(tool),
                "estimated_time": self._estimate_tool_time(tool),
                "resource_requirements": self._estimate_tool_resources(tool)
            }
        
        return capabilities

    def _get_tool_retriever(self):
        if self._tool_retriever is not None:
            return self._tool_retriever

        use_retriever = os.getenv("BR_USE_TOOL_RETRIEVER", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not use_retriever:
            return None

        try:
            from brain_researcher.services.agent.tool_retriever import ToolRetriever

            self._tool_retriever = ToolRetriever()
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("Planning tool retriever unavailable: %s", exc)
            self._tool_retriever = None

        return self._tool_retriever
    
    def _extract_tool_domains(self, tool: BaseTool) -> List[str]:
        """Extract domain categories for a tool."""
        desc = tool.get_tool_description().lower()
        domains = []
        
        # Domain mapping
        domain_keywords = {
            "fmri": ["fmri", "bold", "functional"],
            "structural": ["structural", "t1", "anatomy", "morphometry"],
            "connectivity": ["connectivity", "network", "correlation"],
            "statistics": ["glm", "statistics", "contrast", "model"],
            "knowledge": ["knowledge", "concept", "literature", "neurokg"],
            "preprocessing": ["preprocessing", "motion", "registration"],
            "visualization": ["plot", "visualiz", "display", "render"]
        }
        
        for domain, keywords in domain_keywords.items():
            if any(keyword in desc for keyword in keywords):
                domains.append(domain)
        
        return domains if domains else ["general"]
    
    def _extract_input_types(self, tool: BaseTool) -> List[str]:
        """Extract expected input types for a tool."""
        # This would ideally use tool schema, but for now use heuristics
        return ["dataset_id", "parameters"]
    
    def _extract_output_types(self, tool: BaseTool) -> List[str]:
        """Extract output types produced by a tool."""
        return ["results", "statistics", "visualizations"]
    
    def _estimate_tool_time(self, tool: BaseTool) -> float:
        """Estimate execution time for a tool in seconds."""
        tool_name = tool.get_tool_name().lower()
        
        # Time estimates based on tool type
        if "preprocessing" in tool_name or "fmriprep" in tool_name:
            return 3600.0  # 1 hour
        elif "glm" in tool_name or "analysis" in tool_name:
            return 300.0  # 5 minutes
        elif "connectivity" in tool_name:
            return 180.0  # 3 minutes
        elif "knowledge" in tool_name or "query" in tool_name:
            return 5.0  # 5 seconds
        else:
            return 60.0  # 1 minute default
    
    def _estimate_tool_resources(self, tool: BaseTool) -> Dict[ResourceType, float]:
        """Estimate resource requirements for a tool."""
        tool_name = tool.get_tool_name().lower()

        hints = get_resource_hints(tool.get_tool_name())
        if hints:
            resource_map: Dict[ResourceType, float] = {}
            cpu = hints.get("cpu")
            if cpu is not None:
                resource_map[ResourceType.CPU] = float(cpu)
            mem = hints.get("mem_gb")
            if mem is not None:
                resource_map[ResourceType.MEMORY] = float(mem)
            gpu = hints.get("gpu")
            if gpu:
                resource_map[ResourceType.GPU] = float(gpu)
            if resource_map:
                resource_map.setdefault(ResourceType.STORAGE, 0.0)
                return resource_map
        
        # Resource estimates
        if "preprocessing" in tool_name or "fmriprep" in tool_name:
            return {
                ResourceType.CPU: 4.0,
                ResourceType.MEMORY: 16.0,  # GB
                ResourceType.STORAGE: 50.0  # GB
            }
        elif "glm" in tool_name:
            return {
                ResourceType.CPU: 2.0,
                ResourceType.MEMORY: 8.0,
                ResourceType.STORAGE: 10.0
            }
        else:
            return {
                ResourceType.CPU: 1.0,
                ResourceType.MEMORY: 4.0,
                ResourceType.STORAGE: 1.0
            }
    
    async def parse_query(self, query: str, use_reasoning: bool = True) -> QueryIntent:
        """
        Parse a natural language query to extract intent and entities.
        Enhanced with Chain-of-Thought reasoning for complex queries.
        
        Args:
            query: Natural language query
            use_reasoning: Whether to use CoT reasoning for complex queries
            
        Returns:
            Parsed query intent
        """
        start_time = time.time()
        
        # Determine parsing strategy
        is_complex = self._is_complex_query(query)
        
        # Try advanced parsing first if enabled
        if self.use_advanced_parsing and self.advanced_parser:
            try:
                logger.info("Using advanced query parsing")
                return await self._parse_query_advanced(query, start_time)
            except Exception as e:
                logger.warning(f"Advanced parsing failed: {e}, falling back")
        
        # Fall back to CoT reasoning for complex queries
        should_use_cot = (
            self.use_cot_reasoning and 
            self.cot_reasoner and 
            use_reasoning and
            is_complex
        )
        
        if should_use_cot:
            logger.info("Using Chain-of-Thought reasoning for complex query parsing")
            return await self._parse_query_with_cot(query, start_time)
        else:
            return await self._parse_query_standard(query, start_time)
    
    def _is_complex_query(self, query: str) -> bool:
        """Determine if a query is complex enough to benefit from CoT reasoning."""
        complexity_indicators = [
            len(query.split()) > 15,  # Long query
            " and " in query.lower() or " or " in query.lower(),  # Multiple conditions
            "?" in query and query.count("?") > 1,  # Multiple questions
            any(word in query.lower() for word in ["compare", "contrast", "analyze", "evaluate", "relationship"]),
            "because" in query.lower() or "why" in query.lower(),  # Causal reasoning
        ]
        return sum(complexity_indicators) >= 2
    
    async def _parse_query_advanced(self, query: str, start_time: float) -> QueryIntent:
        """Parse query using advanced query parser with domain knowledge."""
        try:
            # Use advanced parser to get comprehensive parsing
            parsed_query = self.advanced_parser.parse(query)
            
            # Convert advanced parsing result to QueryIntent format
            entities_dict = {}
            for entity in parsed_query.entities:
                entity_type = entity.entity_type.value
                if entity_type not in entities_dict:
                    entities_dict[entity_type] = []
                entities_dict[entity_type].append(entity.text)
            
            # Map to standard entity categories
            standard_entities = {
                "datasets": entities_dict.get("dataset", []),
                "brain_regions": entities_dict.get("brain_region", []),
                "tasks": entities_dict.get("task", []),
                "contrasts": entities_dict.get("contrast", []),
                "methods": entities_dict.get("statistical_method", []),
                "modalities": entities_dict.get("modality", []),
                "coordinates": entities_dict.get("coordinate", []),
                "other": {}
            }
            
            # Add any other entities
            for entity_type, values in entities_dict.items():
                if entity_type not in ["dataset", "brain_region", "task", "contrast", 
                                      "statistical_method", "modality", "coordinate"]:
                    standard_entities["other"][entity_type] = values
            
            # Determine constraints from advanced parsing
            constraints = []
            if parsed_query.expansion:
                for term, synonyms in parsed_query.expansion.expanded_terms.items():
                    if synonyms:
                        constraints.append(f"Term '{term}' expanded to include: {', '.join(synonyms[:3])}")
            
            # Create QueryIntent object
            intent = QueryIntent(
                primary_intent=parsed_query.primary_intent.value,
                domain=self._map_intent_to_domain(parsed_query.primary_intent),
                entities=standard_entities,
                constraints=constraints,
                output_format=None  # Could be inferred from intent
            )
            
            elapsed = time.time() - start_time
            logger.info(
                f"Advanced parsing completed in {elapsed:.3f}s "
                f"(entities: {len(parsed_query.entities)}, confidence: {parsed_query.confidence:.2f})"
            )
            
            return intent
            
        except Exception as e:
            logger.error(f"Advanced parsing failed: {e}")
            # Fall back to standard parsing
            return await self._parse_query_standard(query, start_time)
    
    def _map_intent_to_domain(self, intent) -> str:
        """Map advanced parser intent to domain string."""
        # Import to avoid circular import
        from brain_researcher.services.agent.query_understanding import QueryIntent as AdvancedIntent
        
        intent_domain_map = {
            AdvancedIntent.ANALYSIS: "fmri",
            AdvancedIntent.COMPARISON: "statistics",
            AdvancedIntent.CORRELATION: "connectivity",
            AdvancedIntent.PREDICTION: "statistics",
            AdvancedIntent.VISUALIZATION: "visualization",
            AdvancedIntent.SEARCH: "knowledge",
            AdvancedIntent.PREPROCESSING: "preprocessing",
            AdvancedIntent.META_ANALYSIS: "meta-analysis",
            AdvancedIntent.QUALITY_CONTROL: "preprocessing",
            AdvancedIntent.DATA_EXTRACTION: "general"
        }
        
        return intent_domain_map.get(intent, "general")
    
    async def _parse_query_with_cot(self, query: str, start_time: float) -> QueryIntent:
        """Parse query using Chain-of-Thought reasoning."""
        try:
            # Generate reasoning trace for query understanding
            reasoning_trace = await self.cot_reasoner.reason(
                query,
                context={"task": "query_parsing", "domain": "neuroscience"},
                max_steps=5
            )
            
            # Extract intent from reasoning trace
            parsing_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a neuroscience query parser enhanced with reasoning analysis.

                Based on the reasoning trace below, extract query components:
                1. Primary intent (what the user wants to do)
                2. Domain (fMRI, connectivity, statistics, etc.)
                3. Entities (datasets, brain regions, tasks, etc.)
                4. Constraints (specific requirements or limitations)
                5. Output format (if specified)

                Use the reasoning steps to inform your analysis.

                Return a JSON object with these fields:
                {{
                    "primary_intent": "...",
                    "domain": "...",
                    "entities": {{
                        "datasets": [...],
                        "brain_regions": [...],
                        "tasks": [...],
                        "contrasts": [...],
                        "other": {{}}
                    }},
                    "constraints": [...],
                    "output_format": "..."
                }}
                """),
                ("human", """Query: {query}

                Reasoning Analysis:
                {reasoning_trace}

                Based on this reasoning, extract the query components.""")
            ])

            response = await self._run_prompt(
                parsing_prompt,
                {
                    "query": query,
                    "reasoning_trace": reasoning_trace.explanation,
                },
            )

            # Parse response
            intent = self._parse_intent_response(response.content, query)
            
            elapsed = time.time() - start_time
            logger.info(f"Query parsed with CoT reasoning in {elapsed:.3f}s (confidence: {reasoning_trace.overall_confidence:.2f})")
            
            return intent

        except Exception as e:
            logger.warning(f"CoT reasoning failed during parsing: {e}, falling back to standard parsing")
            return await self._parse_query_standard(query, start_time)
    
    async def _parse_query_standard(self, query: str, start_time: float) -> QueryIntent:
        """Standard query parsing without CoT reasoning."""
        parsing_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a neuroscience query parser.
            
            Analyze the query and extract:
            1. Primary intent (what the user wants to do)
            2. Domain (fMRI, connectivity, statistics, etc.)
            3. Entities (datasets, brain regions, tasks, etc.)
            4. Constraints (specific requirements or limitations)
            5. Output format (if specified)
            
            Return a JSON object with these fields:
            {{
                "primary_intent": "...",
                "domain": "...",
                "entities": {{
                    "datasets": [...],
                    "brain_regions": [...],
                    "tasks": [...],
                    "contrasts": [...],
                    "other": {{}}
                }},
                "constraints": [...],
                "output_format": "..."
            }}
            """),
            ("human", "{query}")
        ])
        
        response = await self._run_prompt(parsing_prompt, {"query": query})
        
        # Parse response
        intent = self._parse_intent_response(response.content, query)
        
        elapsed = time.time() - start_time
        logger.info(f"Query parsed in {elapsed:.3f}s")
        
        return intent
    
    def _parse_intent_response(self, content: str, query: str) -> QueryIntent:
        """Parse the LLM response into QueryIntent object."""
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            intent_data = json.loads(content)
            intent = QueryIntent(**intent_data)
        except Exception as e:
            logger.warning(f"Failed to parse intent: {e}, using defaults")
            intent = QueryIntent(
                primary_intent="analyze",
                domain="general",
                entities={"query": query}
            )
        
        return intent
    
    async def generate_plan(
        self,
        query: str,
        intent: Optional[QueryIntent] = None,
        context: Optional[Dict[str, Any]] = None,
        query_understanding: Optional[QueryUnderstandingResult] = None,
    ) -> ExecutionPlan:
        """
        Generate an execution plan for a query.
        
        Args:
            query: Natural language query
            intent: Pre-parsed intent (optional)
            context: Additional context for planning
            
        Returns:
            Complete execution plan
        """
        start_time = time.time()
        
        # Parse query if intent not provided
        reasoning_trace = None
        if not intent:
            intent = await self.parse_query(query)
            
            # Generate reasoning trace for complex plans if CoT is enabled
            if (self.use_cot_reasoning and self.cot_reasoner and 
                self._is_complex_query(query)):
                try:
                    reasoning_trace = await self.cot_reasoner.reason(
                        query,
                        context={"task": "planning", "domain": intent.domain},
                        max_steps=7
                    )
                    logger.info(f"Generated reasoning trace for planning (confidence: {reasoning_trace.overall_confidence:.2f})")
                except Exception as e:
                    logger.warning(f"Failed to generate reasoning trace for planning: {e}")
        
        # Attach query understanding into context for downstream use
        ctx = dict(context or {})
        if query_understanding:
            ctx["query_understanding"] = query_understanding

        # Ensure preflight query understanding + KG tool candidates (best-effort)
        if self.use_advanced_parsing and self.advanced_parser:
            ensure_query_understanding(query, ctx, parser=self.advanced_parser)

        if self.enable_optimization:
            ensure_tool_candidates(
                query,
                ctx,
                tool_retriever=self._get_tool_retriever(),
                registry=self.tool_registry,
            )

        # Generate workflow steps (enhanced with reasoning if available)
        steps = await self._generate_steps(query, intent, ctx, reasoning_trace)
        
        # Resolve dependencies
        steps = self._resolve_dependencies(steps)
        
        # Infer missing parameters
        steps = await self._infer_parameters(steps, intent, ctx)
        
        # Calculate costs
        total_time, total_resources = self._calculate_costs(steps)
        
        # Adjust confidence score based on reasoning trace
        base_confidence = self._calculate_confidence(steps)
        if reasoning_trace and reasoning_trace.overall_confidence > 0.5:
            # Boost confidence if we have high-quality reasoning
            confidence_boost = min(0.2, reasoning_trace.overall_confidence - 0.5)
            adjusted_confidence = min(1.0, base_confidence + confidence_boost)
        else:
            adjusted_confidence = base_confidence
        
        # Create execution plan
        plan = ExecutionPlan(
            plan_id=f"plan_{int(time.time() * 1000)}",
            query=query,
            objectives=self._extract_objectives(intent),
            steps=steps,
            success_criteria=self._generate_success_criteria(intent),
            total_estimated_time=total_time,
            total_resource_requirements=total_resources,
            confidence_score=adjusted_confidence,
            reasoning_trace=reasoning_trace  # Include CoT reasoning trace
        )
        
        elapsed = time.time() - start_time
        logger.info(f"Plan generated in {elapsed:.3f}s with {len(steps)} steps")
        
        # Verify we meet the <500ms requirement for typical queries
        if elapsed > 0.5 and len(steps) <= 3:
            logger.warning(f"Planning took {elapsed:.3f}s, exceeding 500ms target")
        
        return plan
    
    async def _generate_steps(
        self,
        query: str,
        intent: QueryIntent,
        context: Optional[Dict[str, Any]],
        reasoning_trace: Optional[ReasoningTrace] = None
    ) -> List[WorkflowStep]:
        """Generate workflow steps based on intent, optionally enhanced with reasoning trace."""

        # ------------------------------------------------------------------
        # Fast-path: simple visualization requests (Nilearn stat map plots)
        # ------------------------------------------------------------------
        if self._is_visualization_query(query):
            stat_map = None
            if context:
                stat_map = context.get("stat_map") or context.get("stat_map_path")
            if stat_map:
                display_mode = context.get("display_mode", "ortho") if context else "ortho"
                return [
                    WorkflowStep(
                        step_id="step_1",
                        step_number=1,
                        description="Visualize statistical map",
                        tool_name="viz_stat_maps",
                        tool_args={
                            "stat_map": stat_map,
                            "display_mode": display_mode,
                        },
                    )
                ]

        # ------------------------------------------------------------------
        # Pipeline-first heuristic (KG-driven templates)
        # ------------------------------------------------------------------
        if self._should_use_pipeline(intent, query):
            try:
                modalities = intent.entities.get("modalities") if intent and intent.entities else None
                pipelines = search_pipelines(
                    task=query,
                    modalities=modalities,
                    limit=1,
                )
                if pipelines:
                    logger.info(
                        "Pipeline catalog hit: %s", pipelines[0].get("id", "unknown")
                    )
                    return self._build_steps_from_pipeline(pipelines[0], context)
            except Exception as e:
                logger.warning(f"Pipeline search failed, falling back to LLM planning: {e}")
        
        # Get relevant tools for the domain
        relevant_tools = self._select_relevant_tools(intent.domain, context=context, query=query)
        
        # Build system prompt with optional reasoning context
        tools_json = self._escape_prompt_json(json.dumps(relevant_tools, indent=2))
        planning_policy_section = (
            "Planning policies:\n"
            "- If the query names a task, paradigm, or contrast in free text, "
            "first normalize it with a cheap grounding step before broader KG "
            "or literature search. Reuse the normalized task/concept name in "
            "downstream tool calls.\n"
            "- If a graph- or database-backed tool is unavailable, do not "
            "repeat the same call with only minor argument changes. Switch to "
            "a lighter fallback path such as task/concept grounding, direct "
            "MCP tools, or a narrower query.\n"
            "- Before launching an asynchronous or long-running workflow such "
            "as *_start hypothesis generation, first narrow the seed task, "
            "concept, or KG target with one cheap high-signal step unless the "
            "user query is already tightly scoped.\n"
            "- When a tool returns normalized names, matched tasks, concept "
            "lists, confidence fields, or count fields, preserve those fields "
            "explicitly in the plan and use them as arguments for later steps "
            "instead of paraphrasing them away."
        )
        system_prompt = f"""You are a workflow planner for neuroscience analysis.
            
Available tools:
{tools_json}

Generate a sequence of steps to accomplish the user's goal.
Each step should specify:
- Tool to use
- Arguments for the tool
- Dependencies on previous steps
- Expected output

{planning_policy_section}

{dataset_browse_instruction()}

{self._get_reasoning_context(reasoning_trace)}

Return the result as a JSON array where each entry contains the fields
listed above (step_number, description, tool_name, tool_args,
dependencies, expected_output)."""
        
        intent_json = self._escape_prompt_json(intent.model_dump_json())

        structured_context = ""
        qur: Optional[QueryUnderstandingResult] = None
        if context:
            qur = context.get("query_understanding") if isinstance(context, dict) else None
        if qur:
            structured_context = self._format_query_understanding(qur)

        generation_prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", f"Query: {query}\nIntent: {intent_json}\n{structured_context}")
        ])

        response = await self._run_prompt(generation_prompt, {})
        
        # Parse steps
        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            steps_data = json.loads(content)
        except Exception as e:
            logger.error(f"Failed to parse steps: {e}")
            steps_data = []
        
        # Convert to WorkflowStep objects
        steps = []
        for i, step_data in enumerate(steps_data):
            tool_name = step_data.get("tool_name", "unknown")
            tool_info = self._tool_capabilities.get(tool_name, {})
            
            step = WorkflowStep(
                step_id=f"step_{i+1}",
                step_number=step_data.get("step_number", i+1),
                description=step_data.get("description", ""),
                tool_name=tool_name,
                tool_args=step_data.get("tool_args", {}),
                dependencies=step_data.get("dependencies", []),
                expected_output=step_data.get("expected_output", ""),
                estimated_time_seconds=tool_info.get("estimated_time", 60.0),
                resource_requirements=tool_info.get("resource_requirements", {})
            )
            steps.append(step)
        
        return steps

    def _should_use_pipeline(self, intent: QueryIntent, query: str) -> bool:
        """Heuristic to decide whether to try pipeline templates first."""
        q = query.lower()

        # Strong textual hints of multi-step imaging workflows
        keywords = [
            "pipeline",
            "workflow",
            "preprocess",
            "registration",
            "normalize",
            "skull",
            "strip",
            "align",
            "mni",
            "tractography",
            "ica",
            "glm",
            "first level",
        ]
        keyword_hit = any(k in q for k in keywords)

        # Domain hint: imaging / preprocessing style intents
        domain_hit = intent.domain.lower() in {
            "fmri",
            "dmri",
            "smri",
            "imaging",
            "preprocessing",
            "neuroimaging",
        }

        return keyword_hit or domain_hit

    def _fill_params(self, params: Any, context: Optional[Dict[str, Any]] = None) -> Any:
        """Recursively fill parameter templates using the provided context.

        Supports str.format(**context) for strings and walks nested lists/dicts.
        If a key is missing in context, the original value is preserved.
        """

        if context is None:
            context = {}

        def _resolve(value: Any) -> Any:
            if isinstance(value, str):
                try:
                    return value.format(**context)
                except Exception:
                    return value
            if isinstance(value, list):
                return [_resolve(v) for v in value]
            if isinstance(value, dict):
                return {k: _resolve(v) for k, v in value.items()}
            return value

        return _resolve(params)

    def _build_steps_from_pipeline(self, pipeline: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[WorkflowStep]:
        """Convert a pipeline definition (id, steps list) into WorkflowSteps."""
        steps: List[WorkflowStep] = []
        step_defs = pipeline.get("steps", []) or []

        for idx, step_def in enumerate(step_defs):
            step_number = idx + 1
            dep = [f"step_{idx}"] if idx > 0 else []

            # Support both dict and plain string entries
            if isinstance(step_def, dict):
                tool_id = step_def.get("tool") or step_def.get("tool_id")
                description = step_def.get(
                    "description",
                    pipeline.get("description", f"Pipeline step {step_number}"),
                )
                params = step_def.get("params", {}) or {}
            else:
                tool_id = str(step_def)
                description = pipeline.get("description", f"Pipeline step {step_number}")
                params = {}

            # Fill template params using context (e.g., t1w_image, work_dir)
            filled_params = self._fill_params(params, context)

            step = WorkflowStep(
                step_id=f"step_{step_number}",
                step_number=step_number,
                description=description,
                tool_name=tool_id,
                tool_args=filled_params,
                dependencies=dep,
                expected_output="",
                estimated_time_seconds=60.0,
                resource_requirements={},
            )
            steps.append(step)

        return steps
    
    def _get_reasoning_context(self, reasoning_trace: Optional[ReasoningTrace]) -> str:
        """Get reasoning context for step generation prompt."""
        if not reasoning_trace:
            return ""
        
        context = f"""
Based on the following reasoning analysis, ensure your workflow steps align with the logical reasoning:

Reasoning Summary:
- Reasoning Type: {reasoning_trace.metadata.get('reasoning_type', 'analytical')}
- Overall Confidence: {reasoning_trace.overall_confidence:.2f}
- Key Conclusion: {reasoning_trace.final_conclusion}

Key Reasoning Steps:
"""
        for i, step in enumerate(reasoning_trace.steps[:3]):  # Show top 3 steps
            context += f"- Step {i+1}: {step.conclusion} (confidence: {step.confidence:.2f})\n"
        
        if len(reasoning_trace.steps) > 3:
            context += f"- ... and {len(reasoning_trace.steps) - 3} more steps\n"
        
        context += "\nEnsure workflow steps are consistent with this reasoning."
        return context

    def _format_query_understanding(self, qur: QueryUnderstandingResult) -> str:
        """Render QueryUnderstandingResult as a structured context block for prompts."""
        lines = ["# Structured Context"]

        if qur.resolved_datasets:
            lines.append("Resolved Datasets:")
            for ds in qur.resolved_datasets:
                lines.append(f"- id: {ds.dataset_id}")
                if ds.display_name:
                    lines.append(f"  name: {ds.display_name}")
                if ds.bids_path:
                    lines.append(f"  bids_path: {ds.bids_path}")
                if ds.resources:
                    lines.append(f"  is_bids_available: {ds.resources.is_bids_available}")
                    if ds.resources.derivatives:
                        lines.append("  derivatives:")
                        for kind, path in ds.resources.derivatives.items():
                            lines.append(f"    {kind}: {path}")
                    if ds.resources.remote_urls:
                        lines.append("  remote_urls:")
                        for k, v in ds.resources.remote_urls.items():
                            lines.append(f"    {k}: {v}")
        if qur.kg_nodes:
            lines.append("Resolved KG Nodes:")
            for node in qur.kg_nodes[:10]:
                lines.append(f"- type: {node.type} name: {node.label} kg_id: {node.id}")
        if qur.ambiguities:
            lines.append("Ambiguities (ask user before proceeding):")
            for amb in qur.ambiguities:
                lines.append(f"- {amb}")
        if qur.existing_derivatives:
            lines.append("Existing Derivatives:")
            for hit in qur.existing_derivatives:
                lines.append(f"- dataset: {hit.dataset_id} kind: {hit.kind} path: {hit.path}")
        lines.append(
            "Instruction: Prefer reuse of existing derivatives/paths above; avoid re-running steps already available. "
            "If ambiguities are present, add a clarification step before proceeding."
        )
        lines.append(f"Instruction: {dataset_browse_instruction()}")
        return "\n".join(lines)
    
    def _select_relevant_tools(
        self,
        domain: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Select tools relevant to a domain, preferring KG candidates when present."""
        relevant: Dict[str, Any] = {}

        tool_candidates = None
        if isinstance(context, dict):
            tool_candidates = context.get("tool_candidates")

        if tool_candidates:
            meta_by_id: Dict[str, Dict[str, Any]] = {}
            ordered_ids: List[str] = []
            for cand in tool_candidates:
                tool_id = None
                if isinstance(cand, dict):
                    tool_id = (
                        cand.get("tool_id")
                        or cand.get("tool_id_raw")
                        or cand.get("id")
                        or cand.get("name")
                    )
                else:
                    tool_id = (
                        getattr(cand, "tool_id", None)
                        or getattr(cand, "tool_id_raw", None)
                        or getattr(cand, "id", None)
                    )
                if not tool_id:
                    continue
                tid = str(tool_id)
                if tid not in meta_by_id:
                    ordered_ids.append(tid)
                if isinstance(cand, dict):
                    meta_by_id[tid] = cand

            query_understanding = (
                context.get("query_understanding") if isinstance(context, dict) else None
            )
            if is_exploratory_dataset_asset_request(
                query or "",
                query_understanding=query_understanding,
            ):
                ordered_ids = reorder_tool_ids_for_dataset_browse(ordered_ids)

            for tool_id in ordered_ids:
                capabilities = self._tool_capabilities.get(tool_id)
                if not capabilities:
                    continue
                enriched = {
                    "description": capabilities["description"],
                    "domains": capabilities["domains"],
                }
                meta = meta_by_id.get(tool_id, {})
                for key in ("source", "available", "score", "rank"):
                    if key in meta:
                        enriched[key] = meta[key]
                relevant[tool_id] = enriched

            if relevant:
                return relevant

        for tool_name, capabilities in self._tool_capabilities.items():
            if domain in capabilities["domains"] or "general" in capabilities["domains"]:
                relevant[tool_name] = {
                    "description": capabilities["description"],
                    "domains": capabilities["domains"],
                }

        return relevant
    
    def _resolve_dependencies(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        """Resolve and validate step dependencies."""
        step_ids = {step.step_id for step in steps}
        
        for step in steps:
            # Convert step numbers to IDs if needed
            resolved_deps = []
            for dep in step.dependencies:
                if isinstance(dep, int):
                    dep_id = f"step_{dep}"
                else:
                    dep_id = dep
                
                if dep_id in step_ids and dep_id != step.step_id:
                    resolved_deps.append(dep_id)
            
            step.dependencies = resolved_deps
        
        # Check for cycles
        if self._has_cycle(steps):
            logger.warning("Dependency cycle detected, removing problematic dependencies")
            # Simple fix: remove all dependencies (makes sequential)
            for step in steps:
                step.dependencies = []
        
        return steps
    
    def _has_cycle(self, steps: List[WorkflowStep]) -> bool:
        """Check if the dependency graph has cycles."""
        # Build adjacency list
        graph = {step.step_id: step.dependencies for step in steps}
        
        # DFS cycle detection
        visited = set()
        rec_stack = set()
        
        def has_cycle_util(node):
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle_util(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            
            rec_stack.remove(node)
            return False
        
        for step_id in graph:
            if step_id not in visited:
                if has_cycle_util(step_id):
                    return True
        
        return False
    
    async def _infer_parameters(
        self,
        steps: List[WorkflowStep],
        intent: QueryIntent,
        context: Optional[Dict[str, Any]]
    ) -> List[WorkflowStep]:
        """Infer missing parameters from context."""
        
        for step in steps:
            # Check for missing required parameters
            if not step.tool_args:
                step.tool_args = {}
            
            # Infer dataset_id if needed
            if "dataset" not in step.tool_args and "dataset_id" not in step.tool_args:
                datasets = intent.entities.get("datasets", [])
                if datasets:
                    step.tool_args["dataset_id"] = datasets[0]
                elif context and "dataset_id" in context:
                    step.tool_args["dataset_id"] = context["dataset_id"]
            
            # Infer brain regions
            if "region" not in step.tool_args:
                regions = intent.entities.get("brain_regions", [])
                if regions:
                    step.tool_args["region"] = regions[0]
            
            # Infer task names
            if "task" not in step.tool_args:
                tasks = intent.entities.get("tasks", [])
                if tasks:
                    step.tool_args["task"] = tasks[0]
        
        return steps
    
    def _calculate_costs(
        self,
        steps: List[WorkflowStep]
    ) -> Tuple[float, Dict[ResourceType, float]]:
        """Calculate total time and resource requirements."""
        total_time = 0.0
        total_resources = {}
        
        # Simple sequential time (could be optimized for parallel execution)
        for step in steps:
            total_time += step.estimated_time_seconds
            
            for resource, amount in step.resource_requirements.items():
                if resource not in total_resources:
                    total_resources[resource] = 0.0
                total_resources[resource] = max(
                    total_resources[resource],
                    amount  # Take max for parallel execution
                )
        
        return total_time, total_resources
    
    def _extract_objectives(self, intent: QueryIntent) -> List[str]:
        """Extract objectives from intent."""
        objectives = [intent.primary_intent]
        
        # Add domain-specific objectives
        if intent.domain:
            objectives.append(f"Perform {intent.domain} analysis")
        
        # Add constraint-based objectives
        for constraint in intent.constraints:
            objectives.append(f"Ensure {constraint}")
        
        return objectives
    
    def _generate_success_criteria(self, intent: QueryIntent) -> List[str]:
        """Generate success criteria for the plan."""
        criteria = []
        
        # Domain-specific criteria
        domain_criteria = {
            "fmri": ["Statistical maps generated", "Contrasts computed"],
            "connectivity": ["Connectivity matrix computed", "Network metrics calculated"],
            "statistics": ["Statistical tests completed", "P-values reported"],
            "knowledge": ["Relevant concepts identified", "Literature retrieved"]
        }
        
        if intent.domain in domain_criteria:
            criteria.extend(domain_criteria[intent.domain])
        
        # Output format criteria
        if intent.output_format:
            criteria.append(f"Results formatted as {intent.output_format}")
        
        # Default criteria
        if not criteria:
            criteria = ["Analysis completed successfully", "Results generated"]
        
        return criteria
    
    def _calculate_confidence(self, steps: List[WorkflowStep]) -> float:
        """Calculate confidence score for the plan."""
        if not steps:
            return 0.0
        
        confidence = 1.0
        
        for step in steps:
            # Reduce confidence for unknown tools
            if step.tool_name not in self._tool_capabilities:
                confidence *= 0.7
            
            # Reduce confidence for steps with many dependencies
            if len(step.dependencies) > 2:
                confidence *= 0.9
            
            # Reduce confidence for missing parameters
            if not step.tool_args:
                confidence *= 0.8
        
        return max(0.0, min(1.0, confidence))

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------

    def record_checkpoint(
        self,
        plan: ExecutionPlan,
        step: WorkflowStep,
        status: StepStatus,
        outputs: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> PlanCheckpoint:
        """Record a checkpoint after executing a step."""

        checkpoint = PlanCheckpoint(
            checkpoint_id=f"ckpt_{plan.plan_id}_{step.step_number}",
            step_id=step.step_id,
            step_number=step.step_number,
            status=status,
            outputs=outputs or {},
            error=error,
        )
        plan.checkpoints.append(checkpoint)
        return checkpoint

    def resume_from_checkpoint(
        self, plan: ExecutionPlan, checkpoint_id: str
    ) -> List[WorkflowStep]:
        """Mark steps as completed up to a checkpoint and return remaining steps."""

        completed: set[str] = set()
        for ckpt in plan.checkpoints:
            if ckpt.checkpoint_id == checkpoint_id:
                completed.add(ckpt.step_id)
                break
            completed.add(ckpt.step_id)

        remaining: List[WorkflowStep] = []
        for step in plan.steps:
            if step.step_id in completed:
                step.status = StepStatus.COMPLETED
            else:
                remaining.append(step)
        return remaining
    
    def validate_plan(self, plan: ExecutionPlan) -> List[str]:
        """
        Validate an execution plan.
        
        Args:
            plan: Execution plan to validate
            
        Returns:
            List of validation issues (empty if valid)
        """
        issues = []
        
        # Check for empty plan
        if not plan.steps:
            issues.append("Plan has no steps")
        
        # Check tool availability
        for step in plan.steps:
            if step.tool_name not in self._tool_capabilities:
                issues.append(f"Unknown tool: {step.tool_name}")
        
        # Check dependencies
        step_ids = {step.step_id for step in plan.steps}
        for step in plan.steps:
            for dep in step.dependencies:
                if dep not in step_ids:
                    issues.append(f"Step {step.step_id} has invalid dependency: {dep}")
        
        # Check for cycles
        if self._has_cycle(plan.steps):
            issues.append("Plan has circular dependencies")
        
        # Check resource requirements
        if plan.total_estimated_time > 7200:  # 2 hours
            issues.append(f"Plan exceeds time limit: {plan.total_estimated_time}s")
        
        return issues
    
    def optimize_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """
        Optimize an execution plan for parallel execution.
        
        Args:
            plan: Original execution plan
            
        Returns:
            Optimized execution plan
        """
        # Identify parallelizable steps
        parallel_groups = self._identify_parallel_groups(plan.steps)
        
        # Recalculate time for parallel execution
        parallel_time = 0.0
        for group in parallel_groups:
            group_time = max(step.estimated_time_seconds for step in group)
            parallel_time += group_time
        
        # Update plan with optimized time
        plan.total_estimated_time = parallel_time
        
        logger.info(
            f"Plan optimized: {len(parallel_groups)} parallel groups, "
            f"time reduced from {sum(s.estimated_time_seconds for s in plan.steps)}s "
            f"to {parallel_time}s"
        )
        
        return plan

    @staticmethod
    def _is_visualization_query(query: str) -> bool:
        """Heuristic for simple visualization tasks (stat map / glass brain / overlay)."""
        q = query.lower()
        keywords = [
            "visualize",
            "plot",
            "stat map",
            "glass brain",
            "orthoview",
            "overlay",
            "slice",
            "display",
        ]
        return any(k in q for k in keywords)
    
    def _identify_parallel_groups(
        self,
        steps: List[WorkflowStep]
    ) -> List[List[WorkflowStep]]:
        """Identify groups of steps that can run in parallel."""
        groups = []
        processed = set()
        
        # Simple algorithm: group steps with no dependencies together
        for step in steps:
            if step.step_id in processed:
                continue
            
            if not step.dependencies:
                # Find all other steps with no dependencies
                group = [step]
                processed.add(step.step_id)
                
                for other in steps:
                    if (other.step_id not in processed and 
                        not other.dependencies):
                        group.append(other)
                        processed.add(other.step_id)
                
                groups.append(group)
            else:
                # Single step group for now
                groups.append([step])
                processed.add(step.step_id)
        
        return groups


# Factory function
def get_planning_engine(llm: Optional[BaseChatModel] = None) -> PlanningEngine:
    """
    Get or create a planning engine instance.
    
    Args:
        llm: Optional language model
        
    Returns:
        Planning engine instance
    """
    return PlanningEngine(llm=llm)
