"""
Enhanced PubMed Data Loader with Task Extraction

This is an improved version that properly extracts and includes task information
in the publication data.
"""

# Import the original loader functions
import xml.etree.ElementTree as ET

from .enhanced_pubmed_loader import *

# Import improved task extraction
try:
    from ..task_extraction import extract_tasks_from_metadata

    IMPROVED_EXTRACTION = True
except ImportError:
    IMPROVED_EXTRACTION = False


def _extract_article_data_with_tasks(article: ET.Element) -> dict | None:
    """Enhanced version of _extract_article_data that includes task extraction."""
    # Get base article data
    base_data = _extract_article_data(article)

    if not base_data:
        return None

    # Extract tasks
    if IMPROVED_EXTRACTION:
        tasks = extract_tasks_from_metadata(
            base_data.get("title", ""),
            base_data.get("abstract", ""),
            base_data.get("mesh_terms", []),
            base_data.get("keywords", []),
        )
    else:
        # Simple fallback extraction
        tasks = []

        # Check title and abstract for task mentions
        for text in [base_data.get("title", ""), base_data.get("abstract", "")]:
            if text and "task" in text.lower():
                # Very simple pattern - can be improved
                import re

                pattern = re.compile(r"([\w\s\-]+)\s+task", re.IGNORECASE)
                matches = pattern.findall(text)
                tasks.extend(matches[:5])  # Limit to avoid noise

        # Check MeSH terms and keywords
        for term in base_data.get("mesh_terms", []) + base_data.get("keywords", []):
            if term and "task" in term.lower():
                tasks.append(term)

    # Add tasks to publication data
    base_data["tasks"] = list(set(tasks))  # Deduplicate

    return base_data


def _get_sample_publications_with_tasks() -> list[dict]:
    """Get sample publication data with task information."""
    samples = _get_sample_publications()

    # Add task information to samples
    for sample in samples:
        if IMPROVED_EXTRACTION:
            tasks = extract_tasks_from_metadata(
                sample.get("title", ""),
                sample.get("abstract", ""),
                sample.get("mesh_terms", []),
                sample.get("keywords", []),
            )
        else:
            # Simple extraction for samples
            tasks = []
            if "working memory" in sample.get("title", "").lower():
                tasks.append("working memory task")
            if "executive control" in sample.get("title", "").lower():
                tasks.append("executive control task")
            if "fMRI task" in sample.get("abstract", "").lower():
                tasks.append("fMRI task")

        sample["tasks"] = tasks

    return samples


# Override the fetch_articles function to use enhanced extraction
def fetch_articles_enhanced(pmids: list[str], **kwargs) -> list[dict]:
    """
    Enhanced version of fetch_articles that includes task extraction.

    This function wraps the original fetch_articles and adds task information
    to each article.
    """
    # Get articles using original function
    articles = fetch_articles(pmids, **kwargs)

    # Process each article to add tasks
    enhanced_articles = []
    for article_element in articles:
        article_data = _extract_article_data_with_tasks(article_element)
        if article_data:
            enhanced_articles.append(article_data)

    return enhanced_articles
