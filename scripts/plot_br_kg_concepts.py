#!/usr/bin/env python
"""
Visualize BR-KG concepts in 2D with embeddings, colored by ONVOC/ConceptClass.

Outputs:
- data/br-kg_exports/plots/concept_tsne.png
- data/br-kg_exports/concept_embeddings.csv (id,label,class,x,y)

Requirements: neo4j creds in env (.env), sentence-transformers, matplotlib, scikit-learn.
Run:
    set -a && source .env && set +a && \
    PYTHONUNBUFFERED=1 python scripts/plot_br_kg_concepts.py
"""
from __future__ import annotations

import os
import csv
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from neo4j import GraphDatabase
from sklearn.manifold import TSNE
from umap import UMAP

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "br_kg_exports"
PLOT_DIR = OUT_DIR / "plots"
PLOT_DIR.mkdir(parents=True, exist_ok=True)


def get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing env var: {name}")
    return val


def fetch_concepts() -> List[Tuple[str, str, str, str]]:
    uri = get_env("NEO4J_URI")
    user = get_env("NEO4J_USER")
    pwd = get_env("NEO4J_PASSWORD")
    db = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    cypher = """
    MATCH (c:Concept)
    OPTIONAL MATCH (c)-[:CLASSIFIED_UNDER|:CLASSIFIEDUNDER]->(cc:ConceptClass)
    WITH c, cc
    WHERE cc IS NOT NULL
    WITH c, cc ORDER BY c.id
    RETURN c.id AS id, coalesce(c.label, c.name) AS label,
           c.definition AS definition,
           cc.name AS class
    """
    with driver.session(database=db) as session:
        records = session.run(cypher)
        rows = [(r["id"], r["label"], r["definition"], r["class"]) for r in records]
    driver.close()
    return rows


def build_embeddings(texts: List[str], method: str = "sbert", gemini_model: str = "text-embedding-004", api_key_env: str = "GOOGLE_API_KEY") -> np.ndarray:
    if method == "sbert":
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise SystemExit("Install sentence-transformers (pip install sentence-transformers)") from exc
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embs = model.encode(texts, batch_size=64, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)
        return embs
    elif method == "gemini":
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key env var {api_key_env}")
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise SystemExit("Install google-generativeai (pip install google-generativeai)") from exc
        genai.configure(api_key=api_key)
        vectors = []
        batch_size = 32
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            resp = genai.embed_content(model=gemini_model, content=batch)
            embs = resp["embedding"] if isinstance(resp, dict) and "embedding" in resp else resp
            vectors.extend(embs)
        embs = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-12
        embs = embs / norms
        return embs
    else:
        raise ValueError(f"Unknown embedding method: {method}")


def reduce_tsne(embs: np.ndarray, perp: float = 35.0, seed: int = 42) -> np.ndarray:
    tsne = TSNE(
        n_components=2,
        perplexity=perp,
        random_state=seed,
        init="pca",
        learning_rate="auto",
        max_iter=750,
        verbose=1,
    )
    return tsne.fit_transform(embs)


def reduce_umap(embs: np.ndarray, seed: int = 42, n_neighbors: int = 15, min_dist: float = 0.1) -> np.ndarray:
    reducer = UMAP(n_components=2, random_state=seed, n_neighbors=n_neighbors, min_dist=min_dist, metric="cosine")
    return reducer.fit_transform(embs)


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Plot BR-KG concept embedding TSNE")
    ap.add_argument("--method", choices=["sbert", "gemini"], default="sbert", help="Embedding backend")
    ap.add_argument("--gemini_model", type=str, default="text-embedding-004", help="Gemini embedding model name")
    ap.add_argument("--gemini_api_key_env", type=str, default="GOOGLE_API_KEY", help="Env var for Gemini API key")
    ap.add_argument("--outfile_prefix", type=str, default="br_kg_concepts", help="Prefix for output plot/csv files")
    args = ap.parse_args()

    rows = fetch_concepts()
    if not rows:
        raise SystemExit("No concepts fetched")

    ids, labels, defs, classes = zip(*rows)
    texts = [f"{l}. {d}" if d else l for l, d in zip(labels, defs)]

    embs = build_embeddings(list(texts), method=args.method, gemini_model=args.gemini_model, api_key_env=args.gemini_api_key_env)
    pts_tsne = reduce_tsne(embs)
    pts_umap = reduce_umap(embs)

    # Save CSVs
    csv_path = OUT_DIR / f"{args.outfile_prefix}_{args.method}_concept_embeddings_tsne.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "label", "class", "x", "y"])
        for i, l, c, (x, y) in zip(ids, labels, classes, pts_tsne):
            writer.writerow([i, l, c, x, y])

    csv_path_umap = OUT_DIR / f"{args.outfile_prefix}_{args.method}_concept_embeddings_umap.csv"
    with csv_path_umap.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "label", "class", "x", "y"])
        for i, l, c, (x, y) in zip(ids, labels, classes, pts_umap):
            writer.writerow([i, l, c, x, y])

    # Plot
    def scatter_plot(points, name: str):
        # Slightly smaller canvas so points/labels appear larger on export
        fig, ax = plt.subplots(figsize=(10, 7.5))
        uniq_classes = sorted(set(classes))
        cmap = plt.get_cmap("tab20")
        class_to_color = {c: cmap(i % 20) for i, c in enumerate(uniq_classes)}
        for i, l, c, (x, y) in zip(ids, labels, classes, points):
            ax.scatter(x, y, s=240, color=class_to_color[c], alpha=0.75)  # larger markers
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(name, fontsize=28)
        handles = [
            plt.Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                label=c,
                markerfacecolor=class_to_color[c],
                markersize=22,
            )
            for c in uniq_classes
        ]
        ax.legend(
            handles=handles,
            title="ConceptClass",
            loc="best",
            fontsize=20,
            title_fontsize=22,
            framealpha=0.9,
        )
        ax.tick_params(labelsize=18)
        fig.tight_layout()
        out = PLOT_DIR / f"{args.outfile_prefix}_{args.method}_{name.replace(' ', '_').lower()}.png"
        fig.savefig(out, dpi=600, bbox_inches="tight")
        plt.close(fig)
        print("Saved:", out)

    scatter_plot(pts_tsne, "TSNE map of BR-KG Nodes")
    scatter_plot(pts_umap, "UMAP map of BR-KG Nodes")
    print("CSV:", csv_path)
    print("CSV UMAP:", csv_path_umap)


if __name__ == "__main__":
    main()
