"""Configuration management for Brain Researcher."""

from .config_loader import DataPathConfig, get_data_path, load_config
from .mapping_resolver import (
    MappingSpec,
    clear_mapping_registry_cache,
    get_alias_hit_counter_path,
    get_mapping_registry_path,
    load_mapping_registry,
    read_alias_hit_counts,
    resolve_mapping_path,
)
from .paths import (
    clear_path_caches,
    get_apps_root,
    get_config_root,
    get_data_root,
    get_package_root,
    get_repo_root,
    get_src_root,
    resolve_from_config,
    resolve_from_repo,
)
from .run_artifacts import (
    get_metadata_root,
    get_metadata_root_aliases,
    get_metadata_roots_for_read,
)

__all__ = [
    "DataPathConfig",
    "MappingSpec",
    "clear_path_caches",
    "clear_mapping_registry_cache",
    "get_apps_root",
    "get_config_root",
    "get_data_root",
    "get_alias_hit_counter_path",
    "get_data_path",
    "get_mapping_registry_path",
    "get_metadata_root",
    "get_metadata_root_aliases",
    "get_metadata_roots_for_read",
    "get_package_root",
    "get_repo_root",
    "get_src_root",
    "load_config",
    "load_mapping_registry",
    "read_alias_hit_counts",
    "resolve_from_config",
    "resolve_from_repo",
    "resolve_mapping_path",
]
