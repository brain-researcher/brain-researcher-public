"""Batch processing system for large-scale data ingestion.

Provides parallel processing, job queuing, error recovery, and progress monitoring
for handling large neuroimaging datasets efficiently.
"""

import asyncio
import json
import logging
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable, Union
import traceback
import pickle
from queue import PriorityQueue
import redis
import uuid

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job status states."""
    PENDING = "pending"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"
    CANCELLING = "cancelling"
    SKIPPED = "skipped"
    PAUSED = "paused"
    TIMEOUT = "timeout"


class JobPriority(int, Enum):
    """Job priority levels."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


@dataclass
class BatchJob:
    """Represents a batch processing job."""
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    task_type: str = ""
    input_data: Any = None
    output_path: Optional[str] = None
    priority: JobPriority = JobPriority.NORMAL
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    progress: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)

    def __lt__(self, other):
        """Compare jobs by priority for queue ordering."""
        return self.priority < other.priority


class JobQueue:
    """Priority queue for batch jobs."""

    def __init__(self, redis_url: Optional[str] = None):
        """Initialize job queue.

        Args:
            redis_url: Optional Redis URL for distributed queue
        """
        self.local_queue = PriorityQueue()
        self.jobs: Dict[str, BatchJob] = {}
        self.redis_client = None

        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
                logger.info("Connected to Redis for distributed queue")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}. Using local queue.")

    def submit(self, job: BatchJob) -> str:
        """Submit job to queue.

        Args:
            job: Batch job to submit

        Returns:
            Job ID
        """
        if job.status != JobStatus.RETRYING:
            job.status = JobStatus.QUEUED
        self.jobs[job.job_id] = job

        if self.redis_client:
            # Store in Redis for distributed processing
            self.redis_client.hset(
                f"jobs:{job.job_id}",
                mapping={
                    'data': pickle.dumps(job),
                    'status': job.status.value,
                    'priority': job.priority.value
                }
            )
            self.redis_client.zadd(
                'job_queue',
                {job.job_id: job.priority.value}
            )
        else:
            # Use local priority queue
            self.local_queue.put((job.priority, job.job_id, job))

        logger.info(f"Job {job.job_id} ({job.name}) submitted to queue")
        return job.job_id

    def get_next(self) -> Optional[BatchJob]:
        """Get next job from queue.

        Returns:
            Next job or None if queue is empty
        """
        if self.redis_client:
            # Get from Redis
            result = self.redis_client.zpopmin('job_queue')
            if result:
                job_id = result[0][0].decode() if isinstance(result[0][0], bytes) else result[0][0]
                job_data = self.redis_client.hget(f"jobs:{job_id}", 'data')
                if job_data:
                    return pickle.loads(job_data)
        else:
            # Get from local queue
            if not self.local_queue.empty():
                _, job_id, job = self.local_queue.get()
                return job

        return None

    def get_status(self, job_id: str) -> Optional[JobStatus]:
        """Get job status.

        Args:
            job_id: Job identifier

        Returns:
            Job status or None
        """
        if job_id in self.jobs:
            return self.jobs[job_id].status

        if self.redis_client:
            status = self.redis_client.hget(f"jobs:{job_id}", 'status')
            if status:
                return JobStatus(status.decode() if isinstance(status, bytes) else status)

        return None

    def update_job(self, job: BatchJob):
        """Update job in queue.

        Args:
            job: Updated job
        """
        self.jobs[job.job_id] = job

        if self.redis_client:
            self.redis_client.hset(
                f"jobs:{job.job_id}",
                mapping={
                    'data': pickle.dumps(job),
                    'status': job.status.value,
                    'progress': str(job.progress)
                }
            )


