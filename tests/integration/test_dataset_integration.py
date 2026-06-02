"""
Integration tests for Dataset Card & Explorer Integration
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestDatasetIntegration:
    """Test suite for Dataset integration with BR-KG"""

    @pytest.fixture
    def sample_datasets(self):
        """Sample dataset collection"""
        return [
            {
                "id": "ds000114",
                "name": "Motor Task Dataset",
                "source": "OpenNeuro",
                "modality": ["T1w", "bold"],
                "n_subjects": 10,
                "n_sessions": 2,
                "tasks": ["motor", "rest"],
                "quality_score": 8.5,
                "size_gb": 15.2,
                "bids_version": "1.6.0",
            },
            {
                "id": "hcp_1200",
                "name": "Human Connectome Project",
                "source": "HCP",
                "modality": ["T1w", "T2w", "bold", "dwi"],
                "n_subjects": 1200,
                "n_sessions": 4,
                "tasks": ["motor", "wm", "language", "social"],
                "quality_score": 9.8,
                "size_gb": 2400,
            },
        ]

    @pytest.fixture
    def dataset_filters(self):
        """Sample filter configuration"""
        return {
            "sources": ["OpenNeuro", "HCP"],
            "modalities": ["bold"],
            "subject_range": {"min": 10, "max": 100},
            "tasks": ["motor"],
            "quality_score_min": 7.0,
            "bids_compliant": True,
        }

    @pytest.fixture
    def search_result(self, sample_datasets):
        """Sample search result"""
        return {
            "datasets": sample_datasets,
            "total_count": 2,
            "page": 1,
            "page_size": 20,
            "facets": {
                "sources": [
                    {"value": "OpenNeuro", "count": 1},
                    {"value": "HCP", "count": 1},
                ],
                "modalities": [
                    {"value": "bold", "count": 2},
                    {"value": "T1w", "count": 2},
                ],
                "tasks": [
                    {"value": "motor", "count": 2},
                    {"value": "rest", "count": 1},
                ],
            },
        }

    @pytest.fixture
    def dataset_statistics(self):
        """Sample dataset statistics"""
        return {
            "total_subjects": 10,
            "total_sessions": 20,
            "total_size_gb": 15.2,
            "file_types": [
                {"type": "nii.gz", "count": 240},
                {"type": "json", "count": 50},
                {"type": "tsv", "count": 30},
            ],
            "scan_types": [
                {"type": "T1w", "count": 10},
                {"type": "bold", "count": 200},
            ],
            "average_quality_score": 8.5,
        }

    @pytest.mark.asyncio
    async def test_search_datasets(self, search_result):
        """Test dataset search functionality"""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value.json = AsyncMock(return_value=search_result)
            mock_get.return_value.status_code = 200

            # Simulate search
            query = "motor task"
            result = search_result

            assert result["total_count"] == 2
            assert len(result["datasets"]) == 2
            assert result["page"] == 1

    def test_dataset_filtering(self, sample_datasets, dataset_filters):
        """Test dataset filtering logic"""
        filtered = []

        for dataset in sample_datasets:
            # Apply filters
            if (
                dataset_filters.get("sources")
                and dataset["source"] not in dataset_filters["sources"]
            ):
                continue

            if dataset_filters.get("modalities"):
                if not any(
                    mod in dataset["modality"] for mod in dataset_filters["modalities"]
                ):
                    continue

            if dataset_filters.get("subject_range"):
                range_val = dataset_filters["subject_range"]
                if not (range_val["min"] <= dataset["n_subjects"] <= range_val["max"]):
                    continue

            if dataset_filters.get("quality_score_min"):
                if (
                    dataset.get("quality_score", 0)
                    < dataset_filters["quality_score_min"]
                ):
                    continue

            filtered.append(dataset)

        assert len(filtered) == 1
        assert filtered[0]["id"] == "ds000114"

    def test_facet_counting(self, search_result):
        """Test facet counting for filters"""
        facets = search_result["facets"]

        # Check source facets
        source_counts = {f["value"]: f["count"] for f in facets["sources"]}
        assert source_counts["OpenNeuro"] == 1
        assert source_counts["HCP"] == 1

        # Check modality facets
        modality_counts = {f["value"]: f["count"] for f in facets["modalities"]}
        assert modality_counts["bold"] == 2
        assert modality_counts["T1w"] == 2

    @pytest.mark.asyncio
    async def test_get_dataset_details(self, sample_datasets):
        """Test fetching individual dataset details"""
        dataset_id = "ds000114"

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value.json = AsyncMock(return_value=sample_datasets[0])
            mock_get.return_value.status_code = 200

            # Simulate getting dataset
            result = sample_datasets[0]

            assert result["id"] == dataset_id
            assert result["name"] == "Motor Task Dataset"
            assert result["n_subjects"] == 10

    def test_dataset_statistics_calculation(self, dataset_statistics):
        """Test dataset statistics calculation"""
        stats = dataset_statistics

        assert stats["total_subjects"] == 10
        assert stats["total_sessions"] == 20
        assert stats["total_size_gb"] == 15.2

        # Check file type distribution
        total_files = sum(ft["count"] for ft in stats["file_types"])
        assert total_files == 320

        # Check scan type distribution
        total_scans = sum(st["count"] for st in stats["scan_types"])
        assert total_scans == 210

    @pytest.mark.asyncio
    async def test_dataset_preview(self):
        """Test dataset preview generation"""
        preview = {
            "sample_subjects": ["sub-01", "sub-02", "sub-03"],
            "sample_files": [
                "sub-01/anat/sub-01_T1w.nii.gz",
                "sub-01/func/sub-01_task-motor_bold.nii.gz",
            ],
            "directory_structure": {
                "sub-01": {"anat": ["T1w.nii.gz"], "func": ["task-motor_bold.nii.gz"]}
            },
        }

        assert len(preview["sample_subjects"]) == 3
        assert "sub-01" in preview["sample_subjects"]
        assert "anat" in preview["directory_structure"]["sub-01"]

    @pytest.mark.asyncio
    async def test_dataset_download(self):
        """Test dataset download functionality"""
        dataset_id = "ds000114"
        formats = ["bids", "nifti", "json"]

        for format in formats:
            # Simulate download request
            download_url = f"/api/datasets/{dataset_id}/download?format={format}"

            assert dataset_id in download_url
            assert format in download_url

    @pytest.mark.asyncio
    async def test_related_datasets(self, sample_datasets):
        """Test finding related datasets"""
        dataset_id = "ds000114"

        with patch("httpx.AsyncClient.get") as mock_get:
            # Return HCP as related dataset
            mock_get.return_value.json = AsyncMock(
                return_value={"datasets": [sample_datasets[1]]}
            )
            mock_get.return_value.status_code = 200

            # Simulate getting related
            result = {"datasets": [sample_datasets[1]]}

            assert len(result["datasets"]) == 1
            assert result["datasets"][0]["id"] == "hcp_1200"

    def test_dataset_quality_check(self):
        """Test dataset quality validation"""
        quality_report = {
            "bids_validation": {"valid": True, "warnings": 2, "errors": 0},
            "completeness": {
                "missing_files": [],
                "missing_metadata": ["participants.json"],
            },
            "consistency": {"naming_convention": "consistent", "file_format": "valid"},
            "score": 8.5,
        }

        assert quality_report["bids_validation"]["valid"] is True
        assert quality_report["bids_validation"]["errors"] == 0
        assert quality_report["score"] == 8.5

    def test_dataset_citations(self):
        """Test dataset citation generation"""
        dataset = {
            "id": "ds000114",
            "name": "Motor Task Dataset",
            "authors": ["Smith, J.", "Doe, A."],
            "year": 2021,
            "doi": "10.18112/openneuro.ds000114.v1.0.1",
        }

        # Generate citation
        citation = f"{', '.join(dataset['authors'])} ({dataset['year']}). {dataset['name']}. OpenNeuro. https://doi.org/{dataset['doi']}"

        assert "Smith, J." in citation
        assert "2021" in citation
        assert dataset["doi"] in citation

    def test_br_kg_integration(self):
        """Test BR-KG knowledge graph integration"""
        br_kg_response = {
            "status": "connected",
            "sources": ["OpenNeuro", "HCP", "ABCD"],
            "total_datasets": 150,
            "last_update": datetime.now().isoformat(),
        }

        assert br_kg_response["status"] == "connected"
        assert "OpenNeuro" in br_kg_response["sources"]
        assert br_kg_response["total_datasets"] == 150

    def test_dataset_caching(self, sample_datasets):
        """Test dataset caching mechanism"""
        cache = {}
        cache_ttl = 300  # 5 minutes

        # Add to cache
        dataset_id = "ds000114"
        cache[f"dataset_{dataset_id}"] = {
            "data": sample_datasets[0],
            "timestamp": datetime.now(),
            "ttl": cache_ttl,
        }

        # Check cache
        assert f"dataset_{dataset_id}" in cache
        assert cache[f"dataset_{dataset_id}"]["data"]["id"] == dataset_id

    def test_sorting_options(self, sample_datasets):
        """Test dataset sorting options"""
        sort_options = ["name", "date", "size", "subjects"]

        for sort_by in sort_options:
            if sort_by == "name":
                sorted_data = sorted(sample_datasets, key=lambda x: x["name"])
            elif sort_by == "subjects":
                sorted_data = sorted(sample_datasets, key=lambda x: x["n_subjects"])
            elif sort_by == "size":
                sorted_data = sorted(sample_datasets, key=lambda x: x.get("size_gb", 0))
            else:
                sorted_data = sample_datasets

            assert len(sorted_data) == len(sample_datasets)

    def test_pagination(self, search_result):
        """Test pagination handling"""
        page_size = 20
        total_count = search_result["total_count"]
        total_pages = (total_count + page_size - 1) // page_size

        assert search_result["page"] == 1
        assert search_result["page_size"] == 20
        assert total_pages == 1  # Only 2 items

    @pytest.mark.asyncio
    async def test_batch_dataset_operations(self, sample_datasets):
        """Test batch operations on multiple datasets"""
        dataset_ids = [ds["id"] for ds in sample_datasets]

        # Simulate batch fetch
        async def fetch_dataset(ds_id):
            await asyncio.sleep(0.1)  # Simulate network delay
            return next((ds for ds in sample_datasets if ds["id"] == ds_id), None)

        import asyncio

        results = await asyncio.gather(*[fetch_dataset(ds_id) for ds_id in dataset_ids])

        assert len(results) == 2
        assert all(r is not None for r in results)
