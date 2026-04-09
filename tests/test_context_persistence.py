"""Tests for context_persistence module: save/load roundtrip and corruption recovery."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from code_review_graph.agent_detect import AGENT_PROFILES
from code_review_graph.context_config import ContextConfig
from code_review_graph.context_graph import ContextGraph
from code_review_graph.context_persistence import (
    clear_context,
    load_context,
    save_context,
)


class TestContextPersistence:
    """Test save/load roundtrip functionality."""

    def test_save_empty_context(self, tmp_path: Path) -> None:
        """Test saving empty context."""
        config = ContextConfig(100000, 0.85, 2, str(tmp_path / "context.db"))
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        # Save empty graph
        save_context(graph, str(tmp_path / "context.db"))

        # Verify file was created
        assert (tmp_path / "context.db").exists()

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """Test saving and loading context preserves state."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        # Create graph with nodes
        graph1 = ContextGraph(config, agent)
        graph1.record_access("src/utils.py:func1", "Function", 300, "tool1", "ctx1")
        graph1.record_access("src/models.py:User", "Class", 500, "tool2", "ctx2")
        save_context(graph1, db_path)

        # Load from disk
        graph2 = load_context(db_path, config, agent)

        # Verify state is preserved
        assert len(graph2.active_context()) == 2
        assert graph2.current_token_usage() == 800

        node1 = graph2.get_context("src/utils.py:func1")
        assert node1 is not None
        assert node1.token_estimate == 300
        assert node1.access_count == 1

        node2 = graph2.get_context("src/models.py:User")
        assert node2 is not None
        assert node2.token_estimate == 500

    def test_load_preserves_access_history(self, tmp_path: Path) -> None:
        """Test that access history is preserved after save/load."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        # Record multiple accesses
        graph1 = ContextGraph(config, agent)
        graph1.record_access("node1", "Function", 100, "tool1", "ctx1")
        time.sleep(0.01)
        graph1.record_access("node1", "Function", 100, "tool2", "ctx2")

        save_context(graph1, db_path)

        # Load and verify access count
        graph2 = load_context(db_path, config, agent)
        node = graph2.get_context("node1")
        assert node is not None
        assert node.access_count == 2
        assert len(node.access_log) <= 2  # Keeps last 2 for LRU-K

    def test_load_nonexistent_db_returns_empty(self, tmp_path: Path) -> None:
        """Test loading non-existent database returns empty graph."""
        db_path = str(tmp_path / "nonexistent.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        graph = load_context(db_path, config, agent)
        assert len(graph.active_context()) == 0
        assert graph.current_token_usage() == 0

    def test_clear_context_deletes_file(self, tmp_path: Path) -> None:
        """Test clearing context deletes database file."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        # Create and save
        graph = ContextGraph(config, agent)
        graph.record_access("node1", "Function", 100, "tool1")
        save_context(graph, db_path)
        assert Path(db_path).exists()

        # Clear
        clear_context(db_path)
        assert not Path(db_path).exists()


class TestCorruptionRecovery:
    """Test graceful handling of corrupted databases."""

    def test_load_corrupted_db_returns_empty(self, tmp_path: Path) -> None:
        """Test that corrupted database is gracefully ignored."""
        db_path = str(tmp_path / "corrupt.db")

        # Write invalid SQLite data
        Path(db_path).write_bytes(b"not a valid sqlite database")

        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        # Should not raise; should return empty graph
        graph = load_context(db_path, config, agent)
        assert len(graph.active_context()) == 0

    def test_load_empty_db_file_returns_empty(self, tmp_path: Path) -> None:
        """Test that empty file is handled gracefully."""
        db_path = str(tmp_path / "empty.db")
        Path(db_path).write_bytes(b"")

        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        graph = load_context(db_path, config, agent)
        assert len(graph.active_context()) == 0


class TestPersistenceSchema:
    """Test database schema and migrations."""

    def test_context_nodes_table_created(self, tmp_path: Path) -> None:
        """Test that context_nodes table is created."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        graph = ContextGraph(config, agent)
        graph.record_access("node1", "Function", 100, "tool1")
        save_context(graph, db_path)

        # Verify schema
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='context_nodes'")
        assert cursor.fetchone() is not None
        conn.close()

    def test_access_logs_table_created(self, tmp_path: Path) -> None:
        """Test that access_logs table is created."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        graph = ContextGraph(config, agent)
        graph.record_access("node1", "Function", 100, "tool1", "ctx1")
        save_context(graph, db_path)

        # Verify schema
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='access_logs'")
        assert cursor.fetchone() is not None
        conn.close()

    def test_indexes_created(self, tmp_path: Path) -> None:
        """Test that indexes are created for performance."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        graph = ContextGraph(config, agent)
        graph.record_access("node1", "Function", 100, "tool1")
        save_context(graph, db_path)

        # Verify indexes exist
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        indexes = cursor.fetchall()
        assert len(indexes) > 0  # Should have at least one index
        conn.close()


class TestMultipleSaveLoad:
    """Test multiple save/load cycles."""

    def test_incremental_save_load(self, tmp_path: Path) -> None:
        """Test multiple save/load cycles."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        # Cycle 1: Save
        graph1 = ContextGraph(config, agent)
        graph1.record_access("node1", "Function", 100, "tool1")
        save_context(graph1, db_path)

        # Cycle 2: Load and add
        graph2 = load_context(db_path, config, agent)
        assert len(graph2.active_context()) == 1
        graph2.record_access("node2", "Function", 200, "tool2")
        save_context(graph2, db_path)

        # Cycle 3: Load and verify
        graph3 = load_context(db_path, config, agent)
        assert len(graph3.active_context()) == 2
        assert graph3.current_token_usage() == 300

    def test_save_overwrites_previous(self, tmp_path: Path) -> None:
        """Test that save overwrites previous state."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        # Save v1
        graph1 = ContextGraph(config, agent)
        graph1.record_access("node1", "Function", 100, "tool1")
        save_context(graph1, db_path)

        # Save v2 (different content)
        graph2 = ContextGraph(config, agent)
        graph2.record_access("node2", "Function", 200, "tool2")
        save_context(graph2, db_path)

        # Load and verify v2
        graph3 = load_context(db_path, config, agent)
        assert len(graph3.active_context()) == 1
        assert graph3.get_context("node2") is not None
        assert graph3.get_context("node1") is None
