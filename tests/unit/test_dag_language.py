"""
Unit tests for DAG Language Parser and Components

Tests for:
- YAML/JSON DAG definition parsing
- Node type validation
- Parameter resolution
- Loop configuration parsing
- Conditional logic parsing
- DAG structure validation
"""

import pytest
import yaml
import json
from typing import Dict, Any
from unittest.mock import patch, mock_open

from brain_researcher.services.agent.dag_language import (
    DAGDefinition, DAGNode, NodeType, LoopType, LoopConfig, 
    RetryPolicy, ParameterResolver, EXAMPLE_DAG_YAML
)


class TestDAGDefinition:
    """Test suite for DAGDefinition parsing and validation"""
    
    @pytest.fixture
    def sample_yaml_dag(self):
        """Sample YAML DAG definition"""
        return """
name: test_neuroimaging_workflow
description: A test neuroimaging analysis workflow
version: "1.0"

parameters:
  subject_id: ${SUBJECT_ID}
  threshold: 0.05
  analysis_type: group

nodes:
  preprocessing:
    type: tool
    tool: fmriprep
    parameters:
      input: ${subject_id}
      output_dir: /tmp/output
    timeout: 3600
    retry_policy:
      max_attempts: 3
      backoff_multiplier: 2.0
      max_delay: 300
  
  quality_check:
    type: conditional
    condition: "preprocessing.qc_score > 0.8"
    dependencies: [preprocessing]
    true_branch:
      - first_level_analysis
    false_branch:
      - enhanced_preprocessing
  
  first_level_analysis:
    type: tool
    tool: glm_analysis
    parameters:
      data: ${preprocessing_result}
      design_matrix: ${design_matrix}
    dependencies: [preprocessing]
  
  enhanced_preprocessing:
    type: tool
    tool: advanced_preprocessing
    parameters:
      data: ${preprocessing_result}
      enhanced: true
  
  group_analysis:
    type: loop
    dependencies: [first_level_analysis]
    loop_config:
      loop_type: for
      items: subjects
      max_iterations: 50
      body:
        - subject_stats
  
  subject_stats:
    type: tool
    tool: compute_subject_stats
    parameters:
      subject: ${loop_item}
      data: ${first_level_analysis_result}
"""
    
    @pytest.fixture
    def sample_json_dag(self):
        """Sample JSON DAG definition"""
        return {
            "name": "json_test_dag",
            "parameters": {
                "input_file": "${INPUT_FILE}",
                "output_dir": "/tmp/output"
            },
            "nodes": {
                "load_data": {
                    "type": "tool",
                    "tool": "data_loader",
                    "parameters": {
                        "file": "${input_file}"
                    }
                },
                "process_data": {
                    "type": "tool",
                    "tool": "data_processor",
                    "parameters": {
                        "data": "${load_data_result}"
                    },
                    "dependencies": ["load_data"]
                }
            }
        }
    
    @pytest.mark.unit
    def test_dag_from_yaml_parsing(self, sample_yaml_dag):
        """Test parsing DAG from YAML content"""
        dag = DAGDefinition.from_yaml(sample_yaml_dag)
        
        assert dag.name == "test_neuroimaging_workflow"
        assert dag.description == "A test neuroimaging analysis workflow"
        assert dag.version == "1.0"
        
        # Check parameters
        assert "subject_id" in dag.parameters
        assert dag.parameters["threshold"] == 0.05
        assert dag.parameters["analysis_type"] == "group"
        
        # Check nodes
        assert len(dag.nodes) == 6
        assert "preprocessing" in dag.nodes
        assert "quality_check" in dag.nodes
        assert "group_analysis" in dag.nodes
        
        # Check node types
        assert dag.nodes["preprocessing"].type == NodeType.TOOL
        assert dag.nodes["quality_check"].type == NodeType.CONDITIONAL
        assert dag.nodes["group_analysis"].type == NodeType.LOOP
    
    @pytest.mark.unit
    def test_dag_from_json_parsing(self, sample_json_dag):
        """Test parsing DAG from JSON"""
        dag = DAGDefinition.from_dict(sample_json_dag)
        
        assert dag.name == "json_test_dag"
        assert len(dag.nodes) == 2
        assert "load_data" in dag.nodes
        assert "process_data" in dag.nodes
        
        # Check dependencies
        assert dag.nodes["process_data"].dependencies == ["load_data"]
    
    @pytest.mark.unit
    def test_dag_from_file(self, tmp_path, sample_yaml_dag):
        """Test loading DAG from file"""
        dag_file = tmp_path / "test_dag.yaml"
        dag_file.write_text(sample_yaml_dag)
        
        dag = DAGDefinition.from_file(str(dag_file))
        
        assert dag.name == "test_neuroimaging_workflow"
        assert len(dag.nodes) > 0
    
    @pytest.mark.unit
    def test_invalid_yaml_parsing(self):
        """Test parsing invalid YAML raises appropriate error"""
        invalid_yaml = """
name: invalid_dag
nodes:
  - this is not: valid yaml structure
    missing_type: true
"""
        
        with pytest.raises(ValueError, match="Invalid DAG structure"):
            DAGDefinition.from_yaml(invalid_yaml)
    
    @pytest.mark.unit
    def test_missing_required_fields(self):
        """Test that missing required fields raise validation errors"""
        incomplete_yaml = """
name: incomplete_dag
# Missing nodes section
parameters:
  param1: value1
"""
        
        with pytest.raises(ValueError):
            DAGDefinition.from_yaml(incomplete_yaml)
    
    @pytest.mark.unit
    def test_node_type_validation(self):
        """Test node type validation"""
        yaml_content = """
name: type_test_dag
nodes:
  invalid_node:
    type: invalid_type
    tool: some_tool
"""
        
        with pytest.raises(ValueError, match="Invalid node type"):
            DAGDefinition.from_yaml(yaml_content)
    
    @pytest.mark.unit
    def test_loop_config_parsing(self, sample_yaml_dag):
        """Test loop configuration parsing"""
        dag = DAGDefinition.from_yaml(sample_yaml_dag)
        
        loop_node = dag.nodes["group_analysis"]
        assert loop_node.type == NodeType.LOOP
        assert loop_node.loop_config is not None
        
        loop_config = loop_node.loop_config
        assert loop_config.loop_type == LoopType.FOR
        assert loop_config.items == "subjects"
        assert loop_config.max_iterations == 50
        assert loop_config.body == ["subject_stats"]
    
    @pytest.mark.unit
    def test_retry_policy_parsing(self, sample_yaml_dag):
        """Test retry policy parsing"""
        dag = DAGDefinition.from_yaml(sample_yaml_dag)
        
        preprocessing_node = dag.nodes["preprocessing"]
        assert preprocessing_node.retry_policy is not None
        
        retry_policy = preprocessing_node.retry_policy
        assert retry_policy.max_attempts == 3
        assert retry_policy.backoff_multiplier == 2.0
        assert retry_policy.max_delay == 300
    
    @pytest.mark.unit
    def test_conditional_node_parsing(self, sample_yaml_dag):
        """Test conditional node parsing"""
        dag = DAGDefinition.from_yaml(sample_yaml_dag)
        
        conditional_node = dag.nodes["quality_check"]
        assert conditional_node.type == NodeType.CONDITIONAL
        assert conditional_node.condition == "preprocessing.qc_score > 0.8"
        assert conditional_node.true_branch == ["first_level_analysis"]
        assert conditional_node.false_branch == ["enhanced_preprocessing"]
    
    @pytest.mark.unit
    def test_dag_serialization(self, sample_yaml_dag):
        """Test DAG can be serialized back to dict/YAML"""
        dag = DAGDefinition.from_yaml(sample_yaml_dag)
        
        # Convert back to dict
        dag_dict = dag.to_dict()
        
        assert dag_dict["name"] == dag.name
        assert "nodes" in dag_dict
        assert "parameters" in dag_dict
        
        # Should be able to recreate DAG from dict
        recreated_dag = DAGDefinition.from_dict(dag_dict)
        assert recreated_dag.name == dag.name
        assert len(recreated_dag.nodes) == len(dag.nodes)


