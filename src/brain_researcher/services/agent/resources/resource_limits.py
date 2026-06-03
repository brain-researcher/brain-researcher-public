"""
Resource Limits and Tool Profiles for Brain Researcher Agent.

Defines resource requirements for each neuroimaging tool.
"""

import logging
from dataclasses import dataclass

from brain_researcher.services.agent.tool_metadata_bridge import get_resource_hints

logger = logging.getLogger(__name__)


@dataclass
class ToolResourceProfile:
    """Resource requirements for a tool."""

    tool_name: str
    cpu_cores: float
    memory_gb: float
    gpu_count: int = 0
    estimated_duration_seconds: float = 60.0
    max_concurrent: int = 2  # Max concurrent executions of this tool
    priority_boost: int = 0  # Priority adjustment (-1 to +1)

    @property
    def is_gpu_required(self) -> bool:
        """Check if GPU is required."""
        return self.gpu_count > 0

    @property
    def is_heavyweight(self) -> bool:
        """Check if this is a resource-intensive tool."""
        return self.cpu_cores >= 2 or self.memory_gb >= 4

    def scale_resources(self, factor: float) -> "ToolResourceProfile":
        """Scale resource requirements by a factor."""
        return ToolResourceProfile(
            tool_name=self.tool_name,
            cpu_cores=self.cpu_cores * factor,
            memory_gb=self.memory_gb * factor,
            gpu_count=self.gpu_count,
            estimated_duration_seconds=self.estimated_duration_seconds,
            max_concurrent=self.max_concurrent,
            priority_boost=self.priority_boost,
        )


# Default profile for unknown tools
DEFAULT_PROFILE = ToolResourceProfile(
    tool_name="default",
    cpu_cores=0.5,
    memory_gb=1.0,
    gpu_count=0,
    estimated_duration_seconds=30.0,
    max_concurrent=5,
)

