"""
Improved PubMed Task Linker

Links publications to Task nodes using advanced matching strategies.
Supports multiple task node types (Task, TaskDef, TaskSpec) and uses
the existing TaskMatcher for better accuracy.
"""

import logging
from typing import Any

try:
    # Try to use the existing sophisticated TaskMatcher
    from brain_researcher.core.utils.task_matcher import TaskMatcher

    TASK_MATCHER_AVAILABLE = True
except ImportError:
    TaskMatcher = Any  # type: ignore
    TASK_MATCHER_AVAILABLE = False

from difflib import SequenceMatcher

try:
    from brain_researcher.services.neurokg.utils.text_norm import normalize_task_name
except ImportError:  # pragma: no cover
    from brain_researcher.core.utils.text_norm import normalize_task_name

logger = logging.getLogger(__name__)


def build_comprehensive_task_index(db) -> dict[str, dict]:
    """Build lookup table of normalized task names to node IDs from all task node types."""
    index = {}

    # Search for all task node types
    task_labels = ["Task", "TaskDef", "TaskSpec"]

    for label in task_labels:
        nodes = db.find_nodes(label)
        for task_id, data in nodes:
            # Extract task name from various possible fields
            name = data.get("name") or data.get("task") or data.get("task_name") or ""
            if name:
                normalized = normalize_task_name(name)
                if (
                    normalized not in index
                ):  # Avoid overwriting with same normalized name
                    index[normalized] = {
                        "id": task_id,
                        "name": name,
                        "label": label,
                        "original_name": name,
                    }

    logger.info(f"Built task index with {len(index)} unique normalized task names")
    return index


def match_task_advanced(
    name: str, index: dict, matcher: TaskMatcher | None = None, threshold: float = 0.65
) -> tuple[str | None, float, str]:
    """
    Return best matching task ID, score, and method used.

    Returns:
        Tuple of (task_id, score, method)
        Where method is one of: "exact", "niclip", "sbert", "fuzzy", "sequence"
    """
    if not name or not name.strip():
        return None, 0.0, "none"

    # 1. Try exact match first
    normalized = normalize_task_name(name)
    if normalized in index:
        return index[normalized]["id"], 1.0, "exact"

    # 2. Try sophisticated matching if TaskMatcher is available
    if TASK_MATCHER_AVAILABLE and matcher is not None:
        try:
            # Get all task names for matching
            task_names = [info["original_name"] for info in index.values()]
            matches = matcher.match(name, task_names, top_k=1)

            if matches and matches[0]["score"] >= threshold:
                best_match = matches[0]
                # Find the task ID for this match
                for norm_name, info in index.items():
                    if info["original_name"] == best_match["label"]:
                        return info["id"], best_match["score"], best_match["method"]
        except Exception as e:
            logger.debug(f"TaskMatcher failed, falling back to sequence matching: {e}")

    # 3. Fallback to SequenceMatcher
    best_id = None
    best_score = 0.0
    best_info = None

    for task_norm, info in index.items():
        score = SequenceMatcher(None, normalized, task_norm).ratio()
        if score > best_score:
            best_score = score
            best_id = info["id"]
            best_info = info

    if best_score >= threshold:
        return best_id, best_score, "sequence"

    return None, 0.0, "none"


def ingest_publication_with_tasks(
    db, paper: dict, task_index: dict, matcher: TaskMatcher | None = None
) -> tuple[str, dict]:
    """
    Create Study node and link to Task nodes with statistics.

    Returns:
        Tuple of (publication_id, statistics_dict)
    """
    # Handle authors properly - they should already be dict format from _extract_authors
    authors = paper.get("authors", [])
    if authors and isinstance(authors[0], dict):
        author_list = []
        for a in authors:
            full_name = f"{a.get('first_name', '')} {a.get('last_name', '')}".strip()
            if not full_name:
                full_name = a.get("initials", "") + " " + a.get("last_name", "")
            author_list.append(full_name.strip())
        authors_str = ", ".join(author_list)
    else:
        authors_str = ", ".join(authors) if isinstance(authors, list) else str(authors)

    # Create the Study node
    pub_id = db.create_node(
        "Study",
        {
            "pmid": paper.get("pmid", ""),
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", ""),
            "authors": authors_str,
            "journal": paper.get("journal", ""),
            "year": paper.get("year"),
            "mesh_terms": paper.get("mesh_terms", []),
            "keywords": paper.get("keywords", []),
            "doi": paper.get("doi", ""),
            "source": "pubmed",
        },
        node_id=paper.get("pmid") if paper.get("pmid") else None,
    )

    # Track statistics
    stats = {
        "tasks_extracted": 0,
        "tasks_matched": 0,
        "relationships_created": 0,
        "match_methods": {},
        "unmatched_tasks": [],
    }

    # Process extracted tasks
    tasks = paper.get("tasks", [])
    stats["tasks_extracted"] = len(tasks)

    # Deduplicate tasks by normalized form
    seen_normalized = set()
    unique_tasks = []
    for task in tasks:
        norm = normalize_task_name(task)
        if norm and norm not in seen_normalized:
            seen_normalized.add(norm)
            unique_tasks.append(task)

    # Match and link tasks
    for task_name in unique_tasks:
        task_id, score, method = match_task_advanced(task_name, task_index, matcher)

        if task_id:
            try:
                db.create_relationship(
                    pub_id,
                    task_id,
                    "USES_PARADIGM",
                    {
                        "confidence": round(score, 3),
                        "match_method": method,
                        "original_term": task_name,
                    },
                )
                stats["tasks_matched"] += 1
                stats["relationships_created"] += 1
                stats["match_methods"][method] = (
                    stats["match_methods"].get(method, 0) + 1
                )
            except Exception as e:
                logger.error(f"Failed to create relationship: {e}")
        else:
            stats["unmatched_tasks"].append(task_name)
            logger.debug(f"No match found for task: {task_name}")

    return pub_id, stats
