import csv
import sys
from pathlib import Path


def write_edges(in_csv: str | Path, out_csv: str | Path) -> None:
    fields = [
        "dataset_id",
        "contrast_name",
        "concept_id",
        "direction",
        "overall_confidence",
        "methods_used",
        "ns_z",
    ]

    with open(in_csv, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    with open(out_csv, "w", newline="") as fo:
        writer = csv.DictWriter(fo, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "dataset_id": r.get("dataset_id"),
                    "contrast_name": r.get("contrast_name"),
                    "concept_id": r.get("concept_id"),
                    "direction": r.get("direction", "0"),
                    "overall_confidence": r.get("overall_confidence", 0),
                    "methods_used": r.get("methods", ""),
                    "ns_z": r.get("ns_z", 0),
                }
            )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python write_edges.py pruned.csv measures_edges_FINAL.csv")
        sys.exit(1)
    write_edges(sys.argv[1], sys.argv[2])
