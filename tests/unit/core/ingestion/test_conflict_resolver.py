"""Unit tests for the Conflict Resolver component."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import tempfile
import json

from brain_researcher.core.ingestion.updates.conflict_resolver import (
    ConflictResolver,
    ConflictType,
    ResolutionStrategy
)


class TestConflictResolver:
    """Test suite for ConflictResolver class."""
    
    @pytest.fixture
    def resolver(self):
        """Create a ConflictResolver instance for testing."""
        return ConflictResolver(
            default_strategy=ResolutionStrategy.KEEP_NEWEST,
            quality_threshold=0.7
        )
    
    @pytest.fixture
    def sample_local_data(self):
        """Sample local data for testing."""
        return {
            'id': 'subject_001',
            'age': 25,
            'sex': 'M',
            'score': 85.5,
            'metadata': {'version': '1.0', 'quality': 0.8}
        }
    
    @pytest.fixture
    def sample_remote_data(self):
        """Sample remote data for testing."""
        return {
            'id': 'subject_001',
            'age': 26,  # Different age
            'sex': 'M',
            'score': 87.2,  # Different score
            'handedness': 'R',  # New field
            'metadata': {'version': '1.1', 'quality': 0.9}
        }
    
    def test_initialization(self):
        """Test ConflictResolver initialization."""
        resolver = ConflictResolver()
        
        assert resolver.default_strategy == ResolutionStrategy.KEEP_NEWEST
        assert resolver.quality_threshold == 0.7
        assert resolver.conflict_history == []
        assert resolver.manual_review_queue == []
        assert isinstance(resolver.resolution_rules, dict)
        
        # Test custom initialization
        custom_resolver = ConflictResolver(
            default_strategy=ResolutionStrategy.KEEP_LOCAL,
            quality_threshold=0.5
        )
        
        assert custom_resolver.default_strategy == ResolutionStrategy.KEEP_LOCAL
        assert custom_resolver.quality_threshold == 0.5
    
    def test_detect_conflicts_value_mismatch(self, resolver, sample_local_data, sample_remote_data):
        """Test conflict detection for value mismatches."""
        conflicts = resolver.detect_conflicts(sample_local_data, sample_remote_data)
        
        # Should detect conflicts for age and score
        assert len(conflicts) >= 2
        
        # Check for age conflict
        age_conflicts = [c for c in conflicts if c.get('key') == 'age']
        assert len(age_conflicts) == 1
        
        age_conflict = age_conflicts[0]
        assert age_conflict['type'] == ConflictType.VALUE_MISMATCH
        assert age_conflict['local_value'] == 25
        assert age_conflict['remote_value'] == 26
        assert 'id' in age_conflict
        assert 'timestamp' in age_conflict
    
    def test_detect_conflicts_schema_change(self, resolver):
        """Test conflict detection for schema changes."""
        local_data = {'id': '001', 'age': 25, 'sex': 'M'}
        remote_data = {'id': '001', 'age': 25, 'handedness': 'R'}  # sex removed, handedness added
        
        conflicts = resolver.detect_conflicts(local_data, remote_data)
        
        # Should detect schema change
        schema_conflicts = [c for c in conflicts if c['type'] == ConflictType.SCHEMA_CHANGE]
        assert len(schema_conflicts) == 1
        
        schema_conflict = schema_conflicts[0]
        assert 'sex' in schema_conflict['removed_keys']
        assert 'handedness' in schema_conflict['added_keys']
    
    def test_detect_conflicts_version_conflict(self, resolver, sample_local_data, sample_remote_data):
        """Test conflict detection for version conflicts."""
        metadata = {
            'local_version': '1.0',
            'remote_version': '1.1'
        }
        
        conflicts = resolver.detect_conflicts(
            sample_local_data, 
            sample_remote_data, 
            metadata=metadata
        )
        
        # Should detect version conflict
        version_conflicts = [c for c in conflicts if c['type'] == ConflictType.VERSION_CONFLICT]
        assert len(version_conflicts) == 1
        
        version_conflict = version_conflicts[0]
        assert version_conflict['local_version'] == '1.0'
        assert version_conflict['remote_version'] == '1.1'
    
    def test_detect_conflicts_no_conflicts(self, resolver):
        """Test when no conflicts exist."""
        data = {'id': '001', 'age': 25, 'sex': 'M'}
        
        conflicts = resolver.detect_conflicts(data, data)
        
        # Should detect no conflicts for identical data
        assert len(conflicts) == 0
    
    def test_resolve_conflicts_keep_newest(self, resolver, sample_local_data, sample_remote_data):
        """Test conflict resolution with KEEP_NEWEST strategy."""
        # Add timestamps to metadata
        metadata = {
            'local_timestamp': '2023-01-01T10:00:00',
            'remote_timestamp': '2023-01-01T11:00:00'
        }
        
        conflicts = resolver.detect_conflicts(sample_local_data, sample_remote_data, metadata)
        results = resolver.resolve_conflicts(conflicts, ResolutionStrategy.KEEP_NEWEST)
        
        assert results['statistics']['total_conflicts'] > 0
        assert results['statistics']['resolved'] > 0
        
        # Check that newer values are chosen
        for resolution in results['resolved']:
            if resolution.get('key') == 'age':
                assert resolution['resolved_value'] == 26  # Remote is newer
    
    def test_resolve_conflicts_keep_local(self, resolver, sample_local_data, sample_remote_data):
        """Test conflict resolution with KEEP_LOCAL strategy."""
        conflicts = resolver.detect_conflicts(sample_local_data, sample_remote_data)
        results = resolver.resolve_conflicts(conflicts, ResolutionStrategy.KEEP_LOCAL)
        
        # All conflicts should keep local values
        for resolution in results['resolved']:
            if resolution.get('key') == 'age':
                assert resolution['resolved_value'] == 25  # Local value
    
    def test_resolve_conflicts_keep_remote(self, resolver, sample_local_data, sample_remote_data):
        """Test conflict resolution with KEEP_REMOTE strategy."""
        conflicts = resolver.detect_conflicts(sample_local_data, sample_remote_data)
        results = resolver.resolve_conflicts(conflicts, ResolutionStrategy.KEEP_REMOTE)
        
        # All conflicts should keep remote values
        for resolution in results['resolved']:
            if resolution.get('key') == 'age':
                assert resolution['resolved_value'] == 26  # Remote value
    
    def test_resolve_conflicts_use_quality_score(self, resolver):
        """Test conflict resolution using quality scores."""
        local_data = {'score': 85.5}
        remote_data = {'score': 87.2}
        metadata = {
            'local_quality': 0.6,
            'remote_quality': 0.9  # Higher quality
        }
        
        conflicts = resolver.detect_conflicts(local_data, remote_data, metadata)
        results = resolver.resolve_conflicts(conflicts, ResolutionStrategy.USE_QUALITY_SCORE)
        
        # Should choose remote value due to higher quality
        score_resolution = next(
            (r for r in results['resolved'] if r.get('key') == 'score'), 
            None
        )
        if score_resolution:
            assert score_resolution['resolved_value'] == 87.2
    
    def test_resolve_conflicts_merge_values(self, resolver):
        """Test conflict resolution with value merging."""
        local_data = {'tags': ['A', 'B'], 'info': {'x': 1}}
        remote_data = {'tags': ['B', 'C'], 'info': {'y': 2}}
        
        conflicts = resolver.detect_conflicts(local_data, remote_data)
        results = resolver.resolve_conflicts(conflicts, ResolutionStrategy.MERGE_VALUES)
        
        # Check merged results
        for resolution in results['resolved']:
            if resolution.get('key') == 'tags':
                # Should be union of both lists
                merged_tags = resolution['resolved_value']
                assert 'A' in merged_tags
                assert 'B' in merged_tags
                assert 'C' in merged_tags
            elif resolution.get('key') == 'info':
                # Should merge dictionaries
                merged_info = resolution['resolved_value']
                assert merged_info['x'] == 1
                assert merged_info['y'] == 2
    
    def test_resolve_conflicts_manual_review(self, resolver, sample_local_data, sample_remote_data):
        """Test conflicts requiring manual review."""
        conflicts = resolver.detect_conflicts(sample_local_data, sample_remote_data)
        results = resolver.resolve_conflicts(conflicts, ResolutionStrategy.MANUAL_REVIEW)
        
        # All conflicts should go to manual review
        assert results['statistics']['manual_review'] == results['statistics']['total_conflicts']
        assert len(resolver.manual_review_queue) > 0
    
    def test_merge_data(self, resolver, sample_local_data, sample_remote_data):
        """Test data merging after conflict resolution."""
        conflicts = resolver.detect_conflicts(sample_local_data, sample_remote_data)
        resolution_results = resolver.resolve_conflicts(conflicts, ResolutionStrategy.KEEP_REMOTE)
        
        merged_data = resolver.merge_data(sample_local_data, sample_remote_data, resolution_results)
        
        # Should contain all keys from both datasets
        assert 'id' in merged_data
        assert 'age' in merged_data
        assert 'sex' in merged_data
        assert 'score' in merged_data
        assert 'handedness' in merged_data  # New field from remote
        assert '_merge_metadata' in merged_data
        
        # Values should be resolved according to strategy
        assert merged_data['age'] == 26  # Remote value (KEEP_REMOTE)
    
    def test_validate_resolution(self, resolver):
        """Test resolution validation."""
        original_data = {'id': '001', 'age': 25, 'sex': 'M', 'score': 85.5}
        
        # Valid resolution
        valid_resolved = {'id': '001', 'age': 26, 'sex': 'M', 'score': 87.2}
        assert resolver.validate_resolution(original_data, valid_resolved)
        
        # Invalid resolution (significant data loss)
        invalid_resolved = {'id': '001'}  # Missing most fields
        assert not resolver.validate_resolution(original_data, invalid_resolved)
        
        # Invalid resolution (incompatible type change)
        type_mismatch = {'id': '001', 'age': 'twenty-five', 'sex': 'M', 'score': 85.5}
        assert not resolver.validate_resolution(original_data, type_mismatch)
    
    def test_rollback_changes(self, resolver):
        """Test rollback functionality."""
        data = {'id': '001', 'age': 25}
        checkpoint = 'cp_001'
        
        rolled_back = resolver.rollback_changes(data, checkpoint)
        
        assert rolled_back['id'] == '001'
        assert rolled_back['age'] == 25
        assert '_rollback_metadata' in rolled_back
        assert rolled_back['_rollback_metadata']['checkpoint'] == checkpoint
    
    def test_manual_review_queue_operations(self, resolver):
        """Test manual review queue operations."""
        conflicts = [
            {'id': 'conflict_1', 'type': ConflictType.TYPE_CHANGE, 'key': 'age'},
            {'id': 'conflict_2', 'type': ConflictType.SCHEMA_CHANGE, 'key': 'schema'}
        ]
        
        # Resolve with manual review strategy
        resolver.resolve_conflicts(conflicts, ResolutionStrategy.MANUAL_REVIEW)
        
        # Check queue
        queue = resolver.get_manual_review_queue()
        assert len(queue) == 2
        
        # Manually resolve one conflict
        resolution = {'resolved_value': 26, 'decision': 'keep_remote'}
        success = resolver.resolve_manual_conflict('conflict_1', resolution)
        assert success
        
        # Queue should be smaller
        queue = resolver.get_manual_review_queue()
        assert len(queue) == 1
        
        # Try to resolve non-existent conflict
        success = resolver.resolve_manual_conflict('conflict_999', resolution)
        assert not success
    
    def test_conflict_statistics(self, resolver, sample_local_data, sample_remote_data):
        """Test conflict statistics generation."""
        conflicts = resolver.detect_conflicts(sample_local_data, sample_remote_data)
        resolver.resolve_conflicts(conflicts)
        
        stats = resolver.get_conflict_statistics()
        
        assert 'total_conflicts' in stats
        assert 'resolved_automatically' in stats
        assert 'resolved_manually' in stats
        assert 'pending_review' in stats
        assert 'success_rate' in stats
        assert 'conflict_types' in stats
        assert 'resolution_strategies' in stats
        
        assert isinstance(stats['success_rate'], float)
        assert 0 <= stats['success_rate'] <= 1
    
    def test_values_equivalent(self, resolver):
        """Test value equivalence checking."""
        # Test None values
        assert resolver._values_equivalent(None, None)
        assert not resolver._values_equivalent(None, 'value')
        
        # Test numeric values with tolerance
        assert resolver._values_equivalent(1.0, 1.0000000001)
        assert not resolver._values_equivalent(1.0, 2.0)
        
        # Test numpy arrays
        arr1 = np.array([1, 2, 3])
        arr2 = np.array([1, 2, 3])
        arr3 = np.array([1, 2, 4])
        
        assert resolver._values_equivalent(arr1, arr2)
        assert not resolver._values_equivalent(arr1, arr3)
        
        # Test pandas DataFrames
        df1 = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
        df2 = pd.DataFrame({'a': [1, 2], 'b': [3, 4]})
        df3 = pd.DataFrame({'a': [1, 2], 'b': [3, 5]})
        
        assert resolver._values_equivalent(df1, df2)
        assert not resolver._values_equivalent(df1, df3)
    
    def test_generate_conflict_id(self, resolver):
        """Test conflict ID generation."""
        id1 = resolver._generate_conflict_id('key1', 'value1', 'value2')
        id2 = resolver._generate_conflict_id('key1', 'value1', 'value2')
        
        # IDs should be different due to timestamp
        assert id1 != id2
        assert len(id1) == 32  # MD5 hash length
    
    def test_merge_values(self, resolver):
        """Test value merging utility."""
        # Test dictionary merge
        dict1 = {'a': 1, 'b': 2}
        dict2 = {'b': 3, 'c': 4}
        merged = resolver._merge_values(dict1, dict2)
        
        assert merged == {'a': 1, 'b': 3, 'c': 4}
        
        # Test list merge (union)
        list1 = [1, 2, 3]
        list2 = [3, 4, 5]
        merged = resolver._merge_values(list1, list2)
        
        assert set(merged) == {1, 2, 3, 4, 5}
        
        # Test incompatible types
        merged = resolver._merge_values('string', 42)
        assert merged is None
    
    def test_select_by_quality(self, resolver):
        """Test quality-based selection."""
        conflict = {
            'local_value': 'local',
            'remote_value': 'remote',
            'metadata': {
                'local_quality': 0.8,
                'remote_quality': 0.6
            }
        }
        
        # Should select local due to higher quality
        selected = resolver._select_by_quality(conflict)
        assert selected == 'local'
        
        # Test with similar quality (should return None for manual review)
        conflict['metadata']['remote_quality'] = 0.81
        selected = resolver._select_by_quality(conflict)
        assert selected is None
    
    def test_compatible_type_changes(self, resolver):
        """Test type change compatibility checking."""
        # Compatible changes
        assert resolver._is_compatible_type_change(int, float)
        assert resolver._is_compatible_type_change(float, int)
        assert resolver._is_compatible_type_change(str, bytes)
        assert resolver._is_compatible_type_change(list, tuple)
        
        # Incompatible changes
        assert not resolver._is_compatible_type_change(int, str)
        assert not resolver._is_compatible_type_change(dict, list)
    
    def test_error_handling(self, resolver):
        """Test error handling in conflict resolution."""
        # Create a conflict that will cause an error during resolution
        conflicts = [{
            'id': 'error_conflict',
            'type': ConflictType.VALUE_MISMATCH,
            'key': 'test',
            'local_value': 'local',
            'remote_value': 'remote'
        }]
        
        # Mock the resolution method to raise an exception
        with patch.object(resolver, '_apply_resolution', side_effect=Exception("Test error")):
            results = resolver.resolve_conflicts(conflicts)
            
            # Should handle the error gracefully
            assert len(results['failed']) == 1
            assert results['failed'][0]['error'] == "Test error"
    
    def test_conflict_history_tracking(self, resolver, sample_local_data, sample_remote_data):
        """Test that conflict history is properly tracked."""
        initial_history_length = len(resolver.conflict_history)
        
        conflicts = resolver.detect_conflicts(sample_local_data, sample_remote_data)
        resolver.resolve_conflicts(conflicts)
        
        # History should have one more entry
        assert len(resolver.conflict_history) == initial_history_length + 1
        
        # History entry should contain results
        latest_entry = resolver.conflict_history[-1]
        assert 'timestamp' in latest_entry
        assert 'results' in latest_entry
        assert 'statistics' in latest_entry['results']


class TestConflictTypes:
    """Test ConflictType enum."""
    
    def test_conflict_type_values(self):
        """Test that all conflict types have correct values."""
        assert ConflictType.VALUE_MISMATCH.value == "value_mismatch"
        assert ConflictType.TYPE_CHANGE.value == "type_change"
        assert ConflictType.SCHEMA_CHANGE.value == "schema_change"
        assert ConflictType.DELETION_CONFLICT.value == "deletion_conflict"
        assert ConflictType.DUPLICATE_KEY.value == "duplicate_key"
        assert ConflictType.VERSION_CONFLICT.value == "version_conflict"
        assert ConflictType.MERGE_CONFLICT.value == "merge_conflict"


class TestResolutionStrategy:
    """Test ResolutionStrategy enum."""
    
    def test_resolution_strategy_values(self):
        """Test that all resolution strategies have correct values."""
        assert ResolutionStrategy.KEEP_NEWEST.value == "keep_newest"
        assert ResolutionStrategy.KEEP_OLDEST.value == "keep_oldest"
        assert ResolutionStrategy.KEEP_LOCAL.value == "keep_local"
        assert ResolutionStrategy.KEEP_REMOTE.value == "keep_remote"
        assert ResolutionStrategy.MERGE_VALUES.value == "merge_values"
        assert ResolutionStrategy.MANUAL_REVIEW.value == "manual_review"
        assert ResolutionStrategy.USE_QUALITY_SCORE.value == "use_quality_score"
        assert ResolutionStrategy.VOTING_CONSENSUS.value == "voting_consensus"


@pytest.mark.integration
class TestConflictResolverIntegration:
    """Integration tests for ConflictResolver."""
    
    def test_end_to_end_conflict_resolution(self):
        """Test complete conflict resolution workflow."""
        resolver = ConflictResolver(quality_threshold=0.6)
        
        # Create realistic dataset conflict scenario
        local_data = {
            'participant_id': 'sub-001',
            'age': 25,
            'sex': 'M',
            'handedness': 'R',
            'diagnosis': 'HC',
            'scan_date': '2023-01-15',
            'quality_score': 0.85
        }
        
        remote_data = {
            'participant_id': 'sub-001',
            'age': 26,  # Age updated
            'sex': 'M',
            'handedness': 'R',
            'diagnosis': 'MDD',  # Diagnosis changed
            'scan_date': '2023-06-20',  # New scan
            'quality_score': 0.92,  # Higher quality
            'medication': 'none'  # New field
        }
        
        metadata = {
            'local_timestamp': '2023-01-15T10:00:00',
            'remote_timestamp': '2023-06-20T14:30:00',
            'local_quality': 0.85,
            'remote_quality': 0.92,
            'local_version': '1.0',
            'remote_version': '2.0'
        }
        
        # Detect conflicts
        conflicts = resolver.detect_conflicts(local_data, remote_data, metadata)
        assert len(conflicts) > 0
        
        # Resolve conflicts using quality-based strategy
        resolution_results = resolver.resolve_conflicts(
            conflicts, 
            ResolutionStrategy.USE_QUALITY_SCORE
        )
        
        # Merge data
        merged_data = resolver.merge_data(local_data, remote_data, resolution_results)
        
        # Validate results
        assert resolver.validate_resolution(local_data, merged_data)
        assert 'medication' in merged_data  # New field should be added
        assert '_merge_metadata' in merged_data
        
        # Check statistics
        stats = resolver.get_conflict_statistics()
        assert stats['total_conflicts'] > 0
        assert stats['success_rate'] > 0