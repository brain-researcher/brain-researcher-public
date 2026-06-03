"""
Core LangGraph State Machine Implementation for Brain Researcher Agent

This module implements the foundational LangGraph state machine with Plan/Execute/Review states
as specified in AGENT-001 requirements.
"""

import logging
import time
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from brain_researcher.services.agent.cache_manager import (
    CacheKeyType,
    CachePolicy,
    QueryCacheManager,
)
from brain_researcher.services.agent.complexity_gate import (
    create_complexity_gate,
)
from brain_researcher.services.agent.dependency_resolver import (
    create_dependency_resolver,
)
from brain_researcher.services.agent.error_handling import (
    ErrorHandler,
    ErrorSeverity,
)
from brain_researcher.services.agent.issue_tracker import create_issue_tracker_backend
from brain_researcher.services.agent.parallel_executor import (
    ResourceType,
)
from brain_researcher.services.agent.parallel_executor import Task as ParallelTask
from brain_researcher.services.agent.parallel_executor import (
    create_parallel_orchestrator,
)
from brain_researcher.services.agent.plan_logger import create_plan_logger
from brain_researcher.services.agent.plan_memory import create_plan_memory
from brain_researcher.services.agent.planning import PlanningEngine
from brain_researcher.services.tools.executor import execute_tool
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


def _format_claim_memories_as_house_rules(cards: list[dict]) -> str:
    """Format claim_memory card dicts as a [Prior claims] block (≤5 items)."""
    if not cards:
        return ""
    supporting: list[str] = []
    conflicting: list[str] = []
    other: list[str] = []
    for card in cards[:5]:
        claim = " ".join(str(card.get("claim_text") or "").split())
        if not claim:
            continue
        confidence = str(card.get("confidence") or "preliminary")
        n_conflicting = len(card.get("conflicting_evidence") or [])
        n_supporting = len(card.get("supporting_evidence") or [])
        label = f"({confidence}) {claim}"
        if n_conflicting > 0:
            conflicting.append(label)
        elif n_supporting > 0:
            supporting.append(label)
        else:
            other.append(label)
    lines = ["[Prior claims]"]
    for item in supporting:
        lines.append(f"- SUPPORTS {item}")
    for item in conflicting:
        lines.append(f"- CONFLICTS {item}")
    for item in other:
        lines.append(f"- PRIOR {item}")
    return "\n".join(lines) if len(lines) > 1 else ""


class StatePhase(str, Enum):
    """Enumeration of state machine phases."""

    INIT = "init"
    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"
    ERROR = "error"
    COMPLETE = "complete"


class AgentState(TypedDict):
    """
    Core state definition for the Brain Researcher agent.

    Follows the Plan/Execute/Review pattern required by AGENT-001.
    """

    # Core conversation state
    messages: Annotated[list[BaseMessage], add_messages]

    # State machine phase tracking
    current_phase: StatePhase
    previous_phase: StatePhase | None

    # Planning state
    plan: dict[str, Any] | None
    plan_steps: list[dict[str, Any]]

    # Execution state
    selected_tools: list[str]
    tool_args: dict[str, dict[str, Any]]
    execution_results: dict[str, Any]

    # Review state
    review_feedback: dict[str, Any] | None
    needs_revision: bool

    # Error handling
    error: str | None
    error_recovery_attempts: int
    max_recovery_attempts: int

    # Session management
    thread_id: str
    session_checkpoint_id: str | None  # Renamed to avoid conflict with reserved name

    # Memory-signal routing (set externally or by prior execute step)
    hypothesis_cards: list[dict[str, Any]] | None
    execution_mode: str | None  # "standard" | "conflict_resolution"
    conflict_hint: str | None


