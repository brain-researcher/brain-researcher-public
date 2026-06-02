#!/usr/bin/env python3
"""
NiCLIP Integration Demo

Shows how to use the new NiCLIP-based task classification in your code.
"""

from brain_researcher.services.br_kg.etl.mappers.niclip_task_mapper import get_mapper
from brain_researcher.services.br_kg.utils.vocab_loader import (
    get_task_concepts,
    get_task_process_name,
    search_similar_tasks,
)


def demo_direct_usage():
    """Demo: Direct usage of NiCLIP functions"""
    print("📚 Demo 1: Direct Function Usage")
    print("=" * 50)

    # Example 1: Get concepts for a task
    task = "n-back task"
    concepts = get_task_concepts(task)
    process = get_task_process_name(task)

    print(f"\nTask: {task}")
    print(f"Concepts: {concepts}")
    print(f"Cognitive Process: {process}")

    # Example 2: Search for similar tasks
    print("\n🔍 Searching for tasks similar to 'working memory':")
    similar = search_similar_tasks("working memory", top_k=5)
    for match in similar:
        print(f"  - {match['task']} (score: {match['score']:.2f})")


def demo_mapper_usage():
    """Demo: Using the mapper directly for advanced features"""
    print("\n\n🔧 Demo 2: Advanced Mapper Usage")
    print("=" * 50)

    mapper = get_mapper()

    if mapper and mapper._loaded:
        # Get all tasks in a process category
        print("\nTasks in 'Language' category (ctp_C6):")
        language_tasks = mapper.get_process_tasks("ctp_C6")
        for task in language_tasks[:5]:
            concepts = mapper.get_task_concepts(task)
            print(f"  - {task}: {', '.join(concepts[:2])}...")

        # Get detailed task info
        print("\n📊 Detailed info for 'emotional faces task':")
        info = mapper.format_task_info("emotional faces task")
        print(f"  Task: {info['task']}")
        print(f"  Concepts: {info['concepts']}")
        print(f"  Primary Category: {info['primary_category']}")

        # Show unmapped concepts
        unmapped = mapper.get_unmapped_concepts()
        print(
            f"\n⚠️  Unmapped concepts: {len(unmapped)} out of {len(mapper.concept_to_process) + len(unmapped)}"
        )
        print(f"  Examples: {unmapped[:5]}")


def demo_integration():
    """Demo: How to integrate with existing code"""
    print("\n\n🔌 Demo 3: Integration Example")
    print("=" * 50)

    # Example: Process a list of tasks from an experiment
    experiment_tasks = ["2-back task", "emotional faces", "finger tapping", "rest"]

    print("\nExperiment Task Analysis:")
    task_categories = {}

    for task in experiment_tasks:
        # Get concepts
        concepts = get_task_concepts(task)
        if not concepts:
            # Try searching for similar
            similar = search_similar_tasks(task, top_k=1)
            if similar and similar[0]["score"] > 0.5:
                task = similar[0]["task"]
                concepts = get_task_concepts(task)

        # Get process
        process = get_task_process_name(task)

        # Categorize
        if process:
            if process not in task_categories:
                task_categories[process] = []
            task_categories[process].append(task)

        print(f"\n  {task}:")
        print(f"    Concepts: {concepts[:3] if concepts else 'Not found'}")
        print(f"    Process: {process or 'Not categorized'}")

    print("\n📈 Summary by Process:")
    for process, tasks in task_categories.items():
        print(f"  {process}: {', '.join(tasks)}")


def demo_process_mapping():
    """Demo: Understanding the 6 cognitive processes"""
    print("\n\n🧠 Demo 4: Cognitive Process Categories")
    print("=" * 50)

    mapper = get_mapper()

    if mapper and mapper._loaded:
        summary = mapper.get_classification_summary()

        print("\nNiCLIP Cognitive Process Categories:")
        for process_id, info in summary["processes"].items():
            print(f"\n{process_id}: {info['name']}")
            print(f"  Tasks: {info['task_count']}")
            print(f"  Example concepts: {', '.join(info['example_concepts'][:3])}...")
            print(f"  Example tasks: {', '.join(info['example_tasks'][:2])}...")


if __name__ == "__main__":
    print("🎯 NiCLIP Integration Demo")
    print(
        "This shows how to use NiCLIP's scientifically validated task classifications\n"
    )

    demo_direct_usage()
    demo_mapper_usage()
    demo_integration()
    demo_process_mapping()

    print("\n\n✨ Key Benefits of NiCLIP:")
    print("- Scientifically validated mappings from neuroimaging data")
    print("- Clean 3-level hierarchy: Task → Concept → Process")
    print("- Only 6 main cognitive processes (vs arbitrary topic weights)")
    print("- 88 validated tasks with proper concept mappings")
    print("- Backward compatible with existing code")