class BatchProcessor:
    """Main batch processing engine."""

    def __init__(self,
                 max_workers: int = None,
                 use_processes: bool = True,
                 redis_url: Optional[str] = None):
        """Initialize batch processor.

        Args:
            max_workers: Maximum parallel workers (default: CPU count)
            use_processes: Use processes vs threads
            redis_url: Optional Redis URL for distributed processing
        """
        self.max_workers = max_workers or mp.cpu_count()
        self.use_processes = use_processes
        self.job_queue = JobQueue(redis_url)
        self.task_handlers: Dict[str, Callable] = {}
        self.running_jobs: Dict[str, BatchJob] = {}
        self.executor = None
        self.monitor_task = None
        self.shutdown_event = asyncio.Event()

    def register_handler(self, task_type: str, handler: Callable):
        """Register task handler.

        Args:
            task_type: Type of task
            handler: Handler function
        """
        self.task_handlers[task_type] = handler
        logger.info(f"Registered handler for task type: {task_type}")

    async def start(self):
        """Start batch processor."""
        logger.info(f"Starting batch processor with {self.max_workers} workers")

        # Create executor
        if self.use_processes:
            self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
        else:
            self.executor = ThreadPoolExecutor(max_workers=self.max_workers)

        # Start monitoring task
        self.monitor_task = asyncio.create_task(self._monitor_jobs())

        # Start processing loop
        await self._process_jobs()

    async def _process_jobs(self):
        """Main job processing loop."""
        while not self.shutdown_event.is_set():
            # Get next job from queue
            job = self.job_queue.get_next()

            if job:
                # Check dependencies
                if self._check_dependencies(job):
                    # Submit job for execution
                    asyncio.create_task(self._execute_job(job))
                else:
                    # Re-queue job
                    await asyncio.sleep(1)
                    self.job_queue.submit(job)
            else:
                # No jobs, wait briefly
                await asyncio.sleep(0.1)

    def _check_dependencies(self, job: BatchJob) -> bool:
        """Check if job dependencies are satisfied.

        Args:
            job: Job to check

        Returns:
            True if dependencies are satisfied
        """
        for dep_id in job.dependencies:
            dep_status = self.job_queue.get_status(dep_id)
            if dep_status != JobStatus.COMPLETED:
                return False
        return True

    async def _execute_job(self, job: BatchJob):
        """Execute a single job.

        Args:
            job: Job to execute
        """
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        self.running_jobs[job.job_id] = job
        self.job_queue.update_job(job)

        logger.info(f"Starting job {job.job_id} ({job.name})")

        try:
            # Get handler for task type
            handler = self.task_handlers.get(job.task_type)
            if not handler:
                raise ValueError(f"No handler for task type: {job.task_type}")

            # Execute in executor (avoid default executor to prevent teardown hangs)
            loop = asyncio.get_event_loop()
            executor = self.executor
            owns_executor = False
            if executor is None:
                executor = (
                    ProcessPoolExecutor(max_workers=1)
                    if self.use_processes
                    else ThreadPoolExecutor(max_workers=1)
                )
                owns_executor = True
            try:
                result = await loop.run_in_executor(
                    executor,
                    self._run_handler,
                    handler,
                    job,
                )
            finally:
                if owns_executor:
                    executor.shutdown(wait=True)

            # Update job status
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.progress = 100.0

            # Save result if output path specified
            if job.output_path and result:
                output_file = Path(job.output_path)
                output_file.parent.mkdir(parents=True, exist_ok=True)

                with open(output_file, 'w') as f:
                    json.dump(result, f, indent=2, default=str)

            logger.info(f"Job {job.job_id} completed successfully")

        except Exception as e:
            logger.error(f"Job {job.job_id} failed: {e}")
            job.status = JobStatus.FAILED
            job.error_message = str(e)

            # Retry if applicable
            if job.retry_count < job.max_retries:
                job.retry_count += 1
                job.status = JobStatus.RETRYING
                logger.info(f"Retrying job {job.job_id} (attempt {job.retry_count})")
                await asyncio.sleep(2 ** job.retry_count)  # Exponential backoff
                self.job_queue.submit(job)

        finally:
            # Update job and remove from running
            self.job_queue.update_job(job)
            del self.running_jobs[job.job_id]

    def _run_handler(self, handler: Callable, job: BatchJob) -> Any:
        """Run handler function with progress tracking.

        Args:
            handler: Handler function
            job: Batch job

        Returns:
            Handler result
        """
        # Create progress callback
        def update_progress(progress: float, message: str = ""):
            job.progress = progress
            if message:
                job.metadata['status_message'] = message
            self.job_queue.update_job(job)

        # Call handler with progress callback
        return handler(job.input_data, update_progress)

    async def _monitor_jobs(self):
        """Monitor running jobs and collect statistics."""
        while not self.shutdown_event.is_set():
            stats = self.get_statistics()

            # Log statistics
            logger.info(
                f"Jobs - Running: {stats['running']}, "
                f"Queued: {stats['queued']}, "
                f"Completed: {stats['completed']}, "
                f"Failed: {stats['failed']}"
            )

            # Check for stalled jobs
            for job_id, job in list(self.running_jobs.items()):
                if job.started_at:
                    runtime = (datetime.utcnow() - job.started_at).total_seconds()
                    if runtime > 3600:  # 1 hour timeout
                        logger.warning(f"Job {job_id} has been running for {runtime}s")

            await asyncio.sleep(30)  # Monitor every 30 seconds

    def submit_job(self,
                  name: str,
                  task_type: str,
                  input_data: Any,
                  priority: JobPriority = JobPriority.NORMAL,
                  dependencies: List[str] = None,
                  output_path: Optional[str] = None) -> str:
        """Submit a new job.

        Args:
            name: Job name
            task_type: Type of task
            input_data: Input data for task
            priority: Job priority
            dependencies: Job dependencies
            output_path: Optional output path

        Returns:
            Job ID
        """
        job = BatchJob(
            name=name,
            task_type=task_type,
            input_data=input_data,
            priority=priority,
            dependencies=dependencies or [],
            output_path=output_path
        )

        return self.job_queue.submit(job)

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status.

        Args:
            job_id: Job identifier

        Returns:
            Job status dictionary
        """
        job = self.job_queue.jobs.get(job_id)
        if not job:
            return None

        duration = None
        if job.started_at:
            end_time = job.completed_at or datetime.utcnow()
            duration = (end_time - job.started_at).total_seconds()

        return {
            'job_id': job.job_id,
            'name': job.name,
            'status': job.status.value,
            'progress': job.progress,
            'created_at': job.created_at.isoformat(),
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'duration_seconds': duration,
            'error_message': job.error_message,
            'retry_count': job.retry_count,
            'metadata': job.metadata
        }

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job.

        Args:
            job_id: Job identifier

        Returns:
            True if cancelled
        """
        job = self.job_queue.jobs.get(job_id)
        if job and job.status in [JobStatus.PENDING, JobStatus.QUEUED]:
            job.status = JobStatus.CANCELLED
            self.job_queue.update_job(job)
            logger.info(f"Job {job_id} cancelled")
            return True
        return False

    def get_statistics(self) -> Dict[str, Any]:
        """Get processing statistics.

        Returns:
            Statistics dictionary
        """
        status_counts = {
            'pending': 0,
            'queued': 0,
            'running': 0,
            'completed': 0,
            'failed': 0,
            'cancelled': 0
        }

        for job in self.job_queue.jobs.values():
            status_counts[job.status.value] += 1

        return {
            **status_counts,
            'total': len(self.job_queue.jobs),
            'workers': self.max_workers,
            'queue_size': self.job_queue.local_queue.qsize()
        }

    async def shutdown(self):
        """Shutdown batch processor."""
        logger.info("Shutting down batch processor")

        # Signal shutdown
        self.shutdown_event.set()

        # Cancel monitor task
        if self.monitor_task:
            self.monitor_task.cancel()

        # Shutdown executor
        if self.executor:
            self.executor.shutdown(wait=True)

        logger.info("Batch processor shutdown complete")