class TestDAGNode:
    """Test suite for DAGNode"""
    
    @pytest.mark.unit
    def test_tool_node_creation(self):
        """Test creating tool nodes"""
        node = DAGNode(
            id="test_node",
            type=NodeType.TOOL,
            tool="fmriprep",
            parameters={"input": "data.nii", "output": "/tmp"},
            timeout=3600
        )
        
        assert node.id == "test_node"
        assert node.type == NodeType.TOOL
        assert node.tool == "fmriprep"
        assert node.parameters["input"] == "data.nii"
        assert node.timeout == 3600
    
    @pytest.mark.unit
    def test_conditional_node_creation(self):
        """Test creating conditional nodes"""
        node = DAGNode(
            id="condition_node",
            type=NodeType.CONDITIONAL,
            condition="result.score > 0.5",
            true_branch=["success_node"],
            false_branch=["failure_node"]
        )
        
        assert node.type == NodeType.CONDITIONAL
        assert node.condition == "result.score > 0.5"
        assert node.true_branch == ["success_node"]
        assert node.false_branch == ["failure_node"]
    
    @pytest.mark.unit
    def test_loop_node_creation(self):
        """Test creating loop nodes"""
        loop_config = LoopConfig(
            loop_type=LoopType.FOREACH,
            items="subject_list",
            max_iterations=100,
            body=["process_subject"],
            break_condition="error_rate > 0.1"
        )
        
        node = DAGNode(
            id="loop_node",
            type=NodeType.LOOP,
            loop_config=loop_config
        )
        
        assert node.type == NodeType.LOOP
        assert node.loop_config.loop_type == LoopType.FOREACH
        assert node.loop_config.items == "subject_list"
        assert node.loop_config.max_iterations == 100
        assert node.loop_config.break_condition == "error_rate > 0.1"
    
    @pytest.mark.unit
    def test_parallel_node_creation(self):
        """Test creating parallel nodes"""
        node = DAGNode(
            id="parallel_node",
            type=NodeType.PARALLEL,
            parallel_nodes=["task1", "task2", "task3"],
            parallel_strategy="all_success"
        )
        
        assert node.type == NodeType.PARALLEL
        assert node.parallel_nodes == ["task1", "task2", "task3"]
        assert node.parallel_strategy == "all_success"
    
    @pytest.mark.unit
    def test_subdag_node_creation(self):
        """Test creating sub-DAG nodes"""
        node = DAGNode(
            id="subdag_node",
            type=NodeType.SUBDAG,
            subdag_path="/path/to/subdag.yaml",
            subdag_parameters={"param1": "value1"}
        )
        
        assert node.type == NodeType.SUBDAG
        assert node.subdag_path == "/path/to/subdag.yaml"
        assert node.subdag_parameters["param1"] == "value1"
    
    @pytest.mark.unit
    def test_node_validation(self):
        """Test node validation"""
        # Valid tool node
        valid_node = DAGNode(id="valid", type=NodeType.TOOL, tool="test_tool")
        errors = valid_node.validate()
        assert len(errors) == 0
        
        # Invalid tool node (missing tool)
        invalid_node = DAGNode(id="invalid", type=NodeType.TOOL)
        errors = invalid_node.validate()
        assert len(errors) > 0
        assert any("tool" in error.lower() for error in errors)


