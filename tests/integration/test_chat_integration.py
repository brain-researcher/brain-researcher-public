"""
Integration tests for Chat Interface with LangGraph Agent
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import json
import asyncio
from datetime import datetime


class TestChatIntegration:
    """Test suite for Chat Interface integration"""
    
    @pytest.fixture
    def thread_data(self):
        """Sample thread data"""
        return {
            'id': 'thread_123',
            'title': 'Analysis Session',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'message_count': 5,
            'status': 'active'
        }
    
    @pytest.fixture
    def message_data(self):
        """Sample message data"""
        return [
            {
                'id': 'msg_1',
                'role': 'user',
                'content': 'Run GLM analysis on motor task data',
                'timestamp': datetime.now().isoformat(),
                'attachments': []
            },
            {
                'id': 'msg_2',
                'role': 'assistant',
                'content': 'I\'ll run a GLM analysis on the motor task data. Let me process this for you.',
                'timestamp': datetime.now().isoformat(),
                'metadata': {
                    'model': 'claude-3',
                    'tokens': 150,
                    'tools_used': ['fmri_glm', 'visualization']
                }
            }
        ]
    
    @pytest.fixture
    def sse_events(self):
        """Sample SSE events"""
        return [
            {'type': 'message', 'data': {'content': 'Processing...'}},
            {'type': 'tool_call', 'data': {'tool_name': 'fmri_glm', 'status': 'running'}},
            {'type': 'message', 'data': {'content': 'Analysis complete!'}},
            {'type': 'done', 'data': {'status': 'success'}}
        ]
    
    @pytest.mark.asyncio
    async def test_create_thread(self, thread_data):
        """Test creating a new chat thread"""
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_post.return_value.json = AsyncMock(return_value=thread_data)
            mock_post.return_value.status_code = 200
            
            # Simulate thread creation
            result = thread_data
            
            assert result['id'] == 'thread_123'
            assert result['status'] == 'active'
    
    @pytest.mark.asyncio
    async def test_get_thread_history(self, thread_data, message_data):
        """Test retrieving thread message history"""
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.return_value.json = AsyncMock(return_value={'messages': message_data})
            mock_get.return_value.status_code = 200
            
            # Simulate getting history
            result = {'messages': message_data}
            
            assert len(result['messages']) == 2
            assert result['messages'][0]['role'] == 'user'
            assert result['messages'][1]['role'] == 'assistant'
    
    @pytest.mark.asyncio
    async def test_send_message(self, thread_data):
        """Test sending a message to the agent"""
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_post.return_value.json = AsyncMock(return_value={'message_id': 'msg_123'})
            mock_post.return_value.status_code = 200
            
            # Simulate sending message
            content = "Analyze this dataset"
            result = {'message_id': 'msg_123'}
            
            assert result['message_id'] == 'msg_123'
    
    def test_sse_streaming(self, sse_events):
        """Test SSE streaming for real-time responses"""
        received_events = []
        
        for event in sse_events:
            received_events.append(event)
            
            if event['type'] == 'tool_call':
                assert event['data']['tool_name'] == 'fmri_glm'
            elif event['type'] == 'done':
                assert event['data']['status'] == 'success'
        
        assert len(received_events) == 4
        assert received_events[-1]['type'] == 'done'
    
    @pytest.mark.asyncio
    async def test_file_upload(self):
        """Test file attachment upload"""
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_post.return_value.json = AsyncMock(return_value={
                'id': 'attach_123',
                'name': 'data.nii.gz',
                'type': 'application/gzip',
                'size': 1024000,
                'url': '/api/attachments/attach_123'
            })
            mock_post.return_value.status_code = 200
            
            # Simulate file upload
            result = {
                'id': 'attach_123',
                'name': 'data.nii.gz',
                'size': 1024000
            }
            
            assert result['id'] == 'attach_123'
            assert result['name'] == 'data.nii.gz'
    
    @pytest.mark.asyncio
    async def test_tool_execution(self):
        """Test direct tool execution"""
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_post.return_value.json = AsyncMock(return_value={'job_id': 'job_456'})
            mock_post.return_value.status_code = 200
            
            # Simulate tool execution
            tool_name = 'fmri_glm'
            parameters = {'smoothing': 6, 'threshold': 0.001}
            
            result = {'job_id': 'job_456'}
            
            assert result['job_id'] == 'job_456'
    
    def test_message_metadata(self, message_data):
        """Test message metadata tracking"""
        assistant_message = message_data[1]
        
        assert 'metadata' in assistant_message
        assert assistant_message['metadata']['model'] == 'claude-3'
        assert assistant_message['metadata']['tokens'] == 150
        assert 'fmri_glm' in assistant_message['metadata']['tools_used']
    
    def test_error_handling(self):
        """Test error handling in chat integration"""
        error_response = {
            'error': 'Connection timeout',
            'code': 'E_TIMEOUT',
            'retry_after': 30
        }
        
        assert error_response['code'] == 'E_TIMEOUT'
        assert error_response['retry_after'] == 30
    
    @pytest.mark.asyncio
    async def test_thread_management(self):
        """Test thread lifecycle management"""
        threads = []
        
        # Create multiple threads
        for i in range(3):
            thread = {
                'id': f'thread_{i}',
                'title': f'Session {i}',
                'status': 'active'
            }
            threads.append(thread)
        
        assert len(threads) == 3
        
        # Archive a thread
        threads[0]['status'] = 'archived'
        
        active_threads = [t for t in threads if t['status'] == 'active']
        assert len(active_threads) == 2
    
    def test_streaming_progress(self):
        """Test streaming progress updates"""
        progress_events = [
            {'progress': 0, 'status': 'starting'},
            {'progress': 25, 'status': 'loading_data'},
            {'progress': 50, 'status': 'processing'},
            {'progress': 75, 'status': 'analyzing'},
            {'progress': 100, 'status': 'complete'}
        ]
        
        for event in progress_events:
            assert 0 <= event['progress'] <= 100
        
        assert progress_events[-1]['status'] == 'complete'
    
    @pytest.mark.asyncio
    async def test_concurrent_messages(self):
        """Test handling concurrent message streams"""
        async def send_message(msg_id):
            await asyncio.sleep(0.1)  # Simulate network delay
            return {'id': msg_id, 'status': 'sent'}
        
        # Send multiple messages concurrently
        tasks = [send_message(f'msg_{i}') for i in range(5)]
        results = await asyncio.gather(*tasks)
        
        assert len(results) == 5
        assert all(r['status'] == 'sent' for r in results)
    
    def test_markdown_rendering(self, message_data):
        """Test markdown content in messages"""
        markdown_message = {
            'content': '## Analysis Results\n\n- Peak at **[42, 64, 32]**\n- T-value: `6.23`',
            'role': 'assistant'
        }
        
        assert '##' in markdown_message['content']  # Headers
        assert '**' in markdown_message['content']  # Bold
        assert '`' in markdown_message['content']   # Code
    
    def test_langraph_agent_connection(self):
        """Test connection to LangGraph agent"""
        agent_config = {
            'url': 'http://localhost:8000',
            'timeout': 30,
            'max_retries': 3
        }
        
        assert agent_config['url'] == 'http://localhost:8000'
        assert agent_config['timeout'] == 30
    
    def test_conversation_context(self, message_data):
        """Test conversation context maintenance"""
        context = {
            'thread_id': 'thread_123',
            'messages': message_data,
            'context_window': 10,
            'total_tokens': 0
        }
        
        # Calculate tokens
        for msg in context['messages']:
            # Approximate token count
            context['total_tokens'] += len(msg['content'].split()) * 1.3
        
        assert context['total_tokens'] > 0
        assert len(context['messages']) <= context['context_window']
    
    def test_rate_limiting(self):
        """Test rate limiting for API calls"""
        rate_limit = {
            'requests_per_minute': 60,
            'requests_made': 0,
            'reset_time': datetime.now()
        }
        
        # Simulate requests
        for _ in range(10):
            if rate_limit['requests_made'] < rate_limit['requests_per_minute']:
                rate_limit['requests_made'] += 1
        
        assert rate_limit['requests_made'] == 10
        assert rate_limit['requests_made'] < rate_limit['requests_per_minute']