from __future__ import annotations


def test_dataset_resource_facade_uses_registered_collectors(monkeypatch) -> None:
    from brain_researcher.services.shared import dataset_resource_facade as facade

    calls: dict[str, object] = {}
    resource_sentinel = object()
    resolution_sentinel = object()

    def fake_collect(dataset_ref: str, **kwargs):
        calls["collect_ref"] = dataset_ref
        calls["collect_kwargs"] = kwargs
        return resource_sentinel

    def fake_resolve(user_text: str, **kwargs):
        calls["resolve_text"] = user_text
        calls["resolve_kwargs"] = kwargs
        return resolution_sentinel

    monkeypatch.setattr(facade, "_dataset_resource_collector", None)
    monkeypatch.setattr(facade, "_dataset_reference_resolver", None)
    facade.register_dataset_resource_resolvers(
        collect_dataset_resources=fake_collect,
        resolve_dataset_reference=fake_resolve,
    )

    resource = facade.collect_dataset_resources(
        "ds000001",
        dataset_version="1.0.0",
        analysis_goal="fmri",
        run_bids_validation=False,
    )
    resolution = facade.resolve_dataset_reference("motor task", mounts_path="/mnt")

    assert resource is resource_sentinel
    assert resolution is resolution_sentinel
    assert calls["collect_ref"] == "ds000001"
    assert calls["collect_kwargs"]["dataset_version"] == "1.0.0"
    assert calls["collect_kwargs"]["analysis_goal"] == "fmri"
    assert calls["collect_kwargs"]["run_bids_validation"] is False
    assert calls["resolve_text"] == "motor task"
    assert calls["resolve_kwargs"]["mounts_path"] == "/mnt"
