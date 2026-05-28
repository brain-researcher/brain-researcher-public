from pathlib import Path

import yaml

from brain_researcher.services.tools.meta_glm_multiverse_tool import GLMMultiverseTool


def test_glm_multiverse_wrapper_uses_canonical_runtime_name():
    assert GLMMultiverseTool().get_tool_name() == "glm_multiverse"


def test_glm_multiverse_pipeline_and_studio_surfaces_use_canonical_id():
    pipelines = yaml.safe_load(Path("configs/catalog/pipelines.yaml").read_text()) or {}
    workflows = {
        str(item.get("id")): item for item in (pipelines.get("pipelines") or [])
    }
    workflow = workflows["fmri_glm_multiverse_openneuro"]
    generic_workflow = workflows["fmri_glm_multiverse"]
    steps = workflow.get("steps") or []
    multiverse_step = next(step for step in steps if step.get("order") == 3)
    assert multiverse_step["tool"] == "glm_multiverse"

    generic_tools = [str(step.get("tool")) for step in (generic_workflow.get("steps") or [])]
    assert "glm_multiverse.run" not in generic_tools

    studio = yaml.safe_load(Path("configs/catalog/studio_tool_mappings.yaml").read_text()) or {}
    runtime_tool_ids = studio.get("runtime_tool_ids") or []
    alias_to_runtime = studio.get("alias_to_runtime") or {}

    assert "glm_multiverse" in runtime_tool_ids
    assert "glm_multiverse.run" not in runtime_tool_ids
    assert alias_to_runtime["glm_multiverse"] == "glm_multiverse"
    assert alias_to_runtime["glm_multiverse.run"] == "glm_multiverse"


def test_glm_multiverse_web_preset_uses_canonical_runtime_name():
    analysis_presets = Path("apps/web-ui/src/config/analysis-presets.ts").read_text()

    assert 'tool: "glm_multiverse"' in analysis_presets
    assert '"glm_multiverse.run"' not in analysis_presets


def test_glm_multiverse_deployment_allowlists_use_canonical_runtime_name():
    for relpath in (
        "infrastructure/deployment/gcp/values.prod.yaml",
        "infrastructure/deployment/gce_k3s/values.prod.yaml",
        "infrastructure/k8s/manifests/05-statefulsets.yaml",
    ):
        text = Path(relpath).read_text()
        assert "glm_multiverse.run" not in text, relpath
        assert "glm_multiverse" in text, relpath


def test_public_exposed_tools_whitelist_uses_canonical_runtime_ids():
    exposed = Path("configs/catalog/exposed_tools.yaml").read_text()

    assert "python.data_harmonization.run" not in exposed
    assert "python.brain_simulation.run" not in exposed
    assert "python.realtime_fmri.run" not in exposed
    assert "python.realtime_twophoton.run" not in exposed
    assert "python.lesion_detection.run" not in exposed
    assert "python.coordinate_meta_analysis.run" not in exposed
    assert "data_harmonization" in exposed
    assert "brain_simulation" in exposed
    assert "realtime_fmri" in exposed
    assert "realtime_twophoton" in exposed
    assert "lesion_detection" in exposed
    assert "coordinate_meta_analysis" in exposed


def test_glm_multiverse_tool_family_prefers_canonical_id():
    data = yaml.safe_load(Path("configs/catalog/tool_families.yaml").read_text()) or {}
    families = data.get("families") or []
    glm_family = next(fam for fam in families if fam.get("id") == "fmri.glm_client")
    ops = glm_family.get("ops") or {}

    assert ops["glm_multiverse"] == "glm_multiverse"
    assert "glm_multiverse.run" not in ops
