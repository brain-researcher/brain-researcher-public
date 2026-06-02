import csv
import sys
from pathlib import Path


def _ns_support(z: float) -> float:
    if z >= 5:
        return 1.0
    if z >= 3:
        return 0.7
    return 0.0


def cal_score(in_csv: str | Path, out_csv: str | Path) -> None:
    with open(in_csv, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    fields = reader.fieldnames + ["overall_confidence"] if reader.fieldnames else []
    with open(out_csv, "w", newline="") as fo:
        writer = csv.DictWriter(fo, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            exact = float(r.get("exact_conf", 0))
            fuzzy = float(r.get("fuzzy_conf", 0))
            embed = float(r.get("embed_conf", 0))
            llm = float(r.get("llm_conf", 0))
            ns_z = float(r.get("ns_z", 0))
            overall = (
                0.5 * max(exact, fuzzy, embed) + 0.3 * llm + 0.2 * _ns_support(ns_z)
            )
            r["overall_confidence"] = f"{overall:.3f}"
            writer.writerow(r)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python cal_score.py merged.csv out.csv")
        sys.exit(1)
    cal_score(sys.argv[1], sys.argv[2])
