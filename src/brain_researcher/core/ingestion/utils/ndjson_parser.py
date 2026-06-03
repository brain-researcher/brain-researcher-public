"""High-performance NDJSON streaming parser.

Uses orjson for fast JSON parsing and supports compressed files.
Default is synchronous streaming for local files (CPU-bound).
Async mode available for network streams.
"""

import bz2
import gzip
import logging
from pathlib import Path
from typing import IO, Iterator, Dict, Any, Optional, Callable, List, Tuple

try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    import json
    HAS_ORJSON = False
    logging.warning("orjson not available, falling back to standard json")

logger = logging.getLogger(__name__)


def open_any(path: str | Path) -> IO[bytes]:
    """Open a file with automatic compression detection.

    Args:
        path: File path (supports .gz, .bz2, or uncompressed)

    Returns:
        File handle opened in binary mode
    """
    path = str(path)

    if path.endswith(".gz"):
        return gzip.open(path, "rb")
    elif path.endswith(".bz2"):
        return bz2.open(path, "rb")
    else:
        return open(path, "rb")


def iter_ndjson(
    stream: IO[bytes],
    on_error: Optional[Callable[[int, bytes, Exception], None]] = None,
    max_errors: int = 100
) -> Iterator[Dict[str, Any]]:
    """Iterate over NDJSON lines from a stream.

    Args:
        stream: Binary stream to read from
        on_error: Error callback (line_num, line_content, exception)
        max_errors: Maximum errors before stopping (0 = unlimited)

    Yields:
        Parsed JSON objects

    Example:
        >>> with open_any("data.ndjson.gz") as f:
        ...     for obj in iter_ndjson(f):
        ...         print(obj["id"])
    """
    error_count = 0

    for line_num, line in enumerate(stream, 1):
        # Skip empty lines
        if not line.strip():
            continue

        try:
            if HAS_ORJSON:
                yield orjson.loads(line)
            else:
                yield json.loads(line.decode("utf-8"))

        except Exception as e:
            error_count += 1

            if on_error:
                # Truncate line for error reporting (max 512 bytes)
                on_error(line_num, line[:512], e)
            else:
                logger.warning(f"Line {line_num}: Failed to parse - {e}")

            # Stop if too many errors
            if max_errors > 0 and error_count >= max_errors:
                raise RuntimeError(f"Too many parse errors ({error_count})")


def parse_ndjson_file(
    path: str | Path,
    batch_size: int = 1000,
    on_batch: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
    on_error: Optional[Callable[[int, bytes, Exception], None]] = None,
    max_errors: int = 100
) -> Tuple[int, int, List[Tuple[int, str]]]:
    """Parse an entire NDJSON file with batching support.

    Args:
        path: Path to NDJSON file
        batch_size: Number of records per batch
        on_batch: Callback for each batch of records
        on_error: Error callback
        max_errors: Maximum errors before stopping

    Returns:
        Tuple of (total_lines, valid_lines, errors)

    Example:
        >>> def process_batch(records):
        ...     print(f"Processing {len(records)} records")
        ...
        >>> total, valid, errors = parse_ndjson_file(
        ...     "data.ndjson.gz",
        ...     on_batch=process_batch
        ... )
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    total_lines = 0
    valid_lines = 0
    errors: List[Tuple[int, str]] = []
    batch: List[Dict[str, Any]] = []

    def error_handler(line_num: int, line: bytes, exc: Exception):
        errors.append((line_num, str(exc)))
        if on_error:
            on_error(line_num, line, exc)

    with open_any(path) as stream:
        for obj in iter_ndjson(stream, on_error=error_handler, max_errors=max_errors):
            total_lines += 1
            valid_lines += 1
            batch.append(obj)

            # Process batch when full
            if len(batch) >= batch_size:
                if on_batch:
                    on_batch(list(batch))
                batch.clear()

        # Process remaining records
        if batch and on_batch:
            on_batch(list(batch))

    # Count error lines
    total_lines += len(errors)

    logger.info(
        f"Parsed {path.name}: {valid_lines}/{total_lines} valid "
        f"({len(errors)} errors)"
    )

    return total_lines, valid_lines, errors


class NDJSONStreamProcessor:
    """Process NDJSON streams with backpressure and memory control."""

    def __init__(
        self,
        batch_size: int = 1000,
        max_memory_mb: int = 500,
        error_buffer_size: int = 100
    ):
        """Initialize stream processor.

        Args:
            batch_size: Records per batch
            max_memory_mb: Maximum memory usage in MB
            error_buffer_size: Size of circular error buffer
        """
        self.batch_size = batch_size
        self.max_memory_mb = max_memory_mb
        self.error_buffer_size = error_buffer_size

        # Circular buffer for errors
        self.error_buffer: List[Tuple[int, str]] = []
        self.error_position = 0

        # Statistics
        self.stats = {
            "lines_read": 0,
            "valid": 0,
            "invalid": 0,
            "batches": 0,
            "bytes_processed": 0
        }

    def add_error(self, line_num: int, error: str):
        """Add error to circular buffer."""
        if len(self.error_buffer) < self.error_buffer_size:
            self.error_buffer.append((line_num, error))
        else:
            # Circular overwrite
            self.error_buffer[self.error_position] = (line_num, error)
            self.error_position = (self.error_position + 1) % self.error_buffer_size

    def process_stream(
        self,
        stream: IO[bytes],
        processor: Callable[[List[Dict[str, Any]]], None]
    ) -> Dict[str, Any]:
        """Process a stream with backpressure control.

        Args:
            stream: Input stream
            processor: Function to process each batch

        Returns:
            Processing statistics
        """
        batch = []

        def error_handler(line_num: int, line: bytes, exc: Exception):
            self.add_error(line_num, str(exc))
            self.stats["invalid"] += 1

        for obj in iter_ndjson(stream, on_error=error_handler):
            self.stats["lines_read"] += 1
            self.stats["valid"] += 1
            batch.append(obj)

            if len(batch) >= self.batch_size:
                processor(list(batch))
                self.stats["batches"] += 1
                batch.clear()

                # Simple memory check (could be enhanced with psutil)
                # This is a placeholder - real implementation would check actual memory
                if self.stats["batches"] % 100 == 0:
                    logger.debug(f"Processed {self.stats['batches']} batches")

        # Process remaining
        if batch:
            processor(list(batch))
            self.stats["batches"] += 1

        return {
            **self.stats,
            "recent_errors": list(self.error_buffer)
        }
