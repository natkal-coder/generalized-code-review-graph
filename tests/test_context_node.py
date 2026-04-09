"""Tests for context_node module: ContextNode, AccessLog, and scoring functions."""

from __future__ import annotations

import time

import pytest

from code_review_graph.context_node import (
    AccessLog,
    ContextNode,
    compute_relevance,
    estimate_tokens,
)
from code_review_graph.parser import NodeInfo


class TestAccessLog:
    """Test AccessLog dataclass."""

    def test_create_access_log(self) -> None:
        """Test creating an AccessLog entry."""
        now = time.time()
        log = AccessLog(
            timestamp=now,
            tool_name="test_tool",
            query_context="test context",
        )
        assert log.timestamp == now
        assert log.tool_name == "test_tool"
        assert log.query_context == "test context"

    def test_access_log_frozen(self) -> None:
        """Test that AccessLog is frozen (immutable)."""
        log = AccessLog(time.time(), "tool", "context")
        with pytest.raises(AttributeError):
            log.timestamp = 0.0  # type: ignore


class TestContextNode:
    """Test ContextNode dataclass and access tracking."""

    def test_create_context_node(self) -> None:
        """Test creating a ContextNode."""
        node = ContextNode(
            qualified_name="src/utils.py:sanitize",
            kind="Function",
            token_estimate=150,
        )
        assert node.qualified_name == "src/utils.py:sanitize"
        assert node.kind == "Function"
        assert node.token_estimate == 150
        assert node.access_count == 0
        assert node.frequency_score == 0.0
        assert len(node.access_log) == 0

    def test_record_single_access(self) -> None:
        """Test recording a single access."""
        node = ContextNode("test", "Function", 100)
        node.record_access("tool1", "context1")

        assert node.access_count == 1
        assert len(node.access_log) == 1
        assert node.access_log[0].tool_name == "tool1"
        assert node.access_log[0].query_context == "context1"

    def test_record_multiple_accesses_lru_k(self) -> None:
        """Test LRU-K: keep last 2 accesses."""
        node = ContextNode("test", "Function", 100)

        # Record 4 accesses
        node.record_access("tool1", "ctx1")
        time.sleep(0.01)
        node.record_access("tool2", "ctx2")
        time.sleep(0.01)
        node.record_access("tool3", "ctx3")
        time.sleep(0.01)
        node.record_access("tool4", "ctx4")

        # Should keep only last 2
        assert node.access_count == 4  # Total count
        assert len(node.access_log) == 2  # But only 2 in log
        assert node.access_log[-2].tool_name == "tool3"
        assert node.access_log[-1].tool_name == "tool4"

    def test_frequency_score_computation(self) -> None:
        """Test frequency score increases with recent accesses."""
        node = ContextNode("test", "Function", 100)
        initial_freq = node.frequency_score

        # First access
        node.record_access("tool1")
        freq_after_1 = node.frequency_score
        assert freq_after_1 > initial_freq

        # Second quick access (should increase frequency)
        node.record_access("tool2")
        freq_after_2 = node.frequency_score
        assert freq_after_2 > freq_after_1

        # Wait and access again (longer gap, should increase less)
        time.sleep(0.05)
        node.record_access("tool3")
        freq_after_wait = node.frequency_score

        # With the formula, frequency should still increase but less
        assert freq_after_wait > 0.0

    def test_time_since_access(self) -> None:
        """Test time_since_access() computation."""
        node = ContextNode("test", "Function", 100)
        node.record_access("tool1")
        age_immediately = node.time_since_access()
        assert 0.0 <= age_immediately < 0.1

        time.sleep(0.05)
        age_later = node.time_since_access()
        assert age_later > age_immediately
        assert 0.04 < age_later < 0.1


class TestEstimateTokens:
    """Test estimate_tokens() heuristic."""

    def test_estimate_with_line_range(self) -> None:
        """Test token estimation with line range."""
        node_info = NodeInfo(
            kind="Function",
            name="test_func",
            file_path="test.py",
            line_start=10,
            line_end=25,  # 15 lines
        )
        tokens = estimate_tokens(node_info)
        assert tokens == 15 * 15  # 225 tokens (15 lines × 15 tokens/line)

    def test_estimate_without_line_info(self) -> None:
        """Test token estimation for small single-line nodes."""
        # NodeInfo requires line_start and line_end; test with zero-length range
        node_info = NodeInfo(
            kind="File",
            name="test.py",
            file_path="test.py",
            line_start=1,
            line_end=1,
        )
        tokens = estimate_tokens(node_info)
        # max(1, 1-1) * 15 = max(1, 0) * 15 = 15
        assert tokens == 15

    def test_estimate_single_line(self) -> None:
        """Test token estimation for single line."""
        node_info = NodeInfo(
            kind="Function",
            name="oneliner",
            file_path="test.py",
            line_start=100,
            line_end=100,  # Single line
        )
        tokens = estimate_tokens(node_info)
        # max(1, 100-100) * 15 = max(1, 0) * 15 = 15 tokens
        assert tokens == 15


class TestComputeRelevance:
    """Test compute_relevance() scoring function."""

    def test_fresh_node_high_relevance(self) -> None:
        """Test that fresh, frequently-accessed nodes score high."""
        node = ContextNode("test", "Function", 100)
        now = time.time()

        # Fresh node, recently accessed
        node.last_accessed = now
        node.frequency_score = 0.8
        node.access_count = 10

        relevance = compute_relevance(node, now)
        assert 0.0 < relevance <= 1.0
        # High recency (0.5), high frequency (0.3), high access (0.2)
        assert relevance > 0.7

    def test_stale_node_low_relevance(self) -> None:
        """Test that stale nodes score low."""
        node = ContextNode("test", "Function", 100)
        now = time.time()

        # Old node, not recently accessed
        node.last_accessed = now - 300  # 5 minutes ago
        node.frequency_score = 0.1
        node.access_count = 1

        relevance = compute_relevance(node, now)
        assert 0.0 < relevance < 0.3

    def test_relevance_monotonic_with_time(self) -> None:
        """Test that relevance decreases monotonically as age increases."""
        node = ContextNode("test", "Function", 100)
        base_time = time.time()

        node.frequency_score = 0.5
        node.access_count = 5

        # Compute at different ages
        rel_fresh = compute_relevance(node, base_time + 1)
        rel_10s = compute_relevance(node, base_time + 10)
        rel_60s = compute_relevance(node, base_time + 60)
        rel_300s = compute_relevance(node, base_time + 300)

        # Should monotonically decrease
        assert rel_fresh > rel_10s
        assert rel_10s > rel_60s
        assert rel_60s > rel_300s


class TestContextNodeIntegration:
    """Integration tests for ContextNode behavior."""

    def test_access_pattern_learning(self) -> None:
        """Test that access patterns are learned correctly."""
        node = ContextNode("utils.py:helper", "Function", 200)

        # Simulate rapid accesses (frequent use)
        for i in range(5):
            node.record_access(f"tool_{i % 2}", f"ctx_{i}")
            time.sleep(0.005)

        # Node should have high frequency score
        assert node.frequency_score > 0.5
        assert node.access_count == 5

    def test_node_time_decay(self) -> None:
        """Test that time_since_access increases over time."""
        node = ContextNode("test", "Function", 100)
        node.record_access("tool1")

        age_t0 = node.time_since_access()
        time.sleep(0.02)
        age_t1 = node.time_since_access()

        assert age_t1 > age_t0
        assert (age_t1 - age_t0) >= 0.02
