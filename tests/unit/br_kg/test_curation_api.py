"""Unit tests for curation API."""

from datetime import datetime

import pytest

from brain_researcher.services.br_kg.api.curation import (
    BatchOperation,
    BatchRequest,
    CurationItem,
    CurationWorkflow,
    ValidationRequest,
    ValidationStatus,
)


class TestCurationWorkflow:
    """Test suite for curation workflow."""

    @pytest.fixture
    def workflow(self):
        """Create workflow instance."""
        return CurationWorkflow()

    @pytest.fixture
    def sample_item(self):
        """Create sample curation item."""
        return CurationItem(
            type="concept",
            data={"name": "test_concept", "definition": "A test concept"},
            submitted_by="test_user",
            confidence_score=0.85,
        )

    def test_submit_for_review(self, workflow, sample_item):
        """Test submitting item for review."""
        item_id = workflow.submit_for_review(sample_item)

        assert item_id == sample_item.id
        assert item_id in workflow.items
        assert workflow.items[item_id].status == ValidationStatus.PENDING

    def test_validate_item_approve(self, workflow, sample_item):
        """Test approving an item."""
        workflow.submit_for_review(sample_item)

        request = ValidationRequest(
            item_id=sample_item.id,
            action=ValidationStatus.APPROVED,
            comment="Looks good",
            confidence=0.95,
        )

        validated = workflow.validate_item(request, "reviewer1")

        assert validated.status == ValidationStatus.APPROVED
        assert validated.reviewed_by == "reviewer1"
        assert validated.reviewed_at is not None
        assert "Looks good" in validated.comments[0]
        assert validated.confidence_score == 0.95

    def test_validate_item_reject(self, workflow, sample_item):
        """Test rejecting an item."""
        workflow.submit_for_review(sample_item)

        request = ValidationRequest(
            item_id=sample_item.id,
            action=ValidationStatus.REJECTED,
            comment="Incorrect definition",
        )

        validated = workflow.validate_item(request, "reviewer2")

        assert validated.status == ValidationStatus.REJECTED
        assert "Incorrect definition" in validated.comments[0]

    def test_batch_approve(self, workflow):
        """Test batch approval."""
        # Submit multiple items
        items = []
        for i in range(5):
            item = CurationItem(
                type="concept", data={"name": f"concept_{i}"}, submitted_by="test_user"
            )
            workflow.submit_for_review(item)
            items.append(item)

        # Batch approve
        request = BatchRequest(
            item_ids=[item.id for item in items], operation=BatchOperation.APPROVE
        )

        results = workflow.batch_operation(request, "batch_reviewer")

        assert len(results["success"]) == 5
        assert len(results["failed"]) == 0

        # Check all items are approved
        for item in items:
            assert workflow.items[item.id].status == ValidationStatus.APPROVED

    def test_batch_tag(self, workflow, sample_item):
        """Test batch tagging."""
        workflow.submit_for_review(sample_item)

        request = BatchRequest(
            item_ids=[sample_item.id],
            operation=BatchOperation.TAG,
            params={"tags": ["important", "reviewed"]},
        )

        results = workflow.batch_operation(request, "tagger")

        assert len(results["success"]) == 1
        assert "important" in workflow.items[sample_item.id].tags
        assert "reviewed" in workflow.items[sample_item.id].tags

    def test_batch_merge(self, workflow):
        """Test batch merge operation."""
        # Create two items
        item1 = CurationItem(
            type="concept",
            data={"name": "concept1", "prop1": "value1"},
            submitted_by="user1",
        )
        item2 = CurationItem(
            type="concept",
            data={"name": "concept2", "prop2": "value2"},
            submitted_by="user2",
        )

        workflow.submit_for_review(item1)
        workflow.submit_for_review(item2)

        # Merge item1 into item2
        request = BatchRequest(
            item_ids=[item1.id],
            operation=BatchOperation.MERGE,
            params={"target_id": item2.id},
        )

        results = workflow.batch_operation(request, "merger")

        assert len(results["success"]) == 1

        # Check merge results
        assert workflow.items[item1.id].status == ValidationStatus.REJECTED
        assert "Merged into" in workflow.items[item1.id].comments[-1]
        assert "prop1" in workflow.items[item2.id].data
        assert "prop2" in workflow.items[item2.id].data

    def test_review_queue_filtering(self, workflow):
        """Test review queue filtering."""
        # Submit items with different confidence scores
        high_conf = CurationItem(
            type="concept",
            data={"name": "high_conf"},
            submitted_by="user",
            confidence_score=0.9,
        )
        low_conf = CurationItem(
            type="concept",
            data={"name": "low_conf"},
            submitted_by="user",
            confidence_score=0.3,
        )

        workflow.submit_for_review(high_conf)
        workflow.submit_for_review(low_conf)

        # Get high confidence queue
        high_queue = workflow.get_review_queue("high_confidence")
        assert len(high_queue) == 1
        assert high_queue[0].id == high_conf.id

        # Get low confidence queue
        low_queue = workflow.get_review_queue("low_confidence")
        assert len(low_queue) == 1
        assert low_queue[0].id == low_conf.id

    def test_statistics(self, workflow):
        """Test statistics generation."""
        # Submit and process items
        for i in range(10):
            item = CurationItem(
                type="concept" if i < 5 else "relation",
                data={"name": f"item_{i}"},
                submitted_by="user",
                confidence_score=0.5 + i * 0.05,
            )
            workflow.submit_for_review(item)

            if i < 3:
                request = ValidationRequest(
                    item_id=item.id, action=ValidationStatus.APPROVED
                )
                workflow.validate_item(request, "reviewer")

        stats = workflow.get_statistics()

        assert stats["total_items"] == 10
        assert stats["by_status"]["approved"] == 3
        assert stats["by_status"]["pending"] == 7
        assert stats["by_type"]["concept"] == 5
        assert stats["by_type"]["relation"] == 5
        assert stats["review_rate"] == 0.3  # 3/10
        assert 0.5 <= stats["average_confidence"] <= 1.0
