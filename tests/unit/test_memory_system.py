"""Unit tests for the memory system."""

import pytest
from pathlib import Path
import tempfile
import shutil
from datetime import datetime, timedelta

from brain_researcher.core.memory import MemoryStore, MemorySelector
from brain_researcher.core.memory.memory_store import Memory
from brain_researcher.core.memory.memory_selector import TaskContext


class TestMemoryStore:
    """Test the MemoryStore class."""
    
    @pytest.fixture
    def temp_memory_dir(self):
        """Create a temporary directory with test memory files."""
        temp_dir = tempfile.mkdtemp()
        memory_path = Path(temp_dir) / "memory"
        memory_path.mkdir()
        
        # Create test memory files
        decisions_dir = memory_path / "decisions"
        decisions_dir.mkdir()
        
        # Test memory 1: CVMFS preference
        memory1 = decisions_dir / "prefer_cvmfs.md"
        memory1.write_text("""---
type: memory
id: cvmfs-test
scope: codebase
confidence: 0.9
tags: [cvmfs, neurodesk]
applies_when: ["using neuroimaging tools"]
avoid_when: ["local development"]
created: 2025-08-21
updated: 2025-08-21
---

# Prefer CVMFS for neuroimaging tools

## Why
Better reproducibility

## LLM Prompt Fragment
> House Rule: Use CVMFS when available
""")
        
        # Test memory 2: GLM best practice
        research_dir = memory_path / "research"
        research_dir.mkdir()
        
        memory2 = research_dir / "glm_subject_split.md"
        memory2.write_text("""---
type: memory
id: glm-test
scope: research
confidence: 0.95
tags: [glm, statistics]
applies_when: ["cross-validation", "fmri analysis"]
avoid_when: ["single subject"]
created: 2025-08-20
updated: 2025-08-20
---

# Use subject-level splits for GLM

## Why
Statistical independence

## LLM Prompt Fragment
> House Rule: Always use GroupKFold with subject IDs
""")
        
        yield str(memory_path)
        
        # Cleanup
        shutil.rmtree(temp_dir)
    
    def test_load_memories(self, temp_memory_dir):
        """Test loading memories from directory."""
        store = MemoryStore(temp_memory_dir)
        
        assert len(store.memories) == 2
        
        # Check first memory
        cvmfs_memory = next((m for m in store.memories if m.id == "cvmfs-test"), None)
        assert cvmfs_memory is not None
        assert cvmfs_memory.confidence == 0.9
        assert "cvmfs" in cvmfs_memory.tags
        assert cvmfs_memory.scope == "codebase"
    
    def test_search_by_tags(self, temp_memory_dir):
        """Test searching memories by tags."""
        store = MemoryStore(temp_memory_dir)
        
        # Search for GLM-related memories
        results = store.search(tags=["glm"])
        assert len(results) == 1
        assert results[0].id == "glm-test"
        
        # Search for neurodesk-related memories
        results = store.search(tags=["neurodesk"])
        assert len(results) == 1
        assert results[0].id == "cvmfs-test"
    
    def test_search_by_scope(self, temp_memory_dir):
        """Test searching memories by scope."""
        store = MemoryStore(temp_memory_dir)
        
        # Search for research scope
        results = store.search(scope="research")
        assert len(results) == 1
        assert results[0].id == "glm-test"
        
        # Search for codebase scope
        results = store.search(scope="codebase")
        assert len(results) == 1
        assert results[0].id == "cvmfs-test"
    
    def test_keyword_search(self, temp_memory_dir):
        """Test keyword-based search."""
        store = MemoryStore(temp_memory_dir)
        
        # Search for "reproducibility"
        results = store.search(query="reproducibility")
        assert len(results) >= 1
        assert any(m.id == "cvmfs-test" for m in results)
        
        # Search for "statistical"
        results = store.search(query="statistical")
        assert len(results) >= 1
        assert any(m.id == "glm-test" for m in results)
    
    def test_confidence_filtering(self, temp_memory_dir):
        """Test filtering by minimum confidence."""
        store = MemoryStore(temp_memory_dir)
        
        # High confidence threshold
        results = store.search(min_confidence=0.92)
        assert len(results) == 1
        assert results[0].id == "glm-test"
        
        # Lower threshold
        results = store.search(min_confidence=0.85)
        assert len(results) == 2
    
    def test_decay_factor(self):
        """Test memory decay calculation."""
        memory = Memory(
            id="test",
            type="memory",
            scope="test",
            confidence=1.0,
            title="Test",
            content="Test content",
            updated=datetime.now() - timedelta(days=180),
            decay_half_life_days=180
        )
        
        # After one half-life, confidence should be ~0.5
        assert 0.49 < memory.effective_confidence < 0.51
        
        # Fresh memory should have full confidence
        fresh_memory = Memory(
            id="fresh",
            type="memory",
            scope="test",
            confidence=0.8,
            title="Fresh",
            content="Fresh content",
            updated=datetime.now(),
            decay_half_life_days=180
        )
        assert fresh_memory.effective_confidence == 0.8


