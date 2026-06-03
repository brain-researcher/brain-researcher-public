"""
LLM cost calculation utilities.

Converts token usage to USD cost estimates based on per-model pricing.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class ModelPricing:
    """Per-model pricing information."""

    provider: str
    model: str
    input_price_per_1k: float  # USD per 1K input tokens
    output_price_per_1k: float  # USD per 1K output tokens


# Pricing table based on public rates as of January 2025
# Source: https://ai.google.dev/pricing, https://openai.com/pricing
PRICING_TABLE = {
    # Gemini models (Google AI Studio / API)
    ("google", "gemini-2.0-flash-exp"): ModelPricing(
        "google", "gemini-2.0-flash-exp", 0.0, 0.0
    ),  # Free during preview
    ("google", "gemini-1.5-flash"): ModelPricing(
        "google", "gemini-1.5-flash", 0.000075, 0.0003
    ),
    ("google", "gemini-1.5-flash-8b"): ModelPricing(
        "google", "gemini-1.5-flash-8b", 0.0000375, 0.00015
    ),
    ("google", "gemini-1.5-pro"): ModelPricing(
        "google", "gemini-1.5-pro", 0.00125, 0.005
    ),
    ("google", "gemini-2.5-pro"): ModelPricing(
        "google", "gemini-2.5-pro", 0.00125, 0.005
    ),  # Placeholder
    ("google", "gemini-2.5-flash"): ModelPricing(
        "google", "gemini-2.5-flash", 0.000075, 0.0003
    ),  # Placeholder
    ("google", "gemini-3-flash-preview"): ModelPricing(
        "google", "gemini-3-flash-preview", 0.0005, 0.003
    ),
    ("google", "gemini-3.1-flash-lite-preview"): ModelPricing(
        "google", "gemini-3.1-flash-lite-preview", 0.00025, 0.0015
    ),
    # OpenAI models
    ("openai", "gpt-4o"): ModelPricing("openai", "gpt-4o", 0.0025, 0.01),
    ("openai", "gpt-4o-mini"): ModelPricing("openai", "gpt-4o-mini", 0.00015, 0.0006),
    ("openai", "gpt-4-turbo"): ModelPricing("openai", "gpt-4-turbo", 0.01, 0.03),
    ("openai", "gpt-4"): ModelPricing("openai", "gpt-4", 0.03, 0.06),
    ("openai", "gpt-3.5-turbo"): ModelPricing(
        "openai", "gpt-3.5-turbo", 0.0005, 0.0015
    ),
    # Anthropic Claude models (placeholder for future)
    ("anthropic", "claude-3-opus"): ModelPricing(
        "anthropic", "claude-3-opus", 0.015, 0.075
    ),
    ("anthropic", "claude-3-sonnet"): ModelPricing(
        "anthropic", "claude-3-sonnet", 0.003, 0.015
    ),
    ("anthropic", "claude-3-haiku"): ModelPricing(
        "anthropic", "claude-3-haiku", 0.00025, 0.00125
    ),
}


def get_model_pricing(provider: str, model: str) -> Optional[ModelPricing]:
    """
    Look up pricing for a given provider/model.

    Args:
        provider: Provider name (e.g., "google", "openai", "anthropic")
        model: Model name (e.g., "gemini-1.5-pro", "gpt-4o")

    Returns:
        ModelPricing if found, None otherwise
    """
    # Normalize provider and model names
    provider_normalized = provider.lower()
    model_normalized = model.lower()

    # Direct lookup
    key = (provider_normalized, model_normalized)
    if key in PRICING_TABLE:
        return PRICING_TABLE[key]

    # Fuzzy match for model variants (e.g., "gemini-1.5-pro-001" -> "gemini-1.5-pro")
    for (p, m), pricing in PRICING_TABLE.items():
        if p == provider_normalized and model_normalized.startswith(m):
            return pricing

    return None


def calculate_cost(
    provider: str,
    model: str,
    usage: Dict[str, Any],
    bill_to: Optional[str] = None,
) -> Dict[str, float]:
    """
    Calculate cost for an LLM invocation.

    Args:
        provider: Provider name (e.g., "google", "openai")
        model: Model name (e.g., "gemini-1.5-pro", "gpt-4o")
        usage: Usage dict with token counts (prompt_tokens, completion_tokens, total_tokens)
        bill_to: Billing target ("local_oauth", "byok", "managed", etc.)

    Returns:
        Dict with cost breakdown:
        {
            "prompt_cost": float,      # USD for input tokens
            "completion_cost": float,  # USD for output tokens
            "total_cost": float,       # Total USD
            "pricing_available": bool, # Whether pricing was found
        }
    """
    # Local OAuth (Gemini CLI free tier) is always $0
    if bill_to == "local_oauth":
        return {
            "prompt_cost": 0.0,
            "completion_cost": 0.0,
            "total_cost": 0.0,
            "pricing_available": True,
        }

    # Extract token counts
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)

    # Look up pricing
    pricing = get_model_pricing(provider, model)

    if pricing is None:
        # No pricing available - return zeros but mark as unavailable
        return {
            "prompt_cost": 0.0,
            "completion_cost": 0.0,
            "total_cost": 0.0,
            "pricing_available": False,
        }

    # Calculate costs (prices are per 1K tokens)
    prompt_cost = (prompt_tokens / 1000.0) * pricing.input_price_per_1k
    completion_cost = (completion_tokens / 1000.0) * pricing.output_price_per_1k
    total_cost = prompt_cost + completion_cost

    return {
        "prompt_cost": prompt_cost,
        "completion_cost": completion_cost,
        "total_cost": total_cost,
        "pricing_available": True,
    }


def estimate_cost_for_tokens(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """
    Quick cost estimate for a given token count.

    Args:
        provider: Provider name
        model: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Estimated cost in USD (0.0 if pricing unavailable)
    """
    usage = {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }

    cost_breakdown = calculate_cost(provider, model, usage)
    return cost_breakdown["total_cost"]