# Tool resource profiles based on actual neuroimaging tool requirements
TOOL_PROFILES: dict[str, ToolResourceProfile] = {
    # fMRI Analysis Tools (Heavy)
    "glm_analysis": ToolResourceProfile(
        tool_name="glm_analysis",
        cpu_cores=2.0,
        memory_gb=4.0,
        gpu_count=0,
        estimated_duration_seconds=120.0,
        max_concurrent=2,
        priority_boost=0,
    ),
    "encoding_model": ToolResourceProfile(
        tool_name="encoding_model",
        cpu_cores=4.0,
        memory_gb=8.0,
        gpu_count=1,
        estimated_duration_seconds=300.0,
        max_concurrent=1,
        priority_boost=-1,  # Lower priority due to high resource use
    ),
    "contrast_analysis": ToolResourceProfile(
        tool_name="contrast_analysis",
        cpu_cores=1.0,
        memory_gb=2.0,
        gpu_count=0,
        estimated_duration_seconds=60.0,
        max_concurrent=3,
    ),
    "brain_similarity": ToolResourceProfile(
        tool_name="brain_similarity",
        cpu_cores=2.0,
        memory_gb=3.0,
        gpu_count=0,
        estimated_duration_seconds=90.0,
        max_concurrent=2,
    ),
    # Knowledge Graph Tools (Light)
    "find_related_concepts": ToolResourceProfile(
        tool_name="find_related_concepts",
        cpu_cores=0.5,
        memory_gb=0.5,
        gpu_count=0,
        estimated_duration_seconds=5.0,
        max_concurrent=10,
        priority_boost=1,  # Higher priority for quick queries
    ),
    "coordinate_to_concept": ToolResourceProfile(
        tool_name="coordinate_to_concept",
        cpu_cores=0.5,
        memory_gb=0.5,
        gpu_count=0,
        estimated_duration_seconds=3.0,
        max_concurrent=10,
        priority_boost=1,
    ),
    "concept_literature_search": ToolResourceProfile(
        tool_name="concept_literature_search",
        cpu_cores=0.5,
        memory_gb=1.0,
        gpu_count=0,
        estimated_duration_seconds=10.0,
        max_concurrent=5,
    ),
    "graph_query": ToolResourceProfile(
        tool_name="graph_query",
        cpu_cores=1.0,
        memory_gb=2.0,
        gpu_count=0,
        estimated_duration_seconds=15.0,
        max_concurrent=3,
    ),
    "task_to_concept_mapping": ToolResourceProfile(
        tool_name="task_to_concept_mapping",
        cpu_cores=0.25,
        memory_gb=0.25,
        gpu_count=0,
        estimated_duration_seconds=2.0,
        max_concurrent=20,
        priority_boost=1,
    ),
    # Meta-Analysis Tools (Medium)
    "neurosynth_meta_analysis": ToolResourceProfile(
        tool_name="neurosynth_meta_analysis",
        cpu_cores=1.0,
        memory_gb=2.0,
        gpu_count=0,
        estimated_duration_seconds=30.0,
        max_concurrent=3,
    ),
    "neurosynth_visualize": ToolResourceProfile(
        tool_name="neurosynth_visualize",
        cpu_cores=1.0,
        memory_gb=1.5,
        gpu_count=0,
        estimated_duration_seconds=20.0,
        max_concurrent=4,
    ),
    "neurosynth_search_terms": ToolResourceProfile(
        tool_name="neurosynth_search_terms",
        cpu_cores=0.5,
        memory_gb=0.5,
        gpu_count=0,
        estimated_duration_seconds=5.0,
        max_concurrent=10,
    ),
    "activation_likelihood": ToolResourceProfile(
        tool_name="activation_likelihood",
        cpu_cores=2.0,
        memory_gb=3.0,
        gpu_count=0,
        estimated_duration_seconds=60.0,
        max_concurrent=2,
    ),
    # Data Processing Tools (Variable)
    "validate_bids": ToolResourceProfile(
        tool_name="validate_bids",
        cpu_cores=0.5,
        memory_gb=1.0,
        gpu_count=0,
        estimated_duration_seconds=10.0,
        max_concurrent=5,
    ),
    "query_bids_layout": ToolResourceProfile(
        tool_name="query_bids_layout",
        cpu_cores=0.5,
        memory_gb=0.5,
        gpu_count=0,
        estimated_duration_seconds=5.0,
        max_concurrent=10,
    ),
    "preprocess_fmri": ToolResourceProfile(
        tool_name="preprocess_fmri",
        cpu_cores=4.0,
        memory_gb=16.0,
        gpu_count=0,
        estimated_duration_seconds=3600.0,  # 1 hour
        max_concurrent=1,
        priority_boost=-1,
    ),
    "quality_control": ToolResourceProfile(
        tool_name="quality_control",
        cpu_cores=1.0,
        memory_gb=2.0,
        gpu_count=0,
        estimated_duration_seconds=30.0,
        max_concurrent=3,
    ),
    # Archive/Conversion Tools (Light)
    "heudiconv_convert": ToolResourceProfile(
        tool_name="heudiconv_convert",
        cpu_cores=1.0,
        memory_gb=2.0,
        gpu_count=0,
        estimated_duration_seconds=60.0,
        max_concurrent=2,
    ),
    "extract_archive": ToolResourceProfile(
        tool_name="extract_archive",
        cpu_cores=0.5,
        memory_gb=1.0,
        gpu_count=0,
        estimated_duration_seconds=30.0,
        max_concurrent=3,
    ),
    "compress_archive": ToolResourceProfile(
        tool_name="compress_archive",
        cpu_cores=1.0,
        memory_gb=1.0,
        gpu_count=0,
        estimated_duration_seconds=60.0,
        max_concurrent=2,
    ),
    # NWB Tools (Light)
    "read_nwb": ToolResourceProfile(
        tool_name="read_nwb",
        cpu_cores=0.5,
        memory_gb=1.0,
        gpu_count=0,
        estimated_duration_seconds=5.0,
        max_concurrent=5,
    ),
    "write_nwb": ToolResourceProfile(
        tool_name="write_nwb",
        cpu_cores=0.5,
        memory_gb=1.0,
        gpu_count=0,
        estimated_duration_seconds=10.0,
        max_concurrent=5,
    ),
    "validate_nwb": ToolResourceProfile(
        tool_name="validate_nwb",
        cpu_cores=0.5,
        memory_gb=0.5,
        gpu_count=0,
        estimated_duration_seconds=5.0,
        max_concurrent=10,
    ),
    # Pipeline Tools (Heavy)
    "fmriprep_pipeline": ToolResourceProfile(
        tool_name="fmriprep_pipeline",
        cpu_cores=8.0,
        memory_gb=16.0,
        gpu_count=0,
        estimated_duration_seconds=7200.0,  # 2 hours
        max_concurrent=1,
        priority_boost=-1,
    ),
    "mriqc_pipeline": ToolResourceProfile(
        tool_name="mriqc_pipeline",
        cpu_cores=4.0,
        memory_gb=8.0,
        gpu_count=0,
        estimated_duration_seconds=3600.0,  # 1 hour
        max_concurrent=1,
        priority_boost=-1,
    ),
    # Statistical Tools (Medium)
    "multiple_comparison_correction": ToolResourceProfile(
        tool_name="multiple_comparison_correction",
        cpu_cores=1.0,
        memory_gb=2.0,
        gpu_count=0,
        estimated_duration_seconds=20.0,
        max_concurrent=3,
    ),
    "threshold_statistical_map": ToolResourceProfile(
        tool_name="threshold_statistical_map",
        cpu_cores=0.5,
        memory_gb=1.0,
        gpu_count=0,
        estimated_duration_seconds=5.0,
        max_concurrent=5,
    ),
    "cluster_analysis": ToolResourceProfile(
        tool_name="cluster_analysis",
        cpu_cores=1.0,
        memory_gb=2.0,
        gpu_count=0,
        estimated_duration_seconds=30.0,
        max_concurrent=3,
    ),
    # RAG Tools (Light to Medium)
    "semantic_search": ToolResourceProfile(
        tool_name="semantic_search",
        cpu_cores=1.0,
        memory_gb=2.0,
        gpu_count=0,
        estimated_duration_seconds=10.0,
        max_concurrent=5,
    ),
    "embed_documents": ToolResourceProfile(
        tool_name="embed_documents",
        cpu_cores=2.0,
        memory_gb=4.0,
        gpu_count=1,
        estimated_duration_seconds=60.0,
        max_concurrent=2,
    ),
    "query_knowledge_base": ToolResourceProfile(
        tool_name="query_knowledge_base",
        cpu_cores=0.5,
        memory_gb=1.0,
        gpu_count=0,
        estimated_duration_seconds=5.0,
        max_concurrent=10,
    ),
}


