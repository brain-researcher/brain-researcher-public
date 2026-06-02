import os, csv, re
from pathlib import Path
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
NEO4J_DB = os.environ.get("NEO4J_DATABASE") or None

if not (NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD):
    raise SystemExit("NEO4J_* env vars not set")

tmpdir = Path("tmp")
tmpdir.mkdir(exist_ok=True)

def run_query(session, cypher, params=None):
    return list(session.run(cypher, params or {}))

def write_csv(path, rows, header):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")

with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
    with driver.session(database=NEO4J_DB) as session:
        # 1) dataset_task_map
        rows = run_query(session, """
            MATCH (d:Dataset:DataResource)-[:HAS_TASK]->(t:Task)
            RETURN d.id AS dataset_id, t.name AS task_name, coalesce(t.id, t.neurostore_id) AS task_id
        """)
        dataset_task_rows = [[r["dataset_id"], r.get("task_name"), r.get("task_id")] for r in rows]
        write_csv(tmpdir / "dataset_task_map.csv", dataset_task_rows, ["dataset_id", "task_name", "task_id"])

        # 2) task_contrast_map
        rows = run_query(session, """
            MATCH (t:Task)-[:HAS_CONTRAST]->(c:Contrast)
            RETURN t.name AS task_name, c.name AS contrast_name,
                   coalesce(t.id, t.neurostore_id) AS task_id, coalesce(c.id, c.neurostore_id) AS contrast_id
        """)
        task_contrast_rows = [[r.get("task_name"), r.get("contrast_name"), r.get("task_id"), r.get("contrast_id")] for r in rows]
        write_csv(tmpdir / "task_contrast_map.csv", task_contrast_rows, ["task_name", "contrast_name", "task_id", "contrast_id"])

        # 3) statmap_links - glmfitlins attached to dataset
        rows = run_query(session, """
            MATCH (d:Dataset:DataResource)-[:HAS_STATMAP]->(m:StatMap)
            WHERE m.source = "openneuro_glmfitlins"
            RETURN m.id AS statmap_id, d.id AS dataset_id, m.source AS source,
                   m.map_type AS map_type, m.contrast_name AS contrast_name
        """)
        glm_rows = [[r.get("statmap_id"), r.get("dataset_id"), r.get("source"), r.get("map_type"), r.get("contrast_name")] for r in rows]

        # 3b) statmap_links - neurovault candidates via regex of ds id
        rows = run_query(session, """
            MATCH (m:StatMap)
            WHERE m.source = "neurovault"
            RETURN m.id AS statmap_id,
                   coalesce(m.collection_name,"") AS cname,
                   coalesce(m.description,"") AS descr,
                   coalesce(m.name,"") AS mname,
                   m.map_type AS map_type,
                   coalesce(m.contrast_definition, m.contrast_name, m.name,"") AS contrast_name
        """)
        nv_rows = []
        for r in rows:
            blob = " ".join([r.get("cname", ""), r.get("descr", ""), r.get("mname", "")])
            m = re.search(r"ds\d{6,}", blob, re.IGNORECASE)
            if m:
                ds_hit = m.group(0).lower()
                if not ds_hit.startswith("ds"):
                    ds_hit = "ds" + ds_hit
                dataset_id = f"ds:openneuro:{ds_hit}"
            else:
                dataset_id = ""
            nv_rows.append([r.get("statmap_id"), dataset_id, "neurovault", r.get("map_type"), r.get("contrast_name")])

        statmap_rows = glm_rows + nv_rows
        write_csv(tmpdir / "statmap_links.csv", statmap_rows, ["statmap_id", "dataset_id", "source", "map_type", "contrast_name"])

        # 4) subjectgroup_phenotype
        rows = run_query(session, """
            MATCH (d:Dataset:DataResource)-[:HAS_SUBJECT_GROUP]->(g:SubjectGroup)-[:HAS_PHENOTYPE]->(p:Phenotype)
            RETURN d.id AS dataset_id, g.label AS group_label, p.label AS phenotype_label
        """)
        sg_rows = [[r.get("dataset_id"), r.get("group_label"), r.get("phenotype_label")] for r in rows]
        write_csv(tmpdir / "subjectgroup_phenotype.csv", sg_rows, ["dataset_id", "group_label", "phenotype_label"])
