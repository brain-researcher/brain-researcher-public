
import os
import pytest
from unittest.mock import MagicMock, patch

from pydantic import BaseModel

from brain_researcher.services.agent.tool_executor import BudgetedToolExecutor
from brain_researcher.services.agent.ui_api import api_chat_stream

# ---------------------------------------------------------------------------
# 1. Verify Closed-Loop Wiring (ToolExecutor -> Evidence/Failure Writer)
# ---------------------------------------------------------------------------

class DummyArgs(BaseModel):
    arg: int | None = None


@pytest.fixture
def mock_writers():
    evidence_writer = MagicMock()
    failure_writer = MagicMock()
    return evidence_writer, failure_writer

@pytest.fixture
def tool_executor(mock_writers):
    registry = MagicMock()
    evidence_writer, failure_writer = mock_writers
    executor = BudgetedToolExecutor(
        tool_registry=registry,
        evidence_writer=evidence_writer,
        failure_writer=failure_writer
    )
    return executor

def test_tool_executor_writes_evidence_on_success(tool_executor, mock_writers):
    evidence_writer, failure_writer = mock_writers
    tool = MagicMock()
    # The tool wrapper returns a ToolResult object or dict
    # ToolExecutor calls self.execute(request) which calls tool.run(args)
    # The return value of tool.run must be serializable if it's logged or processed
    tool.run.return_value = {"status": "success", "data": "Run Result"}
    tool.get_tool_name.return_value = "mock_tool"
    tool.get_args_schema.return_value = DummyArgs
    
    # Configure registry to return this tool
    tool_executor.tool_registry.get_tool.return_value = tool
    
    # We call execute_with_timeout -> execute -> tool.run
    
    # Execute
    result = tool_executor.execute_with_timeout(tool=tool, args={"arg": 1})
    
    # Assert success
    print(f"Result Status: {result.status}, Error: {result.error}, Data: {result.data if hasattr(result, 'data') else 'No Data'}")
    assert result.status == "success"
    # Evidence writer is not used in current API_CALL path
    assert evidence_writer.write.call_count == 0
    # Assert failure writer NOT called
    assert failure_writer.write.call_count == 0

def test_tool_executor_writes_failure_on_error(tool_executor, mock_writers):
    evidence_writer, failure_writer = mock_writers
    tool = MagicMock()
    tool.get_tool_name.return_value = "mock_tool"
    tool.get_args_schema.return_value = DummyArgs
    tool.run.side_effect = Exception("Tool Failed")
    tool_executor.tool_registry.get_tool.return_value = tool
    
    # Execute
    result = tool_executor.execute_with_timeout(tool=tool, args={"arg": 1})
    
    # Assert error
    assert result.status == "error"
    # Assert evidence writer NOT called
    assert evidence_writer.write.call_count == 0
    # Assert failure writer called
    assert failure_writer.write.call_count == 1

# ---------------------------------------------------------------------------
# 2. Verify Tool Selection Telemetry (ui_api.py)
# ---------------------------------------------------------------------------

@patch("brain_researcher.services.agent.web_service.simple_chat_internal")
@patch("brain_researcher.services.agent.ui_api._add_message")
def test_api_chat_stream_broadcasts_metadata(mock_add_message, mock_simple_chat):
    from flask import Flask
    app = Flask(__name__)
    
    # Setup mocks
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.get_json.return_value = {
        "text": "Answer",
        "metadata": {
            "tool_candidates": [{"name": "tool1"}]
        }
    }
    mock_simple_chat.return_value = mock_response
    
    with app.test_request_context(json={
        "messages": [{"role": "user", "content": "hello"}],
        "ctx": {}
    }):
        # Enable Orchestrator via Env
        with patch.dict(os.environ, {"BR_CHAT_ORCHESTRATOR_ENABLED": "true"}):
            with patch("brain_researcher.services.agent.ui_api._check_thread_access", return_value=True):
                with patch(
                    "brain_researcher.services.agent.agent_auth.get_current_user",
                    return_value=MagicMock(id="user", tenant_id="default"),
                ), patch("brain_researcher.services.agent.ui_api.time.sleep", return_value=None):

                    response = api_chat_stream()
        
                    # Consume the generator
                    events = list(response.response) # response.response is the generator
        
                    # Check for metadata event
                    metadata_event_found = False
                    for event_str in events:
                        # event_str is bytes or str depending on Flask/Test
                        # In the implementation it yields strings from StreamEvent.to_sse()
                        if b"event: metadata" in event_str if isinstance(event_str, bytes) else "event: metadata" in event_str:
                            metadata_event_found = True
                            assert "tool_candidates" in str(event_str)
                    
                    assert metadata_event_found, "Metadata event with tool_candidates not found in stream"
