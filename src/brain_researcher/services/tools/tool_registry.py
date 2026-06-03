"""
Tool registry system for the BR-KG LangGraph system.

Provides automatic tool discovery, registration, and intelligent tool selection
based on task descriptions.
"""

import importlib
import inspect
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from langchain_core.tools import StructuredTool
except ImportError:  # pragma: no cover
    from langchain.tools import StructuredTool

from langchain_community.vectorstores import FAISS

from brain_researcher.core.utils import configure_mne_environment
from brain_researcher.services.tools.dependency_inspector import (
    ManifestLoadError,
    collect_dependency_status,
    summarise_missing_by_category,
)

# Import base classes
from brain_researcher.services.tools.tool_base import NeuroToolWrapper

# Back-compat alias
NeuroToolWrapper = NeuroToolWrapper

# Import package-based capabilities (preferred approach)
# REFACTORING: Commented out - capabilities being replaced by direct tool implementations
# from brain_researcher.tools.capabilities import (
#     SkullStripCapability,
#     RegistrationCapability,
#     SegmentationCapability,
#     BiasCorrectionCapability,
#     CAPABILITIES
# )
CAPABILITIES = {}  # Empty dict to avoid breaking code below

from brain_researcher.services.tools.afni_clustsim_tool import AFNITools

# Import legacy individual tools (will be gradually replaced by capabilities)
from brain_researcher.services.tools.ants_tool import ANTsTools
from brain_researcher.services.tools.archive_tools import ArchiveTools
from brain_researcher.services.tools.behavior_tools import BehaviorTools
from brain_researcher.services.tools.bids_tools import BIDSTools
from brain_researcher.services.tools.br_kg_query_tool import BRKGQueryTools
from brain_researcher.services.tools.br_kg_tools import BRKGTools
from brain_researcher.services.tools.canonical_runtime_adapter import (
    CanonicalRuntimeAdapter,
)
from brain_researcher.services.tools.conn_tool import CONNTools
from brain_researcher.services.tools.cpac_tool import CPACTools
from brain_researcher.services.tools.dataset_resources_tool import (
    DatasetDescribeTool,
    DatasetResourcesTool,
)
from brain_researcher.services.tools.dl_pytorch_tool import DLPyTorchTools
from brain_researcher.services.tools.fitlins_tool import FitLinsTools
from brain_researcher.services.tools.fmri_tools import FMRITools
from brain_researcher.services.tools.fmriprep_tool import FMRIPrepTools
from brain_researcher.services.tools.freesurfer_tool import FreeSurferTools
from brain_researcher.services.tools.fsl_bedpostx_tool import FSLBEDPOSTXTools
from brain_researcher.services.tools.fsl_bet_tool import FSLBETTools
from brain_researcher.services.tools.fsl_feat_tool import FSLFEATTools
from brain_researcher.services.tools.fsl_fix_tool import FSLFIXTools
from brain_researcher.services.tools.fsl_flirt_tool import FSLFLIRTTools
from brain_researcher.services.tools.fsl_fnirt_tool import FSLFNIRTTools
from brain_researcher.services.tools.fsl_melodic_tool import FSLMELODICTools
from brain_researcher.services.tools.fsl_palm_tool import FSLPALMTools
from brain_researcher.services.tools.grandmaster_tools import GrandMasterTools
from brain_researcher.services.tools.hcp_workbench_tool import HCPWorkbenchTools
from brain_researcher.services.tools.jobs_tool import JobsTools
from brain_researcher.services.tools.kg_novelty_tools import KGNoveltyTools
from brain_researcher.services.tools.metadata_loader import inject_metadata
from brain_researcher.services.tools.mixed_effects_tool import MixedEffectsTools
from brain_researcher.services.tools.mne_connectivity_tool import MNEConnectivityTools
from brain_researcher.services.tools.mne_ica_tool import MNEICATools
from brain_researcher.services.tools.mne_preprocessing_tool import MNEPreprocessingTools
from brain_researcher.services.tools.mne_source_tool import MNESourceTools
from brain_researcher.services.tools.mne_timefreq_tool import MNETimeFreqTools
from brain_researcher.services.tools.multiple_comparison_tool import (
    MultipleComparisonTools,
)
from brain_researcher.services.tools.neuroassistant_tools import NeuroassistantTools

# from brain_researcher.services.tools.neurosynth_tools import NeuroSynthTools  # Temporarily disabled - numpy compatibility issue
from brain_researcher.services.tools.neurodesk_tools import NeurodeskTools
from brain_researcher.services.tools.nilearn_connectivity import (
    register_connectivity_tools,
)

# Import new organized Nilearn modules
from brain_researcher.services.tools.nilearn_glm import register_glm_tools
from brain_researcher.services.tools.nilearn_mvpa import register_mvpa_tools
from brain_researcher.services.tools.nilearn_preprocessing import (
    register_preprocessing_tools,
)
from brain_researcher.services.tools.nilearn_viz import register_nilearn_viz_tools
from brain_researcher.services.tools.nipype_runner_tool import NipypeRunnerTools
from brain_researcher.services.tools.nipype_tool import NipypeTools
from brain_researcher.services.tools.nwb_tools import NWBTools
from brain_researcher.services.tools.openneuro_tool import OpenNeuroTools
from brain_researcher.services.tools.permutation_testing_tool import (
    PermutationTestingTools,
)
from brain_researcher.services.tools.pipeline_search_tool import PipelineSearchTool
from brain_researcher.services.tools.pipeline_tools import PipelineTools
from brain_researcher.services.tools.qc_tools import QCTools
from brain_researcher.services.tools.qsiprep_tool import QSIPrepTools
from brain_researcher.services.tools.spec import spec_from_tool
from brain_researcher.services.tools.spm12_tool import SPM12Tools
from brain_researcher.services.tools.statsmodels_glm_tool import StatsmodelsGLMTools
from brain_researcher.services.tools.workflow_fallback_tools import (
    WorkflowFallbackTools,
)
from brain_researcher.services.tools.xcpd_tool import XCPDTools

# from brain_researcher.services.tools.nilearn_tools import NilearnTools  # Temporarily disabled - causes import hang

# Import new integration modules (relocated into the tools layer in round 2 of
# the services-layer DAG work; previously lived under ``services.agent``).
try:
    from brain_researcher.services.tools.deduplication_integration import (
        AgentDataDeduplication,
    )
    from brain_researcher.services.tools.plugin_integration import AgentPluginManager
    from brain_researcher.services.tools.streaming_integration import (
        AgentStreamingManager,
    )
    from brain_researcher.services.tools.subscription_integration import (
        AgentSubscriptionManager,
    )

    INTEGRATIONS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Some agent integrations not available: {e}")
    INTEGRATIONS_AVAILABLE = False


# NiWrap tools - search/schema/execute wrappers for ~1900 neuroimaging tools
from brain_researcher.services.tools.niwrap_tools import NiWrapTools

logger = logging.getLogger(__name__)

# Import adapter for UnifiedToolRegistry integration
from brain_researcher.services.tools.adapter import wrap_structured_tools

TOOLS_PACKAGE = __name__.rsplit(".", 1)[0]
TOOLS_DIR = Path(__file__).resolve().parent
MODALITY_AUTO_PREFIXES = (
    "ieeg_",
    "eeg_",
    "fixed_",
    "hrf_",
    "physio_",
    "pnm_",
    "cvr_",
    "qbold_",
    "calibrated_",
    "pupillometry_",
    "reproducibility_",
    "dmri_",
    "smri_",
    "pet_",
    "meta_",
    "kg_",
    "coreg_",
    "parcellation_",
    "label_",
    "resolve_",
    "list_",
    "fetch_",
    "extract_",
    "epoch_",
    "timefreq_",
    "connectivity_",
    "demo_",
    "nilearn_",
)

_REGISTRY_BACKEND_ADAPTER = "adapter"
_REGISTRY_BACKEND_LEGACY = "legacy"
_VALID_REGISTRY_BACKENDS = {
    _REGISTRY_BACKEND_ADAPTER,
    _REGISTRY_BACKEND_LEGACY,
}
_VALID_MUTATION_MODES = {"compat", "readonly"}


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _iter_auto_registry_tools() -> list[NeuroToolWrapper]:
    """
    Discover modality-prefixed stub tools without hardcoding imports.

    Only files following the agreed naming convention (e.g., `ieeg_*.py`) are
    considered to avoid double-registering the legacy tool modules that are
    already wired up elsewhere in this registry.
    """

    instances: list[NeuroToolWrapper] = []

    for module_path in TOOLS_DIR.glob("*_tool.py"):
        stem = module_path.stem
        if not stem.startswith(MODALITY_AUTO_PREFIXES):
            continue

        module_name = f"{TOOLS_PACKAGE}.{stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - import failures are logged only
            logger.debug("Auto-registry skipping %s: %s", module_name, exc)
            continue

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if not inspect.isclass(attr):
                continue

            if issubclass(attr, NeuroToolWrapper) and attr is not NeuroToolWrapper:
                try:
                    instances.append(attr())
                except Exception as exc:
                    logger.debug(
                        "Auto-registry failed to instantiate %s.%s: %s",
                        module_name,
                        attr_name,
                        exc,
                    )
                continue

            if not attr_name.endswith("Tools") or not hasattr(attr, "get_all_tools"):
                continue

            try:
                factory = attr()
                tool_objs = factory.get_all_tools()
            except Exception as exc:  # pragma: no cover - defensive logging only
                logger.debug(
                    "Auto-registry failed to initialize %s.%s: %s",
                    module_name,
                    attr_name,
                    exc,
                )
                continue

            for tool in tool_objs or []:
                if isinstance(tool, NeuroToolWrapper):
                    instances.append(tool)

    return instances


