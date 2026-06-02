"""
Chain-of-Thought Reasoning Module for Brain Researcher Agent (AGENT-011)

This module implements CoT prompting for complex query understanding with multi-step
reasoning traces, confidence scoring, and explanation generation.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ReasoningType(str, Enum):
    """Types of reasoning supported by CoT."""

    ANALYTICAL = "analytical"
    DEDUCTIVE = "deductive"
    INDUCTIVE = "inductive"
    CAUSAL = "causal"
    COMPARATIVE = "comparative"


class ConfidenceLevel(str, Enum):
    """Confidence levels for reasoning steps."""

    LOW = "low"  # 0.0 - 0.4
    MEDIUM = "medium"  # 0.4 - 0.7
    HIGH = "high"  # 0.7 - 1.0


@dataclass
class ReasoningStep:
    """Represents a single step in the chain of thought."""

    step_id: str
    step_number: int
    reasoning_type: ReasoningType
    premise: str
    inference: str
    conclusion: str
    confidence: float
    evidence: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    @property
    def confidence_level(self) -> ConfidenceLevel:
        """Get confidence level category."""
        if self.confidence < 0.4:
            return ConfidenceLevel.LOW
        elif self.confidence < 0.7:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.HIGH


@dataclass
class ReasoningTrace:
    """Complete chain of reasoning for a query."""

    trace_id: str
    query: str
    steps: List[ReasoningStep]
    final_conclusion: str
    overall_confidence: float
    explanation: str
    reasoning_path: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def get_high_confidence_steps(self) -> List[ReasoningStep]:
        """Get steps with high confidence scores."""
        return [
            step for step in self.steps if step.confidence_level == ConfidenceLevel.HIGH
        ]

    def get_critical_path(self) -> List[ReasoningStep]:
        """Get the critical reasoning path (highest confidence chain)."""
        if not self.steps:
            return []

        # Simple heuristic: return steps with confidence > 0.6
        return [step for step in self.steps if step.confidence > 0.6]


class CoTTemplates:
    """Templates for different types of Chain-of-Thought reasoning."""

    def __init__(self):
        self.templates = {
            ReasoningType.ANALYTICAL: self._analytical_template(),
            ReasoningType.DEDUCTIVE: self._deductive_template(),
            ReasoningType.INDUCTIVE: self._inductive_template(),
            ReasoningType.CAUSAL: self._causal_template(),
            ReasoningType.COMPARATIVE: self._comparative_template(),
        }

    def _analytical_template(self) -> str:
        return """
        Breaking down this query step by step:

        1. **What is being asked?**: {query}
        2. **Key components to analyze**: {components}
        3. **Approach**: {approach}
        4. **Step-by-step reasoning**:
           - First, I need to {step1}
           - Then, I should {step2}
           - Finally, I can {step3}
        5. **Evidence supporting this approach**: {evidence}
        6. **Assumptions made**: {assumptions}
        7. **Confidence in this reasoning**: {confidence}/10
        """

    def _deductive_template(self) -> str:
        return """
        Using deductive reasoning:

        **General principle**: {principle}
        **Specific case**: {specific_case}
        **Logical inference**: If {premise}, then {conclusion}
        **Application to query**: {application}
        **Confidence**: {confidence}/10
        """

    def _inductive_template(self) -> str:
        return """
        Using inductive reasoning from patterns:

        **Observed patterns**: {patterns}
        **Specific instances**: {instances}
        **General conclusion**: {conclusion}
        **Strength of pattern**: {strength}
        **Confidence**: {confidence}/10
        """

    def _causal_template(self) -> str:
        return """
        Analyzing causal relationships:

        **Potential causes**: {causes}
        **Expected effects**: {effects}
        **Causal mechanism**: {mechanism}
        **Supporting evidence**: {evidence}
        **Confidence in causal link**: {confidence}/10
        """

    def _comparative_template(self) -> str:
        return """
        Comparing different approaches:

        **Option A**: {option_a}
        **Option B**: {option_b}
        **Comparison criteria**: {criteria}
        **Advantages/Disadvantages**: {comparison}
        **Recommended approach**: {recommendation}
        **Confidence**: {confidence}/10
        """

    def get_template(self, reasoning_type: ReasoningType) -> str:
        """Get template for a specific reasoning type."""
        return self.templates.get(
            reasoning_type, self.templates[ReasoningType.ANALYTICAL]
        )


class ReasoningValidator:
    """Validates reasoning chains for logical consistency."""

    def __init__(self):
        self.validation_rules = [
            self._check_logical_consistency,
            self._check_evidence_support,
            self._check_assumption_validity,
            self._check_conclusion_follows,
        ]

    def validate_step(self, step: ReasoningStep) -> List[str]:
        """Validate a single reasoning step."""
        issues = []

        # Check for circular reasoning
        if step.step_id in step.dependencies:
            issues.append(f"Step {step.step_id} has circular dependency")

        # Check confidence bounds
        if not (0.0 <= step.confidence <= 1.0):
            issues.append(
                f"Step {step.step_id} has invalid confidence: {step.confidence}"
            )

        # Check completeness
        if not step.premise or not step.inference or not step.conclusion:
            issues.append(f"Step {step.step_id} is incomplete")

        return issues

    def validate_trace(self, trace: ReasoningTrace) -> List[str]:
        """Validate an entire reasoning trace."""
        issues = []

        # Validate individual steps
        for step in trace.steps:
            step_issues = self.validate_step(step)
            issues.extend(step_issues)

        # Check trace coherence
        if trace.steps:
            # Check if overall confidence aligns with step confidences
            avg_confidence = sum(s.confidence for s in trace.steps) / len(trace.steps)
            if abs(trace.overall_confidence - avg_confidence) > 0.3:
                issues.append("Overall confidence doesn't align with step confidences")

        # Check for gaps in reasoning
        step_numbers = [s.step_number for s in trace.steps]
        if step_numbers != list(range(1, len(step_numbers) + 1)):
            issues.append("Reasoning has gaps or non-sequential steps")

        return issues

    def _check_logical_consistency(self, step: ReasoningStep) -> bool:
        """Check if the step is logically consistent."""
        # Simple heuristic: premise should relate to conclusion
        return True  # Placeholder - could use more sophisticated NLP analysis

    def _check_evidence_support(self, step: ReasoningStep) -> bool:
        """Check if evidence supports the inference."""
        return len(step.evidence) > 0

    def _check_assumption_validity(self, step: ReasoningStep) -> bool:
        """Check if assumptions are reasonable."""
        return len(step.assumptions) < 5  # Too many assumptions = weak reasoning

    def _check_conclusion_follows(self, step: ReasoningStep) -> bool:
        """Check if conclusion follows from premise and inference."""
        return True  # Placeholder


class ChainOfThoughtReasoner:
    """
    Main Chain-of-Thought reasoning engine.

    Features:
    - Multi-step reasoning decomposition
    - Confidence scoring for each step
    - Natural language explanation generation
    - Template-based reasoning patterns
    - Logical validation
    """

    def __init__(self, llm_client: BaseChatModel):
        """
        Initialize the CoT reasoner.

        Args:
            llm_client: Language model for reasoning generation
        """
        self.llm = llm_client
        self.templates = CoTTemplates()
        self.validator = ReasoningValidator()

        # Reasoning configuration
        self.max_steps = 10
        self.min_confidence = 0.3
        self.confidence_threshold = 0.7

        logger.info("Chain-of-Thought Reasoner initialized")

    async def reason(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        reasoning_type: Optional[ReasoningType] = None,
        max_steps: Optional[int] = None,
    ) -> ReasoningTrace:
        """
        Generate a chain of reasoning for a query.

        Args:
            query: The query to reason about
            context: Additional context for reasoning
            reasoning_type: Specific type of reasoning to use
            max_steps: Maximum number of reasoning steps

        Returns:
            Complete reasoning trace
        """
        start_time = time.time()

        # Auto-detect reasoning type if not specified
        if not reasoning_type:
            reasoning_type = await self._detect_reasoning_type(query)

        # Generate reasoning steps
        steps = await self._generate_reasoning_steps(
            query, context or {}, reasoning_type, max_steps or self.max_steps
        )

        # Validate reasoning chain
        validation_issues = self.validator.validate_trace(
            ReasoningTrace(
                trace_id="temp",
                query=query,
                steps=steps,
                final_conclusion="",
                overall_confidence=0.0,
                explanation="",
            )
        )

        if validation_issues:
            logger.warning(f"Reasoning validation issues: {validation_issues}")

        # Generate final conclusion and explanation
        final_conclusion = await self._generate_conclusion(steps, query)
        explanation = await self._generate_explanation(steps, query, reasoning_type)

        # Calculate overall confidence
        overall_confidence = self._calculate_overall_confidence(steps)

        # Create reasoning trace
        trace = ReasoningTrace(
            trace_id=f"cot_{int(time.time() * 1000)}",
            query=query,
            steps=steps,
            final_conclusion=final_conclusion,
            overall_confidence=overall_confidence,
            explanation=explanation,
            reasoning_path=[
                f"Step {i+1}: {step.conclusion}" for i, step in enumerate(steps)
            ],
            metadata={
                "reasoning_type": reasoning_type.value,
                "generation_time": time.time() - start_time,
                "validation_issues": validation_issues,
                "context_used": bool(context),
            },
        )

        elapsed = time.time() - start_time
        logger.info(
            f"CoT reasoning completed in {elapsed:.3f}s with {len(steps)} steps"
        )

        return trace

    async def _detect_reasoning_type(self, query: str) -> ReasoningType:
        """Auto-detect the most appropriate reasoning type for a query."""
        detection_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """Analyze this query and determine the most appropriate reasoning type:

            - ANALYTICAL: Breaking down complex problems into components
            - DEDUCTIVE: Reasoning from general principles to specific conclusions
            - INDUCTIVE: Reasoning from specific observations to general patterns
            - CAUSAL: Analyzing cause-and-effect relationships
            - COMPARATIVE: Comparing different options or approaches

            Return only the reasoning type name.""",
                ),
                ("human", "{query}"),
            ]
        )

        chain = detection_prompt | self.llm
        response = await chain.ainvoke({"query": query})

        # Parse response to reasoning type
        content = response.content.strip().upper()
        for reasoning_type in ReasoningType:
            if reasoning_type.value.upper() in content:
                return reasoning_type

        # Default to analytical
        return ReasoningType.ANALYTICAL

    async def _generate_reasoning_steps(
        self,
        query: str,
        context: Dict[str, Any],
        reasoning_type: ReasoningType,
        max_steps: int,
    ) -> List[ReasoningStep]:
        """Generate individual reasoning steps."""

        # Get appropriate template
        template = self.templates.get_template(reasoning_type)

        step_generation_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    f"""You are reasoning about a neuroscience query using {reasoning_type.value} reasoning.

            Generate a step-by-step reasoning chain. For each step, provide:
            1. A clear premise (what we know/assume)
            2. The inference rule or logical step
            3. The conclusion that follows
            4. Confidence score (0.0-1.0)
            5. Supporting evidence
            6. Any assumptions made

            Context: {context}

            Return a JSON array of steps:
            [
                {{
                    "step_number": 1,
                    "premise": "...",
                    "inference": "...",
                    "conclusion": "...",
                    "confidence": 0.85,
                    "evidence": ["..."],
                    "assumptions": ["..."]
                }}
            ]

            Maximum {max_steps} steps.""",
                ),
                ("human", "{query}"),
            ]
        )

        chain = step_generation_prompt | self.llm
        response = await chain.ainvoke({"query": query})

        # Parse steps from response
        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            steps_data = json.loads(content)
        except Exception as e:
            logger.error(f"Failed to parse reasoning steps: {e}")
            # Fallback to simple step
            steps_data = [
                {
                    "step_number": 1,
                    "premise": f"Query: {query}",
                    "inference": "Direct analysis needed",
                    "conclusion": "Will analyze using available tools",
                    "confidence": 0.7,
                    "evidence": ["User query provided"],
                    "assumptions": ["Query is well-formed"],
                }
            ]

        # Convert to ReasoningStep objects
        steps = []
        for step_data in steps_data:
            step = ReasoningStep(
                step_id=f"step_{step_data.get('step_number', len(steps) + 1)}",
                step_number=step_data.get("step_number", len(steps) + 1),
                reasoning_type=reasoning_type,
                premise=step_data.get("premise", ""),
                inference=step_data.get("inference", ""),
                conclusion=step_data.get("conclusion", ""),
                confidence=min(1.0, max(0.0, step_data.get("confidence", 0.5))),
                evidence=step_data.get("evidence", []),
                assumptions=step_data.get("assumptions", []),
            )
            steps.append(step)

        return steps

    async def _generate_conclusion(self, steps: List[ReasoningStep], query: str) -> str:
        """Generate final conclusion from reasoning steps."""
        if not steps:
            return "No reasoning steps generated"

        conclusion_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """Based on the reasoning steps, generate a clear final conclusion
            that directly answers the original query.

            Keep it concise but comprehensive.""",
                ),
                (
                    "human",
                    """Query: {query}

            Reasoning steps:
            {steps}

            What is the final conclusion?""",
                ),
            ]
        )

        steps_text = "\n".join(
            [
                f"Step {step.step_number}: {step.premise} → {step.inference} → {step.conclusion} (confidence: {step.confidence:.2f})"
                for step in steps
            ]
        )

        chain = conclusion_prompt | self.llm
        response = await chain.ainvoke({"query": query, "steps": steps_text})

        return response.content.strip()

    async def _generate_explanation(
        self, steps: List[ReasoningStep], query: str, reasoning_type: ReasoningType
    ) -> str:
        """Generate natural language explanation of the reasoning process."""

        explanation_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    f"""Generate a clear, natural language explanation of how we reasoned
            through this query using {reasoning_type.value} reasoning.

            Explain:
            1. The overall approach taken
            2. Key reasoning steps
            3. How confidence was assessed
            4. Why this reasoning leads to the conclusion

            Make it understandable to a neuroscience researcher.""",
                ),
                (
                    "human",
                    """Query: {query}

            Reasoning steps:
            {steps}

            Please explain this reasoning process.""",
                ),
            ]
        )

        steps_summary = "\n".join(
            [
                f"Step {step.step_number}: {step.conclusion} (confidence: {step.confidence_level.value})"
                for step in steps
            ]
        )

        chain = explanation_prompt | self.llm
        response = await chain.ainvoke({"query": query, "steps": steps_summary})

        return response.content.strip()

    def _calculate_overall_confidence(self, steps: List[ReasoningStep]) -> float:
        """Calculate overall confidence from individual step confidences."""
        if not steps:
            return 0.0

        # Use geometric mean to be conservative
        # (low confidence in any step reduces overall confidence significantly)
        confidences = [step.confidence for step in steps]
        geometric_mean = 1.0
        for conf in confidences:
            geometric_mean *= conf

        return geometric_mean ** (1.0 / len(confidences))

    def get_reasoning_summary(self, trace: ReasoningTrace) -> Dict[str, Any]:
        """Get a summary of the reasoning trace for display."""
        return {
            "trace_id": trace.trace_id,
            "query": trace.query,
            "reasoning_type": trace.metadata.get("reasoning_type"),
            "total_steps": len(trace.steps),
            "high_confidence_steps": len(trace.get_high_confidence_steps()),
            "overall_confidence": trace.overall_confidence,
            "confidence_level": (
                "High"
                if trace.overall_confidence >= 0.7
                else "Medium" if trace.overall_confidence >= 0.4 else "Low"
            ),
            "final_conclusion": trace.final_conclusion,
            "generation_time": trace.metadata.get("generation_time", 0),
            "validation_issues": len(trace.metadata.get("validation_issues", [])),
        }


# Factory function for easy integration
def get_cot_reasoner(llm_client: BaseChatModel) -> ChainOfThoughtReasoner:
    """
    Factory function to create a ChainOfThoughtReasoner.

    Args:
        llm_client: Language model for reasoning

    Returns:
        Configured CoT reasoner instance
    """
    return ChainOfThoughtReasoner(llm_client)
