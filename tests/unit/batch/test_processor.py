"""Unit tests for batch processing system."""

import pytest
import asyncio
from datetime import datetime
import time
from unittest.mock import Mock, AsyncMock, patch
from brain_researcher.core.ingestion.batch.processor import (
    BatchJob,
    JobStatus,
    JobPriority,
    JobQueue,
    BatchProcessor,
    ParallelProcessor,
    example_ingestion_handler
)


class TestBatchJob:
    """Test suite for BatchJob."""
    
    def test_job_creation(self):
        """Test creating a batch job."""
        job = BatchJob(
            name="Test Job",
            task_type="ingestion",
            input_data={'file': 'test.csv'},
            priority=JobPriority.HIGH
        )
        
        assert job.name == "Test Job"
        assert job.task_type == "ingestion"
        assert job.priority == JobPriority.HIGH
        assert job.status == JobStatus.PENDING
        assert job.job_id is not None
        assert job.retry_count == 0
        assert job.max_retries == 3
    
    def test_job_comparison(self):
        """Test job priority comparison."""
        high_priority = BatchJob(priority=JobPriority.HIGH)
        low_priority = BatchJob(priority=JobPriority.LOW)
        
        assert high_priority < low_priority  # Lower value = higher priority
    
    def test_job_with_dependencies(self):
        """Test job with dependencies."""
        job = BatchJob(
            name="Dependent Job",
            dependencies=["job1", "job2"]
        )
        
        assert len(job.dependencies) == 2
        assert "job1" in job.dependencies


class TestJobQueue:
    """Test suite for JobQueue."""
    
    @pytest.fixture
    def queue(self):
        """Create job queue."""
        return JobQueue()
    
    def test_submit_job(self, queue):
        """Test submitting job to queue."""
        job = BatchJob(name="Test", task_type="test")
        job_id = queue.submit(job)
        
        assert job_id == job.job_id
        assert job.status == JobStatus.QUEUED
        assert job_id in queue.jobs
    
    def test_get_next_job(self, queue):
        """Test getting next job from queue."""
        # Submit multiple jobs with different priorities
        high = BatchJob(name="High", priority=JobPriority.HIGH)
        normal = BatchJob(name="Normal", priority=JobPriority.NORMAL)
        low = BatchJob(name="Low", priority=JobPriority.LOW)
        
        queue.submit(low)
        queue.submit(high)
        queue.submit(normal)
        
        # Should get high priority first
        next_job = queue.get_next()
        assert next_job.name == "High"
        
        next_job = queue.get_next()
        assert next_job.name == "Normal"
        
        next_job = queue.get_next()
        assert next_job.name == "Low"
    
    def test_get_status(self, queue):
        """Test getting job status."""
        job = BatchJob(name="Test")
        job_id = queue.submit(job)
        
        status = queue.get_status(job_id)
        assert status == JobStatus.QUEUED
        
        # Update job
        job.status = JobStatus.RUNNING
        queue.update_job(job)
        
        status = queue.get_status(job_id)
        assert status == JobStatus.RUNNING
    
    def test_empty_queue(self, queue):
        """Test getting from empty queue."""
        next_job = queue.get_next()
        assert next_job is None


