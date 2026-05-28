"""Tests for catalog_loader module.

Tests the unified ToolSpec loading from config files and candidate selection.
"""

import sys
from unittest.mock import patch

import pytest


class TestCatalogLoader:
    """Tests for catalog loader functions."""

    def test_configs_dir_points_to_repo_configs(self):
        """CONFIGS_DIR should resolve to repository configs (not src/configs)."""
        from brain_researcher.config.paths import get_config_root
        from brain_researcher.services.tools import catalog_loader

        assert catalog_loader.CONFIGS_DIR == get_config_root()
        assert (catalog_loader.CONFIGS_DIR / "catalog").exists()

    def test_load_exposed_tools(self):
        """Whitelist loads correctly from exposed_tools.yaml."""
        from brain_researcher.services.tools.catalog_loader import load_exposed_tools

        # Clear cache to ensure fresh load
        load_exposed_tools.cache_clear()

        exposed = load_exposed_tools()

        # Should return a list
        assert isinstance(exposed, list)

        # Should contain expected chat tools
        assert "neurokg.client" in exposed
        assert "gemini.fs" in exposed
        assert "datasets.client" in exposed
        assert "realtime_twophoton" in exposed
        assert "compute_connectivity" in exposed
        assert "workflow_realtime_twophoton_closed_loop" in exposed
        assert "workflow_realtime_twophoton_file_replay" in exposed
        assert "code_agent" not in exposed
        assert "run_bids_app" not in exposed

    def test_load_exposed_tools_returns_list(self):
        """load_exposed_tools returns a list even if file is missing."""
        from brain_researcher.services.tools.catalog_loader import load_exposed_tools

        # The function should handle missing files gracefully
        load_exposed_tools.cache_clear()
        result = load_exposed_tools()
        assert isinstance(result, list)

    def test_load_exposed_tools_includes_hypothesis_tool_surface(self):
        """Hypothesis MCP tools should be exposed on the agent-facing surface."""
        from brain_researcher.services.tools.catalog_loader import load_exposed_tools

        load_exposed_tools.cache_clear()
        exposed = set(load_exposed_tools())

        expected = {
            "kg_hypothesis_candidate_cards",
            "kg_hypothesis_candidate_cards_start",
            "kg_hypothesis_candidate_cards_get",
            "hypothesis_hot_load_research",
            "hypothesis_run_start",
            "hypothesis_run_get",
        }
        missing = sorted(expected - exposed)
        assert not missing, f"Missing hypothesis exposed tools: {missing}"

    def test_load_orchestration_workflows(self):
        """Workflow orchestration IDs load from grandmaster config."""
        from brain_researcher.services.tools.catalog_loader import (
            load_orchestration_workflows,
        )

        load_orchestration_workflows.cache_clear()
        workflows = load_orchestration_workflows()
        assert isinstance(workflows, list)
        assert "workflow_preprocessing_qc" in workflows
        assert "workflow_spd_connectome_analysis" in workflows
        assert "workflow_spatial_correlation" in workflows
        assert "workflow_gene_enrichment" in workflows
        assert "workflow_realtime_twophoton_closed_loop" in workflows
        assert "workflow_realtime_twophoton_file_replay" in workflows

    def test_load_tool_specs_excludes_workflows_by_default(self):
        """Default tool search surface excludes workflow IDs."""
        from brain_researcher.services.tools.catalog_loader import load_tool_specs

        specs = load_tool_specs(force_reload=True, exposed_only=True)
        names = {s.name for s in specs}
        assert "workflow_preprocessing_qc" not in names

    def test_load_tool_specs_can_include_workflows(self):
        """Workflows can be explicitly included only when remote tools are enabled."""
        from brain_researcher.services.tools.catalog_loader import load_tool_specs

        with patch.dict(
            "os.environ", {"BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS": "1"}, clear=False
        ):
            specs = load_tool_specs(
                force_reload=True,
                exposed_only=True,
                include_workflows=True,
            )
            names = {s.name for s in specs}
            assert "workflow_preprocessing_qc" in names

    def test_load_tool_specs_include_workflows_hidden_by_default(self):
        """Exposed workflow specs should stay hidden under local-first defaults."""
        from brain_researcher.services.tools.catalog_loader import load_tool_specs

        specs = load_tool_specs(
            force_reload=True,
            exposed_only=True,
            include_workflows=True,
        )
        names = {s.name for s in specs}
        assert "workflow_preprocessing_qc" not in names

    def test_load_tool_specs_all_can_include_non_catalog_workflows(self):
        """All-tools + workflows view should include orchestration workflows not in catalog."""
        from brain_researcher.services.tools.catalog_loader import (
            load_orchestration_workflows,
            load_tool_specs,
            load_tools_catalog,
        )

        workflows = load_orchestration_workflows()
        if not workflows:
            pytest.skip("No orchestration workflows configured.")

        catalog_ids = set(load_tools_catalog().keys())
        target = next((wid for wid in workflows if wid not in catalog_ids), None)
        if target is None:
            pytest.skip("No non-catalog orchestration workflow IDs configured.")

        specs = load_tool_specs(
            force_reload=True,
            exposed_only=False,
            include_workflows=True,
        )
        names = {s.name for s in specs}
        assert target in names

    def test_load_tool_specs_all_includes_hypothesis_mcp_tools(self):
        """Catalog-backed hypothesis MCP tools should resolve in all-tools view."""
        from brain_researcher.services.tools.catalog_loader import load_tool_specs

        specs = load_tool_specs(force_reload=True, exposed_only=False)
        names = {s.name for s in specs}

        expected = {
            "kg_hypothesis_candidate_cards",
            "kg_hypothesis_candidate_cards_start",
            "kg_hypothesis_candidate_cards_get",
            "hypothesis_hot_load_research",
            "hypothesis_run_start",
            "hypothesis_run_get",
        }
        missing = sorted(expected - names)
        assert not missing, f"Missing hypothesis catalog tools: {missing}"

    def test_load_tool_specs_include_workflows_unions_workflow_sources(
        self, monkeypatch
    ):
        """Explicit opt-in should include both orchestration and workflow-catalog IDs."""
        from brain_researcher.services.tools.catalog_loader import load_tool_specs

        def _stub_exposed(*, agent_visible_only: bool = True):
            return ["python.base_tool.run"]

        _stub_exposed.cache_clear = lambda: None  # type: ignore[attr-defined]

        def _stub_catalog():
            return {
                "python.base_tool.run": {
                    "description": "base",
                    "runtime_kind": "python",
                    "python_module": "brain_researcher.services.tools.grandmaster.exposed",
                }
            }

        _stub_catalog.cache_clear = lambda: None  # type: ignore[attr-defined]

        def _stub_categories():
            return {}

        _stub_categories.cache_clear = lambda: None  # type: ignore[attr-defined]

        def _stub_niwrap():
            return {}

        _stub_niwrap.cache_clear = lambda: None  # type: ignore[attr-defined]

        def _stub_orch():
            return ["workflow_orchestration_only"]

        _stub_orch.cache_clear = lambda: None  # type: ignore[attr-defined]

        def _stub_catalog_ids():
            return {"workflow_catalog_only"}

        _stub_catalog_ids.cache_clear = lambda: None  # type: ignore[attr-defined]

        monkeypatch.setattr(
            "brain_researcher.services.tools.catalog_loader.load_exposed_tools",
            _stub_exposed,
        )
        monkeypatch.setattr(
            "brain_researcher.services.tools.catalog_loader.load_tools_catalog",
            _stub_catalog,
        )
        monkeypatch.setattr(
            "brain_researcher.services.tools.catalog_loader.load_categories",
            _stub_categories,
        )
        monkeypatch.setattr(
            "brain_researcher.services.tools.catalog_loader.load_niwrap_mapping",
            _stub_niwrap,
        )
        monkeypatch.setattr(
            "brain_researcher.services.tools.catalog_loader.load_orchestration_workflows",
            _stub_orch,
        )
        monkeypatch.setattr(
            "brain_researcher.services.tools.catalog_loader.load_workflow_catalog_ids",
            _stub_catalog_ids,
        )
        monkeypatch.setenv("BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS", "1")

        specs = load_tool_specs(
            force_reload=True,
            exposed_only=True,
            include_workflows=True,
        )
        names = {s.name for s in specs}
        assert "workflow_orchestration_only" in names
        assert "workflow_catalog_only" in names

    def test_resolve_backend_container(self):
        """Container runtime_kind maps to niwrap backend."""
        from brain_researcher.services.tools.catalog_loader import resolve_backend

        entry = {"runtime_kind": "container"}
        assert resolve_backend(entry) == "niwrap"

    def test_resolve_backend_python(self):
        """Python runtime_kind maps to python backend."""
        from brain_researcher.services.tools.catalog_loader import resolve_backend

        entry = {"runtime_kind": "python"}
        assert resolve_backend(entry) == "python"

    def test_resolve_backend_mcp(self):
        """MCP runtime_kind maps to external_api backend."""
        from brain_researcher.services.tools.catalog_loader import resolve_backend

        entry = {"runtime_kind": "mcp"}
        assert resolve_backend(entry) == "external_api"

    @pytest.mark.parametrize(
        ("tool_id", "expected"),
        [
            ("ants.2.5.3.antsRegistration.run", "ants_registration"),
            ("ants.2.5.3.antsApplyTransforms.run", "ants_registration"),
            ("ants.2.5.3.antsBrainExtraction.sh.run", "fsl_bet"),
            ("fsl.6.0.4.applywarp.run", "fsl_fnirt"),
            ("fsl.6.0.4.featregapply.run", "fsl_flirt"),
            ("fsl.6.0.4.mcflirt.run", "fmriprep_preprocessing"),
            ("fsl.6.0.4.fast.run", "fsl_fast"),
            ("fsl.6.0.4.fsl_prepare_fieldmap.run", "fsl_prepare_fieldmap"),
            ("fsl.6.0.4.topup.run", "fsl_topup"),
            ("fsl.6.0.4.epi_reg.run", "fsl_epi_reg"),
            ("afni.24.2.06.3dvolreg.run", "fmriprep_preprocessing"),
            ("afni.24.2.06.CompareSurfaces.run", "surface_projection"),
            ("bids.validate", "validate_bids"),
        ],
    )
    def test_resolve_primary_runtime_tool_id_for_versioned_atomic_ids(
        self, tool_id: str, expected: str
    ):
        from brain_researcher.services.tools.catalog_loader import (
            resolve_primary_runtime_tool_id,
        )

        resolve_primary_runtime_tool_id.cache_clear()
        assert resolve_primary_runtime_tool_id(tool_id) == expected

    def test_resolve_backend_default(self):
        """Missing runtime_kind defaults to python."""
        from brain_researcher.services.tools.catalog_loader import resolve_backend

        entry = {}
        assert resolve_backend(entry) == "python"

    def test_build_toolspec_fallback_kg_tool(self):
        """Fallback for KG tools infers correct metadata."""
        from brain_researcher.services.tools.catalog_loader import (
            build_toolspec_fallback,
        )

        spec = build_toolspec_fallback("neurokg.client")

        assert spec.name == "neurokg.client"
        assert spec.backend == "python"
        assert spec.kind == "kg"
        assert "knowledge_graph_query" in spec.intents

    def test_build_toolspec_fallback_external_api(self):
        """Fallback for Gemini tools infers external_api backend."""
        from brain_researcher.services.tools.catalog_loader import (
            build_toolspec_fallback,
        )

        spec = build_toolspec_fallback("gemini.fs")

        assert spec.name == "gemini.fs"
        assert spec.backend == "external_api"
        assert "llm_query" in spec.intents

    def test_build_toolspec_fallback_dataset_tool(self):
        """Fallback for dataset tools infers correct kind."""
        from brain_researcher.services.tools.catalog_loader import (
            build_toolspec_fallback,
        )

        spec = build_toolspec_fallback("datasets.client")

        assert spec.name == "datasets.client"
        assert spec.kind == "data"
        assert "data_access" in spec.intents

    def test_build_toolspec_fallback_meta_analysis(self):
        """Fallback for meta-analysis tools infers correct kind."""
        from brain_researcher.services.tools.catalog_loader import (
            build_toolspec_fallback,
        )

        spec = build_toolspec_fallback("meta_analysis.client")

        assert spec.name == "meta_analysis.client"
        assert spec.kind == "meta"
        assert "meta_analysis" in spec.intents

    def test_build_toolspec_fallback_viz_tool(self):
        """Fallback for visualization tools infers correct kind."""
        from brain_researcher.services.tools.catalog_loader import (
            build_toolspec_fallback,
        )

        spec = build_toolspec_fallback("viz.client")

        assert spec.name == "viz.client"
        assert spec.kind == "viz"
        assert "visualization" in spec.intents

    def test_build_toolspec_from_catalog_sets_runtime_metadata(self):
        """Catalog entries should populate implementation/runtime/dependency metadata."""
        from brain_researcher.services.tools.catalog_loader import (
            build_toolspec_from_catalog,
        )

        entry = {
            "description": "Example python tool",
            "runtime_kind": "python",
            "implementation_level": "production",
            "hard_dependencies": ["numpy", "scikit-learn"],
        }
        spec = build_toolspec_from_catalog(
            "python.example.run",
            entry=entry,
            categories_config={},
            niwrap_map={},
        )

        assert spec.implementation_level == "production"
        assert spec.requires_runtime == "python"
        assert spec.hard_dependencies == ["numpy", "scikit-learn"]

    def test_build_toolspec_from_catalog_sets_qc_spec(self):
        """Catalog entries should populate structured QC metadata."""
        from brain_researcher.services.tools.catalog_loader import (
            build_toolspec_from_catalog,
        )

        entry = {
            "description": "QC-enabled python tool",
            "runtime_kind": "python",
            "qc_spec": {
                "enabled": True,
                "artifact_output_keys": ["mask_png"],
                "checklist": ["No obvious over-strip"],
                "failure_modes": ["over_strip", "under_strip"],
                "judge": {
                    "cheap_model": "gemini-2.5-flash-lite",
                    "uncertain_model": "gemini-2.5-flash",
                    "uncertainty_confidence_threshold": 0.65,
                },
                "retry_rules": [
                    {
                        "match_any_failure_modes": ["over_strip"],
                        "param_updates": {"fractional_intensity": 0.3},
                        "fallback_tool": "ants.bet",
                    }
                ],
            },
        }
        spec = build_toolspec_from_catalog(
            "python.qc_enabled.run",
            entry=entry,
            categories_config={},
            niwrap_map={},
        )

        assert spec.qc_spec is not None
        assert spec.qc_spec.enabled is True
        assert spec.qc_spec.artifact_output_keys == ["mask_png"]
        assert spec.qc_spec.judge is not None
        assert spec.qc_spec.judge.cheap_model == "gemini-2.5-flash-lite"
        assert spec.qc_spec.judge.uncertainty_confidence_threshold == 0.65
        assert spec.qc_spec.retry_rules[0].fallback_tool == "ants.bet"

    def test_build_toolspec_from_catalog_forces_workflow_bridge_module(self):
        """Workflow ToolSpecs should always route through bridge module."""
        from brain_researcher.services.tools.catalog_loader import (
            build_toolspec_from_catalog,
        )

        entry = {
            "description": "Workflow",
            "runtime_kind": "python",
            "python_module": "brain_researcher.services.tools.grandmaster.loader",
        }
        spec = build_toolspec_from_catalog(
            "workflow_seed_based_connectivity",
            entry=entry,
            categories_config={},
            niwrap_map={},
        )

        assert spec.backend == "python"
        assert spec.python_class == "brain_researcher.services.tools.catalog_loader"

    def test_spec_from_tool_reads_module_level_toolspec_qc_spec(self, monkeypatch):
        """spec_from_tool should honor module-level TOOL_SPEC metadata."""
        from brain_researcher.services.tools.spec import (
            ToolQCJudgeConfig,
            ToolQCSpec,
            ToolSpec,
            spec_from_tool,
        )

        class DummyArgs:
            @classmethod
            def model_json_schema(cls):
                return {"type": "object", "properties": {}}

        class DummyTool:
            def get_tool_name(self):
                return "dummy.module.tool"

            def get_tool_description(self):
                return "Dummy module-level toolspec tool"

            def get_args_schema(self):
                return DummyArgs

        monkeypatch.setattr(
            sys.modules[__name__],
            "TOOL_SPEC",
            ToolSpec(
                name="dummy.module.tool",
                description="Dummy module-level toolspec tool",
                qc_spec=ToolQCSpec(
                    enabled=True,
                    checklist=["Review image quality"],
                    judge=ToolQCJudgeConfig(
                        cheap_model="gemini-2.5-flash-lite",
                        uncertain_model="gemini-2.5-flash",
                        uncertainty_confidence_threshold=0.6,
                    ),
                ),
            ),
            raising=False,
        )

        spec = spec_from_tool(DummyTool())

        assert spec is not None
        assert spec.qc_spec is not None
        assert spec.qc_spec.judge is not None
        assert spec.qc_spec.judge.cheap_model == "gemini-2.5-flash-lite"

    def test_mcp_schema_enrichment_preserves_qc_spec(self, monkeypatch):
        """Python MCP enrichment should carry qc_spec through schema materialization."""
        from brain_researcher.services.mcp.server import _enrich_toolspec_schema
        from brain_researcher.services.tools.spec import (
            ToolQCJudgeConfig,
            ToolQCSpec,
            ToolSpec,
        )

        spec = ToolSpec(
            name="dummy.python.tool",
            description="Dummy python tool",
            backend="python",
            python_class="brain_researcher.services.tools.fake.FakeTool",
        )
        extracted = ToolSpec(
            name="dummy.python.tool",
            description="Dummy python tool",
            qc_spec=ToolQCSpec(
                enabled=True,
                checklist=["Check output"],
                judge=ToolQCJudgeConfig(
                    cheap_model="gemini-2.5-flash-lite",
                    uncertain_model="gemini-2.5-flash",
                    uncertainty_confidence_threshold=0.75,
                ),
            ),
        )

        monkeypatch.setattr(
            "brain_researcher.services.tools.executor._resolve_python_tool_instance",
            lambda _spec: object(),
        )
        monkeypatch.setattr(
            "brain_researcher.services.tools.spec.spec_from_tool",
            lambda _tool: extracted,
        )

        enriched = _enrich_toolspec_schema(spec)

        assert enriched.qc_spec is not None
        assert enriched.qc_spec.judge is not None
        assert enriched.qc_spec.judge.uncertain_model == "gemini-2.5-flash"

    def test_load_tool_specs(self):
        """load_tool_specs returns list of ToolSpec objects."""
        from brain_researcher.services.tools.catalog_loader import load_tool_specs

        specs = load_tool_specs(force_reload=True)

        assert isinstance(specs, list)
        # Should have loaded at least some tools
        assert len(specs) > 0

        # Each item should be a ToolSpec
        for spec in specs:
            assert hasattr(spec, "name")
            assert hasattr(spec, "backend")
            assert hasattr(spec, "modalities")
            assert hasattr(spec, "intents")

    def test_get_toolspec_by_name(self):
        """get_toolspec_by_name returns correct spec."""
        from brain_researcher.services.tools.catalog_loader import get_toolspec_by_name

        spec = get_toolspec_by_name("neurokg.client")

        # May return None if not in whitelist, but if found, should be correct
        if spec is not None:
            assert spec.name == "neurokg.client"

    def test_get_toolspec_by_name_resolves_hidden_fsl_runtime_alias(self):
        """Hidden discoverable FSL aliases should still resolve to ToolSpecs."""
        from brain_researcher.services.tools.catalog_loader import get_toolspec_by_name

        spec = get_toolspec_by_name("fsl_fast")

        assert spec is not None
        assert spec.name == "fsl_fast"
        assert spec.backend == "niwrap"
        assert spec.niwrap_id == "fsl.6.0.4.fast.run"

    def test_exposed_python_tools_have_python_class(self):
        """Exposed python planner tools should be executable via ToolSpec dispatch."""
        from brain_researcher.services.tools.catalog_loader import (
            get_toolspec_by_name,
            load_tool_specs,
        )

        load_tool_specs(force_reload=True)

        expected = {
            "data_harmonization": "brain_researcher.services.tools.phase2_batch_tools",
        }

        for tool_id, cls_name in expected.items():
            spec = get_toolspec_by_name(tool_id)
            assert spec is not None, tool_id
            assert spec.backend == "python"
            assert spec.python_class and cls_name in spec.python_class

    def test_run_fitlins_recipe_has_python_class_with_remote_opt_in(self):
        """run_fitlins_recipe remains executable when remote execution is enabled."""
        from brain_researcher.services.tools.catalog_loader import (
            get_toolspec_by_name,
            load_tool_specs,
        )

        with patch.dict(
            "os.environ", {"BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS": "1"}, clear=False
        ):
            load_tool_specs(force_reload=True, exposed_only=True)
            spec = get_toolspec_by_name("run_fitlins_recipe")
            assert spec is not None
            assert spec.backend == "python"
            assert spec.python_class is not None
            assert "RunFitLinsRecipeTool" in spec.python_class

    def test_workflow_hypothesis_candidate_cards_declares_network_capability(self):
        """Hot-load workflow must declare network access for external literature."""
        from brain_researcher.services.tools.catalog_loader import (
            get_toolspec_by_name,
            load_tool_specs,
        )

        with patch.dict(
            "os.environ", {"BR_AGENT_ALLOW_REMOTE_EXECUTION_TOOLS": "1"}, clear=False
        ):
            load_tool_specs(
                force_reload=True,
                exposed_only=False,
                include_workflows=True,
            )
            spec = get_toolspec_by_name("workflow_hypothesis_candidate_cards")

        assert spec is not None
        assert spec.backend == "python"
        assert spec.execution_capabilities is not None
        assert spec.execution_capabilities.needs_network is True
        assert spec.execution_capabilities.allowed_domains == []


