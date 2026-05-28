"""Unit tests for LLM cost calculation."""

import pytest

from brain_researcher.services.agent.cost_calculator import (
    ModelPricing,
    calculate_cost,
    estimate_cost_for_tokens,
    get_model_pricing,
)


class TestGetModelPricing:
    """Test model pricing lookup."""

    def test_exact_match_gemini(self):
        """Test exact match for Gemini model."""
        pricing = get_model_pricing("google", "gemini-1.5-flash")
        assert pricing is not None
        assert pricing.provider == "google"
        assert pricing.model == "gemini-1.5-flash"
        assert pricing.input_price_per_1k == 0.000075
        assert pricing.output_price_per_1k == 0.0003

    def test_exact_match_openai(self):
        """Test exact match for OpenAI model."""
        pricing = get_model_pricing("openai", "gpt-4o")
        assert pricing is not None
        assert pricing.provider == "openai"
        assert pricing.model == "gpt-4o"
        assert pricing.input_price_per_1k == 0.0025
        assert pricing.output_price_per_1k == 0.01

    def test_case_insensitive(self):
        """Test case-insensitive lookup."""
        pricing1 = get_model_pricing("Google", "Gemini-1.5-Flash")
        pricing2 = get_model_pricing("google", "gemini-1.5-flash")
        assert pricing1 is not None
        assert pricing2 is not None
        assert pricing1.model == pricing2.model

    def test_fuzzy_match_variant(self):
        """Test fuzzy matching for model variants."""
        # Model with version suffix should match base model
        pricing = get_model_pricing("google", "gemini-1.5-flash-001")
        assert pricing is not None
        assert pricing.model == "gemini-1.5-flash"

    def test_unknown_model(self):
        """Test unknown model returns None."""
        pricing = get_model_pricing("unknown", "unknown-model")
        assert pricing is None

    def test_unknown_provider(self):
        """Test unknown provider returns None."""
        pricing = get_model_pricing("unknown-provider", "gpt-4o")
        assert pricing is None

    def test_exact_match_gemini_31_flash_lite_preview(self):
        """Test exact match for Gemini 3.1 Flash-Lite preview pricing."""
        pricing = get_model_pricing("google", "gemini-3.1-flash-lite-preview")
        assert pricing is not None
        assert pricing.provider == "google"
        assert pricing.model == "gemini-3.1-flash-lite-preview"
        assert pricing.input_price_per_1k == 0.00025
        assert pricing.output_price_per_1k == 0.0015

    def test_exact_match_gemini_3_flash_preview(self):
        """Test exact match for Gemini 3 Flash preview pricing."""
        pricing = get_model_pricing("google", "gemini-3-flash-preview")
        assert pricing is not None
        assert pricing.provider == "google"
        assert pricing.model == "gemini-3-flash-preview"
        assert pricing.input_price_per_1k == 0.0005
        assert pricing.output_price_per_1k == 0.003


