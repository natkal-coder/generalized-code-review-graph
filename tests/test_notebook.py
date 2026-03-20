"""Tests for Jupyter notebook (.ipynb) parsing."""

import json
from pathlib import Path

from code_review_graph.parser import CodeParser, _SQL_TABLE_RE

FIXTURES = Path(__file__).parent / "fixtures"


class TestNotebookParsing:
    def setup_method(self):
        self.parser = CodeParser()
        self.nodes, self.edges = self.parser.parse_file(
            FIXTURES / "sample_notebook.ipynb",
        )

    def test_detects_notebook(self):
        assert self.parser.detect_language(Path("analysis.ipynb")) == "notebook"

    def test_file_node_uses_python_language(self):
        file_node = [n for n in self.nodes if n.kind == "File"][0]
        assert file_node.language == "python"

    def test_parses_python_functions(self):
        funcs = [n for n in self.nodes if n.kind == "Function"]
        names = {f.name for f in funcs}
        assert "add" in names
        assert "multiply" in names

    def test_parses_python_classes(self):
        classes = [n for n in self.nodes if n.kind == "Class"]
        names = {c.name for c in classes}
        assert "DataProcessor" in names

    def test_parses_class_methods(self):
        methods = [
            n for n in self.nodes
            if n.kind == "Function" and n.parent_name == "DataProcessor"
        ]
        names = {m.name for m in methods}
        assert "__init__" in names
        assert "process" in names

    def test_cell_index_tracking(self):
        funcs = {n.name: n for n in self.nodes if n.kind == "Function"}
        # add and multiply are in cell index 2 (3rd code cell, 0-based)
        assert funcs["add"].extra.get("cell_index") == 2
        assert funcs["multiply"].extra.get("cell_index") == 2
        # DataProcessor.__init__ is in cell index 3
        assert funcs["__init__"].extra.get("cell_index") == 3

    def test_cross_cell_calls(self):
        calls = [e for e in self.edges if e.kind == "CALLS"]
        targets = {e.target.split("::")[-1] for e in calls}
        # process() calls add() and multiply() from different cells
        assert "add" in targets
        assert "multiply" in targets

    def test_imports_from_cells(self):
        imports = [e for e in self.edges if e.kind == "IMPORTS_FROM"]
        targets = {e.target for e in imports}
        assert "os" in targets
        assert "pathlib" in targets
        assert "math" in targets

    def test_skips_magic_commands(self):
        # %pip and !ls lines should be filtered out — no parse errors
        funcs = [n for n in self.nodes if n.kind == "Function"]
        assert len(funcs) >= 4  # add, multiply, __init__, process

    def test_empty_notebook(self):
        nb = {
            "cells": [],
            "metadata": {"kernelspec": {"language": "python"}},
            "nbformat": 4,
        }
        source = json.dumps(nb).encode("utf-8")
        nodes, edges = self.parser.parse_bytes(
            Path("empty.ipynb"), source,
        )
        assert len(nodes) == 1
        assert nodes[0].kind == "File"
        assert edges == []

    def test_non_python_kernel(self):
        nb = {
            "cells": [
                {"cell_type": "code", "source": ["println(\"hello\")"], "outputs": []},
            ],
            "metadata": {"kernelspec": {"language": "scala"}},
            "nbformat": 4,
        }
        source = json.dumps(nb).encode("utf-8")
        nodes, edges = self.parser.parse_bytes(
            Path("scala_notebook.ipynb"), source,
        )
        assert nodes == []
        assert edges == []

    def test_malformed_json(self):
        source = b"not valid json {{"
        nodes, edges = self.parser.parse_bytes(
            Path("bad.ipynb"), source,
        )
        assert nodes == []
        assert edges == []


class TestSqlTableExtraction:
    def test_from_clause(self):
        matches = _SQL_TABLE_RE.findall("SELECT * FROM my_table")
        assert "my_table" in matches

    def test_qualified_table(self):
        matches = _SQL_TABLE_RE.findall("SELECT * FROM catalog.schema.table")
        assert "catalog.schema.table" in matches

    def test_join(self):
        matches = _SQL_TABLE_RE.findall(
            "SELECT * FROM a JOIN b ON a.id = b.id"
        )
        assert "a" in matches
        assert "b" in matches

    def test_insert_into(self):
        matches = _SQL_TABLE_RE.findall("INSERT INTO target_table VALUES (1)")
        assert "target_table" in matches

    def test_create_table(self):
        matches = _SQL_TABLE_RE.findall("CREATE TABLE my_db.new_table (id INT)")
        assert "my_db.new_table" in matches

    def test_create_or_replace_view(self):
        matches = _SQL_TABLE_RE.findall(
            "CREATE OR REPLACE VIEW my_view AS SELECT 1"
        )
        assert "my_view" in matches

    def test_insert_overwrite(self):
        matches = _SQL_TABLE_RE.findall(
            "INSERT OVERWRITE catalog.schema.tbl SELECT * FROM src"
        )
        assert "catalog.schema.tbl" in matches
        assert "src" in matches

    def test_backtick_quoted(self):
        matches = _SQL_TABLE_RE.findall("SELECT * FROM `my-catalog`.`schema`.`table`")
        assert any("my-catalog" in m for m in matches)

    def test_no_table_refs(self):
        matches = _SQL_TABLE_RE.findall("SELECT 1 + 1")
        assert matches == []

    def test_case_insensitive(self):
        matches = _SQL_TABLE_RE.findall("select * from My_Table")
        assert "My_Table" in matches
