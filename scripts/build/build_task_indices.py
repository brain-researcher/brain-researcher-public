"""Utility to rebuild task matcher indices."""

from brain_researcher.core.utils.task_matcher import TaskMatcher

if __name__ == "__main__":
    TaskMatcher()  # building on init
    print("Indices built and cached in memory. No persistence implemented.")
