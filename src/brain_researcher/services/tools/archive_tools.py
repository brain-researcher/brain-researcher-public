"""Archive download and search tools for neuroimaging datasets."""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from brain_researcher.core.ingestion import neuro_downloads
from brain_researcher.services.tools.tool_base import (
    NeuroToolWrapper,
    ToolResult,
)

logger = logging.getLogger(__name__)


class OpenNeuroDownloadArgs(BaseModel):
    """Arguments for OpenNeuro download."""

    dataset_id: str = Field(description="OpenNeuro dataset ID (e.g., ds000001)")
    output_dir: str = Field(description="Directory to download dataset to")
    execute: bool = Field(
        default=True,
        description="If true, perform the download; if false, return the recommended command/code only (preview mode)",
    )


class OpenNeuroDownloadTool(NeuroToolWrapper):
    """Tool for downloading datasets from OpenNeuro."""

    def get_tool_name(self) -> str:
        return "openneuro_download"

    def get_tool_description(self) -> str:
        return "Download a dataset from the OpenNeuro archive"

    def get_args_schema(self):
        return OpenNeuroDownloadArgs

    def _run(
        self, dataset_id: str, output_dir: str, execute: bool = True, **kwargs
    ) -> ToolResult:
        """Download the dataset unless execute=False for preview-only output."""

        from brain_researcher.services.tools.openneuro_tool import (
            get_openneuro_mount_root,
        )

        norm_id = dataset_id.split(":")[-1]
        mount_root = get_openneuro_mount_root()
        local_dir = mount_root / norm_id
        available_locally = local_dir.exists()

        # Choose destination: user-provided output_dir wins; otherwise fall back to a
        # writable working root (not the read-only mount). The router sometimes passes
        # placeholders such as "/path/to/output" or "/path/to/output/directory"—treat
        # any path that starts with "/path/to/" as "not provided".
        output_root = Path(
            os.getenv(
                "OPENNEURO_OUTPUT_ROOT",
                "/app/data/openneuro_work",
            )
        )
        if not output_root.exists():
            output_root.mkdir(parents=True, exist_ok=True)

        placeholder = output_dir and output_dir.startswith("/path/to/")
        if output_dir in (None, "") or placeholder:
            output_root_path = output_root
        else:
            output_root_path = Path(output_dir)
        dest = str(
            output_root_path
            if output_root_path.name == norm_id
            else output_root_path / norm_id
        )
        cmd = f"openneuro download {dataset_id} --dest {dest}"
        example_code = (
            f'from openneuro import download\ndownload("{dataset_id}", "{dest}")\n'
        )

        if not execute:
            # Always honour the requested output_dir. If a mount already exists, expose it
            # as a hint but still return the command for the requested destination.
            return ToolResult(
                status="success",
                data={
                    "dataset_id": dataset_id,
                    "output_dir": dest,
                    "local_path": str(local_dir) if available_locally else None,
                    "available_locally": available_locally,
                    "command": cmd,
                    "example_code": example_code,
                    "preview": True,
                    "execute": False,
                },
            )

        try:
            # If already present and dest is the mount path, avoid redundant download.
            if available_locally and dest == str(local_dir):
                path = str(local_dir)
            else:
                download_root = (
                    output_root_path.parent
                    if output_root_path.name == norm_id
                    else output_root_path
                )
                path = neuro_downloads.download_openneuro(
                    dataset_id, str(download_root)
                )
            return ToolResult(
                status="success",
                data={
                    "dataset_id": dataset_id,
                    "output_dir": path,
                    "command": cmd,
                    "example_code": example_code,
                    "preview": False,
                },
            )
        except Exception as e:
            logger.error(f"OpenNeuro download failed: {e}")
            return ToolResult(status="error", error=f"OpenNeuro download failed: {e}")


class OpenNeuroListArgs(BaseModel):
    """Arguments for listing OpenNeuro files."""

    dataset_id: str = Field(description="OpenNeuro dataset ID")


