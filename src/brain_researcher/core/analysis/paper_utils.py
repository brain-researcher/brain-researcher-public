"""Utility functions for processing retrieved papers."""

import logging
import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

try:
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logging.warning(
        "scikit-learn not available. Clustering functionality will be limited."
    )

logger = logging.getLogger(__name__)


def deduplicate_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate papers using DOI/PMID pairs.

    Args:
        papers: List of paper dictionaries

    Returns:
        List of unique papers
    """
    if not papers:
        return []

    seen_dois = set()
    seen_ids = set()
    unique = []

    for paper in papers:
        # Get DOI and ID
        doi = paper.get("doi")
        paper_id = paper.get("id")

        # Skip if we've seen this DOI before (and it's not None/empty)
        if doi and doi in seen_dois:
            logger.debug(f"Skipping duplicate paper by DOI: {doi}")
            continue

        # Skip if we've seen this ID before (and it's not None/empty)
        if paper_id and paper_id in seen_ids:
            logger.debug(f"Skipping duplicate paper by ID: {paper_id}")
            continue

        # Add to seen sets
        if doi:
            seen_dois.add(doi)
        if paper_id:
            seen_ids.add(paper_id)

        unique.append(paper)

    logger.info(f"Deduplicated {len(papers)} papers to {len(unique)} unique papers")
    return unique


def _extract_year(paper: dict[str, Any]) -> int | None:
    """Extract publication year from paper metadata."""
    # Try different fields where year might be stored
    year = paper.get("year")
    if year:
        try:
            return int(year)
        except (ValueError, TypeError):
            pass

    # Try to extract from date field
    date = paper.get("date") or paper.get("publication_date")
    if date and isinstance(date, str):
        try:
            # Handle common date formats
            if len(date) >= 4:
                return int(date[:4])
        except (ValueError, TypeError):
            pass

    return None


def _generate_cluster_summary(
    cluster_papers: list[dict[str, Any]],
    keywords: list[str],
    vectorizer: Optional["TfidfVectorizer"] = None,
    cluster_vector: np.ndarray | None = None,
) -> str:
    """Generate a more informative cluster summary."""
    summary_parts = []

    # Keywords
    if keywords:
        summary_parts.append(f"Key topics: {', '.join(keywords[:5])}")

    # Paper count
    summary_parts.append(f"{len(cluster_papers)} papers")

    # Year range
    years = [_extract_year(p) for p in cluster_papers]
    years = [y for y in years if y is not None]
    if years:
        if len(set(years)) > 1:
            summary_parts.append(f"({min(years)}-{max(years)})")
        else:
            summary_parts.append(f"({years[0]})")

    # Top journals
    journals = [p.get("journal") for p in cluster_papers if p.get("journal")]
    if journals:
        journal_counts = defaultdict(int)
        for j in journals:
            journal_counts[j] += 1
        top_journal = max(journal_counts.items(), key=lambda x: x[1])
        if top_journal[1] > 1:  # Only mention if appears more than once
            summary_parts.append(f"Main journal: {top_journal[0]}")

    return " | ".join(summary_parts)


def cluster_papers(
    papers: list[dict[str, Any]],
    n_clusters: int | None = None,
    min_cluster_size: int = 2,
) -> list[dict[str, Any]]:
    """Cluster papers by abstract similarity and summarize each cluster.

    Args:
        papers: List of paper dictionaries
        n_clusters: Number of clusters (auto-determined if None)
        min_cluster_size: Minimum papers per cluster

    Returns:
        List of cluster dictionaries with summaries and papers
    """
    if not papers:
        return []

    # Check if we have sklearn
    if not SKLEARN_AVAILABLE:
        logger.warning(
            "scikit-learn not available. Returning all papers in one cluster."
        )
        return [
            {
                "summary": f"All papers ({len(papers)} total) - clustering unavailable",
                "papers": papers,
                "cluster_id": 0,
                "size": len(papers),
                "keywords": [],
            }
        ]

    # Filter papers with valid abstracts
    valid_papers = [
        (i, p)
        for i, p in enumerate(papers)
        if p.get("abstract") and len(str(p.get("abstract", ""))) > 20
    ]

    if not valid_papers:
        logger.warning("No papers with valid abstracts found")
        return [
            {
                "summary": "No abstracts available for clustering",
                "papers": papers,
                "cluster_id": 0,
                "size": len(papers),
                "keywords": [],
            }
        ]

    if len(valid_papers) < 3:
        # Too few papers to cluster meaningfully
        return [
            {
                "summary": f"Small dataset ({len(papers)} papers)",
                "papers": papers,
                "cluster_id": 0,
                "size": len(papers),
                "keywords": [],
            }
        ]

    indices, filtered_papers = zip(*valid_papers, strict=False)
    abstracts = [p["abstract"] for p in filtered_papers]

    try:
        # Vectorize abstracts
        vectorizer = TfidfVectorizer(
            stop_words="english",
            max_features=1000,
            min_df=1,
            max_df=0.9,
            ngram_range=(1, 2),  # Include bigrams for better context
        )
        X = vectorizer.fit_transform(abstracts)

        # Determine optimal number of clusters
        if n_clusters is None:
            # Use sqrt rule but ensure reasonable bounds
            n_clusters = max(
                2,
                min(
                    int(round(math.sqrt(len(filtered_papers)))),
                    len(filtered_papers) // min_cluster_size,
                    10,  # Cap at 10 clusters for usability
                ),
            )

        # Ensure we don't have more clusters than samples
        n_clusters = min(n_clusters, len(filtered_papers))

        logger.info(
            f"Clustering {len(filtered_papers)} papers into {n_clusters} clusters"
        )

        # Perform clustering
        km = KMeans(
            n_clusters=n_clusters,
            n_init="auto" if hasattr(KMeans, "__version__") else 10,
            random_state=42,
            max_iter=300,
        )
        labels = km.fit_predict(X)

        # Build clusters
        clusters = []
        feature_names = vectorizer.get_feature_names_out()

        # Create index mapping for papers without abstracts
        paper_to_cluster = {}
        for idx, label in zip(indices, labels, strict=False):
            paper_to_cluster[idx] = label

        for cluster_id in range(n_clusters):
            # Get indices of papers in this cluster
            cluster_indices = [
                indices[i] for i, lbl in enumerate(labels) if lbl == cluster_id
            ]
            if not cluster_indices:
                continue

            # Get cluster papers
            cluster_papers = [papers[i] for i in cluster_indices]

            # Calculate cluster center and top features
            cluster_mask = labels == cluster_id
            if cluster_mask.any():
                cluster_center = X[cluster_mask].mean(axis=0)
                arr = np.asarray(cluster_center).ravel()

                # Get top features
                top_indices = arr.argsort()[-10:][::-1]
                keywords = [feature_names[i] for i in top_indices if arr[i] > 0]

                # Generate summary
                summary = _generate_cluster_summary(
                    cluster_papers, keywords, vectorizer, cluster_center
                )
            else:
                summary = f"Cluster {cluster_id + 1}"

            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "summary": summary,
                    "papers": cluster_papers,
                    "size": len(cluster_papers),
                    "keywords": keywords[:5] if "keywords" in locals() else [],
                }
            )

        # Add papers without abstracts to nearest cluster
        unassigned = [i for i in range(len(papers)) if i not in paper_to_cluster]
        if unassigned and clusters:
            # Add to largest cluster
            largest_cluster = max(clusters, key=lambda c: c["size"])
            for idx in unassigned:
                largest_cluster["papers"].append(papers[idx])
                largest_cluster["size"] += 1

        # Sort clusters by size (largest first)
        clusters.sort(key=lambda c: c["size"], reverse=True)

        logger.info(f"Created {len(clusters)} clusters")
        return clusters

    except Exception as e:
        logger.error(f"Clustering failed: {e}", exc_info=True)
        # Fallback: return all papers in one cluster
        return [
            {
                "summary": f"Clustering failed - all papers grouped together ({len(papers)} total)",
                "papers": papers,
                "cluster_id": 0,
                "size": len(papers),
                "keywords": [],
                "error": str(e),
            }
        ]


def rank_papers_in_cluster(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank papers within a cluster by relevance and quality metrics.

    Args:
        papers: List of papers to rank

    Returns:
        Sorted list of papers with ranking scores
    """
    current_year = datetime.now().year

    for paper in papers:
        score = 0.0

        # Recency score (max 20 points)
        year = _extract_year(paper)
        if year:
            years_old = current_year - year
            score += max(0, 20 - years_old * 2)

        # Relevance score from retrieval (max 30 points)
        retrieval_score = paper.get("score", 0)
        score += retrieval_score * 30

        # Source quality (max 20 points)
        source = paper.get("source", "").lower()
        if "pubmed" in source:
            score += 20
        elif "pmc" in source:
            score += 15
        elif "arxiv" in source:
            score += 10

        # Has DOI (10 points)
        if paper.get("doi"):
            score += 10

        # Abstract length (max 10 points)
        abstract = paper.get("abstract", "")
        if abstract:
            # Prefer substantial abstracts
            abstract_len = len(abstract)
            if abstract_len > 500:
                score += 10
            elif abstract_len > 200:
                score += 5

        # Citation count if available (max 10 points)
        citations = paper.get("citation_count", 0)
        if citations:
            score += min(10, citations / 10)

        paper["cluster_rank_score"] = score

    # Sort by score descending
    ranked_papers = sorted(
        papers, key=lambda p: p.get("cluster_rank_score", 0), reverse=True
    )

    # Add rank position
    for i, paper in enumerate(ranked_papers):
        paper["cluster_rank"] = i + 1

    return ranked_papers
