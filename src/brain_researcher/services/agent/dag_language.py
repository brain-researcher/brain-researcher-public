"""
Complex DAG Definition Language for Brain Researcher

This module provides a YAML/JSON-based DAG definition language that supports:
- Conditional branching (if/else/switch)
- Loop constructs (for/while with bounds)
- Dynamic parameter substitution
- Sub-DAG composition
- Error handling with retry policies
"""

import yaml
import json
from typing import Dict, List, Optional, Any, Union, Set
from dataclasses import dataclass, field
from enum import Enum
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class NodeType(Enum):
    TOOL = "tool"
    CONDITIONAL = "conditional"
    LOOP = "loop"
    SUBDAG = "subdag"
    PARALLEL = "parallel"


class LoopType(Enum):
    FOR = "for"
    WHILE = "while"
    FOREACH = "foreach"


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_multiplier: float = 2.0
    max_delay: float = 300.0
    retry_on: List[str] = field(default_factory=lambda: ["TIMEOUT", "RESOURCE_ERROR"])


@dataclass
class ConditionalBranch:
    condition: str
    nodes: List[str]


@dataclass
class LoopConfig:
    loop_type: LoopType
    condition: Optional[str] = None
    items: Optional[str] = None  # Parameter name for foreach
    max_iterations: int = 100
    body: List[str] = field(default_factory=list)
    break_condition: Optional[str] = None


@dataclass
class DAGNode:
    id: str
    type: NodeType
    dependencies: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    retry_policy: Optional[RetryPolicy] = None
    timeout: Optional[int] = None

    # Tool-specific
    tool: Optional[str] = None

    # Conditional-specific
    condition: Optional[str] = None
    true_branch: List[str] = field(default_factory=list)
    false_branch: List[str] = field(default_factory=list)
    switch_branches: Dict[str, List[str]] = field(default_factory=dict)
    default_branch: List[str] = field(default_factory=list)

    # Loop-specific
    loop_config: Optional[LoopConfig] = None

    # SubDAG-specific
    subdag_path: Optional[str] = None
    subdag_parameters: Dict[str, Any] = field(default_factory=dict)

    # Parallel-specific
    parallel_nodes: List[str] = field(default_factory=list)
    parallel_strategy: str = "all_success"  # all_success, any_success, continue_on_failure


