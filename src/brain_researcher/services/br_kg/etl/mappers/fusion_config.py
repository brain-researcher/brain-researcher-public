#!/usr/bin/env python3
"""
Configuration loader for NiCLIP-LLM fusion system.

Handles loading and validation of fusion configuration from YAML files
with support for environment variable overrides.
"""

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, validator

from brain_researcher.config.mapping_resolver import get_repo_root

logger = logging.getLogger(__name__)


class SpatialConfig(BaseModel):
    """Spatial mapping configuration."""

    radius_mm: float = Field(10.0, ge=1.0, le=50.0)
    sigma: float = Field(3.33, ge=0.1, le=20.0)
    min_weight: float = Field(0.1, ge=0.0, le=1.0)


class EmbeddingConfig(BaseModel):
    """Embedding configuration."""

    n_dims: int = Field(128, ge=16, le=1024)
    cache_enabled: bool = True
    cache_path: str = "cache/niclip_embeddings.pkl"


class NormalizationConfig(BaseModel):
    """Normalization configuration."""

    method: str = Field("percentile", regex="^(percentile|log|linear)$")
    percentile_range: list = Field([5, 95])
    clip_outliers: bool = True

    @validator("percentile_range")
    def validate_percentile_range(cls, v):
        if len(v) != 2 or v[0] >= v[1] or v[0] < 0 or v[1] > 100:
            raise ValueError("Invalid percentile range")
        return v


class NiCLIPConfig(BaseModel):
    """NiCLIP configuration."""

    atlas: str = Field("difumo512", regex="^difumo(256|512|1024)$")
    spatial: SpatialConfig = SpatialConfig()
    embeddings: EmbeddingConfig = EmbeddingConfig()
    normalization: NormalizationConfig = NormalizationConfig()


class WeightConfig(BaseModel):
    """Weight configuration for fusion."""

    niclip: float = Field(0.5, ge=0.0, le=1.0)
    llm: float = Field(0.5, ge=0.0, le=1.0)

    @validator("llm")
    def validate_sum(cls, v, values):
        if "niclip" in values and abs(values["niclip"] + v - 1.0) > 0.01:
            raise ValueError("Weights must sum to 1.0")
        return v


class FusionWeights(BaseModel):
    """Task-specific fusion weights."""

    perceptual: WeightConfig = WeightConfig(niclip=0.7, llm=0.3)
    cognitive: WeightConfig = WeightConfig(niclip=0.5, llm=0.5)
    social: WeightConfig = WeightConfig(niclip=0.3, llm=0.7)
    default: WeightConfig = WeightConfig()


class FusionConfig(BaseModel):
    """Main fusion configuration."""

    niclip: NiCLIPConfig = NiCLIPConfig()
    weights: FusionWeights = FusionWeights()

    class Config:
        """Pydantic configuration."""

        validate_assignment = True


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """
    Load fusion configuration from YAML file.

    Args:
        config_path: Path to YAML config file. If None, uses default location.

    Returns:
        Configuration dictionary
    """
    # Default config path
    if config_path is None:
        config_path = os.environ.get(
            "FUSION_CONFIG_PATH", "configs/br-kg/br_kg_fusion_config.yaml"
        )

    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = get_repo_root() / config_file

    # Try multiple locations
    if not config_file.exists():
        # Try relative to module
        module_dir = Path(__file__).parent
        for candidate in [
            module_dir / config_path,
            get_repo_root() / config_path,
            Path.home() / ".brain_researcher" / config_path,
        ]:
            if candidate.exists():
                config_file = candidate
                break

    if not config_file.exists():
        logger.warning(f"Config file not found: {config_path}, using defaults")
        return get_default_config()

    try:
        with open(config_file) as f:
            config = yaml.safe_load(f)

        # Apply environment variable overrides
        config = apply_env_overrides(config)

        # Validate configuration
        # Note: For now, just return as-is. Full validation can be added later

        logger.info(f"Loaded configuration from {config_file}")
        return config

    except Exception as e:
        logger.error(f"Failed to load config from {config_file}: {e}")
        return get_default_config()


def apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """
    Apply environment variable overrides to configuration.

    Environment variables should be prefixed with FUSION_ and use
    double underscores for nested keys.

    Example:
        FUSION_NICLIP__ATLAS=difumo1024
        FUSION_WEIGHTS__PERCEPTUAL__NICLIP=0.8
    """
    for key, value in os.environ.items():
        if not key.startswith("FUSION_"):
            continue

        # Remove prefix and split by double underscore
        config_path = key[7:].lower().split("__")

        # Navigate to the nested location
        current = config
        for part in config_path[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        # Set the value (with type conversion)
        final_key = config_path[-1]
        try:
            # Try to parse as number
            if "." in value:
                current[final_key] = float(value)
            elif value.isdigit():
                current[final_key] = int(value)
            elif value.lower() in ("true", "false"):
                current[final_key] = value.lower() == "true"
            else:
                current[final_key] = value
        except:
            current[final_key] = value

    return config


def get_default_config() -> dict[str, Any]:
    """Get default configuration."""
    return {
        "niclip": {
            "atlas": "difumo512",
            "spatial": {"radius_mm": 10.0, "sigma": 3.33, "min_weight": 0.1},
            "embeddings": {
                "n_dims": 128,
                "cache_enabled": True,
                "cache_path": "cache/niclip_embeddings.pkl",
            },
            "normalization": {
                "method": "percentile",
                "percentile_range": [5, 95],
                "clip_outliers": True,
            },
        },
        "llm": {
            "model": "deepseek-reasoner",
            "api": {"url": "http://localhost:8000", "timeout": 30, "max_retries": 3},
            "ensemble": {"n_passes": 5, "temperature": 0.7, "aggregation": "frequency"},
        },
        "fusion": {
            "weights": {
                "perceptual": {"niclip": 0.7, "llm": 0.3},
                "cognitive": {"niclip": 0.5, "llm": 0.5},
                "social": {"niclip": 0.3, "llm": 0.7},
                "default": {"niclip": 0.5, "llm": 0.5},
            },
            "adjustments": {
                "direction_agreement_bonus": 0.1,
                "conflict_penalty": -0.05,
                "literature_boost": 0.15,
            },
            "thresholds": {
                "min_confidence": 0.1,
                "conflict_threshold": 0.3,
                "high_confidence": 0.8,
            },
        },
        "evaluation": {
            "metrics": [
                "precision_at_k",
                "recall_at_k",
                "f1_score",
                "spatial_dice_overlap",
                "expert_agreement",
            ],
            "k_values": [1, 3, 5],
        },
        "performance": {
            "cache": {"enabled": True, "backend": "redis", "ttl": 3600},
            "parallel": {"enabled": True, "n_workers": 4, "batch_size": 10},
        },
    }


def save_config(config: dict[str, Any], output_path: str):
    """
    Save configuration to YAML file.

    Args:
        config: Configuration dictionary
        output_path: Path to save YAML file
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Saved configuration to {output_file}")


def validate_config(config: dict[str, Any]) -> bool:
    """
    Validate configuration structure and values.

    Args:
        config: Configuration dictionary

    Returns:
        True if valid, False otherwise
    """
    try:
        # Check required top-level keys
        required_keys = ["niclip", "fusion"]
        for key in required_keys:
            if key not in config:
                logger.error(f"Missing required config key: {key}")
                return False

        # Validate weights sum to 1
        for task_type in ["perceptual", "cognitive", "social", "default"]:
            weights = config.get("fusion", {}).get("weights", {}).get(task_type, {})
            if weights:
                total = weights.get("niclip", 0) + weights.get("llm", 0)
                if abs(total - 1.0) > 0.01:
                    logger.error(f"Weights for {task_type} don't sum to 1.0: {total}")
                    return False

        return True

    except Exception as e:
        logger.error(f"Config validation error: {e}")
        return False


# Convenience function
def get_config() -> dict[str, Any]:
    """Get the current configuration."""
    return load_config()


if __name__ == "__main__":
    # Test configuration loading
    config = load_config()
    print("Loaded configuration:")
    print(yaml.dump(config, default_flow_style=False))

    # Test validation
    if validate_config(config):
        print("\n✅ Configuration is valid")
    else:
        print("\n❌ Configuration is invalid")

    # Test environment override
    os.environ["FUSION_NICLIP__ATLAS"] = "difumo1024"
    os.environ["FUSION_WEIGHTS__PERCEPTUAL__NICLIP"] = "0.8"
    os.environ["FUSION_WEIGHTS__PERCEPTUAL__LLM"] = "0.2"

    config_with_env = load_config()
    print("\nWith environment overrides:")
    print(f"Atlas: {config_with_env['niclip']['atlas']}")
    print(f"Perceptual weights: {config_with_env['fusion']['weights']['perceptual']}")
