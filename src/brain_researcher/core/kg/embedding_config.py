"""
Configuration system for the embedding index.

Supports environment variables, config files, and defaults.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingConfig:
    """Configuration for the embedding index system."""

    # Model configuration
    model_name: str = "all-MiniLM-L6-v2"
    model_cache_dir: str | None = None
    normalize_embeddings: bool = True

    # Index configuration
    db_dir: str = "brain_researcher/core/kg/db"
    shard_size: int = 10000
    index_type: str = "IndexFlatIP"  # or "IndexFlatL2"

    # Multimodal configuration
    enable_multimodal: bool = True
    figure_embedding_dim: int = 512
    concatenation_strategy: str = "simple"  # or "weighted"

    # Refresh configuration
    enable_periodic_refresh: bool = True
    refresh_interval: int = 86400  # 24 hours in seconds
    refresh_batch_size: int = 100

    # Performance configuration
    max_concurrent_searches: int = 10
    search_timeout: float = 30.0
    embedding_batch_size: int = 32

    # Monitoring configuration
    enable_metrics: bool = True
    metrics_port: int = 9090
    log_slow_queries: bool = True
    slow_query_threshold: float = 1.0  # seconds

    @classmethod
    def from_env(cls) -> "EmbeddingConfig":
        """Load configuration from environment variables."""
        config_dict = {}

        # Map environment variables to config fields
        env_mapping = {
            "EMBEDDING_MODEL_NAME": "model_name",
            "EMBEDDING_MODEL_CACHE": "model_cache_dir",
            "EMBEDDING_DB_DIR": "db_dir",
            "EMBEDDING_SHARD_SIZE": ("shard_size", int),
            "EMBEDDING_INDEX_TYPE": "index_type",
            "EMBEDDING_REFRESH_INTERVAL": ("refresh_interval", int),
            "EMBEDDING_METRICS_PORT": ("metrics_port", int),
            "EMBEDDING_SLOW_QUERY_THRESHOLD": ("slow_query_threshold", float),
        }

        for env_var, config_field in env_mapping.items():
            value = os.environ.get(env_var)
            if value is not None:
                if isinstance(config_field, tuple):
                    field_name, converter = config_field
                    try:
                        config_dict[field_name] = converter(value)
                    except ValueError:
                        logger.warning(f"Invalid value for {env_var}: {value}")
                else:
                    config_dict[config_field] = value

        return cls(**config_dict)

    @classmethod
    def from_file(cls, config_path: str) -> "EmbeddingConfig":
        """Load configuration from a JSON file."""
        try:
            with open(config_path) as f:
                config_dict = json.load(f)
            return cls(**config_dict)
        except Exception as e:
            logger.error(f"Failed to load config from {config_path}: {e}")
            return cls()

    @classmethod
    def load(cls, config_path: str | None = None) -> "EmbeddingConfig":
        """
        Load configuration with the following priority:
        1. Provided config file
        2. Environment variables
        3. Default values
        """
        # Start with defaults
        config = cls()

        # Override with config file if provided
        if config_path and os.path.exists(config_path):
            config = cls.from_file(config_path)

        # Override with environment variables
        env_config = cls.from_env()
        for field_name in config.__dataclass_fields__:
            env_value = getattr(env_config, field_name)
            default_value = config.__dataclass_fields__[field_name].default
            if env_value != default_value:
                setattr(config, field_name, env_value)

        return config

    def validate(self) -> bool:
        """Validate configuration values."""
        errors = []

        if self.shard_size <= 0:
            errors.append("shard_size must be positive")

        if self.refresh_interval <= 0:
            errors.append("refresh_interval must be positive")

        if self.index_type not in ["IndexFlatIP", "IndexFlatL2"]:
            errors.append(f"Unknown index_type: {self.index_type}")

        if self.concatenation_strategy not in ["simple", "weighted"]:
            errors.append(
                f"Unknown concatenation_strategy: {self.concatenation_strategy}"
            )

        if errors:
            for error in errors:
                logger.error(f"Config validation error: {error}")
            return False

        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }

    def save(self, config_path: str) -> None:
        """Save configuration to a JSON file."""
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


# Global config instance
_config: EmbeddingConfig | None = None


def get_config(config_path: str | None = None, reload: bool = False) -> EmbeddingConfig:
    """
    Get the global configuration instance.

    Args:
        config_path: Optional path to config file
        reload: Force reload of configuration

    Returns:
        EmbeddingConfig instance
    """
    global _config

    if _config is None or reload:
        _config = EmbeddingConfig.load(config_path)
        if not _config.validate():
            logger.warning("Configuration validation failed, using defaults")
            _config = EmbeddingConfig()

    return _config


# Example usage
if __name__ == "__main__":
    # Load config
    config = get_config()
    print("Default config:", config.to_dict())

    # Save example config
    example_config = EmbeddingConfig(
        model_name="sentence-transformers/all-mpnet-base-v2",
        shard_size=50000,
        refresh_interval=3600,
    )
    example_config.save("knowledge/config/embedding_config.json")
    print("\nExample config saved to knowledge/config/embedding_config.json")
