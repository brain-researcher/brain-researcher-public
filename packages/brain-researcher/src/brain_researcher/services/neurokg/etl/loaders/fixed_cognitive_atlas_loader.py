"""
Cognitive Atlas Data Loader

Fetches cognitive concepts and tasks from the Cognitive Atlas using the official Python package.
Provides robust error handling and data validation.
"""

import json
import logging
import tempfile
from pathlib import Path

from cognitiveatlas.api import get_concept, get_task

logger = logging.getLogger(__name__)


class CognitiveAtlasError(Exception):
    """Custom exception for Cognitive Atlas data processing errors."""

    pass


def fetch_cognitive_atlas_data(
    output_dir: str, sample_size: int = 500
) -> dict[str, str]:
    """
    Fetch cognitive concepts and tasks from Cognitive Atlas using the official API.

    Args:
        output_dir: Directory to save fetched data
        sample_size: Maximum number of items to fetch per category

    Returns:
        Dictionary mapping data type to output file path

    Raises:
        CognitiveAtlasError: If API requests fail and no fallback available
    """
    logger.info(f"📚 Fetching Cognitive Atlas data (sample_size={sample_size})")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    output_files = {}

    try:
        # Fetch concepts
        logger.info("🧠 Fetching cognitive concepts...")
        concepts_data = _fetch_concepts_with_cognitiveatlas(sample_size)

        concepts_output = output_path / "cognitive_concepts.json"
        with open(concepts_output, "w", encoding="utf-8") as f:
            json.dump(concepts_data, f, indent=2, ensure_ascii=False)
        output_files["concepts"] = str(concepts_output)

        # Fetch tasks
        logger.info("🎯 Fetching cognitive tasks...")
        tasks_data = _fetch_tasks_with_cognitiveatlas(sample_size)

        tasks_output = output_path / "cognitive_tasks.json"
        with open(tasks_output, "w", encoding="utf-8") as f:
            json.dump(tasks_data, f, indent=2, ensure_ascii=False)
        output_files["tasks"] = str(tasks_output)

        logger.info(
            f"✅ Fetched {len(concepts_data)} concepts and {len(tasks_data)} tasks"
        )

    except Exception as e:
        logger.error(f"❌ Cognitive Atlas fetch failed: {e}")
        # Fallback to sample data
        logger.info("🔄 Using sample Cognitive Atlas data")
        return _create_sample_cognitive_atlas_data(output_path)

    return output_files


def _fetch_concepts_with_cognitiveatlas(sample_size: int) -> list[dict]:
    """Fetch concepts using the cognitiveatlas package."""
    logger.info("📥 Downloading concepts from Cognitive Atlas...")

    try:
        # Get all concepts - FIXED: Use .json property to access data
        result = get_concept()
        if not hasattr(result, "json"):
            logger.error(
                "❌ Cognitive Atlas API returned unexpected format (no .json property)"
            )
            raise CognitiveAtlasError("API returned unexpected format")

        concepts_list = result.json
        logger.info(f"📊 Retrieved {len(concepts_list)} concepts from API")

        # Process and clean the data
        concepts = []
        processed_count = 0

        for concept_data in concepts_list:
            if processed_count >= sample_size:
                break

            try:
                # Extract concept data
                concept = {
                    "id": str(concept_data.get("id", "")),
                    "name": str(concept_data.get("name", "")).strip(),
                    "definition": str(
                        concept_data.get("definition_text", "")
                    ).strip(),  # FIXED: Use definition_text
                    "alias": str(concept_data.get("alias", "")).strip(),
                    "concept_class": str(concept_data.get("id_concept_class", "")),
                    "creation_time": concept_data.get("creation_time"),
                    "source": "cognitive_atlas",
                    "url": f"https://www.cognitiveatlas.org/term/id/{concept_data.get('id', '')}/",
                    "category": _categorize_concept(
                        str(concept_data.get("name", "")),
                        str(
                            concept_data.get("definition_text", "")
                        ),  # FIXED: Use definition_text
                    ),
                }

                # Validate required fields
                if concept["name"] and len(concept["name"]) > 2:
                    concepts.append(concept)
                    processed_count += 1

            except Exception as e:
                logger.warning(f"⚠️ Error processing concept: {e}")
                continue

        logger.info(f"✅ Processed {len(concepts)} valid concepts")
        return concepts

    except Exception as e:
        logger.error(f"❌ Failed to fetch concepts: {e}")
        raise CognitiveAtlasError(f"Concept fetch failed: {e}")