class TestResolveNiwrapMetadata:
    """Tests for NiWrap metadata resolution."""

    def test_resolve_niwrap_metadata_fsl_bet(self):
        """FSL BET gets correct modalities and intents."""
        from brain_researcher.services.tools.catalog_loader import (
            load_niwrap_mapping,
            resolve_niwrap_metadata,
        )

        load_niwrap_mapping.cache_clear()
        niwrap_map = load_niwrap_mapping()

        modalities, intents, niwrap_id = resolve_niwrap_metadata(
            "fsl.bet", "fsl", niwrap_map
        )

        assert "smri" in modalities or "fmri" in modalities
        assert "skull_strip_mri" in intents
        assert "fsl.bet.run" in niwrap_id

    def test_resolve_niwrap_metadata_runtime_canonical_id_prefers_descriptor_alias(self):
        """Runtime canonical ids resolve to NiWrap descriptor aliases."""
        from brain_researcher.services.tools.catalog_loader import (
            load_niwrap_mapping,
            resolve_niwrap_metadata,
        )

        load_niwrap_mapping.cache_clear()
        niwrap_map = load_niwrap_mapping()

        modalities, intents, niwrap_id = resolve_niwrap_metadata(
            "spm12_vbm", "cat12", niwrap_map
        )

        assert "smri" in modalities or "fmri" in modalities
        assert len(intents) > 0
        assert niwrap_id == "cat12.vbm.run"

    def test_resolve_niwrap_metadata_prefers_same_package_descriptor(self):
        """Runtime canonical ids should prefer same-suite NiWrap descriptors."""
        from brain_researcher.services.tools.catalog_loader import (
            load_niwrap_mapping,
            resolve_niwrap_metadata,
        )

        load_niwrap_mapping.cache_clear()
        niwrap_map = load_niwrap_mapping()

        modalities, intents, niwrap_id = resolve_niwrap_metadata(
            "fsl_bet", "fsl", niwrap_map
        )

        assert "smri" in modalities or "fmri" in modalities
        assert len(intents) > 0
        assert niwrap_id == "fsl.bet.run"

    def test_resolve_niwrap_metadata_afni_clustsim(self):
        """AFNI ClustSim gets correct intents."""
        from brain_researcher.services.tools.catalog_loader import (
            load_niwrap_mapping,
            resolve_niwrap_metadata,
        )

        load_niwrap_mapping.cache_clear()
        niwrap_map = load_niwrap_mapping()

        modalities, intents, niwrap_id = resolve_niwrap_metadata(
            "afni.3dClustSim", "afni", niwrap_map
        )

        assert "fmri" in modalities or "smri" in modalities
        assert "afni_clustsim_correction" in intents

    def test_resolve_niwrap_metadata_unknown_package(self):
        """Unknown package uses defaults."""
        from brain_researcher.services.tools.catalog_loader import (
            load_niwrap_mapping,
            resolve_niwrap_metadata,
        )

        load_niwrap_mapping.cache_clear()
        niwrap_map = load_niwrap_mapping()

        modalities, intents, niwrap_id = resolve_niwrap_metadata(
            "unknown.tool", "unknown", niwrap_map
        )

        # Should get default modalities
        assert len(modalities) > 0
        # Should get default intents
        assert len(intents) > 0


