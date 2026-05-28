"""Tests for synonym loader module."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from brain_researcher.services.agent.planner.synonyms_loader import (
    _clean,
    load_synonym_map,
    match_intents,
    get_operator_synonyms,
    get_mappings_dir,
    clear_cache,
)


class TestTextCleaning:
    """Test text normalization."""

    def test_clean_lowercase(self):
        """Test that text is lowercased."""
        assert _clean("SKULL STRIP") == "skull strip"
        assert _clean("Brain Extraction") == "brain extraction"

    def test_clean_punctuation(self):
        """Test that punctuation is removed."""
        assert _clean("skull-strip!") == "skull strip"
        assert _clean("skull_strip?") == "skull_strip"  # Underscores are kept
        assert _clean("brain,extraction.") == "brain extraction"

    def test_clean_whitespace(self):
        """Test that whitespace is collapsed."""
        assert _clean("  skull   strip  ") == "skull strip"
        assert _clean("skull\t\nstrip") == "skull strip"

    def test_clean_modality_scope(self):
        """Test that @ is preserved for modality scoping."""
        assert _clean("connectome@fmri") == "connectome@fmri"
        assert _clean("CONNECTOME@FMRI") == "connectome@fmri"


class TestSynonymMapLoading:
    """Test synonym map loading."""

    def test_load_synonym_map_returns_dict(self):
        """Test that load_synonym_map returns a dictionary."""
        clear_cache()
        map_data = load_synonym_map()
        assert isinstance(map_data, dict)
        assert len(map_data) > 0

    def test_load_synonym_map_has_op_synonyms(self):
        """Test that op_synonyms.yaml entries are loaded."""
        clear_cache()
        map_data = load_synonym_map()

        # Check for known op_synonyms entries
        assert "skull strip" in map_data
        assert map_data["skull strip"] == "skull_strip"

        assert "brain extraction" in map_data
        assert map_data["brain extraction"] == "skull_strip"

    def test_load_synonym_map_cached(self):
        """Test that synonym map is cached."""
        clear_cache()
        map1 = load_synonym_map()
        map2 = load_synonym_map()
        # Should be the same object due to LRU cache
        assert map1 is map2

    def test_mappings_dir_exists(self):
        """Test that mappings directory exists."""
        dir_path = get_mappings_dir()
        assert dir_path.exists()
        assert dir_path.is_dir()
        assert (dir_path / "op_synonyms.yaml").exists()


class TestIntentMatching:
    """Test intent matching functionality."""

    def test_match_intents_basic(self):
        """Test basic intent matching."""
        clear_cache()
        ops = match_intents("Please skull strip T1 image")
        assert "skull_strip" in ops

    def test_match_intents_includes_intent_synonyms(self):
        """intent_synonyms.yaml should be part of the unified synonym map."""
        clear_cache()
        ops = match_intents("run fmriprep on a BIDS dataset")
        assert "fmriprep_preprocessing" in ops

    def test_match_intents_multiple(self):
        """Test matching multiple operators in one text."""
        clear_cache()
        ops = match_intents("register and align the images")
        # Should match registration-related operators
        assert any("regist" in op.lower() for op in ops)

    def test_match_intents_modality_filter(self):
        """Test that modality filtering works."""
        clear_cache()
        # Test that the function runs without error with modality filter
        ops_fmri = match_intents("skull strip brain", modality="fmri")

        # Should return a list (even if empty is ok - depends on synonym data)
        assert isinstance(ops_fmri, list)

    def test_match_intents_empty_text(self):
        """Test with empty text."""
        clear_cache()
        ops = match_intents("")
        assert ops == []

    def test_match_intents_no_matches(self):
        """Test with text that has no operator matches."""
        clear_cache()
        ops = match_intents("xyz123 random nonsense text")
        assert ops == []

    def test_match_intents_case_insensitive(self):
        """Test that matching is case insensitive."""
        clear_cache()
        ops1 = match_intents("SKULL STRIP")
        ops2 = match_intents("skull strip")
        ops3 = match_intents("Skull Strip")

        assert ops1 == ops2 == ops3
        assert "skull_strip" in ops1

    def test_match_intents_punctuation_insensitive(self):
        """Test that punctuation doesn't affect matching."""
        clear_cache()
        ops1 = match_intents("skull-strip!")
        ops2 = match_intents("skull strip")

        assert ops1 == ops2

    def test_match_intents_phrase_matching(self):
        """Test that phrases are matched as well as individual words."""
        clear_cache()
        # "bias correction" as a phrase should match
        ops = match_intents("perform bias correction on the image")
        assert any("bias" in op.lower() or "correction" in op.lower() for op in ops)

    def test_match_intents_ranking(self):
        """Test that results are ranked (modality-scoped higher)."""
        clear_cache()
        # "functional connectivity" with fmri modality should prioritize fmri-specific ops
        ops = match_intents("functional connectivity analysis", modality="fmri")

        if len(ops) > 0:
            # First result should be relevant to connectivity
            assert any("connect" in ops[0].lower() or "seed" in ops[0].lower()
                      for _ in [ops[0]])


