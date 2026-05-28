"""
Mock execution plan classes for optimization testing.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class ResourceType(str, Enum):
    """Types of computational resources."""
    CPU = "cpu"
    MEMORY = "memory"
    STORAGE = "storage"
    GPU = "gpu"
    NETWORK = "network"


@dataclass
class WorkflowStep:
    """Mock workflow step for testing."""
    step_id: str
    step_number: int
    description: str
    tool_name: str
    tool_args: Dict[str, Any]
    dependencies: List[str] = field(default_factory=list)
    expected_output: str = ""
    estimated_time_seconds: float = 3600.0
    resource_requirements: Dict[str, float] = field(default_factory=dict)
    
    def __post_init__(self):
        """Ensure resource requirements have defaults."""
        if not self.resource_requirements:
            self.resource_requirements = {
                "cpu": 1.0,
                "memory": 4.0,
                "storage": 10.0
            }


@dataclass 
class ExecutionPlan:
    """Mock execution plan for testing."""
    plan_id: str
    steps: List[WorkflowStep]
    description: str = ""
    created_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Set defaults after initialization."""
        if self.created_at is None:
            import time
            self.created_at = time.time()


def create_mock_execution_plan(test_data: Dict[str, Any]) -> ExecutionPlan:
    """
    Create mock execution plan from test data.
    
    Args:
        test_data: Dictionary containing plan data
        
    Returns:
        ExecutionPlan instance
    """
    steps = []
    for step_data in test_data["steps"]:
        step = WorkflowStep(
            step_id=step_data["step_id"],
            step_number=step_data["step_number"],
            description=step_data["description"],
            tool_name=step_data["tool_name"],
            tool_args=step_data["tool_args"],
            dependencies=step_data.get("dependencies", []),
            expected_output=step_data.get("expected_output", ""),
            estimated_time_seconds=step_data.get("estimated_time_seconds", 3600.0),
            resource_requirements=step_data.get("resource_requirements", {})
        )
        steps.append(step)
    
    plan = ExecutionPlan(
        plan_id=test_data["plan_id"],
        steps=steps,
        description=test_data.get("description", "")
    )
    
    return plan


def create_simple_plan() -> ExecutionPlan:
    """Create a simple execution plan for testing."""
    steps = [
        WorkflowStep(
            step_id="preprocess",
            step_number=1,
            description="Data preprocessing",
            tool_name="fmriprep",
            tool_args={"input": "/data/raw", "output": "/data/preprocessed"},
            estimated_time_seconds=3600.0,
            resource_requirements={"cpu": 4.0, "memory": 8.0, "storage": 20.0}
        ),
        WorkflowStep(
            step_id="analysis",
            step_number=2,
            description="Statistical analysis",
            tool_name="fsl_feat", 
            tool_args={"input": "/data/preprocessed"},
            dependencies=["preprocess"],
            estimated_time_seconds=1800.0,
            resource_requirements={"cpu": 2.0, "memory": 4.0, "storage": 10.0}
        ),
        WorkflowStep(
            step_id="report",
            step_number=3,
            description="Generate report",
            tool_name="report_generator",
            tool_args={"analysis_results": "analysis"},
            dependencies=["analysis"],
            estimated_time_seconds=600.0,
            resource_requirements={"cpu": 1.0, "memory": 2.0, "storage": 5.0}
        )
    ]
    
    return ExecutionPlan(
        plan_id="simple_test_plan",
        steps=steps,
        description="Simple test plan for optimization"
    )


def create_complex_plan() -> ExecutionPlan:
    """Create a complex execution plan for testing."""
    steps = [
        # Data validation
        WorkflowStep(
            step_id="validation",
            step_number=1,
            description="Data validation",
            tool_name="bids_validator",
            tool_args={"dataset": "/data/bids"},
            estimated_time_seconds=300.0,
            resource_requirements={"cpu": 1.0, "memory": 2.0, "storage": 1.0}
        ),
        
        # Parallel preprocessing for multiple subjects
        WorkflowStep(
            step_id="preproc_sub01",
            step_number=2,
            description="Preprocess subject 01",
            tool_name="fmriprep",
            tool_args={"subject": "sub-01"},
            dependencies=["validation"],
            estimated_time_seconds=7200.0,
            resource_requirements={"cpu": 4.0, "memory": 8.0, "storage": 30.0}
        ),
        WorkflowStep(
            step_id="preproc_sub02",
            step_number=3,
            description="Preprocess subject 02",
            tool_name="fmriprep",
            tool_args={"subject": "sub-02"},
            dependencies=["validation"],
            estimated_time_seconds=7200.0,
            resource_requirements={"cpu": 4.0, "memory": 8.0, "storage": 30.0}
        ),
        WorkflowStep(
            step_id="preproc_sub03",
            step_number=4,
            description="Preprocess subject 03",
            tool_name="fmriprep",
            tool_args={"subject": "sub-03"},
            dependencies=["validation"],
            estimated_time_seconds=7200.0,
            resource_requirements={"cpu": 4.0, "memory": 8.0, "storage": 30.0}
        ),
        
        # Individual analyses
        WorkflowStep(
            step_id="glm_sub01",
            step_number=5,
            description="GLM analysis subject 01",
            tool_name="fsl_feat",
            tool_args={"subject": "sub-01"},
            dependencies=["preproc_sub01"],
            estimated_time_seconds=1800.0,
            resource_requirements={"cpu": 2.0, "memory": 4.0, "storage": 10.0}
        ),
        WorkflowStep(
            step_id="glm_sub02",
            step_number=6,
            description="GLM analysis subject 02",
            tool_name="fsl_feat",
            tool_args={"subject": "sub-02"},
            dependencies=["preproc_sub02"],
            estimated_time_seconds=1800.0,
            resource_requirements={"cpu": 2.0, "memory": 4.0, "storage": 10.0}
        ),
        WorkflowStep(
            step_id="glm_sub03",
            step_number=7,
            description="GLM analysis subject 03",
            tool_name="fsl_feat",
            tool_args={"subject": "sub-03"},
            dependencies=["preproc_sub03"],
            estimated_time_seconds=1800.0,
            resource_requirements={"cpu": 2.0, "memory": 4.0, "storage": 10.0}
        ),
        
        # Group analysis
        WorkflowStep(
            step_id="group_analysis",
            step_number=8,
            description="Group analysis",
            tool_name="fsl_randomise",
            tool_args={"subjects": ["sub-01", "sub-02", "sub-03"]},
            dependencies=["glm_sub01", "glm_sub02", "glm_sub03"],
            estimated_time_seconds=3600.0,
            resource_requirements={"cpu": 8.0, "memory": 16.0, "storage": 20.0}
        ),
        
        # Final report
        WorkflowStep(
            step_id="final_report",
            step_number=9,
            description="Generate final report",
            tool_name="report_generator",
            tool_args={"group_results": "group_analysis"},
            dependencies=["group_analysis"],
            estimated_time_seconds=900.0,
            resource_requirements={"cpu": 1.0, "memory": 2.0, "storage": 5.0}
        )
    ]
    
    return ExecutionPlan(
        plan_id="complex_test_plan",
        steps=steps,
        description="Complex multi-subject analysis plan"
    )


