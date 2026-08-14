from __future__ import annotations

import ast
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from pathlib import Path

import pytest
import yaml

from brain_researcher.autoresearch.canonical_program_registry import (
    CANONICAL_PROGRAM_REGISTRY,
    CanonicalProgramConflictError,
    CanonicalProgramDescriptor,
    CanonicalProgramDuplicateError,
    CanonicalProgramKey,
    CanonicalProgramLaunchPlanV1,
    CanonicalProgramNotRegisteredError,
    CanonicalProgramRegistry,
    RegisteredCanonicalProgram,
)
from brain_researcher.autoresearch.episode_paths import (
    AUTORESEARCH_DATA_ROOT_ENV,
    EPISODE_ADDRESS_SCHEMA_VERSION,
    EPISODE_LAYOUT_VERSION,
    EpisodeAddressV1,
    EpisodePaths,
    resolve_autoresearch_data_root,
)


@dataclass(frozen=True)
class _Adapter:
    descriptor: CanonicalProgramDescriptor
    authorization_resolver: Callable[..., object]
    launch_plan_builder: Callable[..., CanonicalProgramLaunchPlanV1]
    episode_preparer: Callable[..., Mapping[str, object]] | None = None
    goal_confirmation_adopter: Callable[..., object] | None = None
    scientific_goal_confirmation_adopter: Callable[..., object] | None = None


def _authorization_resolver(**_kwargs: object) -> object:
    return object()


def _launch_plan_builder(**_kwargs: object) -> CanonicalProgramLaunchPlanV1:
    return CanonicalProgramLaunchPlanV1(
        scenario="fixture",
        plan={"steps": [], "execution": {"approval_level": "confirm"}},
    )


def _episode_preparer(**_kwargs: object) -> Mapping[str, object]:
    return {
        "execution_authorized": False,
        "execution_started": False,
        "scientific_outcome": None,
    }


def _adapter(
    *,
    program_id: str = "example-program",
    program_version: str = "v1",
    executor_id: str = "example-executor",
    executor_version: str = "v1",
    admission: bool = False,
) -> _Adapter:
    return _Adapter(
        descriptor=CanonicalProgramDescriptor(
            key=CanonicalProgramKey(
                program_id=program_id,
                program_version=program_version,
                executor_id=executor_id,
                executor_version=executor_version,
            )
        ),
        authorization_resolver=_authorization_resolver,
        launch_plan_builder=_launch_plan_builder,
        episode_preparer=_episode_preparer if admission else None,
    )


def _imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _brain_researcher_imports(modules: set[str]) -> set[str]:
    return {
        module
        for module in modules
        if module == "brain_researcher" or module.startswith("brain_researcher.")
    }


def test_registry_is_empty_and_resolves_only_exact_program_executor_identity() -> None:
    registry = CanonicalProgramRegistry()
    adapter = _adapter()

    assert registry.registered_descriptors() == ()
    assert registry.register(adapter) == adapter.descriptor
    registered = registry.resolve(
        program_id="example-program",
        program_version="v1",
        executor_id="example-executor",
        executor_version="v1",
    )
    assert isinstance(registered, RegisteredCanonicalProgram)
    assert registered.hook is adapter
    with pytest.raises(CanonicalProgramNotRegisteredError):
        registry.resolve(
            program_id="example-program",
            program_version="v1",
            executor_id="example-executor",
            executor_version="v2",
        )
    with pytest.raises(CanonicalProgramDuplicateError):
        registry.register(adapter)
    with pytest.raises(CanonicalProgramConflictError):
        registry.register(_adapter())


def test_registry_preserves_full_hook_revalidation_and_admission_semantics() -> None:
    registry = CanonicalProgramRegistry()
    admitted = _adapter(admission=True)

    registry.register(admitted)
    resolved = registry.resolve_admission_program(program_id="example-program")
    assert resolved.hook is admitted
    assert resolved.episode_preparer is _episode_preparer

    @dataclass
    class MutableAdapter:
        descriptor: CanonicalProgramDescriptor
        authorization_resolver: Callable[..., object] = _authorization_resolver
        launch_plan_builder: Callable[..., CanonicalProgramLaunchPlanV1] = (
            _launch_plan_builder
        )
        episode_preparer: Callable[..., Mapping[str, object]] | None = None
        goal_confirmation_adopter: Callable[..., object] | None = None
        scientific_goal_confirmation_adopter: Callable[..., object] | None = None

    mutable_registry = CanonicalProgramRegistry()
    mutable = MutableAdapter(_adapter().descriptor)
    mutable_registry.register(mutable)
    mutable.authorization_resolver = lambda: object()
    with pytest.raises(CanonicalProgramConflictError, match="changed"):
        mutable_registry.resolve(
            program_id="example-program",
            program_version="v1",
            executor_id="example-executor",
            executor_version="v1",
        )


