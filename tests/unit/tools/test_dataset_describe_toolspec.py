from brain_researcher.services.tools.catalog_loader import (
    get_toolspec_by_name,
    load_tool_specs,
)


def test_dataset_describe_resources_toolspec_has_python_class():
    load_tool_specs(force_reload=True, exposed_only=True)
    spec = get_toolspec_by_name("datasets.describe_resources")
    assert spec is not None
    assert spec.backend == "python"
    assert spec.python_class is not None
    assert spec.python_class.endswith(".DatasetDescribeTool")