class OpenNeuroListFilesTool(NeuroToolWrapper):
    """Tool for listing files in an OpenNeuro dataset."""

    def get_tool_name(self) -> str:
        return "openneuro_list_files"

    def get_tool_description(self) -> str:
        return "List files available in an OpenNeuro dataset"

    def get_args_schema(self):
        return OpenNeuroListArgs

    def _run(self, dataset_id: str) -> ToolResult:
        try:
            files = neuro_downloads.list_openneuro_files(dataset_id)
            return ToolResult(
                status="success", data={"files": files, "n_files": len(files)}
            )
        except Exception as e:
            logger.error(f"Listing files failed: {e}")
            return ToolResult(status="error", error=f"Failed to list files: {e}")


class OpenNeuroCacheArgs(BaseModel):
    """Arguments for caching an OpenNeuro dataset via rsync."""

    dataset_id: str = Field(
        description="OpenNeuro dataset ID (e.g., ds000001). Must match format dsXXXXXX."
    )
    dest_root: str | None = Field(
        default=None,
        description=(
            "Destination root directory. Defaults to BR_DATA_ROOT if set, "
            "otherwise 'data/bids/'. The dataset will be cached to dest_root/<dataset_id>/"
        ),
    )
    validate_bids: bool = Field(
        default=True,
        description="Run BIDS Validator after caching (best-effort). Writes bids_validation.json.",
    )
    strict: bool = Field(
        default=True,
        description="If true, BIDS Validator treats warnings as failures.",
    )
    write_manifest: bool = Field(
        default=True,
        description="Generate dataset_manifest.json after caching (best-effort).",
    )
    manifest_mode: Literal["fast", "secure", "paranoid"] = Field(
        default="secure",
        description=(
            "Hash mode for dataset_manifest.json: 'fast' (path+size only), "
            "'secure' (first 1MB SHA-256), 'paranoid' (full SHA-256, use max_hash_mb to cap)."
        ),
    )
    include_derivatives: bool = Field(
        default=False,
        description="Include derivatives/ in dataset_manifest.json (default False).",
    )
    max_hash_mb: int | None = Field(
        default=None,
        description="For paranoid mode, cap per-file hashing at N MB (None = full file).",
    )
    register_local: bool = Field(
        default=True,
        description="Upsert this dataset into the local dataset registry (best-effort).",
    )
    execute: bool = Field(
        default=True,
        description="If False, return the rsync command without executing (preview mode)",
    )
    exclude: list[str] | None = Field(
        default=None,
        description=(
            "rsync --exclude patterns. Default (None) excludes ['derivatives/']. "
            "Pass empty list [] to include everything, or custom patterns like ['derivatives/', 'sourcedata/']."
        ),
    )


