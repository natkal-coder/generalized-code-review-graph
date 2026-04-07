"""Tests for code smell detection."""

import pytest

from code_review_graph.smells import (
    analyze_node,
    detect_god_object,
    detect_long_param_list,
    detect_deep_nesting,
)
from code_review_graph.parser import NodeInfo


class TestSmellDetection:
    """Test individual smell detectors."""

    def test_long_param_list_detected(self):
        """Function with >5 params is flagged."""
        node = NodeInfo(
            kind="Function",
            name="func",
            file_path="test.py",
            line_start=1,
            line_end=10,
            language="python",
            params="a, b, c, d, e, f, g",  # 7 params
            extra={"param_count": 7},
        )
        smell = detect_long_param_list(node)
        assert smell is not None
        assert smell.tag == "long_param_list"
        assert smell.severity == "medium"
        assert smell.confidence == 1.0

    def test_long_param_list_not_detected_when_few_params(self):
        """Function with <=5 params is not flagged."""
        node = NodeInfo(
            kind="Function",
            name="func",
            file_path="test.py",
            line_start=1,
            line_end=10,
            language="python",
            params="a, b, c",
            extra={"param_count": 3},
        )
        smell = detect_long_param_list(node)
        assert smell is None

    def test_deep_nesting_detected(self):
        """Function with >4 nesting depth is flagged."""
        node = NodeInfo(
            kind="Function",
            name="func",
            file_path="test.py",
            line_start=1,
            line_end=50,
            language="python",
            extra={"nesting_depth": 5},
        )
        smell = detect_deep_nesting(node)
        assert smell is not None
        assert smell.tag == "deep_nesting"
        assert smell.severity == "medium"

    def test_deep_nesting_high_severity_for_very_deep(self):
        """Function with >6 nesting depth is high severity."""
        node = NodeInfo(
            kind="Function",
            name="func",
            file_path="test.py",
            line_start=1,
            line_end=50,
            language="python",
            extra={"nesting_depth": 7},
        )
        smell = detect_deep_nesting(node)
        assert smell is not None
        assert smell.severity == "high"

    def test_deep_nesting_not_detected_for_shallow(self):
        """Function with <=4 nesting depth is not flagged."""
        node = NodeInfo(
            kind="Function",
            name="func",
            file_path="test.py",
            line_start=1,
            line_end=20,
            language="python",
            extra={"nesting_depth": 3},
        )
        smell = detect_deep_nesting(node)
        assert smell is None

    def test_analyze_node_combines_multiple_smells(self):
        """analyze_node detects multiple smells from single node."""
        node = NodeInfo(
            kind="Function",
            name="func",
            file_path="test.py",
            line_start=1,
            line_end=50,
            language="python",
            params="a, b, c, d, e, f",
            extra={"param_count": 6, "nesting_depth": 5},
        )
        smells_list = analyze_node(node, graph=None)  # graph=None OK for node-only detectors
        assert len(smells_list) == 2
        tags = {s["tag"] for s in smells_list}
        assert "long_param_list" in tags
        assert "deep_nesting" in tags
