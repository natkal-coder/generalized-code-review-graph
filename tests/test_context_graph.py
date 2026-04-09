"""Tests for context_graph module: ContextGraph core engine with eviction."""

from __future__ import annotations

import time

import pytest

from code_review_graph.agent_detect import AgentInfo, AGENT_PROFILES
from code_review_graph.context_config import ContextConfig
from code_review_graph.context_graph import ContextGraph
from code_review_graph.context_node import ContextNode


class TestContextGraphBasics:
    """Test basic ContextGraph operations."""

    def test_create_context_graph(self) -> None:
        """Test creating a ContextGraph."""
        config = ContextConfig(
            max_tokens=100000,
            eviction_threshold=0.85,
            lru_k=2,
            persistence_path="/tmp/test.db",
        )
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        assert graph.current_token_usage() == 0
        assert graph.capacity_ratio() == 0.0
        assert len(graph.active_context()) == 0

    def test_record_access_single_node(self) -> None:
        """Test recording a single node access."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        graph.record_access("src/utils.py:sanitize", "Function", 500, "test_tool", "test")

        assert graph.current_token_usage() == 500
        assert len(graph.active_context()) == 1
        assert graph.capacity_ratio() == 500 / (200000 - 20000)  # 180k capacity

    def test_record_multiple_accesses_same_node(self) -> None:
        """Test multiple accesses to the same node."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        graph.record_access("src/utils.py:func", "Function", 300, "tool1", "ctx1")
        graph.record_access("src/utils.py:func", "Function", 300, "tool2", "ctx2")

        # Should update existing node, not add duplicate
        assert len(graph.active_context()) == 1
        assert graph.current_token_usage() == 300  # Same node, same tokens
        node = graph.get_context("src/utils.py:func")
        assert node is not None
        assert node.access_count == 2

    def test_get_context_nonexistent(self) -> None:
        """Test getting non-existent context."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        result = graph.get_context("nonexistent")
        assert result is None

    def test_capacity_ratio(self) -> None:
        """Test capacity ratio calculation."""
        config = ContextConfig(max_tokens=10000, eviction_threshold=0.85, lru_k=2, persistence_path="/tmp/test.db")
        agent = AgentInfo("Test", context_window=10000, estimated_overhead=1000)  # 9k capacity
        graph = ContextGraph(config, agent)

        graph.record_access("node1", "Function", 4500, "tool1")
        assert 0.49 < graph.capacity_ratio() < 0.51  # ~4500/9000 = 0.5


class TestContextGraphEviction:
    """Test LRU-K eviction behavior."""

    def test_eviction_triggers_above_threshold(self) -> None:
        """Test that eviction triggers when capacity > threshold."""
        config = ContextConfig(
            max_tokens=1000,  # Small capacity for testing
            eviction_threshold=0.85,
            lru_k=2,
            persistence_path="/tmp/test.db",
        )
        agent = AgentInfo("Test", context_window=1000, estimated_overhead=100)  # 900 capacity
        graph = ContextGraph(config, agent)

        # Fill cache above threshold
        graph.record_access("node1", "Function", 400, "tool1")
        graph.record_access("node2", "Function", 400, "tool2")
        graph.record_access("node3", "Function", 200, "tool3")

        # At 1000 tokens with 900 capacity = 1.11 ratio, triggers eviction
        # Should evict down to below 70% (630 tokens)
        assert graph.current_token_usage() < 900 * 0.75  # Below hysteresis band

    def test_hysteresis_prevents_thrashing(self) -> None:
        """Test hysteresis: evict at 85%, stop at 70%."""
        config = ContextConfig(
            max_tokens=1000,
            eviction_threshold=0.85,
            lru_k=2,
            persistence_path="/tmp/test.db",
        )
        agent = AgentInfo("Test", context_window=1000, estimated_overhead=100)  # 900 capacity
        graph = ContextGraph(config, agent)

        # Add nodes such that total is ~820 tokens (91% of 900)
        graph.record_access("node1", "Function", 300, "tool1")
        time.sleep(0.01)
        graph.record_access("node2", "Function", 300, "tool2")
        time.sleep(0.01)
        graph.record_access("node3", "Function", 220, "tool3")

        # Should trigger eviction because 820/900 = 0.91 > 0.85
        usage_after_eviction = graph.current_token_usage()

        # After eviction, should be below (0.85 - 0.15) = 0.70 threshold
        ratio = usage_after_eviction / 900
        assert ratio < 0.70

    def test_eviction_removes_stale_nodes(self) -> None:
        """Test that eviction removes least recently used nodes."""
        config = ContextConfig(
            max_tokens=1000,
            eviction_threshold=0.85,
            lru_k=2,
            persistence_path="/tmp/test.db",
        )
        agent = AgentInfo("Test", context_window=1000, estimated_overhead=100)
        graph = ContextGraph(config, agent)

        # Add nodes with known timestamps
        graph.record_access("old_node", "Function", 300, "tool1")
        time.sleep(0.05)
        graph.record_access("new_node1", "Function", 300, "tool2")
        graph.record_access("new_node2", "Function", 220, "tool3")

        # old_node should be evicted first due to age
        # Verify active nodes don't include old_node
        active = graph.active_context()
        active_names = [node.qualified_name for node in active]

        # After eviction, old_node should be gone
        assert "old_node" not in active_names

    def test_clear_context(self) -> None:
        """Test clearing all context."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        graph.record_access("node1", "Function", 100, "tool1")
        graph.record_access("node2", "Function", 200, "tool2")
        assert graph.current_token_usage() == 300

        graph.clear()
        assert graph.current_token_usage() == 0
        assert len(graph.active_context()) == 0


