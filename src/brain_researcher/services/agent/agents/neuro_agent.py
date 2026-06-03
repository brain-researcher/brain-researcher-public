"""
Main neuroscience research agent using LangGraph.

Following Biomni's minimal state pattern with clean workflow design.
"""

import logging
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, StateGraph

from brain_researcher.services.agent.states.base import NeuroAgentState
from brain_researcher.services.tools.fmri_tools import FMRITools
from brain_researcher.services.tools.br_kg_tools import BRKGTools
from brain_researcher.services.tools.statistical_critic import StatisticalCriticTool
from brain_researcher.services.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class NeuroAgent:
    """
    Main neuroscience research agent with StateGraph workflow.

    Following Biomni's pattern:
    - Minimal state management
    - Clear workflow with conditional routing
    - Dynamic tool selection
    """

    def __init__(self, tool_registry: ToolRegistry = None):
        """
        Initialize the agent.

        Args:
            tool_registry: Optional tool registry, creates new one if not provided
        """
        self.tool_registry = tool_registry or ToolRegistry(auto_discover=True)
        self.graph = self._build_graph()

        # Tool instances for direct access
        self.fmri_tools = FMRITools()
        self.br_kg_tools = BRKGTools()
        self.critic_tool = StatisticalCriticTool()


    def _build_graph(self) -> StateGraph:
        """Build the agent workflow graph."""
        workflow = StateGraph(NeuroAgentState)

        # Add nodes
        workflow.add_node("understand", self.understand_query)
        workflow.add_node("select_tools", self.select_tools)
        workflow.add_node("execute", self.execute_tools)
        workflow.add_node("validate", self.validate_statistics)  # NEW: Critic
        workflow.add_node("synthesize", self.synthesize_results)
        workflow.add_node("memorize", self.memorize_finding)     # NEW: Memory
        workflow.add_node("handle_error", self.handle_error)

        # Set entry point
        workflow.set_entry_point("understand")

        # Add edges
        workflow.add_edge("understand", "select_tools")
        workflow.add_edge("select_tools", "execute")

        # Conditional edges from execution
        workflow.add_conditional_edges(
            "execute",
            self.check_execution_result,
            # If tools succeeded, we validate. If failed, handle error/retry.
            {"success": "validate", "error": "handle_error", "retry": "select_tools"},
        )

        # Conditional edge from validator
        workflow.add_conditional_edges(
            "validate",
            self.check_validation_result,
            {"valid": "synthesize", "invalid": "handle_error"}
        )

        # Synthesis -> Memorize -> End
        workflow.add_edge("synthesize", "memorize")
        workflow.add_edge("memorize", END)
        workflow.add_edge("handle_error", END)

        return workflow.compile()


    def understand_query(self, state: NeuroAgentState) -> NeuroAgentState:
        """
        Understand the user's query and set the phase.

        This is where we would use an LLM to parse the query in production.
        For now, using simple pattern matching.
        """
        logger.info("Understanding query...")

        # Get last user message
        last_message = state["messages"][-1]
        if not isinstance(last_message, HumanMessage):
            state["error"] = "No user message found"
            return state

        query = last_message.content.lower()

        # Simple intent detection
        analysis_keywords = ["analyze", "analysis", "glm", "contrast", "activation"]
        search_keywords = ["search", "find", "literature", "papers", "concepts"]
        comparison_keywords = ["compare", "similarity", "difference", "versus"]

        # Determine primary intent
        intents = []
        if any(keyword in query for keyword in analysis_keywords):
            intents.append("analysis")
        if any(keyword in query for keyword in search_keywords):
            intents.append("search")
        if any(keyword in query for keyword in comparison_keywords):
            intents.append("comparison")

        # Add understanding to messages
        understanding = f"I understand you want to: {', '.join(intents) if intents else 'perform research'}"
        state["messages"].append(AIMessage(content=understanding))

        # Update phase
        state["current_phase"] = "tool_selection"

        return state

    def select_tools(self, state: NeuroAgentState) -> NeuroAgentState:
        """Select appropriate tools based on the query."""
        logger.info("Selecting tools...")

        # Get query from messages
        query = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                query = msg.content
                break

        # Use tool registry to find relevant tools
        selected_tools = self.tool_registry.get_tools_for_task(query, k=3)

        # Convert to tool names
        tool_names = [tool.get_tool_name() for tool in selected_tools]

        # If no tools selected, use defaults based on keywords
        if not tool_names:
            query_lower = query.lower()
            if "glm" in query_lower or "contrast" in query_lower:
                tool_names = ["glm_analysis"]
            elif "concept" in query_lower or "literature" in query_lower:
                tool_names = ["find_related_concepts"]
            elif any(
                task in query_lower
                for task in ["n-back", "n back", "task", "finger tapping", "face"]
            ):
                tool_names = ["task_to_concept_mapping"]
            elif "what is" in query_lower or "explain" in query_lower:
                tool_names = ["find_related_concepts", "task_to_concept_mapping"]
            else:
                tool_names = ["glm_analysis"]  # Default

        state["selected_tools"] = tool_names

        # Add message about tool selection
        tools_msg = f"Selected tools: {', '.join(tool_names)}"
        state["messages"].append(AIMessage(content=tools_msg))

        # Update phase
        state["current_phase"] = "execution"

        # Prepare tool arguments (in production, would use LLM)
        state["tool_args"] = self._prepare_tool_args(query, tool_names)

        return state

    def _prepare_tool_args(
        self, query: str, tool_names: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Prepare arguments for selected tools."""
        tool_args = {}

        # Extract common patterns
        import re

        # Dataset pattern
        dataset_match = re.search(r"ds\d{6}", query)
        dataset_id = dataset_match.group() if dataset_match else "ds000001"

        # Coordinate pattern
        coord_pattern = (
            r"\[?\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\]?"
        )
        coord_matches = re.findall(coord_pattern, query)
        coordinates = [[float(x), float(y), float(z)] for x, y, z in coord_matches]

        # Prepare args for each tool
        for tool_name in tool_names:
            if tool_name == "glm_analysis":
                task_name = None
                query_lower = query.lower()
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
                tool_args[tool_name] = {
                    "dataset_id": dataset_id,
                    "contrasts": {"task_vs_baseline": [1, -1]},  # Default contrast
                    "threshold": 3.1,
                }
                if task_name:
                    tool_args[tool_name]["task"] = task_name
                else:
                    tool_args[tool_name]["allow_mock"] = True
            elif tool_name == "find_related_concepts":
                # Extract concept name
                concepts = ["motor cortex"]  # Default
                if "visual" in query.lower():
                    concepts = ["visual cortex"]
                elif "memory" in query.lower():
                    concepts = ["memory"]

                tool_args[tool_name] = {"concept": concepts[0], "depth": 2, "limit": 5}
            elif tool_name == "coordinate_to_concept":
                tool_args[tool_name] = {
                    "coordinates": coordinates if coordinates else [[-42, -22, 54]],
                    "radius": 10.0,
                    "top_k": 5,
                }
            elif tool_name == "concept_literature_search":
                tool_args[tool_name] = {
                    "concepts": ["motor cortex", "movement"],
                    "max_results": 10,
                }
            elif tool_name == "task_to_concept_mapping":
                # Extract task name from query
                task_name = "n-back"  # Default
                query_lower = query.lower()
                if "n back" in query_lower or "n-back" in query_lower:
                    task_name = "n-back"
                elif "finger tapping" in query_lower:
                    task_name = "finger tapping"
                elif "face" in query_lower:
                    task_name = "face viewing"
                elif "motor" in query_lower:
                    task_name = "motor"
                elif "memory" in query_lower:
                    task_name = "memory"
                elif "attention" in query_lower:
                    task_name = "attention"

                tool_args[tool_name] = {
                    "task_name": task_name,
                    "include_synonyms": True,
                }
            else:
                # For other tools, provide minimal required args
                if tool_name == "find_related_concepts":
                    tool_args[tool_name] = {"concept": "motor", "depth": 2, "limit": 10}
                elif tool_name == "coordinate_to_concept":
                    tool_args[tool_name] = {
                        "coordinates": [[-42, -22, 54]],
                        "radius": 10.0,
                    }
                elif tool_name == "concept_literature_search":
                    tool_args[tool_name] = {"concepts": ["motor"], "max_results": 10}
                else:
                    tool_args[tool_name] = {}

        return tool_args

    def execute_tools(self, state: NeuroAgentState) -> NeuroAgentState:
        """Execute selected tools with prepared arguments."""
        logger.info(f"Executing tools: {state['selected_tools']}")

        results = {}
        tool_args = state.get("tool_args", {})

        for tool_name in state["selected_tools"]:
            try:
                # Get tool from registry
                tool = self.tool_registry.get_tool(tool_name)
                if not tool:
                    results[tool_name] = {
                        "status": "error",
                        "error": f"Tool {tool_name} not found",
                    }
                    continue

                # Get arguments
                args = tool_args.get(tool_name, {})

                # Execute tool
                logger.info(f"Executing {tool_name} with args: {args}")
                logger.debug(f"Tool instance: {tool.__class__.__name__}")

                result = tool.run(**args)

                logger.info(
                    f"Tool {tool_name} returned: status={result.get('status')}, "
                    f"has_data={bool(result.get('data'))}, "
                    f"error={result.get('error', 'None')}"
                )
                logger.debug(f"Full result from {tool_name}: {result}")

                results[tool_name] = result

            except Exception as e:
                logger.error(f"Error executing {tool_name}: {e}")
                results[tool_name] = {"status": "error", "error": str(e)}

        state["results"] = results

        # Check if any tools succeeded
        any_success = any(r.get("status") == "success" for r in results.values())
        if not any_success:
            state["error"] = "All tools failed"

        # Update phase
        state["current_phase"] = "synthesis" if any_success else "error"

        return state

    def check_execution_result(self, state: NeuroAgentState) -> Literal["success", "error", "retry"]:
        """Determine next step based on execution results."""
        results = state.get("results", {})
        if not results:
            return "error"

        # Check for immediate critical errors or retries
        # For now, simple logic: if any success, proceed. If all failed, error.
        any_success = any(r.get("status") == "success" for r in results.values())

        if any_success:
            return "success"

        return "error"

    def validate_statistics(self, state: NeuroAgentState) -> NeuroAgentState:
        """Run the Statistical Critic on analysis results."""
        logger.info("Validating statistics...")

        results = state.get("results", {})

        # If no analysis was done, we essentially skip validation
        # But we pass through this node to keep the graph simple.

        # Check if we have GLM results
        if "glm_analysis" in results and results["glm_analysis"].get("status") == "success":
            glm_data = results["glm_analysis"].get("data", {})
            # Mock extracting residuals/design matrix if not fully populated in this proto
            # In a real scenario, we'd pull these from the output files or return payload

            # Running the critic
            # For demonstration, we assume valid interactions if data is present
            critic_result = self.critic_tool.run(
                residuals=glm_data.get("residuals"), # May be None
                design_matrix=glm_data.get("design_matrix") # May be None
            )

            state["validation_report"] = critic_result.get("data", {})
            if not state["validation_report"].get("valid", True):
                state["error"] = f"Statistical Validation Failed: {state['validation_report'].get('issues')}"
        else:
            state["validation_report"] = {"valid": True, "skipped": True}

        return state

    def check_validation_result(self, state: NeuroAgentState) -> Literal["valid", "invalid"]:
        """Check if validation passed."""
        report = state.get("validation_report", {})
        if report.get("valid", True):
            return "valid"
        return "invalid"

    def synthesize_results(self, state: NeuroAgentState) -> NeuroAgentState:
        """Synthesize results from multiple tools."""
        logger.info("Synthesizing results...")

        results = state.get("results", {})
        synthesis = {
            "summary": "",
            "key_findings": [],
            "recommendations": [],
            "errors": [],
        }

        # Process each tool's results
        for tool_name, result in results.items():
            if result.get("status") != "success":
                # Include error information
                error_msg = result.get("error", "Unknown error")
                synthesis["errors"].append(f"{tool_name}: {error_msg}")
                continue

            data = result.get("data", {})

            # Extract key information based on tool type
            if tool_name == "glm_analysis":
                synthesis["key_findings"].append(
                    f"GLM analysis completed for {data.get('dataset_id', 'unknown dataset')}"
                )
                if "peak_coordinates" in data:
                    synthesis["key_findings"].append(
                        f"Found {len(data['peak_coordinates'])} activation peaks"
                    )

            elif tool_name == "find_related_concepts":
                concepts = data.get("related_concepts", [])
                if concepts:
                    concept_names = [c["concept"] for c in concepts[:3]]
                    synthesis["key_findings"].append(
                        f"Related concepts: {', '.join(concept_names)}"
                    )

            elif tool_name == "coordinate_to_concept":
                mappings = data.get("coordinate_mappings", [])
                if mappings:
                    regions = set(m["region"] for m in mappings)
                    synthesis["key_findings"].append(
                        f"Brain regions identified: {', '.join(regions)}"
                    )

            elif tool_name == "concept_literature_search":
                papers = data.get("papers", [])
                synthesis["key_findings"].append(f"Found {len(papers)} relevant papers")

            elif tool_name == "task_to_concept_mapping":
                task_name = data.get("task_name", "")
                concepts = data.get("concepts", [])
                synonyms = data.get("synonyms", [])

                if task_name and concepts:
                    synthesis["key_findings"].append(
                        f"The {task_name} task is associated with: {', '.join(concepts)}"
                    )
                    if synonyms:
                        synthesis["key_findings"].append(
                            f"Also known as: {', '.join(synonyms)}"
                        )

        # Create summary based on query and results
        query = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                query = msg.content.lower()
                break

        if synthesis["key_findings"]:
            if "what is" in query:
                synthesis["summary"] = " ".join(synthesis["key_findings"])
            else:
                synthesis["summary"] = "Analysis complete. " + " ".join(
                    synthesis["key_findings"]
                )
        elif synthesis["errors"]:
            # If only errors, report them
            synthesis["summary"] = "Analysis encountered errors. " + " ".join(
                synthesis["errors"][:2]
            )
        else:
            synthesis["summary"] = "Analysis complete but no significant findings."

        # Add recommendations
        if "glm_analysis" in results and "coordinate_to_concept" not in results:
            synthesis["recommendations"].append(
                "Consider mapping peak coordinates to cognitive concepts"
            )

        if (
            "find_related_concepts" in results
            and "concept_literature_search" not in results
        ):
            synthesis["recommendations"].append(
                "Consider searching literature for the identified concepts"
            )

        state["synthesis"] = synthesis

        # Add synthesis message
        synthesis_msg = synthesis["summary"]
        if synthesis["recommendations"]:
            synthesis_msg += "\n\nRecommendations:\n" + "\n".join(
                f"- {rec}" for rec in synthesis["recommendations"]
            )

        state["messages"].append(AIMessage(content=synthesis_msg))
        state["current_phase"] = "complete"

        return state

    def memorize_finding(self, state: NeuroAgentState) -> NeuroAgentState:
        """Write key findings back to BR-KG."""
        logger.info("Memorizing findings...")

        synthesis = state.get("synthesis", {})
        summary = synthesis.get("summary")
        if not summary:
            return state

        # Use simple heuristic to decide what to write
        # In production, LLM would parse "findings" vs "chat"

        results = state.get("results", {})
        validation_report = state.get("validation_report", {}) or {}
        statistical_validation = bool(validation_report.get("valid", True)) and not bool(
            validation_report.get("skipped", False)
        )

        # Evidence count from any literature-style tool outputs
        evidence_count = 0
        for result in results.values():
            if result.get("status") != "success":
                continue
            data = result.get("data", {}) or {}
            if not isinstance(data, dict):
                continue
            for key in ("papers", "articles", "references", "citations"):
                items = data.get(key)
                if isinstance(items, list):
                    evidence_count += len(items)

        # Infer dataset + concepts when available
        dataset_id = None
        if "glm_analysis" in results and results["glm_analysis"].get("status") == "success":
            dataset_id = results["glm_analysis"].get("data", {}).get("dataset_id")

        concepts = None
        if "find_related_concepts" in results and results["find_related_concepts"].get("status") == "success":
            related = results["find_related_concepts"].get("data", {}).get("related_concepts", [])
            if related:
                concepts = [c.get("concept") for c in related if isinstance(c, dict) and c.get("concept")]

        confidence = 0.5
        try:
            score_result = self.br_kg_tools.score_confidence.run(
                evidence_count=evidence_count,
                statistical_validation=statistical_validation,
                contradictions=0,
            )
            confidence = score_result.get("data", {}).get("score", confidence)
        except Exception as e:
            logger.warning(f"Confidence scoring failed: {e}")

        try:
             # Just memorizing the topline summary for now
             self.br_kg_tools.add_finding.run(
                 description=summary,
                 source_tool="neuro_agent_v1",
                 confidence=confidence,
                 dataset_id=dataset_id,
                 concepts=concepts,
                 evidence={
                     "validation_report": validation_report,
                     "evidence_count": evidence_count,
                     "tools_used": list(results.keys()),
                 },
             )
        except Exception as e:
            logger.warning(f"Failed to memorize: {e}")

        return state

    def handle_error(self, state: NeuroAgentState) -> NeuroAgentState:
        """Handle errors gracefully."""
        logger.error(f"Handling error: {state.get('error')}")

        error_msg = f"I encountered an error: {state.get('error', 'Unknown error')}"
        error_msg += "\n\nWould you like me to try a different approach?"

        state["messages"].append(AIMessage(content=error_msg))
        state["current_phase"] = "error_handled"

        return state

    def run(self, query: str, initial_state: dict[str, Any] = None) -> dict[str, Any]:
        """
        Run the agent with a query.

        Args:
            query: The user's research query
            initial_state: Optional initial state

        Returns:
            Final state after workflow completion
        """
        # Create initial state if not provided
        if initial_state is None:
            initial_state = NeuroAgentState(
                messages=[HumanMessage(content=query)],
                current_phase="init",
                selected_tools=[],
            )

        # Run workflow
        final_state = self.graph.invoke(initial_state)

        return final_state

    def process_instruction_with_llm(self, instruction: str) -> dict[str, Any]:
        """
        CLI compatibility wrapper for run() method.

        Converts the LangGraph agent's complex state output to the simple
        format expected by the CLI.

        Args:
            instruction: Natural language instruction from user

        Returns:
            Dictionary with 'tool', 'params', and 'reasoning' keys
        """
        try:
            # Run the full agent workflow
            final_state = self.run(instruction)

            # Extract first tool and convert to CLI format
            selected_tools = final_state.get("selected_tools", [])
            if not selected_tools:
                return {
                    "tool": "error",
                    "params": {"message": "No suitable tool found for this request"},
                    "reasoning": "Could not identify an appropriate tool for the given instruction",
                }

            # Map internal tool names to CLI expectations
            tool_mapping = {
                "glm_analysis": "statistical_analysis",
                "find_related_concepts": "literature_retrieval",
                "coordinate_to_concept": "literature_retrieval",
                "compare_concepts": "literature_retrieval",
                "dataset_analysis": "nilearn_analysis",
                "fmri_analysis": "nilearn_analysis",
                # Add more mappings as needed
            }

            # Get the first selected tool
            tool_name = selected_tools[0]
            cli_tool_name = tool_mapping.get(tool_name, tool_name)

            # Map to expected CLI tool names if not in mapping
            if cli_tool_name not in [
                "nilearn_analysis",
                "statistical_analysis",
                "literature_retrieval",
                "fmriprep_command_generation",
            ]:
                # Default to nilearn_analysis for unknown tools
                cli_tool_name = "nilearn_analysis"

            # Extract parameters from tool_args
            tool_args = final_state.get("tool_args", {})
            params = tool_args.get(tool_name, {})

            # Extract reasoning from messages or phase information
            reasoning = f"Selected {tool_name} based on query analysis"
            messages = final_state.get("messages", [])

            # Try to find a more detailed reasoning from AI messages
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    content = msg.content
                    if "understand" in content.lower() or "select" in content.lower():
                        reasoning = content
                        break

            # Get current phase for additional context
            current_phase = final_state.get("current_phase", "unknown")
            if current_phase == "complete":
                reasoning = f"{reasoning} (Analysis completed successfully)"
            elif current_phase == "error_handled":
                reasoning = f"{reasoning} (Encountered error: {final_state.get('error', 'unknown')})"

            return {"tool": cli_tool_name, "params": params, "reasoning": reasoning}

        except Exception as e:
            logger.error(f"Error in process_instruction_with_llm: {e}")
            return {
                "tool": "error",
                "params": {"message": str(e)},
                "reasoning": f"Error processing instruction: {e}",
            }
