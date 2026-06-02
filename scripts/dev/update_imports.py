#!/usr/bin/env python3
"""Update br_kg imports to services.br_kg."""

import argparse
from pathlib import Path

REPLACEMENTS = {
    "from br_kg": "from brain_researcher.services.br_kg",
    "import br_kg.": "import brain_researcher.services.br_kg.",
}


def update_imports(repo_path: Path) -> None:
    """Replace br_kg import strings in all Python files."""
    for py_file in repo_path.rglob("*.py"):
        if py_file == Path(__file__):
            continue
        if "__pycache__" in py_file.parts or py_file.parts[0].startswith("."):
            continue
        try:
            text = py_file.read_text()
        except Exception:
            continue
        new_text = text
        for old, new in REPLACEMENTS.items():
            if old in new_text:
                new_text = new_text.replace(old, new)
        if new_text != text:
            py_file.write_text(new_text)
            print(f"Updated {py_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update imports to services.br_kg")
    parser.add_argument("path", nargs="?", default=".", help="Repository root")
    args = parser.parse_args()

    update_imports(Path(args.path))


if __name__ == "__main__":
    main()
