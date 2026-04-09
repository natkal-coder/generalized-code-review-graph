"""Integration tests for context-graph MCP tools and full workflow."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from code_review_graph.agent_detect import AGENT_PROFILES
from code_review_graph.context_config import ContextConfig
from code_review_graph.context_graph import ContextGraph
from code_review_graph.context_persistence import clear_context, load_context, save_context
from code_review_graph.tools.context_tools import (
    clear_context,
    get_active_context,
    get_context_summary,
)


class TestContextSummaryTool:
    """Test get_context_summary MCP tool."""

    def test_summary_empty_graph(self) -> None:
        """Test summary of empty graph."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        result = get_context_summary(graph)

        assert result["enabled"] is True
        assert result["nodes_count"] == 0
        assert result["total_tokens"] == 0

    def test_summary_with_nodes(self) -> None:
        """Test summary includes active nodes."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        graph.record_access("src/utils.py:func1", "Function", 300, "review_tool")
        graph.record_access("src/models.py:User", "Class", 500, "impact_tool")

        result = get_context_summary(graph)

        assert result["nodes_count"] == 2
        assert result["total_tokens"] == 800
        assert len(result["active_nodes"]) == 2

    def test_summary_includes_agent_info(self) -> None:
        """Test summary includes agent type and capacity."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["gemini-cli"]
        graph = ContextGraph(config, agent)

        result = get_context_summary(graph)

        assert result["agent_type"] == "Gemini CLI"
        assert result["agent_context_window"] == 1000000