class TestUnifiedToolRegistry:
    """Tests for UnifiedToolRegistry candidate selection."""

    def test_get_all_tools_includes_hypothesis_mcp_runtime_wrappers(self):
        """Runtime registry should surface hypothesis MCP tools for agent /tools."""
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()
        names = {tool.name for tool in registry.get_all_tools()}

        expected = {
            "kg_hypothesis_candidate_cards",
            "kg_hypothesis_candidate_cards_start",
            "kg_hypothesis_candidate_cards_get",
            "hypothesis_hot_load_research",
            "hypothesis_run_start",
            "hypothesis_run_get",
        }
        missing = sorted(expected - names)
        assert not missing, f"Missing hypothesis runtime wrappers: {missing}"

    def test_get_exposed_toolspecs(self):
        """get_exposed_toolspecs returns cached ToolSpecs."""
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()
        specs = registry.get_exposed_toolspecs()

        assert isinstance(specs, list)

        # Second call should return cached version
        specs2 = registry.get_exposed_toolspecs()
        assert specs == specs2

    def test_get_candidate_tools_basic(self):
        """get_candidate_tools returns relevant tools for goal."""
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()
        candidates = registry.get_candidate_tools(
            goal="search knowledge graph for motor cortex",
            k=5,
        )

        assert isinstance(candidates, list)
        assert len(candidates) <= 5

        # Should prefer KG-related tools
        tool_names = [c.name for c in candidates]
        # At least one should be KG-related
        kg_related = any(
            "neurokg" in name or "graph" in name or "concept" in name
            for name in tool_names
        )
        assert kg_related or len(candidates) == 0  # May have no KG tools exposed

    def test_get_candidate_tools_modality_filter(self):
        """get_candidate_tools filters by modality."""
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()
        candidates = registry.get_candidate_tools(
            goal="analyze connectivity",
            modalities=["fmri"],
            k=10,
        )

        # All returned tools should either have no modalities or include fmri
        for c in candidates:
            if c.modalities:
                assert "fmri" in c.modalities or not c.modalities

    def test_get_candidate_tools_kind_filter(self):
        """get_candidate_tools filters by kind."""
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()
        candidates = registry.get_candidate_tools(
            goal="query brain regions",
            kind="kg",
            k=5,
        )

        # All returned tools should have kind=kg or kind=None
        for c in candidates:
            assert c.kind == "kg" or c.kind is None

    def test_get_candidate_tools_empty_goal(self):
        """get_candidate_tools handles empty goal."""
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()
        candidates = registry.get_candidate_tools(goal="", k=5)

        # Should return some tools even with empty goal
        assert isinstance(candidates, list)

    def test_get_toolspec_by_name_found(self):
        """get_toolspec_by_name returns spec when found."""
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()

        # Get all exposed specs first
        specs = registry.get_exposed_toolspecs()
        if specs:
            # Try to find the first one by name
            first_name = specs[0].name
            found = registry.get_toolspec_by_name(first_name)
            assert found is not None
            assert found.name == first_name

    def test_get_toolspec_by_name_not_found(self):
        """get_toolspec_by_name returns None when not found."""
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()
        found = registry.get_toolspec_by_name("nonexistent.tool.xyz")
        assert found is None

    def test_get_toolspec_by_name_resolves_hidden_discoverable_fsl_alias(self):
        """Registry should resolve hidden discoverable FSL aliases for execution."""
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        registry = UnifiedToolRegistry()
        found = registry.get_toolspec_by_name("fsl_fast")

        assert found is not None
        assert found.name == "fsl_fast"
        assert found.backend == "niwrap"
        assert found.niwrap_id == "fsl.6.0.4.fast.run"

    def test_get_toolspec_by_name_resolves_non_catalog_workflow(self):
        """Resolver should find orchestration workflows even when absent in merged catalog."""
        from brain_researcher.services.tools.catalog_loader import (
            load_orchestration_workflows,
            load_tools_catalog,
        )
        from brain_researcher.services.tools.registry import UnifiedToolRegistry

        workflows = load_orchestration_workflows()
        if not workflows:
            pytest.skip("No orchestration workflows configured.")

        catalog_ids = set(load_tools_catalog().keys())
        target = next((wid for wid in workflows if wid not in catalog_ids), None)
        if target is None:
            pytest.skip("No non-catalog orchestration workflow IDs configured.")

        registry = UnifiedToolRegistry()
        registry.get_exposed_toolspecs(force_reload=True)
        registry.get_all_toolspecs(force_reload=True, include_workflows=True)
        found = registry.get_toolspec_by_name(target)
        assert found is not None
        assert found.name == target


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_candidate_tools_function(self):
        """Module-level get_candidate_tools works."""
        from brain_researcher.services.tools.registry import get_candidate_tools

        candidates = get_candidate_tools(
            goal="find brain regions",
            k=3,
        )

        assert isinstance(candidates, list)
        assert len(candidates) <= 3


