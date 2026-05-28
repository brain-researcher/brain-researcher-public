import json

from brain_researcher.services.agent.memory import ConversationMemory


def test_memory_append_and_recent(tmp_path):
    store = tmp_path / "memory.md"
    mem = ConversationMemory(store_path=store, max_entries_per_thread=2)

    mem.append("thread-1", "user", "hello", {"turn": 1})
    mem.append("thread-1", "assistant", "hi", {"turn": 2})
    mem.append("thread-1", "user", "second", {"turn": 3})

    recent = mem.get_recent("thread-1", limit=5)
    assert len(recent) == 2  # trimmed to max_entries_per_thread
    assert recent[-1].content == "second"

    md_text = store.read_text(encoding="utf-8")
    assert "thread-1" in md_text
    # ensure JSON sidecar is in sync
    jsonl = store.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(jsonl[-1])["content"] == "second"