class TestCalculateCost:
    """Test cost calculation logic."""

    def test_local_oauth_is_free(self):
        """Test local OAuth (free tier) has zero cost."""
        usage = {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}
        result = calculate_cost(
            provider="google",
            model="gemini-2.5-flash",
            usage=usage,
            bill_to="local_oauth",
        )

        assert result["total_cost"] == 0.0
        assert result["prompt_cost"] == 0.0
        assert result["completion_cost"] == 0.0
        assert result["pricing_available"] is True

    def test_gemini_flash_cost(self):
        """Test Gemini Flash cost calculation."""
        usage = {
            "prompt_tokens": 10000,
            "completion_tokens": 2000,
            "total_tokens": 12000,
        }
        result = calculate_cost(
            provider="google",
            model="gemini-1.5-flash",
            usage=usage,
            bill_to="byok",
        )

        # Input: 10K tokens * $0.000075 per 1K = $0.00075
        # Output: 2K tokens * $0.0003 per 1K = $0.0006
        # Total: $0.00135
        assert result["pricing_available"] is True
        assert abs(result["prompt_cost"] - 0.00075) < 1e-6
        assert abs(result["completion_cost"] - 0.0006) < 1e-6
        assert abs(result["total_cost"] - 0.00135) < 1e-6

    def test_gpt4o_cost(self):
        """Test GPT-4o cost calculation."""
        usage = {"prompt_tokens": 5000, "completion_tokens": 1000, "total_tokens": 6000}
        result = calculate_cost(
            provider="openai",
            model="gpt-4o",
            usage=usage,
            bill_to="byok",
        )

        # Input: 5K tokens * $0.0025 per 1K = $0.0125
        # Output: 1K tokens * $0.01 per 1K = $0.01
        # Total: $0.0225
        assert result["pricing_available"] is True
        assert abs(result["prompt_cost"] - 0.0125) < 1e-6
        assert abs(result["completion_cost"] - 0.01) < 1e-6
        assert abs(result["total_cost"] - 0.0225) < 1e-6

    def test_gemini_31_flash_lite_preview_cost(self):
        """Test Gemini 3.1 Flash-Lite preview cost calculation."""
        usage = {
            "prompt_tokens": 10000,
            "completion_tokens": 2000,
            "total_tokens": 12000,
        }
        result = calculate_cost(
            provider="google",
            model="gemini-3.1-flash-lite-preview",
            usage=usage,
            bill_to="byok",
        )

        # Input: 10K tokens * $0.00025 per 1K = $0.0025
        # Output: 2K tokens * $0.0015 per 1K = $0.003
        # Total: $0.0055
        assert result["pricing_available"] is True
        assert abs(result["prompt_cost"] - 0.0025) < 1e-6
        assert abs(result["completion_cost"] - 0.003) < 1e-6
        assert abs(result["total_cost"] - 0.0055) < 1e-6

    def test_gemini_3_flash_preview_cost(self):
        """Test Gemini 3 Flash preview cost calculation."""
        usage = {
            "prompt_tokens": 10000,
            "completion_tokens": 2000,
            "total_tokens": 12000,
        }
        result = calculate_cost(
            provider="google",
            model="gemini-3-flash-preview",
            usage=usage,
            bill_to="byok",
        )

        # Input: 10K tokens * $0.0005 per 1K = $0.005
        # Output: 2K tokens * $0.003 per 1K = $0.006
        # Total: $0.011
        assert result["pricing_available"] is True
        assert abs(result["prompt_cost"] - 0.005) < 1e-6
        assert abs(result["completion_cost"] - 0.006) < 1e-6
        assert abs(result["total_cost"] - 0.011) < 1e-6

    def test_zero_tokens(self):
        """Test cost with zero tokens."""
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        result = calculate_cost(
            provider="google",
            model="gemini-1.5-flash",
            usage=usage,
        )

        assert result["total_cost"] == 0.0
        assert result["prompt_cost"] == 0.0
        assert result["completion_cost"] == 0.0

    def test_missing_token_counts(self):
        """Test cost with missing token counts in usage dict."""
        usage = {}  # No token counts
        result = calculate_cost(
            provider="google",
            model="gemini-1.5-flash",
            usage=usage,
        )

        # Should default to 0
        assert result["total_cost"] == 0.0

    def test_unknown_model_no_pricing(self):
        """Test cost calculation for unknown model."""
        usage = {"prompt_tokens": 1000, "completion_tokens": 500}
        result = calculate_cost(
            provider="unknown",
            model="unknown-model",
            usage=usage,
        )

        assert result["pricing_available"] is False
        assert result["total_cost"] == 0.0
        assert result["prompt_cost"] == 0.0
        assert result["completion_cost"] == 0.0

    def test_free_preview_model(self):
        """Test free preview model (gemini-2.0-flash-exp)."""
        usage = {"prompt_tokens": 10000, "completion_tokens": 5000}
        result = calculate_cost(
            provider="google",
            model="gemini-2.0-flash-exp",
            usage=usage,
            bill_to="byok",
        )

        # This model is free during preview
        assert result["pricing_available"] is True
        assert result["total_cost"] == 0.0

    def test_large_token_counts(self):
        """Test cost with large token counts."""
        usage = {"prompt_tokens": 1_000_000, "completion_tokens": 500_000}
        result = calculate_cost(
            provider="google",
            model="gemini-1.5-pro",
            usage=usage,
        )

        # Input: 1M tokens * $0.00125 per 1K = $1.25
        # Output: 500K tokens * $0.005 per 1K = $2.5
        # Total: $3.75
        assert result["pricing_available"] is True
        assert abs(result["prompt_cost"] - 1.25) < 1e-6
        assert abs(result["completion_cost"] - 2.5) < 1e-6
        assert abs(result["total_cost"] - 3.75) < 1e-6

    def test_fractional_tokens(self):
        """Test cost with fractional token counts (edge case)."""
        usage = {"prompt_tokens": 500, "completion_tokens": 250}
        result = calculate_cost(
            provider="google",
            model="gemini-1.5-flash",
            usage=usage,
        )

        # Input: 0.5K tokens * $0.000075 = $0.0000375
        # Output: 0.25K tokens * $0.0003 = $0.000075
        assert result["pricing_available"] is True
        assert result["total_cost"] > 0


