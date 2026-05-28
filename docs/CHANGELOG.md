# Changelog

All notable changes to the Brain Researcher project are documented in this file.

## [Unreleased]

### Tool System Unification Phase 7 - Registry Unification (2025-12-04)

#### ✨ Added
- **StructuredToolAdapter**: New adapter class in `services.tools.adapter`
  - Wraps LangChain `StructuredTool` to expose `NeuroKGToolWrapper` interface
  - Enables UnifiedToolRegistry integration with Agent ToolRegistry
  - `wrap_structured_tools()` helper for batch wrapping
  - No double-wrapping: `as_langchain_tool()` returns the original tool

- **Registry Unification Tests**: New test suite at `tests/unit/tools/test_registry_unification.py`
  - Adapter functionality tests (name, description, schema preservation)
  - Registry integration tests (unified tools in agent registry)
  - Tool count consistency tests

#### 🔄 Changed
- **Agent ToolRegistry Integration**: Now delegates to UnifiedToolRegistry first
  - `_load_from_unified_registry()` loads tools from canonical source
  - Tools wrapped via `StructuredToolAdapter` for compatibility
  - Legacy tool discovery runs after unified registry load
  - No duplicate registration (skips if tool name exists)

#### 📚 Architecture
- **Single Source of Truth**: UnifiedToolRegistry is canonical tool source
- **Agent Compatibility**: StructuredToolAdapter bridges StructuredTool → NeuroKGToolWrapper
- **Discovery Order**: UnifiedToolRegistry → Light/Full Discovery → Capabilities

---

### Tool System Unification Phase 6 - Final Migration (2025-12-03)

#### ✨ Added
- **MRIQC Pipeline Support**: Complete MRIQC integration in `services.tools.pipelines`
  - `MRIQCParameters` dataclass with frozen immutability and tuple normalization
  - `build_mriqc_command()`, `build_mriqc_env()`, `mriqc_from_payload()` helpers
  - `run_mriqc()`, `run_mriqc_from_dict()` container execution with path remapping
  - `MRIQC_IMAGE` env override (`BR_MRIQC_IMAGE`)

- **Import Smoke Tests**: Comprehensive test suite at `tests/unit/tools/test_imports_smoke.py`
  - Pipeline params import validation
  - UnifiedToolRegistry functionality tests
  - Neurocore deprecation warning verification
  - Container command path remapping tests
  - Runtime Literal validation (docker, apptainer, wrapper)
- **Unified Params Facade**: New `services.tools.params` re-exports all neurocore parameter
  classes/command builders, providing the canonical import path for analysis tools.
  - Legacy `brain_researcher.neurocore` package removed; importing it now raises ImportError.

#### 🔄 Changed
- **Agent Tool Imports**: Updated to use `services.tools.pipelines` as canonical source
  - `pipeline_tools.py`: MRIQC imports now from `services.tools.pipelines`
  - `qc_tools.py`: MRIQC imports now from `services.tools.pipelines`
  - 38 analysis agent tools now import params from `services.tools.params`
  - Neurocore shim removed; params live under `services.tools.params`

#### 📚 Architecture Documentation
- **Pipeline Parameters Canonical Location**: `brain_researcher.services.tools.pipelines.params`
  - FMRIPrepParameters, QSIPrepParameters, FitLinsParameters, MRIQCParameters
- **Pipeline Execution Helpers**: `brain_researcher.services.tools.pipelines.helpers`
  - Container execution with automatic path remapping (host → container)
  - Environment variable overrides for container images (BR_*_IMAGE)
- **Neurocore Re-exports**: Thin wrappers with deprecation warnings
  - Import from `services.tools.pipelines` instead of `neurocore.*`
  - Will be removed in future release

#### ⚙️ Tool Registry Architecture
- **UnifiedToolRegistry** (`services.tools.registry`): Returns LangChain `StructuredTool` for direct consumers
- **Agent ToolRegistry** (`services.tools.registry`): Uses `NeuroKGToolWrapper` with rich metadata
- Both registries serve complementary purposes and coexist in the architecture

### Phase 1.4 - Hierarchical Config Overrides (2025-11-13)

#### ✨ Added
- **Cache Management Helper**: `clear_scoring_weights_cache()` for test isolation and runtime env-var changes
- **Comprehensive Test Coverage**: 4 new Phase 1.4 tests (modality/environment overrides, feature toggles, GPU constraints)
- **Shared Test Helpers**: Consolidated mock classes in `tests/unit/planner/helpers.py`
- **7-Factor Scoring**: Fully implemented `historical_quality` and `latency_pred` scoring factors
  - Historical quality based on literature references, documentation URLs, and source reputation
  - Latency prediction from `tool.resources.time_min_default` (≤5 min = 1.0, ≥60 min = 0.0)