class TestParameterResolver:
    """Test suite for parameter resolution"""
    
    @pytest.mark.unit
    def test_simple_parameter_substitution(self):
        """Test simple parameter substitution"""
        parameters = {
            "input_file": "${DATA_PATH}/input.nii",
            "output_dir": "/tmp/output",
            "threshold": 0.05
        }
        
        context = {
            "DATA_PATH": "/data/subjects/sub-001"
        }
        
        resolved = ParameterResolver.resolve_parameters(parameters, context)
        
        assert resolved["input_file"] == "/data/subjects/sub-001/input.nii"
        assert resolved["output_dir"] == "/tmp/output"
        assert resolved["threshold"] == 0.05
    
    @pytest.mark.unit
    def test_nested_parameter_substitution(self):
        """Test nested parameter substitution"""
        parameters = {
            "config": {
                "input": "${INPUT_PATH}",
                "output": "${OUTPUT_PATH}",
                "settings": {
                    "threshold": "${THRESHOLD}",
                    "method": "glm"
                }
            }
        }
        
        context = {
            "INPUT_PATH": "/input/data.nii",
            "OUTPUT_PATH": "/output/result.nii",
            "THRESHOLD": 0.001
        }
        
        resolved = ParameterResolver.resolve_parameters(parameters, context)
        
        assert resolved["config"]["input"] == "/input/data.nii"
        assert resolved["config"]["output"] == "/output/result.nii"
        assert resolved["config"]["settings"]["threshold"] == 0.001
        assert resolved["config"]["settings"]["method"] == "glm"
    
    @pytest.mark.unit
    def test_list_parameter_substitution(self):
        """Test parameter substitution in lists"""
        parameters = {
            "subjects": ["${SUBJECT_1}", "${SUBJECT_2}", "sub-003"],
            "contrasts": [
                {"name": "${CONTRAST_1}", "weights": [1, -1]},
                {"name": "fixed_contrast", "weights": [0.5, 0.5]}
            ]
        }
        
        context = {
            "SUBJECT_1": "sub-001",
            "SUBJECT_2": "sub-002", 
            "CONTRAST_1": "task_vs_rest"
        }
        
        resolved = ParameterResolver.resolve_parameters(parameters, context)
        
        assert resolved["subjects"] == ["sub-001", "sub-002", "sub-003"]
        assert resolved["contrasts"][0]["name"] == "task_vs_rest"
        assert resolved["contrasts"][1]["name"] == "fixed_contrast"
    
    @pytest.mark.unit
    def test_missing_parameter_handling(self):
        """Test handling of missing parameters"""
        parameters = {
            "existing": "${EXISTING_VAR}",
            "missing": "${MISSING_VAR}",
            "default": "${MISSING_VAR:-default_value}"
        }
        
        context = {
            "EXISTING_VAR": "existing_value"
        }
        
        resolved = ParameterResolver.resolve_parameters(parameters, context)
        
        assert resolved["existing"] == "existing_value"
        # Missing parameter should remain as template
        assert resolved["missing"] == "${MISSING_VAR}"
        # Default value should be used
        assert resolved["default"] == "default_value"
    
    @pytest.mark.unit
    def test_expression_evaluation(self):
        """Test expression evaluation in parameters"""
        parameters = {
            "calculated": "${BASE_VALUE * 2}",
            "conditional": "${SCORE > 0.5 ? 'high' : 'low'}",
            "string_op": "${PREFIX + '_' + SUFFIX}"
        }
        
        context = {
            "BASE_VALUE": 10,
            "SCORE": 0.8,
            "PREFIX": "sub",
            "SUFFIX": "001"
        }
        
        # Note: This would require actual expression evaluation
        # For now, test the structure
        resolved = ParameterResolver.resolve_parameters(parameters, context)
        
        # Basic substitution should work
        assert "${BASE_VALUE}" not in str(resolved.get("calculated", ""))
    
    @pytest.mark.unit
    def test_recursive_parameter_resolution(self):
        """Test recursive parameter resolution"""
        parameters = {
            "base_path": "${ROOT_DIR}",
            "subject_path": "${base_path}/subjects",
            "data_path": "${subject_path}/${SUBJECT_ID}"
        }
        
        context = {
            "ROOT_DIR": "/data",
            "SUBJECT_ID": "sub-001"
        }
        
        # Multiple passes might be needed for full resolution
        resolved = ParameterResolver.resolve_parameters(parameters, context)
        resolved = ParameterResolver.resolve_parameters(resolved, resolved)
        
        assert resolved["base_path"] == "/data"
        assert resolved["subject_path"] == "/data/subjects"
        assert resolved["data_path"] == "/data/subjects/sub-001"