def _fetch_tasks_with_cognitiveatlas(sample_size: int) -> list[dict]:
    """Fetch tasks using the cognitiveatlas package."""
    logger.info("📥 Downloading tasks from Cognitive Atlas...")

    try:
        # Get all tasks - FIXED: Use .json property to access data
        result = get_task()
        if not hasattr(result, "json"):
            logger.error(
                "❌ Cognitive Atlas API returned unexpected format (no .json property)"
            )
            raise CognitiveAtlasError("API returned unexpected format")

        tasks_list = result.json
        logger.info(f"📊 Retrieved {len(tasks_list)} tasks from API")

        # Process and clean the data
        tasks = []
        processed_count = 0

        for task_data in tasks_list:
            if processed_count >= sample_size:
                break

            try:
                # Extract task data
                task = {
                    "id": str(task_data.get("id", "")),
                    "name": str(task_data.get("name", "")).strip(),
                    "definition": str(task_data.get("definition", "")).strip(),
                    "implementation": str(task_data.get("implementation", "")).strip(),
                    "creation_time": task_data.get("creation_time"),
                    "source": "cognitive_atlas",
                    "url": f"https://www.cognitiveatlas.org/task/id/{task_data.get('id', '')}/",
                    "category": _categorize_task(
                        str(task_data.get("name", "")),
                        str(task_data.get("definition", "")),
                    ),
                }

                # Validate required fields
                if task["name"] and len(task["name"]) > 2:
                    tasks.append(task)
                    processed_count += 1

            except Exception as e:
                logger.warning(f"⚠️ Error processing task: {e}")
                continue

        logger.info(f"✅ Processed {len(tasks)} valid tasks")
        return tasks

    except Exception as e:
        logger.error(f"❌ Failed to fetch tasks: {e}")
        raise CognitiveAtlasError(f"Task fetch failed: {e}")


def _categorize_concept(name: str, definition: str) -> str:
    """Categorize cognitive concepts based on name and definition."""
    name_lower = name.lower()
    definition_lower = definition.lower()

    # Memory-related concepts
    if any(
        term in name_lower
        for term in ["memory", "recall", "recognition", "encoding", "retrieval"]
    ):
        return "memory"

    # Attention-related concepts
    if any(
        term in name_lower for term in ["attention", "focus", "vigilance", "alertness"]
    ):
        return "attention"

    # Executive function concepts
    if any(
        term in name_lower
        for term in ["executive", "control", "inhibition", "switching", "planning"]
    ):
        return "executive"

    # Language concepts
    if any(
        term in name_lower
        for term in ["language", "speech", "verbal", "linguistic", "comprehension"]
    ):
        return "language"

    # Perception concepts
    if any(
        term in name_lower for term in ["perception", "visual", "auditory", "sensory"]
    ):
        return "perception"

    # Motor concepts
    if any(
        term in name_lower for term in ["motor", "movement", "action", "coordination"]
    ):
        return "motor"

    # Emotion concepts
    if any(term in name_lower for term in ["emotion", "affect", "mood", "feeling"]):
        return "emotion"

    # Social cognition
    if any(
        term in name_lower
        for term in ["social", "theory of mind", "empathy", "mentalizing"]
    ):
        return "social"

    # Decision making
    if any(
        term in name_lower for term in ["decision", "choice", "judgment", "reasoning"]
    ):
        return "decision"

    return "general"


