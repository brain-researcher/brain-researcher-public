import csv
import sys
from collections import defaultdict
from pathlib import Path


def prune_rank(
    in_csv: str | Path, out_csv: str | Path, min_conf: float = 0.5, top_k: int = 10
) -> None:
    with open(in_csv, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    grouped = defaultdict(list)
    for r in rows:
        conf = float(r.get("overall_confidence", 0))
        if conf >= min_conf:
            key = (r["dataset_id"], r["contrast_name"])
            grouped[key].append(r)

    fields = reader.fieldnames
    with open(out_csv, "w", newline="") as fo:
        writer = csv.DictWriter(fo, fieldnames=fields)
        writer.writeheader()
        for key, recs in grouped.items():
            recs.sort(key=lambda x: float(x.get("overall_confidence", 0)), reverse=True)
            for r in recs[:top_k]:
                writer.writerow(r)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python prune_rank.py scored.csv out.csv")
        sys.exit(1)
    prune_rank(sys.argv[1], sys.argv[2])