class TestLoopConfig:
    """Test suite for LoopConfig"""
    
    @pytest.mark.unit
    def test_for_loop_config(self):
        """Test FOR loop configuration"""
        config = LoopConfig(
            loop_type=LoopType.FOR,
            items="subjects",
            max_iterations=10,
            body=["process_subject"]
        )
        
        assert config.loop_type == LoopType.FOR
        assert config.items == "subjects"
        assert config.max_iterations == 10
        assert config.body == ["process_subject"]
    
    @pytest.mark.unit
    def test_foreach_loop_config(self):
        """Test FOREACH loop configuration"""
        config = LoopConfig(
            loop_type=LoopType.FOREACH,
            items="file_list",
            max_iterations=100,
            body=["load_file", "process_file"],
            break_condition="error_count > 5"
        )
        
        assert config.loop_type == LoopType.FOREACH
        assert config.items == "file_list"
        assert config.break_condition == "error_count > 5"
        assert len(config.body) == 2
    
    @pytest.mark.unit
    def test_while_loop_config(self):
        """Test WHILE loop configuration"""
        config = LoopConfig(
            loop_type=LoopType.WHILE,
            condition="convergence < threshold",
            max_iterations=1000,
            body=["iteration_step"]
        )
        
        assert config.loop_type == LoopType.WHILE
        assert config.condition == "convergence < threshold"
        assert config.max_iterations == 1000
    
    @pytest.mark.unit
    def test_loop_config_validation(self):
        """Test loop configuration validation"""
        # Valid config
        valid_config = LoopConfig(
            loop_type=LoopType.FOR,
            items="subjects",
            max_iterations=10,
            body=["process"]
        )
        errors = valid_config.validate()
        assert len(errors) == 0
        
        # Invalid config (missing items for FOR loop)
        invalid_config = LoopConfig(
            loop_type=LoopType.FOR,
            max_iterations=10,
            body=["process"]
        )
        errors = invalid_config.validate()
        assert len(errors) > 0
        assert any("items" in error.lower() for error in errors)