#### 🔧 Fixed
- **Override Threading**: `SelectionCandidate` now requires `scoring_weights` parameter (no default)
  - Removed fallbacks to global cache that ignored modality/operator/environment overrides
  - Merged weights from `load_hierarchical_config()` properly reach scoring calculation
- **GPU Constraint Enforcement**: Fixed GPU checks to use `tool.resources.gpu` instead of `hasattr()`
- **Test Isolation**: All env-var tests now use proper cache clearing pattern

#### 📚 Documentation
- Added Phase 1.4 completion notes to `docs/issues/09_move_planning_into_agent.md`
- Enhanced `clear_scoring_weights_cache()` docstring with usage patterns and examples
- Documented cache semantics: when to call, how it affects planner processes

#### 🧪 Test Results
- **167/167 planner unit tests passing** (35 selection tests, 12 materializer tests, 120 other planner tests)
- All Phase 1.4 correctness gaps resolved
- No regressions in existing test suite

## [2.0.0] - 2025-07-23

### 🎉 Major Modernization Release

This release represents a complete modernization of the Brain Researcher project, following Biomni and LangGraph architectural patterns.

### ✨ Added

- **Unified CLI System**
  - Single entry point via `brain-researcher` or `br` command
  - Organized subcommands: `db`, `data`, `query`, `test`
  - Rich terminal output with progress indicators
  - Comprehensive help system

- **Testing Framework**
  - Three-role testing system (Tester, StaticAnalyst, Supervisor)
  - Quality gates and deployment recommendations
  - Code coverage reporting
  - Static analysis with ruff, mypy, bandit
  - HTML quality reports

- **Data Management**
  - Git-LFS integration for large files
  - Automated data download/upload scripts
  - Structured data organization

- **Documentation System**
  - MkDocs with Material theme
  - Comprehensive API documentation
  - Migration guides and tutorials
  - Architecture diagrams

- **Development Tools**
  - Pre-commit hooks for code quality
  - Docker multi-stage builds
  - Development and production configurations
  - Automated code formatting

### 🔄 Changed

- **Package Structure**
  - Consolidated 40+ scattered scripts into organized CLI
  - Merged duplicate tool implementations
  - Unified configuration in `pyproject.toml`
  - Removed 10 separate requirements.txt files

- **Code Quality**
  - Fixed 471 code style issues (91.5% improvement)
  - Added type hints throughout
  - Standardized error handling
  - Consistent naming conventions

- **Service Architecture**
  - Replaced individual service scripts with unified CLI
  - Standardized port configuration (BR-KG: 5000, Agent: 8000)
  - Retired legacy Dash UI (8050) in favor of Next.js (3000) and Gradio (7860)
  - Improved service health checks

### 🗑️ Removed

- Duplicate tool implementations
- Scattered test files
- Individual startup scripts
- Redundant documentation files

### 🐛 Fixed

- BR-KG API port mismatch (5000 vs 5010)
- Module import errors
- Test coverage conflicts
- Docker build issues
- Git tracking of binary files

### 📝 Migration Guide

#### For Users

**Installation**:
```bash
# Old way
pip install -r requirements.txt
pip install -r requirements_full.txt

# New way
pip install -e ".[all]"
```

**Running Services**:
```bash
# Old way
./start_neurokg_gui.sh
python simple_cli.py

# New way
brain-researcher serve kg
brain-researcher chat
```

**Data Operations**:
```bash
# Old way
python add_sample_datasets.py
python query_neurokg_interactive.py

# New way
brain-researcher data load-samples
brain-researcher query search "your query"
```

#### For Developers

**Running Tests**:
```bash
# Old way
pytest services/agent/tests/
python test_framework_demo.py

# New way
brain-researcher test assess
brain-researcher test analyze
```

**Code Quality**:
```bash
# Old way
black .
flake8
mypy services/

# New way
pre-commit run --all-files
brain-researcher test analyze --tools all
```

### 📊 Statistics

- **Files removed**: 1,094 (binary files, logs, generated content)
- **Code issues fixed**: 471 out of 515
- **Test coverage target**: 80%
- **Docker image size reduction**: ~40%
- **CLI commands created**: 37

### 🙏 Acknowledgments

This modernization was inspired by the clean architecture patterns from:
- [Biomni](https://github.com/BioMNI/Biomni) - Multi-modal AI framework
- [LangGraph](https://github.com/langchain-ai/langgraph) - Graph-based agent orchestration

---

## Previous Versions

For changes prior to v2.0.0, see the [archived documentation](docs/archive/).