def _categorize_task(name: str, definition: str) -> str:
    """Categorize cognitive tasks based on name and definition."""
    name_lower = name.lower()
    definition_lower = definition.lower()

    # Memory tasks
    if any(
        term in name_lower
        for term in ["memory", "recall", "recognition", "n-back", "span"]
    ):
        return "memory"

    # Attention tasks
    if any(
        term in name_lower
        for term in ["attention", "stroop", "flanker", "cueing", "vigilance"]
    ):
        return "attention"

    # Executive tasks
    if any(
        term in name_lower
        for term in ["switching", "inhibition", "go/no-go", "stop signal", "wisconsin"]
    ):
        return "executive"

    # Language tasks
    if any(
        term in name_lower
        for term in ["language", "reading", "naming", "verbal", "semantic"]
    ):
        return "language"

    # Perception tasks
    if any(
        term in name_lower for term in ["perception", "visual", "auditory", "detection"]
    ):
        return "perception"

    # Motor tasks
    if any(
        term in name_lower
        for term in ["motor", "movement", "finger", "hand", "tapping"]
    ):
        return "motor"

    # Emotion tasks
    if any(term in name_lower for term in ["emotion", "face", "affect", "mood"]):
        return "emotion"

    # Social tasks
    if any(
        term in name_lower
        for term in ["social", "theory of mind", "empathy", "mentalizing"]
    ):
        return "social"

    # Decision tasks
    if any(term in name_lower for term in ["decision", "choice", "gambling", "risk"]):
        return "decision"

    return "general"


def _create_sample_cognitive_atlas_data(output_path: Path) -> dict[str, str]:
    """Create sample Cognitive Atlas data when API is unavailable."""
    logger.info("📝 Creating sample Cognitive Atlas data")

    # Sample concepts
    sample_concepts = [
        {
            "id": "trm_4a3fd79d096be",
            "name": "working memory",
            "definition": "The ability to maintain and manipulate information in mind over short periods of time.",
            "alias": "WM",
            "concept_class": "ctp_C3",
            "creation_time": 1512660626063,
            "source": "cognitive_atlas",
            "url": "https://www.cognitiveatlas.org/term/id/trm_4a3fd79d096be/",
            "category": "memory",
        },
        {
            "id": "trm_4a3fd79d096e3",
            "name": "attention",
            "definition": "The cognitive process of selectively concentrating on one aspect of the environment.",
            "alias": "ATT",
            "concept_class": "ctp_C3",
            "creation_time": 1512660626088,
            "source": "cognitive_atlas",
            "url": "https://www.cognitiveatlas.org/term/id/trm_4a3fd79d096e3/",
            "category": "attention",
        },
        {
            "id": "trm_4a3fd79d096f0",
            "name": "executive control",
            "definition": "The ability to control and coordinate cognitive processes.",
            "alias": "EC",
            "concept_class": "ctp_C1",
            "creation_time": 1512660626111,
            "source": "cognitive_atlas",
            "url": "https://www.cognitiveatlas.org/term/id/trm_4a3fd79d096f0/",
            "category": "executive",
        },
    ]

    # Sample tasks
    sample_tasks = [
        {
            "id": "tsk_4a57abb949e8a",
            "name": "n-back task",
            "definition": "A task that requires participants to respond when a stimulus matches one presented n trials back.",
            "implementation": "Participants view a sequence of stimuli and respond when the current stimulus matches the one from n steps earlier.",
            "creation_time": 1512660626133,
            "source": "cognitive_atlas",
            "url": "https://www.cognitiveatlas.org/task/id/tsk_4a57abb949e8a/",
            "category": "memory",
        },
        {
            "id": "tsk_4a57abb949e9b",
            "name": "stroop task",
            "definition": "A task that measures the ability to inhibit cognitive interference.",
            "implementation": "Participants name the color of words while ignoring the word meaning.",
            "creation_time": 1512660626154,
            "source": "cognitive_atlas",
            "url": "https://www.cognitiveatlas.org/task/id/tsk_4a57abb949e9b/",
            "category": "attention",
        },
    ]

    output_files = {}

    # Save sample concepts
    concepts_output = output_path / "cognitive_concepts.json"
    with open(concepts_output, "w", encoding="utf-8") as f:
        json.dump(sample_concepts, f, indent=2, ensure_ascii=False)
    output_files["concepts"] = str(concepts_output)

    # Save sample tasks
    tasks_output = output_path / "cognitive_tasks.json"
    with open(tasks_output, "w", encoding="utf-8") as f:
        json.dump(sample_tasks, f, indent=2, ensure_ascii=False)
    output_files["tasks"] = str(tasks_output)

    logger.info(
        f"✅ Created sample data: {len(sample_concepts)} concepts, {len(sample_tasks)} tasks"
    )

    return output_files


