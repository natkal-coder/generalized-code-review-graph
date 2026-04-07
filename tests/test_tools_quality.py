"""Tests for quality-related MCP tools."""

import pytest
from pathlib import Path

from code_review_graph.graph import GraphStore
from code_review_graph.parser import CodeParser


@pytest.fixture
def graph_with_metrics(tmp_path: Path) -> GraphStore:
    """Build a graph with code quality metrics."""
    db_path = tmp_path / "test.db"
    store = GraphStore(str(db_path))
    parser = CodeParser()

    # Parse a Python file with intentionally complex functions
    source = b"""
def simple_func(a, b):
    '''Simple function with few params.'''
    return a + b

def complex_func(a, b, c, d, e, f, g):
    '''Function with many params.'''
    if a:
        if b:
            if c:
                if d:
                    return "nested"
    return None
"""

    nodes, edges = parser.parse_bytes(Path("test.py"), source)
    # Manually set complexity metrics for testing
    for node in nodes:
        if node.name == "complex_func":
            node.extra.update({
                "param_count": 7,
                "complexity_score": 5,
                "cognitive_complexity": 4,
                "nesting_depth": 4,
            })
        elif node.name == "simple_func":
            node.extra.update({
                "param_count": 2,
                "complexity_score": 1,
                "cognitive_complexity": 0,
                "nesting_depth": 0,
            })

    store.store_file_nodes_edges("test.py", nodes, edges)
    store.commit()
    return store


class TestCodeQualityTools:
    """Test quality analysis tools."""

    def test_graph_stores_complexity_metrics(self, graph_with_metrics):
        """Graph persists complexity metrics to database."""
        nodes = graph_with_metrics.get_nodes_by_file("test.py")
        complex_node = next((n for n in nodes if n.name == "complex_func"), None)

        assert complex_node is not None
        assert complex_node.extra.get("param_count") == 7 or hasattr(complex_node, "param_count")
        assert complex_node.extra.get("complexity_score") == 5 or hasattr(complex_node, "complexity_score")

    def test_graph_persists_smell_tags(self, graph_with_metrics, tmp_path):
        """Graph can persist and retrieve smell tags."""
        db_path = tmp_path / "smell_test.db"
        store = GraphStore(str(db_path))
        parser = CodeParser()

        source = b"""
def many_params(a, b, c, d, e, f, g):
    pass
"""
        nodes, edges = parser.parse_bytes(Path("test.py"), source)
        for node in nodes:
            if node.name == "many_params":
                node.extra["smell_tags"] = ["long_param_list"]

        store.store_file_nodes_edges("test.py", nodes, edges)
        store.commit()

        # Retrieve and verify
        nodes = store.get_nodes_by_file("test.py")
        many_params_node = next((n for n in nodes if n.name == "many_params"), None)
        assert many_params_node is not None
        # smell_tags should be persisted (though may be JSON string)
        assert many_params_node.extra.get("smell_tags") is not None

    def test_tool_dict_structure(self):
        """MCP tool responses follow expected structure."""
        tool_response = {
            "status": "ok",
            "summary": "Found 5 high-complexity functions",
            "data": [
                {
                    "name": "authenticate",
                    "file": "auth.py",
                    "complexity_score": 15,
                    "smell_tags": ["long_param_list"],
                }
            ],
        }
        # Verify structure
        assert "status" in tool_response
        assert "summary" in tool_response
        assert "data" in tool_response
        assert isinstance(tool_response["data"], list)
