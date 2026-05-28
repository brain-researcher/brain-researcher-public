import json
import pytest
from pathlib import Path

from brain_researcher.semantics.taxonomy.matcher import normalize_text, TaskMatcher, build_flat_map

@pytest.fixture
def taxonomy_dir(tmp_path: Path) -> Path:
    """Creates a temporary taxonomy directory with mock data for testing."""
    entities_data = {
        "entities": {
            "task:n-back": {
                "label": "n-back", "type": "Task",
                "measures": ["construct:working-memory"], "domains": ["domain:executive-function"]
            },
            "task:go-no-go": {
                "label": "go/no-go", "type": "Task"
            },
            "construct:working-memory": {"label": "working memory", "type": "Construct"},
            "domain:executive-function": {"label": "executive function", "type": "Domain"}
        }
    }
    rules_data = {
        "surface_rules": [
            {
                "pattern": r"\b(\d+)[- ]?back\b",
                "canonical": "task:n-back",
                "extract": {"level": "1"},
                "confidence": 0.98
            },
            {
                "pattern": r"\b(verbal|spatial)\s+n[- ]?back\b",
                "canonical": "task:n-back",
                "extract": {"modality": "1"}
            },
            {
                "pattern": r"\b(go[- /]?no[- /]?go|gng)\b",
                "canonical": "task:go-no-go",
                "confidence": 0.99
            }
        ]
    }
    
    entities_path = tmp_path / "entities.json"
    rules_path = tmp_path / "surface_rules.json"
    
    with open(entities_path, "w") as f:
        json.dump(entities_data, f)
    with open(rules_path, "w") as f:
        json.dump(rules_data, f)
        
    return tmp_path


class TestNormalizeText:
    def test_casefolding(self):
        assert normalize_text("N-BACK TASK") == "n back"

    def test_unicode_normalization(self):
        assert normalize_text("go/no\u2010go") == "go no go" # HYPHEN instead of HYPHEN-MINUS

    def test_punctuation_stripping(self):
        assert normalize_text("'stroop, task!?'") == "stroop"

    def test_whitespace_collapse(self):
        assert normalize_text("  stop    signal  ") == "stop signal"

    def test_boilerplate_removal(self):
        assert normalize_text("n-back paradigm") == "n back"
        assert normalize_text("the flanker test") == "flanker"


class TestTaskMatcher:
    def test_initialization(self, taxonomy_dir):
        matcher = TaskMatcher(entities_path=taxonomy_dir / "entities.json", rules_path=taxonomy_dir / "surface_rules.json")
        assert len(matcher.compiled_rules) == 3
        assert "task:n-back" in matcher.entities

    def test_simple_match(self, taxonomy_dir):
        matcher = TaskMatcher(entities_path=taxonomy_dir / "entities.json", rules_path=taxonomy_dir / "surface_rules.json")
        result = matcher.match("a test of go/no-go response")
        assert result is not None
        assert result["canonical_id"] == "task:go-no-go"
        assert result["label"] == "go/no-go"

    def test_parameter_extraction_level(self, taxonomy_dir):
        matcher = TaskMatcher(entities_path=taxonomy_dir / "entities.json", rules_path=taxonomy_dir / "surface_rules.json")
        result = matcher.match("3-back task")
        assert result is not None
        assert result["canonical_id"] == "task:n-back"
        assert result["parameters"] == {"level": "3"}

    def test_parameter_extraction_modality(self, taxonomy_dir):
        matcher = TaskMatcher(entities_path=taxonomy_dir / "entities.json", rules_path=taxonomy_dir / "surface_rules.json")
        result = matcher.match("verbal n-back")
        assert result is not None
        assert result["canonical_id"] == "task:n-back"
        assert result["parameters"] == {"modality": "verbal"}

    def test_no_match(self, taxonomy_dir):
        matcher = TaskMatcher(entities_path=taxonomy_dir / "entities.json", rules_path=taxonomy_dir / "surface_rules.json")
        result = matcher.match("this is a completely unrelated string")
        assert result is None


class TestBackwardCompatibility:
    def test_build_flat_map(self, taxonomy_dir):
        flat_map = build_flat_map(entities_path=taxonomy_dir / "entities.json", rules_path=taxonomy_dir / "surface_rules.json")
        assert isinstance(flat_map, dict)
        # Note: The keys are simplified patterns, so we check for values
        assert "n-back" in flat_map.values()
        assert "go/no-go" in flat_map.values()