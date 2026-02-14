"""Tests for the config module (paths, constants, data dirs)."""

import pytest
from pathlib import Path

from jaybrain.config import (
    ensure_data_dirs,
    MEMORY_CATEGORIES,
    FORGE_CATEGORIES,
    FORGE_INTERVALS,
    FORGE_MASTERY_LEVELS,
    FORGE_MASTERY_DELTAS_V2,
    FORGE_BLOOM_LEVELS,
    FORGE_ERROR_TYPES,
    GRAPH_ENTITY_TYPES,
    GRAPH_RELATIONSHIP_TYPES,
    EMBEDDING_DIM,
)
import jaybrain.config as config


class TestEnsureDataDirs:
    def test_creates_directories(self, temp_data_dir):
        ensure_data_dirs()
        assert config.DATA_DIR.exists()
        assert config.MEMORIES_DIR.exists()
        assert config.SESSIONS_DIR.exists()
        assert config.MODELS_DIR.exists()
        assert config.FORGE_DIR.exists()

    def test_creates_category_subdirs(self, temp_data_dir):
        ensure_data_dirs()
        for cat in MEMORY_CATEGORIES:
            assert (config.MEMORIES_DIR / cat).exists()

    def test_idempotent(self, temp_data_dir):
        ensure_data_dirs()
        ensure_data_dirs()
        assert config.DATA_DIR.exists()


class TestConstants:
    def test_memory_categories(self):
        assert "semantic" in MEMORY_CATEGORIES
        assert "episodic" in MEMORY_CATEGORIES
        assert "procedural" in MEMORY_CATEGORIES
        assert "decision" in MEMORY_CATEGORIES
        assert "preference" in MEMORY_CATEGORIES

    def test_forge_categories(self):
        assert "python" in FORGE_CATEGORIES
        assert "security" in FORGE_CATEGORIES
        assert "general" in FORGE_CATEGORIES

    def test_forge_intervals_ascending(self):
        keys = sorted(FORGE_INTERVALS.keys())
        values = [FORGE_INTERVALS[k] for k in keys]
        for i in range(len(values) - 1):
            assert values[i] < values[i + 1]

    def test_forge_mastery_levels_ascending(self):
        thresholds = [t for _, t in FORGE_MASTERY_LEVELS]
        for i in range(len(thresholds) - 1):
            assert thresholds[i] < thresholds[i + 1]

    def test_mastery_deltas_v2_quadrants(self):
        assert FORGE_MASTERY_DELTAS_V2["correct_confident"] > 0
        assert FORGE_MASTERY_DELTAS_V2["correct_unsure"] > 0
        assert FORGE_MASTERY_DELTAS_V2["incorrect_confident"] < 0
        assert FORGE_MASTERY_DELTAS_V2["incorrect_unsure"] < 0
        assert FORGE_MASTERY_DELTAS_V2["skipped"] == 0

    def test_bloom_levels_order(self):
        assert FORGE_BLOOM_LEVELS == ["remember", "understand", "apply", "analyze"]

    def test_error_types(self):
        assert set(FORGE_ERROR_TYPES) == {"slip", "lapse", "mistake", "misconception"}

    def test_graph_entity_types(self):
        assert "person" in GRAPH_ENTITY_TYPES
        assert "project" in GRAPH_ENTITY_TYPES
        assert "tool" in GRAPH_ENTITY_TYPES

    def test_graph_relationship_types(self):
        assert "uses" in GRAPH_RELATIONSHIP_TYPES
        assert "depends_on" in GRAPH_RELATIONSHIP_TYPES

    def test_embedding_dim(self):
        assert EMBEDDING_DIM == 384