class TestContextGraphSummary:
    """Test summary and status reporting."""

    def test_summary_empty_graph(self) -> None:
        """Test summary of empty graph."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        summary = graph.summary()
        assert summary["nodes_count"] == 0
        assert summary["total_tokens"] == 0
        assert summary["capacity_ratio"] == 0.0
        assert summary["agent_type"] == "Claude Code"

    def test_summary_with_nodes(self) -> None:
        """Test summary with active nodes."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        graph.record_access("node1", "Function", 100, "tool1")
        graph.record_access("node2", "Function", 200, "tool2")

        summary = graph.summary()
        assert summary["nodes_count"] == 2
        assert summary["total_tokens"] == 300
        assert summary["agent_type"] == "Claude Code"
        assert "active_nodes" in summary
        assert len(summary["active_nodes"]) == 2

    def test_active_context_sorted_by_relevance(self) -> None:
        """Test that active_context() returns nodes sorted by relevance."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        # Add nodes with different access patterns
        graph.record_access("fresh_node", "Function", 100, "tool1")
        time.sleep(0.02)
        graph.record_access("old_node", "Function", 100, "tool2")

        # fresh_node should be more relevant due to recency
        active = graph.active_context()
        assert len(active) == 2
        assert active[0].qualified_name == "fresh_node"
        assert active[1].qualified_name == "old_node"


class TestContextGraphThreadSafety:
    """Test thread safety of context graph operations."""

    def test_concurrent_record_access(self) -> None:
        """Test concurrent access recording (basic thread safety)."""
        import threading

        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        def record_many(node_id: int) -> None:
            for i in range(10):
                graph.record_access(f"node_{node_id}", "Function", 10, f"tool_{i}")

        threads = [threading.Thread(target=record_many, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have 3 unique nodes with correct access counts
        assert len(graph.active_context()) == 3
        for node in graph.active_context():
            assert node.access_count == 10


class TestAgentAwareness:
    """Test agent-aware capacity management."""

    def test_claude_code_capacity(self) -> None:
        """Test Claude Code agent capacity."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["claude-code"]
        graph = ContextGraph(config, agent)

        # Claude Code: 200k window, 20k overhead = 180k capacity
        assert agent.effective_capacity() == 180000

    def test_gemini_cli_capacity(self) -> None:
        """Test Gemini CLI agent capacity."""
        config = ContextConfig(100000, 0.85, 2, "/tmp/test.db")
        agent = AGENT_PROFILES["gemini-cli"]
        graph = ContextGraph(config, agent)

        # Gemini CLI: 1M window, 50k overhead = 950k capacity
        assert agent.effective_capacity() == 950000

    def test_capacity_respects_agent_limit(self) -> None:
        """Test that capacity is bounded by agent context window."""
        config = ContextConfig(max_tokens=500000, eviction_threshold=0.85, lru_k=2, persistence_path="/tmp/test.db")
        # Use cursor with smaller capacity
        agent = AGENT_PROFILES["cursor"]  # 128k window, 15k overhead = 113k capacity

        graph = ContextGraph(config, agent)

        # Try to add more nodes than cursor can hold
        graph.record_access("node1", "Function", 100000, "tool1")

        # Effective capacity should be limited by agent, not config
        assert graph.current_token_usage() <= agent.effective_capacity()