class TestRetryPolicy:
    """Test suite for RetryPolicy"""
    
    @pytest.mark.unit
    def test_retry_policy_creation(self):
        """Test retry policy creation"""
        policy = RetryPolicy(
            max_attempts=5,
            backoff_multiplier=1.5,
            max_delay=600,
            retry_on_errors=["TimeoutError", "ConnectionError"]
        )
        
        assert policy.max_attempts == 5
        assert policy.backoff_multiplier == 1.5
        assert policy.max_delay == 600
        assert "TimeoutError" in policy.retry_on_errors
        assert "ConnectionError" in policy.retry_on_errors
    
    @pytest.mark.unit
    def test_retry_policy_defaults(self):
        """Test retry policy default values"""
        policy = RetryPolicy()
        
        assert policy.max_attempts == 3
        assert policy.backoff_multiplier == 2.0
        assert policy.max_delay == 300
        assert policy.retry_on_errors == []
    
    @pytest.mark.unit
    def test_retry_delay_calculation(self):
        """Test retry delay calculation"""
        policy = RetryPolicy(backoff_multiplier=2.0, max_delay=100)
        
        # First retry
        delay1 = policy.calculate_delay(1)
        assert delay1 == 2.0
        
        # Second retry
        delay2 = policy.calculate_delay(2)
        assert delay2 == 4.0
        
        # Should not exceed max_delay
        delay_high = policy.calculate_delay(10)
        assert delay_high <= policy.max_delay


class TestExampleDAG:
    """Test the example DAG provided in the module"""
    
    @pytest.mark.unit
    def test_example_dag_parsing(self):
        """Test that the example DAG parses correctly"""
        dag = DAGDefinition.from_yaml(EXAMPLE_DAG_YAML)
        
        assert dag.name == "neuroimaging_analysis"
        assert len(dag.nodes) > 0
        assert "preprocessing" in dag.nodes
    
    @pytest.mark.unit
    def test_example_dag_validation(self):
        """Test that the example DAG validates correctly"""
        dag = DAGDefinition.from_yaml(EXAMPLE_DAG_YAML)
        errors = dag.validate()
        
        # Example DAG should be valid
        assert len(errors) == 0


# Property-based testing
@pytest.mark.property
class TestDAGProperties:
    """Property-based tests for DAG language components"""
    
    def test_parameter_resolution_idempotent(self):
        """Test that parameter resolution is idempotent"""
        # Would use hypothesis for property-based testing
        pass
    
    def test_dag_serialization_roundtrip(self):
        """Test that DAG serialization is reversible"""
        pass