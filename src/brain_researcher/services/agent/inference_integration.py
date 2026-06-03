"""
Integration module for Parameter Inference with existing validation system.

Connects AGENT-005 (Parameter Inference) with AGENT-008 (Parameter Validation).
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from brain_researcher.services.agent.parameter_inference import (
    ParameterInferenceEngine,
    InferredParameters,
)
from brain_researcher.services.agent.parameter_validation import ParameterValidator

logger = logging.getLogger(__name__)


class InferenceAwareValidator:
    """
    Enhanced parameter validator with automatic inference capabilities.

    Combines parameter inference (AGENT-005) with validation (AGENT-008)
    to provide a seamless parameter handling experience.
    """

    def __init__(
        self,
        enable_inference: bool = True,
        confidence_threshold: float = 0.5,
    ):
        """
        Initialize the inference-aware validator.

        Args:
            enable_inference: Whether to enable automatic inference
            confidence_threshold: Minimum confidence to accept inferred params
        """
        self.validator = ParameterValidator()
        self.inference_engine = ParameterInferenceEngine() if enable_inference else None
        self.confidence_threshold = confidence_threshold
        self.enable_inference = enable_inference

        logger.info(
            f"InferenceAwareValidator initialized "
            f"(inference: {'enabled' if enable_inference else 'disabled'})"
        )

    def validate_with_inference(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        query: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        previous_results: Optional[List[Dict[str, Any]]] = None,
        auto_complete: bool = True,
    ) -> Tuple[Dict[str, Any], Dict[str, str], List[str]]:
        """
        Validate parameters with automatic inference for missing values.

        Args:
            tool_name: Name of the tool
            parameters: User-provided parameters
            query: User query for context
            file_paths: BIDS files to analyze
            previous_results: Previous analysis results
            auto_complete: Whether to auto-complete missing parameters

        Returns:
            Tuple of (validated_params, validation_errors, warnings)
        """
        validated_params = parameters.copy()
        validation_errors = {}
        warnings = []

        # Step 1: Infer missing parameters if enabled
        if self.enable_inference and auto_complete:
            inferred = self._infer_parameters(
                tool_name=tool_name,
                existing_params=parameters,
                query=query,
                file_paths=file_paths,
                previous_results=previous_results,
            )

            # Merge inferred parameters (only if not already provided)
            for param_name, param_value in inferred.parameters.items():
                if param_name not in validated_params:
                    confidence = inferred.confidence.get(param_name, 0)

                    if confidence >= self.confidence_threshold:
                        validated_params[param_name] = param_value
                        source = inferred.sources.get(param_name, "unknown")
                        warnings.append(
                            f"Parameter '{param_name}' inferred from {source} "
                            f"(confidence: {confidence:.2f})"
                        )
                    else:
                        warnings.append(
                            f"Parameter '{param_name}' inferred with low confidence "
                            f"({confidence:.2f}), not using"
                        )

            # Add inference warnings
            warnings.extend(inferred.warnings)

        # Step 2: Validate all parameters (provided + inferred)
        validation_result = self.validator.validate_parameters(
            tool_name=tool_name,
            parameters=validated_params,
        )

        if not validation_result.is_valid:
            validation_errors.update(validation_result.errors)

        # Step 3: Apply suggestions from validator
        if validation_result.suggestions:
            for param_name, suggestion in validation_result.suggestions.items():
                if param_name not in validated_params:
                    validated_params[param_name] = suggestion
                    warnings.append(
                        f"Parameter '{param_name}' set to suggested value: {suggestion}"
                    )

        # Step 4: Check for missing required parameters
        tool_schema = self.validator.get_tool_schema(tool_name)
        if tool_schema and "required" in tool_schema:
            missing = []
            for required_param in tool_schema["required"]:
                if required_param not in validated_params:
                    missing.append(required_param)

            if missing:
                validation_errors["missing_required"] = (
                    f"Missing required parameters: {', '.join(missing)}"
                )

        return validated_params, validation_errors, warnings

    def _infer_parameters(
        self,
        tool_name: str,
        existing_params: Dict[str, Any],
        query: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        previous_results: Optional[List[Dict[str, Any]]] = None,
    ) -> InferredParameters:
        """Internal method to infer parameters."""
        if not self.inference_engine:
            return InferredParameters()

        # Infer from context
        inferred = self.inference_engine.infer_from_context(
            query=query or "",
            file_paths=file_paths,
            previous_results=previous_results,
            tool_name=tool_name,
        )

        # Don't override existing parameters
        for param in existing_params:
            if param in inferred.parameters:
                del inferred.parameters[param]
                if param in inferred.confidence:
                    del inferred.confidence[param]
                if param in inferred.sources:
                    del inferred.sources[param]

        return inferred

    def suggest_parameters(
        self,
        tool_name: str,
        query: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Suggest parameters for a tool based on context.

        Args:
            tool_name: Name of the tool
            query: User query for context
            file_paths: BIDS files to analyze

        Returns:
            Dictionary of suggested parameters
        """
        if not self.enable_inference:
            return {}

        inferred = self._infer_parameters(
            tool_name=tool_name,
            existing_params={},
            query=query,
            file_paths=file_paths,
        )

        # Only return high-confidence suggestions
        suggestions = {}
        for param_name, param_value in inferred.parameters.items():
            confidence = inferred.confidence.get(param_name, 0)
            if confidence >= self.confidence_threshold:
                suggestions[param_name] = {
                    "value": param_value,
                    "confidence": confidence,
                    "source": inferred.sources.get(param_name, "unknown"),
                }

        return suggestions

    def explain_inference(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        query: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
    ) -> str:
        """
        Explain how parameters would be inferred.

        Args:
            tool_name: Name of the tool
            parameters: Current parameters
            query: User query
            file_paths: BIDS files

        Returns:
            Human-readable explanation
        """
        if not self.enable_inference:
            return "Parameter inference is disabled"

        inferred = self._infer_parameters(
            tool_name=tool_name,
            existing_params={},
            query=query,
            file_paths=file_paths,
        )

        explanation = f"Parameter Inference for {tool_name}\n"
        explanation += "=" * 50 + "\n\n"

        if query:
            explanation += f"Query: {query}\n\n"

        if file_paths:
            explanation += "Input Files:\n"
            for fp in file_paths:
                explanation += f"  - {fp}\n"
            explanation += "\n"

        if inferred.parameters:
            explanation += "Inferred Parameters:\n"
            for param_name, param_value in inferred.parameters.items():
                confidence = inferred.confidence.get(param_name, 0)
                source = inferred.sources.get(param_name, "unknown")

                explanation += f"  {param_name}:\n"
                explanation += f"    Value: {param_value}\n"
                explanation += f"    Confidence: {confidence:.2f}\n"
                explanation += f"    Source: {source}\n"
        else:
            explanation += "No parameters could be inferred from the context.\n"

        if inferred.warnings:
            explanation += "\nWarnings:\n"
            for warning in inferred.warnings:
                explanation += f"  - {warning}\n"

        # Add confidence summary
        explanation += "\n" + self.inference_engine.get_confidence_summary(inferred)

        return explanation


