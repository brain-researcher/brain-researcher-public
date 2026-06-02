import json, os, re, tarfile
from pathlib import Path
from neo4j import GraphDatabase

NEO4J_URI=os.environ.get("NEO4J_URI")
NEO4J_USER=os.environ.get("NEO4J_USER")
NEO4J_PASSWORD=os.environ.get("NEO4J_PASSWORD")
NEO4J_DB=os.environ.get("NEO4J_DATABASE") or None
TAR_PATH=Path("/app/data/neurostore/task_info.tar.gz")

if not (NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD):
    raise SystemExit("Missing NEO4J env vars")
if not TAR_PATH.exists():
    raise SystemExit(f"Tarball not found: {TAR_PATH}")

DS_RE=re.compile(r"ds\d{6,}", re.IGNORECASE)

def extract_json(tf, member_name):
    try:
        f=tf.extractfile(member_name)
        if not f: return None
        return json.load(f)
    except Exception:
        return None

def iter_entries(tf):
    for m in tf.getmembers():
        if m.name.endswith("/results.json"):
            base=m.name[:-len("results.json")]
            info_name=base+"info.json"
            yield m.name, info_name

def find_dataset_ids(text):
    if not text: return []
    ids=set()
    for m in DS_RE.finditer(text):
        ds=m.group(0).lower()
        if not ds.startswith("ds"): ds="ds"+ds
        ids.add(f"ds:openneuro:{ds}")
    return list(ids)

def main():
    with tarfile.open(TAR_PATH, "r:gz") as tf:
        with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)) as driver:
            with driver.session(database=NEO4J_DB) as session:

                stats={"tasks_created":0,"tasks_merged":0,"links_created":0,"unlinked_tasks":0}

                for res_name, info_name in iter_entries(tf):
                    results=extract_json(tf,res_name) or {}
                    info=extract_json(tf,info_name) or {}
                    dbid=info.get("identifiers",{}).get("dbid")
                    pmid=info.get("identifiers",{}).get("pmid")
                    doi=info.get("identifiers",{}).get("doi")

                    study_text = results.get("StudyObjective", "")

                    tasks = (results.get("fMRITasks") or []) + (results.get("BehavioralTasks") or [])
                    for t in tasks:
                        if isinstance(t, str):
                            name = t
                            desc = ""
                        elif isinstance(t, dict):
                            name=t.get("TaskName") or t.get("name")
                            desc=t.get("TaskDescription") or t.get("Description") or ""
                        else:
                            continue
                        if not name: continue
                        blob=" ".join([x for x in [name, desc, study_text] if x])
                        ds_ids=find_dataset_ids(blob)

                        res=session.run(
                            """
                            MERGE (task:Task {name:$name})
                            ON CREATE SET task.source=$src, task.neurostore_id=$dbid, task.description=$desc
                            SET task.source = coalesce(task.source,$src),
                                task.pmid = coalesce(task.pmid,$pmid),
                                task.doi = coalesce(task.doi,$doi)
                            RETURN task, task.source IS NOT NULL AS existed
                            """,
                            {"name":name, "dbid":dbid, "desc":desc, "pmid":pmid, "doi":doi, "src":"neurostore"}
                        )
                        existed = res.single()
                        if existed is None:
                            continue
                        stats["tasks_created"] += 0 if existed["existed"] else 1
                        stats["tasks_merged"] += 1

                        if ds_ids:
                            for ds in ds_ids:
                                link_res=session.run(
                                    """
                                    MATCH (d:Dataset {id:$ds})
                                    MERGE (d)-[:HAS_TASK]->(task:Task {name:$name})
                                    SET task.source = coalesce(task.source,neurostore)
                                    RETURN d
                                    """,
                                    {"ds":ds, "name":name}
                                ).single()
                                if link_res:
                                    stats["links_created"] +=1
                        else:
                            stats["unlinked_tasks"] +=1

                print("Ingestion complete:", stats)

if __name__ == "__main__":
    main()
