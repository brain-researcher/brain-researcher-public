"""Adapters for converting between different plan representations.

This package provides adapters to convert Plan/PlanDAG/StepSpec objects
to workflow engine formats:

- Nipype: Traditional neuroimaging workflow engine
- Pydra: Next-generation workflow engine with async support
"""

from brain_researcher.services.agent.adapters.plan_to_nipype import (
    SUPPORTED_RUNTIME_KINDS,
    UNSUPPORTED_RUNTIME_KINDS,
    NipypeExportResult,
    export_plan_to_nipype,
    plan_to_nipype_builder_args,
)
from brain_researcher.services.agent.adapters.plan_to_pydra import (
    PydraExportResult,
    PydraInterfaceSpec,
    export_plan_to_pydra,
    get_pydra_interface_spec,
    load_pydra_tool_interface_map,
    plan_to_pydra_workflow,
)
from brain_researcher.services.agent.adapters.tool_interface_map import (
    CORE_TOOL_TO_INTERFACE,
    InterfaceSpec,
    IOMap,
    get_interface_spec,
    load_tool_interface_map,
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
