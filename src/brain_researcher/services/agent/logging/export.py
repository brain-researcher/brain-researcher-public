"""
Log Export Utilities for Training Datasets

This module provides utilities to export logged agent executions into
formats suitable for training, analysis, and evaluation.
"""

import csv
import json
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from brain_researcher.config.run_artifacts import (
    get_metadata_root,
    get_metadata_roots_for_read,
)


class LogExporter:
    """Export logs to various formats for training and analysis."""

    def __init__(self, log_path: str | Path | None = None):
        """
        Initialize exporter.

        Args:
            log_path: Path to log directory. When omitted, use the canonical
                metadata root plus compatible legacy read aliases.
        """
        self.log_path = (
            Path(log_path)
            if log_path is not None
            else get_metadata_root()
        )
        self.read_roots = (
            (self.log_path.resolve(),)
            if log_path is not None
            else get_metadata_roots_for_read(self.log_path)
        )

    def export_for_training(
        self,
        output_file: str,
        filters: Optional[Dict[str, Any]] = None,
        format: str = 'jsonl'
    ) -> int:
        """
        Export logs for model training.

        Args:
            output_file: Output file path
            filters: Filtering criteria
            format: Output format (jsonl|csv|parquet)

        Returns:
            Number of records exported
        """
        # Load and filter logs
        logs = self._load_logs(filters)

        # Transform for training
        training_data = self._transform_for_training(logs)

        # Export in requested format
        if format == 'jsonl':
            return self._export_jsonl(training_data, output_file)
        elif format == 'csv':
            return self._export_csv(training_data, output_file)
        elif format == 'parquet':
            return self._export_parquet(training_data, output_file)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def export_conversation_pairs(
        self,
        output_file: str,
        min_quality_score: float = 0.7
    ) -> int:
        """
        Export query-response pairs for conversational training.

        Args:
            output_file: Output file path
            min_quality_score: Minimum quality threshold

        Returns:
            Number of pairs exported
        """
        pairs = []

        # Group logs by run_id
        runs = self._group_by_run()

        for run_id, phases in runs.items():
            # Must have all three phases
            if not all(p in phases for p in ['planning', 'execution', 'review']):
                continue

            # Calculate quality score
            quality = self._calculate_quality_score(phases)

            if quality < min_quality_score:
                continue

            # Extract conversation pair
            pair = {
                'instruction': phases['planning'].get('request', {}).get('query', ''),
                'input': json.dumps(phases['planning'].get('request', {}).get('tool_candidates', [])),
                'output': json.dumps({
                    'selected_tool': phases['execution'].get('request', {}).get('selected_tool'),
                    'parameters': phases['execution'].get('args', {}).get('args_resolved', {}),
                    'result': phases['review'].get('review', {}).get('status')
                }),
                'quality_score': quality,
                'run_id': run_id,
                'timestamp': phases['planning'].get('timestamps', {}).get('ts_event_utc')
            }

            pairs.append(pair)

        # Write pairs
        with open(output_file, 'w') as f:
            for pair in pairs:
                f.write(json.dumps(pair) + '\n')

        return len(pairs)

    def export_tool_usage_dataset(
        self,
        output_file: str,
        include_failures: bool = False
    ) -> int:
        """
        Export tool usage patterns for tool selection training.

        Args:
            output_file: Output file path
            include_failures: Include failed executions

        Returns:
            Number of records exported
        """
        tool_usage = []

        # Load execution logs
        exec_logs = self._load_logs({'phase': 'execution'})

        for log in exec_logs:
            # Skip failures if requested
            if not include_failures and log.get('status') != 'SUCCESS':
                continue

            # Extract tool usage pattern
            usage = {
                'query': log.get('request', {}).get('query', ''),
                'tool': log.get('request', {}).get('selected_tool', ''),
                'parameters_raw': log.get('args', {}).get('args_raw', {}),
                'parameters_resolved': log.get('args', {}).get('args_resolved', {}),
                'validation_ok': log.get('args', {}).get('validation', {}).get('ok', False),
                'execution_time_ms': log.get('timestamps', {}).get('perf', {}).get('duration_ms', 0),
                'success': log.get('status') == 'SUCCESS'
            }

            # Add environment context
            if 'execution' in log and 'env' in log['execution']:
                usage['environment'] = log['execution']['env']

            tool_usage.append(usage)

        # Export as JSONL
        with open(output_file, 'w') as f:
            for usage in tool_usage:
                f.write(json.dumps(usage) + '\n')

        return len(tool_usage)

    def export_evaluation_dataset(
        self,
        output_dir: str,
        split_ratio: Tuple[float, float, float] = (0.8, 0.1, 0.1)
    ) -> Dict[str, int]:
        """
        Export dataset split for evaluation (train/val/test).

        Args:
            output_dir: Output directory
            split_ratio: (train, val, test) split ratios

        Returns:
            Number of records in each split
        """
        import random

        # Ensure ratios sum to 1
        assert abs(sum(split_ratio) - 1.0) < 0.001

        # Load all complete runs
        runs = self._group_by_run()
        complete_runs = [
            run_id for run_id, phases in runs.items()
            if all(p in phases for p in ['planning', 'execution', 'review'])
        ]

        # Shuffle and split
        random.shuffle(complete_runs)
        n = len(complete_runs)

        train_size = int(n * split_ratio[0])
        val_size = int(n * split_ratio[1])

        train_runs = complete_runs[:train_size]
        val_runs = complete_runs[train_size:train_size + val_size]
        test_runs = complete_runs[train_size + val_size:]

        # Export each split
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        stats = {}

        for split_name, run_ids in [
            ('train', train_runs),
            ('val', val_runs),
            ('test', test_runs)
        ]:
            split_file = output_path / f"{split_name}.jsonl"
            count = 0

            with open(split_file, 'w') as f:
                for run_id in run_ids:
                    # Export all phases for this run
                    for phase in ['planning', 'execution', 'review']:
                        if phase in runs[run_id]:
                            f.write(json.dumps(runs[run_id][phase]) + '\n')
                            count += 1

            stats[split_name] = count

        # Write split metadata
        meta_file = output_path / 'metadata.json'
        with open(meta_file, 'w') as f:
            json.dump({
                'total_runs': len(complete_runs),
                'split_ratio': split_ratio,
                'splits': {
                    'train': len(train_runs),
                    'val': len(val_runs),
                    'test': len(test_runs)
                },
                'records_per_split': stats,
                'created_at': datetime.now().isoformat()
            }, f, indent=2)

        return stats

    def generate_analytics_report(
        self,
        output_file: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive analytics report.

        Args:
            output_file: Output file path
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Analytics summary
        """
        # Load logs within date range
        filters = {}
        if start_date:
            filters['start_date'] = start_date
        if end_date:
            filters['end_date'] = end_date

        logs = self._load_logs(filters)

        # Compute analytics
        analytics = {
            'date_range': {
                'start': start_date or 'all',
                'end': end_date or 'all'
            },
            'total_logs': len(logs),
            'by_phase': defaultdict(int),
            'by_status': defaultdict(int),
            'by_tool': defaultdict(int),
            'execution_times': [],
            'daily_activity': defaultdict(int),
            'error_analysis': defaultdict(list)
        }

        for log in logs:
            # Phase distribution
            phase = log.get('phase', 'unknown')
            analytics['by_phase'][phase] += 1

            # Status distribution
            status = log.get('status', 'unknown')
            analytics['by_status'][status] += 1

            # Tool usage
            if 'request' in log and 'selected_tool' in log['request']:
                tool = log['request']['selected_tool']
                analytics['by_tool'][tool] += 1

            # Execution times
            if 'timestamps' in log and 'perf' in log['timestamps']:
                duration = log['timestamps']['perf'].get('duration_ms', 0)
                analytics['execution_times'].append(duration)

            # Daily activity
            if 'timestamps' in log and 'ts_event_utc' in log['timestamps']:
                date = log['timestamps']['ts_event_utc'][:10]
                analytics['daily_activity'][date] += 1

            # Error analysis
            if log.get('status') == 'FAILED' and 'errors' in log:
                for error in log['errors']:
                    analytics['error_analysis'][phase].append(error)

        # Compute statistics
        if analytics['execution_times']:
            analytics['execution_stats'] = {
                'mean_ms': sum(analytics['execution_times']) / len(analytics['execution_times']),
                'min_ms': min(analytics['execution_times']),
                'max_ms': max(analytics['execution_times']),
                'median_ms': sorted(analytics['execution_times'])[len(analytics['execution_times']) // 2]
            }

        # Convert defaultdicts to regular dicts for JSON serialization
        analytics['by_phase'] = dict(analytics['by_phase'])
        analytics['by_status'] = dict(analytics['by_status'])
        analytics['by_tool'] = dict(analytics['by_tool'])
        analytics['daily_activity'] = dict(analytics['daily_activity'])
        analytics['error_analysis'] = dict(analytics['error_analysis'])

        # Write report
        with open(output_file, 'w') as f:
            json.dump(analytics, f, indent=2)

        return analytics

    def _load_logs(self, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Load logs from disk with optional filtering.

        Args:
            filters: Filtering criteria

        Returns:
            List of log entries
        """
        logs = []
        filters = filters or {}
        seen_records = set()

        for jsonl_file in self._iter_session_files():
            # Check date filter
            file_date = jsonl_file.stem  # YYYY-MM-DD

            if 'start_date' in filters and file_date < filters['start_date']:
                continue
            if 'end_date' in filters and file_date > filters['end_date']:
                continue

            # Load logs from file
            with open(jsonl_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        log = json.loads(line)

                        # Apply filters
                        if 'phase' in filters and log.get('phase') != filters['phase']:
                            continue
                        if 'status' in filters and log.get('status') != filters['status']:
                            continue
                        if 'run_id' in filters and log.get('run_id') != filters['run_id']:
                            continue

                        dedupe_key = json.dumps(log, sort_keys=True, ensure_ascii=False)
                        if dedupe_key in seen_records:
                            continue
                        seen_records.add(dedupe_key)
                        logs.append(log)

                    except json.JSONDecodeError:
                        continue

        # Sort by timestamp
        logs.sort(
            key=lambda x: x.get('timestamps', {}).get('ts_event_utc', ''),
            reverse=False
        )

        return logs

    def _iter_session_files(self) -> List[Path]:
        """Return session JSONL files across all readable metadata roots."""

        session_files: list[Path] = []
        seen_paths: set[str] = set()

        for root in self.read_roots:
            session_dir = root / 'sessions'
            if not session_dir.exists():
                continue
            for jsonl_file in sorted(session_dir.glob('*.jsonl')):
                resolved = str(jsonl_file.resolve())
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                session_files.append(jsonl_file)

        return session_files

    def _group_by_run(self) -> Dict[str, Dict[str, Any]]:
        """
        Group logs by run_id and phase.

        Returns:
            Dict mapping run_id to phases
        """
        runs = defaultdict(dict)

        logs = self._load_logs()

        for log in logs:
            run_id = log.get('run_id')
            phase = log.get('phase')

            if run_id and phase:
                runs[run_id][phase] = log

        return dict(runs)

    def _calculate_quality_score(self, phases: Dict[str, Any]) -> float:
        """
        Calculate quality score for a complete run.

        Args:
            phases: Dict of phase logs

        Returns:
            Quality score (0-1)
        """
        score = 0.0

        # Check execution success
        if phases.get('execution', {}).get('status') == 'SUCCESS':
            score += 0.4

        # Check review pass
        if phases.get('review', {}).get('review', {}).get('status') == 'PASS':
            score += 0.3

        # Check validation
        if phases.get('execution', {}).get('args', {}).get('validation', {}).get('ok'):
            score += 0.2

        # Check execution time (penalize very slow)
        exec_time = phases.get('execution', {}).get('timestamps', {}).get('perf', {}).get('duration_ms', 0)
        if 0 < exec_time < 5000:  # Under 5 seconds
            score += 0.1
        elif exec_time > 30000:  # Over 30 seconds
            score -= 0.1

        return max(0.0, min(1.0, score))

    def _transform_for_training(self, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Transform logs into training-friendly format.

        Args:
            logs: Raw log entries

        Returns:
            Transformed training data
        """
        training_data = []

        for log in logs:
            # Skip incomplete logs
            if 'request' not in log or 'query' not in log['request']:
                continue

            # Create training record
            record = {
                'query': log['request']['query'],
                'phase': log.get('phase'),
                'tool': log['request'].get('selected_tool'),
                'success': log.get('status') == 'SUCCESS',
                'duration_ms': log.get('timestamps', {}).get('perf', {}).get('duration_ms', 0)
            }

            # Add parameters for execution phase
            if log.get('phase') == 'execution' and 'args' in log:
                record['parameters_raw'] = json.dumps(log['args'].get('args_raw', {}))
                record['parameters_resolved'] = json.dumps(log['args'].get('args_resolved', {}))
                record['validation_ok'] = log['args'].get('validation', {}).get('ok', False)

            # Add review data
            if log.get('phase') == 'review' and 'review' in log:
                record['review_status'] = log['review'].get('status')
                record['review_checks'] = len(log['review'].get('checks', []))

            training_data.append(record)

        return training_data

    def _export_jsonl(self, data: List[Dict[str, Any]], output_file: str) -> int:
        """Export data as JSONL."""
        with open(output_file, 'w') as f:
            for record in data:
                f.write(json.dumps(record) + '\n')
        return len(data)

    def _export_csv(self, data: List[Dict[str, Any]], output_file: str) -> int:
        """Export data as CSV."""
        if not data:
            return 0

        # Get all keys
        keys = set()
        for record in data:
            keys.update(record.keys())

        # Write CSV
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=sorted(keys))
            writer.writeheader()
            writer.writerows(data)

        return len(data)

    def _export_parquet(self, data: List[Dict[str, Any]], output_file: str) -> int:
        """Export data as Parquet."""
        if not data:
            return 0

        df = pd.DataFrame(data)
        df.to_parquet(output_file, index=False)

        return len(data)