class ParallelProcessor:
    """Simplified parallel processing for common tasks."""

    @staticmethod
    def process_files(file_paths: List[Path],
                     processor_func: Callable,
                     max_workers: int = None,
                     chunk_size: int = 100) -> List[Any]:
        """Process files in parallel.

        Args:
            file_paths: List of file paths
            processor_func: Function to process each file
            max_workers: Maximum parallel workers
            chunk_size: Files per chunk

        Returns:
            Processing results
        """
        results = []
        max_workers = max_workers or mp.cpu_count()

        use_processes = True
        try:
            pickle.dumps(processor_func)
        except Exception:
            use_processes = False

        executor_cls = ProcessPoolExecutor if use_processes else ThreadPoolExecutor

        with executor_cls(max_workers=max_workers) as executor:
            # Submit in chunks
            futures = []
            for i in range(0, len(file_paths), chunk_size):
                chunk = file_paths[i:i + chunk_size]
                future = executor.submit(ParallelProcessor._process_chunk, chunk, processor_func)
                futures.append(future)

            # Collect results with progress
            for i, future in enumerate(as_completed(futures)):
                try:
                    chunk_results = future.result()
                    results.extend(chunk_results)
                    logger.info(f"Processed chunk {i+1}/{len(futures)}")
                except Exception as e:
                    logger.error(f"Chunk processing failed: {e}")

        return results

    @staticmethod
    def _process_chunk(file_paths: List[Path], processor_func: Callable) -> List[Any]:
        """Process a chunk of files.

        Args:
            file_paths: Files to process
            processor_func: Processing function

        Returns:
            Results list
        """
        results = []
        for path in file_paths:
            try:
                result = processor_func(path)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process {path}: {e}")
                results.append(None)
        return results


# Example task handlers
def example_ingestion_handler(input_data: Dict[str, Any],
                             progress_callback: Callable) -> Dict[str, Any]:
    """Example handler for data ingestion.

    Args:
        input_data: Input configuration
        progress_callback: Progress update function

    Returns:
        Processing results
    """
    progress_callback(0, "Starting ingestion")

    # Simulate processing
    total_items = input_data.get('total_items', 100)
    processed = 0

    for i in range(total_items):
        # Process item
        processed += 1

        # Update progress
        progress = (processed / total_items) * 100
        progress_callback(progress, f"Processed {processed}/{total_items} items")

    return {
        'processed': processed,
        'status': 'success'
    }