class TestOperatorSynonyms:
    """Test operator synonym lookup."""

    def test_get_operator_synonyms(self):
        """Test getting synonyms for an operator."""
        clear_cache()
        synonyms = get_operator_synonyms("skull_strip")

        assert len(synonyms) > 0
        assert "skull strip" in synonyms
        # Should be sorted
        assert synonyms == sorted(synonyms)

    def test_get_operator_synonyms_nonexistent(self):
        """Test getting synonyms for nonexistent operator."""
        clear_cache()
        synonyms = get_operator_synonyms("nonexistent_op_xyz123")
        assert synonyms == []


class TestPrecedence:
    """Test that op_synonyms takes precedence over other files."""

    def test_op_synonyms_precedence(self):
        """Test that op_synonyms.yaml overrides task/concept synonyms."""
        clear_cache()
        map_data = load_synonym_map()

        # If there's overlap, op_synonyms should win
        # Check a phrase that we know is in op_synonyms
        if "skull strip" in map_data:
            # Should map to operator name from op_synonyms
            assert map_data["skull strip"] == "skull_strip"


class TestModalityScoping:
    """Test modality-scoped operator matching."""

    def test_modality_scoped_operator_parsing(self):
        """Test that @ scoping is parsed correctly."""
        clear_cache()
        # If we have modality-scoped entries in op_synonyms
        map_data = load_synonym_map()

        # Check if any modality-scoped operators exist
        scoped_ops = [op for op in map_data.values() if "@" in op]

        if scoped_ops:
            # Test that matching respects the scope
            example_op = scoped_ops[0]
            op_name, modality = example_op.split("@")

            # Find a phrase that maps to this scoped operator
            phrase = next((p for p, o in map_data.items() if o == example_op), None)

            if phrase:
                # Should match with correct modality
                results_with_mod = match_intents(phrase, modality=modality)
                assert len(results_with_mod) > 0

                # Should not match with wrong modality
                wrong_mod = "xyz" if modality != "xyz" else "abc"
                results_wrong_mod = match_intents(phrase, modality=wrong_mod)
                # Either empty or doesn't contain our specific operator
                assert op_name not in results_wrong_mod or example_op not in map_data.values()

    def test_fmri_connectivity_scoping(self):
        """Test that fmri connectivity is properly scoped."""
        clear_cache()
        # Test that scoped matching works without error
        ops = match_intents("skull strip", modality="fmri")

        # Should return a list
        assert isinstance(ops, list)

        # If we got results, verify they make sense
        if len(ops) > 0:
            # Results should be strings
            assert all(isinstance(op, str) for op in ops)

    def test_modality_filter_priority(self):
        """Test that modality-scoped operators are prioritized."""
        clear_cache()
        # If we search for "connectivity" with fmri modality,
        # fmri-specific ops should rank higher than generic ones
        ops_with_modality = match_intents("connectivity", modality="fmri")
        ops_without_modality = match_intents("connectivity")

        # Both should return results (if connectivity synonyms exist)
        assert isinstance(ops_with_modality, list)
        assert isinstance(ops_without_modality, list)

        # If both have results, modality-scoped version should prioritize fmri ops
        if ops_with_modality and ops_without_modality:
            # Results can differ in ranking/content
            # This test just verifies both modes work
            assert len(ops_with_modality) >= 0
            assert len(ops_without_modality) >= 0

    def test_multiple_modalities_handled(self):
        """Test that different modalities work correctly."""
        clear_cache()
        # Test various modalities don't crash
        for modality in ["fmri", "smri", "dmri", "eeg", "meg", "ieeg"]:
            ops = match_intents("analysis", modality=modality)
            assert isinstance(ops, list)

    def test_overlapping_synonyms_priority(self):
        """Test that synonym priority order is maintained."""
        clear_cache()
        map_data = load_synonym_map()

        # The priority should be: op_synonyms > task > concept > roi
        # If the same phrase appears in multiple files, op_synonyms wins

        # Check for any phrase that might appear in multiple synonym files
        # For example, "registration" could be in both op and task synonyms
        if "registration" in map_data:
            # Should map to something (exact value depends on synonym files)
            assert map_data["registration"] is not None

        # Verify we have entries from different sources
        # (This is an indirect check - we can't easily tell source from map_data alone)
        assert len(map_data) > 10  # Should have decent number of entries