@dataclass
class DAGDefinition:
    name: str
    version: str = "1.0"
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    nodes: Dict[str, DAGNode] = field(default_factory=dict)
    edges: List[tuple] = field(default_factory=list)
    global_retry_policy: Optional[RetryPolicy] = None
    global_timeout: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: DAGNode) -> None:
        """Add a node to the DAG"""
        self.nodes[node.id] = node

    def add_edge(self, from_node: str, to_node: str) -> None:
        """Add a dependency edge between nodes"""
        self.edges.append((from_node, to_node))
        if to_node in self.nodes:
            if from_node not in self.nodes[to_node].dependencies:
                self.nodes[to_node].dependencies.append(from_node)

    def validate(self) -> List[str]:
        """Validate the DAG structure and return any errors"""
        errors = []

        # Check for cycles
        if self._has_cycles():
            errors.append("DAG contains cycles")

        # Validate node references
        for node_id, node in self.nodes.items():
            # Check dependencies exist
            for dep in node.dependencies:
                if dep not in self.nodes:
                    errors.append(f"Node {node_id} depends on non-existent node {dep}")

            # Validate conditional branches
            if node.type == NodeType.CONDITIONAL:
                for branch_node in node.true_branch + node.false_branch:
                    if branch_node not in self.nodes:
                        errors.append(f"Conditional node {node_id} references non-existent node {branch_node}")

            # Validate loop bodies
            if node.type == NodeType.LOOP and node.loop_config:
                for body_node in node.loop_config.body:
                    if body_node not in self.nodes:
                        errors.append(f"Loop node {node_id} references non-existent node {body_node}")

            # Validate parallel nodes
            if node.type == NodeType.PARALLEL:
                for parallel_node in node.parallel_nodes:
                    if parallel_node not in self.nodes:
                        errors.append(f"Parallel node {node_id} references non-existent node {parallel_node}")

        # Validate parameters
        for param_name, param_value in self.parameters.items():
            if isinstance(param_value, str) and self._has_circular_parameter_reference(param_name, param_value):
                errors.append(f"Circular parameter reference detected for {param_name}")

        return errors

    def _has_cycles(self) -> bool:
        """Check if the DAG has cycles using DFS"""
        visited = set()
        rec_stack = set()

        def dfs(node_id: str) -> bool:
            if node_id in rec_stack:
                return True
            if node_id in visited:
                return False

            visited.add(node_id)
            rec_stack.add(node_id)

            # Check dependencies
            if node_id in self.nodes:
                for dep in self.nodes[node_id].dependencies:
                    if dfs(dep):
                        return True

            rec_stack.remove(node_id)
            return False

        for node_id in self.nodes:
            if node_id not in visited:
                if dfs(node_id):
                    return True
        return False

    def _has_circular_parameter_reference(self, param_name: str, param_value: str) -> bool:
        """Check for circular parameter references"""
        if not isinstance(param_value, str):
            return False

        # Simple check for ${param_name} in param_value
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, param_value)
        return param_name in matches

    def get_root_nodes(self) -> List[str]:
        """Get nodes with no dependencies"""
        return [node_id for node_id, node in self.nodes.items() if not node.dependencies]

    def get_execution_order(self) -> List[List[str]]:
        """Get topological ordering of nodes as execution levels"""
        levels = []
        processed = set()

        while len(processed) < len(self.nodes):
            current_level = []
            for node_id, node in self.nodes.items():
                if node_id not in processed:
                    if all(dep in processed for dep in node.dependencies):
                        current_level.append(node_id)

            if not current_level:
                # This should not happen if DAG is valid
                break

            levels.append(current_level)
            processed.update(current_level)

        return levels

    @classmethod
    def from_yaml(cls, yaml_content: str) -> 'DAGDefinition':
        """Parse DAG definition from YAML content"""
        try:
            data = yaml.safe_load(yaml_content)
            return cls._from_dict(data)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}")

    @classmethod
    def from_json(cls, json_content: str) -> 'DAGDefinition':
        """Parse DAG definition from JSON content"""
        try:
            data = json.loads(json_content)
            return cls._from_dict(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

    @classmethod
    def from_file(cls, file_path: Union[str, Path]) -> 'DAGDefinition':
        """Load DAG definition from file"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"DAG file not found: {file_path}")

        content = path.read_text()
        if path.suffix.lower() in ['.yaml', '.yml']:
            return cls.from_yaml(content)
        elif path.suffix.lower() == '.json':
            return cls.from_json(content)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")

    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> 'DAGDefinition':
        """Create DAG definition from dictionary"""
        dag = cls(
            name=data.get('name', 'unnamed'),
            version=data.get('version', '1.0'),
            description=data.get('description', ''),
            parameters=data.get('parameters', {}),
            metadata=data.get('metadata', {})
        )

        # Parse global retry policy
        if 'global_retry_policy' in data:
            dag.global_retry_policy = cls._parse_retry_policy(data['global_retry_policy'])

        dag.global_timeout = data.get('global_timeout')

        # Parse nodes
        nodes_data = data.get('nodes', [])
        if isinstance(nodes_data, list):
            for node_data in nodes_data:
                node = cls._parse_node(node_data)
                dag.add_node(node)
        elif isinstance(nodes_data, dict):
            for node_id, node_data in nodes_data.items():
                node_data['id'] = node_id
                node = cls._parse_node(node_data)
                dag.add_node(node)

        # Parse edges
        edges_data = data.get('edges', [])
        for edge in edges_data:
            if isinstance(edge, list) and len(edge) == 2:
                dag.add_edge(edge[0], edge[1])
            elif isinstance(edge, dict):
                dag.add_edge(edge['from'], edge['to'])

        return dag

    @staticmethod
    def _parse_node(node_data: Dict[str, Any]) -> DAGNode:
        """Parse a single node from dictionary"""
        node = DAGNode(
            id=node_data['id'],
            type=NodeType(node_data.get('type', 'tool')),
            dependencies=node_data.get('dependencies', []),
            parameters=node_data.get('parameters', {}),
            timeout=node_data.get('timeout'),
            tool=node_data.get('tool')
        )

        # Parse retry policy
        if 'retry_policy' in node_data:
            node.retry_policy = DAGDefinition._parse_retry_policy(node_data['retry_policy'])

        # Parse conditional fields
        if node.type == NodeType.CONDITIONAL:
            node.condition = node_data.get('condition')
            node.true_branch = node_data.get('true_branch', [])
            node.false_branch = node_data.get('false_branch', [])
            node.switch_branches = node_data.get('switch_branches', {})
            node.default_branch = node_data.get('default_branch', [])

        # Parse loop fields
        if node.type == NodeType.LOOP:
            loop_data = node_data.get('loop_config', {})
            node.loop_config = LoopConfig(
                loop_type=LoopType(loop_data.get('loop_type', 'for')),
                condition=loop_data.get('condition'),
                items=loop_data.get('items'),
                max_iterations=loop_data.get('max_iterations', 100),
                body=loop_data.get('body', []),
                break_condition=loop_data.get('break_condition')
            )

        # Parse subdag fields
        if node.type == NodeType.SUBDAG:
            node.subdag_path = node_data.get('subdag_path')
            node.subdag_parameters = node_data.get('subdag_parameters', {})

        # Parse parallel fields
        if node.type == NodeType.PARALLEL:
            node.parallel_nodes = node_data.get('parallel_nodes', [])
            node.parallel_strategy = node_data.get('parallel_strategy', 'all_success')

        return node

    @staticmethod
    def _parse_retry_policy(retry_data: Dict[str, Any]) -> RetryPolicy:
        """Parse retry policy from dictionary"""
        return RetryPolicy(
            max_attempts=retry_data.get('max_attempts', 3),
            backoff_multiplier=retry_data.get('backoff_multiplier', 2.0),
            max_delay=retry_data.get('max_delay', 300.0),
            retry_on=retry_data.get('retry_on', ["TIMEOUT", "RESOURCE_ERROR"])
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert DAG definition to dictionary"""
        nodes_dict = {}
        for node_id, node in self.nodes.items():
            node_dict = {
                'id': node.id,
                'type': node.type.value,
                'dependencies': node.dependencies,
                'parameters': node.parameters
            }

            if node.timeout:
                node_dict['timeout'] = node.timeout

            if node.retry_policy:
                node_dict['retry_policy'] = {
                    'max_attempts': node.retry_policy.max_attempts,
                    'backoff_multiplier': node.retry_policy.backoff_multiplier,
                    'max_delay': node.retry_policy.max_delay,
                    'retry_on': node.retry_policy.retry_on
                }

            if node.type == NodeType.TOOL and node.tool:
                node_dict['tool'] = node.tool
            elif node.type == NodeType.CONDITIONAL:
                node_dict.update({
                    'condition': node.condition,
                    'true_branch': node.true_branch,
                    'false_branch': node.false_branch,
                    'switch_branches': node.switch_branches,
                    'default_branch': node.default_branch
                })
            elif node.type == NodeType.LOOP and node.loop_config:
                node_dict['loop_config'] = {
                    'loop_type': node.loop_config.loop_type.value,
                    'condition': node.loop_config.condition,
                    'items': node.loop_config.items,
                    'max_iterations': node.loop_config.max_iterations,
                    'body': node.loop_config.body,
                    'break_condition': node.loop_config.break_condition
                }
            elif node.type == NodeType.SUBDAG:
                node_dict.update({
                    'subdag_path': node.subdag_path,
                    'subdag_parameters': node.subdag_parameters
                })
            elif node.type == NodeType.PARALLEL:
                node_dict.update({
                    'parallel_nodes': node.parallel_nodes,
                    'parallel_strategy': node.parallel_strategy
                })

            nodes_dict[node_id] = node_dict

        result = {
            'name': self.name,
            'version': self.version,
            'description': self.description,
            'parameters': self.parameters,
            'nodes': nodes_dict,
            'edges': [{'from': edge[0], 'to': edge[1]} for edge in self.edges],
            'metadata': self.metadata
        }

        if self.global_retry_policy:
            result['global_retry_policy'] = {
                'max_attempts': self.global_retry_policy.max_attempts,
                'backoff_multiplier': self.global_retry_policy.backoff_multiplier,
                'max_delay': self.global_retry_policy.max_delay,
                'retry_on': self.global_retry_policy.retry_on
            }

        if self.global_timeout:
            result['global_timeout'] = self.global_timeout

        return result

    def to_yaml(self) -> str:
        """Convert DAG definition to YAML string"""
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    def to_json(self) -> str:
        """Convert DAG definition to JSON string"""
        return json.dumps(self.to_dict(), indent=2)


class ParameterResolver:
    """Resolves dynamic parameters in DAG definitions"""

    @staticmethod
    def resolve_parameters(value: Any, context: Dict[str, Any]) -> Any:
        """Resolve parameter substitutions in values"""
        if isinstance(value, str):
            return ParameterResolver._resolve_string(value, context)
        elif isinstance(value, dict):
            return {k: ParameterResolver.resolve_parameters(v, context) for k, v in value.items()}
        elif isinstance(value, list):
            return [ParameterResolver.resolve_parameters(item, context) for item in value]
        else:
            return value

    @staticmethod
    def _resolve_string(value: str, context: Dict[str, Any]) -> str:
        """Resolve parameter substitutions in a string"""
        pattern = r'\$\{([^}]+)\}'

        def replacer(match):
            param_name = match.group(1)
            if param_name in context:
                return str(context[param_name])
            else:
                logger.warning(f"Parameter {param_name} not found in context")
                return match.group(0)  # Return original if not found

        return re.sub(pattern, replacer, value)


# Example DAG definitions for testing and documentation
EXAMPLE_DAG_YAML = """
name: neuroimaging_analysis
version: "1.0"
description: Complex neuroimaging analysis with conditionals and loops
parameters:
  subject_id: "${SUBJECT_ID}"
  threshold: 0.05
  max_subjects: 50

global_retry_policy:
  max_attempts: 3
  backoff_multiplier: 2.0
  max_delay: 300

nodes:
  - id: preprocessing
    type: tool
    tool: fmriprep
    parameters:
      input: "${subject_id}"
      output_space: "MNI152NLin2009cAsym"
    timeout: 3600

  - id: quality_check
    type: conditional
    dependencies: [preprocessing]
    condition: "preprocessing.qc_score > 0.8"
    true_branch: [first_level_analysis]
    false_branch: [enhanced_preprocessing]

  - id: enhanced_preprocessing
    type: tool
    tool: enhanced_fmriprep
    parameters:
      input: "${subject_id}"
      aggressive_denoising: true

  - id: first_level_analysis
    type: tool
    tool: nilearn_glm
    dependencies: [quality_check]
    parameters:
      smoothing_fwhm: 6
      threshold: "${threshold}"

  - id: group_loop
    type: loop
    dependencies: [first_level_analysis]
    loop_config:
      loop_type: for
      items: "subjects"
      max_iterations: 100
      body: [subject_stats, collect_results]
      break_condition: "len(results) >= max_subjects"

  - id: subject_stats
    type: tool
    tool: compute_statistics
    parameters:
      method: "group_comparison"

  - id: collect_results
    type: tool
    tool: aggregate_results

  - id: generate_report
    type: tool
    tool: create_report
    dependencies: [group_loop]
    parameters:
      format: "html"
      include_plots: true

edges:
  - from: preprocessing
    to: quality_check
  - from: quality_check
    to: first_level_analysis
  - from: quality_check
    to: enhanced_preprocessing
  - from: enhanced_preprocessing
    to: first_level_analysis
  - from: first_level_analysis
    to: group_loop
  - from: group_loop
    to: generate_report
"""


if __name__ == "__main__":
    # Test the DAG language implementation
    dag = DAGDefinition.from_yaml(EXAMPLE_DAG_YAML)

    # Validate the DAG
    errors = dag.validate()
    if errors:
        print("Validation errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("DAG validation successful")

    # Print execution order
    print("\nExecution order:")
    for i, level in enumerate(dag.get_execution_order()):
        print(f"  Level {i}: {level}")

    # Test parameter resolution
    context = {
        "SUBJECT_ID": "sub-001",
        "subjects": ["sub-001", "sub-002", "sub-003"],
        "max_subjects": 3
    }

    resolved_params = ParameterResolver.resolve_parameters(dag.parameters, context)
    print(f"\nResolved parameters: {resolved_params}")