class ResourceLimits:
    """Manages resource limits and constraints."""

    def __init__(
        self,
        global_cpu_limit: float = 4.0,
        global_memory_limit: float = 8.0,
        global_gpu_limit: int = 0,
        per_tool_limits: dict[str, ToolResourceProfile] | None = None,
    ):
        """
        Initialize resource limits.

        Args:
            global_cpu_limit: Global CPU core limit
            global_memory_limit: Global memory limit in GB
            global_gpu_limit: Global GPU count limit
            per_tool_limits: Override profiles for specific tools
        """
        self.global_cpu_limit = global_cpu_limit
        self.global_memory_limit = global_memory_limit
        self.global_gpu_limit = global_gpu_limit

        # Merge default profiles with overrides
        self.tool_profiles = TOOL_PROFILES.copy()
        if per_tool_limits:
            self.tool_profiles.update(per_tool_limits)

        logger.info(
            f"ResourceLimits initialized: {global_cpu_limit} CPU, "
            f"{global_memory_limit}GB memory, {global_gpu_limit} GPU"
        )

    def get_tool_profile(self, tool_name: str) -> ToolResourceProfile:
        """Get resource profile for a tool."""
        base = self.tool_profiles.get(
            tool_name,
            ToolResourceProfile(
                tool_name=tool_name,
                cpu_cores=DEFAULT_PROFILE.cpu_cores,
                memory_gb=DEFAULT_PROFILE.memory_gb,
                gpu_count=DEFAULT_PROFILE.gpu_count,
                estimated_duration_seconds=DEFAULT_PROFILE.estimated_duration_seconds,
                max_concurrent=DEFAULT_PROFILE.max_concurrent,
                priority_boost=DEFAULT_PROFILE.priority_boost,
            ),
        )

        profile = _profile_with_hints(tool_name, base)

        # Ensure profile doesn't exceed global limits
        if profile.cpu_cores > self.global_cpu_limit:
            logger.warning(
                f"Tool {tool_name} requests {profile.cpu_cores} CPU cores, "
                f"but global limit is {self.global_cpu_limit}"
            )
            profile = profile.scale_resources(self.global_cpu_limit / profile.cpu_cores)

        if profile.memory_gb > self.global_memory_limit:
            logger.warning(
                f"Tool {tool_name} requests {profile.memory_gb}GB memory, "
                f"but global limit is {self.global_memory_limit}GB"
            )
            profile = profile.scale_resources(
                self.global_memory_limit / profile.memory_gb
            )

        return profile

    def can_execute_tool(self, tool_name: str, current_usage: dict[str, float]) -> bool:
        """
        Check if tool can be executed given current usage.

        Args:
            tool_name: Tool to check
            current_usage: Current resource usage (cpu_cores, memory_gb, gpus)

        Returns:
            True if tool can be executed
        """
        profile = self.get_tool_profile(tool_name)

        available_cpu = self.global_cpu_limit - current_usage.get("cpu_cores", 0)
        available_memory = self.global_memory_limit - current_usage.get("memory_gb", 0)
        available_gpu = self.global_gpu_limit - current_usage.get("gpus", 0)

        return (
            profile.cpu_cores <= available_cpu
            and profile.memory_gb <= available_memory
            and profile.gpu_count <= available_gpu
        )

    def get_resource_summary(self) -> dict[str, dict]:
        """Get summary of all tool resource requirements."""
        summary = {
            "lightweight": [],
            "medium": [],
            "heavyweight": [],
        }

        for tool_name, profile in self.tool_profiles.items():
            info = {
                "tool": tool_name,
                "cpu": profile.cpu_cores,
                "memory_gb": profile.memory_gb,
                "gpu": profile.gpu_count,
                "duration_s": profile.estimated_duration_seconds,
            }

            if profile.cpu_cores <= 0.5 and profile.memory_gb <= 1.0:
                summary["lightweight"].append(info)
            elif profile.is_heavyweight:
                summary["heavyweight"].append(info)
            else:
                summary["medium"].append(info)

        return summary


