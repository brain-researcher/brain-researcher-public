"""Adapters for converting between different plan representations.

This package provides adapters to convert Plan/PlanDAG/StepSpec objects
to workflow engine formats:

- Nipype: Traditional neuroimaging workflow engine
- Pydra: Next-generation workflow engine with async support
"""

from brain_researcher.services.agent.adapters.plan_to_nipype import (
    plan_to_nipype_builder_args,
    export_plan_to_nipype,
    NipypeExportResult,
    SUPPORTED_RUNTIME_KINDS,
    UNSUPPORTED_RUNTIME_KINDS,
)
from brain_researcher.services.agent.adapters.plan_to_pydra import (
    plan_to_pydra_workflow,
    export_plan_to_pydra,
    PydraExportResult,
    PydraInterfaceSpec,
    load_pydra_tool_interface_map,
    get_pydra_interface_spec,
)
from brain_researcher.services.agent.adapters.tool_interface_map import (
    load_tool_interface_map,
    get_interface_spec,
    CORE_TOOL_TO_INTERFACE,
    InterfaceSpec,
    IOMap,
)

__all__ = [
    # Plan to Nipype conversion
    "plan_to_nipype_builder_args",
    "export_plan_to_nipype",
    "NipypeExportResult",
    "SUPPORTED_RUNTIME_KINDS",
    "UNSUPPORTED_RUNTIME_KINDS",
    # Plan to Pydra conversion
    "plan_to_pydra_workflow",
    "export_plan_to_pydra",
    "PydraExportResult",
    "PydraInterfaceSpec",
    "load_pydra_tool_interface_map",
    "get_pydra_interface_spec",
    # Tool interface mapping (Nipype)
    "load_tool_interface_map",
    "get_interface_spec",
    "CORE_TOOL_TO_INTERFACE",
    "InterfaceSpec",
    "IOMap",
]