class OpenNeuroCacheTool(NeuroToolWrapper):
    """Tool for caching OpenNeuro datasets locally via rsync from the mount."""

    # OpenNeuro dataset ID format: ds + 6 digits
    _DATASET_ID_PATTERN = r"^ds\d{6}$"

    def get_tool_name(self) -> str:
        return "prefetch.openneuro_cache"

    def get_tool_description(self) -> str:
        return (
            "Cache an OpenNeuro dataset locally using rsync from the OpenNeuro mount. "
            "This is faster than downloading and provides a local copy for repeated analysis. "
            "By default excludes derivatives/ (pass exclude=[] to include everything)."
        )

    def get_args_schema(self):
        return OpenNeuroCacheArgs

    def _run(
        self,
        dataset_id: str,
        dest_root: str | None = None,
        validate_bids: bool = True,
        strict: bool = True,
        write_manifest: bool = True,
        manifest_mode: Literal["fast", "secure", "paranoid"] = "secure",
        include_derivatives: bool = False,
        max_hash_mb: int | None = None,
        register_local: bool = True,
        execute: bool = True,
        exclude: list[str] | None = None,
    ) -> ToolResult:
        import re
        import shutil

        from brain_researcher.services.tools.openneuro_tool import (
            get_openneuro_mount_root,
        )

        # Validate dataset_id format
        if not re.match(self._DATASET_ID_PATTERN, dataset_id):
            return ToolResult(
                status="error",
                error=f"Invalid dataset_id '{dataset_id}'. Must match format dsXXXXXX (e.g., ds000001).",
            )

        # Check rsync availability
        if not shutil.which("rsync"):
            return ToolResult(
                status="error",
                error="rsync command not found. Please install rsync.",
            )

        mount_root = get_openneuro_mount_root().resolve()
        source = (mount_root / dataset_id).resolve()

        # Path safety: ensure source is under mount_root (handles symlinks)
        try:
            source.relative_to(mount_root)
        except ValueError:
            return ToolResult(
                status="error",
                error=f"Invalid dataset path: {source} is not under mount root {mount_root}",
            )

        if not source.is_dir():
            return ToolResult(
                status="error",
                error=f"Dataset {dataset_id} not found in OpenNeuro mount at {mount_root}",
            )

        # Determine destination root
        if dest_root is None:
            dest_root = os.getenv("BR_DATA_ROOT", "data/bids")
        dest = Path(dest_root).resolve() / dataset_id

        # Ensure parent directory exists
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return ToolResult(
                status="error",
                error=f"Failed to create destination directory {dest.parent}: {e}",
            )

        # Default exclusions
        if exclude is None:
            exclude = ["derivatives/"]

        # Build rsync command (no --progress to avoid memory issues with capture_output)
        rsync_cmd = ["rsync", "-avh", "--partial"]
        for pattern in exclude:
            rsync_cmd.extend(["--exclude", pattern])
        rsync_cmd.extend([str(source) + "/", str(dest)])

        command_str = " ".join(rsync_cmd)

        if not execute:
            return ToolResult(
                status="success",
                data={
                    "dataset_id": dataset_id,
                    "source": str(source),
                    "dest": str(dest),
                    "exclude": exclude,
                    "command": command_str,
                    "preview": True,
                },
            )

        # Execute rsync (don't capture output to avoid memory issues)
        proc = subprocess.run(
            rsync_cmd,
            capture_output=False,  # Let output go to stdout/stderr directly
            check=False,
        )

        if proc.returncode != 0:
            return ToolResult(
                status="error",
                error=f"rsync failed with exit code {proc.returncode}",
                data={
                    "dataset_id": dataset_id,
                    "source": str(source),
                    "dest": str(dest),
                    "command": command_str,
                    "returncode": proc.returncode,
                },
            )

        # Post-sync: manifest + validation + registry (best-effort)
        post: dict[str, Any] = {}
        try:
            from brain_researcher.core.ingestion.bids_io import (
                validate_bids_dataset,
                write_bids_dataset_manifest,
            )

            if validate_bids:
                validation = validate_bids_dataset(dest.as_posix(), strict=strict)
                (dest / "bids_validation.json").write_text(
                    json.dumps(validation, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                post["bids_validation"] = validation

            if write_manifest:
                manifest = write_bids_dataset_manifest(
                    dest,
                    mode=manifest_mode,
                    include_derivatives=include_derivatives,
                    max_hash_mb=max_hash_mb,
                )
                post["dataset_manifest"] = {
                    "path": manifest.get("path"),
                    "manifest_sha256": manifest.get("manifest_sha256"),
                    "summary": manifest.get("summary"),
                }
        except Exception as e:
            post["postprocess_error"] = str(e)

        if register_local:
            try:
                from brain_researcher.core.datasets.bids_import import (
                    register_bids_dataset,
                )

                rec = register_bids_dataset(
                    dataset_id=dataset_id,
                    bids_root=dest,
                    source="openneuro_cache",
                    extra_meta={"openneuro_mount_root": str(mount_root)},
                )
                post["local_registry"] = {
                    "dataset_id": rec.dataset_id,
                    "bids_root": rec.bids_root,
                }
            except Exception as e:
                post["local_registry_error"] = str(e)

        return ToolResult(
            status="success",
            data={
                "dataset_id": dataset_id,
                "source": str(source),
                "dest": str(dest),
                "exclude": exclude,
                "command": command_str,
                "cached": True,
                **post,
            },
        )


class DANDIDownloadArgs(BaseModel):
    """Arguments for DANDI download."""

    dandiset_id: str = Field(description="DANDI set identifier")
    output_dir: str = Field(description="Output directory")
    include_assets: str = Field(default="all", description="Assets to include")
    execute: bool = Field(
        default=True,
        description="If true, perform the download. If false, just return the command/code to run manually.",
    )


class DANDIDownloadTool(NeuroToolWrapper):
    """Tool for downloading datasets from DANDI archive."""

    def get_tool_name(self) -> str:
        return "dandi_download"

    def get_tool_description(self) -> str:
        return "Download a dataset from the DANDI archive"

    def get_args_schema(self):
        return DANDIDownloadArgs

    def _run(
        self,
        dandiset_id: str,
        output_dir: str,
        include_assets: str = "all",
        execute: bool = True,
    ) -> ToolResult:
        """Download a DANDI dataset unless execute=False for preview-only output."""

        # Always return a runnable command / code snippet
        cli_cmd = ["dandi", "download", dandiset_id, "-o", output_dir]
        if include_assets and include_assets != "all":
            cli_cmd += ["--include", include_assets]
        command_str = " ".join(cli_cmd)

        example_code = (
            "from dandi.dandiapi import DandiAPIClient\n"
            "from pathlib import Path\n\n"
            "api = DandiAPIClient()\n"
            f'out = Path("{output_dir}")\n'
            "out.mkdir(parents=True, exist_ok=True)\n"
            f'api.get_dandiset("{dandiset_id}").download(out, include="{include_assets}")\n'
        )

        if not execute:
            return ToolResult(
                status="success",
                data={
                    "dandiset_id": dandiset_id,
                    "output_dir": output_dir,
                    "include_assets": include_assets,
                    "command": command_str,
                    "example_code": example_code,
                    "preview": True,
                    "execute": False,
                },
            )

        # execute=True → perform the download
        try:
            path = neuro_downloads.download_dandiset(
                dandiset_id, output_dir, include_assets
            )
            return ToolResult(
                status="success",
                data={
                    "dandiset_id": dandiset_id,
                    "output_dir": path,
                    "include_assets": include_assets,
                    "command": command_str,
                    "preview": False,
                    "execute": True,
                },
            )
        except Exception as e:
            logger.error(f"DANDI download failed: {e}")
            return ToolResult(status="error", error=f"DANDI download failed: {e}")


class DANDISearchArgs(BaseModel):
    """Arguments for DANDI search."""

    search_term: str = Field(description="Search term")
    max_results: int = Field(default=20, description="Maximum results")


class DANDISearchTool(NeuroToolWrapper):
    """Tool for searching DANDI archive."""

    def get_tool_name(self) -> str:
        return "dandi_search"

    def get_tool_description(self) -> str:
        return "Search the DANDI archive for datasets"

    def get_args_schema(self):
        return DANDISearchArgs

    def _run(self, search_term: str, max_results: int = 20) -> ToolResult:
        try:
            results = neuro_downloads.search_dandi(search_term, max_results)
            return ToolResult(
                status="success", data={"results": results, "n_results": len(results)}
            )
        except Exception as e:
            logger.error(f"DANDI search failed: {e}")
            return ToolResult(status="error", error=f"DANDI search failed: {e}")


class NeurovaultDownloadArgs(BaseModel):
    """Arguments for NeuroVault download."""

    collection_id: int = Field(description="NeuroVault collection id")
    output_dir: str = Field(description="Directory to store images")
    execute: bool = Field(
        default=True,
        description="If true, perform download; if false, return command/code preview only",
    )


class NeurovaultDownloadTool(NeuroToolWrapper):
    """Tool for downloading NeuroVault collections."""

    def get_tool_name(self) -> str:
        return "neurovault_download_collection"

    def get_tool_description(self) -> str:
        return "Download all images from a NeuroVault collection"

    def get_args_schema(self):
        return NeurovaultDownloadArgs

    def _run(
        self, collection_id: int, output_dir: str, execute: bool = True
    ) -> ToolResult:
        """Download a NeuroVault collection unless execute=False for preview-only output."""
        command = f"python -m neuro_researcher.downloads.neurovault --collection {collection_id} --output {output_dir}"
        example_code = (
            "from brain_researcher.core.ingestion import neuro_downloads\n"
            f'neuro_downloads.download_neurovault_collection({collection_id}, "{output_dir}")\n'
        )

        if not execute:
            return ToolResult(
                status="success",
                data={
                    "collection_id": collection_id,
                    "output_dir": output_dir,
                    "command": command,
                    "example_code": example_code,
                    "preview": True,
                    "execute": False,
                },
            )

        try:
            paths = neuro_downloads.download_neurovault_collection(
                collection_id, output_dir
            )
            return ToolResult(
                status="success",
                data={
                    "paths": paths,
                    "n_files": len(paths),
                    "command": command,
                    "preview": False,
                    "execute": True,
                },
            )
        except Exception as e:
            logger.error(f"NeuroVault download failed: {e}")
            return ToolResult(status="error", error=f"NeuroVault download failed: {e}")


class NeurovaultSearchArgs(BaseModel):
    """Arguments for NeuroVault search."""

    text_query: str = Field(description="Search query")
    threshold: float = Field(default=0.8, description="Relevance threshold")


class NeurovaultSearchTool(NeuroToolWrapper):
    """Tool for searching NeuroVault images."""

    def get_tool_name(self) -> str:
        return "neurovault_search_images"

    def get_tool_description(self) -> str:
        return "Search NeuroVault for images matching a text query"

    def get_args_schema(self):
        return NeurovaultSearchArgs

    def _run(self, text_query: str, threshold: float = 0.8) -> ToolResult:
        try:
            results = neuro_downloads.search_neurovault_images(text_query, threshold)
            return ToolResult(
                status="success", data={"results": results, "n_results": len(results)}
            )
        except Exception as e:
            logger.error(f"NeuroVault search failed: {e}")
            return ToolResult(status="error", error=f"NeuroVault search failed: {e}")


class ArchiveTools:
    """Collection of archive download/search tools."""

    def __init__(self):
        self.openneuro_download = OpenNeuroDownloadTool()
        self.openneuro_list_files = OpenNeuroListFilesTool()
        self.openneuro_cache = OpenNeuroCacheTool()
        self.dandi_download = DANDIDownloadTool()
        self.dandi_search = DANDISearchTool()
        self.neurovault_download = NeurovaultDownloadTool()
        self.neurovault_search = NeurovaultSearchTool()

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        return [
            self.openneuro_download,
            self.openneuro_list_files,
            self.openneuro_cache,
            self.dandi_download,
            self.dandi_search,
            self.neurovault_download,
            self.neurovault_search,
        ]

    def get_tool_by_name(self, name: str) -> NeuroToolWrapper | None:
        tool_map = {
            "openneuro_download": self.openneuro_download,
            "openneuro_list_files": self.openneuro_list_files,
            "prefetch.openneuro_cache": self.openneuro_cache,
            "dandi_download": self.dandi_download,
            "dandi_search": self.dandi_search,
            "neurovault_download_collection": self.neurovault_download,
            "neurovault_search_images": self.neurovault_search,
        }
        return tool_map.get(name)