class TestBatchProcessor:
    """Test suite for BatchProcessor."""
    
    @pytest.fixture
    def processor(self):
        """Create batch processor."""
        return BatchProcessor(max_workers=2, use_processes=False)
    
    def test_register_handler(self, processor):
        """Test registering task handler."""
        def dummy_handler(data, progress):
            return {'status': 'ok'}
        
        processor.register_handler('test_task', dummy_handler)
        assert 'test_task' in processor.task_handlers
        assert processor.task_handlers['test_task'] == dummy_handler
    
    def test_submit_job(self, processor):
        """Test submitting job to processor."""
        job_id = processor.submit_job(
            name="Test Job",
            task_type="ingestion",
            input_data={'items': 10},
            priority=JobPriority.NORMAL
        )
        
        assert job_id is not None
        assert job_id in processor.job_queue.jobs
    
    def test_get_job_status(self, processor):
        """Test getting job status."""
        job_id = processor.submit_job(
            name="Test Job",
            task_type="test",
            input_data={}
        )
        
        status = processor.get_job_status(job_id)
        
        assert status is not None
        assert status['job_id'] == job_id
        assert status['name'] == "Test Job"
        assert status['status'] == JobStatus.QUEUED.value
        assert status['progress'] == 0.0
    
    def test_cancel_job(self, processor):
        """Test cancelling a job."""
        job_id = processor.submit_job(
            name="Test Job",
            task_type="test",
            input_data={}
        )
        
        # Cancel job
        success = processor.cancel_job(job_id)
        assert success is True
        
        # Check status
        job = processor.job_queue.jobs[job_id]
        assert job.status == JobStatus.CANCELLED
        
        # Can't cancel running job
        job.status = JobStatus.RUNNING
        success = processor.cancel_job(job_id)
        assert success is False
    
    def test_get_statistics(self, processor):
        """Test getting processor statistics."""
        # Submit some jobs
        for i in range(5):
            processor.submit_job(f"Job {i}", "test", {})
        
        stats = processor.get_statistics()
        
        assert stats['total'] == 5
        assert stats['queued'] == 5
        assert stats['running'] == 0
        assert stats['completed'] == 0
        assert stats['workers'] == 2
    
    @pytest.mark.asyncio
    async def test_execute_job(self, processor):
        """Test job execution."""
        # Register handler
        def test_handler(data, progress):
            progress(50, "Half done")
            progress(100, "Complete")
            return {'result': 'success'}
        
        processor.register_handler('test', test_handler)
        
        # Create and execute job
        job = BatchJob(
            name="Test",
            task_type="test",
            input_data={}
        )
        
        await processor._execute_job(job)
        
        assert job.status == JobStatus.COMPLETED
        assert job.progress == 100.0
        assert job.started_at is not None
        assert job.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_execute_job_with_error(self, processor):
        """Test job execution with error."""
        # Register failing handler
        def failing_handler(data, progress):
            raise ValueError("Test error")
        
        processor.register_handler('failing', failing_handler)
        
        # Create job
        job = BatchJob(
            name="Failing",
            task_type="failing",
            input_data={},
            max_retries=1
        )
        
        await processor._execute_job(job)
        
        assert job.status == JobStatus.RETRYING
        assert job.retry_count == 1
        assert "Test error" in job.error_message
    
    @pytest.mark.asyncio
    async def test_dependency_checking(self, processor):
        """Test dependency checking."""
        # Create jobs with dependencies
        job1 = BatchJob(job_id="job1", name="Job 1")
        job2 = BatchJob(job_id="job2", name="Job 2", dependencies=["job1"])
        
        processor.job_queue.jobs["job1"] = job1
        processor.job_queue.jobs["job2"] = job2
        
        # Job2 dependencies not satisfied
        job1.status = JobStatus.RUNNING
        assert processor._check_dependencies(job2) is False
        
        # Dependencies satisfied
        job1.status = JobStatus.COMPLETED
        assert processor._check_dependencies(job2) is True


class TestParallelProcessor:
    """Test suite for ParallelProcessor."""
    
    def test_process_files(self, tmp_path):
        """Test parallel file processing."""
        # Create test files
        files = []
        for i in range(10):
            file = tmp_path / f"test_{i}.txt"
            file.write_text(f"Content {i}")
            files.append(file)
        
        # Process files
        def process_file(path):
            return len(path.read_text())
        
        results = ParallelProcessor.process_files(
            files,
            process_file,
            max_workers=2,
            chunk_size=3
        )
        
        assert len(results) == 10
        assert all(r > 0 for r in results if r is not None)
    
    def test_process_chunk(self, tmp_path):
        """Test chunk processing."""
        # Create test files
        files = []
        for i in range(3):
            file = tmp_path / f"test_{i}.txt"
            file.write_text(f"Data {i}")
            files.append(file)
        
        def processor(path):
            return path.name
        
        results = ParallelProcessor._process_chunk(files, processor)
        
        assert len(results) == 3
        assert "test_0.txt" in results
        assert "test_1.txt" in results
        assert "test_2.txt" in results


class TestExampleHandler:
    """Test suite for example handler."""
    
    def test_example_ingestion_handler(self):
        """Test the example ingestion handler."""
        progress_calls = []
        
        def progress_callback(progress, message):
            progress_calls.append((progress, message))
        
        input_data = {'total_items': 5}
        result = example_ingestion_handler(input_data, progress_callback)
        
        assert result['processed'] == 5
        assert result['status'] == 'success'
        
        # Check progress calls
        assert len(progress_calls) == 6  # Start + 5 items
        assert progress_calls[0][0] == 0  # Start at 0%
        assert progress_calls[-1][0] == 100  # End at 100%