class TestRouterPrompt:
    """Tests for router prompt templates."""

    def test_format_tool_summary(self):
        """format_tool_summary produces readable output."""
        from brain_researcher.services.agent.prompts import format_tool_summary
        from brain_researcher.services.tools.spec import ToolSpec

        spec = ToolSpec(
            name="test.tool",
            description="A test tool for unit testing",
            modalities=["fmri"],
            intents=["test_intent"],
            kind="analysis",
        )

        summary = format_tool_summary(spec)

        assert "test.tool" in summary
        assert "test tool" in summary

    def test_build_router_prompt(self):
        """build_router_prompt creates valid prompt."""
        from brain_researcher.services.agent.prompts import build_router_prompt
        from brain_researcher.services.tools.spec import ToolSpec

        specs = [
            ToolSpec(
                name="tool1",
                description="First tool",
                intents=["intent1"],
            ),
            ToolSpec(
                name="tool2",
                description="Second tool",
                intents=["intent2"],
            ),
        ]

        prompt = build_router_prompt(
            goal="do something",
            candidates=specs,
            context="some context",
        )

        assert "do something" in prompt
        assert "tool1" in prompt
        assert "tool2" in prompt
        assert "some context" in prompt


class TestToolRouterUnified:
    """Tests for ToolRouter unified interface (Phase 2)."""

    def test_get_candidates_unified(self):
        """ToolRouter.get_candidates_unified returns ToolSpec list."""
        from brain_researcher.services.agent.tool_router import ToolRouter
        from brain_researcher.services.tools.tool_registry import ToolRegistry

        core_registry = ToolRegistry()
        router = ToolRouter(core_registry=core_registry)

        candidates = router.get_candidates_unified(
            goal="extract brain from MRI",
            k=5,
        )

        assert isinstance(candidates, list)
        assert len(candidates) <= 5

    def test_build_llm_prompt(self):
        """ToolRouter.build_llm_prompt creates valid prompt."""
        from brain_researcher.services.agent.tool_router import ToolRouter
        from brain_researcher.services.tools.tool_registry import ToolRegistry

        core_registry = ToolRegistry()
        router = ToolRouter(core_registry=core_registry)

        # Get some candidates
        candidates = router.get_candidates_unified("skull stripping", k=3)

        if candidates:
            prompt = router.build_llm_prompt(
                goal="perform skull stripping on T1w image",
                candidates=candidates,
                context="Input: /data/sub-01/anat/T1w.nii.gz",
            )

            assert "skull stripping" in prompt
            assert "Input:" in prompt
            # Should contain tool info
            assert len(prompt) > 100