class SmartParameterHandler:
    """
    High-level parameter handler combining inference, validation, and discovery.

    This is the main interface for parameter handling in the agent.
    """

    def __init__(self):
        """Initialize the smart parameter handler."""
        self.validator = InferenceAwareValidator(enable_inference=True)
        self.history: List[Dict[str, Any]] = []

    def process_parameters(
        self,
        tool_name: str,
        user_params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process parameters with full inference and validation.

        Args:
            tool_name: Tool to run
            user_params: User-provided parameters
            context: Additional context (query, files, etc.)

        Returns:
            Processed and validated parameters
        """
        context = context or {}

        # Extract context components
        query = context.get("query")
        file_paths = context.get("file_paths", [])

        # Validate with inference
        validated_params, errors, warnings = self.validator.validate_with_inference(
            tool_name=tool_name,
            parameters=user_params,
            query=query,
            file_paths=file_paths,
            previous_results=self.history[-10:],  # Use last 10 results
            auto_complete=True,
        )

        # Log the process
        result = {
            "tool_name": tool_name,
            "input_params": user_params,
            "validated_params": validated_params,
            "errors": errors,
            "warnings": warnings,
            "timestamp": str(time.time()),
        }

        self.history.append(result)

        if errors:
            error_msg = "Parameter validation failed:\n"
            for param, error in errors.items():
                error_msg += f"  - {param}: {error}\n"
            raise ValueError(error_msg)

        # Log warnings
        for warning in warnings:
            logger.info(f"Parameter warning: {warning}")

        return validated_params

    def suggest_missing(
        self,
        tool_name: str,
        current_params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Suggest values for missing parameters.

        Args:
            tool_name: Tool name
            current_params: Currently set parameters
            context: Additional context

        Returns:
            Suggested parameters with confidence scores
        """
        context = context or {}

        suggestions = self.validator.suggest_parameters(
            tool_name=tool_name,
            query=context.get("query"),
            file_paths=context.get("file_paths", []),
        )

        # Remove already set parameters
        for param in current_params:
            suggestions.pop(param, None)

        return suggestions

    def explain(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Explain parameter inference and validation.

        Args:
            tool_name: Tool name
            parameters: Parameters to explain
            context: Additional context

        Returns:
            Human-readable explanation
        """
        context = context or {}

        return self.validator.explain_inference(
            tool_name=tool_name,
            parameters=parameters,
            query=context.get("query"),
            file_paths=context.get("file_paths", []),
        )