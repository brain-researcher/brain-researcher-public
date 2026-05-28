import asyncio

from brain_researcher.services.agent.codegen.fs_context import build_fs_context_for_task


class FakeFsClient:
    def __init__(self, search_hits, contents):
        self._hits = search_hits
        self._contents = contents

    async def search_text(self, query: str, root: str, max_results: int = 200):
        return self._hits[:max_results]

    async def read_file(self, path: str, max_bytes: int = 8000, offset: int = 0):
        return self._contents[path]


def test_build_fs_context_returns_snippets():
    search_hits = [
        {"path": "src/a.py", "line": 10},
        {"path": "src/b.py", "line": 5},
    ]
    contents = {
        "src/a.py": "def a():\n    return 1\n",
        "src/b.py": "def b():\n    return 2\n",
    }
    client = FakeFsClient(search_hits, contents)

    snippets = asyncio.run(
        build_fs_context_for_task("return", repo_root=".", fs_client=client, max_files=5, max_chars_per_file=200)
    )

    assert len(snippets) == 2
    assert snippets[0].path == "src/a.py"
    assert snippets[0].start_line == 10
    assert "def a" in snippets[0].snippet


def test_build_fs_context_truncates_long_files():
    search_hits = [{"path": "src/long.py", "line": 1}]
    contents = {"src/long.py": "x" * 5000}
    client = FakeFsClient(search_hits, contents)

    snippets = asyncio.run(
        build_fs_context_for_task("x", repo_root=".", fs_client=client, max_files=1, max_chars_per_file=100)
    )

    assert len(snippets) == 1
    assert len(snippets[0].snippet) <= 110  # includes truncation marker
    assert "(truncated)" in snippets[0].snippet
