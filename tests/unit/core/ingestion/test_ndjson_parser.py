"""Tests for NDJSON parser."""

import gzip
import bz2
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from brain_researcher.core.ingestion.utils.ndjson_parser import (
    open_any,
    iter_ndjson,
    parse_ndjson_file,
    NDJSONStreamProcessor,
)


class TestOpenAny:
    """Test file opening with compression detection."""
    
    def test_open_regular_file(self, tmp_path):
        """Test opening regular file."""
        file_path = tmp_path / "test.ndjson"
        file_path.write_text("test")
        
        with open_any(file_path) as f:
            content = f.read()
        
        assert content == b"test"
    
    def test_open_gzip_file(self, tmp_path):
        """Test opening gzipped file."""
        file_path = tmp_path / "test.ndjson.gz"
        
        with gzip.open(file_path, "wb") as f:
            f.write(b"test")
        
        with open_any(file_path) as f:
            content = f.read()
        
        assert content == b"test"
    
    def test_open_bz2_file(self, tmp_path):
        """Test opening bz2 file."""
        file_path = tmp_path / "test.ndjson.bz2"
        
        with bz2.open(file_path, "wb") as f:
            f.write(b"test")
        
        with open_any(file_path) as f:
            content = f.read()
        
        assert content == b"test"


class TestIterNDJSON:
    """Test NDJSON iteration."""
    
    def test_iter_valid_ndjson(self):
        """Test iterating valid NDJSON."""
        lines = [
            b'{"id": 1, "name": "test1"}\n',
            b'{"id": 2, "name": "test2"}\n',
            b'\n',  # Empty line should be skipped
            b'{"id": 3, "name": "test3"}\n',
        ]
        
        results = list(iter_ndjson(lines))
        
        assert len(results) == 3
        assert results[0] == {"id": 1, "name": "test1"}
        assert results[1] == {"id": 2, "name": "test2"}
        assert results[2] == {"id": 3, "name": "test3"}
    
    def test_iter_with_errors(self):
        """Test iteration with error handling."""
        lines = [
            b'{"id": 1}\n',
            b'invalid json\n',
            b'{"id": 2}\n',
        ]
        
        errors = []
        
        def error_handler(line_num, line, exc):
            errors.append((line_num, str(exc)))
        
        results = list(iter_ndjson(lines, on_error=error_handler))
        
        assert len(results) == 2
        assert results[0] == {"id": 1}
        assert results[1] == {"id": 2}
        assert len(errors) == 1
        assert errors[0][0] == 2  # Line number
    
    def test_max_errors(self):
        """Test max_errors limit."""
        lines = [
            b'invalid1\n',
            b'invalid2\n',
            b'invalid3\n',
        ]
        
        with pytest.raises(RuntimeError, match="Too many parse errors"):
            list(iter_ndjson(lines, max_errors=2))


class TestParseNDJSONFile:
    """Test file parsing with batching."""
    
    def test_parse_file(self, tmp_path):
        """Test parsing entire file."""
        file_path = tmp_path / "test.ndjson"
        
        data = [
            {"id": i, "value": f"test{i}"}
            for i in range(10)
        ]
        
        with open(file_path, "w") as f:
            for item in data:
                f.write(json.dumps(item) + "\n")
        
        batches = []
        
        def on_batch(records):
            batches.append(records)
        
        total, valid, errors = parse_ndjson_file(
            file_path,
            batch_size=3,
            on_batch=on_batch
        )
        
        assert total == 10
        assert valid == 10
        assert len(errors) == 0
        assert len(batches) == 4  # 10 records / 3 per batch = 4 batches
        assert len(batches[0]) == 3
        assert len(batches[-1]) == 1  # Last batch has remainder
    
    def test_parse_with_errors(self, tmp_path):
        """Test parsing with some invalid lines."""
        file_path = tmp_path / "test.ndjson"
        
        with open(file_path, "w") as f:
            f.write('{"id": 1}\n')
            f.write('invalid\n')
            f.write('{"id": 2}\n')
        
        total, valid, errors = parse_ndjson_file(file_path)
        
        assert total == 3
        assert valid == 2
        assert len(errors) == 1
    
    def test_parse_compressed(self, tmp_path):
        """Test parsing compressed file."""
        file_path = tmp_path / "test.ndjson.gz"
        
        data = [{"id": i} for i in range(5)]
        
        with gzip.open(file_path, "wt") as f:
            for item in data:
                f.write(json.dumps(item) + "\n")
        
        total, valid, errors = parse_ndjson_file(file_path)
        
        assert total == 5
        assert valid == 5
        assert len(errors) == 0


class TestNDJSONStreamProcessor:
    """Test stream processor with backpressure."""
    
    def test_process_stream(self):
        """Test stream processing."""
        processor = NDJSONStreamProcessor(batch_size=2)
        
        lines = [
            b'{"id": 1}\n',
            b'{"id": 2}\n',
            b'{"id": 3}\n',
        ]
        
        batches = []
        
        def process_batch(batch):
            batches.append(batch)
        
        stats = processor.process_stream(lines, process_batch)
        
        assert stats["lines_read"] == 3
        assert stats["valid"] == 3
        assert stats["invalid"] == 0
        assert stats["batches"] == 2
        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 1
    
    def test_error_buffer(self):
        """Test circular error buffer."""
        processor = NDJSONStreamProcessor(error_buffer_size=2)
        
        # Add more errors than buffer size
        processor.add_error(1, "error1")
        processor.add_error(2, "error2")
        processor.add_error(3, "error3")  # Should overwrite first
        
        assert len(processor.error_buffer) == 2
        # Should contain last 2 errors
        assert (2, "error2") in processor.error_buffer
        assert (3, "error3") in processor.error_buffer


@pytest.mark.benchmark
class TestPerformance:
    """Performance benchmarks."""
    
    def test_parse_speed(self, tmp_path, benchmark):
        """Benchmark parsing speed."""
        file_path = tmp_path / "large.ndjson"
        
        # Create large file
        with open(file_path, "w") as f:
            for i in range(10000):
                f.write(json.dumps({"id": i, "data": "x" * 100}) + "\n")
        
        def parse():
            total, _, _ = parse_ndjson_file(file_path, batch_size=1000)
            return total
        
        result = benchmark(parse)
        assert result == 10000
    
    @pytest.mark.skipif(
        not pytest.importorskip("orjson"),
        reason="orjson not available"
    )
    def test_orjson_vs_json(self, benchmark):
        """Compare orjson vs standard json."""
        data = {"id": 1, "nested": {"value": "test" * 100}}
        line = json.dumps(data).encode()
        
        import orjson
        
        def parse_orjson():
            return orjson.loads(line)
        
        def parse_json():
            return json.loads(line)
        
        # Benchmark both
        result_orjson = benchmark(parse_orjson)
        # result_json = benchmark(parse_json)  # Would need separate benchmark
        
        assert result_orjson == data