class CoreStateMachine:
    """
    Core LangGraph state machine implementation with Plan/Execute/Review states.

    Implements the foundational requirements from AGENT-001:
    - State machine with proper transitions between Plan → Execute → Review states
    - State persistence using checkpointer (Redis-ready)
    - Error state handling and recovery mechanisms
    - Async operation support
    - Parallel execution orchestration (AGENT-015)
    """

    def __init__(
        self,
        llm=None,
        checkpointer=None,
        use_planning_engine=True,
        memory_path=None,
        cache_manager=None,
        cache_policy=CachePolicy.MODERATE,
        enable_parallel_execution=True,
        parallel_workers=4,
        resume_checkpoint_id: str | None = None,
    ):
        """
        Initialize the core state machine.

        Args:
            llm: Language model instance (optional, will use default if not provided)
            checkpointer: State persistence checkpointer (optional, uses MemorySaver by default)
            use_planning_engine: Whether to use the advanced planning engine (default: True)
            memory_path: Path to memory directory (optional, defaults to 'memory/')
            cache_manager: Cache manager instance (optional, will create if not provided)
            cache_policy: Cache policy to use (default: MODERATE)
            enable_parallel_execution: Enable parallel execution of independent tools (default: True)
            parallel_workers: Number of parallel worker threads (default: 4)
        """
        self.tool_registry = ToolRegistry.from_env(auto_discover=True)
        self.use_planning_engine = use_planning_engine
        self.enable_parallel_execution = enable_parallel_execution

        # Initialize cache manager
        if cache_manager:
            self.cache_manager = cache_manager
        else:
            self.cache_manager = QueryCacheManager(policy=cache_policy)

        logger.info(f"Cache manager initialized with policy: {cache_policy.value}")

        # Initialize Plan Memory System (Slice 1 MVP)
        try:
            self.plan_memory = create_plan_memory()
            self.complexity_gate = create_complexity_gate(plan_memory=self.plan_memory)

            # Initialize external issue tracker backend (optional, lazy)
            issue_tracker = create_issue_tracker_backend()
            if issue_tracker:
                logger.info(
                    "Issue tracker backend available (%s); enabling external issue logging",
                    getattr(issue_tracker, "provider", "unknown"),
                )

            self.plan_logger = create_plan_logger(
                plan_memory=self.plan_memory,
                issue_tracker=issue_tracker,
            )
            logger.info("Plan memory system initialized (MVP)")
        except Exception as e:
            logger.warning(
                f"Failed to initialize plan memory system: {e}, proceeding without it"
            )
            self.plan_memory = None
            self.complexity_gate = None
            self.plan_logger = None

        # Optional resume support for LangGraph runner
        self.resume_checkpoint_id = resume_checkpoint_id

        # Initialize parallel execution components
        if self.enable_parallel_execution:
            self.parallel_orchestrator = create_parallel_orchestrator(
                max_workers=parallel_workers
            )
            self.dependency_resolver = create_dependency_resolver()
            logger.info(f"Parallel execution enabled with {parallel_workers} workers")
        else:
            self.parallel_orchestrator = None
            self.dependency_resolver = None

        # Initialize memory system
        self._init_memory_system(memory_path)

        # Initialize LLM
        if llm:
            self.llm = llm
        else:
            try:
                from brain_researcher.services.agent.llm import get_llm

                self.llm = get_llm()
                logger.info("Initialized LLM from configured factory")
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")
                raise

        # Initialize checkpointer (can be swapped for Redis checkpointer)
        self.checkpointer = checkpointer or MemorySaver()

        # Initialize planning engine if enabled
        if self.use_planning_engine:
            self.planning_engine = PlanningEngine(llm=self.llm)
            logger.info("Planning engine initialized")
        else:
            self.planning_engine = None

        # Build and compile the graph
        self.graph = self._build_graph()
        self.app = self.graph.compile(checkpointer=self.checkpointer)

        logger.info("Core state machine initialized successfully")

    def _build_graph(self) -> StateGraph:
        """
        Build the Plan/Execute/Review state machine graph.

        Returns:
            Configured StateGraph instance
        """
        workflow = StateGraph(AgentState)

        # Add state nodes
        workflow.add_node("route_memory", self.route_by_memory_signal)
        workflow.add_node("plan", self._plan_state)
        workflow.add_node("execute", self._execute_state)
        workflow.add_node("review", self._review_state)
        workflow.add_node("error", self._error_state)

        # Set entry point
        workflow.set_entry_point("route_memory")
        workflow.add_edge("route_memory", "plan")

        # Add conditional edges
        workflow.add_conditional_edges(
            "plan",
            self._route_from_plan,
            {
                "execute": "execute",
                "error": "error",
            },
        )

        workflow.add_conditional_edges(
            "execute",
            self._route_from_execute,
            {
                "review": "review",
                "error": "error",
            },
        )

        workflow.add_conditional_edges(
            "review",
            self._route_from_review,
            {
                "complete": END,
                "plan": "plan",  # Revision needed
                "error": "error",
            },
        )

        workflow.add_conditional_edges(
            "error",
            self._route_from_error,
            {
                "plan": "plan",  # Retry from planning
                "execute": "execute",  # Retry execution
                "end": END,  # Max attempts reached
            },
        )

        return workflow

    async def _plan_state_async(self, state: AgentState) -> AgentState:
        """
        Planning state with async planning engine support.
        """
        if self.use_planning_engine and self.planning_engine:
            return await self._plan_with_engine(state)
        else:
            return self._plan_state_sync(state)

    def _plan_state(self, state: AgentState) -> AgentState:
        """
        Planning state with complexity gate routing and plan memory integration.

        Flow:
        1. Assess query complexity via ComplexityGate
        2. Simple queries → single tool execution (fast path)
        3. Complex queries → check plan memory for similar plans
        4. No similar plan → full planning via PlanningEngine
        5. Record plan to memory and log to markdown
        """
        import asyncio

        # Extract query
        human_messages = [
            msg for msg in state.get("messages", []) if isinstance(msg, HumanMessage)
        ]

        if not human_messages:
            logger.warning("No human message found, falling back to standard planning")
            return self._plan_state_fallback(state)

        query = human_messages[-1].content
        user_id = state.get("user_id", "anonymous")
        workspace_id = state.get("workspace_id")

        # Step 1: Complexity Assessment (if available)
        complexity_result = None
        if self.complexity_gate:
            try:
                complexity_result = self.complexity_gate.assess(
                    query,
                    {
                        "user_id": user_id,
                        "workspace_id": workspace_id,
                    },
                )
                state["complexity_result"] = {
                    "level": complexity_result.level,
                    "confidence": complexity_result.confidence,
                    "reason": complexity_result.reason,
                }
                logger.info(
                    f"Complexity assessment: {complexity_result.level} (confidence={complexity_result.confidence:.2f})"
                )
            except Exception as e:
                logger.warning(
                    f"Complexity gate failed: {e}, proceeding with full planning"
                )

        # Step 2: Route based on complexity
        if (
            complexity_result
            and complexity_result.level == "simple"
            and complexity_result.suggested_tool
        ):
            # FAST PATH: Simple query with suggested tool
            plan = self._create_simple_plan(query, complexity_result.suggested_tool)
            state["plan"] = plan
            state["plan_steps"] = plan.get("steps", [])
            state["plan_source"] = "complexity_gate_simple"

            # Record to memory and log
            self._record_and_log_plan(
                plan, user_id, workspace_id, query, complexity_result, state
            )

            state["previous_phase"] = state.get("current_phase")
            state["current_phase"] = StatePhase.PLAN

            state["messages"].append(
                AIMessage(
                    content=f"Simple query detected - using {complexity_result.suggested_tool}"
                )
            )
            return state

        # Step 3: Check Plan Memory for similar plans (complex queries)
        if self.plan_memory and complexity_result:
            try:
                similar_plans = self.plan_memory.recall_similar(
                    query, user_id, workspace_id, top_k=3
                )

                if similar_plans and similar_plans[0].get("similarity", 0) > 0.7:
                    # Found a similar successful plan - could adapt it
                    # For MVP, we just log and proceed with fresh planning
                    # Plan adaptation will be added in Slice 2
                    logger.info(
                        f"Found similar plan with {similar_plans[0]['similarity']:.2f} similarity"
                    )
                    state["similar_plan_found"] = similar_plans[0]["plan_id"]
            except Exception as e:
                logger.warning(f"Plan memory lookup failed: {e}")

        # Step 4: Full planning via PlanningEngine
        if self.use_planning_engine and self.planning_engine:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    self._plan_with_engine_and_record(
                        state, query, user_id, workspace_id, complexity_result
                    )
                )
                return result
            finally:
                loop.close()
        else:
            return self._plan_state_sync_with_record(
                state, query, user_id, workspace_id, complexity_result
            )

    def _create_simple_plan(self, query: str, tool_name: str) -> dict:
        """Create a simple single-step plan for direct tool execution."""
        import uuid

        return {
            "plan_id": f"simple_{uuid.uuid4().hex[:12]}",
            "query": query,
            "steps": [
                {
                    "step_id": "step_1",
                    "step_number": 1,
                    "tool_name": tool_name,
                    "tool_args": {},  # Will be inferred during execution
                    "description": f"Execute {tool_name} for: {query[:50]}...",
                    "dependencies": [],
                }
            ],
            "source": "complexity_gate_simple",
            "objectives": [f"Execute {tool_name} query"],
            "success_criteria": ["Tool execution succeeded"],
        }

    def _record_and_log_plan(
        self,
        plan: dict,
        user_id: str,
        workspace_id: str,
        query: str,
        complexity_result,
        state: AgentState,
    ):
        """Record plan to memory and log to markdown."""
        plan.get("plan_id")

        # Record to plan memory
        if self.plan_memory:
            try:
                memory_id = self.plan_memory.record_plan(
                    plan=plan,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    query=query,
                    complexity_level=(
                        complexity_result.level if complexity_result else None
                    ),
                    complexity_reason=(
                        complexity_result.reason if complexity_result else None
                    ),
                )
                state["plan_memory_id"] = memory_id
                logger.info(f"Plan recorded to memory: {memory_id}")
            except Exception as e:
                logger.warning(f"Failed to record plan to memory: {e}")

        # Log to markdown
        if self.plan_logger:
            try:
                md_path = self.plan_logger.log_plan(
                    plan=plan,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    plan_memory_id=state.get("plan_memory_id"),
                )
                state["plan_markdown_path"] = md_path

                # Update memory with markdown path
                if self.plan_memory and state.get("plan_memory_id"):
                    self.plan_memory.update_markdown_path(
                        state["plan_memory_id"], md_path
                    )

                logger.info(f"Plan logged to: {md_path}")
            except Exception as e:
                logger.warning(f"Failed to log plan to markdown: {e}")

    async def _plan_with_engine_and_record(
        self,
        state: AgentState,
        query: str,
        user_id: str,
        workspace_id: str,
        complexity_result,
    ) -> AgentState:
        """Use planning engine and record the result."""
        # Call the existing planning engine logic
        state = await self._plan_with_engine(state)

        # Record and log if planning succeeded
        if state.get("plan") and not state.get("error"):
            plan = state["plan"]
            plan["query"] = query
            plan["plan_id"] = plan.get("plan_id", f"engine_{uuid4().hex[:12]}")
            self._record_and_log_plan(
                plan, user_id, workspace_id, query, complexity_result, state
            )
            state["plan_source"] = "planning_engine"

        return state

    def _plan_state_sync_with_record(
        self,
        state: AgentState,
        query: str,
        user_id: str,
        workspace_id: str,
        complexity_result,
    ) -> AgentState:
        """Sync planning with recording."""
        import uuid

        state = self._plan_state_sync(state)

        # Record and log if planning succeeded
        if state.get("plan") and not state.get("error"):
            plan = state["plan"]
            plan["query"] = query
            plan["plan_id"] = plan.get("plan_id", f"sync_{uuid.uuid4().hex[:12]}")
            self._record_and_log_plan(
                plan, user_id, workspace_id, query, complexity_result, state
            )
            state["plan_source"] = "sync_planning"

        return state

    def _plan_state_fallback(self, state: AgentState) -> AgentState:
        """Fallback planning when no query is found."""
        state["previous_phase"] = state.get("current_phase")
        state["current_phase"] = StatePhase.PLAN
        state["error"] = "No query found in messages"
        return state

    async def _plan_with_engine(self, state: AgentState) -> AgentState:
        """
        Use the advanced planning engine for plan generation with caching.
        """
        logger.info("Using Planning Engine for plan generation")

        state["previous_phase"] = state.get("current_phase")
        state["current_phase"] = StatePhase.PLAN

        try:
            # Extract query
            human_messages = [
                msg for msg in state["messages"] if isinstance(msg, HumanMessage)
            ]

            if not human_messages:
                raise ValueError("No human message found in conversation")

            query = human_messages[-1].content

            # Generate cache key for planning
            cache_context = {
                "use_planning_engine": True,
                "thread_id": state.get("thread_id"),
            }

            cache_key = self.cache_manager.key_generator.generate_key(
                query, context=cache_context, key_type=CacheKeyType.PLANNING_RESULT
            )

            # Check cache first
            cached_plan = self.cache_manager._get_from_cache(cache_key)
            if cached_plan is not None:
                execution_plan = cached_plan
                logger.info("Using cached planning result")
            else:
                # Generate plan using planning engine
                execution_plan = await self.planning_engine.generate_plan(query)

                # Cache the result
                self.cache_manager._set_in_cache(
                    cache_key,
                    execution_plan,
                    ttl_seconds=1800,  # 30 minutes
                    key_type=CacheKeyType.PLANNING_RESULT,
                    tags={"planning", "query_based"},
                )
                logger.info("Generated and cached new planning result")

            # Convert to state format
            plan = {
                "objectives": execution_plan.objectives,
                "steps": [
                    {
                        "step_number": step.step_number,
                        "description": step.description,
                        "tool": step.tool_name,
                        "args": step.tool_args,
                        "expected_output": step.expected_output,
                    }
                    for step in execution_plan.steps
                ],
                "success_criteria": execution_plan.success_criteria,
            }

            if not plan["steps"]:
                logger.warning(
                    "Planning engine returned empty plan, falling back to sync planning"
                )
                return self._plan_state_sync(state)

            state["plan"] = plan
            state["plan_steps"] = plan["steps"]

            # Add AI message about the plan
            state["messages"].append(
                AIMessage(
                    content=f"Generated execution plan with {len(plan['steps'])} steps in {execution_plan.total_estimated_time:.1f}s estimated time"
                )
            )

            logger.info(f"Planning Engine generated {len(plan['steps'])} steps")

        except Exception as e:
            logger.error(f"Planning Engine error: {e}, falling back to simple planning")
            # Fallback to simple planning
            return self._plan_state_sync(state)

        return state

    def _plan_state_sync(self, state: AgentState) -> AgentState:
        """
        Planning state: Analyze query and create execution plan.

        Args:
            state: Current agent state

        Returns:
            Updated state with plan
        """
        logger.info("Entering PLAN state")

        state["previous_phase"] = state.get("current_phase")
        state["current_phase"] = StatePhase.PLAN

        try:
            # Extract the latest human message
            human_messages = [
                msg for msg in state["messages"] if isinstance(msg, HumanMessage)
            ]

            if not human_messages:
                raise ValueError("No human message found in conversation")

            query = human_messages[-1].content

            # Inject memory-based house rules
            house_rules = self._get_relevant_memories(query, state)

            # Optionally inject conflict-resolution guidance from prior routing
            conflict_section = ""
            if state.get("execution_mode") == "conflict_resolution":
                hint = str(state.get("conflict_hint") or "")
                conflict_section = (
                    "\n\n[Conflict resolution mode]"
                    + (f"\nReason: {hint}" if hint else "")
                    + "\nDesign the first step to be a discriminating experiment that "
                    "distinguishes the two competing claims. Prefer within-subject "
                    "designs, matched contrasts, or held-out datasets not used in "
                    "prior runs."
                )

            planning_policy_section = (
                "\n\n[Planning policies]"
                "\n- If the query names a task, paradigm, or contrast in free text, "
                "first normalize it with a cheap grounding step before broader KG "
                "or literature search. Reuse the normalized task/concept name in "
                "downstream tool calls."
                "\n- If a graph- or database-backed tool is unavailable, do not "
                "repeat the same call with only minor argument changes. Switch to "
                "a lighter fallback path such as task/concept grounding, direct "
                "MCP tools, or a narrower query."
                "\n- Before launching an asynchronous or long-running workflow such "
                "as *_start hypothesis generation, first narrow the seed task, "
                "concept, or KG target with one cheap high-signal step unless the "
                "user query is already tightly scoped."
                "\n- When a tool returns normalized names, matched tasks, concept "
                "lists, confidence fields, or count fields, preserve those fields "
                "explicitly in the plan and use them as arguments for later steps "
                "instead of paraphrasing them away."
            )

            # Create planning prompt with house rules
            system_prompt = """You are a neuroscience research assistant creating an execution plan.

                Analyze the user's query and create a structured plan with:
                1. Clear objectives
                2. Required tools and their sequence
                3. Expected outputs
                4. Success criteria

                {house_rules}{conflict_section}{planning_policy_section}

                Return a JSON object with:
                {{
                    "objectives": ["objective1", "objective2"],
                    "steps": [
                        {{
                            "step_number": 1,
                            "description": "...",
                            "tool": "tool_name",
                            "args": {{}},
                            "expected_output": "..."
                        }}
                    ],
                    "success_criteria": ["criterion1", "criterion2"]
                }}
                """.format(
                house_rules=house_rules if house_rules else "",
                conflict_section=conflict_section,
                planning_policy_section=planning_policy_section,
            )
            system_prompt = system_prompt.replace("{", "{{").replace("}", "}}")

            planning_prompt = ChatPromptTemplate.from_messages(
                [("system", system_prompt), ("human", "{query}")]
            )

            # Generate plan
            prompt_value = planning_prompt.invoke({"query": query})
            input_data = (
                prompt_value.to_messages()
                if hasattr(prompt_value, "to_messages")
                else prompt_value
            )
            response = self.llm.invoke(input_data)

            # Parse plan (with error handling)
            import json

            try:
                plan_content = (
                    response.content if hasattr(response, "content") else response
                )
                # Extract JSON from response if wrapped in markdown
                if "```json" in plan_content:
                    plan_content = plan_content.split("```json")[1].split("```")[0]
                elif "```" in plan_content:
                    plan_content = plan_content.split("```")[1].split("```")[0]

                plan = json.loads(plan_content)
            except json.JSONDecodeError:
                # Fallback plan structure
                plan = {
                    "objectives": ["Analyze the user's neuroscience query"],
                    "steps": [
                        {
                            "step_number": 1,
                            "description": "Process query with available tools",
                            "tool": "task_to_concept_mapping",
                            "args": {},
                            "expected_output": "Analysis results",
                        }
                    ],
                    "success_criteria": ["Provide meaningful neuroscience insights"],
                }

            state["plan"] = plan
            state["plan_steps"] = plan.get("steps", [])

            # Add AI message about the plan
            state["messages"].append(
                AIMessage(
                    content=f"Created execution plan with {len(plan['steps'])} steps"
                )
            )

            logger.info(f"Plan created with {len(plan['steps'])} steps")

        except Exception as e:
            logger.error(f"Error in planning state: {e}")
            state["error"] = f"Planning failed: {str(e)}"
            state["current_phase"] = StatePhase.ERROR

        return state

    def _execute_state(self, state: AgentState) -> AgentState:
        """
        Execution state: Execute the planned tools with optional parallel execution.

        Args:
            state: Current agent state

        Returns:
            Updated state with execution results
        """
        logger.info("Entering EXECUTE state")

        state["previous_phase"] = state.get("current_phase")
        state["current_phase"] = StatePhase.EXECUTE

        try:
            plan_steps = state.get("plan_steps", [])
            if not plan_steps:
                raise ValueError("No plan steps to execute")

            # Determine execution strategy
            if (
                self.enable_parallel_execution
                and self.parallel_orchestrator
                and len(plan_steps) > 1
            ):
                # Use parallel execution
                execution_results = self._execute_parallel(plan_steps, state)
            else:
                # Use sequential execution (fallback)
                execution_results = self._execute_sequential(plan_steps, state)

            state["execution_results"] = execution_results

            # Add execution summary to messages
            successful_tools = [
                name
                for name, result in execution_results.items()
                if result.get("status") == "success"
            ]

            state["messages"].append(
                AIMessage(
                    content=f"Executed {len(successful_tools)}/{len(plan_steps)} tools successfully"
                )
            )

        except Exception as e:
            logger.error(f"Error in execution state: {e}")
            state["error"] = f"Execution failed: {str(e)}"
            state["current_phase"] = StatePhase.ERROR

        return state

    def _execute_parallel(
        self, plan_steps: list[dict[str, Any]], state: AgentState
    ) -> dict[str, Any]:
        """
        Execute plan steps in parallel using the orchestrator.

        Args:
            plan_steps: List of plan steps
            state: Current agent state

        Returns:
            Dictionary of execution results
        """
        logger.info(f"Executing {len(plan_steps)} steps in parallel")

        # Convert plan steps to parallel tasks
        tasks = []
        for i, step in enumerate(plan_steps):
            tool_name = step.get("tool", f"unknown_{i}")
            task = ParallelTask(
                task_id=f"task_{i}",
                name=step.get("description", f"Execute {tool_name}"),
                tool_name=tool_name,
                tool_args=step.get("args", {}),
                dependencies=step.get("dependencies", []),
                estimated_duration=step.get("estimated_duration", 60.0),
                resource_requirements=self._infer_resource_requirements(tool_name),
            )
            tasks.append(task)

        # Create execution graph
        try:
            execution_graph = self.dependency_resolver.resolve(tasks)
        except Exception as e:
            logger.warning(
                f"Failed to resolve dependencies for parallel execution: {e}, falling back to sequential"
            )
            return self._execute_sequential(plan_steps, state)

        # Execute in parallel
        try:
            import asyncio

            # Create execution tracker for progress monitoring
            from brain_researcher.services.agent.execution_status import (
                ExecutionTracker,
            )

            tracker = ExecutionTracker(execution_id=f"parallel_{int(time.time())}")

            # Run parallel execution
            loop = asyncio.new_event_loop()
            try:
                parallel_result = loop.run_until_complete(
                    self.parallel_orchestrator.execute_parallel(
                        execution_graph, tracker
                    )
                )

                # Convert parallel results back to expected format
                execution_results = {}
                for i, step in enumerate(plan_steps):
                    tool_name = step.get("tool")
                    task_id = f"task_{i}"

                    if task_id in parallel_result["results"]:
                        execution_results[tool_name] = {
                            "status": "success",
                            "result": parallel_result["results"][task_id],
                        }
                    elif task_id in parallel_result["errors"]:
                        execution_results[tool_name] = {
                            "status": "error",
                            "error": parallel_result["errors"][task_id],
                        }
                    else:
                        execution_results[tool_name] = {
                            "status": "unknown",
                            "error": "No result found",
                        }

                # Log performance metrics
                metrics = parallel_result.get("metrics", {})
                speedup = metrics.get("speedup", 1.0)
                logger.info(
                    f"Parallel execution completed with {speedup:.2f}x speedup "
                    f"({metrics.get('tasks_completed', 0)} successful, "
                    f"{metrics.get('tasks_failed', 0)} failed)"
                )

                return execution_results

            finally:
                loop.close()

        except Exception as e:
            logger.error(f"Parallel execution failed: {e}, falling back to sequential")
            return self._execute_sequential(plan_steps, state)

    def _execute_sequential(
        self, plan_steps: list[dict[str, Any]], state: AgentState
    ) -> dict[str, Any]:
        """
        Execute plan steps sequentially (fallback method).

        Args:
            plan_steps: List of plan steps
            state: Current agent state

        Returns:
            Dictionary of execution results
        """
        logger.info(f"Executing {len(plan_steps)} steps sequentially")

        execution_results = {}

        for step in plan_steps:
            tool_name = step.get("tool")
            tool_args = step.get("args", {})

            logger.info(f"Executing tool: {tool_name}")

            # Get tool from registry
            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                logger.warning(f"Tool {tool_name} not found, skipping")
                execution_results[tool_name] = {
                    "status": "skipped",
                    "reason": "Tool not found",
                }
                continue

            try:
                # Generate cache key for tool execution
                tool_cache_key = self.cache_manager.key_generator.generate_key(
                    f"tool_{tool_name}",
                    context=tool_args,
                    key_type=CacheKeyType.TOOL_EXECUTION,
                )

                # Check cache for tool result
                use_cache = not hasattr(tool, "mock_calls")
                cached_result = (
                    self.cache_manager._get_from_cache(tool_cache_key)
                    if use_cache
                    else None
                )
                status = "success"
                if cached_result is not None:
                    result = cached_result
                    logger.info(f"Using cached result for tool {tool_name}")
                else:
                    # Execute tool directly when available; fall back to unified executor.
                    if tool and hasattr(tool, "run"):
                        exec_res = tool.run(**tool_args)
                    else:
                        exec_res = execute_tool(
                            tool_name,
                            tool_args,
                            work_dir=tool_args.get("work_dir"),
                            output_dir=tool_args.get("output_dir"),
                        )
                    if hasattr(exec_res, "model_dump"):
                        result = exec_res.model_dump()
                        status = exec_res.status
                    else:
                        result = exec_res or {}
                        status = result.get("status", "success")

                    # Cache the result (shorter TTL for tool execution)
                    if use_cache:
                        self.cache_manager._set_in_cache(
                            tool_cache_key,
                            result,
                            ttl_seconds=900,  # 15 minutes for tool results
                            key_type=CacheKeyType.TOOL_EXECUTION,
                            tags={"tools", tool_name},
                        )
                        logger.info(f"Tool {tool_name} executed and cached")

                execution_results[tool_name] = {"status": status, "result": result}

            except Exception as tool_error:
                logger.error(f"Tool {tool_name} failed: {tool_error}")
                execution_results[tool_name] = {
                    "status": "error",
                    "error": str(tool_error),
                }

        return execution_results

    def _infer_resource_requirements(self, tool_name: str) -> list:
        """
        Infer resource requirements for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            List of resource requirements
        """
        # Simple heuristics for resource inference
        from brain_researcher.services.agent.parallel_executor import (
            ResourceRequirement,
        )

        requirements = []

        if not tool_name:
            return requirements

        tool_name_lower = tool_name.lower()

        if "fmriprep" in tool_name_lower or "preprocessing" in tool_name_lower:
            requirements.extend(
                [
                    ResourceRequirement(ResourceType.CPU, 4.0, "cores", 3),
                    ResourceRequirement(ResourceType.MEMORY, 16.0, "GB", 3),
                    ResourceRequirement(ResourceType.STORAGE, 50.0, "GB", 2),
                ]
            )
        elif "glm" in tool_name_lower or "analysis" in tool_name_lower:
            requirements.extend(
                [
                    ResourceRequirement(ResourceType.CPU, 2.0, "cores", 2),
                    ResourceRequirement(ResourceType.MEMORY, 8.0, "GB", 2),
                ]
            )
        elif "connectivity" in tool_name_lower or "network" in tool_name_lower:
            requirements.extend(
                [
                    ResourceRequirement(ResourceType.CPU, 2.0, "cores", 2),
                    ResourceRequirement(ResourceType.MEMORY, 4.0, "GB", 2),
                ]
            )
        else:
            # Default requirements for unknown tools
            requirements.extend(
                [
                    ResourceRequirement(ResourceType.CPU, 1.0, "cores", 1),
                    ResourceRequirement(ResourceType.MEMORY, 2.0, "GB", 1),
                ]
            )

        return requirements

    def _review_state(self, state: AgentState) -> AgentState:
        """
        Review state: Evaluate execution results and determine if revision is needed.

        Args:
            state: Current agent state

        Returns:
            Updated state with review feedback
        """
        logger.info("Entering REVIEW state")

        state["previous_phase"] = state.get("current_phase")
        state["current_phase"] = StatePhase.REVIEW

        try:
            execution_results = state.get("execution_results", {})
            plan = state.get("plan", {})
            success_criteria = plan.get("success_criteria", [])

            # Create review prompt
            review_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        """You are reviewing the execution results of a neuroscience analysis.

                Evaluate:
                1. Were the success criteria met?
                2. Is the output complete and accurate?
                3. Does it answer the user's query?
                4. Are any revisions needed?

                Return a JSON object with:
                {{
                    "criteria_met": true/false,
                    "completeness": 0-100,
                    "accuracy_confidence": 0-100,
                    "needs_revision": true/false,
                    "revision_reason": "..." (if revision needed),
                    "summary": "Brief summary of results"
                }}
                """,
                    ),
                    ("human", "Results: {results}\nCriteria: {criteria}"),
                ]
            )

            prompt_value = review_prompt.invoke(
                {"results": str(execution_results), "criteria": str(success_criteria)}
            )
            input_data = (
                prompt_value.to_messages()
                if hasattr(prompt_value, "to_messages")
                else prompt_value
            )
            response = self.llm.invoke(input_data)

            # Parse review feedback
            import json

            try:
                review_content = (
                    response.content if hasattr(response, "content") else response
                )
                if "```json" in review_content:
                    review_content = review_content.split("```json")[1].split("```")[0]
                elif "```" in review_content:
                    review_content = review_content.split("```")[1].split("```")[0]

                review_feedback = json.loads(review_content)
            except json.JSONDecodeError:
                # Fallback review
                review_feedback = {
                    "criteria_met": True,
                    "completeness": 80,
                    "accuracy_confidence": 85,
                    "needs_revision": False,
                    "summary": "Analysis completed successfully",
                }

            state["review_feedback"] = review_feedback
            state["needs_revision"] = review_feedback.get("needs_revision", False)

            # Add review summary to messages
            state["messages"].append(
                AIMessage(content=review_feedback.get("summary", "Review completed"))
            )

            if state["needs_revision"]:
                logger.info("Review determined revision is needed")
            else:
                logger.info("Review passed, marking as complete")
                state["current_phase"] = StatePhase.COMPLETE

                # Record outcome to plan memory (MVP - Slice 1)
                self._record_plan_outcome(state, "succeeded")

        except Exception as e:
            logger.error(f"Error in review state: {e}")
            state["error"] = f"Review failed: {str(e)}"
            state["current_phase"] = StatePhase.ERROR

            # Record failure outcome
            self._record_plan_outcome(state, "failed", str(e))

        return state

    def _record_plan_outcome(
        self, state: AgentState, outcome: str, error_message: str = None
    ):
        """
        Record plan execution outcome for learning.

        Args:
            state: Agent state with plan_memory_id
            outcome: 'succeeded' or 'failed'
            error_message: Optional error message
        """
        plan_id = state.get("plan_memory_id")
        if not plan_id:
            return

        # Calculate execution time
        import time

        started_at = state.get("started_at")
        execution_time_ms = None
        if started_at:
            execution_time_ms = int((time.time() - started_at) * 1000)

        # Update plan memory
        if self.plan_memory:
            try:
                self.plan_memory.update_outcome(
                    plan_id=plan_id,
                    outcome=outcome,
                    execution_time_ms=execution_time_ms,
                    error_message=error_message,
                    step_results=state.get("execution_results"),
                )
                logger.info(f"Plan outcome recorded: {plan_id} -> {outcome}")
            except Exception as e:
                logger.warning(f"Failed to record plan outcome: {e}")

        # Update markdown log
        if self.plan_logger and execution_time_ms is not None:
            try:
                self.plan_logger.update_outcome(
                    plan_id=plan_id,
                    outcome=outcome,
                    execution_time_ms=execution_time_ms,
                    error_message=error_message,
                )
            except Exception as e:
                logger.warning(f"Failed to update plan markdown: {e}")

    def _error_state(self, state: AgentState) -> AgentState:
        """
        Error state: Handle errors and attempt recovery using the comprehensive error handling system.

        Args:
            state: Current agent state

        Returns:
            Updated state with error handling
        """
        logger.info(f"Entering ERROR state: {state.get('error')}")

        state["previous_phase"] = state.get("current_phase")
        state["current_phase"] = StatePhase.ERROR

        # Parse error string to create exception
        error_msg = state.get("error", "Unknown error")
        error_obj = Exception(error_msg)

        # Use the error handler to categorize and get recovery suggestions
        error_handler = ErrorHandler()
        error_context = error_handler.create_error_context(
            error_obj,
            details={
                "phase": state.get("previous_phase"),
                "plan_steps": state.get("plan_steps"),
                "selected_tools": state.get("selected_tools"),
            },
        )

        # Increment recovery attempts
        attempts = state.get("error_recovery_attempts", 0)
        max_attempts = state.get("max_recovery_attempts", 3)
        current_attempt = attempts + 1
        state["error_recovery_attempts"] = current_attempt

        # Get recovery strategy
        recovery_strategy = error_handler.recovery_strategies.get(
            error_context.category
        )

        if (
            current_attempt < max_attempts
            and recovery_strategy
            and recovery_strategy.can_retry
        ):
            logger.info(
                f"Attempting recovery ({attempts + 1}/{max_attempts}) "
                f"for {error_context.category.value} error"
            )

            # Add user-friendly error message with recovery suggestions
            recovery_msg = error_context.user_message
            if error_context.recovery_suggestions:
                recovery_msg += "\n\nSuggestions:\n" + "\n".join(
                    f"• {s}" for s in error_context.recovery_suggestions[:3]
                )

            state["messages"].append(
                SystemMessage(
                    content=f"⚠️ {recovery_msg}\n\nAttempting automatic recovery..."
                )
            )

            # Clear error for retry
            state["error"] = None
        else:
            # Max attempts reached or non-retryable error
            severity_emoji = {
                ErrorSeverity.LOW: "ℹ️",
                ErrorSeverity.MEDIUM: "⚠️",
                ErrorSeverity.HIGH: "❌",
                ErrorSeverity.CRITICAL: "🚨",
            }

            emoji = severity_emoji.get(error_context.severity, "❌")
            if current_attempt >= max_attempts:
                final_msg = (
                    f"{emoji} Failed after {current_attempt} attempts. "
                    f"{error_context.user_message}"
                )
            else:
                final_msg = f"{emoji} {error_context.user_message}"
            if error_context.recovery_suggestions:
                final_msg += "\n\nTo resolve this issue:\n" + "\n".join(
                    f"• {s}" for s in error_context.recovery_suggestions
                )

            logger.error(
                f"Error recovery failed - Category: {error_context.category.value}, "
                f"Severity: {error_context.severity.value}"
            )

            state["messages"].append(SystemMessage(content=final_msg))

        return state

    def route_by_memory_signal(self, state: AgentState) -> AgentState:
        """Inspect the top hypothesis card and set execution_mode / conflict_hint."""
        cards = state.get("hypothesis_cards") or []
        top_card = cards[0] if cards else {}
        priority = top_card.get("claim_memory_priority", "none")
        if priority == "conflict_resolution":
            state["execution_mode"] = "conflict_resolution"
            state["conflict_hint"] = str(top_card.get("claim_memory_reason") or "")
        elif state.get("execution_mode") == "conflict_resolution":
            state["conflict_hint"] = str(state.get("conflict_hint") or "")
        else:
            state["execution_mode"] = "standard"
            state["conflict_hint"] = ""
        return state

    def _route_from_plan(self, state: AgentState) -> Literal["execute", "error"]:
        """Route from plan state based on success/failure."""
        if state.get("error"):
            return "error"
        return "execute"

    def _route_from_execute(self, state: AgentState) -> Literal["review", "error"]:
        """Route from execute state based on success/failure."""
        if state.get("error"):
            return "error"
        return "review"

    def _route_from_review(
        self, state: AgentState
    ) -> Literal["complete", "plan", "error"]:
        """Route from review state based on review results."""
        if state.get("error"):
            return "error"
        if state.get("needs_revision"):
            return "plan"
        return "complete"

    def _route_from_error(self, state: AgentState) -> Literal["plan", "execute", "end"]:
        """Route from error state based on recovery attempts."""
        attempts = state.get("error_recovery_attempts", 0)
        max_attempts = state.get("max_recovery_attempts", 3)

        if attempts >= max_attempts:
            return "end"

        # Determine where to retry based on previous phase
        previous_phase = state.get("previous_phase")
        if previous_phase == StatePhase.EXECUTE:
            return "execute"

        # Default to retrying from plan
        return "plan"

    async def arun(
        self,
        query: str,
        thread_id: str | None = None,
        resume_checkpoint_id: str | None = None,
        **kwargs,
    ):
        """
        Run the state machine asynchronously.

        Args:
            query: User query to process
            thread_id: Thread ID for conversation (optional)
            **kwargs: Additional configuration

        Yields:
            State updates as the graph executes
        """
        if not thread_id:
            thread_id = str(uuid4())

        resume_id = resume_checkpoint_id or self.resume_checkpoint_id

        initial_state = {
            "messages": [HumanMessage(content=query)],
            "current_phase": StatePhase.INIT,
            "previous_phase": None,
            "plan": None,
            "plan_steps": [],
            "selected_tools": [],
            "tool_args": {},
            "execution_results": {},
            "review_feedback": None,
            "needs_revision": False,
            "error": None,
            "error_recovery_attempts": 0,
            "max_recovery_attempts": kwargs.get("max_recovery_attempts", 3),
            "thread_id": thread_id,
            "session_checkpoint_id": None,
            "hypothesis_cards": kwargs.get("hypothesis_cards", None),
            "execution_mode": kwargs.get("execution_mode", None),
            "conflict_hint": kwargs.get("conflict_hint", None),
        }

        config = {"configurable": {"thread_id": thread_id}}
        if resume_id:
            config["configurable"]["checkpoint_id"] = resume_id

        async for event in self.app.astream(initial_state, config):
            yield event

    def get_last_checkpoint_id(self, thread_id: str) -> str | None:
        """Return the latest checkpoint id for a thread if available."""
        if not self.checkpointer:
            return None

        try:
            storage = getattr(self.checkpointer, "storage", {})
            if thread_id not in storage or not storage[thread_id]:
                return None
            checkpoint_ns = next(iter(storage[thread_id].keys()))
            cfg = {
                "configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}
            }
            checkpoint_tuple = self.checkpointer.get_tuple(cfg)
            if checkpoint_tuple and checkpoint_tuple.config:
                return checkpoint_tuple.config["configurable"].get("checkpoint_id")
        except Exception:
            return None
        return None

    def run(self, query: str, thread_id: str | None = None, **kwargs):
        """
        Run the state machine synchronously.

        Args:
            query: User query to process
            thread_id: Thread ID for conversation (optional)
            **kwargs: Additional configuration

        Returns:
            Final state after execution
        """
        if not thread_id:
            thread_id = str(uuid4())

        initial_state = {
            "messages": [HumanMessage(content=query)],
            "current_phase": StatePhase.INIT,
            "previous_phase": None,
            "plan": None,
            "plan_steps": [],
            "selected_tools": [],
            "tool_args": {},
            "execution_results": {},
            "review_feedback": None,
            "needs_revision": False,
            "error": None,
            "error_recovery_attempts": 0,
            "max_recovery_attempts": kwargs.get("max_recovery_attempts", 3),
            "thread_id": thread_id,
            "session_checkpoint_id": None,
            "hypothesis_cards": kwargs.get("hypothesis_cards", None),
            "execution_mode": kwargs.get("execution_mode", None),
            "conflict_hint": kwargs.get("conflict_hint", None),
        }

        config = {"configurable": {"thread_id": thread_id}}

        result = self.app.invoke(initial_state, config)
        return result

    def _init_memory_system(self, memory_path=None):
        """
        Initialize the memory system for context injection.

        Args:
            memory_path: Path to memory directory
        """
        self.memory_store = None
        self.memory_selector = None
        self.derived_memory_store = None

        try:
            from brain_researcher.core.memory import MemorySelector, MemoryStore

            # Use provided path or default
            if memory_path is None:
                # Try to find memory directory relative to project root
                possible_paths = [
                    Path("memory/"),  # Current directory
                    Path(__file__).parents[4] / "memory",  # Project root
                    Path.home()
                    / "projects"
                    / "brain_researcher"
                    / "memory",  # Absolute fallback
                ]

                for path in possible_paths:
                    if path.exists():
                        memory_path = str(path)
                        break

            if memory_path and Path(memory_path).exists():
                self.memory_store = MemoryStore(memory_path)
                self.memory_selector = MemorySelector(self.memory_store)
                logger.info(
                    f"Memory system initialized with {len(self.memory_store.memories)} memories"
                )
            else:
                logger.info("Memory system not initialized (no memory directory found)")

        except ImportError:
            logger.warning("Memory system modules not available")
        try:
            from brain_researcher.config.run_artifacts import (
                get_mcp_run_root,
                get_mcp_run_roots_for_read,
            )
            from brain_researcher.services.memory import (
                MemoryStore as DerivedMemoryStore,
            )

            primary_run_root = Path(get_mcp_run_root()).expanduser().resolve()
            readable_roots = get_mcp_run_roots_for_read(primary_run_root)
            has_runtime_memory = any(
                (Path(root) / "memory" / "index" / "memory.sqlite3").exists()
                or (Path(root) / "memory" / "cards").exists()
                for root in readable_roots
            )
            if has_runtime_memory:
                self.derived_memory_store = DerivedMemoryStore(
                    run_root=primary_run_root
                )
                logger.info("Derived memory store initialized for planning retrieval")
            else:
                logger.info(
                    "Derived memory store not initialized (no runtime cards found)"
                )
        except Exception as exc:
            logger.warning(f"Failed to initialize derived memory store: {exc}")

    @staticmethod
    def _first_memory_line(values: Any) -> str:
        if not isinstance(values, list):
            return ""
        for raw in values:
            text = " ".join(str(raw or "").strip().split())
            if text:
                return text
        return ""

    def _format_derived_memories_as_house_rules(
        self, cards: list[dict[str, Any]]
    ) -> str:
        if not cards:
            return ""

        lines = ["[Runtime Memory - Prior Similar Runs]"]
        for card in cards[:3]:
            task = " ".join(str(card.get("task_description") or "").strip().split())
            if not task:
                continue
            status = (
                " ".join(str(card.get("status") or "").strip().split()) or "unknown"
            )
            fragments = [f"Similar run ({status}): {task}"]

            worked = self._first_memory_line(card.get("what_worked"))
            if worked:
                fragments.append(f"reuse {worked}")

            failed = self._first_memory_line(card.get("what_failed"))
            if failed:
                fragments.append(f"avoid {failed}")

            hint = self._first_memory_line(card.get("next_time_hints"))
            if hint:
                fragments.append(f"next {hint}")

            if len(fragments) == 1:
                output_summary = " ".join(
                    str(card.get("output_summary") or "").strip().split()
                )
                if output_summary:
                    fragments.append(f"outcome {output_summary}")

            lines.append(f"- {'; '.join(fragments[:4])}")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _select_derived_memory_cards(
        self, cards: list[dict[str, Any]], limit: int = 3
    ) -> list[dict[str, Any]]:
        if not cards:
            return []

        status_ranks = {
            "success": 0,
            "partial": 1,
            "interrupted": 2,
            "failed": 3,
        }

        def _sort_key(card: dict[str, Any]) -> tuple[int, int, int, float, str]:
            task = " ".join(str(card.get("task_description") or "").strip().split())
            normalized_task = task.lower()
            status = " ".join(str(card.get("status") or "").strip().split()).lower()
            score = float(card.get("score") or 0.0)
            lesson_count = sum(
                1
                for key in ("what_worked", "what_failed", "next_time_hints")
                if self._first_memory_line(card.get(key))
            )
            generic_penalty = int(
                normalized_task.startswith("run br_")
                or "via pipeline_execute" in normalized_task
            )
            return (
                status_ranks.get(status, 4),
                generic_penalty,
                -lesson_count,
                -score,
                normalized_task,
            )

        if any(
            isinstance(card, dict) and card.get("score") is not None for card in cards
        ):
            cards = [
                card
                for card in cards
                if isinstance(card, dict) and float(card.get("score") or 0.0) > 0.0
            ]
            if not cards:
                return []

        ranked = sorted(
            (card for card in cards if isinstance(card, dict)),
            key=_sort_key,
        )
        selected = ranked[: max(1, int(limit))]
        return selected or list(cards[: max(1, int(limit))])

    def _get_relevant_memories(self, query: str, state: AgentState) -> str:
        """
        Get relevant memories for the current query and format as house rules.

        Args:
            query: User query
            state: Current agent state

        Returns:
            Formatted house rules string
        """
        rule_blocks: list[str] = []

        if self.memory_selector:
            try:
                # Extract context from state
                context = self.memory_selector.get_context_from_state(state)

                # Select relevant memories
                memories = self.memory_selector.select_memories(
                    task=query,
                    context=context,
                    k=5,  # Top 5 memories
                    min_confidence=0.3,
                )

                if memories:
                    rule_blocks.append(
                        self.memory_selector.format_as_house_rules(memories)
                    )
                    logger.info(
                        "Injected %s project memories as house rules", len(memories)
                    )
            except Exception as exc:
                logger.warning(f"Error getting project memories: {exc}")

        if self.derived_memory_store:
            try:
                search = self.derived_memory_store.search(
                    query=query,
                    card_type="episodic_run_memory",
                    limit=8,
                )
                cards = self._select_derived_memory_cards(
                    list(search.get("cards") or []),
                    limit=3,
                )
                derived_rules = self._format_derived_memories_as_house_rules(cards)
                if derived_rules:
                    rule_blocks.append(derived_rules)
                    logger.info(
                        "Injected %s derived episodic memories into planning",
                        len(cards),
                    )
            except Exception as exc:
                logger.warning("Error getting derived episodic memories: %s", exc)

            try:
                claim_search = self.derived_memory_store.search(
                    query=query,
                    card_type="claim_memory",
                    filters={"status": "active"},
                    limit=6,
                )
                claim_cards = list(claim_search.get("cards") or [])
                claim_rules = _format_claim_memories_as_house_rules(claim_cards)
                if claim_rules:
                    rule_blocks.append(claim_rules)
                    logger.info(
                        "Injected %s claim memories into planning", len(claim_cards)
                    )
            except Exception as exc:
                logger.warning("Error getting claim memories: %s", exc)

        return "\n\n".join(block for block in rule_blocks if block)

    def invalidate_cache(
        self,
        pattern: str | None = None,
        tags: set | None = None,
        key_type: CacheKeyType | None = None,
    ) -> int:
        """
        Invalidate cache entries.

        Args:
            pattern: Redis key pattern to match
            tags: Tags to invalidate
            key_type: Specific key type to invalidate

        Returns:
            Number of keys invalidated
        """
        return self.cache_manager.invalidate(
            pattern=pattern, tags=tags, key_type=key_type
        )

    def warm_cache(self, common_queries: list[str]):
        """
        Warm the cache with common queries.

        Args:
            common_queries: List of common queries to pre-compute
        """
        logger.info(f"Warming cache with {len(common_queries)} queries")

        for query in common_queries:
            try:
                # Use synchronous run for cache warming
                self.run(query, thread_id=f"warmup_{hash(query)}")
            except Exception as e:
                logger.warning(
                    f"Failed to warm cache for query: {query[:50]}... Error: {e}"
                )

        logger.info("Cache warming completed")

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return self.cache_manager.get_stats()

    async def shutdown(self):
        """Shutdown the state machine and cleanup resources."""
        logger.info("Shutting down core state machine")

        # Shutdown parallel execution components
        if self.parallel_orchestrator:
            await self.parallel_orchestrator.shutdown()

        logger.info("Core state machine shutdown complete")


def get_core_graph():
    """
    Factory function to get the core state machine graph.

    Returns:
        Compiled LangGraph application
    """
    machine = CoreStateMachine()
    return machine.app
