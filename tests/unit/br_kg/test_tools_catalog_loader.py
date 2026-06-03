import yaml

from brain_researcher.services.br_kg.loader import tools_catalog_loader as loader


class StubTx:
    def __init__(self):
        self.nodes = []
        self.rels = []

    def merge_node(self, label, key, props):
        self.nodes.append((label, key, props))

    def merge_rel(self, l1, k1, v1, rel, l2, k2, v2):
        self.rels.append((l1, k1, v1, rel, l2, k2, v2))


def test_iter_tools_parses_python_and_container(tmp_path):
    caps = {
        "tools": [
            {
                "id": "python.fetch_atlas.run",
                "name": "Fetch Atlas",
                "package": "python",
                "runtime_kind": "python",
                "modality": ["fmri"],
                "capabilities": ["atlas_fetch"],
                "consumes": ["bids_root"],
                "produces": ["parcellation_labels"],
                "python": {
                    "module": "brain_researcher.services.tools.fetch_atlas_tool",
                    "function": "FetchAtlasTool",
                },
            },
            {
                "id": "fsl.bet.run",
                "name": "BET",
                "package": "fsl",
                "runtime_kind": "container",
                "modality": ["smri"],
                "capabilities": ["skull_strip"],
                "consumes": ["volume_3d"],
                "produces": ["mask_path"],
                "container": {"image": "fsl:latest", "digest": "sha256:abc"},
            },
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    items = list(loader.iter_tools(caps_loaded))
    assert len(items) == 2
    py_tool, py_ver, py_edges, py_mods, py_fams = items[0]
    assert py_tool["runtime_kind"] == "python"
    assert py_ver["python_module"] == "brain_researcher.services.tools.fetch_atlas_tool"
    assert any(res == "parcellation_labels" and rel == "PRODUCES_RESOURCE" for _, res, rel in py_edges)
    assert "fmri" in py_mods and "atlas_fetch" in py_fams
    container_tool, container_ver, cont_edges, cont_mods, cont_fams = items[1]
    assert container_ver["container_image"] == "fsl:latest"
    assert any(rel == "CONSUMES_RESOURCE" and res == "volume_3d" for _, res, rel in cont_edges)
    assert "smri" in cont_mods and "skull_strip" in cont_fams


def test_ingest_merges_nodes_and_edges(tmp_path):
    caps_path = tmp_path / "caps.yaml"
    caps_path.write_text(
        """
version: "0.1"
tools:
  - id: python.fetch_atlas.run
    name: Fetch Atlas
    package: python
    runtime_kind: python
    modality: [fmri]
    capabilities: [atlas_fetch]
    consumes: [bids_root]
    produces: [parcellation_labels]
    python:
      module: brain_researcher.services.tools.fetch_atlas_tool
      function: FetchAtlasTool
"""
    )
    evidence = {
        "python.fetch_atlas.run": {
            "publications": ["10.1000/demo"],
            "validated_on_collections": ["openneuro:ds000001"],
        }
    }
    tx = StubTx()
    loader.ingest(tx, caps_path, evidence)
    # Tool + version nodes
    assert any(n[0] == "Tool" for n in tx.nodes)
    assert any(n[0] == "ToolVersion" for n in tx.nodes)
    # Resource edges should target ResourceType on the version
    assert any(r[3] == "CONSUMES_RESOURCE" and r[0] == "ToolVersion" and r[6] == "bids_root" for r in tx.rels)
    assert any(r[3] == "PRODUCES_RESOURCE" and r[0] == "ToolVersion" and r[6] == "parcellation_labels" for r in tx.rels)
    # Modality and capability edges
    assert any(r[3] == "SUPPORTS_MODALITY" for r in tx.rels)
    assert any(r[3] == "IMPLEMENTS_FAMILY" for r in tx.rels)
    # Evidence edges
    assert any(r[3] == "DOCUMENTED_IN" for r in tx.rels)
    assert any(r[3] == "VALIDATED_ON" for r in tx.rels)
    assert (
        "DataResource",
        "id",
        {"id": "openneuro:ds000001", "resource_id": "openneuro:ds000001"},
    ) in tx.nodes
    assert any(
        r[3] == "VALIDATED_ON"
        and r[4] == "DataResource"
        and r[5] == "id"
        and r[6] == "openneuro:ds000001"
        for r in tx.rels
    )
    # Idempotence: rerun should not crash or change counts meaningfully
    pre_nodes = len(tx.nodes)
    pre_rels = len(tx.rels)
    loader.ingest(tx, caps_path, evidence)
    assert len(tx.nodes) >= pre_nodes
    assert len(tx.rels) >= pre_rels


def test_version_id_fallbacks():
    base = {"id": "tool.a", "python": {"module": "m", "function": "f"}}
    assert loader._build_version_id({**base, "version": "1.0"}) == "tool.a@1.0"
    assert loader._build_version_id({**base, "container": {"digest": "sha"}}) == "tool.a@image:sha"
    assert loader._build_version_id({**base, "container": {"image": "img"}}) == "tool.a@image:img"
    assert loader._build_version_id(base) == "tool.a@py:m:f"


def test_iter_tools_op_key_alias_injects_method_intent(tmp_path):
    """op_key_aliases should promote film_gls to the GLM method when intents are missing."""
    caps = {
        "tools": [
            {
                "id": "fsl.6.0.4.film_gls.run",
                "name": "film_gls",
                "package": "fsl",
                "runtime_kind": "container",
                "description": "FSL first-level GLM (FILM).",
            }
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "op_key_aliases": {"filmgls": "glm_first_level_fmri"},
        "priority": ["glm_first_level_fmri"],
    }

    items = list(loader.iter_tools(caps_loaded, tool_meta=tool_meta, intent_config=intent_config))
    assert len(items) == 1
    tool_node, version_node, *_ = items[0]
    assert tool_node.get("software") == "fsl"
    assert tool_node.get("version") == "6.0.4"
    assert tool_node.get("op") == "film_gls"
    assert tool_node.get("op_key") == "filmgls"
    assert "glm_first_level_fmri" in (tool_node.get("intents") or [])
    assert tool_node.get("primary_intent") == "glm_first_level_fmri"
    assert version_node.get("software") == "fsl"
    assert version_node.get("version") == "6.0.4"
    assert version_node.get("op") == "film_gls"
    assert version_node.get("op_key") is None  # ToolVersion keeps op/software/version only


def test_iter_tools_op_key_alias_injects_visualization_intent(tmp_path):
    """op_key_aliases should be able to promote unknown ops into a method bucket (e.g. whirlgif)."""
    caps = {
        "tools": [
            {
                "id": "afni.24.2.06.whirlgif.run",
                "name": "whirlgif",
                "package": "afni",
                "runtime_kind": "container",
                "description": "Create an animated GIF from slices/timepoints.",
            }
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "op_key_aliases": {"whirlgif": "visualization"},
        "priority": ["visualization"],
    }

    items = list(loader.iter_tools(caps_loaded, tool_meta=tool_meta, intent_config=intent_config))
    assert len(items) == 1
    tool_node, version_node, *_ = items[0]
    assert tool_node.get("software") == "afni"
    assert tool_node.get("version") == "24.2.06"
    assert tool_node.get("op") == "whirlgif"
    assert tool_node.get("op_key") == "whirlgif"
    assert tool_node.get("primary_intent") == "visualization"
    assert "visualization" in (tool_node.get("intents") or [])
    assert version_node.get("software") == "afni"


def test_iter_tools_op_key_prefix_alias_injects_utilities_intent(tmp_path):
    """op_key_prefix_aliases should bucket long-tail utilities (e.g. AFNI 1d* tools) without curated intents."""
    caps = {
        "tools": [
            {
                "id": "afni.24.2.06.1dcat.run",
                "name": "1dcat",
                "package": "afni",
                "runtime_kind": "container",
                "description": "Concatenate 1D files.",
            }
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "op_key_prefix_aliases": {"1d": "timeseries_utilities"},
        "priority": ["glm_first_level_fmri"],
    }

    items = list(loader.iter_tools(caps_loaded, tool_meta=tool_meta, intent_config=intent_config))
    assert len(items) == 1
    tool_node, *_ = items[0]
    assert tool_node.get("op_key") == "1dcat"
    assert tool_node.get("primary_intent") == "timeseries_utilities"
    assert "timeseries_utilities" in (tool_node.get("intents") or [])


def test_iter_tools_op_key_patterns_inject_data_access_for_converters(tmp_path):
    """op_key_patterns should map converter-style ops into data_access buckets (e.g. 3dAFNItoNIFTI)."""
    caps = {
        "tools": [
            {
                "id": "afni.24.2.06.3dAFNItoNIFTI.run",
                "name": "3dAFNItoNIFTI",
                "package": "afni",
                "runtime_kind": "container",
                "description": "Convert AFNI datasets to NIFTI.",
            }
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "op_key_patterns": [{"pattern": "to(nifti|analyze|raw|niml|afni|3d)$", "method": "data_access"}],
        "priority": ["data_access"],
    }

    items = list(loader.iter_tools(caps_loaded, tool_meta=tool_meta, intent_config=intent_config))
    assert len(items) == 1
    tool_node, *_ = items[0]
    assert tool_node.get("op_key") == "3dafnitonifti"
    assert tool_node.get("primary_intent") == "data_access"
    assert "data_access" in (tool_node.get("intents") or [])


def test_iter_tools_op_key_alias_maps_segmentation_fast(tmp_path):
    """op_key_aliases should map common FSL ops into stable method buckets (e.g. FAST → segmentation)."""
    caps = {
        "tools": [
            {
                "id": "fsl.6.0.4.fast.run",
                "name": "fast",
                "package": "fsl",
                "runtime_kind": "container",
                "description": "FSL FAST tissue segmentation.",
            }
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "op_key_aliases": {"fast": "segmentation"},
        "priority": ["segmentation"],
    }

    items = list(loader.iter_tools(caps_loaded, tool_meta=tool_meta, intent_config=intent_config))
    assert len(items) == 1
    tool_node, *_ = items[0]
    assert tool_node.get("software") == "fsl"
    assert tool_node.get("op_key") == "fast"
    assert tool_node.get("primary_intent") == "segmentation"


def test_load_intent_config_normalizes_op_key_aliases(tmp_path, monkeypatch):
    """load_intent_config should normalize op_key_aliases keys (e.g. film_gls → filmgls)."""
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    (configs_dir / "intent_priority.yaml").write_text(
        yaml.dump(
            {
                "op_key_aliases": {
                    "film_gls": "glm_first_level_fmri",
                    "fsl_sbca": "seed_based_connectivity",
                },
                "priority": ["glm_first_level_fmri"],
            }
        )
    )

    monkeypatch.setattr(loader, "CONFIGS_DIR", configs_dir)
    loader.load_intent_config.cache_clear()

    intent_config = loader.load_intent_config()
    assert intent_config.get("op_key_aliases", {}).get("filmgls") == "glm_first_level_fmri"
    assert intent_config.get("op_key_aliases", {}).get("fslsbca") == "seed_based_connectivity"
    loader.load_intent_config.cache_clear()


def test_op_key_alias_overrides_single_niwrap_method_intent(tmp_path, monkeypatch):
    """op_key_aliases should be able to override a single NiWrap-derived method intent."""
    def _fake_resolve_niwrap_metadata(_tool_id, _package, _niwrap_map):
        # (category, intents, display_name)
        return None, ["glm_first_level_fmri"], None

    monkeypatch.setattr(loader, "resolve_niwrap_metadata", _fake_resolve_niwrap_metadata)

    caps = {
        "tools": [
            {
                "id": "fsl.6.0.4.featquery.run",
                "name": "featquery",
                "package": "fsl",
                "runtime_kind": "container",
                "description": "Extract stats/time series from FEAT directories.",
            }
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "op_key_aliases": {"featquery": "roi_statistics_extraction"},
        "priority": ["glm_first_level_fmri", "roi_statistics_extraction"],
    }

    items = list(
        loader.iter_tools(
            caps_loaded,
            tool_meta=tool_meta,
            niwrap_map={"_": {}},
            intent_config=intent_config,
        )
    )
    assert len(items) == 1
    tool_node, version_node, *_ = items[0]
    assert tool_node.get("op_key") == "featquery"
    assert tool_node.get("primary_intent") == "roi_statistics_extraction"
    assert "roi_statistics_extraction" in (tool_node.get("intents") or [])
    assert "glm_first_level_fmri" not in (tool_node.get("intents") or [])
    assert version_node.get("software") == "fsl"


def test_exposure_policy_derives_allow_primary_from_intent_priority(tmp_path):
    """derive_allow_primary_from_intent_priority should gate exposure to method intents."""
    caps = {
        "tools": [
            {
                "id": "fsl.6.0.4.film_gls.run",
                "name": "film_gls",
                "package": "fsl",
                "runtime_kind": "container",
            },
            {
                "id": "fsl.6.0.4.bet.run",
                "name": "bet",
                "package": "fsl",
                "runtime_kind": "container",
            },
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    default_by_group = loader.select_default_tools(tool_meta, default_config={})
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "op_key_aliases": {"filmgls": "glm_first_level_fmri", "bet": "skull_strip_mri"},
        "priority": ["glm_first_level_fmri"],
    }
    exposure_policy = {
        "derive_allow_primary_from_intent_priority": True,
        "allow_primary_intents": [],
    }

    items = list(
        loader.iter_tools(
            caps_loaded,
            tool_meta=tool_meta,
            default_by_group=default_by_group,
            intent_config=intent_config,
            exposure_policy=exposure_policy,
        )
    )
    exposed = {tool_node["op_key"]: tool_node.get("exposed") for tool_node, *_ in items}
    assert exposed["filmgls"] is True
    assert exposed["bet"] is False


def test_exposure_policy_denies_known_long_tail_prefixes(tmp_path):
    """deny_op_key_prefixes_by_software and deny_op_prefixes_by_software should force exposed=false."""
    caps = {
        "tools": [
            {
                "id": "afni.24.2.06.1dbandpass.run",
                "name": "1dbandpass",
                "package": "afni",
                "runtime_kind": "container",
            },
            {
                "id": "afni.24.2.06.@Align_Centers.run",
                "name": "@Align_Centers",
                "package": "afni",
                "runtime_kind": "container",
            },
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    default_by_group = loader.select_default_tools(tool_meta, default_config={})
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "op_key_aliases": {"1dbandpass": "glm_first_level_fmri", "aligncenters": "glm_first_level_fmri"},
        "priority": ["glm_first_level_fmri"],
    }
    exposure_policy = {
        "allow_primary_intents": ["glm_first_level_fmri"],
        "deny_op_key_prefixes_by_software": {"afni": ["1d", "2d"]},
        "deny_op_prefixes_by_software": {"afni": ["@"]},
    }

    items = list(
        loader.iter_tools(
            caps_loaded,
            tool_meta=tool_meta,
            default_by_group=default_by_group,
            intent_config=intent_config,
            exposure_policy=exposure_policy,
        )
    )
    exposed = {tool_node["tool_id"]: tool_node.get("exposed") for tool_node, *_ in items}
    assert exposed["afni.24.2.06.1dbandpass.run"] is False
    assert exposed["afni.24.2.06.@Align_Centers.run"] is False


def test_exposure_policy_denies_softwares(tmp_path):
    """deny_softwares should force exposed=false even when the intent is allowed."""
    caps = {
        "tools": [
            {
                "id": "workbench.1.5.0.wb_command.run",
                "name": "wb_command",
                "package": "workbench",
                "runtime_kind": "container",
            }
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    default_by_group = loader.select_default_tools(tool_meta, default_config={})
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "op_key_aliases": {"wbcommand": "surface_ops"},
        "priority": ["surface_ops"],
    }
    exposure_policy = {
        "derive_allow_primary_from_intent_priority": True,
        "allow_primary_intents": [],
        "deny_softwares": ["workbench"],
    }

    items = list(
        loader.iter_tools(
            caps_loaded,
            tool_meta=tool_meta,
            default_by_group=default_by_group,
            intent_config=intent_config,
            exposure_policy=exposure_policy,
        )
    )
    assert len(items) == 1
    tool_node, *_ = items[0]
    assert tool_node.get("primary_intent") == "surface_ops"
    assert tool_node.get("exposed") is False


def test_exposure_policy_denies_primary_intents(tmp_path):
    """deny_primary_intents should force exposed=false even when the intent is otherwise allowed."""
    caps = {
        "tools": [
            {
                "id": "fsl.6.0.4.atlasquery.run",
                "name": "atlasquery",
                "package": "fsl",
                "runtime_kind": "container",
            }
        ]
    }
    path = tmp_path / "caps.yaml"
    path.write_text(yaml.dump(caps))
    caps_loaded = loader.load_capabilities(path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    default_by_group = loader.select_default_tools(tool_meta, default_config={})
    intent_config = {
        "impl_intents": ["generic_container_op"],
        "priority": ["data_access"],
    }
    exposure_policy = {
        "derive_allow_primary_from_intent_priority": True,
        "allow_primary_intents": [],
        "deny_primary_intents": ["data_access"],
    }
    catalog = {"fsl.6.0.4.atlasquery.run": {"intents": ["data_access"]}}

    items = list(
        loader.iter_tools(
            caps_loaded,
            catalog=catalog,
            tool_meta=tool_meta,
            default_by_group=default_by_group,
            intent_config=intent_config,
            exposure_policy=exposure_policy,
        )
    )
    assert len(items) == 1
    tool_node, *_ = items[0]
    assert tool_node.get("primary_intent") == "data_access"
    assert tool_node.get("exposed") is False


def test_select_primary_intent_applies_aliases_to_category_fallback():
    """Category fallbacks should be canonicalized via intent aliases (e.g. data_management → data_access)."""
    intent_config = {
        "aliases": {
            "data_management": "data_access",
            "statistical_analysis": "statistical_inference",
        },
        "priority": ["data_access", "statistical_inference"],
    }
    assert loader.select_primary_intent([], "data_management", [], intent_config) == "data_access"
    assert (
        loader.select_primary_intent([], "Statistical_Analysis", [], intent_config)
        == "statistical_inference"
    )


def test_ingest_idempotent_counts(tmp_path):
    caps_path = tmp_path / "caps.yaml"
    caps_path.write_text(
        """
version: "0.1"
tools:
  - id: demo.t1
    name: Demo
    runtime_kind: python
    modality: [fmri]
    capabilities: [atlas]
    consumes: [bids_root]
    produces: [parcellation_labels]
    python:
      module: demo
      function: run
        """
    )
    tx = StubTx()
    loader.ingest(tx, caps_path, {})
    first_nodes = len(tx.nodes)
    first_rels = len(tx.rels)

    loader.ingest(tx, caps_path, {})
    assert len(tx.nodes) >= first_nodes
    assert len(tx.rels) >= first_rels


def test_ingest_tool_run_stub():
    tx = StubTx()
    provenance = {
        "run_id": "job-1",
        "tool_id": "demo.t1",
        "version_id": "demo.t1@1.0",
        "status": "success",
        "runtime_kind": "python",
        "inputs": ["ds-in"],
        "outputs": ["ds-out"],
        "parameters": {"alpha": 0.1},
    }
    loader.ingest_tool_run(tx, provenance)

    assert any(n[0] == "ToolRun" and n[2]["run_id"] == "job-1" for n in tx.nodes)
    assert any(r[3] == "EXECUTED_VERSION" for r in tx.rels)
    assert any(r[3] == "USED_RESOURCE" and r[6] == "ds-in" for r in tx.rels)
    assert any(r[3] == "GENERATED_RESOURCE" and r[6] == "ds-out" for r in tx.rels)


def test_ingest_ibl_tool_stack_slice(tmp_path):
    caps_path = tmp_path / "caps.yaml"
    caps_path.write_text(
        """
version: "0.1"
tools:
  - id: ibl_one
    name: IBL ONE
    package: ibl
    runtime_kind: python
    modality: [multimodal, data_catalog]
    capabilities: [data_access, session_resolution]
    intents: [data_access]
    consumes: []
    produces: [path_list, metadata]
    resources:
      cpu_min: 1
      mem_mb_min: 256
      gpu: false
      time_min_default: 1
    python:
      module: one.api
      function: ONE
  - id: ibl_brainbox_session_ephys
    name: IBL brainbox session/ephys loader
    package: ibl
    runtime_kind: python
    modality: [multimodal]
    capabilities: [session_loading, ephys_loading, timeseries_extraction]
    intents: [data_access, timeseries_extraction]
    consumes: [nwb_file]
    produces: [spike_times, timeseries, metadata]
    resources:
      cpu_min: 1
      mem_mb_min: 1024
      gpu: false
      time_min_default: 5
    python:
      module: brainbox.io.one
      function: load_session_ephys
  - id: ibl_atlas_region_mapping
    name: IBL atlas region mapping
    package: ibl
    runtime_kind: python
    modality: [multimodal]
    capabilities: [region_mapping, registration, atlas_lookup]
    intents: [registration, linear_registration]
    consumes: [coord_table, atlas_path]
    produces: [parcellation_labels, metadata]
    resources:
      cpu_min: 1
      mem_mb_min: 1024
      gpu: false
      time_min_default: 2
    python:
      module: iblatlas.regions
      function: map_regions
  - id: ibl_rig_task_layer
    name: IBL rig task layer
    package: ibl
    runtime_kind: python
    modality: [multimodal]
    capabilities: [task_control, behavior_acquisition, event_logging]
    intents: [preprocessing]
    consumes: [metadata]
    produces: [events_tsv, nwb_summary, metadata]
    resources:
      cpu_min: 1
      mem_mb_min: 512
      gpu: false
      time_min_default: 5
    python:
      module: iblrig.task
      function: run_task
  - id: ibl_sorter
    name: IBL spike sorter
    package: ibl
    runtime_kind: python
    modality: [multimodal]
    capabilities: [spike_sorting, ephys_qc, preprocessing]
    intents: [spike_sorting, preprocessing]
    consumes: [nwb_file]
    produces: [spike_times, qc_report, features_table]
    resources:
      cpu_min: 2
      mem_mb_min: 4096
      gpu: false
      time_min_default: 60
    python:
      module: iblsorter.sorting
      function: sort_spikes
"""
    )
    evidence = {
        "ibl_one": {"publications": [], "validated_on_collections": ["ds:manual:ibl_brainwide"]},
        "ibl_brainbox_session_ephys": {
            "publications": [],
            "validated_on_collections": ["ds:manual:ibl_brainwide"],
        },
        "ibl_atlas_region_mapping": {
            "publications": [],
            "validated_on_collections": ["ds:manual:ibl_brainwide"],
        },
        "ibl_rig_task_layer": {
            "publications": [],
            "validated_on_collections": ["ds:manual:ibl_brainwide"],
        },
        "ibl_sorter": {
            "publications": [],
            "validated_on_collections": ["ds:manual:ibl_brainwide"],
        },
    }

    tx = StubTx()
    loader.ingest(tx, caps_path, evidence)

    tool_nodes = {props["tool_id"]: props for label, _, props in tx.nodes if label == "Tool"}
    version_nodes = {
        props["tool_id"]: props for label, _, props in tx.nodes if label == "ToolVersion"
    }
    resource_names = {
        props["name"] for label, _, props in tx.nodes if label == "ResourceType"
    }

    assert set(tool_nodes) == {
        "ibl_one",
        "ibl_brainbox_session_ephys",
        "ibl_atlas_region_mapping",
        "ibl_rig_task_layer",
        "ibl_sorter",
    }
    assert tool_nodes["ibl_one"]["runtime_kind"] == "python"
    assert version_nodes["ibl_one"]["python_module"] == "one.api"
    assert version_nodes["ibl_brainbox_session_ephys"]["python_module"] == "brainbox.io.one"
    assert "spike_times" in resource_names
    assert "parcellation_labels" in resource_names
    assert "qc_report" in resource_names
    assert sum(1 for rel in tx.rels if rel[3] == "HAS_VERSION") == 5
    assert sum(1 for rel in tx.rels if rel[3] == "VALIDATED_ON") == 5
    assert any(
        rel[0] == "ToolVersion"
        and rel[3] == "CONSUMES_RESOURCE"
        and rel[6] == "coord_table"
        for rel in tx.rels
    )
    assert any(
        rel[0] == "ToolVersion"
        and rel[3] == "PRODUCES_RESOURCE"
        and rel[6] == "spike_times"
        for rel in tx.rels
    )


def test_ingest_neuropixels_workflow_slice_parses_kilosort_pose_and_alignment(
    tmp_path,
):
    caps_path = tmp_path / "caps.yaml"
    caps_path.write_text(
        yaml.safe_dump(
            {
                "version": "0.1",
                "tools": [
                    {
                        "id": "ibl_kilosort",
                        "name": "IBL Kilosort",
                        "package": "ibl",
                        "runtime_kind": "python",
                        "modality": ["multimodal"],
                        "capabilities": ["spike_sorting"],
                        "intents": ["spike_sorting"],
                        "consumes": ["file_path"],
                        "produces": [
                            "spike_times",
                            "qc_report",
                            "features_table",
                            "metadata",
                        ],
                        "python": {
                            "module": "brain_researcher.services.tools.ibl_tools",
                            "function": "IBLKilosortTool",
                        },
                    },
                    {
                        "id": "ibl_deeplabcut",
                        "name": "IBL DeepLabCut",
                        "package": "ibl",
                        "runtime_kind": "python",
                        "modality": ["optical"],
                        "capabilities": ["pose_tracking"],
                        "intents": ["pose_tracking"],
                        "consumes": ["file_path"],
                        "produces": ["coord_table", "optical_metrics", "metadata"],
                        "python": {
                            "module": "brain_researcher.services.tools.ibl_tools",
                            "function": "IBLDeepLabCutTool",
                        },
                    },
                    {
                        "id": "ibl_lightning_pose",
                        "name": "IBL Lightning Pose",
                        "package": "ibl",
                        "runtime_kind": "python",
                        "modality": ["optical"],
                        "capabilities": ["pose_tracking"],
                        "intents": ["pose_tracking"],
                        "consumes": ["file_path"],
                        "produces": ["coord_table", "optical_metrics", "metadata"],
                        "python": {
                            "module": "brain_researcher.services.tools.ibl_tools",
                            "function": "IBLLightningPoseTool",
                        },
                    },
                    {
                        "id": "ibl_spike_behavior_alignment",
                        "name": "IBL spike-behavior alignment",
                        "package": "ibl",
                        "runtime_kind": "python",
                        "modality": ["multimodal"],
                        "capabilities": ["behavior_alignment"],
                        "intents": ["behavior_alignment"],
                        "consumes": ["spike_times", "coord_table", "events_tsv"],
                        "produces": [
                            "aligned_timeseries",
                            "timeseries",
                            "features_table",
                            "metadata",
                        ],
                        "python": {
                            "module": "brain_researcher.services.tools.ibl_tools",
                            "function": "IBLSpikeBehaviorAlignmentTool",
                        },
                    },
                    {
                        "id": "ibl_decoding_dataset",
                        "name": "IBL decoding dataset builder",
                        "package": "ibl",
                        "runtime_kind": "python",
                        "modality": ["multimodal"],
                        "capabilities": [
                            "feature_extraction",
                            "behavior_alignment",
                            "multimodal_fusion",
                        ],
                        "intents": ["pipeline_run"],
                        "consumes": [
                            "spike_times",
                            "events_tsv",
                            "features_table",
                            "dataset_ref",
                        ],
                        "produces": [
                            "data_file",
                            "labels_file",
                            "groups_file",
                            "sample_metadata",
                            "feature_metadata",
                            "label_map",
                            "metadata",
                        ],
                        "python": {
                            "module": "brain_researcher.services.tools.ibl_tools",
                            "function": "IBLDecodingDatasetTool",
                        },
                    },
                    {
                        "id": "ibl_neuropixels_workflow",
                        "name": "IBL Neuropixels workflow",
                        "package": "ibl",
                        "runtime_kind": "python",
                        "modality": ["multimodal"],
                        "capabilities": [
                            "workflow_planning",
                            "spike_sorting",
                            "pose_tracking",
                            "behavior_alignment",
                        ],
                        "intents": ["pipeline_run"],
                        "consumes": ["file_path", "path_list", "events_tsv"],
                        "produces": [
                            "spike_times",
                            "coord_table",
                            "aligned_timeseries",
                            "qc_report",
                            "optical_metrics",
                            "metadata",
                        ],
                        "python": {
                            "module": "brain_researcher.services.tools.ibl_tools",
                            "function": "IBLNeuropixelsWorkflowTool",
                        },
                    },
                ],
            }
        )
    )

    intent_config = {
        "impl_intents": [
            "generic_container_op",
            "python_op",
            "mcp_tool",
            "wrapper_tool",
            "service_tool",
        ],
        "priority": ["spike_sorting", "pose_tracking", "behavior_alignment", "pipeline_run"],
        "op_key_aliases": {
            "kilosort": "spike_sorting",
            "deeplabcut": "pose_tracking",
            "lightningpose": "pose_tracking",
            "spikebehavioralignment": "behavior_alignment",
            "neuropixelsworkflow": "pipeline_run",
        },
    }

    evidence = {
        "ibl_kilosort": {"publications": [], "validated_on_collections": []},
        "ibl_deeplabcut": {"publications": [], "validated_on_collections": []},
        "ibl_lightning_pose": {"publications": [], "validated_on_collections": []},
        "ibl_spike_behavior_alignment": {
            "publications": [],
            "validated_on_collections": [],
        },
        "ibl_decoding_dataset": {
            "publications": [],
            "validated_on_collections": [],
        },
        "ibl_neuropixels_workflow": {
            "publications": [],
            "validated_on_collections": [],
        },
    }

    tx = StubTx()
    caps_loaded = loader.load_capabilities(caps_path)
    tool_meta = loader.build_tool_meta(caps_loaded, catalog=None)
    items = list(
        loader.iter_tools(
            caps_loaded,
            intent_config=intent_config,
            tool_meta=tool_meta,
        )
    )

    assert [tool_node["tool_id"] for tool_node, *_ in items] == [
        "ibl_kilosort",
        "ibl_deeplabcut",
        "ibl_lightning_pose",
        "ibl_spike_behavior_alignment",
        "ibl_decoding_dataset",
        "ibl_neuropixels_workflow",
    ]
    assert items[0][0]["op_key"] == "iblkilosort"
    assert items[0][0]["primary_intent"] == "spike_sorting"
    assert items[1][0]["op_key"] == "ibldeeplabcut"
    assert items[1][0]["primary_intent"] == "pose_tracking"
    assert items[2][0]["op_key"] == "ibllightningpose"
    assert items[2][0]["primary_intent"] == "pose_tracking"
    assert items[3][0]["op_key"] == "iblspikebehavioralignment"
    assert items[3][0]["primary_intent"] == "behavior_alignment"
    assert items[4][0]["op_key"] == "ibldecodingdataset"
    assert items[4][0]["primary_intent"] == "feature_extraction"
    assert items[5][0]["op_key"] == "iblneuropixelsworkflow"
    assert items[5][0]["primary_intent"] == "workflow_planning"

    loader.ingest(tx, caps_path, evidence)

    tool_nodes = {props["tool_id"]: props for label, _, props in tx.nodes if label == "Tool"}
    version_nodes = {
        props["tool_id"]: props for label, _, props in tx.nodes if label == "ToolVersion"
    }
    resource_names = {
        props["name"] for label, _, props in tx.nodes if label == "ResourceType"
    }

    assert set(tool_nodes) == {
        "ibl_kilosort",
        "ibl_deeplabcut",
        "ibl_lightning_pose",
        "ibl_spike_behavior_alignment",
        "ibl_decoding_dataset",
        "ibl_neuropixels_workflow",
    }
    assert version_nodes["ibl_kilosort"]["python_module"] == (
        "brain_researcher.services.tools.ibl_tools"
    )
    assert version_nodes["ibl_lightning_pose"]["python_function"] == (
        "IBLLightningPoseTool"
    )
    assert {
        "spike_times",
        "coord_table",
        "aligned_timeseries",
        "events_tsv",
        "data_file",
        "labels_file",
        "groups_file",
    } <= resource_names
    assert any(
        rel[0] == "ToolVersion"
        and rel[3] == "PRODUCES_RESOURCE"
        and rel[6] == "coord_table"
        for rel in tx.rels
    )
    assert any(
        rel[0] == "ToolVersion"
        and rel[3] == "CONSUMES_RESOURCE"
        and rel[6] == "spike_times"
        for rel in tx.rels
    )


def test_ibl_public_config_surfaces_use_canonical_ids():
    from pathlib import Path

    for relpath in (
        "configs/grandmaster/toolset_vfinal.yaml",
        "configs/workflows/workflow_catalog.yaml",
        "configs/br-kg/tool_evidence.yaml",
    ):
        text = Path(relpath).read_text()
        assert "ibl.decoding_dataset.run" not in text, relpath
        assert "ibl.neuropixels_workflow.run" not in text, relpath

    toolset = Path("configs/grandmaster/toolset_vfinal.yaml").read_text()
    workflow_catalog = Path("configs/workflows/workflow_catalog.yaml").read_text()
    tool_evidence = Path("configs/br-kg/tool_evidence.yaml").read_text()

    assert "ibl_decoding_dataset" in toolset
    assert "ibl_neuropixels_workflow" in toolset
    assert "ibl_decoding_dataset" in workflow_catalog
    assert "ibl_neuropixels_workflow" in workflow_catalog
    assert "ibl_decoding_dataset" in tool_evidence
    assert "ibl_neuropixels_workflow" in tool_evidence