def create_resource_intensive_plan() -> ExecutionPlan:
    """Create a resource-intensive plan for testing."""
    steps = [
        WorkflowStep(
            step_id="freesurfer_recon",
            step_number=1,
            description="FreeSurfer reconstruction",
            tool_name="freesurfer_recon_all",
            tool_args={"subject": "sub-01"},
            estimated_time_seconds=28800.0,  # 8 hours
            resource_requirements={"cpu": 8.0, "memory": 16.0, "storage": 50.0}
        ),
        WorkflowStep(
            step_id="fmriprep_full",
            step_number=2,
            description="Full fMRIPrep preprocessing",
            tool_name="fmriprep",
            tool_args={"full_pipeline": True},
            estimated_time_seconds=14400.0,  # 4 hours
            resource_requirements={"cpu": 8.0, "memory": 16.0, "storage": 40.0}
        ),
        WorkflowStep(
            step_id="connectivity_full",
            step_number=3,
            description="Full connectivity analysis",
            tool_name="connectivity_analysis",
            tool_args={"method": "full_correlation"},
            dependencies=["fmriprep_full"],
            estimated_time_seconds=10800.0,  # 3 hours
            resource_requirements={"cpu": 16.0, "memory": 32.0, "storage": 30.0}
        ),
        WorkflowStep(
            step_id="meta_analysis",
            step_number=4,
            description="Meta-analysis",
            tool_name="nimare_meta_analysis",
            tool_args={"datasets": ["neurosynth", "brainmap"]},
            dependencies=["connectivity_full"],
            estimated_time_seconds=7200.0,  # 2 hours
            resource_requirements={"cpu": 4.0, "memory": 12.0, "storage": 25.0}
        )
    ]
    
    return ExecutionPlan(
        plan_id="resource_intensive_plan",
        steps=steps,
        description="Resource-intensive neuroimaging pipeline"
    )


def create_parallel_optimizable_plan() -> ExecutionPlan:
    """Create a plan that can benefit from parallelization optimization."""
    steps = []
    
    # Create many independent preprocessing tasks
    for i in range(6):
        step = WorkflowStep(
            step_id=f"preprocess_run_{i+1:02d}",
            step_number=i + 1,
            description=f"Preprocess run {i+1:02d}",
            tool_name="fmriprep",
            tool_args={"run": f"run-{i+1:02d}"},
            estimated_time_seconds=3600.0,
            resource_requirements={"cpu": 2.0, "memory": 4.0, "storage": 15.0}
        )
        steps.append(step)
    
    # Create GLM analyses that depend on preprocessing
    for i in range(6):
        step = WorkflowStep(
            step_id=f"glm_run_{i+1:02d}",
            step_number=i + 7,
            description=f"GLM analysis run {i+1:02d}",
            tool_name="fsl_feat",
            tool_args={"run": f"run-{i+1:02d}"},
            dependencies=[f"preprocess_run_{i+1:02d}"],
            estimated_time_seconds=1800.0,
            resource_requirements={"cpu": 1.0, "memory": 2.0, "storage": 8.0}
        )
        steps.append(step)
    
    # Final aggregation step
    aggregate_step = WorkflowStep(
        step_id="aggregate_results",
        step_number=13,
        description="Aggregate all results",
        tool_name="aggregate_tool",
        tool_args={"runs": [f"run-{i+1:02d}" for i in range(6)]},
        dependencies=[f"glm_run_{i+1:02d}" for i in range(6)],
        estimated_time_seconds=1200.0,
        resource_requirements={"cpu": 4.0, "memory": 8.0, "storage": 20.0}
    )
    steps.append(aggregate_step)
    
    return ExecutionPlan(
        plan_id="parallel_optimizable_plan",
        steps=steps,
        description="Plan optimizable for parallel execution"
    )