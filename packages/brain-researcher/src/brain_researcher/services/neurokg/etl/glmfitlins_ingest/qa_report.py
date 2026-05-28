#!/usr/bin/env python3
"""Simple QA checks for Neo4j import CSVs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

OUT_DIR = Path("data/etl_cache/glmfitlins_ingest")
REPORT_HTML = OUT_DIR / "qa_glmfitlins.html"


def load_csv(path: Path):
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def main(out_dir: Path = OUT_DIR) -> None:
    datasets = load_csv(out_dir / "datasets.csv")
    contrasts = load_csv(out_dir / "contrasts.csv")
    edges = load_csv(out_dir / "measures_edges.csv")

    n_datasets = len(datasets)
    n_contrasts = len(contrasts)
    n_edges = len(edges)

    conf_good = sum(float(e.get("overall_confidence", 0) or 0) >= 0.5 for e in edges)
    conf_ratio = (conf_good / n_edges * 100) if n_edges else 0

    html = f"""
    <html><body>
    <h1>GLMFITLINS QA Report</h1>
    <ul>
    <li>Datasets: {n_datasets}</li>
    <li>Contrasts: {n_contrasts}</li>
    <li>Edges: {n_edges}</li>
    <li>High-confidence edges: {conf_ratio:.1f}%</li>
    </ul>
    </body></html>
    """
    report_html = out_dir / "qa_glmfitlins.html"
    report_html.write_text(html)
    print(f"QA report written to {report_html}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate QA report")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    main(args.out_dir)
