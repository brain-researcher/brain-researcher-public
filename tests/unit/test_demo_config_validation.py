"""
Unit tests for demo configuration and path validation

Tests that:
1. demo_map.yaml is valid and loads correctly
2. All configured demo paths exist on disk
3. Demo artifacts are readable
4. Path validation function works correctly
5. Broken symlinks are handled gracefully
"""

import pytest
from pathlib import Path
import yaml

from brain_researcher.services.orchestrator import demo_endpoints


class TestDemoMapConfig:
    """Test demo_map.yaml configuration loading"""

    def test_demo_map_yaml_exists(self):
        """Test that demo_map.yaml file exists"""
        config_path = demo_endpoints.CONFIG_PATH
        assert config_path.exists(), f"demo_map.yaml not found at {config_path}"

    def test_demo_map_yaml_valid(self):
        """Test that demo_map.yaml is valid YAML"""
        try:
            with open(demo_endpoints.CONFIG_PATH, 'r') as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            pytest.fail(f"Invalid YAML in demo_map.yaml: {e}")

        assert config is not None
        assert "demos" in config
        assert isinstance(config["demos"], dict)

    def test_all_demos_loaded(self):
        """Test that DEMO_CONFIG contains expected demos"""
        config = demo_endpoints.DEMO_CONFIG

        assert len(config) > 0, "No demos loaded from config"

        # Expected demo IDs from demo_map.yaml
        expected_demos = {
            "glm_motor",
            "connectivity_dmn",
            "dmn_default",
            "group_analysis",
            "smart_preprocessing",
            "meta_analysis"
        }

        loaded_demos = set(config.keys())
        assert expected_demos.issubset(loaded_demos), \
            f"Missing demos: {expected_demos - loaded_demos}"

    def test_demo_config_structure(self):
        """Test that each demo has required fields"""
        config = demo_endpoints.DEMO_CONFIG

        for demo_id, demo_info in config.items():
            # Required fields
            assert "output_path" in demo_info, \
                f"Demo '{demo_id}' missing 'output_path'"
            assert "title" in demo_info, \
                f"Demo '{demo_id}' missing 'title'"
            assert "description" in demo_info, \
                f"Demo '{demo_id}' missing 'description'"

            # Validate types
            assert isinstance(demo_info["output_path"], str)
            assert isinstance(demo_info["title"], str)
            assert isinstance(demo_info["description"], str)
            assert len(demo_info["title"]) > 0
            assert len(demo_info["description"]) > 0


class TestDemoPathValidation:
    """Test demo path existence and accessibility"""

    def test_all_demo_paths_exist(self):
        """Test that all configured demo paths exist"""
        config = demo_endpoints.DEMO_CONFIG
        data_root = demo_endpoints.DATA_ROOT

        for demo_id, demo_info in config.items():
            output_path = data_root / demo_info["output_path"]

            assert output_path.exists() or output_path.is_symlink(), \
                f"Demo '{demo_id}' path does not exist: {output_path}"

    def test_all_demo_paths_readable(self):
        """Test that all demo paths are readable"""
        config = demo_endpoints.DEMO_CONFIG
        data_root = demo_endpoints.DATA_ROOT

        for demo_id, demo_info in config.items():
            output_path = data_root / demo_info["output_path"]

            if output_path.exists():
                # Try to list directory contents
                try:
                    list(output_path.iterdir())
                except (PermissionError, OSError) as e:
                    pytest.fail(
                        f"Demo '{demo_id}' path exists but not readable: {output_path}\n"
                        f"Error: {e}"
                    )

    def test_validate_demo_paths_function(self):
        """Test the validate_demo_paths() function"""
        validation_results = demo_endpoints.validate_demo_paths()

        assert isinstance(validation_results, dict)
        assert len(validation_results) > 0

        # Check that all demos are validated
        config = demo_endpoints.DEMO_CONFIG
        for demo_id in config.keys():
            assert demo_id in validation_results, \
                f"Demo '{demo_id}' not in validation results"

            result = validation_results[demo_id]

            # Validate result structure
            assert "exists" in result
            assert "readable" in result
            assert "path" in result
            assert "error" in result

            # Validate types
            assert isinstance(result["exists"], bool)
            assert isinstance(result["readable"], bool)
            assert isinstance(result["path"], str)

    def test_validation_results_stored_on_startup(self):
        """Test that PATH_VALIDATION_RESULTS is populated on startup"""
        assert hasattr(demo_endpoints, 'PATH_VALIDATION_RESULTS')
        assert isinstance(demo_endpoints.PATH_VALIDATION_RESULTS, dict)
        assert len(demo_endpoints.PATH_VALIDATION_RESULTS) > 0