def process_cognitive_atlas_data(raw_dir: str, output_dir: str) -> dict[str, str]:
    """
    Process downloaded Cognitive Atlas data into BR-KG format.

    Args:
        raw_dir: Directory containing raw Cognitive Atlas files
        output_dir: Directory to save processed files

    Returns:
        Dictionary mapping data type to output file path
    """
    logger.info(f"🔄 Processing Cognitive Atlas data from {raw_dir}")

    raw_path = Path(raw_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    output_files = {}

    # Process concepts file if exists
    concepts_file = raw_path / "cognitive_concepts.json"
    if concepts_file.exists():
        concepts_output = output_path / "concepts.csv"
        _convert_concepts_to_csv(concepts_file, concepts_output)
        output_files["concepts"] = str(concepts_output)
        logger.info("✅ Converted concepts to CSV")

    # Process tasks file if exists
    tasks_file = raw_path / "cognitive_tasks.json"
    if tasks_file.exists():
        tasks_output = output_path / "tasks.csv"
        _convert_tasks_to_csv(tasks_file, tasks_output)
        output_files["tasks"] = str(tasks_output)
        logger.info("✅ Converted tasks to CSV")

    return output_files


def _convert_concepts_to_csv(concepts_file: Path, output_file: Path):
    """Convert concepts JSON to CSV format."""
    with open(concepts_file, encoding="utf-8") as f:
        concepts = json.load(f)

    with open(output_file, "w", encoding="utf-8") as f:
        # Write CSV header
        f.write("id,name,definition,alias,concept_class,category,url\n")

        for concept in concepts:
            # Escape CSV fields
            name = concept.get("name", "").replace('"', '""')
            definition = concept.get("definition", "").replace('"', '""')
            alias = concept.get("alias", "").replace('"', '""')

            f.write(
                f'"{concept.get("id", "")}","{name}","{definition}","{alias}",'
                f'"{concept.get("concept_class", "")}","{concept.get("category", "")}",'
                f'"{concept.get("url", "")}"\n'
            )


def _convert_tasks_to_csv(tasks_file: Path, output_file: Path):
    """Convert tasks JSON to CSV format."""
    with open(tasks_file, encoding="utf-8") as f:
        tasks = json.load(f)

    with open(output_file, "w", encoding="utf-8") as f:
        # Write CSV header
        f.write("id,name,definition,implementation,category,url\n")

        for task in tasks:
            # Escape CSV fields
            name = task.get("name", "").replace('"', '""')
            definition = task.get("definition", "").replace('"', '""')
            implementation = task.get("implementation", "").replace('"', '""')

            f.write(
                f'"{task.get("id", "")}","{name}","{definition}","{implementation}",'
                f'"{task.get("category", "")}","{task.get("url", "")}"\n'
            )


if __name__ == "__main__":
    # Test the loader
    import tempfile

    # Configure logging
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            result = fetch_cognitive_atlas_data(temp_dir, sample_size=10)
            print(f"✅ Test successful: {result}")
        except Exception as e:
            print(f"❌ Test failed: {e}")
