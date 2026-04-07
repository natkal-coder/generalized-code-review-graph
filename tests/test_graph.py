"""Tests for the graph storage and query engine."""

import tempfile
from pathlib import Path

from code_review_graph.graph import GraphStore
from code_review_graph.parser import EdgeInfo, NodeInfo


class TestGraphStore:
    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.store = GraphStore(self.tmp.name)

    def teardown_method(self):
        self.store.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def _make_file_node(self, path="/test/file.py"):
        return NodeInfo(
            kind="File", name=path, file_path=path,
            line_start=1, line_end=100, language="python",
        )

    def _make_func_node(self, name="my_func", path="/test/file.py", parent=None, is_test=False):
        return NodeInfo(
            kind="Test" if is_test else "Function",
            name=name, file_path=path,
            line_start=10, line_end=20, language="python",
            parent_name=parent, is_test=is_test,
        )

    def _make_class_node(self, name="MyClass", path="/test/file.py"):
        return NodeInfo(
            kind="Class", name=name, file_path=path,
            line_start=5, line_end=50, language="python",
        )

    def test_upsert_and_get_node(self):
        node = self._make_file_node()
        self.store.upsert_node(node)
        self.store.commit()

        result = self.store.get_node("/test/file.py")
        assert result is not None
        assert result.kind == "File"
        assert result.name == "/test/file.py"

    def test_upsert_function_node(self):
        func = self._make_func_node()
        self.store.upsert_node(func)
        self.store.commit()

        result = self.store.get_node("/test/file.py::my_func")
        assert result is not None
        assert result.kind == "Function"
        assert result.name == "my_func"

    def test_upsert_method_node(self):
        method = self._make_func_node(name="do_thing", parent="MyClass")
        self.store.upsert_node(method)
        self.store.commit()

        result = self.store.get_node("/test/file.py::MyClass.do_thing")
        assert result is not None
        assert result.parent_name == "MyClass"

    def test_upsert_edge(self):
        edge = EdgeInfo(
            kind="CALLS",
            source="/test/file.py::func_a",
            target="/test/file.py::func_b",
            file_path="/test/file.py",
            line=15,
        )
        self.store.upsert_edge(edge)
        self.store.commit()

        edges = self.store.get_edges_by_source("/test/file.py::func_a")
        assert len(edges) == 1
        assert edges[0].kind == "CALLS"
        assert edges[0].target_qualified == "/test/file.py::func_b"

    def test_remove_file_data(self):
        node = self._make_file_node()
        func = self._make_func_node()
        self.store.upsert_node(node)
        self.store.upsert_node(func)
        self.store.commit()

        self.store.remove_file_data("/test/file.py")
        self.store.commit()

        assert self.store.get_node("/test/file.py") is None
        assert self.store.get_node("/test/file.py::my_func") is None

    def test_store_file_nodes_edges(self):
        nodes = [self._make_file_node(), self._make_func_node()]
        edges = [
            EdgeInfo(
                kind="CONTAINS", source="/test/file.py",
                target="/test/file.py::my_func", file_path="/test/file.py",
            )
        ]
        self.store.store_file_nodes_edges("/test/file.py", nodes, edges)

        result = self.store.get_nodes_by_file("/test/file.py")
        assert len(result) == 2

    def test_search_nodes(self):
        self.store.upsert_node(self._make_func_node("authenticate"))
        self.store.upsert_node(self._make_func_node("authorize"))
        self.store.upsert_node(self._make_func_node("process"))
        self.store.commit()

        results = self.store.search_nodes("auth")
        names = {r.name for r in results}
        assert "authenticate" in names
        assert "authorize" in names
        assert "process" not in names

    def test_get_stats(self):
        self.store.upsert_node(self._make_file_node())
        self.store.upsert_node(self._make_func_node())
        self.store.upsert_node(self._make_class_node())
        self.store.upsert_edge(EdgeInfo(
            kind="CONTAINS", source="/test/file.py",
            target="/test/file.py::my_func", file_path="/test/file.py",
        ))
        self.store.commit()

        stats = self.store.get_stats()
        assert stats.total_nodes == 3
        assert stats.total_edges == 1
        assert stats.nodes_by_kind["File"] == 1
        assert stats.nodes_by_kind["Function"] == 1
        assert stats.nodes_by_kind["Class"] == 1
        assert "python" in stats.languages

    def test_impact_radius(self):
        # Create a chain: file_a -> func_a -> (calls) -> func_b in file_b
        self.store.upsert_node(self._make_file_node("/a.py"))
        self.store.upsert_node(self._make_func_node("func_a", "/a.py"))
        self.store.upsert_node(self._make_file_node("/b.py"))
        self.store.upsert_node(self._make_func_node("func_b", "/b.py"))
        self.store.upsert_edge(EdgeInfo(
            kind="CALLS", source="/a.py::func_a",
            target="/b.py::func_b", file_path="/a.py", line=10,
        ))
        self.store.commit()

        result = self.store.get_impact_radius(["/a.py"], max_depth=2)
        assert len(result["changed_nodes"]) > 0
        # func_b in /b.py should be impacted
        impacted_qns = {n.qualified_name for n in result["impacted_nodes"]}
        assert "/b.py::func_b" in impacted_qns or "/b.py" in impacted_qns

    def test_upsert_edge_preserves_multiple_call_sites(self):
        """Multiple CALLS edges to the same target from the same source on different lines."""
        edge1 = EdgeInfo(
            kind="CALLS", source="/test/file.py::caller",
            target="/test/file.py::helper", file_path="/test/file.py", line=10,
        )
        edge2 = EdgeInfo(
            kind="CALLS", source="/test/file.py::caller",
            target="/test/file.py::helper", file_path="/test/file.py", line=20,
        )
        self.store.upsert_edge(edge1)
        self.store.upsert_edge(edge2)
        self.store.commit()

        edges = self.store.get_edges_by_source("/test/file.py::caller")
        assert len(edges) == 2
        lines = {e.line for e in edges}
        assert lines == {10, 20}

    def test_metadata(self):
        self.store.set_metadata("test_key", "test_value")
        assert self.store.get_metadata("test_key") == "test_value"
        assert self.store.get_metadata("nonexistent") is None


