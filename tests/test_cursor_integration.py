"""Integration tests verifying Cursor support in context-graph v3.0.0."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from code_review_graph.agent_detect import AGENT_PROFILES, detect_agent, get_agent_by_name
from code_review_graph.context_config import ContextConfig, load_context_config
from code_review_graph.context_graph import ContextGraph
from code_review_graph.context_persistence import load_context, save_context
from code_review_graph.tools.context_tools import clear_context, get_active_context, get_context_summary


class TestCursorDetection:
    """Test Cursor detection and configuration."""

    def test_cursor_env_var_detection(self) -> None:
        """Test detecting Cursor from CURSOR env var."""
        os.environ["CURSOR"] = "1"
        try:
            agent = detect_agent()
            assert agent.name == "Cursor"
            assert agent.context_window == 128000
            assert agent.estimated_overhead == 15000
            assert agent.effective_capacity() == 113000
        finally:
            os.environ.pop("CURSOR", None)

    def test_cursor_session_detection(self) -> None:
        """Test detecting Cursor from CURSOR_SESSION env var."""
        os.environ["CURSOR_SESSION"] = "abc123"
        try:
            agent = detect_agent()
            assert agent.name == "Cursor"
        finally:
            os.environ.pop("CURSOR_SESSION", None)

    def test_cursor_profile(self) -> None:
        """Test Cursor agent profile specs."""
        agent = AGENT_PROFILES["cursor"]
        assert agent.name == "Cursor"
        assert agent.context_window == 128000
        assert agent.estimated_overhead == 15000
        assert agent.effective_capacity() == 113000

    def test_cursor_name_lookup(self) -> None:
        """Test getting Cursor by name."""
        agent = get_agent_by_name("cursor")
        assert agent is not None
        assert agent.name == "Cursor"

    def test_cursor_name_lookup_case_insensitive(self) -> None:
        """Test case-insensitive Cursor lookup."""
        agent1 = get_agent_by_name("CURSOR")
        agent2 = get_agent_by_name("Cursor")
        agent3 = get_agent_by_name("cursor")
        assert agent1 == agent2 == agent3
        assert agent1.name == "Cursor"


class TestCursorWorkflow:
    """Test realistic Cursor usage workflows."""

    def test_cursor_code_review_workflow(self, tmp_path: Path) -> None:
        """Test code review workflow in Cursor."""
        os.environ["CURSOR"] = "1"
        try:
            db_path = str(tmp_path / "context.db")
            config = ContextConfig(100000, 0.85, 2, db_path)
            agent = detect_agent()

            # Verify Cursor is detected
            assert agent.name == "Cursor"

            # Create context-graph
            graph = ContextGraph(config, agent)

            # Simulate Cursor asking for code review
            # User 1: Review auth handler
            graph.record_access("src/api/auth.py:login", "Function", 400, "code_review", "login endpoint review")
            graph.record_access("src/auth/jwt.py:verify_token", "Function", 300, "code_review", "token verification")

            assert graph.current_token_usage() == 700
            assert len(graph.active_context()) == 2

            # User 2: Check impact of changes
            graph.record_access("src/api/auth.py:login", "Function", 400, "impact_analysis", "find callers")
            graph.record_access("tests/test_auth.py:test_login", "Function", 250, "impact_analysis", "find tests")

            assert graph.current_token_usage() == 950
            assert len(graph.active_context()) == 3

            # Summary should show Cursor
            summary = get_context_summary(graph)
            assert summary["agent_type"] == "Cursor"
            assert summary["nodes_count"] == 3

        finally:
            os.environ.pop("CURSOR", None)

    def test_cursor_context_persistence(self, tmp_path: Path) -> None:
        """Test Cursor context persistence across sessions."""
        os.environ["CURSOR"] = "1"
        try:
            db_path = str(tmp_path / "context.db")
            config = ContextConfig(100000, 0.85, 2, db_path)
            agent = detect_agent()

            # Session 1: Create and save context
            graph1 = ContextGraph(config, agent)
            graph1.record_access("src/components/Button.tsx", "Class", 250, "review")
            graph1.record_access("src/hooks/useForm.ts", "Function", 300, "review")
            save_context(graph1, db_path)

            # Session 2: Load and extend context
            graph2 = load_context(db_path, config, agent)
            assert len(graph2.active_context()) == 2
            assert graph2.current_token_usage() == 550

            # Add more nodes in session 2
            graph2.record_access("src/utils/validation.ts", "Function", 200, "search")
            save_context(graph2, db_path)

            # Session 3: Load and verify
            graph3 = load_context(db_path, config, agent)
            assert len(graph3.active_context()) == 3
            assert graph3.current_token_usage() == 750

        finally:
            os.environ.pop("CURSOR", None)

    def test_cursor_capacity_bounds(self) -> None:
        """Test that Cursor cache respects 113k token limit."""
        os.environ["CURSOR"] = "1"
        try:
            config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
            agent = detect_agent()
            graph = ContextGraph(config, agent)

            # Cursor effective capacity is 113k
            assert agent.effective_capacity() == 113000

            # Try to add nodes exceeding capacity
            for i in range(20):
                graph.record_access(f"node_{i}", "Function", 10000, "tool")

            # Should never exceed Cursor's effective capacity
            usage = graph.current_token_usage()
            assert usage <= agent.effective_capacity()
            assert usage <= 113000

        finally:
            os.environ.pop("CURSOR", None)

    def test_cursor_eviction_maintains_capacity(self) -> None:
        """Test LRU-K eviction keeps Cursor cache within bounds."""
        os.environ["CURSOR"] = "1"
        try:
            config = ContextConfig(max_tokens=1000, eviction_threshold=0.85, lru_k=2, persistence_path="/tmp/test.db")
            agent = detect_agent()
            graph = ContextGraph(config, agent)

            # Add nodes until eviction triggers
            for i in range(3):
                graph.record_access(f"old_node_{i}", "Function", 300, "tool")
                time.sleep(0.01)

            initial_usage = graph.current_token_usage()

            # Add more to trigger eviction
            graph.record_access("new_node", "Function", 300, "tool")

            # Should have evicted to maintain capacity
            usage_after_eviction = graph.current_token_usage()
            capacity_ratio = usage_after_eviction / agent.effective_capacity()

            # After eviction, should be below 70% hysteresis threshold
            assert capacity_ratio < 0.70

        finally:
            os.environ.pop("CURSOR", None)


class TestCursorMCPTools:
    """Test MCP tools work correctly with Cursor."""

    def test_cursor_context_summary_tool(self) -> None:
        """Test get_context_summary with Cursor agent."""
        os.environ["CURSOR"] = "1"
        try:
            config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
            agent = detect_agent()
            graph = ContextGraph(config, agent)

            graph.record_access("file1.py", "File", 100, "tool1")
            graph.record_access("file2.py", "File", 200, "tool2")

            summary = get_context_summary(graph)

            assert summary["enabled"] is True
            assert summary["agent_type"] == "Cursor"
            assert summary["nodes_count"] == 2
            assert summary["total_tokens"] == 300
            assert summary["agent_context_window"] == 128000

        finally:
            os.environ.pop("CURSOR", None)

    def test_cursor_active_context_tool(self) -> None:
        """Test get_active_context with Cursor agent."""
        os.environ["CURSOR"] = "1"
        try:
            config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
            agent = detect_agent()
            graph = ContextGraph(config, agent)

            graph.record_access("Button.tsx", "Class", 250, "review")
            graph.record_access("useForm.ts", "Function", 300, "review")
            time.sleep(0.01)
            graph.record_access("Button.tsx", "Class", 250, "search")

            active = get_active_context(graph)

            assert active["enabled"] is True
            assert active["count"] == 2
            assert len(active["nodes"]) == 2
            # Most recent should be first
            assert active["nodes"][0]["qualified_name"] == "Button.tsx"
            assert active["nodes"][0]["access_count"] == 2

        finally:
            os.environ.pop("CURSOR", None)

    def test_cursor_clear_context_tool(self) -> None:
        """Test clear_context with Cursor agent."""
        os.environ["CURSOR"] = "1"
        try:
            config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
            agent = detect_agent()
            graph = ContextGraph(config, agent)

            graph.record_access("file1", "File", 100, "tool")
            graph.record_access("file2", "File", 200, "tool")

            result = clear_context(graph)

            assert result["enabled"] is True
            assert result["cleared"] is True
            assert result["nodes_removed"] == 2
            assert result["tokens_freed"] == 300

        finally:
            os.environ.pop("CURSOR", None)


class TestCursorConfigVariations:
    """Test various configuration scenarios with Cursor."""

    def test_cursor_with_custom_max_tokens(self) -> None:
        """Test Cursor with custom max_tokens override."""
        os.environ["CURSOR"] = "1"
        os.environ["CRG_CONTEXT_MAX_TOKENS"] = "80000"
        try:
            config = load_context_config(".")
            agent = detect_agent()

            # Agent is Cursor but config respects env override
            assert agent.name == "Cursor"
            assert config.max_tokens == 80000

        finally:
            os.environ.pop("CURSOR", None)
            os.environ.pop("CRG_CONTEXT_MAX_TOKENS", None)

    def test_cursor_with_custom_eviction_threshold(self) -> None:
        """Test Cursor with custom eviction threshold."""
        os.environ["CURSOR"] = "1"
        os.environ["CRG_EVICTION_THRESHOLD"] = "0.75"
        try:
            config = load_context_config(".")
            agent = detect_agent()

            assert agent.name == "Cursor"
            assert config.eviction_threshold == 0.75

        finally:
            os.environ.pop("CURSOR", None)
            os.environ.pop("CRG_EVICTION_THRESHOLD", None)

    def test_cursor_explicit_override(self) -> None:
        """Test explicit Cursor type override via env var."""
        # Don't set CURSOR, but set CRG_AGENT_TYPE
        os.environ["CRG_AGENT_TYPE"] = "cursor"
        try:
            agent = detect_agent()
            assert agent.name == "Cursor"
            assert agent.context_window == 128000

        finally:
            os.environ.pop("CRG_AGENT_TYPE", None)
