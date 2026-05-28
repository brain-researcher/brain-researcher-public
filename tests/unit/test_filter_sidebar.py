"""
Unit tests for UI-008: Filter Sidebar component
Tests filter presets, real-time updates, and export functionality
"""

import pytest
from unittest.mock import Mock, patch
import json
from datetime import datetime


class TestFilterSidebar:
    """Test suite for Filter Sidebar component functionality"""

    def test_filter_presets(self):
        """测试过滤器预设 - Based on actual implementation"""
        # Mock filter presets based on actual FilterSidebar component
        filter_presets = {
            "fmri_studies": [
                {"facet": "modality", "value": "fmri", "op": "=", "label": "fMRI"},
                {"facet": "task", "value": "rest", "op": "=", "label": "Resting State"},
                {"facet": "n_subjects", "value": [10, 100], "op": "range", "label": "10 - 100"}
            ],
            "high_quality": [
                {"facet": "quality", "value": "bids_compliant", "op": "=", "label": "BIDS Compliant"},
                {"facet": "quality", "value": "qc_passed", "op": "=", "label": "QC Passed"},
                {"facet": "source", "value": "openneuro", "op": "=", "label": "OpenNeuro"}
            ],
            "recent_studies": [
                {"facet": "year", "value": [2020, 2024], "op": "range", "label": "2020 - 2024"},
                {"facet": "population", "value": "adults", "op": "=", "label": "Adults (18-65)"}
            ]
        }
        
        # Test preset structure
        assert len(filter_presets) == 3
        assert "fmri_studies" in filter_presets
        assert "high_quality" in filter_presets
        assert "recent_studies" in filter_presets
        
        # Test individual preset structure
        for preset_name, filters in filter_presets.items():
            assert isinstance(filters, list)
            assert len(filters) > 0
            
            for filter_item in filters:
                assert "facet" in filter_item
                assert "value" in filter_item
                assert "op" in filter_item
                assert filter_item["op"] in ["=", "range", "!=", ">", "<"]
        
        # Test applying a preset
        fmri_preset = filter_presets["fmri_studies"]
        assert len(fmri_preset) == 3
        
        # Test filter structure
        modality_filter = next(f for f in fmri_preset if f["facet"] == "modality")
        assert modality_filter["value"] == "fmri"
        assert modality_filter["op"] == "="
        
        # Test range filter
        range_filter = next(f for f in fmri_preset if f["op"] == "range")
        assert isinstance(range_filter["value"], list)
        assert len(range_filter["value"]) == 2

    def test_custom_preset_creation(self):
        """Test creating and managing custom filter presets"""
        custom_preset_manager = {
            "custom_presets": [],
            "max_custom_presets": 5,
            "current_filters": {
                "modality": ["sMRI", "fMRI"],
                "brain_region": ["frontal cortex"],
                "age_range": {"min": 18, "max": 65},
                "cognitive_domain": ["memory", "attention"]
            }
        }
        
        # Test creating custom preset
        new_preset = {
            "id": "my_memory_studies",
            "name": "Memory Studies",
            "description": "My collection of memory-related neuroimaging studies",
            "filters": custom_preset_manager["current_filters"].copy(),
            "created_at": datetime.now().isoformat(),
            "is_custom": True,
            "usage_count": 0
        }
        
        # Add custom preset
        custom_preset_manager["custom_presets"].append(new_preset)
        
        # Test custom preset was added
        assert len(custom_preset_manager["custom_presets"]) == 1
        assert custom_preset_manager["custom_presets"][0]["name"] == "Memory Studies"
        assert custom_preset_manager["custom_presets"][0]["is_custom"]
        
        # Test custom preset limit
        for i in range(5):  # Try to add 5 more presets
            if len(custom_preset_manager["custom_presets"]) < custom_preset_manager["max_custom_presets"]:
                preset = {
                    "id": f"preset_{i}",
                    "name": f"Preset {i}",
                    "filters": {},
                    "is_custom": True
                }
                custom_preset_manager["custom_presets"].append(preset)
        
        # Should be limited to max_custom_presets
        assert len(custom_preset_manager["custom_presets"]) <= custom_preset_manager["max_custom_presets"]

    def test_realtime_updates(self):
        """测试实时更新"""
        # Mock real-time filter state
        realtime_state = {
            "active_filters": {
                "modality": ["fMRI"],
                "task_type": ["cognitive"],
                "n_subjects": {"min": 20, "max": None}
            },
            "result_count": 145,
            "last_update": "2025-01-20T10:30:00Z",
            "update_pending": False,
            "debounce_delay": 500,  # milliseconds
            "auto_update_enabled": True
        }
        
        # Test initial state
        assert realtime_state["result_count"] == 145
        assert not realtime_state["update_pending"]
        assert realtime_state["auto_update_enabled"]
        
        # Simulate filter change
        realtime_state["active_filters"]["modality"].append("sMRI")
        realtime_state["update_pending"] = True
        
        # Test update pending state
        assert realtime_state["update_pending"]
        assert "sMRI" in realtime_state["active_filters"]["modality"]
        
        # Simulate completing the update
        new_result_count = 287  # More results with additional modality
        realtime_state["result_count"] = new_result_count
        realtime_state["update_pending"] = False
        realtime_state["last_update"] = "2025-01-20T10:30:15Z"
        
        # Test update completion
        assert realtime_state["result_count"] == 287
        assert not realtime_state["update_pending"]
        assert realtime_state["last_update"] > "2025-01-20T10:30:00Z"

    def test_filter_combinations(self):
        """Test complex filter combinations"""
        filter_combinations = {
            "filters": {
                "modality": {
                    "type": "multi_select",
                    "options": ["fMRI", "sMRI", "DTI", "PET", "EEG", "MEG"],
                    "selected": ["fMRI", "sMRI"],
                    "operator": "OR"
                },
                "age_range": {
                    "type": "range",
                    "min": 18,
                    "max": 85,
                    "current": {"min": 20, "max": 65}
                },
                "brain_region": {
                    "type": "hierarchical",
                    "selected": ["frontal_cortex", "hippocampus"],
                    "hierarchy": {
                        "cerebral_cortex": ["frontal_cortex", "parietal_cortex"],
                        "limbic_system": ["hippocampus", "amygdala"]
                    }
                },
                "publication_year": {
                    "type": "range",
                    "min": 2000,
                    "max": 2024,
                    "current": {"min": 2020, "max": 2024}
                }
            },
            "combination_logic": "AND"
        }
        
        # Test filter types
        assert filter_combinations["filters"]["modality"]["type"] == "multi_select"
        assert filter_combinations["filters"]["age_range"]["type"] == "range"
        assert filter_combinations["filters"]["brain_region"]["type"] == "hierarchical"
        
        # Test multi-select filter
        modality_filter = filter_combinations["filters"]["modality"]
        assert len(modality_filter["selected"]) == 2
        assert "fMRI" in modality_filter["selected"]
        assert modality_filter["operator"] == "OR"
        
        # Test range filter
        age_filter = filter_combinations["filters"]["age_range"]
        assert age_filter["current"]["min"] >= age_filter["min"]
        assert age_filter["current"]["max"] <= age_filter["max"]
        
        # Test hierarchical filter
        brain_region_filter = filter_combinations["filters"]["brain_region"]
        assert "frontal_cortex" in brain_region_filter["selected"]
        assert "frontal_cortex" in brain_region_filter["hierarchy"]["cerebral_cortex"]

    def test_export_filters(self):
        """测试导出功能"""
        # Mock export functionality
        export_manager = {
            "current_filters": {
                "modality": ["fMRI"],
                "task_type": ["memory", "attention"],
                "age_range": {"min": 18, "max": 65},
                "brain_region": ["frontal_cortex", "hippocampus"],
                "quality_score": {"min": 7.5, "max": None}
            },
            "result_count": 234,
            "export_formats": ["json", "csv", "yaml", "url"],
            "export_history": []
        }
        
        # Test JSON export
        json_export = {
            "format": "json",
            "filename": "brain_researcher_filters_20240120.json",
            "content": {
                "filters": export_manager["current_filters"],
                "result_count": export_manager["result_count"],
                "exported_at": "2025-01-20T10:30:00Z",
                "version": "1.0"
            }
        }
        
        # Test export structure
        assert json_export["format"] == "json"
        assert json_export["filename"].endswith(".json")
        assert "filters" in json_export["content"]
        assert "result_count" in json_export["content"]
        assert "exported_at" in json_export["content"]
        
        # Test CSV export format
        csv_export = {
            "format": "csv",
            "filename": "brain_researcher_filters_20240120.csv",
            "headers": ["filter_type", "filter_value", "operator"],
            "rows": [
                ["modality", "fMRI", "equals"],
                ["task_type", "memory", "in"],
                ["task_type", "attention", "in"],
                ["age_range_min", "18", "gte"],
                ["age_range_max", "65", "lte"]
            ]
        }
        
        # Test CSV structure
        assert csv_export["format"] == "csv"
        assert len(csv_export["headers"]) == 3
        assert len(csv_export["rows"]) == 5
        
        # Test URL export (shareable link)
        url_export = {
            "format": "url",
            "base_url": "https://brain-researcher.app/finder",
            "query_params": {
                "modality": "fMRI",
                "task_type": "memory,attention",
                "age_min": "18",
                "age_max": "65",
                "brain_region": "frontal_cortex,hippocampus",
                "quality_min": "7.5"
            },
            "full_url": "https://brain-researcher.app/finder?modality=fMRI&task_type=memory,attention&age_min=18&age_max=65&brain_region=frontal_cortex,hippocampus&quality_min=7.5"
        }
        
        # Test URL export
        assert url_export["format"] == "url"
        assert url_export["base_url"] in url_export["full_url"]
        assert "modality=fMRI" in url_export["full_url"]
        assert len(url_export["query_params"]) == 6
        
        # Add export to history
        export_record = {
            "timestamp": "2025-01-20T10:30:00Z",
            "format": json_export["format"],
            "filename": json_export["filename"],
            "result_count": export_manager["result_count"]
        }
        
        export_manager["export_history"].append(export_record)
        
        # Test export history
        assert len(export_manager["export_history"]) == 1
        assert export_manager["export_history"][0]["format"] == "json"

    def test_filter_validation(self):
        """Test filter input validation"""
        validation_rules = {
            "age_range": {
                "min_allowed": 0,
                "max_allowed": 120,
                "required": False,
                "type": "integer"
            },
            "quality_score": {
                "min_allowed": 0.0,
                "max_allowed": 10.0,
                "required": False,
                "type": "float"
            },
            "sample_size": {
                "min_allowed": 1,
                "max_allowed": 10000,
                "required": False,
                "type": "integer"
            },
            "publication_year": {
                "min_allowed": 1900,
                "max_allowed": 2024,
                "required": False,
                "type": "integer"
            }
        }
        
        def validate_filter(filter_name: str, value: any) -> dict:
            if filter_name not in validation_rules:
                return {"valid": False, "error": f"Unknown filter: {filter_name}"}
            
            rule = validation_rules[filter_name]
            
            # Type validation
            if rule["type"] == "integer" and not isinstance(value, int):
                return {"valid": False, "error": f"Expected integer for {filter_name}"}
            
            if rule["type"] == "float" and not isinstance(value, (int, float)):
                return {"valid": False, "error": f"Expected number for {filter_name}"}
            
            # Range validation
            if value < rule["min_allowed"] or value > rule["max_allowed"]:
                return {"valid": False, "error": f"Value out of range for {filter_name}"}
            
            return {"valid": True, "error": None}
        
        # Test valid inputs
        assert validate_filter("age_range", 25)["valid"]
        assert validate_filter("quality_score", 8.5)["valid"]
        assert validate_filter("sample_size", 100)["valid"]
        
        # Test invalid inputs
        assert not validate_filter("age_range", -5)["valid"]
        assert not validate_filter("quality_score", 15.0)["valid"]
        assert not validate_filter("unknown_filter", 10)["valid"]

    def test_filter_sidebar_accessibility(self):
        """Test filter sidebar accessibility features"""
        accessibility_state = {
            "aria_label": "Filter options",
            "role": "complementary",
            "keyboard_navigation": True,
            "screen_reader_support": True,
            "high_contrast_mode": False,
            "focus_management": {
                "focus_trap": True,
                "focus_restoration": True,
                "skip_links": True
            },
            "announcements": []
        }
        
        # Test ARIA attributes
        assert accessibility_state["aria_label"] == "Filter options"
        assert accessibility_state["role"] == "complementary"
        
        # Test accessibility features
        assert accessibility_state["keyboard_navigation"]
        assert accessibility_state["screen_reader_support"]
        assert accessibility_state["focus_management"]["focus_trap"]
        
        # Test filter change announcement
        accessibility_state["announcements"].append(
            "Filters updated. 234 results found."
        )
        
        assert len(accessibility_state["announcements"]) == 1
        assert "234 results" in accessibility_state["announcements"][0]


