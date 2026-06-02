"""
One-shot loader: register Yeo 2011 7/17 network atlases in Neo4j.

Reads existing Yeo assets from the flat atlas home (/app/data/atlases/yeo_2011
when available) or the legacy nilearn cache,
hashes the NIfTI files, parses the ColorLUT labels, and creates/links nodes:
  (:Atlas)-[:HAS_PARCELLATION]->(:Parcellation)-[:HAS_PARCEL]->(:Parcel)
  (:Parcellation)-[:IN_SPACE]->(:TemplateSpace {name:"MNI152"})
  (:Atlas)-[:CITES]->(:Publication {doi:"10.1152/jn.00338.2010"})

Usage (env):
    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=pass \
    python scripts/load_yeo_atlas_to_neo4j.py

Optional args:
    --base-dir /path/to/Yeo_JNeurophysiol11_MNI152
    --uri ... --user ... --password ...
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
from pathlib import Path
from typing import Dict, List
from os import getenv

from neo4j import GraphDatabase

from brain_researcher.services.tools.atlas_utils import (
    default_atlas_output_root,
    repo_data_dir,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("load_yeo_atlas")


def default_base_dir() -> Path:
    candidates = [
        default_atlas_output_root() / "yeo_2011",
        repo_data_dir()
        / "br_kg"
        / "raw"
        / "nilearn_atlases"
        / "yeo_2011"
        / "Yeo_JNeurophysiol11_MNI152",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_lut(lut_path: Path) -> List[Dict]:
    rows: List[Dict] = []
    for line in lut_path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = re.split(r"\s+", line.strip())
        if len(parts) < 2:
            continue
        idx = int(parts[0])
        label = " ".join(parts[1:])
        rows.append({"idx": idx, "label": label})
    return rows


def load_to_neo4j(
    uri: str,
    user: str,
    password: str,
    base_dir: Path,
) -> None:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    atlas_name = "Yeo2011"
    citation = {
        "doi": "10.1152/jn.00338.2010",
        "title": "The organization of the human cerebral cortex estimated by intrinsic functional connectivity",
        "year": 2011,
        "url": "https://doi.org/10.1152/jn.00338.2010",
    }

    parcs = [
        {
            "name": "Yeo2011-7",
            "nifti": base_dir
            / "Yeo2011_7Networks_MNI152_FreeSurferConformed1mm.nii.gz",
            "lut": base_dir / "Yeo2011_7Networks_ColorLUT.txt",
            "resolution_mm": 1.0,
            "space": "MNI152",
        },
        {
            "name": "Yeo2011-17",
            "nifti": base_dir
            / "Yeo2011_17Networks_MNI152_FreeSurferConformed1mm.nii.gz",
            "lut": base_dir / "Yeo2011_17Networks_ColorLUT.txt",
            "resolution_mm": 1.0,
            "space": "MNI152",
        },
    ]

    for parc in parcs:
        if not parc["nifti"].exists():
            raise FileNotFoundError(f"Missing NIfTI: {parc['nifti']}")
        if not parc["lut"].exists():
            raise FileNotFoundError(f"Missing LUT: {parc['lut']}")
        parc["sha256"] = sha256_file(parc["nifti"])
        parc["labels"] = parse_lut(parc["lut"])

    with driver.session() as session:
        # Atlas + citation
        session.run(
            """
            MERGE (a:Atlas {name:$atlas_name})
            SET a.source='Yeo2011', a.modality='fMRI'
            MERGE (pub:Publication {doi:$doi})
            SET pub.title=$title, pub.year=$year, pub.url=$url
            MERGE (a)-[:CITES]->(pub)
            """,
            atlas_name=atlas_name,
            **citation,
        )

        for parc in parcs:
            session.run(
                """
                MERGE (a:Atlas {name:$atlas_name})
                MERGE (p:Parcellation {name:$pname})
                SET p.space=$space, p.resolution_mm=$res, p.sha256=$sha, p.source_path=$path
                MERGE (a)-[:HAS_PARCELLATION]->(p)
                MERGE (t:TemplateSpace {name:$space})
                MERGE (p)-[:IN_SPACE]->(t)
                """,
                atlas_name=atlas_name,
                pname=parc["name"],
                space=parc["space"],
                res=parc["resolution_mm"],
                sha=parc["sha256"],
                path=str(parc["nifti"]),
            )

            # Parcels
            for row in parc["labels"]:
                session.run(
                    """
                    MATCH (p:Parcellation {name:$pname})
                    MERGE (c:Parcel {parcellation:$pname, index:$idx})
                    SET c.name=$label, c.label_raw=$label
                    MERGE (p)-[:HAS_PARCEL]->(c)
                    """,
                    pname=parc["name"],
                    idx=row["idx"],
                    label=row["label"],
                )

    driver.close()
    log.info("Loaded Yeo parcellations and parcels into Neo4j.")


def main():
    parser = argparse.ArgumentParser(
        description="Load Yeo2011 atlas (7/17) into Neo4j."
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=default_base_dir(),
        help=(
            "Directory containing Yeo2011_*Networks_* NIfTI and *_ColorLUT.txt files. "
            "Defaults to /app/data/atlases/yeo_2011 when available."
        ),
    )
    parser.add_argument(
        "--uri", default=None, help="Neo4j URI (default: env NEO4J_URI)"
    )
    parser.add_argument(
        "--user", default=None, help="Neo4j user (default: env NEO4J_USER)"
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Neo4j password (default: env NEO4J_PASSWORD/NEO4J_PASS)",
    )
    args = parser.parse_args()

    uri = args.uri or getenv("NEO4J_URI", "bolt://localhost:7687")
    user = args.user or getenv("NEO4J_USER")
    password = args.password or getenv("NEO4J_PASSWORD") or getenv("NEO4J_PASS")

    if not (user and password):
        parser.error(
            "Neo4j credentials missing (set --user/--password or NEO4J_USER/NEO4J_PASSWORD)"
        )

    load_to_neo4j(uri=uri, user=user, password=password, base_dir=args.base_dir)


if __name__ == "__main__":
    main()
