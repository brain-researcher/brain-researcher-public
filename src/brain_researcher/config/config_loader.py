"""Configuration loader for Brain Researcher data paths."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


class DataPathConfig:
    """Configuration manager for data paths."""

    _instance = None
    _config = None

    def __new__(cls):
        """Singleton pattern to ensure only one config instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize configuration."""
        if self._config is None:
            self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file.

        Returns:
            Configuration dictionary
        """
        # Prefer new layered configs if available
        try:
            from .datasets_loader import compose_data_paths

            composed = compose_data_paths()
            if composed:
                logger.info(
                    "Loaded dataset configuration from layered registry/overlays/local_mounts"
                )
                return composed
        except Exception as e:
            logger.debug(
                f"Layered dataset config load failed, falling back to legacy file: {e}"
            )

        # Legacy single-file fallback
        config_path = Path(__file__).parent / "data_paths.yaml"
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config = yaml.safe_load(f)
                logger.info(f"Loaded configuration from {config_path}")
                return config
            except Exception as e:
                logger.error(f"Failed to load legacy config: {e}")

        return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration if file loading fails.

        Paths resolve via env overrides or fall back to the repository's
        ``data/`` directory (see :func:`brain_researcher.config.get_data_root`).
        Supported env vars:

        - ``BR_DATA_ROOT``: override the default ``<repo>/data`` base
        - ``BR_OPENNEURO_ROOT``: external OpenNeuro mount (default: ``$BR_DATA_ROOT/openneuro``)
        - ``BR_OAK_MOUNT``: SLURM/HPC scratch mount (default: empty, disabled)

        Returns:
            Default configuration dictionary
        """
        from .paths import get_data_root

        data_root = Path(os.environ.get("BR_DATA_ROOT", str(get_data_root())))
        openneuro = os.environ.get("BR_OPENNEURO_ROOT", str(data_root / "openneuro"))
        oak_mount = os.environ.get("BR_OAK_MOUNT", "").strip()

        return {
            "local": {
                "niclip": str(data_root / "niclip"),
                "brainmap": str(data_root / "brainmap"),
                "openneuro_local": openneuro,
                "br_kg": str(data_root / "br_kg"),
                "cache": str(data_root / "cache"),
            },
            "oak_mount": {
                "enabled": bool(oak_mount),
                "base": oak_mount or str(data_root / "oak_mount"),
            },
            "dataset_priority": ["local", "oak_mount", "api"],
        }

    def get_path(
        self, source: str, dataset: Optional[str] = None, fallback: bool = True
    ) -> Optional[Path]:
        """Get path for a data source.

        Args:
            source: Source type ('local', 'oak_mount', 'api_sources')
            dataset: Specific dataset name (optional)
            fallback: Whether to fall back to alternatives if path doesn't exist

        Returns:
            Path object if found, None otherwise
        """
        # Handle nested paths (e.g., 'oak_mount.datasets.hcp_young_adult')
        parts = source.split(".")
        current = self._config

        try:
            for part in parts:
                current = current[part]

            if dataset:
                current = current.get(dataset)

            if current is None:
                return None

            path = Path(current) if isinstance(current, str) else None

            # Check if path exists
            if path and path.exists():
                return path
            elif path and not fallback:
                return path  # Return even if doesn't exist
            elif fallback and path:
                logger.debug(f"Path {path} not found, trying fallbacks")
                return self._find_fallback(source, dataset)
            else:
                return None

        except (KeyError, TypeError) as e:
            logger.debug(f"Path lookup failed for {source}.{dataset}: {e}")
            if fallback:
                return self._find_fallback(source, dataset)
            return None

    def _find_fallback(self, source: str, dataset: Optional[str]) -> Optional[Path]:
        """Find fallback path based on priority.

        Args:
            source: Original source type
            dataset: Dataset name

        Returns:
            Fallback path if found
        """
        priority = self._config.get("dataset_priority", ["local", "oak_mount", "api"])

        for source_type in priority:
            if source_type == source.split(".")[0]:
                continue  # Skip the original source

            # Try to find equivalent path in other sources
            if source_type == "local":
                alt_path = self.get_path(f"{source_type}.{dataset}", fallback=False)
                if alt_path and alt_path.exists():
                    logger.info(f"Using fallback: {alt_path}")
                    return alt_path
            elif source_type == "oak_mount":
                if self.is_oak_enabled():
                    alt_path = self.get_path(
                        f"{source_type}.datasets.{dataset}", fallback=False
                    )
                    if alt_path and alt_path.exists():
                        logger.info(f"Using fallback: {alt_path}")
                        return alt_path

        return None

    def is_oak_enabled(self) -> bool:
        """Check if OAK mount is enabled and accessible.

        Returns:
            True if OAK mount is enabled and base path exists
        """
        oak_config = self._config.get("oak_mount", {})
        enabled = oak_config.get("enabled", False)

        if not enabled:
            return False

        base_path = Path(oak_config.get("base", ""))
        return base_path.exists()

    def get_oak_datasets(self) -> List[str]:
        """Get list of available OAK datasets.

        Returns:
            List of dataset names
        """
        if not self.is_oak_enabled():
            return []

        datasets = self._config.get("oak_mount", {}).get("datasets", {})
        return list(datasets.keys())

    def get_api_config(self, source: str) -> Dict[str, Any]:
        """Get API configuration for a source.

        Args:
            source: API source name (e.g., 'pubmed', 'neurovault')

        Returns:
            API configuration dictionary
        """
        return self._config.get("api_sources", {}).get(source, {})

    def get_loader_defaults(self) -> Dict[str, Any]:
        """Get default loader configuration.

        Returns:
            Loader defaults dictionary
        """
        return self._config.get(
            "loader_defaults",
            {
                "max_workers": 4,
                "retry_attempts": 3,
                "retry_delay": 1.0,
                "use_cache": True,
                "batch_size": 100,
            },
        )

    def reload(self):
        """Reload configuration from file."""
        self._config = self._load_config()
        logger.info("Configuration reloaded")


# Global config instance
_config = None


def load_config() -> DataPathConfig:
    """Load or get existing configuration instance.

    Returns:
        DataPathConfig instance
    """
    global _config
    if _config is None:
        _config = DataPathConfig()
    return _config


def get_data_path(
    source: str, dataset: Optional[str] = None, fallback: bool = True
) -> Optional[Path]:
    """Convenience function to get data path.

    Args:
        source: Source type (e.g., 'local', 'oak_mount.datasets')
        dataset: Dataset name (optional)
        fallback: Whether to use fallback paths

    Returns:
        Path object if found

    Examples:
        >>> get_data_path('local', 'niclip')  # doctest: +SKIP
        PosixPath('<BR_DATA_ROOT>/niclip')

        >>> get_data_path('oak_mount.datasets', 'hcp_young_adult')  # doctest: +SKIP
        PosixPath('<BR_OAK_MOUNT>/data/HCP_YA')
    """
    config = load_config()
    return config.get_path(source, dataset, fallback)


if __name__ == "__main__":
    # Test configuration loading
    config = load_config()

    print("Configuration Test")
    print("=" * 50)
    print(f"OAK Enabled: {config.is_oak_enabled()}")
    print(f"OAK Datasets: {config.get_oak_datasets()}")
    print(f"\nLocal NICLIP: {get_data_path('local', 'niclip')}")
    print(f"Local BrainMap: {get_data_path('local', 'brainmap')}")
    print(f"\nPubMed API Config: {config.get_api_config('pubmed')}")
    print(f"\nLoader Defaults: {config.get_loader_defaults()}")