class TestDemoArtifacts:
    """Test that demo artifacts are accessible"""

    @pytest.mark.parametrize("demo_id", [
        "glm_motor",
        "connectivity_dmn",
        "group_analysis"
    ])
    def test_demo_has_artifacts(self, demo_id):
        """Test that demos have at least some artifacts"""
        config = demo_endpoints.DEMO_CONFIG
        data_root = demo_endpoints.DATA_ROOT

        if demo_id not in config:
            pytest.skip(f"Demo '{demo_id}' not in config")

        output_path = data_root / config[demo_id]["output_path"]

        if not output_path.exists():
            pytest.skip(f"Demo path does not exist: {output_path}")

        # Look for common artifact types
        nifti_files = list(output_path.rglob("*.nii.gz"))
        csv_files = list(output_path.rglob("*.csv"))
        html_files = list(output_path.rglob("*.html"))
        png_files = list(output_path.rglob("*.png"))

        total_artifacts = len(nifti_files) + len(csv_files) + len(html_files) + len(png_files)

        assert total_artifacts > 0, \
            f"Demo '{demo_id}' has no artifacts at {output_path}"

    def test_sample_nifti_readable(self):
        """Test that at least one NIfTI file is readable"""
        config = demo_endpoints.DEMO_CONFIG
        data_root = demo_endpoints.DATA_ROOT

        # Try glm_motor demo
        if "glm_motor" in config:
            output_path = data_root / config["glm_motor"]["output_path"]

            if output_path.exists():
                nifti_files = list(output_path.rglob("*.nii.gz"))

                if len(nifti_files) > 0:
                    sample_file = nifti_files[0]

                    # Check file is readable
                    assert sample_file.exists()
                    assert sample_file.is_file()
                    assert sample_file.stat().st_size > 0


class TestSymlinkHandling:
    """Test handling of symlinks and git-annex links"""

    def test_symlink_detection(self):
        """Test that symlinks are detected correctly"""
        config = demo_endpoints.DEMO_CONFIG
        data_root = demo_endpoints.DATA_ROOT

        for demo_id, demo_info in config.items():
            output_path = data_root / demo_info["output_path"]

            if output_path.is_symlink():
                # Symlink should still be considered as existing
                validation_results = demo_endpoints.PATH_VALIDATION_RESULTS

                if demo_id in validation_results:
                    result = validation_results[demo_id]
                    assert result["exists"], \
                        f"Symlink path for '{demo_id}' not marked as existing"

    def test_broken_symlinks_handled(self):
        """Test that broken symlinks are handled gracefully"""
        # This test documents expected behavior for broken symlinks
        # They should be detected as existing (is_symlink=True) but not readable

        validation_results = demo_endpoints.PATH_VALIDATION_RESULTS

        for demo_id, result in validation_results.items():
            if not result["exists"]:
                # Broken symlink should have an error message
                assert result["error"] is not None


class TestPathValidationLogging:
    """Test that path validation produces appropriate logs"""

    def test_validation_logs_summary(self, caplog):
        """Test that validation logs a summary"""
        import logging
        caplog.set_level(logging.INFO)

        # Re-run validation to capture logs
        demo_endpoints.validate_demo_paths()

        # Check for summary log
        log_messages = [record.message for record in caplog.records]

        summary_logs = [
            msg for msg in log_messages
            if "Demo path validation" in msg and "paths valid" in msg
        ]

        assert len(summary_logs) > 0, "No validation summary log found"

    def test_validation_warns_on_missing_paths(self, caplog):
        """Test that validation warns about missing paths"""
        import logging
        caplog.set_level(logging.WARNING)

        validation_results = demo_endpoints.PATH_VALIDATION_RESULTS

        # Check if any paths are missing
        missing_demos = [
            demo_id for demo_id, result in validation_results.items()
            if not result["exists"]
        ]

        if len(missing_demos) > 0:
            # Should have warning logs
            warning_messages = [
                record.message for record in caplog.records
                if record.levelname == "WARNING"
            ]

            assert len(warning_messages) > 0, \
                f"Missing demos but no warnings logged: {missing_demos}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
