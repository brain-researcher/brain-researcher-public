"""Tests for the ONVOC tree loader utility."""

from __future__ import annotations

import yaml

from brain_researcher.services.neurokg.utils.onvoc_tree import (
    OnvocTree,
    OnvocTreeError,
)


def test_onvoc_tree_loads_nodes_and_constraints(tmp_path) -> None:
    payload = {
        "version": "0.1",
        "tree": [
            {
                "id": "ONVOC_ROOT",
                "label": "Root",
                "level": 1,
                "children": [
                    {
                        "id": "ONVOC_CHILD_A",
                        "label": "Child A",
                        "level": 2,
                    },
                    {
                        "id": "ONVOC_CHILD_B",
                        "label": "Child B",
                        "level": 2,
                        "alt_parents": ["ONVOC_ALT"],
                    },
                ],
            }
        ],
        "constraints": {
            "cannot_link": [
                {"ids": ["ONVOC_CHILD_A", "ONVOC_CHILD_B"], "reason": "siblings"}
            ]
        },
    }
    path = tmp_path / "tree.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    tree = OnvocTree.load(path)

    assert tree.nodes["ONVOC_CHILD_A"].parent_id == "ONVOC_ROOT"
    assert tree.nodes["ONVOC_CHILD_B"].alt_parents == ("ONVOC_ALT",)
    assert tree.conflicts_with("ONVOC_CHILD_A", ["ONVOC_CHILD_B"])
    assert tree.level("ONVOC_CHILD_B") == 2


def test_onvoc_tree_missing_tree_section(tmp_path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("{}", encoding="utf-8")
    try:
        OnvocTree.load(path)
    except OnvocTreeError as exc:
        assert "missing 'tree'" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected OnvocTreeError")