# Module-level function for easy access
def _profile_with_hints(
    tool_name: str,
    base: ToolResourceProfile,
    hint_key: str | None = None,
) -> ToolResourceProfile:
    """Merge MCP resource hints into an existing profile."""
    hint_target = hint_key or tool_name
    hints = get_resource_hints(hint_target)
    if not hints:
        return base

    cpu = float(hints.get("cpu", base.cpu_cores))
    mem = float(hints.get("mem_gb", base.memory_gb))
    gpu = int(hints.get("gpu", base.gpu_count or 0))

    boost = base.priority_boost
    if boost == 0:
        if cpu >= 4 or mem >= 16:
            boost = -1
        elif cpu <= 1 and mem <= 2:
            boost = 1

    return ToolResourceProfile(
        tool_name=tool_name,
        cpu_cores=max(cpu, 0.1),
        memory_gb=max(mem, 0.1),
        gpu_count=max(gpu, 0),
        estimated_duration_seconds=base.estimated_duration_seconds,
        max_concurrent=base.max_concurrent,
        priority_boost=boost,
    )


def get_tool_profile(tool_name: str) -> ToolResourceProfile:
    """Get resource profile for a tool."""
    base = TOOL_PROFILES.get(tool_name)
    if base:
        return _profile_with_hints(tool_name, base)

    return _profile_with_hints(
        DEFAULT_PROFILE.tool_name, DEFAULT_PROFILE, hint_key=tool_name
    )
