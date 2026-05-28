"""
Enhanced Agent Service Integration for LangGraph State Machine

This module provides comprehensive integration of all advanced features:
- Enhanced tool registry with parameter inference
- Workflow composition and execution
- Advanced evidence collection and aggregation
- Error recovery with checkpoint/restart
- Performance monitoring and optimization

Integrates seamlessly with the existing LangGraph CoreStateMachine.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from brain_researcher.services.agent.graph import CoreStateMachine, AgentState
from brain_researcher.services.tools.enhanced_registry import EnhancedToolRegistry
from brain_researcher.services.agent.logging.run_recorder import RunRecorder
from brain_researcher.services.agent.workflow_composer import (
    WorkflowComposer,
    WorkflowExecutor,
    create_workflow_system,
)
from brain_researcher.services.agent.enhanced_evidence import (
    EnhancedEvidenceCollector,
    ProvenanceTracker,
    EvidenceVisualizationAPI,
)
from brain_researcher.services.agent.advanced_error_recovery import (
    AdvancedErrorRecoverySystem,
    create_error_recovery_system,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionSession:
    """Enhanced execution session with comprehensive tracking."""

    session_id: str
    thread_id: str
    start_time: float
    user_query: str
    workflow_pipeline: Optional[Any] = None
    evidence_collector: Optional[EnhancedEvidenceCollector] = None
    execution_metrics: Dict[str, Any] = field(default_factory=dict)
    recovery_attempts: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "active"
    end_time: Optional[float] = None
    final_result: Optional[Dict[str, Any]] = None


class EnhancedAgentOrchestrator:
    """
    Enhanced agent orchestrator that integrates all advanced capabilities
    with the existing LangGraph state machine.
    """

    def __init__(
        self,
        base_state_machine: Optional[CoreStateMachine] = None,
        enable_workflow_composition: bool = True,
        enable_advanced_evidence: bool = True,
        enable_error_recovery: bool = True,
        evidence_storage_path: Optional[Path] = None,
        redis_url: Optional[str] = None,
    ):
        """Initialize enhanced agent orchestrator."""

        # Initialize base state machine or create new one
        self.base_state_machine = base_state_machine or CoreStateMachine()

        # Initialize enhanced components
        self.enhanced_registry = EnhancedToolRegistry()

        # Replace base registry in state machine
        self.base_state_machine.tool_registry = self.enhanced_registry

        # Optional advanced features
        self.workflow_composer = None
        self.workflow_executor = None
        self.error_recovery_system = None
        self.evidence_storage_path = evidence_storage_path or Path("/tmp/evidence")

        # Initialize workflow system
        if enable_workflow_composition:
            self.workflow_composer, self.workflow_executor = create_workflow_system(
                self.enhanced_registry
            )
            logger.info("Workflow composition system enabled")

        # Initialize error recovery system
        if enable_error_recovery:
            self.error_recovery_system = create_error_recovery_system(
                self.enhanced_registry, redis_url=redis_url
            )
            logger.info("Advanced error recovery system enabled")

        # Session management
        self.active_sessions: Dict[str, ExecutionSession] = {}
        self.session_history: List[ExecutionSession] = []

        # Initialize run recorder for logging
        self.run_recorder = RunRecorder()

        # Performance metrics
        self.performance_metrics = {
            "total_queries_processed": 0,
            "average_response_time": 0.0,
            "success_rate": 0.0,
            "recovery_success_rate": 0.0,
            "most_used_tools": {},
            "common_error_patterns": {},
        }

        logger.info("Enhanced agent orchestrator initialized")

    async def process_query(
        self,
        query: str,
        thread_id: Optional[str] = None,
        user_preferences: Dict[str, Any] = None,
        execution_options: Dict[str, Any] = None,
        resume_checkpoint_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a query with all enhanced capabilities.

        Args:
            query: User query
            thread_id: Thread ID for conversation continuity
            user_preferences: User-specific preferences
            execution_options: Execution configuration options

        Returns:
            Comprehensive execution result
        """
        # Initialize session
        session = self._create_execution_session(query, thread_id)

        try:
            # Phase 1: Query Understanding and Planning
            planning_result = await self._enhanced_planning_phase(
                session, query, user_preferences, execution_options
            )

            # Phase 2: Execution with Monitoring
            execution_result = await self._enhanced_execution_phase(
                session, planning_result, resume_checkpoint_id=resume_checkpoint_id
            )

            # Phase 3: Result Review and Evidence Aggregation
            review_result = await self._enhanced_review_phase(session, execution_result)

            # Phase 4: Generate Comprehensive Response
            final_response = await self._generate_comprehensive_response(
                session, review_result
            )

            # Update performance metrics
            self._update_performance_metrics(session, True)

            if self.base_state_machine:
                final_response["checkpoint_id"] = (
                    self.base_state_machine.get_last_checkpoint_id(session.thread_id)
                )
            return final_response

        except Exception as e:
            logger.error(f"Query processing error: {e}")

            # Attempt error recovery if enabled
            if self.error_recovery_system:
                recovery_result = await self._attempt_error_recovery(session, e)
                if recovery_result.get("success"):
                    # Update performance metrics for successful recovery
                    self._update_performance_metrics(session, True, recovery_used=True)
                    return recovery_result

            # Update performance metrics for failure
            self._update_performance_metrics(session, False)

            # Return error response
            return {
                "success": False,
                "session_id": session.session_id,
                "error": str(e),
                "recovery_attempted": self.error_recovery_system is not None,
                "execution_time": time.time() - session.start_time,
            }

        finally:
            # Clean up session
            session.end_time = time.time()
            session.status = "completed"
            self._archive_session(session)

    def _create_execution_session(
        self, query: str, thread_id: Optional[str]
    ) -> ExecutionSession:
        """Create a new execution session."""
        session_id = f"session_{uuid4().hex[:8]}"
        thread_id = thread_id or f"thread_{uuid4().hex[:8]}"

        # Create session-specific evidence collector
        evidence_collector = EnhancedEvidenceCollector(
            storage_path=self.evidence_storage_path / session_id,
            auto_persist=True,
            run_metadata={
                "session_id": session_id,
                "thread_id": thread_id,
                "query": query,
            },
        )

        session = ExecutionSession(
            session_id=session_id,
            thread_id=thread_id,
            start_time=time.time(),
            user_query=query,
            evidence_collector=evidence_collector,
        )

        self.active_sessions[session_id] = session

        logger.info(f"Created execution session {session_id}")
        return session

    async def _enhanced_planning_phase(
        self,
        session: ExecutionSession,
        query: str,
        user_preferences: Dict[str, Any] = None,
        execution_options: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Enhanced planning phase with workflow composition."""
        user_preferences = user_preferences or {}
        execution_options = execution_options or {}

        # Start logging for planning phase
        run_id = self.run_recorder.start("planning", session.session_id)

        # Collect evidence about the query
        session.evidence_collector.collect(
            type=session.evidence_collector.EvidenceType.USER_INPUT,
            source="user",
            content={"query": query, "preferences": user_preferences},
            confidence=session.evidence_collector.ConfidenceLevel.HIGH,
        )

        # Get intelligent tool recommendations
        recommendations = self.enhanced_registry.get_intelligent_recommendations(
            query=query,
            context={"session_id": session.session_id},
            user_preferences=user_preferences,
            max_recommendations=10,
        )

        # Convert recommendations to tool candidates format for logging
        tool_candidates = [
            {"name": rec["tool_name"], "score": rec.get("confidence", 0.5)}
            for rec in recommendations[:5]  # Top 5 for logging
        ]
        selected_tool = recommendations[0]["tool_name"] if recommendations else None

        # Create workflow if composer is available
        workflow_pipeline = None
        if self.workflow_composer:
            try:
                workflow_pipeline = self.workflow_composer.compose_workflow(
                    intent=query,
                    context={"session_id": session.session_id},
                    user_preferences=user_preferences,
                )
                session.workflow_pipeline = workflow_pipeline

                # Collect workflow evidence
                session.evidence_collector.collect(
                    type=session.evidence_collector.EvidenceType.INFERENCE,
                    source="workflow_composer",
                    content={
                        "pipeline_id": workflow_pipeline.pipeline_id,
                        "step_count": len(workflow_pipeline.steps),
                        "estimated_duration": workflow_pipeline.get_total_estimated_duration(),
                        "pattern": workflow_pipeline.pattern.value,
                    },
                    confidence=session.evidence_collector.ConfidenceLevel.MEDIUM,
                )

            except Exception as e:
                logger.warning(f"Workflow composition failed: {e}")

        # Use base state machine planning with enhanced context
        planning_context = {
            "session_id": session.session_id,
            "tool_recommendations": recommendations,
            "workflow_pipeline": workflow_pipeline,
            "user_preferences": user_preferences,
            "execution_options": execution_options,
        }

        # Run base planning but capture the result
        base_result = self.base_state_machine.run(
            query=query,
            thread_id=session.thread_id,
            resume_checkpoint_id=execution_options.get("resume_checkpoint_id")
            if execution_options
            else None,
            **(execution_options or {}),
        )

        # Log planning phase
        self.run_recorder.record_planning(
            query=query,
            tool_candidates=tool_candidates,
            selected_tool=selected_tool,
            llm_provider="google",  # TODO: Get from config
            llm_model="gemini-3-flash-preview",  # TODO: Get from actual model
            llm_params={
                "temperature": 0.2,
                "max_tokens": 1024,
            },  # TODO: Get from config
        )

        return {
            "base_result": base_result,
            "recommendations": recommendations,
            "workflow_pipeline": workflow_pipeline,
            "planning_context": planning_context,
        }

    async def _enhanced_execution_phase(
        self, session: ExecutionSession, planning_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enhanced execution phase with monitoring and evidence collection."""

        # Start logging for execution phase
        run_id = self.run_recorder.start("execution", session.session_id)

        # Start evidence chain for execution
        evidence_chain = session.evidence_collector.start_chain(
            description=f"Query execution: {session.user_query[:100]}"
        )

        execution_results = {}

        # Prepare for logging
        selected_tool = None
        args_raw = {}
        args_resolved = {}
        validation_ok = True
        validation_errors = []
        input_files = []
        output_files = []

        # Execute workflow if available
        if session.workflow_pipeline and self.workflow_executor:
            try:
                logger.info("Executing composed workflow")

                workflow_execution = await self.workflow_executor.execute_workflow(
                    pipeline=session.workflow_pipeline,
                    context={"session_id": session.session_id},
                    parallel_execution=True,
                )

                execution_results["workflow_execution"] = workflow_execution

                # Collect workflow execution evidence
                session.evidence_collector.collect(
                    type=session.evidence_collector.EvidenceType.RESULT,
                    source="workflow_executor",
                    content={
                        "execution_id": workflow_execution.execution_id,
                        "status": workflow_execution.status,
                        "completed_steps": len(workflow_execution.completed_steps),
                        "failed_steps": len(workflow_execution.failed_steps),
                        "total_time": (workflow_execution.end_time or time.time())
                        - workflow_execution.start_time,
                    },
                    confidence=session.evidence_collector.ConfidenceLevel.HIGH,
                )

            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")
                execution_results["workflow_error"] = str(e)

        # Execute individual tools from recommendations
        recommendations = planning_result.get("recommendations", [])
        for i, recommendation in enumerate(recommendations[:3]):  # Limit to top 3
            try:
                tool_result = await self.enhanced_registry.execute_with_monitoring(
                    tool=recommendation.tool,
                    parameters=recommendation.parameter_suggestions,
                    context={"session_id": session.session_id},
                )

                execution_results[f"tool_{i}_{recommendation.tool.get_tool_name()}"] = (
                    tool_result
                )

            except Exception as e:
                logger.warning(
                    f"Tool execution failed for {recommendation.tool.get_tool_name()}: {e}"
                )
                execution_results[
                    f"tool_{i}_{recommendation.tool.get_tool_name()}_error"
                ] = str(e)

        # End evidence chain
        session.evidence_collector.end_chain()

        # Update session metrics
        session.execution_metrics = {
            "tools_executed": len(
                [
                    k
                    for k in execution_results.keys()
                    if k.startswith("tool_") and not k.endswith("_error")
                ]
            ),
            "tools_failed": len(
                [k for k in execution_results.keys() if k.endswith("_error")]
            ),
            "workflow_executed": "workflow_execution" in execution_results,
            "total_execution_time": time.time() - session.start_time,
        }

        # Extract tool info from recommendations for logging
        recommendations = planning_result.get("recommendations", [])
        if recommendations:
            selected_tool = recommendations[0]["tool_name"]
            # TODO: Get actual args from tool execution
            args_raw = recommendations[0].get("parameter_suggestions", {})
            args_resolved = args_raw  # TODO: Get from ArgsResolver

        # Log execution phase
        exit_code = (
            0 if not any(k.endswith("_error") for k in execution_results.keys()) else 1
        )

        self.run_recorder.record_execution(
            query=session.user_query,
            selected_tool=selected_tool or "unknown",
            args_raw=args_raw,
            args_resolved=args_resolved,
            validation_ok=validation_ok,
            validation_errors=validation_errors,
            input_files=input_files,
            output_files=output_files,
            exit_code=exit_code,
            plan_cmd=f"execute {selected_tool}" if selected_tool else None,
        )

        return execution_results

    async def _enhanced_review_phase(
        self, session: ExecutionSession, execution_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enhanced review phase with evidence aggregation."""

        # Start logging for review phase
        run_id = self.run_recorder.start("review", session.session_id)

        # Aggregate evidence from execution
        evidence_aggregations = {}

        # Aggregate tool results if multiple tools were executed
        tool_results = [
            (k, v)
            for k, v in execution_result.items()
            if k.startswith("tool_")
            and not k.endswith("_error")
            and isinstance(v, dict)
        ]

        if len(tool_results) > 1:
            # Create evidence list from tool results
            tool_evidence_list = []
            for tool_key, tool_result in tool_results:
                tool_name = tool_key.split("_")[-1]
                evidence = session.evidence_collector.collect(
                    type=session.evidence_collector.EvidenceType.TOOL,
                    source=tool_name,
                    content=tool_result,
                    confidence=session.evidence_collector.ConfidenceLevel.HIGH,
                )
                tool_evidence_list.append(evidence)

            # Aggregate tool evidence
            if len(tool_evidence_list) > 1:
                aggregation = session.evidence_collector.aggregate_related_evidence(
                    evidence_type=session.evidence_collector.EvidenceType.TOOL,
                    method="consensus",
                )
                if aggregation:
                    evidence_aggregations["tool_consensus"] = aggregation

        # Calculate evidence quality score
        quality_score = session.evidence_collector.get_evidence_quality_score()

        # Generate comprehensive report
        evidence_report = session.evidence_collector.generate_report()

        # Create visualizations
        visualization_data = {
            "timeline": session.evidence_collector.visualization_api.create_evidence_timeline(),
            "confidence_distribution": session.evidence_collector.visualization_api.create_confidence_distribution(),
            "network": session.evidence_collector.visualization_api.create_evidence_network(),
        }

        # Determine review status
        has_errors = any(k.endswith("_error") for k in execution_result.keys())
        review_status = "FAIL" if has_errors else "PASS"

        # Prepare checks
        checks = []
        if quality_score:
            checks.append(
                {
                    "item": "evidence_quality",
                    "result": "OK" if quality_score > 0.7 else "WARNING",
                    "note": f"Score: {quality_score:.2f}",
                }
            )

        if session.execution_metrics:
            checks.append(
                {
                    "item": "execution_metrics",
                    "result": "OK"
                    if session.execution_metrics["tools_failed"] == 0
                    else "FAILED",
                    "note": f"Executed: {session.execution_metrics['tools_executed']}, Failed: {session.execution_metrics['tools_failed']}",
                }
            )

        # Log review phase
        self.run_recorder.record_review(
            query=session.user_query,
            status=review_status,
            checks=checks,
            notes=f"Quality score: {quality_score:.2f}" if quality_score else None,
        )

        return {
            "execution_result": execution_result,
            "evidence_aggregations": evidence_aggregations,
            "quality_score": quality_score,
            "evidence_report": evidence_report,
            "visualization_data": visualization_data,
        }

    async def _generate_comprehensive_response(
        self, session: ExecutionSession, review_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate comprehensive response with all collected information."""

        # Extract key results
        execution_result = review_result["execution_result"]
        quality_score = review_result["quality_score"]
        evidence_report = review_result["evidence_report"]

        # Generate summary
        successful_tools = []
        failed_tools = []

        for key, value in execution_result.items():
            if key.startswith("tool_"):
                tool_name = key.split("_")[-1]
                if key.endswith("_error"):
                    failed_tools.append(tool_name)
                elif isinstance(value, dict) and value.get("status") == "success":
                    successful_tools.append(tool_name)

        # Create response summary
        response_summary = f"""
Query processed successfully with {len(successful_tools)} tools executed.
Evidence quality score: {quality_score["quality_score"]:.2f}
Total evidence collected: {evidence_report["summary"]["total_evidence"]}
Processing time: {time.time() - session.start_time:.2f} seconds
        """.strip()

        # Compile comprehensive result
        result = {
            "success": True,
            "session_id": session.session_id,
            "thread_id": session.thread_id,
            "query": session.user_query,
            "response_summary": response_summary,
            "execution_results": execution_result,
            "evidence_summary": evidence_report["summary"],
            "quality_metrics": quality_score,
            "successful_tools": successful_tools,
            "failed_tools": failed_tools,
            "execution_time": time.time() - session.start_time,
            "workflow_used": session.workflow_pipeline is not None,
            "evidence_export_path": None,  # Will be set if exported
        }

        # Export evidence if requested or for important sessions
        if quality_score["quality_score"] > 0.7 or len(successful_tools) > 2:
            try:
                export_path = session.evidence_collector.visualization_api.export_comprehensive_report()
                result["evidence_export_path"] = str(export_path)
            except Exception as e:
                logger.warning(f"Failed to export evidence report: {e}")

        session.final_result = result
        return result

    async def _attempt_error_recovery(
        self, session: ExecutionSession, error: Exception
    ) -> Dict[str, Any]:
        """Attempt error recovery using the advanced recovery system."""

        if not self.error_recovery_system:
            return {"success": False, "error": "No recovery system available"}

        # Build error context
        error_context = {
            "session_id": session.session_id,
            "query": session.user_query,
            "execution_metrics": session.execution_metrics,
            "tool_name": "unknown",  # Would be extracted from error context
            "parameters": {},  # Would be extracted from error context
        }

        # Attempt recovery
        recovery_result = await self.error_recovery_system.handle_error_with_recovery(
            error=error, execution_context=error_context
        )

        # Record recovery attempt
        session.recovery_attempts.append(
            {
                "timestamp": time.time(),
                "error": str(error),
                "recovery_result": recovery_result,
            }
        )

        if recovery_result.get("success"):
            # Generate recovery response
            return {
                "success": True,
                "session_id": session.session_id,
                "recovery_used": True,
                "recovery_summary": f"Recovered using: {recovery_result.get('successful_action', 'unknown')}",
                "original_error": str(error),
                "recovery_time": recovery_result.get("recovery_time", 0),
                "actions_taken": recovery_result.get("actions_taken", []),
            }

        return recovery_result

    def _update_performance_metrics(
        self, session: ExecutionSession, success: bool, recovery_used: bool = False
    ):
        """Update system performance metrics."""
        self.performance_metrics["total_queries_processed"] += 1

        # Update success rate
        total_queries = self.performance_metrics["total_queries_processed"]
        if success:
            current_successes = (
                self.performance_metrics["success_rate"] * (total_queries - 1)
            ) + 1
        else:
            current_successes = self.performance_metrics["success_rate"] * (
                total_queries - 1
            )

        self.performance_metrics["success_rate"] = current_successes / total_queries

        # Update recovery success rate
        if recovery_used:
            # This would need more sophisticated tracking
            pass

        # Update response time
        execution_time = time.time() - session.start_time
        current_avg = self.performance_metrics["average_response_time"]
        new_avg = ((current_avg * (total_queries - 1)) + execution_time) / total_queries
        self.performance_metrics["average_response_time"] = new_avg

        # Update tool usage statistics
        if session.execution_metrics:
            # This would track which tools were used most frequently
            pass

    def _archive_session(self, session: ExecutionSession):
        """Archive completed session."""
        if session.session_id in self.active_sessions:
            del self.active_sessions[session.session_id]

        self.session_history.append(session)

        # Keep only recent history
        if len(self.session_history) > 1000:
            self.session_history = self.session_history[-1000:]

    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status."""
        return {
            "active_sessions": len(self.active_sessions),
            "total_sessions_processed": len(self.session_history),
            "performance_metrics": self.performance_metrics,
            "enhanced_features": {
                "workflow_composition": self.workflow_composer is not None,
                "error_recovery": self.error_recovery_system is not None,
                "advanced_evidence": True,  # Always available
            },
            "tool_registry_stats": self.enhanced_registry.get_registry_statistics(),
            "error_recovery_stats": (
                self.error_recovery_system.get_recovery_statistics()
                if self.error_recovery_system
                else None
            ),
        }

    def get_session_details(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific session."""
        # Check active sessions first
        if session_id in self.active_sessions:
            session = self.active_sessions[session_id]
        else:
            # Check session history
            session = next(
                (s for s in self.session_history if s.session_id == session_id), None
            )

        if not session:
            return None

        return {
            "session_id": session.session_id,
            "thread_id": session.thread_id,
            "query": session.user_query,
            "status": session.status,
            "start_time": session.start_time,
            "end_time": session.end_time,
            "execution_time": (session.end_time or time.time()) - session.start_time,
            "workflow_used": session.workflow_pipeline is not None,
            "execution_metrics": session.execution_metrics,
            "recovery_attempts": len(session.recovery_attempts),
            "evidence_collected": (
                len(session.evidence_collector.evidence)
                if session.evidence_collector
                else 0
            ),
            "final_result_available": session.final_result is not None,
        }


# Factory function for easy integration
def create_enhanced_agent_orchestrator(
    base_state_machine: Optional[CoreStateMachine] = None, **kwargs
) -> EnhancedAgentOrchestrator:
    """Create an enhanced agent orchestrator instance."""
    return EnhancedAgentOrchestrator(base_state_machine=base_state_machine, **kwargs)


# Convenience wrapper for backward compatibility
class EnhancedCoreStateMachine(CoreStateMachine):
    """Enhanced version of CoreStateMachine with all advanced features."""

    def __init__(self, *args, **kwargs):
        """Initialize enhanced core state machine."""
        super().__init__(*args, **kwargs)

        # Replace with enhanced orchestrator
        self.orchestrator = create_enhanced_agent_orchestrator(
            base_state_machine=self, **kwargs
        )

    async def arun_enhanced(
        self, query: str, thread_id: Optional[str] = None, **kwargs
    ):
        """Enhanced async run with all advanced features."""
        return await self.orchestrator.process_query(
            query=query, thread_id=thread_id, **kwargs
        )

    def run_enhanced(self, query: str, thread_id: Optional[str] = None, **kwargs):
        """Enhanced synchronous run with all advanced features."""
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self.arun_enhanced(query, thread_id, **kwargs)
            )
        finally:
            loop.close()

    def get_enhanced_status(self) -> Dict[str, Any]:
        """Get enhanced system status."""
        base_status = {
            "cache_stats": self.get_cache_stats(),
            "tool_count": len(self.tool_registry.get_all_tools()),
        }

        enhanced_status = self.orchestrator.get_system_status()

        return {**base_status, **enhanced_status}