def test_registry_contract_keeps_the_canonical_four_part_key_and_no_imports() -> None:
    import brain_researcher.autoresearch.canonical_program_registry as registry_module

    imports = _imported_modules(Path(registry_module.__file__).read_text())

    assert {field.name for field in fields(CanonicalProgramKey)} == {
        "program_id",
        "program_version",
        "executor_id",
        "executor_version",
    }
    assert {field.name for field in fields(CanonicalProgramDescriptor)} == {
        "key",
        "schema_version",
    }
    assert set(inspect.signature(CanonicalProgramRegistry.resolve).parameters) == {
        "self",
        "program_id",
        "program_version",
        "executor_id",
        "executor_version",
    }
    assert {
        name
        for name, value in inspect.getmembers(
            CanonicalProgramRegistry, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    } == {
        "register",
        "registered_descriptors",
        "registered_goal_confirmation_programs",
        "registered_scientific_goal_confirmation_programs",
        "resolve",
        "resolve_admission_program",
    }
    assert _brain_researcher_imports(imports) == set()
    assert CANONICAL_PROGRAM_REGISTRY.registered_descriptors() == ()


def test_private_import_detector_checks_import_from_modules() -> None:
    imports = _imported_modules(
        """
from brain_researcher.services.private import adapter
from brain_researcher.private import program
"""
    )

    assert _brain_researcher_imports(imports) == {
        "brain_researcher.private",
        "brain_researcher.services.private",
    }


def test_episode_paths_derive_the_complete_canonical_tree_without_writing(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "brain-researcher-data"
    paths = EpisodePaths.from_ids(
        data_root=data_root,
        line_id="example-line",
        owner_key="workspace:researcher",
        campaign_id="campaign-001",
        round_id="round-001",
        episode_id="episode-001",
    )
    episode_root = (
        data_root
        / "research"
        / "example-line"
        / "owners"
        / "workspace:researcher"
        / "campaigns"
        / "campaign-001"
        / "rounds"
        / "round-001"
        / "episodes"
        / "episode-001"
    )
    run = paths.run("run-001")

    assert paths.inputs_root == data_root / "research" / "example-line" / "inputs"
    assert paths.sources_root == data_root / "research" / "example-line" / "sources"
    assert paths.episode_root == episode_root
    assert paths.registration_root == episode_root / "registration"
    assert paths.authority_root == episode_root / "authority"
    assert paths.control_root == episode_root / "control"
    assert paths.runs_root == episode_root / "runs"
    assert run.run_root == episode_root / "runs" / "run-001"
    assert run.execution_root == run.run_root / "execution"
    assert run.outputs_root == run.run_root / "outputs"
    assert run.society_root == run.run_root / "society"
    assert run.public_root == run.run_root / "public"
    assert run.private_root == run.run_root / "private"
    assert paths.to_dict()["layout_version"] == EPISODE_LAYOUT_VERSION
    assert not data_root.exists()


def test_episode_paths_unset_env_uses_the_canonical_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(AUTORESEARCH_DATA_ROOT_ENV, raising=False)

    assert (
        resolve_autoresearch_data_root()
        == (Path.home() / ".local" / "share" / "brain-researcher").resolve()
    )


def test_episode_paths_empty_env_uses_the_canonical_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AUTORESEARCH_DATA_ROOT_ENV, "")

    assert (
        resolve_autoresearch_data_root()
        == (Path.home() / ".local" / "share" / "brain-researcher").resolve()
    )


def test_episode_paths_explicit_root_and_env_override_the_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_root = tmp_path / "env-root"
    explicit_root = tmp_path / "explicit-root"
    monkeypatch.setenv(AUTORESEARCH_DATA_ROOT_ENV, str(env_root))

    assert resolve_autoresearch_data_root() == env_root.resolve()
    assert resolve_autoresearch_data_root(explicit_root) == explicit_root.resolve()


@pytest.mark.parametrize("invalid", ["", " ", ".", "..", "a/b", "a\\b", "a\x00b"])
def test_episode_address_validates_exact_v1_components(invalid: str) -> None:
    with pytest.raises(ValueError):
        EpisodeAddressV1(
            line_id="example-line",
            owner_key="workspace:researcher",
            campaign_id="campaign-001",
            round_id="round-001",
            episode_id=invalid,
        )


def test_episode_address_round_trips_the_canonical_schema() -> None:
    address = EpisodeAddressV1(
        line_id="example-line",
        owner_key="workspace:researcher",
        campaign_id="campaign-001",
        round_id="round-001",
        episode_id="episode-001",
    )

    assert address.to_dict()["schema_version"] == EPISODE_ADDRESS_SCHEMA_VERSION
    assert EpisodeAddressV1.from_dict(address.to_dict()) == address
    with pytest.raises(ValueError, match="fields must match"):
        EpisodeAddressV1.from_dict({**address.to_dict(), "status": "completed"})


def test_machine_readable_manifest_is_limited_to_the_public_foundations() -> None:
    manifest_path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "contracts"
        / "autoresearch_public_foundations_v1.yaml"
    )
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    assert manifest["implementation_status"] == "contract_only"
    assert manifest["authority"] == "none"
    assert set(manifest["implemented"]) == {
        "canonical_program_registry",
        "episode_paths",
    }
    assert manifest["implemented"]["canonical_program_registry"]["identity_fields"] == [
        "program_id",
        "program_version",
        "executor_id",
        "executor_version",
    ]
    assert (
        manifest["implemented"]["canonical_program_registry"]["authorization_terms"]
        == "deferred"
    )
    assert manifest["implemented"]["episode_paths"]["default_data_root"] == (
        "~/.local/share/brain-researcher"
    )
    assert "goal handoff and candidate bundles" in manifest["deferred_to_pr_b"]