class ToolRegistry:
    """
    Registry for managing and discovering tools.

    Following Biomni's pattern of automatic tool discovery and intelligent selection.
    """

    def __init__(
        self,
        auto_discover: bool = True,
        use_capabilities: bool = True,
        enable_integrations: bool = True,
        light_mode: bool = False,
        source_backend: str | None = None,
    ):
        """
        Initialize the tool registry.

        Args:
            auto_discover: Whether to automatically discover tools on init
            use_capabilities: Whether to use package-based capabilities (recommended)
            enable_integrations: Whether to enable new integration capabilities
            light_mode: Whether to use light discovery mode (skip heavy probing)
            source_backend: Tool source backend override ("adapter" or "legacy")
        """
        # Check for light mode from environment
        self.light_mode = light_mode or os.environ.get("TOOL_DISCOVERY_MODE") == "light"

        self.tools: dict[str, NeuroToolWrapper] = {}
        self.tool_descriptions: dict[str, str] = {}
        self.tool_embeddings: FAISS | None = None
        self.embedding_model = None
        self.tool_documents: list[dict[str, Any]] = []  # Initialize early
        self.use_capabilities = use_capabilities
        self.capabilities = {}

        requested_backend = (
            source_backend
            or os.getenv("BR_TOOL_REGISTRY_BACKEND")
            or _REGISTRY_BACKEND_ADAPTER
        )
        backend_normalized = str(requested_backend).strip().lower()
        if backend_normalized not in _VALID_REGISTRY_BACKENDS:
            logger.warning(
                "Unknown BR_TOOL_REGISTRY_BACKEND=%r, defaulting to '%s'",
                requested_backend,
                _REGISTRY_BACKEND_ADAPTER,
            )
            backend_normalized = _REGISTRY_BACKEND_ADAPTER
        self.source_backend = backend_normalized

        mutation_mode = (
            str(os.getenv("BR_TOOL_REGISTRY_MUTATION_MODE", "compat")).strip().lower()
        )
        if mutation_mode not in _VALID_MUTATION_MODES:
            logger.warning(
                "Unknown BR_TOOL_REGISTRY_MUTATION_MODE=%r, defaulting to 'compat'",
                mutation_mode,
            )
            mutation_mode = "compat"
        self.mutation_mode = mutation_mode
        self.shadow_compare = _truthy(os.getenv("BR_TOOL_REGISTRY_SHADOW_COMPARE"))
        self.fail_open = _truthy(os.getenv("BR_TOOL_REGISTRY_FAIL_OPEN"))

        # Integration managers
        self.enable_integrations = enable_integrations and INTEGRATIONS_AVAILABLE
        self.subscription_manager: AgentSubscriptionManager | None = None
        self.streaming_manager: AgentStreamingManager | None = None
        self.deduplication_manager: AgentDataDeduplication | None = None
        self.plugin_manager: AgentPluginManager | None = None

        # Integration statistics
        self.integration_stats = {
            "subscriptions_active": 0,
            "streaming_active": False,
            "deduplication_active": False,
            "plugins_loaded": 0,
        }

        if auto_discover:
            if self.source_backend == _REGISTRY_BACKEND_LEGACY:
                self._discover_tools()
            else:
                self._discover_tools_from_canonical_adapter()
            if use_capabilities:
                self._register_package_capabilities()
            self._build_tool_index()

    @classmethod
    def from_env(
        cls,
        auto_discover: bool = True,
        use_capabilities: bool = True,
        enable_integrations: bool = True,
        light_mode: bool | None = None,
    ) -> "ToolRegistry":
        """Construct registry from environment defaults.

        Supports:
        - BR_TOOL_REGISTRY_BACKEND=adapter|legacy
        - BR_TOOL_REGISTRY_LIGHT_MODE=1|0
        """

        resolved_light_mode = light_mode
        if resolved_light_mode is None:
            resolved_light_mode = _truthy(os.getenv("BR_TOOL_REGISTRY_LIGHT_MODE"))
        return cls(
            auto_discover=auto_discover,
            use_capabilities=use_capabilities,
            enable_integrations=enable_integrations,
            light_mode=bool(resolved_light_mode),
            source_backend=os.getenv("BR_TOOL_REGISTRY_BACKEND"),
        )

    def _discover_tools_from_canonical_adapter(self) -> None:
        """Primary discovery path: canonical registry + optional compat merge."""
        adapter_step = "initialize_adapter"
        try:
            adapter = CanonicalRuntimeAdapter()

            adapter_step = "load_runtime_tools"
            canonical_tools = adapter.load_runtime_tools()

            adapter_step = "register_runtime_tools"
            for tool in canonical_tools:
                self.register_tool(tool)

            logger.info(
                "ToolRegistry(adapter) loaded %d canonical tools", len(canonical_tools)
            )

            if self.mutation_mode == "compat":
                adapter_step = "build_legacy_supplement_registry"
                legacy_registry = self._build_legacy_supplement_registry()

                adapter_step = "merge_prefer_primary"
                merged, report = adapter.merge_prefer_primary(
                    self.get_all_tools(), legacy_registry.get_all_tools()
                )
                self.tools = {tool.get_tool_name(): tool for tool in merged}
                self.tool_descriptions = {
                    tool.get_tool_name(): tool.get_tool_description() for tool in merged
                }
                logger.info(
                    "ToolRegistry(adapter) merged %d legacy-only tools (collisions=%d)",
                    report.added,
                    report.collisions,
                )
                if self.shadow_compare:
                    adapter_step = "emit_shadow_compare"
                    self._emit_shadow_compare(report.collision_ids)

            # Ensure declarative workflow wrappers stay available in adapter mode.
            adapter_step = "register_grandmaster_tools"
            self._register_grandmaster_tools()

            adapter_step = "register_prefixed_stub_tools"
            self._register_prefixed_stub_tools()
        except Exception as exc:
            context = (
                "ToolRegistry(adapter) failed during canonical discovery step "
                f"'{adapter_step}': {exc}"
            )
            if self.fail_open:
                logger.warning("%s", context)
                logger.warning(
                    "BR_TOOL_REGISTRY_FAIL_OPEN enabled, falling back to legacy discovery"
                )
                self.tools.clear()
                self.tool_descriptions.clear()
                self._discover_tools()
                return

            logger.exception("%s", context)
            raise

    def _build_legacy_supplement_registry(self) -> "ToolRegistry":
        """Build a legacy-backed registry for compat merging."""

        return ToolRegistry(
            auto_discover=True,
            use_capabilities=False,
            enable_integrations=False,
            light_mode=self.light_mode,
            source_backend=_REGISTRY_BACKEND_LEGACY,
        )

    def _emit_shadow_compare(self, collision_ids: tuple[str, ...]) -> None:
        if not collision_ids:
            logger.info("ToolRegistry shadow compare: no canonical/legacy collisions")
            return
        logger.info(
            "ToolRegistry shadow compare: %d collisions (sample=%s)",
            len(collision_ids),
            list(collision_ids[:10]),
        )

    def _load_from_unified_registry(self) -> list[NeuroToolWrapper]:
        """Load tools from UnifiedToolRegistry and wrap as NeuroToolWrapper.

        This method integrates with the canonical UnifiedToolRegistry, wrapping
        its StructuredTool instances as NeuroToolWrapper for compatibility
        with existing agent code.

        Returns:
            List of NeuroToolWrapper instances from UnifiedToolRegistry
        """
        try:
            from brain_researcher.services.tools import UnifiedToolRegistry

            unified = UnifiedToolRegistry()
            structured_tools = unified.get_all_tools()
            wrapped = wrap_structured_tools(structured_tools)
            logger.info(
                "Loaded %d tools from UnifiedToolRegistry (wrapped as NeuroToolWrapper)",
                len(wrapped),
            )
            return wrapped
        except Exception as e:
            logger.warning(f"Failed to load from UnifiedToolRegistry: {e}")
            return []

    def _register_package_capabilities(self):
        """Register package-based capabilities as tools."""
        logger.info("Registering package capabilities...")

        # Create wrapper tools for each capability
        for name, capability_class in CAPABILITIES.items():
            try:
                capability = capability_class()
                self.capabilities[name] = capability
                backends = capability.get_available_backends()
                logger.info(
                    f"Capability '{name}' has {len(backends)} backends available"
                )
            except Exception as e:
                logger.warning(f"Failed to register capability '{name}': {e}")

        # Register Gemini CLI wrappers if available (can be disabled via env)
        if os.getenv("DISABLE_GEMINI_CLI", "0").lower() in {"1", "true", "yes"}:
            logger.info(
                "DISABLE_GEMINI_CLI set - skipping Gemini CLI tool registration"
            )
        else:
            try:
                from brain_researcher.services.tools import gemini_cli_tools

                for tool in gemini_cli_tools.get_all_tools():
                    self.register_tool(tool)
                logger.info("Registered Gemini CLI tools for chat/fs support")
            except Exception as exc:  # pragma: no cover - optional dependency
                logger.debug("Gemini CLI tools not registered: %s", exc)

        try:
            from brain_researcher.services.tools import ibl_tools

            for tool in ibl_tools.get_all_tools():
                self.register_tool(tool)
            logger.info("Registered repo-owned IBL tools")
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("IBL tools not registered: %s", exc)

        # Load additional capabilities from YAML (comma-separated via BR_CAPABILITIES_YAML)
        yaml_files = os.environ.get(
            "BR_CAPABILITIES_YAML", "capabilities.gemini_cli.yaml"
        )
        from brain_researcher.config.paths import get_config_root

        catalog_dir = get_config_root() / "catalog"
        for fname in [f.strip() for f in yaml_files.split(",") if f.strip()]:
            path = catalog_dir / fname
            if not path.exists():
                logger.debug("Capabilities YAML not found: %s", path)
                continue
            try:
                self._register_yaml_capabilities(path)
                logger.info("Registered tools from YAML: %s", fname)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to load capabilities YAML %s: %s", fname, exc)

    def _register_yaml_capabilities(self, path: Path) -> None:
        import yaml

        data = yaml.safe_load(path.read_text()) or {}
        for item in data.get("tools", []) or []:
            entry = item.get("entrypoint")
            if not entry:
                continue
            try:
                module_name, cls_name = entry.rsplit(".", 1)
                mod = importlib.import_module(module_name)
                tool_cls = getattr(mod, cls_name)
                tool = tool_cls()
                self.register_tool(tool)
            except Exception as exc:
                logger.debug(
                    "Skip tool from %s entrypoint=%s: %s", path.name, entry, exc
                )

    def _report_dependency_health(self) -> None:
        """
        Emit a structured report of missing dependencies prior to discovery.

        The manifest mirrors the Biomni approach so we can distinguish between
        Python packages, CLI tools, container runtimes, and environment flags.
        """
        try:
            statuses = collect_dependency_status()
        except (
            ManifestLoadError
        ) as exc:  # pragma: no cover - only hits when manifest missing
            logger.debug("Dependency manifest unavailable: %s", exc)
            return

        missing = summarise_missing_by_category(statuses)
        if not missing:
            return

        logger.info("Optional tool dependencies missing from environment:")
        for category, entries in sorted(missing.items()):
            heading = category.replace("_", " ").replace("-", " ").title()
            logger.info("  %s:", heading)
            for status in entries:
                spec = status.spec
                level = logger.warning if not spec.optional else logger.info
                parts = []
                if spec.summary:
                    parts.append(spec.summary)
                if status.detail and (
                    not spec.summary or status.detail not in spec.summary
                ):
                    parts.append(status.detail)
                if spec.used_by:
                    parts.append(f"affects: {', '.join(spec.used_by)}")
                if spec.install_hint:
                    parts.append(f"hint: {spec.install_hint}")
                message = "; ".join(parts) if parts else "missing"
                level("    - %s (%s)", spec.name, message)

    def _discover_tools(self):
        """Automatically discover and register available tools.

        Discovery order:
        1. Load from UnifiedToolRegistry (canonical source)
        2. Run light or full discovery for additional tools
        3. Merge without duplicates
        """
        # First, load from UnifiedToolRegistry (canonical source)
        unified_tools = self._load_from_unified_registry()
        for tool in unified_tools:
            tool_name = tool.get_tool_name()
            if tool_name not in self.tools:
                self.register_tool(tool)

        # Then run additional discovery
        if self.light_mode:
            logger.info("Discovering tools in LIGHT mode (skipping heavy probing)...")
            self._light_discovery()
        else:
            logger.info("Discovering tools in FULL mode...")
            self._full_discovery()

        # Grandmaster tool surface (YAML-driven wrappers + optional declarative workflows).
        self._register_grandmaster_tools()

    def _light_discovery(self):
        """Light discovery - only check if paths exist, no heavy probing."""
        neurodesk_path = os.environ.get(
            "NEURODESK_PATH", "/cvmfs/neurodesk.ardc.edu.au"
        )

        # Quick checks for key tools without execution
        import glob

        tool_checks = [
            ("fsl", f"{neurodesk_path}/containers/fsl_*/bet"),
            ("freesurfer", f"{neurodesk_path}/containers/freesurfer_*/recon-all"),
            ("afni", f"{neurodesk_path}/containers/afni_*/3dClustSim"),
            ("ants", f"{neurodesk_path}/containers/ants_*/antsRegistration"),
            ("fmriprep", f"{neurodesk_path}/containers/fmriprep_*/fmriprep"),
        ]

        for name, pattern in tool_checks:
            if glob.glob(pattern):
                logger.info(f"[light] Found {name} at {pattern}")

        # Register minimal set of tools without probing
        self._register_core_tools_light()

    def _register_core_tools_light(self):
        """Register core tools in light mode without heavy probing."""
        # Grand Master wrapper surface (intent-based IDs)
        try:
            for tool in GrandMasterTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered Grand Master wrapper tools")
        except Exception as exc:
            logger.debug("[light] Skipping Grand Master tools: %s", exc)

        # Register essential tools that don't need probing
        try:
            # BR-KG tools (lightweight)
            br_kg_tools = BRKGTools()
            for tool in br_kg_tools.get_all_tools():
                self.register_tool(tool)
            logger.info(
                f"[light] Registered {len(br_kg_tools.get_all_tools())} BR-KG tools"
            )
        except Exception as e:
            logger.warning(f"[light] Failed to register BR-KG tools: {e}")

        try:
            novelty_tools = KGNoveltyTools()
            for tool in novelty_tools.get_all_tools():
                self.register_tool(tool)
            logger.info(
                f"[light] Registered {len(novelty_tools.get_all_tools())} KG novelty tools"
            )
        except Exception as exc:
            logger.warning(f"[light] Failed to register KG novelty tools: {exc}")

        try:
            query_tools = BRKGQueryTools()
            for tool in query_tools.get_all_tools():
                self.register_tool(tool)
            logger.info(
                f"[light] Registered {len(query_tools.get_all_tools())} BR-KG query tools"
            )
        except Exception as exc:
            logger.warning(f"[light] Failed to register BR-KG query tools: {exc}")

        try:
            # NiWrap tools (lightweight - only search/schema/execute wrappers)
            niwrap_tools = NiWrapTools()
            for tool in niwrap_tools.get_all_tools():
                self.register_tool(tool)
            logger.info(
                f"[light] Registered {len(niwrap_tools.get_all_tools())} NiWrap agent tools"
            )
        except Exception as e:
            logger.warning(f"[light] Failed to register NiWrap tools: {e}")

        # Dataset resources lookup (read-only, lightweight)
        try:
            self.register_tool(DatasetResourcesTool())
            self.register_tool(DatasetDescribeTool())
        except Exception as exc:  # pragma: no cover - keep light path resilient
            logger.debug("[light] Skipping dataset resources tools: %s", exc)

        # Genetics/Genomics tools (lightweight synthetic fallbacks)
        try:
            from brain_researcher.services.tools.genetics_genomics_tools import (
                GeneticsGenomicsTools,
            )

            genetics_tools = GeneticsGenomicsTools()
            for tool in genetics_tools.get_all_tools():
                self.register_tool(tool)
            logger.info(
                "[light] Registered %d genetics/genomics tools",
                len(genetics_tools.get_all_tools()),
            )
        except Exception as exc:  # pragma: no cover - keep light path resilient
            logger.debug("[light] Skipping genetics/genomics tools: %s", exc)

        # OpenNeuro dataset query tools (read-only, lightweight)
        try:
            for tool in OpenNeuroTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered OpenNeuro tools")
        except Exception as exc:
            logger.debug("[light] Skipping OpenNeuro tools: %s", exc)

        # Jobs management tools
        try:
            for tool in JobsTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered Jobs tools")
        except Exception as exc:
            logger.debug("[light] Skipping Jobs tools: %s", exc)

        # Track K+ Neuroassistant tools (knowledge-aware planning)
        try:
            for tool in NeuroassistantTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered Neuroassistant tools")
        except Exception as exc:
            logger.debug("[light] Skipping Neuroassistant tools: %s", exc)

        # fMRI tools (lightweight fallbacks/stubs)
        try:
            for tool in FMRITools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered fMRI tools")
        except Exception as exc:
            logger.debug("[light] Skipping fMRI tools: %s", exc)

        # Nilearn GLM/connectivity/viz/MVPA tools (Python-only)
        try:
            register_glm_tools(self)
            register_connectivity_tools(self)
            register_nilearn_viz_tools(self)
            register_mvpa_tools(self)
            logger.info("[light] Registered Nilearn analysis tools")
        except Exception as exc:
            logger.debug("[light] Skipping Nilearn analysis tools: %s", exc)

        # Cross-validation tools (lightweight, numpy-only fallback)
        try:
            from brain_researcher.services.tools.cross_validation_tool import (
                CrossValidationTools,
            )

            for tool in CrossValidationTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered cross-validation tools")
        except Exception as exc:
            logger.debug("[light] Skipping cross-validation tools: %s", exc)

        # Dynamic connectivity tools (lightweight fallback)
        try:
            from brain_researcher.services.tools.dynamic_connectivity_tool import (
                DynamicConnectivityTools,
            )

            for tool in DynamicConnectivityTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered dynamic connectivity tools")
        except Exception as exc:
            logger.debug("[light] Skipping dynamic connectivity tools: %s", exc)

        # fMRIPrep/XCP-D command builders (safe by default: generate commands)
        try:
            from brain_researcher.services.tools.fmriprep_tool import FMRIPrepTools

            for tool in FMRIPrepTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered fMRIPrep tools")
        except Exception as exc:
            logger.debug("[light] Skipping fMRIPrep tools: %s", exc)

        try:
            from brain_researcher.services.tools.xcpd_tool import XCPDTools

            for tool in XCPDTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered XCP-D tools")
        except Exception as exc:
            logger.debug("[light] Skipping XCP-D tools: %s", exc)

        # FSL FEAT/MELODIC wrappers
        try:
            for tool in FSLFEATTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered FSL FEAT tools")
        except Exception as exc:
            logger.debug("[light] Skipping FSL FEAT tools: %s", exc)

        try:
            for tool in FSLMELODICTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered FSL MELODIC tools")
        except Exception as exc:
            logger.debug("[light] Skipping FSL MELODIC tools: %s", exc)

        # AFNI tools (NiWrap-backed wrappers)
        try:
            for tool in AFNITools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered AFNI tools")
        except Exception as exc:
            logger.debug("[light] Skipping AFNI tools: %s", exc)

        # BIDS tools
        try:
            for tool in BIDSTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered BIDS tools")
        except Exception as exc:
            logger.debug("[light] Skipping BIDS tools: %s", exc)

        # Behavior ingest/QC/export tools
        try:
            for tool in BehaviorTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered behavior tools")
        except Exception as exc:
            logger.debug("[light] Skipping behavior tools: %s", exc)

        # NWB tools
        try:
            for tool in NWBTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered NWB tools")
        except Exception as exc:
            logger.debug("[light] Skipping NWB tools: %s", exc)

        # Archive tools (OpenNeuro/DANDI/NeuroVault)
        try:
            for tool in ArchiveTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered archive tools")
        except Exception as exc:
            logger.debug("[light] Skipping archive tools: %s", exc)

        # Pipeline tools (fMRIPrep/MRIQC)
        try:
            for tool in PipelineTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered pipeline tools")
        except Exception as exc:
            logger.debug("[light] Skipping pipeline tools: %s", exc)

        # Neurodesk command generators (lightweight)
        try:
            for tool in NeurodeskTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered Neurodesk tools")
        except Exception as exc:
            logger.debug("[light] Skipping Neurodesk tools: %s", exc)

        # Multiple-comparison correction (lightweight)
        try:
            for tool in MultipleComparisonTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered multiple comparison tools")
        except Exception as exc:
            logger.debug("[light] Skipping multiple comparison tools: %s", exc)

        # Targeted meta-analysis helpers
        try:
            from brain_researcher.services.tools.enhanced_meta_analysis import (
                CoordinateMetaAnalysisTool,
                LiteratureMiningTool,
            )

            self.register_tool(CoordinateMetaAnalysisTool())
            self.register_tool(LiteratureMiningTool())
            logger.info("[light] Registered meta-analysis helpers")
        except Exception as exc:
            logger.debug("[light] Skipping meta-analysis helpers: %s", exc)

        # Brain simulation / lesion detection / realtime fMRI tools
        try:
            from brain_researcher.services.tools.brain_simulation_tool import (
                BrainSimulationTools,
            )

            for tool in BrainSimulationTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered brain simulation tools")
        except Exception as exc:
            logger.debug("[light] Skipping brain simulation tools: %s", exc)

        # Hyperalignment tools (python-only fallback)
        try:
            from brain_researcher.services.tools.hyperalignment_tool import (
                HyperalignmentTools,
            )

            for tool in HyperalignmentTools.get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered hyperalignment tools")
        except Exception as exc:
            logger.debug("[light] Skipping hyperalignment tools: %s", exc)

        try:
            from brain_researcher.services.tools.lesion_detection_tool import (
                LesionDetectionTools,
            )

            for tool in LesionDetectionTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered lesion detection tools")
        except Exception as exc:
            logger.debug("[light] Skipping lesion detection tools: %s", exc)

        try:
            from brain_researcher.services.tools.realtime_fmri_tool import (
                RealtimeFMRITools,
            )

            for tool in RealtimeFMRITools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered realtime fMRI tools")
        except Exception as exc:
            logger.debug("[light] Skipping realtime fMRI tools: %s", exc)

        try:
            from brain_researcher.services.tools.realtime_twophoton_tool import (
                RealtimeTwoPhotonTools,
            )

            for tool in RealtimeTwoPhotonTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered realtime two-photon tools")
        except Exception as exc:
            logger.debug("[light] Skipping realtime two-photon tools: %s", exc)

        # Phase2 batch: data harmonization only (lightweight)
        try:
            from brain_researcher.services.tools.phase2_batch_tools import (
                HarmonizationTool,
            )

            self.register_tool(HarmonizationTool())
            logger.info("[light] Registered data harmonization tool")
        except Exception as exc:
            logger.debug("[light] Skipping data harmonization tool: %s", exc)

        # Pipeline search (Neo4j-backed but lightweight)
        try:
            self.register_tool(PipelineSearchTool())
            logger.info("[light] Registered pipeline search tool")
        except Exception as exc:
            logger.debug("[light] Skipping pipeline search tool: %s", exc)

        # QC tools
        try:
            for tool in QCTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered QC tools")
        except Exception as exc:
            logger.debug("[light] Skipping QC tools: %s", exc)

        # Register lightweight fallbacks so core agent functionality works without heavy deps
        self._register_light_fallbacks()
        self._register_prefixed_stub_tools()

        logger.info(f"[light] Total tools registered: {len(self.tools)}")

    def _register_light_fallbacks(self) -> None:
        """Register neurocore-backed fallbacks for minimal environments."""

        try:
            from brain_researcher.services.tools.asl_perfusion_tool import (
                ASLPerfusionTools,
            )

            for tool in ASLPerfusionTools().get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.debug("[light] Skipping ASL fallback: %s", exc)

        try:
            from brain_researcher.services.tools.diffusion_tractography_tool import (
                DiffusionTractographyTools,
            )

            for tool in DiffusionTractographyTools().get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.debug("[light] Skipping diffusion fallback: %s", exc)

        try:
            for tool in DLPyTorchTools().get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.debug("[light] Skipping PyTorch fallback: %s", exc)

        try:
            from brain_researcher.services.tools.gnn_connectivity_tool import (
                GNNConnectivityTools,
            )

            for tool in GNNConnectivityTools().get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.debug("[light] Skipping GNN fallback: %s", exc)

        try:
            from brain_researcher.services.tools.graph_theory_tool import (
                GraphTheoryTools,
            )

            for tool in GraphTheoryTools().get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.debug("[light] Skipping graph theory fallback: %s", exc)

        # Declarative workflow gap fillers (lightweight implementations)
        try:
            for tool in WorkflowFallbackTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered workflow fallback tools")
        except Exception as exc:  # pragma: no cover
            logger.debug("[light] Skipping workflow fallback tools: %s", exc)

        # Nipype runner (optional dependency)
        try:
            for tool in NipypeRunnerTools().get_all_tools():
                self.register_tool(tool)
            logger.info("[light] Registered Nipype workflow runner tools")
        except Exception as exc:  # pragma: no cover
            logger.debug("[light] Skipping Nipype runner tools: %s", exc)

    def _register_prefixed_stub_tools(self) -> None:
        """Register modality-prefixed stub tools discovered via auto-registry."""

        auto_tools = _iter_auto_registry_tools()
        if not auto_tools:
            return

        registered = 0
        for tool in auto_tools:
            tool_name = tool.get_tool_name()
            if tool_name in self.tools:
                continue
            self.register_tool(tool)
            registered += 1

        if registered:
            logger.info("Auto-registered %s modality-prefixed tool(s)", registered)

    def _register_grandmaster_tools(self) -> None:
        """Register Grandmaster tools/workflows from YAML if available."""
        env_flag = os.getenv("BR_GRANDMASTER_ENABLE")
        if env_flag is not None and env_flag.lower() in {"0", "false", "no", "off"}:
            return

        enable_stubs = os.getenv("BR_GRANDMASTER_STUBS", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        try:
            from brain_researcher.services.tools.grandmaster import (
                register_grandmaster_tools,
            )

            register_grandmaster_tools(self, enable_stubs=enable_stubs)
        except Exception as exc:  # pragma: no cover - best-effort
            logger.debug("Grandmaster tools not registered: %s", exc)

    def _full_discovery(self):
        """Full discovery with probing and validation."""
        self._report_dependency_health()
        configure_mne_environment()

        # Grand Master wrapper surface (intent-based IDs)
        try:
            for tool in GrandMasterTools().get_all_tools():
                self.register_tool(tool)
            logger.info("Registered Grand Master wrapper tools")
        except Exception as exc:
            logger.warning("Skipping Grand Master tools: %s", exc)

        # Register fMRI tools
        fmri_tools = FMRITools()
        for tool in fmri_tools.get_all_tools():
            self.register_tool(tool)

        # Register BR-KG tools
        br_kg_tools = BRKGTools()
        for tool in br_kg_tools.get_all_tools():
            self.register_tool(tool)
        novelty_tools = KGNoveltyTools()
        for tool in novelty_tools.get_all_tools():
            self.register_tool(tool)
        query_tools = BRKGQueryTools()
        for tool in query_tools.get_all_tools():
            self.register_tool(tool)
        # Dataset resources lookup (read-only, fast)
        self.register_tool(DatasetResourcesTool())
        self.register_tool(DatasetDescribeTool())

        # OpenNeuro dataset query tools (read-only)
        for tool in OpenNeuroTools().get_all_tools():
            self.register_tool(tool)

        # Jobs management tools
        for tool in JobsTools().get_all_tools():
            self.register_tool(tool)

        # Track K+ Neuroassistant tools (knowledge-aware planning)
        try:
            for tool in NeuroassistantTools().get_all_tools():
                self.register_tool(tool)
            logger.info("Registered Neuroassistant tools")
        except Exception as exc:
            logger.warning("Skipping Neuroassistant tools: %s", exc)

        # NiCLIP utilities (embedding + rerank)
        try:
            from brain_researcher.services.tools.niclip_tool import NiclipTools

            for tool in NiclipTools().get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("Skipping NiCLIP tools: %s", exc)

        # TRIBE v2 utilities (multimodal stimulus -> predicted fMRI response)
        try:
            from brain_researcher.services.tools.tribe_tool import TribePredictTools

            for tool in TribePredictTools().get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("Skipping TRIBE tools: %s", exc)

        # NeuroVLM utilities (semantic decoding + RDM building)
        try:
            from brain_researcher.services.tools.neurovlm_tool import NeuroVLMTools

            for tool in NeuroVLMTools().get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.debug("Skipping NeuroVLM tools: %s", exc)

        # Register Neurosynth tools
        # Temporarily disabled - numpy compatibility issue
        # neurosynth_tools = NeuroSynthTools()
        # for tool in neurosynth_tools.get_all_tools():
        #     self.register_tool(tool)

        # Register BIDS tools
        bids_tools = BIDSTools()
        for tool in bids_tools.get_all_tools():
            self.register_tool(tool)

        # Register behavior ingest/QC/export tools
        behavior_tools = BehaviorTools()
        for tool in behavior_tools.get_all_tools():
            self.register_tool(tool)

        # Register NWB tools
        nwb_tools = NWBTools()
        for tool in nwb_tools.get_all_tools():
            self.register_tool(tool)

        # Register archive tools
        archive_tools = ArchiveTools()
        for tool in archive_tools.get_all_tools():
            self.register_tool(tool)

        # Register preprocessing pipeline tools
        pipeline_tools = PipelineTools()
        for tool in pipeline_tools.get_all_tools():
            self.register_tool(tool)

        # Pipeline search (Neo4j-backed but lightweight)
        try:
            self.register_tool(PipelineSearchTool())
        except Exception as exc:
            logger.warning("Skipping pipeline search tool: %s", exc)

        # Register QC tools
        qc_tools = QCTools()
        for tool in qc_tools.get_all_tools():
            self.register_tool(tool)

        # Register FSL FEAT tools
        fsl_feat_tools = FSLFEATTools()
        for tool in fsl_feat_tools.get_all_tools():
            self.register_tool(tool)

        # Register FSL MELODIC tools
        fsl_melodic_tools = FSLMELODICTools()
        for tool in fsl_melodic_tools.get_all_tools():
            self.register_tool(tool)

        # Register FSL BET tools
        fsl_bet_tools = FSLBETTools()
        for tool in fsl_bet_tools.get_all_tools():
            self.register_tool(tool)

        # Register FSL FLIRT tools
        fsl_flirt_tools = FSLFLIRTTools()
        for tool in fsl_flirt_tools.get_all_tools():
            self.register_tool(tool)

        # Register FSL FNIRT tools
        fsl_fnirt_tools = FSLFNIRTTools()
        for tool in fsl_fnirt_tools.get_all_tools():
            self.register_tool(tool)

        # Register FSL BEDPOSTX tools
        fsl_bedpostx_tools = FSLBEDPOSTXTools()
        for tool in fsl_bedpostx_tools.get_all_tools():
            self.register_tool(tool)

        # Register MNE preprocessing tools (optional dependency)
        try:
            mne_preprocessing_tools = MNEPreprocessingTools()
            for tool in mne_preprocessing_tools.get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.warning("Skipping MNE preprocessing tools: %s", exc)

        try:
            mne_ica_tools = MNEICATools()
            for tool in mne_ica_tools.get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.warning("Skipping MNE ICA tools: %s", exc)

        try:
            mne_timefreq_tools = MNETimeFreqTools()
            for tool in mne_timefreq_tools.get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.warning("Skipping MNE time-frequency tools: %s", exc)

        # Register Statsmodels GLM tools
        statsmodels_glm_tools = StatsmodelsGLMTools()
        for tool in statsmodels_glm_tools.get_all_tools():
            self.register_tool(tool)

        # Register fMRIPrep tools
        fmriprep_tools = FMRIPrepTools()
        for tool in fmriprep_tools.get_all_tools():
            self.register_tool(tool)

        # Register ANTs tools
        ants_tools = ANTsTools()
        for tool in ants_tools.get_all_tools():
            self.register_tool(tool)

        # Register QSIPrep tools
        qsiprep_tools = QSIPrepTools()
        for tool in qsiprep_tools.get_all_tools():
            self.register_tool(tool)

        # Register XCP-D tools
        xcpd_tools = XCPDTools()
        for tool in xcpd_tools.get_all_tools():
            self.register_tool(tool)

        # Register SPM12 tools
        spm12_tools = SPM12Tools()
        for tool in spm12_tools.get_all_tools():
            self.register_tool(tool)

        # Register organized Nilearn tools
        register_glm_tools(self)
        register_connectivity_tools(self)
        register_nilearn_viz_tools(self)
        register_preprocessing_tools(self)
        register_mvpa_tools(self)

        # Register Neurodesk tools
        neurodesk_tools = NeurodeskTools()
        for tool in neurodesk_tools.get_all_tools():
            self.register_tool(tool)

        # Register FreeSurfer tools
        freesurfer_tools = FreeSurferTools()
        for tool in freesurfer_tools.get_all_tools():
            self.register_tool(tool)

        # Register CONN tools
        conn_tools = CONNTools()
        for tool in conn_tools.get_all_tools():
            self.register_tool(tool)

        # Register Nipype tools
        nipype_tools = NipypeTools()
        for tool in nipype_tools.get_all_tools():
            self.register_tool(tool)

        # Register Mixed Effects tools
        mixed_effects_tools = MixedEffectsTools()
        for tool in mixed_effects_tools.get_all_tools():
            self.register_tool(tool)

        # Register FitLins tools
        fitlins_tools = FitLinsTools()
        for tool in fitlins_tools.get_all_tools():
            self.register_tool(tool)

        # Register FSL FIX tools
        fsl_fix_tools = FSLFIXTools()
        for tool in fsl_fix_tools.get_all_tools():
            self.register_tool(tool)

        # Register FSL PALM tools
        fsl_palm_tools = FSLPALMTools()
        for tool in fsl_palm_tools.get_all_tools():
            self.register_tool(tool)

        try:
            mne_source_tools = MNESourceTools()
            for tool in mne_source_tools.get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.warning("Skipping MNE source tools: %s", exc)

        try:
            mne_connectivity_tools = MNEConnectivityTools()
            for tool in mne_connectivity_tools.get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.warning("Skipping MNE connectivity tools: %s", exc)

        # Register Permutation Testing tools
        permutation_tools = PermutationTestingTools()
        for tool in permutation_tools.get_all_tools():
            self.register_tool(tool)

        # Register Multiple Comparison Correction tools
        multiple_comparison_tools = MultipleComparisonTools()
        for tool in multiple_comparison_tools.get_all_tools():
            self.register_tool(tool)

        # Register C-PAC Pipeline tools
        cpac_tools = CPACTools()
        for tool in cpac_tools.get_all_tools():
            self.register_tool(tool)

        # Register HCP Workbench tools
        hcp_workbench_tools = HCPWorkbenchTools()
        for tool in hcp_workbench_tools.get_all_tools():
            self.register_tool(tool)

        # Register AFNI tools
        afni_tools = AFNITools()
        for tool in afni_tools.get_all_tools():
            self.register_tool(tool)

        try:
            from brain_researcher.services.tools.mne_fooof_tool import MNEFOOOFTools

            mne_fooof_tools = MNEFOOOFTools()
            for tool in mne_fooof_tools.get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.warning("Skipping MNE FOOOF tools: %s", exc)

        try:
            from brain_researcher.services.tools.mne_autoreject_tool import (
                MNEAutorejectTools,
            )

            mne_autoreject_tools = MNEAutorejectTools()
            for tool in mne_autoreject_tools.get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.warning("Skipping MNE autoreject tools: %s", exc)

        # Register RSA Toolbox tools
        from brain_researcher.services.tools.rsa_toolbox_tool import RSAToolboxTools

        rsa_tools = RSAToolboxTools()
        for tool in rsa_tools.get_all_tools():
            self.register_tool(tool)

        # Register Searchlight Analysis tools
        from brain_researcher.services.tools.searchlight_tool import SearchlightTools

        searchlight_tools = SearchlightTools()
        for tool in searchlight_tools.get_all_tools():
            self.register_tool(tool)

        try:
            pytorch_tools = DLPyTorchTools()
            for tool in pytorch_tools.get_all_tools():
                self.register_tool(tool)
        except Exception as exc:  # pragma: no cover
            logger.warning("Skipping PyTorch deep learning tools: %s", exc)

        # Register GNN Connectivity tools
        from brain_researcher.services.tools.gnn_connectivity_tool import (
            GNNConnectivityTools,
        )

        gnn_tools = GNNConnectivityTools()
        for tool in gnn_tools.get_all_tools():
            self.register_tool(tool)

        # Register Multimodal Integration tools
        from brain_researcher.services.tools.multimodal_integration_tool import (
            MultimodalIntegrationTools,
        )

        multimodal_tools = MultimodalIntegrationTools()
        for tool in multimodal_tools.get_all_tools():
            self.register_tool(tool)

        # Register Real-time fMRI tools
        from brain_researcher.services.tools.realtime_fmri_tool import RealtimeFMRITools

        realtime_tools = RealtimeFMRITools()
        for tool in realtime_tools.get_all_tools():
            self.register_tool(tool)

        # Register realtime two-photon tools
        from brain_researcher.services.tools.realtime_twophoton_tool import (
            RealtimeTwoPhotonTools,
        )

        realtime_twophoton_tools = RealtimeTwoPhotonTools()
        for tool in realtime_twophoton_tools.get_all_tools():
            self.register_tool(tool)

        # Register MVPA tools
        from brain_researcher.services.tools.mvpa_tool import MVPATools

        mvpa_tools = MVPATools()
        for tool in mvpa_tools.get_all_tools():
            self.register_tool(tool)

        # Register Encoding Models tools
        from brain_researcher.services.tools.encoding_models_tool import (
            EncodingModelsTools,
        )

        encoding_tools = EncodingModelsTools()
        for tool in encoding_tools.get_all_tools():
            self.register_tool(tool)

        # Register Feature Selection tools
        from brain_researcher.services.tools.feature_selection_tool import (
            FeatureSelectionTools,
        )

        feature_tools = FeatureSelectionTools()
        for tool in feature_tools.get_all_tools():
            self.register_tool(tool)

        # Register Temporal Decoding tools
        from brain_researcher.services.tools.temporal_decoding_tool import (
            TemporalDecodingTools,
        )

        temporal_tools = TemporalDecodingTools()
        for tool in temporal_tools.get_all_tools():
            self.register_tool(tool)

        # Register Dynamic Connectivity tools
        from brain_researcher.services.tools.dynamic_connectivity_tool import (
            DynamicConnectivityTools,
        )

        dynamic_conn_tools = DynamicConnectivityTools()
        for tool in dynamic_conn_tools.get_all_tools():
            self.register_tool(tool)

        # Register Graph Theory tools
        from brain_researcher.services.tools.graph_theory_tool import GraphTheoryTools

        graph_tools = GraphTheoryTools()
        for tool in graph_tools.get_all_tools():
            self.register_tool(tool)

        # Register Statistical Inference tools
        from brain_researcher.services.tools.statistical_inference_tool import (
            StatisticalInferenceTools,
        )

        stat_inference_tools = StatisticalInferenceTools()
        for tool in stat_inference_tools.get_all_tools():
            self.register_tool(tool)

        # Register Advanced Visualization tools
        from brain_researcher.services.tools.advanced_visualization_tool import (
            AdvancedVisualizationTools,
        )

        viz_tools = AdvancedVisualizationTools()
        for tool in viz_tools.get_all_tools():
            self.register_tool(tool)

        # Register Cross-validation tools
        from brain_researcher.services.tools.cross_validation_tool import (
            CrossValidationTools,
        )

        cv_tools = CrossValidationTools()
        for tool in cv_tools.get_all_tools():
            self.register_tool(tool)

        try:
            from brain_researcher.services.tools.meta_analysis_tool import (
                MetaAnalysisTools,
            )

            meta_tools = MetaAnalysisTools()
            for tool in meta_tools.get_all_tools():
                self.register_tool(tool)

            from brain_researcher.services.tools.enhanced_meta_analysis import (
                CoordinateMetaAnalysisTool,
                EffectSizeMetaAnalysisTool,
                ImageBasedMetaAnalysisTool,
                LiteratureMiningTool,
                NetworkMetaAnalysisTool,
            )

            self.register_tool(CoordinateMetaAnalysisTool())
            self.register_tool(ImageBasedMetaAnalysisTool())
            self.register_tool(EffectSizeMetaAnalysisTool())
            self.register_tool(LiteratureMiningTool())
            self.register_tool(NetworkMetaAnalysisTool())
        except Exception as exc:  # pragma: no cover
            logger.warning("Skipping meta-analysis suite: %s", exc)

        # Register Brain Simulation tools
        from brain_researcher.services.tools.brain_simulation_tool import (
            BrainSimulationTools,
        )

        sim_tools = BrainSimulationTools()
        for tool in sim_tools.get_all_tools():
            self.register_tool(tool)

        # Register Hyperalignment tools
        from brain_researcher.services.tools.hyperalignment_tool import (
            HyperalignmentTools,
        )

        hyper_tools = HyperalignmentTools()
        for tool in hyper_tools.get_all_tools():
            self.register_tool(tool)

        # Register MONAI deep learning tools
        from brain_researcher.services.tools.monai_tool import MONAITools

        monai_tools = MONAITools()
        for tool in monai_tools.get_all_tools():
            self.register_tool(tool)

        # Register Diffusion Tractography tools
        from brain_researcher.services.tools.diffusion_tractography_tool import (
            DiffusionTractographyTools,
        )

        tract_tools = DiffusionTractographyTools()
        for tool in tract_tools.get_all_tools():
            self.register_tool(tool)

        # Register Registration Pipeline tools
        from brain_researcher.services.tools.registration_tool import RegistrationTools

        reg_tools = RegistrationTools()
        for tool in reg_tools.get_all_tools():
            self.register_tool(tool)

        # Register Segmentation tools
        from brain_researcher.services.tools.segmentation_tool import SegmentationTools

        seg_tools = SegmentationTools()
        for tool in seg_tools.get_all_tools():
            self.register_tool(tool)

        # Register ASL Perfusion tools
        from brain_researcher.services.tools.asl_perfusion_tool import ASLPerfusionTools

        asl_tools = ASLPerfusionTools()
        for tool in asl_tools.get_all_tools():
            self.register_tool(tool)

        # Register Lesion Detection tools
        from brain_researcher.services.tools.lesion_detection_tool import (
            LesionDetectionTools,
        )

        lesion_tools = LesionDetectionTools()
        for tool in lesion_tools.get_all_tools():
            self.register_tool(tool)

        # Register QSM tools
        from brain_researcher.services.tools.qsm_tool import QSMTools

        qsm_tools = QSMTools()
        for tool in qsm_tools.get_all_tools():
            self.register_tool(tool)

        # Register MR Spectroscopy tools
        from brain_researcher.services.tools.mrs_tool import MRSpectroscopyTools

        mrs_tools = MRSpectroscopyTools()
        for tool in mrs_tools.get_all_tools():
            self.register_tool(tool)

        # Register Genetics/Genomics tools
        from brain_researcher.services.tools.genetics_genomics_tools import (
            GeneticsGenomicsTools,
        )

        genetics_tools = GeneticsGenomicsTools()
        for tool in genetics_tools.get_all_tools():
            self.register_tool(tool)

        # Register NiWrap tools (search/schema/execute for ~1900 neuroimaging tools)
        niwrap_tools = NiWrapTools()
        for tool in niwrap_tools.get_all_tools():
            self.register_tool(tool)
        logger.info(
            "Registered %d NiWrap agent tools", len(niwrap_tools.get_all_tools())
        )

        # Register Phase 2 Batch tools (final 11 tools to reach 130)
        from brain_researcher.services.tools.phase2_batch_tools import Phase2BatchTools

        batch_tools = Phase2BatchTools()
        for tool in batch_tools.get_all_tools():
            self.register_tool(tool)

        # Register Clinical Decision Support Tool (reach 131 tools)

        # Note: Pipeline orchestration is handled by LangGraph, not as a tool
        # self.register_tool(ClinicalDecisionSupport())
        # TODO: Register additional tool categories when implemented
        # # Register Brain Simulation tools (8 tools)
        # from brain_researcher.services.tools.brain_simulation import BrainSimulationTools
        # brain_sim_tools = BrainSimulationTools()
        # for tool in brain_sim_tools.get_all_tools():
        #     self.register_tool(tool)
        # # Register Advanced Deep Learning tools (8 tools)
        # from brain_researcher.services.tools.advanced_deep_learning import AdvancedDeepLearningTools
        # adv_dl_tools = AdvancedDeepLearningTools()
        # for tool in adv_dl_tools.get_all_tools():
        #     self.register_tool(tool)
        # # Register Multimodal Fusion tools (8 tools)
        # from brain_researcher.services.tools.multimodal_fusion import MultimodalFusionTools
        # mm_fusion_tools = MultimodalFusionTools()
        # for tool in mm_fusion_tools.get_all_tools():
        #     self.register_tool(tool)
        # # Register Causality Analysis tools (8 tools)
        # from brain_researcher.services.tools.causality_analysis import CausalityAnalysisTools
        # causality_tools = CausalityAnalysisTools()
        # for tool in causality_tools.get_all_tools():
        #     self.register_tool(tool)
        # # Register Cloud-Native Processing tools (8 tools)
        # from brain_researcher.services.tools.cloud_native_processing import CloudNativeProcessingTools
        # cloud_tools = CloudNativeProcessingTools()
        # for tool in cloud_tools.get_all_tools():
        #     self.register_tool(tool)
        # # Register Genetics/Genomics tools (8 tools)
        # from brain_researcher.services.tools.genetics_genomics_tools import GeneticsGenomicsTools
        # genetics_tools = GeneticsGenomicsTools()
        # for tool in genetics_tools.get_all_tools():
        #     self.register_tool(tool)
        # # Register PET Imaging tools (6 tools)
        # from brain_researcher.services.tools.pet_imaging_tools import PETImagingTools
        # pet_tools = PETImagingTools()
        # for tool in pet_tools.get_all_tools():
        #     self.register_tool(tool)
        # # Register Optical Imaging tools (5 tools)
        # from brain_researcher.services.tools.optical_imaging_tools import OpticalImagingTools
        # optical_tools = OpticalImagingTools()
        # for tool in optical_tools.get_all_tools():
        #     self.register_tool(tool)
        # # Register Interactive Visualization tools (5 tools)
        # from brain_researcher.services.tools.interactive_visualization_tools import InteractiveVisualizationTools
        # viz_tools = InteractiveVisualizationTools()
        # for tool in viz_tools.get_all_tools():
        #     self.register_tool(tool)
        # Register Nilearn tools
        # Temporarily disabled - causes import hang
        # nilearn_tools = NilearnTools()
        # for tool in nilearn_tools.get_all_tools():
        #     self.register_tool(tool)
        # Could also discover tools from directory
        # self._discover_from_directory("tools/custom")
        # Automatically pick up modality-prefixed stub tools (ieeg_*, dmri_*, etc.)
        self._register_prefixed_stub_tools()

        logger.info(f"Discovered {len(self.tools)} tools")

    def register_tool(self, tool: NeuroToolWrapper):
        """
        Register a tool in the registry.

        Args:
            tool: The tool to register
        """
        tool_name = tool.get_tool_name()
        if tool_name in self.tools:
            logger.warning(f"Tool {tool_name} already registered, replacing duplicate")

        # Propagate catalog metadata to the tool if available (for router/spec)
        try:
            inject_metadata(tool)
        except Exception as exc:
            logger.debug("Metadata injection failed for %s: %s", tool_name, exc)

        self.tools[tool_name] = tool
        self.tool_descriptions[tool_name] = tool.get_tool_description()
        logger.debug(f"Registered tool: {tool_name}")

    # Thin runtime accessor for routing/execution layers
    def get_runtime_tool(self, tool_id: str) -> NeuroToolWrapper | None:
        """Return the underlying runtime tool instance by id."""

        return self.tools.get(tool_id)

    def get_tool(self, name: str) -> NeuroToolWrapper | None:
        """
        Get a tool by name.

        Args:
            name: The tool name

        Returns:
            The tool if found, None otherwise
        """
        return self.tools.get(name)

    def get_all_tools(self) -> list[NeuroToolWrapper]:
        """Get all registered tools."""
        return list(self.tools.values())

    def find_tools_by_tags(
        self,
        domain: str | None = None,
        function: str | None = None,
        risk: str | None = None,
        limit: int = 10,
    ) -> list[str]:
        """Return tool ids whose tags include the requested metadata.

        Args:
            domain: desired domain tag (exact match)
            function: desired function tag (exact match)
            risk: desired risk tag (exact match)
            limit: max number of tool ids to return
        """
        matches = []
        for tool in self.get_all_tools():
            spec = spec_from_tool(tool)
            if not spec:
                continue
            tags = {t.lower() for t in (spec.tags or [])}
            if domain and domain.lower() not in tags:
                continue
            if function and function.lower() not in tags:
                continue
            if risk and risk.lower() not in tags:
                continue
            matches.append(spec.name)
            if len(matches) >= limit:
                break
        return matches

    def get_langchain_tools(self) -> list[StructuredTool]:
        """Get all tools as LangChain StructuredTools."""
        return [tool.as_langchain_tool() for tool in self.tools.values()]

    def _build_tool_index(self):
        """Build vector index for semantic tool search."""
        try:
            # Try to use embeddings for semantic search
            # In production, would use actual embeddings
            self._build_simple_index()
        except Exception as e:
            logger.warning(f"Failed to build embeddings index: {e}")
            self._build_simple_index()

    def _build_simple_index(self):
        """Build a simple keyword-based index as fallback."""
        # Create documents from tool descriptions
        self.tool_documents = []
        for name, description in self.tool_descriptions.items():
            # Add tool name to description for better matching
            full_text = f"{name}: {description}"
            self.tool_documents.append(
                {
                    "name": name,
                    "text": full_text.lower(),
                    "keywords": self._extract_keywords(full_text),
                }
            )

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract keywords from text for matching."""
        # Simple keyword extraction
        keywords = []

        # Domain-specific keywords
        keyword_map = {
            "glm": ["glm", "general linear model", "statistical", "contrast"],
            "encoding": ["encoding", "model", "predict", "brain activity"],
            "similarity": ["similarity", "compare", "correlation", "distance"],
            "concept": ["concept", "cognitive", "knowledge", "graph"],
            "coordinate": ["coordinate", "mni", "brain", "location"],
            "literature": ["literature", "paper", "publication", "research"],
        }

        text_lower = text.lower()
        for key, terms in keyword_map.items():
            if any(term in text_lower for term in terms):
                keywords.append(key)

        return keywords

    def get_tools_for_task(
        self, task_description: str, k: int = 5
    ) -> list[NeuroToolWrapper]:
        """
        Get the most relevant tools for a task description.

        Args:
            task_description: Natural language description of the task
            k: Maximum number of tools to return

        Returns:
            List of relevant tools, sorted by relevance
        """
        if self.tool_embeddings:
            # Use vector similarity search
            return self._semantic_tool_search(task_description, k)
        else:
            # Fall back to keyword matching
            return self._keyword_tool_search(task_description, k)

    def _keyword_tool_search(
        self, task_description: str, k: int
    ) -> list[NeuroToolWrapper]:
        """Simple keyword-based tool search."""
        task_lower = task_description.lower()
        task_keywords = self._extract_keywords(task_description)

        # Score each tool
        tool_scores = []
        for doc in self.tool_documents:
            score = 0.0

            # Direct text matching
            for word in task_lower.split():
                if len(word) > 3 and word in doc["text"]:
                    score += 1.0

            # Keyword matching
            common_keywords = set(task_keywords) & set(doc["keywords"])
            score += len(common_keywords) * 2.0

            # Specific pattern matching - check both name and text
            if "glm" in task_lower and ("glm" in doc["name"] or "glm" in doc["text"]):
                # Extra bonus if GLM appears multiple times in description
                glm_count = doc["text"].count("glm")
                score += 5.0 + (glm_count - 1) * 2.0
            if "encoding" in task_lower and (
                "encoding" in doc["name"] or "encoding" in doc["text"]
            ):
                score += 5.0
            if "coordinate" in task_lower and (
                "coordinate" in doc["name"] or "coordinate" in doc["text"]
            ):
                score += 5.0
            if "literature" in task_lower and (
                "literature" in doc["name"] or "literature" in doc["text"]
            ):
                score += 5.0
            if "concept" in task_lower and (
                "concept" in doc["name"] or "concept" in doc["text"]
            ):
                score += 3.0

            tool_scores.append((doc["name"], score))

        # Sort by score and return top k
        tool_scores.sort(key=lambda x: x[1], reverse=True)

        selected_tools = []
        for name, score in tool_scores[:k]:
            if score > 0:  # Only include tools with positive scores
                tool = self.get_tool(name)
                if tool:
                    selected_tools.append(tool)

        return selected_tools

    def _semantic_tool_search(
        self, task_description: str, k: int
    ) -> list[NeuroToolWrapper]:
        """Semantic tool search using embeddings (placeholder)."""
        # In production, would use actual embeddings
        # For now, fall back to keyword search
        return self._keyword_tool_search(task_description, k)

    def get_tool_info(self) -> dict[str, Any]:
        """Get information about all registered tools."""
        return {
            "n_tools": len(self.tools),
            "tools": [
                {
                    "name": name,
                    "description": self.tool_descriptions[name],
                    "type": tool.__class__.__name__,
                }
                for name, tool in self.tools.items()
            ],
        }

    def suggest_tools_sequence(self, workflow_description: str) -> list[list[str]]:
        """
        Suggest a sequence of tools for a workflow.

        Args:
            workflow_description: Description of the desired workflow

        Returns:
            List of tool sequences (each sequence is a list of tool names)
        """
        # Common workflow patterns
        workflow_patterns = {
            "fmri_to_concepts": [
                "glm_analysis",
                "coordinate_to_concept",
                "find_related_concepts",
            ],
            "concept_to_literature": [
                "find_related_concepts",
                "concept_literature_search",
            ],
            "full_analysis": [
                "glm_analysis",
                "contrast_analysis",
                "coordinate_to_concept",
                "find_related_concepts",
                "concept_literature_search",
            ],
            "meta_analysis": ["graph_query", "brain_similarity", "encoding_model"],
            "task_analysis": [
                "task_to_concept_mapping",
                "find_related_concepts",
                "glm_analysis",
            ],
        }

        # Simple pattern matching
        workflow_lower = workflow_description.lower()
        suggestions = []

        # Check for pattern matches
        if "fmri" in workflow_lower and "concept" in workflow_lower:
            suggestions.append(workflow_patterns["fmri_to_concepts"])

        if "literature" in workflow_lower or "paper" in workflow_lower:
            suggestions.append(workflow_patterns["concept_to_literature"])

        if "full" in workflow_lower or "complete" in workflow_lower:
            suggestions.append(workflow_patterns["full_analysis"])

        if "meta" in workflow_lower or "multiple" in workflow_lower:
            suggestions.append(workflow_patterns["meta_analysis"])

        if "task" in workflow_lower:
            suggestions.append(workflow_patterns["task_analysis"])

        # If no specific pattern, suggest based on mentioned tools
        if not suggestions:
            mentioned_tools = []
            for tool_name in self.tools.keys():
                if tool_name.replace("_", " ") in workflow_lower:
                    mentioned_tools.append(tool_name)

            if mentioned_tools:
                suggestions.append(mentioned_tools)

        return (
            suggestions if suggestions else [["glm_analysis", "coordinate_to_concept"]]
        )

    # Integration Management Methods

    async def setup_integrations(
        self,
        subscription_system=None,
        kafka_config=None,
        redis_client=None,
        neo4j_driver=None,
    ):
        """Set up all available integrations.

        Args:
            subscription_system: Subscription system instance
            kafka_config: Kafka configuration
            redis_client: Redis client
            neo4j_driver: Neo4j driver
        """
        if not self.enable_integrations:
            logger.info("Integrations disabled, skipping setup")
            return

        try:
            # Set up subscription integration
            if subscription_system and INTEGRATIONS_AVAILABLE:
                from brain_researcher.services.tools.subscription_integration import (
                    setup_agent_subscriptions,
                )

                self.subscription_manager = await setup_agent_subscriptions(
                    None, subscription_system, redis_client
                )
                self.integration_stats["subscriptions_active"] = 1
                logger.info("Subscription integration enabled")

            # Set up streaming integration
            if kafka_config is not None and INTEGRATIONS_AVAILABLE:
                from brain_researcher.services.tools.streaming_integration import (
                    setup_agent_streaming,
                )

                self.streaming_manager = await setup_agent_streaming(
                    None, kafka_config, redis_client
                )
                self.integration_stats["streaming_active"] = True
                logger.info("Streaming integration enabled")

            # Set up deduplication integration
            if INTEGRATIONS_AVAILABLE:
                from brain_researcher.services.tools.deduplication_integration import (
                    setup_agent_deduplication,
                )

                self.deduplication_manager = await setup_agent_deduplication(
                    None, neo4j_driver, redis_client
                )
                self.integration_stats["deduplication_active"] = True
                logger.info("Deduplication integration enabled")

            # Set up plugin integration
            if INTEGRATIONS_AVAILABLE:
                from brain_researcher.services.tools.plugin_integration import (
                    setup_agent_plugins,
                )

                self.plugin_manager = await setup_agent_plugins(None)
                self.integration_stats["plugins_loaded"] = len(
                    self.plugin_manager.plugin_tools
                )

                # Register plugin tools
                await self._register_plugin_tools()
                logger.info(
                    f"Plugin integration enabled with {self.integration_stats['plugins_loaded']} tools"
                )

        except Exception as e:
            logger.error(f"Error setting up integrations: {e}", exc_info=True)

    async def _register_plugin_tools(self):
        """Register plugin tools with the registry."""
        if self.plugin_manager:
            plugin_tools = self.plugin_manager.get_plugin_tools()
            for tool in plugin_tools:
                self.register_tool(tool)
                logger.debug(f"Registered plugin tool: {tool.get_tool_name()}")

    def enable_tool_deduplication(self, tool_names: list[str] = None):
        """Enable deduplication for specified tools.

        Args:
            tool_names: List of tool names to wrap (all if None)
        """
        if not self.deduplication_manager:
            logger.warning("Deduplication manager not available")
            return

        try:
            from brain_researcher.services.tools.deduplication_integration import (
                wrap_tools_for_deduplication,
            )

            wrap_tools_for_deduplication(self, self.deduplication_manager, tool_names)
            logger.info(
                f"Enabled deduplication for {len(tool_names or self.tools)} tools"
            )
        except Exception as e:
            logger.error(f"Error enabling tool deduplication: {e}")

    def enable_tool_streaming(self):
        """Enable streaming for all tools."""
        if not self.streaming_manager:
            logger.warning("Streaming manager not available")
            return

        try:
            from brain_researcher.services.tools.streaming_integration import (
                wrap_tools_for_streaming,
            )

            wrap_tools_for_streaming(self, self.streaming_manager)
            logger.info("Enabled streaming for all tools")
        except Exception as e:
            logger.error(f"Error enabling tool streaming: {e}")

    async def subscribe_to_analysis_events(self, thread_id: str):
        """Subscribe a thread to analysis events.

        Args:
            thread_id: Thread ID to subscribe
        """
        if self.subscription_manager:
            try:
                from brain_researcher.services.tools.subscription_integration import (
                    subscribe_agent_to_analysis_events,
                )

                await subscribe_agent_to_analysis_events(
                    self.subscription_manager, thread_id
                )
                self.integration_stats["subscriptions_active"] += 1
            except Exception as e:
                logger.error(f"Error subscribing to analysis events: {e}")
        else:
            logger.warning("Subscription manager not available")

    def get_integration_info(self) -> dict[str, Any]:
        """Get information about enabled integrations.

        Returns:
            Integration information dictionary
        """
        info = {
            "integrations_enabled": self.enable_integrations,
            "integrations_available": INTEGRATIONS_AVAILABLE,
            "statistics": self.integration_stats.copy(),
        }

        if self.subscription_manager:
            info["subscription_stats"] = self.subscription_manager.get_statistics()

        if self.streaming_manager:
            info["streaming_stats"] = self.streaming_manager.get_statistics()

        if self.deduplication_manager:
            info["deduplication_stats"] = self.deduplication_manager.get_statistics()

        if self.plugin_manager:
            info["plugin_stats"] = self.plugin_manager.get_statistics()

        return info

    async def shutdown_integrations(self):
        """Shutdown all integrations gracefully."""
        if self.streaming_manager:
            try:
                await self.streaming_manager.stop()
                logger.info("Streaming manager stopped")
            except Exception as e:
                logger.error(f"Error stopping streaming manager: {e}")

        logger.info("All integrations shutdown completed")


class DynamicToolLoader:
    """
    Loader for dynamically discovering and loading tools from modules.

    Useful for plugin-style tool additions.
    """

    @staticmethod
    def load_tools_from_module(module_path: str) -> list[NeuroToolWrapper]:
        """
        Load all tool classes from a module.

        Args:
            module_path: Python module path (e.g., 'custom_tools.my_tools')

        Returns:
            List of tool instances
        """
        tools = []

        try:
            module = importlib.import_module(module_path)

            # Find all classes that inherit from NeuroToolWrapper
            for name, obj in inspect.getmembers(module):
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, NeuroToolWrapper)
                    and obj != NeuroToolWrapper
                ):
                    try:
                        # Instantiate the tool
                        tool_instance = obj()
                        tools.append(tool_instance)
                        logger.info(f"Loaded tool: {tool_instance.get_tool_name()}")
                    except Exception as e:
                        logger.error(f"Failed to instantiate {name}: {e}")

        except ImportError as e:
            logger.error(f"Failed to import module {module_path}: {e}")

        return tools

    @staticmethod
    def load_tools_from_directory(directory: str) -> list[NeuroToolWrapper]:
        """
        Load all tools from Python files in a directory.

        Args:
            directory: Directory path containing tool modules

        Returns:
            List of tool instances
        """
        tools = []

        if not os.path.exists(directory):
            logger.warning(f"Directory {directory} does not exist")
            return tools

        # Add directory to Python path temporarily
        import sys

        sys.path.insert(0, directory)

        try:
            for filename in os.listdir(directory):
                if filename.endswith(".py") and not filename.startswith("_"):
                    module_name = filename[:-3]  # Remove .py extension
                    module_tools = DynamicToolLoader.load_tools_from_module(module_name)
                    tools.extend(module_tools)
        finally:
            # Remove from path
            sys.path.pop(0)

        return tools


def _register_shared_tool_registry_factory() -> None:
    """Expose ToolRegistry through the shared BR-KG facade when imported."""

    try:
        from brain_researcher.services.shared.tool_registry_facade import (
            register_default_tool_registry,
        )

        register_default_tool_registry(ToolRegistry)
    except Exception as exc:  # pragma: no cover - defensive import guard
        logger.debug("Failed to register shared tool-registry facade: %s", exc)


_register_shared_tool_registry_factory()
