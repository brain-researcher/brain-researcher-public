"""
Brain Researcher LangGraph Implementation

This module defines the agent graph using LangGraph for better state management,
checkpointing, and scalability.
"""

import logging
from collections.abc import Sequence
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """State definition for the Brain Researcher agent."""

    messages: Annotated[Sequence[BaseMessage], "The messages in the conversation"]
    selected_tools: list[str]
    tool_results: dict[str, Any]
    synthesis: dict[str, Any]
    current_phase: str


class BrainResearcherGraph:
    """Brain Researcher agent implemented with LangGraph."""

    def __init__(self):
        """Initialize the Brain Researcher graph."""
        self.tool_registry = ToolRegistry()

        # Initialize LLM using the configured LLM factory
        try:
            from brain_researcher.services.agent.llm import get_llm
            self.llm = get_llm()
            logger.info("Initialized LLM from configured factory")
        except Exception as e:
            logger.warning(f"Failed to initialize LLM from factory: {e}")
            # Fallback to a mock LLM for testing
            from langchain_core.language_models import FakeListLLM

            self.llm = FakeListLLM(
                responses=["Understanding query", "Selecting tools", "Processing"]
            )

        self.tools = [
            tool.as_langchain_tool() for tool in self.tool_registry.get_all_tools()
        ]
        self.tool_node = ToolNode(self.tools)

        # Build the graph
        self.graph = self._build_graph()

        # Add memory checkpointer
        self.checkpointer = MemorySaver()
        self.app = self.graph.compile(checkpointer=self.checkpointer)

    def _build_graph(self) -> StateGraph:
        """Build the agent graph."""
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("understand_query", self._understand_query)
        workflow.add_node("select_tools", self._select_tools)
        workflow.add_node("execute_tools", self._execute_tools)
        workflow.add_node("synthesize", self._synthesize_results)

        # Add edges
        workflow.set_entry_point("understand_query")
        workflow.add_edge("understand_query", "select_tools")
        workflow.add_edge("select_tools", "execute_tools")
        workflow.add_edge("execute_tools", "synthesize")
        workflow.add_edge("synthesize", END)

        return workflow

    def _understand_query(self, state: AgentState) -> AgentState:
        """Understand the user's query and extract intent."""
        logger.info("Understanding query...")

        messages = state["messages"]
        last_message = messages[-1].content if messages else ""

        from brain_researcher.services.agent.llm import get_system_prompt

        understanding_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    get_system_prompt("neuroscience_expert") + """

            For this step, analyze the user's query and identify:
            1. The main research question
            2. The type of analysis needed (fMRI, knowledge graph, literature)
            3. Any specific datasets, brain regions, or concepts mentioned

            Be concise and focus on actionable insights.""",
                ),
                ("human", "{query}"),
            ]
        )

        chain = understanding_prompt | self.llm
        response = chain.invoke({"query": last_message})

        # Add AI message with understanding
        state["messages"].append(AIMessage(content=response.content))
        state["current_phase"] = "tool_selection"

        return state

    def _select_tools(self, state: AgentState) -> AgentState:
        """Select appropriate tools based on the query understanding."""
        logger.info("Selecting tools...")

        # Get available tool descriptions
        tool_descriptions = "\n".join(
            [
                f"- {tool.get_tool_name()}: {tool.get_tool_description()}"
                for tool in self.tool_registry.get_all_tools()
            ]
        )

        selection_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    f"""Based on the query analysis, select the most appropriate tools.

            Available tools:
            {tool_descriptions}

            Return a JSON list of tool names to use. Select 1-3 most relevant tools.
            Consider the order of execution - some tools may depend on outputs from others.""",
                ),
                ("human", "Query analysis: {analysis}"),
            ]
        )

        chain = selection_prompt | self.llm
        analysis = state["messages"][-1].content
        response = chain.invoke({"analysis": analysis})

        # Parse tool selection
        import json

        try:
            selected_tools = json.loads(response.content)
            state["selected_tools"] = selected_tools
        except:
            # Fallback to simple parsing
            state["selected_tools"] = [
                "task_to_concept_mapping",
                "find_related_concepts",
            ]

        state["current_phase"] = "tool_execution"
        logger.info(f"Selected tools: {state['selected_tools']}")

        return state

    def _execute_tools(self, state: AgentState) -> AgentState:
        """Execute the selected tools."""
        logger.info("Executing tools...")

        tool_results = {}
        messages = state["messages"]

        for tool_name in state["selected_tools"]:
            tool = self.tool_registry.get_tool(tool_name)
            if not tool:
                logger.warning(f"Tool {tool_name} not found")
                continue

            # Prepare tool arguments based on query
            args = self._prepare_tool_args(
                tool_name, messages[-1].content if messages else ""
            )

            try:
                # Create tool call message
                tool_call_id = str(uuid4())
                tool_message = AIMessage(
                    content="",
                    tool_calls=[{"id": tool_call_id, "name": tool_name, "args": args}],
                )
                state["messages"].append(tool_message)

                # Execute tool
                result = tool.run(**args)
                tool_results[tool_name] = result

                # Add tool result message
                tool_result_message = ToolMessage(
                    content=str(result), tool_call_id=tool_call_id
                )
                state["messages"].append(tool_result_message)

            except Exception as e:
                logger.error(f"Error executing {tool_name}: {e}")
                tool_results[tool_name] = {"status": "error", "error": str(e)}

        state["tool_results"] = tool_results
        state["current_phase"] = "synthesis"

        return state

    def _synthesize_results(self, state: AgentState) -> AgentState:
        """Synthesize results from all tools into a coherent response."""
        logger.info("Synthesizing results...")

        synthesis_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a neuroscience research assistant.
            Synthesize the tool results into a clear, informative response.

            Guidelines:
            - Highlight key findings
            - Connect results across different tools
            - Provide scientific context
            - Suggest next steps if appropriate
            - Be concise but thorough""",
                ),
                ("human", "Tool results: {results}\n\nOriginal query: {query}"),
            ]
        )

        chain = synthesis_prompt | self.llm

        original_query = next(
            (msg.content for msg in state["messages"] if isinstance(msg, HumanMessage)),
            "",
        )

        response = chain.invoke(
            {"results": state["tool_results"], "query": original_query}
        )

        # Add final synthesis
        state["messages"].append(AIMessage(content=response.content))
        state["synthesis"] = {
            "summary": response.content,
            "tool_results": state["tool_results"],
            "selected_tools": state["selected_tools"],
        }
        state["current_phase"] = "completed"

        return state

    def _prepare_tool_args(self, tool_name: str, query: str) -> dict:
        """Prepare arguments for tool execution based on the query."""
        # This is a simplified version - in production, use LLM to extract args
        args = {}

        if tool_name == "task_to_concept_mapping":
            # Extract task name from query
            if "n-back" in query.lower():
                args["task_name"] = "n-back"
            elif "motor" in query.lower():
                args["task_name"] = "motor"
            else:
                args["task_name"] = "cognitive task"

        elif tool_name == "find_related_concepts":
            # Extract concept from query
            if "motor" in query.lower():
                args["concept"] = "motor cortex"
            elif "memory" in query.lower():
                args["concept"] = "working memory"
            else:
                args["concept"] = "brain"
            args["depth"] = 2
            args["limit"] = 10

        elif tool_name == "glm_analysis":
            # Extract dataset ID
            import re

            dataset_match = re.search(r"ds\d+", query)
            args["dataset_id"] = dataset_match.group() if dataset_match else "ds000001"
            args["contrasts"] = {"task_vs_baseline": [1, -1]}
            query_lower = query.lower()
            task_name = None
            if "n back" in query_lower or "n-back" in query_lower:
                task_name = "n-back"
            elif "finger tapping" in query_lower:
                task_name = "finger tapping"
            elif "face" in query_lower:
                task_name = "face"
            elif "motor" in query_lower:
                task_name = "motor"
            elif "memory" in query_lower:
                task_name = "memory"
            elif "attention" in query_lower:
                task_name = "attention"
            if task_name:
                args["task"] = task_name
            else:
                args["allow_mock"] = True

        return args

    async def arun(self, query: str, thread_id: str = None, resume_checkpoint_id: str | None = None):
        """Run the agent asynchronously with optional checkpoint resume."""
        if not thread_id:
            thread_id = str(uuid4())

        initial_state = {
            "messages": [HumanMessage(content=query)],
            "selected_tools": [],
            "tool_results": {},
            "synthesis": {},
            "current_phase": "understanding",
        }

        config = {"configurable": {"thread_id": thread_id}}
        if resume_checkpoint_id:
            config["configurable"]["checkpoint_id"] = resume_checkpoint_id

        async for event in self.app.astream(initial_state, config):
            yield event

    def _get_last_checkpoint_id(self, thread_id: str) -> str | None:
        """Return the latest checkpoint id for a thread if present."""
        try:
            storage = getattr(self.checkpointer, "storage", {})
            if thread_id not in storage or not storage[thread_id]:
                return None
            checkpoint_ns = next(iter(storage[thread_id].keys()))
            cfg = {"configurable": {"thread_id": thread_id, "checkpoint_ns": checkpoint_ns}}
            ck = self.checkpointer.get_tuple(cfg)
            if ck and ck.config:
                return ck.config["configurable"].get("checkpoint_id")
        except Exception:
            return None
        return None

    def run(self, query: str, thread_id: str = None, resume_checkpoint_id: str | None = None):
        """Run the agent synchronously with optional checkpoint resume."""
        if not thread_id:
            thread_id = str(uuid4())

        initial_state = {
            "messages": [HumanMessage(content=query)],
            "selected_tools": [],
            "tool_results": {},
            "synthesis": {},
            "current_phase": "understanding",
        }

        config = {"configurable": {"thread_id": thread_id}}
        if resume_checkpoint_id:
            config["configurable"]["checkpoint_id"] = resume_checkpoint_id

        result = self.app.invoke(initial_state, config)
        # Surface the latest checkpoint id to callers for resume support.
        checkpoint_id = self._get_last_checkpoint_id(thread_id)
        if isinstance(result, dict):
            result["checkpoint_id"] = checkpoint_id
        return result


# Create the graph instance when needed
def get_graph():
    """Get or create the graph instance."""
    return BrainResearcherGraph().app
