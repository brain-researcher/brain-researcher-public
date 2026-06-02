from pathlib import Path

from brain_researcher.core.ingestion.loaders.openneuro_glm_loader import (
    OpenNeuroGLMFitlinsLoader,
)
from brain_researcher.core.ingestion.loaders.openneuro_glm_spec_parser import TaskSpec


class FakeOnvocLinker:
    available = True


class FakeConstructManager:
    def process_ids_for_concepts(self, concept_ids):
        return set(concept_ids)

    def link_entity_to_processes(self, *args, **kwargs):
        return 0


def _loader() -> OpenNeuroGLMFitlinsLoader:
    # _build_taskspec_properties does not require full loader initialization.
    return object.__new__(OpenNeuroGLMFitlinsLoader)


def test_taskspec_properties_events_present_true_when_column_names_exist() -> None:
    loader = _loader()
    spec = TaskSpec(
        dataset_id="ds000001",
        task_name="nback",
        spec_path=Path("/tmp/ds000001-nback_specs.json"),
        task_metadata={"column_names": ["onset", "duration", "trial_type"]},
    )

    props = loader._build_taskspec_properties(spec)

    assert props["events_present"] is True
    assert props["events_metadata_source"] == "column_names_proxy"
    assert props["column_names"] == ["onset", "duration", "trial_type"]


def test_taskspec_properties_events_present_false_is_retained() -> None:
    loader = _loader()
    spec = TaskSpec(
        dataset_id="ds000002",
        task_name="stroop",
        spec_path=Path("/tmp/ds000002-stroop_specs.json"),
        task_metadata={"column_names": []},
    )

    props = loader._build_taskspec_properties(spec)

    assert "events_present" in props
    assert props["events_present"] is False
    assert props["events_metadata_source"] == "column_names_proxy"


def test_service_helpers_are_injected_and_cached(tmp_path: Path) -> None:
    onvoc_calls = []
    construct_calls = []

    def onvoc_factory(db):
        onvoc_calls.append(db)
        return FakeOnvocLinker()

    def construct_factory(db):
        construct_calls.append(db)
        return FakeConstructManager()

    loader = OpenNeuroGLMFitlinsLoader(
        datasets_root=tmp_path,
        onvoc_linker_factory=onvoc_factory,
        construct_manager_factory=construct_factory,
    )
    db = object()

    assert isinstance(loader._ensure_onvoc_linker(db), FakeOnvocLinker)
    assert isinstance(loader._ensure_onvoc_linker(db), FakeOnvocLinker)
    assert isinstance(loader._get_construct_manager(db), FakeConstructManager)
    assert isinstance(loader._get_construct_manager(db), FakeConstructManager)
    assert onvoc_calls == [db]
    assert construct_calls == [db]
