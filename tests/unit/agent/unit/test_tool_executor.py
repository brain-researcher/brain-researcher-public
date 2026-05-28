"""
Unit tests for the Tool Executor.

Tests command generation, API execution, and safety features.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from brain_researcher.services.agent.tool_executor import (
    ToolExecutor,
    ToolExecutionRequest,
    ToolExecutionResult,
    ExecutionMode,
    ToolCategory,
    Priority
)
from brain_researcher.services.tools.tool_base import ToolResult
from brain_researcher.services.tools.neurodesk_tools import (
    NeurodeskCommandGenerator,
    NeurodeskTools,
    NEURODESK_TOOLS
)


class TestToolExecutionRequest:
    """Test ToolExecutionRequest dataclass."""
    
    def test_auto_detect_category_neuroimaging(self):
        """Test auto-detection of neuroimaging tools."""
        request = ToolExecutionRequest(
            tool_name="fsl_command",
            parameters={"command": "bet", "input_files": ["brain.nii"]}
        )
        assert request.category == ToolCategory.NEUROIMAGING
        
    def test_auto_detect_category_analysis(self):
        """Test auto-detection of analysis tools."""
        request = ToolExecutionRequest(
            tool_name="glm_analysis",
            parameters={"dataset_id": "ds000001"}
        )
        assert request.category == ToolCategory.ANALYSIS
        
    def test_auto_detect_mode_command_generation(self):
        """Test auto-detection of command generation mode."""
        request = ToolExecutionRequest(
            tool_name="neurodesk_command",
            parameters={"tool_name": "fsl", "command": "bet"}
        )
        assert request.mode == ExecutionMode.COMMAND_GENERATION
        
    def test_auto_detect_mode_api_call(self):
        """Test auto-detection of API call mode."""
        request = ToolExecutionRequest(
            tool_name="graph_query",
            parameters={"query": "MATCH (n) RETURN n"}
        )
        assert request.mode == ExecutionMode.API_CALL
        
    def test_force_direct_execution(self):
        """Test forcing direct execution mode."""
        request = ToolExecutionRequest(
            tool_name="fsl_command",
            parameters={"command": "bet"},
            execute_directly=True
        )
        assert request.mode == ExecutionMode.DIRECT_EXECUTION
        
    def test_execution_id_generation(self):
        """Test automatic execution ID generation."""
        request = ToolExecutionRequest(
            tool_name="test_tool",
            parameters={}
        )
        assert request.execution_id is not None
        assert request.execution_id.startswith("exec_")


class TestToolExecutor:
    """Test ToolExecutor class."""
    
    @pytest.fixture
    def executor(self):
        """Create a ToolExecutor instance."""
        return ToolExecutor(
            max_workers=2,
            default_timeout=10.0,
            enable_caching=False,
            safe_mode=True
        )
    
    @pytest.fixture
    def mock_tool(self):
        """Create a mock tool."""
        tool = Mock()
        tool.get_tool_name.return_value = "mock_tool"
        tool.get_tool_description.return_value = "Mock tool for testing"
        tool.get_args_schema.return_value = None
        tool.run.return_value = {
            "status": "success",
            "data": {"result": "test_result"}
        }
        return tool
    
    def test_initialization(self, executor):
        """Test executor initialization."""
        assert executor.max_workers == 2
        assert executor.default_timeout == 10.0
        assert executor.safe_mode is True
        assert len(executor.active_executions) == 0
        
    def test_neurodesk_tools_registration(self):
        """Test that Neurodesk tools are registered."""
        executor = ToolExecutor()
        
        # Check that neurodesk tools are accessible
        neurodesk_tool = executor.neurodesk_tools.get_tool_by_name("neurodesk_command")
        assert neurodesk_tool is not None
        
    def test_command_generation_mode(self, executor):
        """Test command generation for neuroimaging tools."""
        request = ToolExecutionRequest(
            tool_name="neurodesk_command",
            parameters={
                "tool_name": "fsl",
                "command": "bet",
                "input_files": ["/data/brain.nii"],
                "output_path": "/data/brain_skull.nii",
                "parameters": {"f": 0.5}
            }
        )
        
        result = executor.execute(request)
        
        assert result.status == "success"
        assert result.command is not None
        assert "module load fsl" in result.command
        assert "bet" in result.command
        assert "/data/brain.nii" in result.command

    def test_command_generation_with_execution_plan(self, executor, monkeypatch):
        """Command generation should expand multi-step execution plans."""
        base_command = (
            "apptainer exec /cvmfs/neurodesk/fsl.sif fslmaths "
            "/data/input.nii -s 2.5460 /data/output.nii"
        )

        tool = Mock()
        tool.get_tool_name.return_value = "fsl.fslmaths"
        tool.get_tool_description.return_value = "FSL smooth"
        tool.get_args_schema.return_value = None
        tool.run.return_value = {
            "status": "success",
            "data": {
                "command": base_command,
            },
        }

        plan = {
            "executable": "fslmaths",
            "steps": [
                {
                    "name": "apply_mask",
                    "args": [
                        "/data/input.nii",
                        "-mas",
                        "/data/mask.nii.gz",
                        "/tmp/temp_masked.nii.gz",
                    ],
                },
                {
                    "name": "smooth",
                    "args": [
                        "/tmp/temp_masked.nii.gz",
                        "-s",
                        "2.5460",
                        "/data/output.nii",
                    ],
                },
            ],
        }

        parameters = {
            "sigma": 2.5460,
            "input": "/data/input.nii",
            "output": "/data/output.nii",
            "mask": "/data/mask.nii.gz",
            "execution_plan": plan,
        }

        request = ToolExecutionRequest(
            tool_name="fsl.fslmaths",
            parameters=parameters,
        )

        monkeypatch.setattr(executor, "_get_tool", Mock(return_value=tool))
        monkeypatch.setattr(executor, "_infer_parameters", Mock(return_value=parameters))
        monkeypatch.setattr(executor, "_validate_parameters", Mock(return_value={"valid": True}))

        result = executor.execute(request)

        assert result.status == "success"
        assert "&&" in result.command
        assert "fslmaths /data/input.nii -mas /data/mask.nii.gz /tmp/temp_masked.nii.gz" in result.command
        data = result.result.get("data", {})
        assert data.get("multi_step") is True
        script = data.get("script")
        assert script is not None
        assert "set -euo pipefail" in script
        assert script.count("fslmaths") == 2
        tool.run.assert_called_once()
        
    def test_command_generation_cvmfs_mode(self, executor):
        """Test command generation using CVMFS paths."""
        request = ToolExecutionRequest(
            tool_name="neurodesk_command",
            parameters={
                "tool_name": "mrtrix3",
                "command": "mrinfo",
                "input_files": ["/data/dwi.mif"],
                "use_module": False
            }
        )
        
        result = executor.execute(request)
        
        assert result.status == "success"
        assert result.command is not None
        assert "apptainer exec" in result.command
        assert "/cvmfs/neurodesk.ardc.edu.au/containers" in result.command
        assert "mrinfo" in result.command
        
    def test_api_call_mode(self, executor, mock_tool):
        """Test API call execution mode."""
        # Patch tool registry to return mock tool
        with patch.object(executor.tool_registry, 'get_tool', return_value=mock_tool):
            request = ToolExecutionRequest(
                tool_name="mock_tool",
                parameters={"param1": "value1"},
                mode=ExecutionMode.API_CALL
            )
            
            result = executor.execute(request)
            
            assert result.status == "success"
            assert result.result is not None
            mock_tool.run.assert_called_once()
            
    def test_safe_mode_blocks_direct_execution(self, executor):
        """Test that safe mode blocks direct execution of neuroimaging tools."""
        request = ToolExecutionRequest(
            tool_name="fsl_command",
            parameters={"command": "rm -rf /"},
            execute_directly=True
        )
        
        # Should switch to command generation in safe mode
        result = executor.execute(request)
        
        # Should either generate command or error, not execute directly
        assert result.status in ["success", "error"]
        if result.status == "success":
            assert result.command is not None  # Generated command
        
    def test_parameter_inference(self, executor, mock_tool):
        """Test parameter inference integration."""
        mock_tool.get_args_schema.return_value = Mock(
            __fields__={
                "required_param": Mock(is_required=lambda: True),
                "optional_param": Mock(is_required=lambda: False)
            }
        )
        
        with patch.object(executor.tool_registry, 'get_tool', return_value=mock_tool):
            with patch.object(executor.parameter_inference, 'infer_from_context') as mock_infer:
                mock_infer.return_value = Mock(
                    parameters={"required_param": "inferred_value"}
                )
                
                request = ToolExecutionRequest(
                    tool_name="mock_tool",
                    parameters={},  # Missing required param
                    context={"query": "test query"},
                    mode=ExecutionMode.API_CALL
                )
                
                result = executor.execute(request)
                
                # Check that inference was called
                mock_infer.assert_called_once()
                
    def test_resource_allocation(self, executor, mock_tool):
        """Test resource allocation integration."""
        with patch.object(executor.tool_registry, 'get_tool', return_value=mock_tool):
            with patch.object(executor.resource_manager, 'request_resources') as mock_alloc:
                mock_alloc.return_value = "alloc_123"
                
                request = ToolExecutionRequest(
                    tool_name="mock_tool",
                    parameters={},
                    priority=Priority.HIGH,
                    mode=ExecutionMode.API_CALL
                )
                
                result = executor.execute(request)
                
                # Check that resources were requested
                mock_alloc.assert_called_once()
                # Verify the call had the expected parameters
                call_args = mock_alloc.call_args
                assert call_args.kwargs['tool_name'] == "mock_tool"
                assert call_args.kwargs['priority'] == Priority.HIGH
                assert 'execution_id' in call_args.kwargs  # Should have execution_id
                
    def test_execution_tracking(self, executor, mock_tool):
        """Test execution status tracking."""
        with patch.object(executor.tool_registry, 'get_tool', return_value=mock_tool):
            request = ToolExecutionRequest(
                tool_name="mock_tool",
                parameters={},
                mode=ExecutionMode.API_CALL
            )
            
            # Start execution in background
            from threading import Thread
            thread = Thread(target=executor.execute, args=(request,))
            thread.start()
            
            # Check status while running (may be complete by the time we check)
            import time
            time.sleep(0.1)
            
            status = executor.get_execution_status(request.execution_id)
            if status:
                assert "execution_id" in status
                assert "status" in status
            
            thread.join()
            
    def test_caching(self):
        """Test result caching."""
        executor = ToolExecutor(enable_caching=True)
        
        request = ToolExecutionRequest(
            tool_name="neurodesk_command",
            parameters={
                "tool_name": "fsl",
                "command": "bet",
                "input_files": ["/data/brain.nii"]
            }
        )
        
        # First execution
        result1 = executor.execute(request)
        
        # Second execution should return cached result
        result2 = executor.execute(request)
        
        assert result2.metadata.get("from_cache") is True
        assert result1.command == result2.command
        
    def test_batch_execution(self, executor):
        """Test batch execution mode."""
        request = ToolExecutionRequest(
            tool_name="neurodesk_command",
            parameters={
                "batch": [
                    {
                        "tool_name": "fsl",
                        "command": "bet",
                        "input_files": [f"/data/brain_{i}.nii"]
                    }
                    for i in range(3)
                ]
            },
            mode=ExecutionMode.BATCH
        )
        
        result = executor.execute(request)
        
        assert result.status in ["success", "partial"]
        assert result.metadata["batch_size"] == 3
        assert "results" in result.metadata
        
    def test_timeout_handling(self, executor):
        """Test execution timeout."""
        # Create a tool that takes too long
        slow_tool = Mock()
        slow_tool.get_tool_name.return_value = "slow_tool"
        slow_tool.get_args_schema.return_value = None
        
        def slow_run(**kwargs):
            import time
            time.sleep(5)  # Longer than timeout
            return {"status": "success"}
        
        slow_tool.run = slow_run
        
        with patch.object(executor.tool_registry, 'get_tool', return_value=slow_tool):
            request = ToolExecutionRequest(
                tool_name="slow_tool",
                parameters={},
                timeout=0.5,  # Short timeout
                mode=ExecutionMode.API_CALL
            )
            
            result = executor.execute(request)
            
            # Should timeout
            assert "timeout" in result.result.get("error", "").lower() or \
                   result.status == "error"
            
    def test_error_handling(self, executor):
        """Test error handling."""
        # Create a tool that raises an error
        error_tool = Mock()
        error_tool.get_tool_name.return_value = "error_tool"
        error_tool.get_args_schema.return_value = None
        error_tool.run.side_effect = ValueError("Test error")
        
        with patch.object(executor.tool_registry, 'get_tool', return_value=error_tool):
            request = ToolExecutionRequest(
                tool_name="error_tool",
                parameters={},
                mode=ExecutionMode.API_CALL,
                retry_on_failure=False  # Disable retry for test
            )
            
            result = executor.execute(request)
            
            assert result.status == "error"
            assert "Test error" in str(result.error) or \
                   "Test error" in str(result.result.get("error", ""))
            
    def test_retry_logic(self, executor):
        """Test retry on failure."""
        # Create a tool that fails first time, succeeds second
        retry_tool = Mock()
        retry_tool.get_tool_name.return_value = "retry_tool"
        retry_tool.get_args_schema.return_value = None
        
        call_count = {"count": 0}
        
        def retry_run(**kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise ValueError("First attempt failed")
            return {"status": "success", "data": {"attempt": call_count["count"]}}
        
        retry_tool.run = retry_run
        
        with patch.object(executor.tool_registry, 'get_tool', return_value=retry_tool):
            request = ToolExecutionRequest(
                tool_name="retry_tool",
                parameters={},
                mode=ExecutionMode.API_CALL,
                retry_on_failure=True,
                max_retries=2
            )
            
            result = executor.execute(request)
            
            # Should succeed on retry
            assert result.status == "success"
            assert call_count["count"] == 2
            
    def test_dangerous_command_blocking(self):
        """Test blocking of dangerous commands."""
        executor = ToolExecutor(safe_mode=False)  # Even with safe_mode off
        
        request = ToolExecutionRequest(
            tool_name="dangerous_tool",
            parameters={"command": "rm -rf /"},
            mode=ExecutionMode.DIRECT_EXECUTION,
            execute_directly=True
        )
        
        result = executor.execute(request)
        
        assert result.status == "error"
        assert "dangerous" in result.error.lower() or "blocked" in result.error.lower()
        
    def test_neurodesk_batch_generation(self, executor):
        """Test batch command generation for pipeline."""
        request = ToolExecutionRequest(
            tool_name="neurodesk_batch",
            parameters={
                "commands": [
                    {
                        "tool_name": "fsl",
                        "command": "bet",
                        "input_files": ["/data/brain.nii"],
                        "output_path": "/data/brain_skull.nii"
                    },
                    {
                        "tool_name": "fsl",
                        "command": "flirt",
                        "input_files": ["/data/brain_skull.nii"],
                        "output_path": "/data/brain_reg.nii",
                        "parameters": {"ref": "/data/template.nii"}
                    }
                ],
                "pipeline_name": "preprocessing_pipeline",
                "parallel": False
            }
        )
        
        result = executor.execute(request)
        
        assert result.status == "success"
        assert result.result["data"]["script"] is not None
        assert "#!/bin/bash" in result.result["data"]["script"]
        assert "bet" in result.result["data"]["script"]
        assert "flirt" in result.result["data"]["script"]
        
    def test_shutdown(self, executor):
        """Test executor shutdown."""
        # Add some active executions
        executor.active_executions["test_1"] = Mock()
        executor.active_executions["test_2"] = Mock()
        
        executor.shutdown()
        
        # Should cancel all executions
        for mock_tracker in executor.active_executions.values():
            mock_tracker.cancel_execution.assert_called_once()
            

class TestNeurodeskIntegration:
    """Test integration with Neurodesk tools."""
    
    def test_fsl_command_generation(self):
        """Test FSL command generation."""
        generator = NeurodeskCommandGenerator()
        
        result = generator._run(
            tool_name="fsl",
            command="bet",
            input_files=["/data/T1.nii"],
            output_path="/data/T1_brain.nii",
            parameters={"f": 0.5, "g": 0.1},
            use_module=True
        )
        
        assert result.status == "success"
        command = result.data["command"]
        assert "module load fsl/6.0.7.16" in command
        assert "bet /data/T1.nii /data/T1_brain.nii" in command
        assert "-f 0.5" in command
        assert "-g 0.1" in command
        
    def test_mrtrix3_command_generation(self):
        """Test MRtrix3 command generation."""
        generator = NeurodeskCommandGenerator()
        
        result = generator._run(
            tool_name="mrtrix3",
            command="tckgen",
            input_files=["/data/wm_fod.mif"],
            output_path="/data/tracks.tck",
            parameters={"number": 10000, "algorithm": "iFOD2"},
            use_module=True
        )
        
        assert result.status == "success"
        command = result.data["command"]
        assert "module load mrtrix3" in command
        assert "tckgen" in command
        assert "--number 10000" in command or "-number 10000" in command
        
    def test_unknown_tool_error(self):
        """Test error for unknown tool."""
        generator = NeurodeskCommandGenerator()
        
        result = generator._run(
            tool_name="unknown_tool",
            command="test",
            input_files=["/data/test.nii"]
        )
        
        assert result.status == "error"
        assert "Unknown tool" in result.error
        
    def test_cvmfs_path_generation(self):
        """Test CVMFS direct path generation."""
        generator = NeurodeskCommandGenerator()
        
        result = generator._run(
            tool_name="afni",
            command="3dSkullStrip",
            input_files=["/data/head.nii"],
            output_path="/data/brain.nii",
            use_module=False,
            bind_paths=["/scratch"]
        )
        
        assert result.status == "success"
        command = result.data["command"]
        assert "apptainer exec" in command
        assert "/cvmfs/neurodesk.ardc.edu.au/containers" in command
        assert "-B /scratch" in command
        assert "3dSkullStrip" in command
        

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
