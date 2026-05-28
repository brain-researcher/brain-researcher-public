from __future__ import annotations

from pathlib import Path

import pandas as pd

from brain_researcher.core.ingestion.loaders.neuromaps_parcellations import (
    AtlasFile,
    discover_atlas_files,
    insert_brain_regions,
    insert_part_of_relationships,
    read_table,
)
from brain_researcher.services.neurokg.graph.fake_graph_database import FakeGraphDB


def test_discover_and_read_tabular_atlas(tmp_path: Path) -> None:
    atlas_path = tmp_path / "demo_atlas.tsv"
    atlas_path.write_text("name\tnetwork\nRegion A\tControl\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

    atlas_files = discover_atlas_files(tmp_path)

    assert atlas_files == [AtlasFile(path=atlas_path, atlas="demo_atlas")]
    df = read_table(atlas_path)
    assert df.to_dict("records") == [
        {"name": "Region A", "network": "Control", "source_file": "demo_atlas.tsv"}
    ]


def test_insert_brain_regions_and_part_of_relationships() -> None:
    db = FakeGraphDB()
    atlas_file = AtlasFile(path=Path("demo.tsv"), atlas="demo")
    df = pd.DataFrame(
        [
            {"name": "Network A", "parent": ""},
            {"name": "Region A", "parent": "Network A"},
        ]
    )

    nodes_created, nodes_skipped, node_lookup, column_info = insert_brain_regions(
        db=db,
        atlas_file=atlas_file,
        df=df,
    )
    part_of_created, part_of_skipped = insert_part_of_relationships(
        db=db,
        atlas_file=atlas_file,
        df=df,
        node_id_lookup=node_lookup,
        parent_col=column_info["parent_col"],
        name_col=column_info["name_col"],
    )

    assert nodes_created == 2
    assert nodes_skipped == 0
    assert part_of_created == 1
    assert part_of_skipped == 0
    assert db.find_relationships(
        start_node="demo:region_a",
        end_node="demo:network_a",
        rel_type="PART_OF",
    )
