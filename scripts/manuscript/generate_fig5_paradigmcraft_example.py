#!/usr/bin/env python
"""Generate a KG-backed example JSON output for Fig 5 — ParadigmCraft (UC3).

This produces a concrete, machine-readable payload that can be used to drive
Fig 5 panels (b/c/d) and to demonstrate “knowledge → decision” conversion.

Default output:
  - docs/figures/fig5_paradigmcraft_example.json

Run:
  python scripts/manuscript/generate_fig5_paradigmcraft_example.py
  python scripts/manuscript/generate_fig5_paradigmcraft_example.py --out /data/fig5/uc3.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from brain_researcher.services.br_kg import query_service

EVIDENCE = {
    1: "neurostore_task:4Nhft7XEBgbN:fmri:0",  # Psychomotor Vigilance Task (PVT)
    2: "trm_50b55d8a6da00",  # PEBL Perceptual Vigilance Task
    3: "ds:openneuro:ds003673",  # pupillometry + fMRI example dataset
    4: "tsk_4a57abb949a4f",  # Eriksen flanker task
    5: "trm_551f0857e1db8",  # ANT task (alerting/orienting/executive)
    6: "cnt_52b4cfac3a8ce",  # alerting contrast
    7: "trm_59d184d0980bf",  # arousal (physical)
    8: "trm_4aae62e4ad209",  # cognitive control
    9: "ONVOC_0000096",  # rostral anterior cingulate cortex
    10: "neurostore_task:4KT9kAm9CTGq:fmri:0",  # Task Switching Paradigm
    11: "ds:openneuro:ds000102",  # flanker fMRI dataset
}


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("docs") / "figures" / "fig5_paradigmcraft_example.json",
        help="Output JSON path",
    )
    ap.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation (default: 2)",
    )
    return ap.parse_args()


def _snippet(props: dict) -> str | None:
    for key in ("definition", "description"):
        val = props.get(key)
        if isinstance(val, str) and val.strip():
            txt = " ".join(val.strip().split())
            return (txt[:220] + "…") if len(txt) > 220 else txt
    blob = props.get("search_blob")
    if isinstance(blob, str) and blob.strip():
        txt = " ".join(blob.strip().split())
        return (txt[:220] + "…") if len(txt) > 220 else txt
    return None


def _evidence_obj(kg_id: str) -> dict:
    node = query_service.node_details(kg_id)
    if node is None:
        return {"kg_id": kg_id, "missing": True}
    props = node.properties or {}
    labels = props.get("labels") if isinstance(props.get("labels"), list) else None
    out: dict = {
        "kg_id": node.kg_id,
        "label": node.label,
        "node_type": node.node_type,
        "labels": labels,
    }
    src = props.get("source") or props.get("source_repo")
    if isinstance(src, str) and src.strip():
        out["source"] = src
    url = props.get("primary_url")
    if isinstance(url, str) and url.strip():
        out["primary_url"] = url
    nsub = props.get("subjects_count")
    if isinstance(nsub, int):
        out["subjects_count"] = nsub
    snippet = _snippet(props)
    if snippet:
        out["snippet"] = snippet
    return out


def main() -> None:
    args = _parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    query_service.get_default_db.cache_clear()

    result = {
        "use_case": "UC3.ParadigmCraft",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": {
            "hypotheses": [
                {
                    "id": "H1",
                    "color": "blue",
                    "claim": "Performance variability driven by arousal fluctuations",
                },
                {
                    "id": "H2",
                    "color": "orange",
                    "claim": "…driven by executive control lapses",
                },
            ],
            "constraints": {
                "participants": "healthy young adults",
                "species": "human",
                "scanner": "3T fMRI",
                "max_duration_min": 45,
            },
        },
        "candidates_top3": [
            {
                "id": "D1",
                "title": "Psychomotor Vigilance + Pupillometry",
                "template_type": "single_paradigm",
                "kg_refs": {
                    "task": EVIDENCE[1],
                    "maps_to": EVIDENCE[2],
                    "example_dataset": EVIDENCE[3],
                },
            },
            {
                "id": "D2",
                "title": "ANT / Flanker × Alerting cue (arousal proxy)",
                "template_type": "decoupled_crossed_factors",
                "kg_refs": {
                    "task": EVIDENCE[5],
                    "flanker": EVIDENCE[4],
                    "alerting_contrast": EVIDENCE[6],
                    "example_dataset": EVIDENCE[11],
                },
            },
            {
                "id": "D3",
                "title": "Multi-task (Task Switching) + physiological monitoring",
                "template_type": "orthogonal_template",
                "kg_refs": {
                    "task": EVIDENCE[10],
                    "control_construct": EVIDENCE[8],
                    "arousal_construct": EVIDENCE[7],
                },
            },
        ],
        # NOTE: Scores/winner/recommended_output are currently a demonstration template.
        # For a “real” pipeline, compute these from KG-derived features + constraints.
        "scorecard": {
            "dimensions": [
                "Construct Validity",
                "Sensitivity",
                "Specificity/Confound Risk",
                "Discriminability",
                "Feasibility",
            ],
            "rows": [
                {
                    "candidate": "D1",
                    "cells": {
                        "Construct Validity": {
                            "score": 4.0,
                            "evidence": "vigilance",
                            "evidence_ids": [1, 2],
                        },
                        "Sensitivity": {
                            "score": 4.3,
                            "evidence": "RT+pupil",
                            "evidence_ids": [3],
                        },
                        "Specificity/Confound Risk": {
                            "score": 2.7,
                            "evidence": "fatigue",
                            "evidence_ids": [2],
                        },
                        "Discriminability": {
                            "score": 3.0,
                            "evidence": "single-factor",
                            "evidence_ids": [],
                        },
                        "Feasibility": {
                            "score": 4.6,
                            "evidence": "simple",
                            "evidence_ids": [],
                        },
                    },
                },
                {
                    "candidate": "D2",
                    "cells": {
                        "Construct Validity": {
                            "score": 4.8,
                            "evidence": "alerting+conflict",
                            "evidence_ids": [5, 6, 4],
                        },
                        "Sensitivity": {
                            "score": 4.2,
                            "evidence": "RT effect",
                            "evidence_ids": [4, 11],
                        },
                        "Specificity/Confound Risk": {
                            "score": 3.8,
                            "evidence": "factorial",
                            "evidence_ids": [5],
                        },
                        "Discriminability": {
                            "score": 5.0,
                            "evidence": "crossed-test",
                            "evidence_ids": [5, 6],
                        },
                        "Feasibility": {
                            "score": 4.2,
                            "evidence": "existing fMRI",
                            "evidence_ids": [11],
                        },
                    },
                },
                {
                    "candidate": "D3",
                    "cells": {
                        "Construct Validity": {
                            "score": 3.8,
                            "evidence": "control suite",
                            "evidence_ids": [10, 8],
                        },
                        "Sensitivity": {
                            "score": 4.0,
                            "evidence": "multi-signal",
                            "evidence_ids": [10, 3],
                        },
                        "Specificity/Confound Risk": {
                            "score": 3.0,
                            "evidence": "switch-cost",
                            "evidence_ids": [10],
                        },
                        "Discriminability": {
                            "score": 4.0,
                            "evidence": "orthogonal",
                            "evidence_ids": [10],
                        },
                        "Feasibility": {
                            "score": 3.0,
                            "evidence": "complex",
                            "evidence_ids": [],
                        },
                    },
                },
            ],
            "winner": "D2",
        },
        "recommended_output": {
            "recommended_candidate": "D2",
            "diverging_predictions": [
                {
                    "hypothesis": "H1",
                    "statement": "pupil diameter predicts RT variability ⟂ conflict level",
                    "kg_support": [7, 3],
                },
                {
                    "hypothesis": "H2",
                    "statement": "ACC activation predicts RT variability ⟂ alerting/arousal state",
                    "kg_support": [9, 8],
                },
            ],
            "analysis_skeleton": [
                "Preprocess fMRI + pupil (QA, alignment)",
                "Compute RT variability and task factors (conflict × alerting)",
                "Fit competing models and compare (interaction/conditional-independence)",
            ],
        },
        "evidence_index": {str(k): _evidence_obj(v) for k, v in EVIDENCE.items()},
    }

    args.out.write_text(
        json.dumps(result, indent=int(args.indent), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("Wrote", args.out)


if __name__ == "__main__":
    main()
