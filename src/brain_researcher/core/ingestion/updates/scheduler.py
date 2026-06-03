"""Simple scheduler for regular updates.

Provides basic scheduling without external dependencies.
For production, consider using APScheduler or Celery.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class Priority(Enum):
    """Update priority levels."""
    HIGH = 1
    NORMAL = 2
    LOW = 3


def run_every(
    interval_seconds: int,
    function: Callable,
    *args,
    daemon: bool = True,
    **kwargs
) -> threading.Thread:
    """Run a function periodically in a background thread.

    Args:
        interval_seconds: Interval between runs
        function: Function to run
        *args: Function arguments
        daemon: Run as daemon thread
        **kwargs: Function keyword arguments

    Returns:
        Thread object
    """
    def loop():
        while True:
            try:
                function(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in scheduled function: {e}")
            finally:
                time.sleep(interval_seconds)

    thread = threading.Thread(target=loop, daemon=daemon)
    thread.start()
    return thread


class UpdateScheduler:
    """Schedule and manage data source updates."""

    def __init__(self, max_workers: int = 1):
        """Initialize scheduler.

        Args:
            max_workers: Maximum concurrent update workers
        """
        self.max_workers = max_workers

        # Scheduled tasks
        self.tasks: Dict[str, Dict[str, Any]] = {}

        # Running threads
        self.threads: Dict[str, threading.Thread] = {}

        # Lock for thread safety
        self.lock = threading.Lock()

        # Statistics
        self.stats = {
            "scheduled": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "last_run": {},
        }

    def schedule(
        self,
        name: str,
        function: Callable,
        interval: timedelta,
        priority: Priority = Priority.NORMAL,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        start_immediately: bool = False
    ):
        """Schedule a periodic update task.

        Args:
            name: Task name
            function: Function to run
            interval: Time between runs
            priority: Task priority
            args: Function arguments
            kwargs: Function keyword arguments
            start_immediately: Run immediately on schedule
        """
        with self.lock:
            self.tasks[name] = {
                "function": function,
                "interval": interval,
                "priority": priority,
                "args": args,
                "kwargs": kwargs or {},
                "next_run": datetime.now() if start_immediately else datetime.now() + interval,
                "last_run": None,
                "runs": 0,
                "failures": 0,
            }

            self.stats["scheduled"] += 1

        logger.info(f"Scheduled task '{name}' to run every {interval}")

        if start_immediately:
            self._run_task(name)

    def _run_task(self, name: str):
        """Run a scheduled task.

        Args:
            name: Task name
        """
        if name not in self.tasks:
            logger.warning(f"Task '{name}' not found")
            return

        task = self.tasks[name]

        # Check if already running
        if name in self.threads and self.threads[name].is_alive():
            logger.warning(f"Task '{name}' is already running")
            return

        def worker():
            with self.lock:
                self.stats["running"] += 1
                task["last_run"] = datetime.now()
                self.stats["last_run"][name] = task["last_run"].isoformat()

            try:
                logger.info(f"Running task '{name}'")
                task["function"](*task["args"], **task["kwargs"])

                with self.lock:
                    task["runs"] += 1
                    self.stats["completed"] += 1

                logger.info(f"Task '{name}' completed successfully")

            except Exception as e:
                logger.error(f"Task '{name}' failed: {e}")

                with self.lock:
                    task["failures"] += 1
                    self.stats["failed"] += 1

            finally:
                with self.lock:
                    self.stats["running"] -= 1
                    # Schedule next run
                    task["next_run"] = datetime.now() + task["interval"]

        # Start worker thread
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.threads[name] = thread

    def start(self):
        """Start the scheduler."""
        logger.info("Starting update scheduler")

        def scheduler_loop():
            while True:
                now = datetime.now()

                # Find tasks to run
                with self.lock:
                    due_tasks = [
                        (name, task["priority"])
                        for name, task in self.tasks.items()
                        if task["next_run"] <= now
                    ]

                # Sort by priority
                due_tasks.sort(key=lambda x: x[1].value)

                # Run due tasks (respecting max_workers)
                running_count = sum(
                    1 for t in self.threads.values() if t and t.is_alive()
                )

                for name, _ in due_tasks:
                    if running_count >= self.max_workers:
                        break

                    self._run_task(name)
                    running_count += 1

                # Sleep before next check
                time.sleep(60)  # Check every minute

        # Start scheduler thread
        scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
        scheduler_thread.start()

        return scheduler_thread

    def stop_task(self, name: str):
        """Stop a scheduled task.

        Args:
            name: Task name
        """
        with self.lock:
            if name in self.tasks:
                del self.tasks[name]
                logger.info(f"Stopped task '{name}'")

            # Note: Running threads will complete their current execution

    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status.

        Returns:
            Status dictionary
        """
        with self.lock:
            status = {
                "tasks": {},
                "stats": dict(self.stats),
            }

            for name, task in self.tasks.items():
                status["tasks"][name] = {
                    "interval": str(task["interval"]),
                    "priority": task["priority"].name,
                    "next_run": task["next_run"].isoformat() if task["next_run"] else None,
                    "last_run": task["last_run"].isoformat() if task["last_run"] else None,
                    "runs": task["runs"],
                    "failures": task["failures"],
                    "is_running": name in self.threads and self.threads[name].is_alive(),
                }

        return status

    def run_now(self, name: str):
        """Run a task immediately.

        Args:
            name: Task name
        """
        if name not in self.tasks:
            raise ValueError(f"Task '{name}' not found")

        self._run_task(name)

    def list_tasks(self) -> List[str]:
        """List all scheduled tasks.

        Returns:
            List of task names
        """
        with self.lock:
            return list(self.tasks.keys())


class DataSourceUpdater:
    """Coordinate updates for multiple data sources."""

    def __init__(self, scheduler: Optional[UpdateScheduler] = None):
        """Initialize data source updater.

        Args:
            scheduler: Update scheduler (creates default if None)
        """
        self.scheduler = scheduler or UpdateScheduler(max_workers=2)

        # Update functions for each source
        self.update_functions: Dict[str, Callable] = {}

    def register_source(
        self,
        name: str,
        update_function: Callable,
        interval: timedelta,
        priority: Priority = Priority.NORMAL
    ):
        """Register a data source for updates.

        Args:
            name: Source name
            update_function: Function to update the source
            interval: Update interval
            priority: Update priority
        """
        self.update_functions[name] = update_function

        self.scheduler.schedule(
            name=f"update_{name}",
            function=update_function,
            interval=interval,
            priority=priority
        )

        logger.info(f"Registered data source '{name}' for updates")

    def update_all(self):
        """Run updates for all sources immediately."""
        for name, function in self.update_functions.items():
            logger.info(f"Updating {name}")
            try:
                function()
            except Exception as e:
                logger.error(f"Failed to update {name}: {e}")

    def start(self):
        """Start the update scheduler."""
        return self.scheduler.start()

    def get_status(self) -> Dict[str, Any]:
        """Get updater status.

        Returns:
            Status dictionary
        """
        return {
            "sources": list(self.update_functions.keys()),
            "scheduler": self.scheduler.get_status(),
        }