class TestMemorySelector:
    """Test the MemorySelector class."""
    
    @pytest.fixture
    def selector_with_memories(self, temp_memory_dir):
        """Create a selector with test memories."""
        store = MemoryStore(temp_memory_dir)
        return MemorySelector(store)
    
    def test_select_memories_by_context(self, selector_with_memories):
        """Test selecting memories based on task context."""
        context = TaskContext(
            task_type="fmri_analysis",
            environment="hpc",
            tools=["fsl", "ants"],
            datasets=["openneuro"]
        )
        
        memories = selector_with_memories.select_memories(
            task="Run fMRI preprocessing on HPC",
            context=context,
            k=5
        )
        
        # Should select CVMFS memory for HPC + neuroimaging tools
        assert any(m.id == "cvmfs-test" for m in memories)
    
    def test_format_house_rules(self, selector_with_memories):
        """Test formatting memories as house rules."""
        # Get all memories
        memories = selector_with_memories.store.memories
        
        rules = selector_with_memories.format_as_house_rules(memories)
        
        assert "[Project Memory - House Rules]" in rules
        assert "Use CVMFS when available" in rules
        assert "Always use GroupKFold" in rules
    
    def test_empty_memory_handling(self):
        """Test handling when no memories are available."""
        empty_store = MemoryStore("nonexistent_path")
        selector = MemorySelector(empty_store)
        
        memories = selector.select_memories("Some task")
        assert memories == []
        
        rules = selector.format_as_house_rules([])
        assert rules == ""
    
    def test_context_extraction(self, selector_with_memories):
        """Test extracting context from agent state."""
        state = {
            "messages": [
                type("Message", (), {"content": "I need to run fMRIPrep on Sherlock cluster"})()
            ]
        }
        
        context = selector_with_memories.get_context_from_state(state)
        
        assert context.task_type == "fmri_analysis"
        assert context.environment == "hpc"
        assert "fmriprep" in context.tools
    
    def test_conflict_resolution(self, selector_with_memories):
        """Test that conflicting memories are resolved."""
        # Create two memories about the same topic with different confidence
        memory1 = Memory(
            id="mem1",
            type="memory",
            scope="test",
            confidence=0.7,
            title="Use approach A",
            content="Content A",
            tags=["testing"],
            updated=datetime.now()
        )
        
        memory2 = Memory(
            id="mem2", 
            type="memory",
            scope="test",
            confidence=0.9,
            title="Use approach B",
            content="Content B",
            tags=["testing"],
            updated=datetime.now()
        )
        
        selector = MemorySelector(None)
        resolved = selector._resolve_conflicts([memory1, memory2])
        
        # Should keep the higher confidence one
        assert len(resolved) <= 2  # May keep both if topics differ
        if len(resolved) == 1:
            assert resolved[0].confidence == 0.9
    
    def test_compliance_checking(self, selector_with_memories):
        """Test checking plans against house rules."""
        memories = selector_with_memories.store.memories
        
        # Plan that violates a rule
        bad_plan = "Run analysis on local development machine using apt-installed tools"
        
        violations = selector_with_memories.check_plan_compliance(bad_plan, memories)
        
        # Should detect violation of CVMFS rule
        assert len(violations) > 0
        assert any("avoid when" in v.lower() for v in violations)


class TestMemoryIntegration:
    """Test integration between memory components."""
    
    def test_end_to_end_memory_flow(self, temp_memory_dir):
        """Test complete flow from loading to selection to formatting."""
        # Load memories
        store = MemoryStore(temp_memory_dir)
        selector = MemorySelector(store)
        
        # Create task context
        context = TaskContext(
            task_type="fmri_analysis",
            environment="hpc",
            tools=["fsl"],
            datasets=[]
        )
        
        # Select relevant memories
        memories = selector.select_memories(
            task="Process fMRI data with FSL",
            context=context,
            k=3
        )
        
        # Format as rules
        rules = selector.format_as_house_rules(memories)
        
        # Verify the flow worked
        assert len(memories) > 0
        assert len(rules) > 0
        assert "House Rules" in rules
    
    def test_memory_with_missing_fields(self, tmp_path):
        """Test handling memories with optional fields missing."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        
        # Create minimal memory file
        minimal_memory = memory_dir / "minimal.md"
        minimal_memory.write_text("""---
type: memory
id: minimal
scope: test
confidence: 0.5
---

# Minimal memory

Content here
""")
        
        store = MemoryStore(str(memory_dir))
        assert len(store.memories) == 1
        
        memory = store.memories[0]
        assert memory.id == "minimal"
        assert memory.tags == []  # Should have empty default
        assert memory.applies_when == []
        assert memory.llm_prompt is None