class TestEstimateCostForTokens:
    """Test quick cost estimation helper."""

    def test_estimate_gemini_flash(self):
        """Test cost estimation for Gemini Flash."""
        cost = estimate_cost_for_tokens(
            provider="google",
            model="gemini-1.5-flash",
            input_tokens=10000,
            output_tokens=2000,
        )

        # Should match calculate_cost result
        assert abs(cost - 0.00135) < 1e-6

    def test_estimate_gpt4o(self):
        """Test cost estimation for GPT-4o."""
        cost = estimate_cost_for_tokens(
            provider="openai",
            model="gpt-4o",
            input_tokens=5000,
            output_tokens=1000,
        )

        assert abs(cost - 0.0225) < 1e-6

    def test_estimate_unknown_model(self):
        """Test estimation for unknown model returns zero."""
        cost = estimate_cost_for_tokens(
            provider="unknown",
            model="unknown",
            input_tokens=1000,
            output_tokens=500,
        )

        assert cost == 0.0

    def test_estimate_zero_tokens(self):
        """Test estimation with zero tokens."""
        cost = estimate_cost_for_tokens(
            provider="google",
            model="gemini-1.5-flash",
            input_tokens=0,
            output_tokens=0,
        )

        assert cost == 0.0


class TestModelPricingDataclass:
    """Test ModelPricing dataclass."""

    def test_create_pricing(self):
        """Test creating a ModelPricing instance."""
        pricing = ModelPricing(
            provider="test",
            model="test-model",
            input_price_per_1k=0.001,
            output_price_per_1k=0.002,
        )

        assert pricing.provider == "test"
        assert pricing.model == "test-model"
        assert pricing.input_price_per_1k == 0.001
        assert pricing.output_price_per_1k == 0.002


class TestPricingTableCoverage:
    """Test that pricing table has expected models."""

    def test_gemini_models_present(self):
        """Test Gemini models are in pricing table."""
        models = [
            "gemini-2.0-flash-exp",
            "gemini-1.5-flash",
            "gemini-1.5-flash-8b",
            "gemini-1.5-pro",
        ]
        for model in models:
            pricing = get_model_pricing("google", model)
            assert pricing is not None, f"Missing pricing for {model}"

    def test_openai_models_present(self):
        """Test OpenAI models are in pricing table."""
        models = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo"]
        for model in models:
            pricing = get_model_pricing("openai", model)
            assert pricing is not None, f"Missing pricing for {model}"

    def test_all_prices_non_negative(self):
        """Test all pricing table entries have non-negative prices."""
        from brain_researcher.services.agent.cost_calculator import PRICING_TABLE

        for (provider, model), pricing in PRICING_TABLE.items():
            assert pricing.input_price_per_1k >= 0, (
                f"{provider}/{model} has negative input price"
            )
            assert pricing.output_price_per_1k >= 0, (
                f"{provider}/{model} has negative output price"
            )
