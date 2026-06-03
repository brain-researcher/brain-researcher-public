#!/usr/bin/env python3
"""Test NiCLIP integration with various examples."""


from brain_researcher.services.br_kg.etl.mappers.niclip_task_mapper import get_mapper
from brain_researcher.services.br_kg.utils.vocab_loader import (
    get_task_concepts,
    get_task_process_name,
    search_similar_tasks,
)


def test_examples():
    """Run various examples of NiCLIP task classification."""

    print("🧠 NiCLIP Task Classification Examples")
    print("=" * 60)

    # Example 1: Common neuroscience tasks
    print("\n📋 Example 1: Common Neuroscience Tasks")
    print("-" * 40)

    common_tasks = [
        "n-back task",
        "stroop task",
        "go/no-go task",
        "face viewing",
        "finger tapping",
        "resting state",
        "working memory task",
        "emotional faces",
    ]

    for task in common_tasks:
        concepts = get_task_concepts(task)
        process = get_task_process_name(task)

        if concepts:
            print(f"\n✓ '{task}':")
            print(f"  → Concepts: {', '.join(concepts)}")
            print(f"  → Cognitive Process: {process or 'Not mapped'}")
        else:
            # Try to find similar tasks
            similar = search_similar_tasks(task, top_k=1)
            if similar and similar[0]["score"] > 0.3:
                match = similar[0]["task"]
                concepts = get_task_concepts(match)
                process = get_task_process_name(match)
                print(
                    f"\n≈ '{task}' → matched to '{match}' (score: {similar[0]['score']:.2f}):"
                )
                print(f"  → Concepts: {', '.join(concepts) if concepts else 'None'}")
                print(f"  → Cognitive Process: {process or 'Not mapped'}")
            else:
                print(f"\n✗ '{task}': Not found in NiCLIP")

    # Example 2: Search for tasks by keyword
    print("\n\n🔍 Example 2: Search Tasks by Keyword")
    print("-" * 40)

    keywords = ["memory", "visual", "motor", "emotion", "language", "attention"]

    for keyword in keywords:
        similar = search_similar_tasks(keyword, top_k=3)
        if similar:
            print(f"\n'{keyword}' related tasks:")
            for match in similar:
                task_name = match["task"]
                score = match["score"]
                concepts = get_task_concepts(task_name)
                if concepts:
                    print(f"  • {task_name} (score: {score:.2f})")
                    print(f"    Concepts: {', '.join(concepts[:2])}...")

    # Example 3: Show tasks by cognitive process
    print("\n\n🧩 Example 3: Tasks Grouped by Cognitive Process")
    print("-" * 40)

    mapper = get_mapper()
    if mapper and mapper._loaded:
        processes = {
            "ctp_C1": "Perception",
            "ctp_C3": "Cognitive Control",
            "ctp_C4": "Visual Processing",
            "ctp_C6": "Language",
            "ctp_C7": "Motor",
            "ctp_C8": "Emotion",
        }

        for process_id, process_name in processes.items():
            tasks = mapper.get_process_tasks(process_id)
            if tasks:
                print(f"\n{process_name} ({process_id}):")
                # Show up to 5 example tasks
                for task in tasks[:5]:
                    concepts = mapper.get_task_concepts(task)
                    if concepts:
                        print(f"  • {task}")
                        print(f"    → {', '.join(concepts[:2])}...")

    # Example 4: Detailed task information
    print("\n\n📊 Example 4: Detailed Task Analysis")
    print("-" * 40)

    detailed_tasks = [
        "n-back task",
        "emotional faces task",
        "language fMRI task paradigm",
    ]

    for task in detailed_tasks:
        if mapper and mapper._loaded:
            info = mapper.format_task_info(task)
            if info["concepts"]:
                print(f"\n{info['task']}:")
                print(f"  Concepts: {', '.join(info['concepts'])}")
                print(f"  Primary Category: {info['primary_category'] or 'Unmapped'}")
                if info["processes"]:
                    print(
                        f"  All Processes: {', '.join([p['name'] for p in info['processes']])}"
                    )

    # Example 5: Statistics
    print("\n\n📈 Example 5: NiCLIP Dataset Statistics")
    print("-" * 40)

    if mapper and mapper._loaded:
        summary = mapper.get_classification_summary()
        print(f"\nTotal tasks: {summary['total_tasks']}")
        print(f"Total concepts: {summary['total_concepts']}")
        print(f"Mapped concepts: {summary['mapped_concepts']}")
        print(f"Unmapped concepts: {summary['unmapped_concepts']}")

        print("\nTasks per cognitive process:")
        for process_id, info in summary["processes"].items():
            print(f"  • {info['name']}: {info['task_count']} tasks")


if __name__ == "__main__":
    test_examples()