class TestActiveContextTool:
    """Test get_active_context MCP tool."""

    def test_active_context_empty(self) -> None:
        """Test active context for empty graph."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        result = get_active_context(graph)
        assert result["count"] == 0
        assert len(result["nodes"]) == 0

    def test_active_context_with_nodes(self) -> None:
        """Test active context returns nodes sorted by relevance."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        graph.record_access("node1", "Function", 100, "tool1")
        time.sleep(0.01)
        graph.record_access("node2", "Function", 200, "tool2")

        result = get_active_context(graph)

        assert result["count"] == 2
        assert result["nodes"][0]["qualified_name"] == "node2"  # Most recent first
        assert result["nodes"][0]["access_count"] == 1
        assert "time_since_access_seconds" in result["nodes"][0]
        assert "token_estimate" in result["nodes"][0]

    def test_active_context_all_nodes(self) -> None:
        """Test that active context returns all nodes."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        for i in range(10):
            graph.record_access(f"node{i}", "Function", 100, "tool1")
            time.sleep(0.005)

        result = get_active_context(graph)
        # All 10 nodes should be returned
        assert result["count"] == 10
        assert len(result["nodes"]) == 10


class TestClearContextTool:
    """Test clear_context MCP tool."""

    def test_clear_removes_all_nodes(self) -> None:
        """Test that clear removes all context."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        graph.record_access("node1", "Function", 100, "tool1")
        graph.record_access("node2", "Function", 200, "tool2")

        result = clear_context(graph)

        assert result["nodes_removed"] == 2
        assert result["tokens_freed"] == 300
        assert graph.current_token_usage() == 0

    def test_clear_empty_graph(self) -> None:
        """Test clearing empty graph."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        result = clear_context(graph)

        assert result["nodes_removed"] == 0
        assert result["tokens_freed"] == 0


class TestFullWorkflow:
    """Integration tests for complete context-graph workflow."""

    def test_session_lifecycle(self, tmp_path: Path) -> None:
        """Test complete session: init -> access -> save -> load."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["cursor"]

        # Phase 1: Initialize and access
        graph1 = ContextGraph(config, agent)
        graph1.record_access("src/auth/login.py:authenticate", "Function", 400, "review_tool", "user login flow")
        graph1.record_access("src/db/user.py:User", "Class", 600, "impact_tool", "user model")

        summary1 = get_context_summary(graph1)
        assert summary1["nodes_count"] == 2
        assert summary1["agent_type"] == "Cursor"

        # Phase 2: Persist
        save_context(graph1, db_path)

        # Phase 3: Load in new session
        graph2 = load_context(db_path, config, agent)
        summary2 = get_context_summary(graph2)

        # Verify state preserved
        assert summary2["nodes_count"] == 2
        assert summary2["total_tokens"] == 1000

        # Phase 4: Continue in new session
        graph2.record_access("src/api/handlers.py:create_user", "Function", 500, "review_tool", "handler")
        assert len(graph2.active_context()) == 3

    def test_eviction_under_load(self, tmp_path: Path) -> None:
        """Test eviction triggers and maintains capacity during heavy load."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(max_tokens=10000, eviction_threshold=0.85, lru_k=2, persistence_path=db_path)
        agent = AGENT_PROFILES["claude-code"]  # 180k capacity

        graph = ContextGraph(config, agent)

        # Simulate continuous access over multiple "requests"
        for request in range(5):
            # Each request accesses 5 different files
            for i in range(5):
                node_id = f"node_{request}_{i}"
                graph.record_access(node_id, "Function", 5000, "tool1")

            # Check that capacity is maintained
            usage_ratio = graph.capacity_ratio()
            # Should never exceed effective capacity
            assert usage_ratio <= 1.0

            # Should have some eviction if we've added enough
            if request > 2:
                # Should have evicted some old nodes
                assert len(graph.active_context()) < 25

    def test_multi_tool_access_pattern(self) -> None:
        """Test realistic multi-tool access pattern."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        # Simulate multiple tools accessing same nodes
        tools = ["review_tool", "impact_tool", "search_tool", "change_tool"]
        nodes = ["src/utils.py:func", "src/models.py:User", "src/handlers.py:create"]

        # Tool 1: Review
        for node in nodes:
            graph.record_access(node, "Function", 200, tools[0], "code review")

        summary = get_context_summary(graph)
        assert summary["nodes_count"] == 3

        # Tool 2: Impact analysis (accesses same + new nodes)
        for node in nodes + ["src/db/query.py:execute"]:
            graph.record_access(node, "Function", 200, tools[1], "impact analysis")

        summary = get_context_summary(graph)
        assert summary["nodes_count"] == 4

        # Tool 3: Search (accesses subset)
        for node in nodes[:2]:
            graph.record_access(node, "Function", 200, tools[2], "search")

        # Verify all tools' accesses are tracked
        result = get_active_context(graph)
        for node in result["nodes"]:
            assert node["access_count"] >= 1

    def test_frequency_scoring_drives_eviction(self) -> None:
        """Test that frequently-accessed nodes survive eviction."""
        config = ContextConfig(max_tokens=1000, eviction_threshold=0.85, lru_k=2, persistence_path="/tmp/test.db")
        agent = AGENT_PROFILES["cursor"]
        graph = ContextGraph(config, agent)

        # Hot node (accessed frequently)
        for i in range(5):
            graph.record_access("hot_node", "Function", 100, f"tool_{i}")
            time.sleep(0.001)

        # Cold nodes (accessed once)
        for i in range(5):
            graph.record_access(f"cold_node_{i}", "Function", 100, "tool_once")
            time.sleep(0.001)

        # Trigger eviction by adding more
        graph.record_access("new_node", "Function", 300, "tool_new")

        # Hot node should survive, cold nodes should be evicted
        active_names = [node.qualified_name for node in graph.active_context()]

        assert "hot_node" in active_names
        # Most cold nodes should be evicted
        cold_count = sum(1 for name in active_names if "cold_node" in name)
        assert cold_count < 5

    def test_clear_and_restart(self, tmp_path: Path) -> None:
        """Test clearing context and starting fresh."""
        db_path = str(tmp_path / "context.db")
        config = ContextConfig(100000, 0.85, 2, db_path)
        agent = AGENT_PROFILES["claude-code"]

        # Session 1
        graph1 = ContextGraph(config, agent)
        graph1.record_access("session1_node", "Function", 100, "tool1")
        save_context(graph1, db_path)

        # Clear
        clear_context(db_path)
        assert not Path(db_path).exists()

        # Session 2 (fresh)
        graph2 = load_context(db_path, config, agent)
        assert graph2.current_token_usage() == 0

        graph2.record_access("session2_node", "Function", 200, "tool2")
        assert len(graph2.active_context()) == 1
        assert graph2.get_context("session1_node") is None
        assert graph2.get_context("session2_node") is not None