class TestHighLevelExposurePolicy:
    """Exposure surface should prefer high-level workflow-facing tools."""

    def test_runtime_execution_tools_hidden_from_agent_visible_surface(self):
        """Default exposed surface should hide broad runtime tools except allowed connectome steps."""
        from brain_researcher.services.tools.catalog_loader import load_exposed_tools

        load_exposed_tools.cache_clear()
        exposed = load_exposed_tools()

        assert "fsl_bet" not in exposed
        assert "fsl_fast" not in exposed
        assert "fsl_prepare_fieldmap" not in exposed
        assert "fsl_topup" not in exposed
        assert "fsl_epi_reg" not in exposed
        assert "fsl_flirt" not in exposed
        assert "afni_3dClustSim" not in exposed
        assert "ants_registration" not in exposed
        assert "freesurfer_recon_all" not in exposed
        assert "execute_tool" not in exposed
        assert "neurodesk_command" not in exposed
        assert "run_local_script" not in exposed
        assert "identity" not in exposed
        assert "prefetch.openneuro_cache" not in exposed
        assert "fmriprep_preprocessing" not in exposed
        assert "freesurfer_qc" not in exposed

        # Rest-connectome launch is explicitly exposed so UI/MCP preflight and
        # execution use the same runtime IDs.
        assert "connectivity_matrix" in exposed
        assert "compute_connectivity" in exposed
        assert "extract_timeseries" in exposed
        assert "fetch_atlas" in exposed

    def test_user_facing_analysis_helpers_remain_agent_visible(self):
        """User-facing helpers should stay on the default chat/agent surface."""
        from brain_researcher.services.tools.catalog_loader import load_exposed_tools

        load_exposed_tools.cache_clear()
        exposed = load_exposed_tools()

        assert "bids.manifest" in exposed
        assert "multiple_comparison_correction" in exposed
        assert "brain_simulation" in exposed
        assert "realtime_fmri" in exposed
        assert "viz_stat_maps" in exposed
        assert "surface_projection" in exposed
        assert "motion_quantification" in exposed
        assert "mriqc_group_report" in exposed

    def test_discoverable_exposed_surface_keeps_runtime_tools_searchable(self):
        """Search discovery should retain hidden runtime tools for ranking."""
        from brain_researcher.services.tools.catalog_loader import load_exposed_tools

        load_exposed_tools.cache_clear()
        exposed = load_exposed_tools(agent_visible_only=False)

        assert "fsl_bet" in exposed
        assert "fsl_flirt" in exposed
        assert "ants_registration" in exposed
        assert "freesurfer_recon_all" in exposed
        assert "neurodesk_command" in exposed
        assert "prefetch.openneuro_cache" in exposed
        assert "connectivity_matrix" in exposed
        assert "fmriprep_preprocessing" in exposed
        assert "motion_quantification" in exposed
        assert "mriqc_group_report" in exposed
        assert "freesurfer_qc" in exposed
        assert "neurokg.search_nodes" in exposed
        assert "kg_multihop_qa" in exposed
        assert "openneuro.search" in exposed
        assert "mne_ica" in exposed
        assert "mne_timefreq" in exposed
        assert "mne_source_localization" in exposed
        assert "fsl_prepare_fieldmap" in exposed
        assert "fsl_topup" in exposed
        assert "fsl_epi_reg" in exposed
        assert "fsl_fast" in exposed
        assert "fsl.6.0.4.fsl_prepare_fieldmap.run" not in exposed
        assert "fsl.6.0.4.topup.run" not in exposed
        assert "fsl.6.0.4.epi_reg.run" not in exposed
        assert "fsl.6.0.4.fast.run" not in exposed
        assert "fsl_melodic_ica" in exposed
        assert "fsl_dual_regression" in exposed
        assert "mrtrix.3.0.4.dwi2fod.run" in exposed
        assert "diffusion_tractography" in exposed
        assert "validate_bids" in exposed
        assert "derivatives_sanity_checker" in exposed
        assert "cross_validation" in exposed
        assert "ml_cross_validation" in exposed
        assert "validation_metrics" in exposed

    def test_discoverable_only_validation_and_cv_tools_stay_hidden_from_agent_surface(self):
        """New discoverable retrieval helpers should not widen the default chat surface."""
        from brain_researcher.services.tools.catalog_loader import load_exposed_tools

        load_exposed_tools.cache_clear()
        exposed = load_exposed_tools()

        assert "validate_bids" not in exposed
        assert "derivatives_sanity_checker" not in exposed
        assert "cross_validation" not in exposed
        assert "ml_cross_validation" not in exposed
        assert "validation_metrics" not in exposed
        assert "mrtrix.3.0.4.dwi2fod.run" not in exposed

    def test_high_level_connectors_remain_exposed(self):
        """Pruning low-level tools should keep workflow-facing connectors visible."""
        from brain_researcher.services.tools.catalog_loader import load_exposed_tools

        load_exposed_tools.cache_clear()
        exposed = load_exposed_tools()
        assert "pipeline.search" in exposed
        assert "query_neuromaps" in exposed
        assert "seed_based_fc" in exposed
        assert "stack_surface_hemis" in exposed
        assert "glm_first_level" in exposed
        assert "glm_second_level" in exposed
        assert "visualize_interactive" in exposed

    def test_execution_connectors_hidden_from_exposed_surface(self):
        """Executor-style tools should stay hidden except the allowed connectome runtime IDs."""
        from brain_researcher.services.tools.catalog_loader import load_exposed_tools

        load_exposed_tools.cache_clear()
        exposed = load_exposed_tools()
        assert "code_agent" not in exposed
        assert "run_bids_app" not in exposed
        assert "run_fitlins_recipe" not in exposed
        assert "extract_timeseries" in exposed
        assert "fetch_atlas" in exposed
