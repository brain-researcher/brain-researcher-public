import json
from pathlib import Path
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent.parent
manifest_path = ROOT / "data" / "neurosynth_maps" / "manifest.json"

def main():
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
    manifest = json.loads(manifest_path.read_text())
    updated = 0
    with driver.session() as sess:
        for entry in manifest:
            term = entry.get("term")
            z_rel = entry.get("z_map")
            if not term or not z_rel:
                continue
            # match statmap id
            stat_id = f"neurosynth_statmap:{term}"
            abs_path = (ROOT / z_rel).resolve()
            if not abs_path.exists():
                print(f"[warn] missing file for {stat_id}: {abs_path}")
                continue
            sess.run(
                """
                MATCH (m:StatMap {id:$id})
                SET m.path = $path,
                    m.map_type = coalesce(m.map_type, 'z'),
                    m.source = coalesce(m.source, 'neurosynth'),
                    m.is_thresholded = false,
                    m.updated_at = timestamp()
                RETURN m.id
                """,
                id=stat_id,
                path=str(abs_path),
            )
            updated += 1
    print(f"Updated {updated} statmaps")

if __name__ == "__main__":
    main()
