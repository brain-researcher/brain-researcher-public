import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


def _load_matches(path: str | Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _load_llm_annotations(
    llm_dir: str | Path,
) -> dict[tuple[str, str], list[dict[str, str]]]:
    result: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    llm_dir = Path(llm_dir)
    if not llm_dir.exists():
        return result
    for jf in llm_dir.glob("*.json"):
        with open(jf) as f:
            data = json.load(f)
        for entry in data:
            dataset = entry.get("dataset_id", "")
            contrast = entry.get("contrast_name", "")
            for c in entry.get("constructs", []):
                cid = c.get("id") or c.get("concept_id")
                if not cid:
                    continue
                result[(dataset, contrast)].append(
                    {
                        "concept_id": cid,
                        "direction": str(c.get("direction", "0")),
                        "llm_conf": float(
                            c.get("llm_confidence", c.get("confidence", 0))
                        ),
                    }
                )
    return result


def merge_candidates(
    exact_csv: str | Path,
    embed_csv: str | Path,
    llm_dir: str | Path,
    out_csv: str | Path,
) -> None:
    exact = _load_matches(exact_csv)
    embed = _load_matches(embed_csv)
    llm = _load_llm_annotations(llm_dir)

    merged: dict[tuple[str, str, str], dict[str, any]] = {}

    for row in exact + embed:
        key = (row["dataset_id"], row["contrast_name"], row["concept_id"])
        rec = merged.setdefault(
            key,
            {
                "dataset_id": row["dataset_id"],
                "contrast_name": row["contrast_name"],
                "concept_id": row["concept_id"],
                "methods": set(),
                "exact_conf": 0.0,
                "fuzzy_conf": 0.0,
                "embed_conf": 0.0,
                "llm_conf": 0.0,
                "direction": "0",
                "ns_z": 0.0,
            },
        )
        method = row.get("method")
        if method == "exact":
            rec["exact_conf"] = max(rec["exact_conf"], float(row.get("confidence", 0)))
        elif method == "fuzzy":
            rec["fuzzy_conf"] = max(rec["fuzzy_conf"], float(row.get("confidence", 0)))
        elif method == "embed":
            rec["embed_conf"] = max(rec["embed_conf"], float(row.get("confidence", 0)))
        if method:
            rec["methods"].add(method)

    for (ds, c), vals in llm.items():
        for v in vals:
            key = (ds, c, v["concept_id"])
            rec = merged.setdefault(
                key,
                {
                    "dataset_id": ds,
                    "contrast_name": c,
                    "concept_id": v["concept_id"],
                    "methods": set(),
                    "exact_conf": 0.0,
                    "fuzzy_conf": 0.0,
                    "embed_conf": 0.0,
                    "llm_conf": 0.0,
                    "direction": "0",
                    "ns_z": 0.0,
                },
            )
            rec["llm_conf"] = max(rec["llm_conf"], v.get("llm_conf", 0.0))
            rec["direction"] = v.get("direction", "0")
            rec["methods"].add("llm")

    fields = [
        "dataset_id",
        "contrast_name",
        "concept_id",
        "direction",
        "exact_conf",
        "fuzzy_conf",
        "embed_conf",
        "llm_conf",
        "ns_z",
        "methods",
    ]
    with open(out_csv, "w", newline="") as fo:
        writer = csv.DictWriter(fo, fieldnames=fields)
        writer.writeheader()
        for rec in merged.values():
            rec_copy = rec.copy()
            rec_copy["methods"] = "+".join(sorted(rec_copy.pop("methods")))
            writer.writerow(rec_copy)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(
            "Usage: python merge_candidates.py matches_exact_fuzzy.csv matches_embed.csv llm_dir output.csv"
        )
        sys.exit(1)
    merge_candidates(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
