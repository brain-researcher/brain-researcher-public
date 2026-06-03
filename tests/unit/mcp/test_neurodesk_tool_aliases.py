from __future__ import annotations

from brain_researcher.services.mcp import server as srv
from brain_researcher.services.tools.registry import UnifiedToolRegistry


def test_registry_resolves_cat12_alias_to_spm12_vbm() -> None:
    reg = UnifiedToolRegistry()

    spec = reg.get_toolspec_by_name("cat12")

    assert spec is not None
    assert spec.name == "spm12_vbm"
    assert spec.backend == "niwrap"


def test_get_execution_recipe_resolves_cat12_alias_with_module_metadata() -> None:
    resp = srv.get_execution_recipe(
        "cat12",
        params={
            "structural_images": ["/tmp/sub-01_T1w.nii.gz"],
            "output_dir": "/tmp/out",
        },
        target_runtime="neurodesk",
    )

    assert resp["ok"] is True
    assert resp["requested_tool_id"] == "cat12"
    assert resp["resolved_tool_id"] == "spm12_vbm"
    assert resp["canonical_tool_id"] == "spm12_vbm"
    assert resp["neurodesk_module_name"] == "cat12"
    assert resp["neurodesk_recommended_module"] == "cat12/12.9"
    # cat12 (spm12_vbm) is a neurodesk lmod module, not a standalone OCI app: it has
    # no entry in the container_images registry (which holds only BIDS-App/NiPreps
    # images like fmriprep/mriqc). So `container` is correctly NOT a supported target
    # -- get_execution_recipe(..., target_runtime="container") legitimately returns
    # unsupported for it. Advertising "container" here would lie about what the recipe
    # generator can actually produce.
    assert resp["supported_recipe_targets"] == ["neurodesk", "slurm"]
    assert (
        resp["recipe"]["run_command"]
        == "module load cat12/12.9 && python run_spm12_vbm.py"
    )


def test_tool_search_exposed_surface_discovers_spm12_vbm() -> None:
    reg = UnifiedToolRegistry()
    reg.get_exposed_toolspecs(force_reload=True)

    for query in ("VBM grey matter volume", "cat12"):
        resp = srv.tool_search(
            query,
            limit=10,
            exposed_only=True,
            include_workflows=False,
        )
        names = [str(tool.get("name") or "") for tool in resp["tools"]]

        assert "spm12_vbm" in names
        assert names.index("spm12_vbm") < 5