# ---------------------------------------------------------------------------
# Sprint 1: Graph persistence of readability fields
# ---------------------------------------------------------------------------

class TestReadabilityFieldPersistence:
    """Tests that upsert_node persists readability fields to nodes and node_metrics."""

    def setup_method(self):
        import tempfile
        from pathlib import Path
        from code_review_graph.graph import GraphStore
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.store = GraphStore(self.tmp.name)
        self._tmp_path = Path(self.tmp.name)

    def teardown_method(self):
        self.store.close()
        self._tmp_path.unlink(missing_ok=True)

    def _make_node(self, name="func", extra=None):
        from code_review_graph.parser import NodeInfo
        return NodeInfo(
            kind="Function", name=name, file_path="/test/f.py",
            line_start=1, line_end=10, language="python",
            extra=extra or {},
        )

    def test_has_docstring_persisted(self):
        node = self._make_node(extra={"has_docstring": True, "docstring_summary": "Does X"})
        self.store.upsert_node(node)
        self.store.commit()
        row = self.store._conn.execute(
            "SELECT has_docstring, docstring_summary FROM nodes WHERE name=?", ("func",)
        ).fetchone()
        assert row["has_docstring"] == 1
        assert row["docstring_summary"] == "Does X"

    def test_intent_tags_stored_as_json(self):
        node = self._make_node(extra={"intent_tags": ["TODO", "FIXME"]})
        self.store.upsert_node(node)
        self.store.commit()
        row = self.store._conn.execute(
            "SELECT intent_tags FROM nodes WHERE name=?", ("func",)
        ).fetchone()
        import json
        tags = json.loads(row["intent_tags"])
        assert "TODO" in tags
        assert "FIXME" in tags

    def test_documentation_gap_persisted(self):
        node = self._make_node(extra={"documentation_gap": True})
        self.store.upsert_node(node)
        self.store.commit()
        row = self.store._conn.execute(
            "SELECT documentation_gap FROM nodes WHERE name=?", ("func",)
        ).fetchone()
        assert row["documentation_gap"] == 1

    def test_complexity_score_in_nodes_and_metrics(self):
        node = self._make_node(extra={"complexity_score": 4.0})
        node_id = self.store.upsert_node(node)
        self.store.commit()
        row = self.store._conn.execute(
            "SELECT complexity_score FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        assert row["complexity_score"] == 4.0
        metric_row = self.store._conn.execute(
            "SELECT value FROM node_metrics WHERE node_id=? AND metric=?",
            (node_id, "complexity_score"),
        ).fetchone()
        assert metric_row is not None
        assert metric_row["value"] == 4.0

    def test_cognitive_complexity_in_nodes_and_metrics(self):
        node = self._make_node(extra={"cognitive_complexity": 7.0})
        node_id = self.store.upsert_node(node)
        self.store.commit()
        row = self.store._conn.execute(
            "SELECT cognitive_complexity FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        assert row["cognitive_complexity"] == 7.0
        metric_row = self.store._conn.execute(
            "SELECT value FROM node_metrics WHERE node_id=? AND metric=?",
            (node_id, "cognitive_complexity"),
        ).fetchone()
        assert metric_row["value"] == 7.0

    def test_param_count_in_nodes_and_metrics(self):
        node = self._make_node(extra={"param_count": 6})
        node_id = self.store.upsert_node(node)
        self.store.commit()
        row = self.store._conn.execute(
            "SELECT param_count FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        assert row["param_count"] == 6
        metric_row = self.store._conn.execute(
            "SELECT value FROM node_metrics WHERE node_id=? AND metric=?",
            (node_id, "param_count"),
        ).fetchone()
        assert metric_row["value"] == 6.0

    def test_nesting_depth_in_nodes_and_metrics(self):
        node = self._make_node(extra={"nesting_depth": 3})
        node_id = self.store.upsert_node(node)
        self.store.commit()
        row = self.store._conn.execute(
            "SELECT nesting_depth FROM nodes WHERE id=?", (node_id,)
        ).fetchone()
        assert row["nesting_depth"] == 3
        metric_row = self.store._conn.execute(
            "SELECT value FROM node_metrics WHERE node_id=? AND metric=?",
            (node_id, "nesting_depth"),
        ).fetchone()
        assert metric_row["value"] == 3.0

    def test_upsert_updates_metrics_on_conflict(self):
        """Re-upserting a node with changed complexity_score updates node_metrics."""
        node = self._make_node(extra={"complexity_score": 2.0})
        node_id = self.store.upsert_node(node)
        self.store.commit()

        updated = self._make_node(extra={"complexity_score": 9.0})
        self.store.upsert_node(updated)
        self.store.commit()

        metric_row = self.store._conn.execute(
            "SELECT value FROM node_metrics WHERE node_id=? AND metric=?",
            (node_id, "complexity_score"),
        ).fetchone()
        assert metric_row["value"] == 9.0

    def test_none_metric_not_inserted(self):
        """Metrics absent from extra should not appear in node_metrics."""
        node = self._make_node(extra={})
        node_id = self.store.upsert_node(node)
        self.store.commit()
        rows = self.store._conn.execute(
            "SELECT * FROM node_metrics WHERE node_id=?", (node_id,)
        ).fetchall()
        assert len(rows) == 0
