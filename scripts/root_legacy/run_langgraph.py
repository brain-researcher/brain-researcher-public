#!/usr/bin/env python3
"""
Legacy interactive runner for the Brain Researcher LangGraph agent.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from brain_researcher.services.agent.brain_researcher_graph import BrainResearcherGraph

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def run_interactive_session():
    """Run an interactive session with the Brain Researcher agent."""
    print("\n🧠 Brain Researcher Agent - LangGraph Edition")
    print("=" * 50)
    print("Type 'exit' to quit, 'help' for available commands\n")

    graph = BrainResearcherGraph()
    thread_id = None

    while True:
        try:
            query = input("\n> ").strip()

            if query.lower() == "exit":
                print("Goodbye!")
                break

            elif query.lower() == "help":
                print("\nAvailable commands:")
                print("  help - Show this help message")
                print("  tools - List available tools")
                print("  new - Start a new conversation thread")
                print("  exit - Exit the program")
                print("\nExample queries:")
                print("  - What is the n-back task?")
                print("  - Find concepts related to motor cortex")
                print("  - Run GLM analysis on dataset ds000001")
                continue

            elif query.lower() == "tools":
                print("\nAvailable tools:")
                for tool in graph.tool_registry.get_all_tools():
                    print(f"  - {tool.get_tool_name()}: {tool.get_tool_description()}")
                continue

            elif query.lower() == "new":
                thread_id = None
                print("Started new conversation thread")
                continue

            if not query:
                continue

            # Run the agent
            print("\n🔄 Processing...")

            async for event in graph.arun(query, thread_id):
                # Process and display events
                if "understand_query" in event:
                    print("📊 Understanding query...")

                elif "select_tools" in event:
                    state = event["select_tools"]
                    if state.get("selected_tools"):
                        tools = ", ".join(state["selected_tools"])
                        print(f"🔧 Selected tools: {tools}")

                elif "execute_tools" in event:
                    state = event["execute_tools"]
                    print("⚙️ Executing tools...")

                    # Show tool results
                    for tool_name, result in state.get("tool_results", {}).items():
                        if result.get("status") == "success":
                            print(f"  ✅ {tool_name}: Success")
                        else:
                            print(f"  ❌ {tool_name}: {result.get('error', 'Failed')}")

                elif "synthesize" in event:
                    state = event["synthesize"]
                    if state.get("synthesis"):
                        print("\n📝 Results:")
                        print("-" * 50)
                        print(state["synthesis"].get("summary", "No summary available"))
                        print("-" * 50)

        except KeyboardInterrupt:
            print("\n\nInterrupted. Type 'exit' to quit.")
        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"\n❌ Error: {e}")


async def run_single_query(query: str, thread_id: str | None = None, resume_checkpoint_id: str | None = None):
    """Run a single query through the agent."""
    graph = BrainResearcherGraph()

    print(f"\n🔄 Processing: {query}")

    result = None
    async for event in graph.arun(query, thread_id, resume_checkpoint_id=resume_checkpoint_id):
        if "synthesize" in event:
            result = event["synthesize"]

    if result and result.get("synthesis"):
        print("\n📝 Results:")
        print(result["synthesis"].get("summary", "No summary available"))

        if result["synthesis"].get("tool_results"):
            print("\n🔧 Tool Results:")
            for tool, data in result["synthesis"].get("tool_results", {}).items():
                print(f"  - {tool}: {data.get('status', 'unknown')}")

        checkpoint_id = result.get("checkpoint_id") or result.get("last_checkpoint_id")
        if checkpoint_id:
            print(f"\n💾 Last checkpoint id: {checkpoint_id}")

    return result


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Brain Researcher Agent - LangGraph Edition"
    )
    parser.add_argument(
        "query", nargs="?", help="Query to process (interactive mode if not provided)"
    )
    parser.add_argument("--thread-id", help="Thread ID for conversation continuity")
    parser.add_argument("--resume-checkpoint", help="Checkpoint id to resume from")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.query:
        # Single query mode
        asyncio.run(run_single_query(args.query, args.thread_id, resume_checkpoint_id=args.resume_checkpoint))
    else:
        # Interactive mode
        try:
            asyncio.run(run_interactive_session())
        except KeyboardInterrupt:
            print("\nGoodbye!")


if __name__ == "__main__":
    main()
