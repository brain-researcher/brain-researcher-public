"""
Token Counting and Cost Estimation for LLM Calls

This module provides utilities to estimate token counts and costs for
various LLM providers, enabling budget tracking and optimization.
"""

import json
import re
from typing import Any


class TokenCounter:
    """Estimate token counts for various LLM providers."""

    # Approximate token/character ratios for different providers
    TOKEN_RATIOS = {
        "openai": 0.25,  # ~4 chars per token
        "anthropic": 0.25,  # Similar to OpenAI
        "google": 0.3,  # Slightly different tokenizer
        "default": 0.25,  # Conservative estimate
    }

    # Cost per 1K tokens (USD) - as of 2025
    PRICING = {
        "openai": {
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
            "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        },
        "anthropic": {
            "claude-3-opus": {"input": 0.015, "output": 0.075},
            "claude-3-sonnet": {"input": 0.003, "output": 0.015},
            "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
        },
        "google": {
            "gemini-2.0-flash": {"input": 0.00015, "output": 0.0006},
            "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
            "gemini-1.5-flash": {"input": 0.00025, "output": 0.001},
            "gemini-2.5-pro": {"input": 0.00125, "output": 0.005},
            "gemini-2.5-flash": {"input": 0.00015, "output": 0.0006},
            "gemini-3-flash-preview": {"input": 0.0005, "output": 0.003},
            "gemini-3.1-flash-lite-preview": {"input": 0.00025, "output": 0.0015},
        },
        "gemini-oauth": {
            # Local Gemini CLI with OAuth - free credits
            "gemini-2.0-flash": {"input": 0.0, "output": 0.0},
            "gemini-1.5-pro": {"input": 0.0, "output": 0.0},
            "gemini-1.5-flash": {"input": 0.0, "output": 0.0},
            "gemini-2.5-pro": {"input": 0.0, "output": 0.0},
            "gemini-2.5-flash": {"input": 0.0, "output": 0.0},
            "gemini-3-flash-preview": {"input": 0.0, "output": 0.0},
            "gemini-3.1-flash-lite-preview": {"input": 0.0, "output": 0.0},
        },
    }

    @classmethod
    def estimate_tokens(cls, text: str, provider: str = "default") -> int:
        """
        Estimate token count for text.

        Args:
            text: Input text
            provider: LLM provider name

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        # Get ratio for provider
        ratio = cls.TOKEN_RATIOS.get(provider, cls.TOKEN_RATIOS["default"])

        # Basic estimation: character count * ratio
        char_count = len(text)

        # Adjust for JSON structure (adds overhead)
        if cls._is_json(text):
            char_count *= 1.1

        # Adjust for code (typically more tokens)
        if cls._has_code(text):
            char_count *= 1.2

        return int(char_count * ratio)

    @classmethod
    def estimate_cost(
        cls, input_tokens: int, output_tokens: int, provider: str, model: str
    ) -> dict[str, float]:
        """
        Estimate cost for token usage.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            provider: LLM provider
            model: Model name

        Returns:
            Dict with cost breakdown
        """
        # Get pricing for provider/model
        provider_pricing = cls.PRICING.get(provider, {})

        # Try to find exact model match
        model_pricing = None
        for model_key in provider_pricing:
            if model_key in model.lower():
                model_pricing = provider_pricing[model_key]
                break

        if not model_pricing:
            # Use default conservative estimate
            model_pricing = {"input": 0.001, "output": 0.002}

        # Calculate costs (prices are per 1K tokens)
        input_cost = (input_tokens / 1000) * model_pricing["input"]
        output_cost = (output_tokens / 1000) * model_pricing["output"]

        return {
            "input_cost_usd": round(input_cost, 6),
            "output_cost_usd": round(output_cost, 6),
            "total_cost_usd": round(input_cost + output_cost, 6),
        }

    @classmethod
    def get_cost_for_model(
        cls, provider: str, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """
        Helper method to get total cost for a specific model.

        Args:
            provider: Provider name (google, openai, anthropic, gemini-oauth)
            model: Model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Total cost in USD
        """
        cost_breakdown = cls.estimate_cost(input_tokens, output_tokens, provider, model)
        return cost_breakdown["total_cost_usd"]

    @staticmethod
    def _is_json(text: str) -> bool:
        """Check if text appears to be JSON."""
        try:
            json.loads(text)
            return True
        except:
            return text.strip().startswith("{") or text.strip().startswith("[")

    @staticmethod
    def _has_code(text: str) -> bool:
        """Check if text contains code patterns."""
        code_patterns = [
            r"def\s+\w+\s*\(",  # Python function
            r"function\s+\w+\s*\(",  # JavaScript function
            r"class\s+\w+",  # Class definition
            r"import\s+\w+",  # Import statement
            r"```",  # Code block
        ]

        for pattern in code_patterns:
            if re.search(pattern, text):
                return True
        return False


class UsageTracker:
    """Track cumulative token usage and costs."""

    def __init__(self):
        """Initialize usage tracker."""
        self.sessions = {}
        self.daily_usage = {}
        self.monthly_usage = {}

    def track_usage(
        self,
        session_id: str,
        provider: str,
        model: str,
        input_text: str,
        output_text: str,
        timestamp: str,
    ) -> dict[str, Any]:
        """
        Track token usage for a session.

        Args:
            session_id: Session identifier
            provider: LLM provider
            model: Model name
            input_text: Input prompt
            output_text: Model response
            timestamp: ISO timestamp

        Returns:
            Usage statistics
        """
        # Estimate tokens
        input_tokens = TokenCounter.estimate_tokens(input_text, provider)
        output_tokens = TokenCounter.estimate_tokens(output_text, provider)

        # Calculate cost
        cost_info = TokenCounter.estimate_cost(
            input_tokens, output_tokens, provider, model
        )

        # Create usage record
        usage = {
            "timestamp": timestamp,
            "provider": provider,
            "model": model,
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            },
            "cost": cost_info,
        }

        # Update session tracking
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "total_tokens": 0,
                "total_cost_usd": 0,
                "calls": [],
            }

        session = self.sessions[session_id]
        session["total_tokens"] += usage["tokens"]["total"]
        session["total_cost_usd"] += cost_info["total_cost_usd"]
        session["calls"].append(usage)

        # Update daily tracking
        date = timestamp[:10]  # YYYY-MM-DD
        if date not in self.daily_usage:
            self.daily_usage[date] = {
                "total_tokens": 0,
                "total_cost_usd": 0,
                "by_provider": {},
            }

        daily = self.daily_usage[date]
        daily["total_tokens"] += usage["tokens"]["total"]
        daily["total_cost_usd"] += cost_info["total_cost_usd"]

        if provider not in daily["by_provider"]:
            daily["by_provider"][provider] = {"tokens": 0, "cost_usd": 0}

        daily["by_provider"][provider]["tokens"] += usage["tokens"]["total"]
        daily["by_provider"][provider]["cost_usd"] += cost_info["total_cost_usd"]

        return usage

    def get_session_summary(self, session_id: str) -> dict[str, Any] | None:
        """
        Get usage summary for a session.

        Args:
            session_id: Session identifier

        Returns:
            Session usage summary or None
        """
        if session_id not in self.sessions:
            return None

        session = self.sessions[session_id]
        return {
            "session_id": session_id,
            "total_tokens": session["total_tokens"],
            "total_cost_usd": round(session["total_cost_usd"], 4),
            "call_count": len(session["calls"]),
            "average_tokens_per_call": (
                session["total_tokens"] // len(session["calls"])
                if session["calls"]
                else 0
            ),
        }

    def get_daily_summary(self, date: str) -> dict[str, Any] | None:
        """
        Get usage summary for a specific date.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            Daily usage summary or None
        """
        if date not in self.daily_usage:
            return None

        return self.daily_usage[date]

    def estimate_monthly_cost(self, current_date: str) -> dict[str, float]:
        """
        Estimate monthly cost based on current usage.

        Args:
            current_date: Current date in YYYY-MM-DD format

        Returns:
            Monthly cost estimates
        """
        # Get current month
        month = current_date[:7]  # YYYY-MM

        # Calculate days elapsed and remaining
        day = int(current_date[8:10])
        days_in_month = 30  # Simplified

        # Sum usage for current month
        month_total = 0
        for date, usage in self.daily_usage.items():
            if date.startswith(month):
                month_total += usage["total_cost_usd"]

        # Calculate projections
        daily_average = month_total / day if day > 0 else 0
        projected_total = daily_average * days_in_month

        return {
            "current_month_cost": round(month_total, 2),
            "daily_average": round(daily_average, 2),
            "projected_month_total": round(projected_total, 2),
            "days_elapsed": day,
            "days_remaining": days_in_month - day,
        }


class CostOptimizer:
    """Suggest cost optimization strategies."""

    @staticmethod
    def analyze_usage(tracker: UsageTracker) -> list[dict[str, Any]]:
        """
        Analyze usage patterns and suggest optimizations.

        Args:
            tracker: UsageTracker instance

        Returns:
            List of optimization suggestions
        """
        suggestions = []

        # Analyze session patterns
        for session_id, session in tracker.sessions.items():
            if session["total_cost_usd"] > 1.0:
                suggestions.append(
                    {
                        "type": "high_cost_session",
                        "session_id": session_id,
                        "cost": session["total_cost_usd"],
                        "recommendation": "Consider using a cheaper model for this type of task",
                    }
                )

            # Check for repetitive calls
            if len(session["calls"]) > 10:
                avg_tokens = session["total_tokens"] / len(session["calls"])
                if avg_tokens < 100:
                    suggestions.append(
                        {
                            "type": "many_small_calls",
                            "session_id": session_id,
                            "call_count": len(session["calls"]),
                            "recommendation": "Batch multiple small requests into fewer larger ones",
                        }
                    )

        # Analyze daily patterns
        for date, daily in tracker.daily_usage.items():
            if daily["total_cost_usd"] > 10.0:
                suggestions.append(
                    {
                        "type": "high_daily_cost",
                        "date": date,
                        "cost": daily["total_cost_usd"],
                        "recommendation": "Daily cost exceeds $10 - review usage patterns",
                    }
                )

            # Check provider distribution
            if "by_provider" in daily:
                for provider, usage in daily["by_provider"].items():
                    if provider == "openai" and usage["cost_usd"] > 5.0:
                        suggestions.append(
                            {
                                "type": "expensive_provider",
                                "date": date,
                                "provider": provider,
                                "cost": usage["cost_usd"],
                                "recommendation": "Consider using Google Gemini Flash for lower costs",
                            }
                        )

        return suggestions


# Example integration with RunRecorder
def enhance_log_with_tokens(
    log: dict[str, Any],
    query: str,
    response: str,
    provider: str = "google",
    model: str = "gemini-3-flash-preview",
) -> dict[str, Any]:
    """
    Enhance log entry with token counts and cost estimates.

    Args:
        log: Base log entry
        query: User query/prompt
        response: Model response
        provider: LLM provider
        model: Model name

    Returns:
        Enhanced log entry
    """
    # Estimate tokens
    input_tokens = TokenCounter.estimate_tokens(query, provider)
    output_tokens = TokenCounter.estimate_tokens(response, provider)

    # Calculate cost
    cost_info = TokenCounter.estimate_cost(input_tokens, output_tokens, provider, model)

    # Enhance llm_call section
    if "llm_call" not in log:
        log["llm_call"] = {}

    log["llm_call"].update(
        {
            "tokens": {
                "prompt": input_tokens,
                "completion": output_tokens,
                "total": input_tokens + output_tokens,
            },
            "cost": cost_info,
        }
    )

    return log
