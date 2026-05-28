"""
Improved Task Extraction Module

Extracts task names from publication metadata using refined patterns
and filtering to reduce false positives.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Common false positive phrases to filter out
GENERIC_TASK_BLACKLIST = {
    "this task",
    "the task",
    "a task",
    "that task",
    "each task",
    "every task",
    "task performance",
    "task difficulty",
    "task completion",
    "task accuracy",
    "cognitive task",
    "behavioral task",
    "experimental task",
    "simple task",
    "complex task",
    "difficult task",
    "easy task",
    "main task",
    "primary task",
    "secondary task",
    "control task",
    "baseline task",
    "task condition",
    "task phase",
    "task block",
    "task trial",
    "task session",
    "task run",
    "during task",
    "post task",
    "pre task",
    "between task",
    "across task",
    "task related",
    "task based",
    "task specific",
    "task dependent",
    "task independent",
    "multi task",
    "single task",
    "dual task",
}

# Known task name patterns (can be extended)
KNOWN_TASK_PATTERNS = [
    # Classic cognitive tasks
    r"\b(stroop|flanker|simon|go[/-]?no[/-]?go|stop[/-]?signal)\s*tasks?\b",
    r"\b(n[/-]?back|sternberg|digit[/-]?span|spatial[/-]?span)\s*tasks?\b",
    r"\b(wisconsin card sorting|wcst|tower of (london|hanoi)|tol|toh)\s*tasks?\b",
    # Memory tasks
    r"\b(working memory|episodic memory|semantic memory|recognition memory)\s*tasks?\b",
    r"\b(free recall|cued recall|paired[/-]?associate)\s*tasks?\b",
    r"\b(face[/-]?name|object[/-]?location|source memory)\s*tasks?\b",
    # Attention tasks
    r"\b(visual search|attention network|ant|sustained attention)\s*tasks?\b",
    r"\b(posner cueing|spatial cueing|endogenous cueing|exogenous cueing)\s*tasks?\b",
    r"\b(rapid serial visual presentation|rsvp|attentional blink)\s*tasks?\b",
    # Language tasks
    r"\b(semantic fluency|phonemic fluency|verbal fluency|letter fluency)\s*tasks?\b",
    r"\b(picture naming|word generation|sentence comprehension)\s*tasks?\b",
    r"\b(lexical decision|semantic decision|rhyme judgment)\s*tasks?\b",
    # Motor tasks
    r"\b(finger tapping|sequential finger|motor sequence|serial reaction time|srt)\s*tasks?\b",
    r"\b(grip force|precision grip|power grip|bimanual coordination)\s*tasks?\b",
    # Emotion tasks
    r"\b(emotion recognition|facial emotion|emotional face|face matching)\s*tasks?\b",
    r"\b(fear conditioning|extinction|emotion regulation)\s*tasks?\b",
    # Decision making tasks
    r"\b(iowa gambling|igt|balloon analogue risk|bart|delay discounting)\s*tasks?\b",
    r"\b(probabilistic reversal|reward learning|punishment learning)\s*tasks?\b",
    # Social cognition tasks
    r"\b(theory of mind|tom|false belief|sally[/-]?anne)\s*tasks?\b",
    r"\b(trust game|ultimatum game|dictator game|prisoners dilemma)\s*tasks?\b",
    # Specific paradigms
    r"\b(oddball|mismatch negativity|mmn|p300)\s*(?:task|paradigm)s?\b",
    r"\b(resting[/-]?state|eyes[/-]?open|eyes[/-]?closed)\s*(?:task|paradigm|condition)s?\b",
    # General pattern with specific descriptors
    r"\b(visual|auditory|tactile|motor|cognitive|memory|attention|language|emotional|social)\s+\w+\s+tasks?\b",
]

# Compile patterns for efficiency
COMPILED_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in KNOWN_TASK_PATTERNS
]

# Generic task pattern (use with caution)
GENERIC_TASK_PATTERN = re.compile(r"\b([\w\s\-/]+?)\s+tasks?\b", re.IGNORECASE)


def extract_tasks_from_text(text: str) -> set[str]:
    """Extract task names from a text string using known patterns."""
    if not text:
        return set()

    tasks = set()

    # First, try known specific patterns
    for pattern in COMPILED_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            task_name = match.strip()
            # Normalize whitespace and add "task" if not present
            if not task_name.lower().endswith("task"):
                task_name += " task"
            tasks.add(task_name)

    # If no specific patterns found, try generic pattern with filtering
    if not tasks:
        generic_matches = GENERIC_TASK_PATTERN.findall(text)
        for match in generic_matches:
            task_phrase = match.strip() + " task"
            # Check if it's not in blacklist
            if task_phrase.lower() not in GENERIC_TASK_BLACKLIST:
                # Additional filters
                words = match.strip().split()
                # Must have at least one meaningful word
                if len(words) >= 1 and len(words) <= 5:  # Reasonable task name length
                    # Check if it contains at least one "meaningful" word
                    if any(len(word) > 3 for word in words):
                        tasks.add(task_phrase)

    return tasks


def extract_tasks_from_metadata(
    title: str, abstract: str, mesh_terms: list[str], keywords: list[str]
) -> list[str]:
    """
    Extract potential task names from publication metadata.

    Args:
        title: Publication title
        abstract: Publication abstract
        mesh_terms: List of MeSH terms
        keywords: List of keywords

    Returns:
        List of unique task names found
    """
    all_tasks = set()

    # Extract from title (higher weight)
    if title:
        title_tasks = extract_tasks_from_text(title)
        all_tasks.update(title_tasks)
        if title_tasks:
            logger.debug(f"Found tasks in title: {title_tasks}")

    # Extract from abstract
    if abstract:
        # Limit abstract length to avoid processing very long texts
        abstract_tasks = extract_tasks_from_text(abstract[:2000])
        all_tasks.update(abstract_tasks)
        if abstract_tasks:
            logger.debug(f"Found tasks in abstract: {abstract_tasks}")

    # Check MeSH terms for task-related terms
    if mesh_terms:
        for term in mesh_terms:
            if term:
                # Clean up MeSH term format first
                clean_term = term.replace("/", " ")

                if "task" in term.lower():
                    all_tasks.add(clean_term)
                # Also check for specific paradigm names in MeSH
                elif any(
                    paradigm in term.lower()
                    for paradigm in [
                        "stroop",
                        "n-back",
                        "wisconsin card",
                        "tower of london",
                        "go/no-go",
                        "stop signal",
                        "flanker",
                        "simon",
                    ]
                ):
                    # Use cleaned term and add task
                    all_tasks.add(clean_term + " task")

    # Check keywords
    if keywords:
        for keyword in keywords:
            if keyword and "task" in keyword.lower():
                all_tasks.add(keyword)
            # Also extract from keywords using patterns
            keyword_tasks = extract_tasks_from_text(keyword)
            all_tasks.update(keyword_tasks)

    # Convert to list and sort for consistency
    task_list = sorted(list(all_tasks))

    # Final filtering pass
    filtered_tasks = []
    for task in task_list:
        # Normalize whitespace
        task = " ".join(task.split())
        # Skip if too short or too generic
        if len(task) > 5 and task.lower() not in GENERIC_TASK_BLACKLIST:
            filtered_tasks.append(task)

    logger.info(f"Extracted {len(filtered_tasks)} unique tasks from metadata")
    return filtered_tasks


# Convenience function to replace the basic extraction in enhanced_pubmed_loader
def extract_tasks(
    title: str, abstract: str, mesh_terms: list[str], keywords: list[str]
) -> list[str]:
    """Compatibility wrapper for enhanced_pubmed_loader."""
    return extract_tasks_from_metadata(title, abstract, mesh_terms, keywords)