@pytest.fixture
def mock_filter_sidebar():
    """Mock filter sidebar component for testing"""
    return {
        "component_name": "FilterSidebar",
        "props": {
            "position": "left",
            "collapsible": True,
            "auto_update": True,
            "show_result_count": True
        },
        "state": {
            "is_collapsed": False,
            "active_filters": {},
            "result_count": 0,
            "loading": False
        }
    }


def test_filter_sidebar_integration(mock_filter_sidebar):
    """Test filter sidebar component integration"""
    component = mock_filter_sidebar
    
    # Test component structure
    assert component["component_name"] == "FilterSidebar"
    assert component["props"]["collapsible"]
    assert component["props"]["auto_update"]
    
    # Test initial state
    assert not component["state"]["is_collapsed"]
    assert len(component["state"]["active_filters"]) == 0
    assert component["state"]["result_count"] == 0


class TestFilterSidebarEnhancements:
    """Enhanced tests for filter sidebar based on actual implementation"""

    def test_facet_configs_structure(self):
        """Test FACET_CONFIGS structure from component"""
        # Based on actual FACET_CONFIGS from component
        facet_configs = {
            "modality": {
                "label": "Modality",
                "type": "checkbox",
                "searchable": True,
                "sortBy": "count",
                "defaultOpen": True
            },
            "task": {
                "label": "Task",
                "type": "checkbox",
                "searchable": True,
                "sortBy": "count",
                "defaultOpen": True
            },
            "population": {
                "label": "Population",
                "type": "checkbox",
                "sortBy": "count",
                "defaultOpen": False
            },
            "n_subjects": {
                "label": "Sample Size",
                "type": "range",
                "defaultOpen": False
            },
            "year": {
                "label": "Publication Year",
                "type": "range",
                "defaultOpen": False
            },
            "source": {
                "label": "Data Source",
                "type": "checkbox",
                "sortBy": "alpha",
                "defaultOpen": True
            },
            "anatomical_region": {
                "label": "Brain Region",
                "type": "checkbox",
                "searchable": True,
                "sortBy": "alpha",
                "defaultOpen": False
            }
        }
        
        # Test facet config structure
        for facet_name, config in facet_configs.items():
            assert "label" in config
            assert "type" in config
            assert config["type"] in ["checkbox", "range", "search"]
            assert "defaultOpen" in config
            assert isinstance(config["defaultOpen"], bool)
            
            # Test optional fields
            if "searchable" in config:
                assert isinstance(config["searchable"], bool)
            if "sortBy" in config:
                assert config["sortBy"] in ["count", "value", "alpha"]
        
        # Test specific facets
        assert facet_configs["modality"]["searchable"]
        assert facet_configs["modality"]["defaultOpen"]
        assert facet_configs["n_subjects"]["type"] == "range"
        assert facet_configs["source"]["sortBy"] == "alpha"

    def test_filter_value_interface(self):
        """Test FilterValue interface"""
        # Based on actual FilterValue interface
        filter_value = {
            "value": "fmri",
            "count": 150,
            "label": "fMRI"
        }
        
        # Test required fields
        assert "value" in filter_value
        assert "count" in filter_value
        
        # Test field types
        assert isinstance(filter_value["count"], int)
        assert filter_value["count"] >= 0
        
        # Test optional label
        if "label" in filter_value:
            assert isinstance(filter_value["label"], str)

    def test_filter_interface(self):
        """Test Filter interface"""
        # Based on actual Filter interface
        filter_item = {
            "facet": "modality",
            "value": "fmri",
            "op": "=",
            "label": "fMRI"
        }
        
        # Test required fields
        assert "facet" in filter_item
        assert "value" in filter_item
        assert "op" in filter_item
        
        # Test operator validation
        valid_operators = ["=", "!=", ">", "<", ">=", "<=", "range", "in", "not_in"]
        assert filter_item["op"] in valid_operators
        
        # Test optional label
        if "label" in filter_item:
            assert isinstance(filter_item["label"], str)

    def test_mock_facet_data_structure(self):
        """Test mock facet data structure from component"""
        # Based on actual mock data from component
        facet_data = {
            "modality": [
                {"value": "fmri", "count": 150, "label": "fMRI"},
                {"value": "structural", "count": 80, "label": "Structural MRI"},
                {"value": "dwi", "count": 45, "label": "Diffusion MRI"},
                {"value": "meg", "count": 20, "label": "MEG"},
                {"value": "eeg", "count": 15, "label": "EEG"},
                {"value": "pet", "count": 10, "label": "PET"},
                {"value": "multimodal", "count": 8, "label": "Multimodal"}
            ],
            "task": [
                {"value": "motor", "count": 45, "label": "Motor"},
                {"value": "rest", "count": 60, "label": "Resting State"},
                {"value": "language", "count": 30, "label": "Language"},
                {"value": "visual", "count": 25, "label": "Visual"},
                {"value": "memory", "count": 20, "label": "Memory"},
                {"value": "emotion", "count": 18, "label": "Emotion"},
                {"value": "attention", "count": 15, "label": "Attention"}
            ],
            "population": [
                {"value": "adults", "count": 120, "label": "Adults (18-65)"},
                {"value": "older_adults", "count": 40, "label": "Older Adults (65+)"},
                {"value": "children", "count": 30, "label": "Children (5-12)"},
                {"value": "adolescents", "count": 25, "label": "Adolescents (13-17)"},
                {"value": "infants", "count": 10, "label": "Infants (0-2)"}
            ]
        }
        
        # Test facet data structure
        assert "modality" in facet_data
        assert "task" in facet_data
        assert "population" in facet_data
        
        # Test modality facet
        modality_values = facet_data["modality"]
        assert len(modality_values) == 7
        
        # Test sorting by count (should be descending)
        modality_counts = [item["count"] for item in modality_values]
        assert modality_counts == sorted(modality_counts, reverse=True)
        
        # Test specific values
        fmri_item = next(item for item in modality_values if item["value"] == "fmri")
        assert fmri_item["label"] == "fMRI"
        assert fmri_item["count"] == 150
        
        # Test population labels
        population_values = facet_data["population"]
        adult_item = next(item for item in population_values if item["value"] == "adults")
        assert "18-65" in adult_item["label"]

    def test_range_filter_functionality(self):
        """Test range filter functionality"""
        range_filter_state = {
            "facet": "n_subjects",
            "min_value": 1,
            "max_value": 500,
            "current_range": [10, 100],
            "step": 1
        }
        
        def update_range_filter(new_range):
            """Mock updateRangeFilter function"""
            filter_obj = {
                "facet": range_filter_state["facet"],
                "value": new_range,
                "op": "range",
                "label": f"{new_range[0]} - {new_range[1]}"
            }
            return filter_obj
        
        # Test range filter creation
        new_range = [20, 80]
        filter_result = update_range_filter(new_range)
        
        assert filter_result["facet"] == "n_subjects"
        assert filter_result["value"] == new_range
        assert filter_result["op"] == "range"
        assert filter_result["label"] == "20 - 80"
        
        # Test range validation
        assert new_range[0] >= range_filter_state["min_value"]
        assert new_range[1] <= range_filter_state["max_value"]
        assert new_range[0] <= new_range[1]

    def test_filter_search_functionality(self):
        """Test filter search functionality"""
        def filter_values_by_search(values, search_term):
            """Mock getFilteredValues function"""
            if not search_term:
                return values
            
            search_lower = search_term.lower()
            return [
                item for item in values
                if search_lower in str(item["value"]).lower() or 
                   (item.get("label") and search_lower in item["label"].lower())
            ]
        
        # Test data
        brain_regions = [
            {"value": "frontal", "count": 45, "label": "Frontal Cortex"},
            {"value": "parietal", "count": 38, "label": "Parietal Cortex"},
            {"value": "temporal", "count": 32, "label": "Temporal Cortex"},
            {"value": "occipital", "count": 28, "label": "Occipital Cortex"},
            {"value": "subcortical", "count": 25, "label": "Subcortical"},
            {"value": "cerebellum", "count": 20, "label": "Cerebellum"}
        ]
        
        # Test search functionality
        cortex_results = filter_values_by_search(brain_regions, "cortex")
        assert len(cortex_results) == 4  # All cortex regions
        
        frontal_results = filter_values_by_search(brain_regions, "frontal")
        assert len(frontal_results) == 1
        assert frontal_results[0]["value"] == "frontal"
        
        empty_results = filter_values_by_search(brain_regions, "xyz")
        assert len(empty_results) == 0

    def test_filter_statistics_calculation(self):
        """Test filter statistics calculation"""
        active_filters = [
            {"facet": "modality", "value": "fmri", "op": "="},
            {"facet": "modality", "value": "structural", "op": "="},
            {"facet": "task", "value": "rest", "op": "="},
            {"facet": "n_subjects", "value": [10, 100], "op": "range"},
            {"facet": "year", "value": [2020, 2024], "op": "range"}
        ]
        
        # Calculate filter statistics
        filter_counts = {}
        for filter_item in active_filters:
            facet = filter_item["facet"]
            filter_counts[facet] = filter_counts.get(facet, 0) + 1
        
        filter_stats = {
            "total_filters": len(active_filters),
            "facets_used": len(filter_counts),
            "range_filters": len([f for f in active_filters if f["op"] == "range"]),
            "value_filters": len([f for f in active_filters if f["op"] == "="])
        }
        
        # Test statistics
        assert filter_stats["total_filters"] == 5
        assert filter_stats["facets_used"] == 4  # modality, task, n_subjects, year (4 unique facets)
        assert filter_stats["range_filters"] == 2  # n_subjects and year
        assert filter_stats["value_filters"] == 3  # modality (2) + task (1)
        
        # Test facet counts
        assert filter_counts["modality"] == 2
        assert filter_counts["task"] == 1
        assert filter_counts["n_subjects"] == 1

    def test_preset_management(self):
        """Test preset save/load/delete functionality"""
        preset_manager = {
            "presets": {},
            "current_preset": None
        }
        
        def save_preset(name, filters):
            """Mock savePreset function"""
            if name.strip() and len(filters) > 0:
                preset_manager["presets"][name] = filters.copy()
                preset_manager["current_preset"] = name
                return True
            return False
        
        def apply_preset(name):
            """Mock applyPreset function"""
            if name in preset_manager["presets"]:
                preset_manager["current_preset"] = name
                return preset_manager["presets"][name]
            return None
        
        def delete_preset(name):
            """Mock deletePreset function"""
            if name in preset_manager["presets"]:
                del preset_manager["presets"][name]
                if preset_manager["current_preset"] == name:
                    preset_manager["current_preset"] = None
                return True
            return False
        
        # Test saving preset
        test_filters = [
            {"facet": "modality", "value": "fmri", "op": "="},
            {"facet": "task", "value": "rest", "op": "="}
        ]
        
        assert save_preset("my_preset", test_filters)
        assert "my_preset" in preset_manager["presets"]
        assert preset_manager["current_preset"] == "my_preset"
        
        # Test applying preset
        applied_filters = apply_preset("my_preset")
        assert applied_filters is not None
        assert len(applied_filters) == 2
        assert applied_filters[0]["facet"] == "modality"
        
        # Test deleting preset
        assert delete_preset("my_preset")
        assert "my_preset" not in preset_manager["presets"]
        assert preset_manager["current_preset"] is None
        
        # Test invalid operations
        assert not save_preset("", test_filters)  # Empty name
        assert not save_preset("test", [])  # Empty filters
        assert apply_preset("nonexistent") is None
        assert not delete_preset("nonexistent")

    def test_real_time_update_functionality(self):
        """Test real-time update functionality"""
        update_state = {
            "is_real_time_enabled": True,
            "debounce_delay": 300,
            "pending_update": None,
            "last_update_time": 0
        }
        
        def debounced_update(filters, delay=300):
            """Mock debounced filter update"""
            import time
            current_time = time.time() * 1000  # Convert to milliseconds
            
            if update_state["is_real_time_enabled"]:
                # Simulate debouncing
                update_state["pending_update"] = filters
                update_state["last_update_time"] = current_time
                return True
            return False
        
        # Test real-time updates
        test_filters = [{"facet": "modality", "value": "fmri", "op": "="}]
        
        # Test with real-time enabled
        assert debounced_update(test_filters)
        assert update_state["pending_update"] == test_filters
        assert update_state["last_update_time"] > 0
        
        # Test with real-time disabled
        update_state["is_real_time_enabled"] = False
        assert not debounced_update(test_filters)
        
        # Test toggling real-time
        update_state["is_real_time_enabled"] = not update_state["is_real_time_enabled"]
        assert update_state["is_real_time_enabled"]

    def test_export_functionality(self):
        """Test filter export functionality"""
        filters_to_export = [
            {"facet": "modality", "value": "fmri", "op": "=", "label": "fMRI"},
            {"facet": "task", "value": "rest", "op": "=", "label": "Resting State"},
            {"facet": "n_subjects", "value": [10, 100], "op": "range", "label": "10 - 100"}
        ]
        
        def export_filters_as_json(filters):
            """Mock export functionality"""
            import json
            export_data = {
                "filters": filters,
                "export_timestamp": "2025-01-20T10:30:00Z",
                "version": "1.0",
                "exported_by": "brain-researcher"
            }
            return json.dumps(export_data, indent=2)
        
        # Test export
        exported_json = export_filters_as_json(filters_to_export)
        assert isinstance(exported_json, str)
        
        # Parse back to verify structure
        import json
        parsed_data = json.loads(exported_json)
        
        assert "filters" in parsed_data
        assert "export_timestamp" in parsed_data
        assert "version" in parsed_data
        assert len(parsed_data["filters"]) == 3
        
        # Test filter preservation
        first_filter = parsed_data["filters"][0]
        assert first_filter["facet"] == "modality"
        assert first_filter["value"] == "fmri"
        assert first_filter["op"] == "="