"""Tools 2, 3, 5, 6, 9: query / search / stats helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..embeddings import EmbeddingStore
from ..graph import edge_to_dict, node_to_dict
from ..hints import generate_hints, get_session
from ..incremental import get_changed_files, get_db_path, get_staged_and_unstaged
from ..search import hybrid_search
from ._common import _BUILTIN_CALL_NAMES, _get_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool 2: get_impact_radius
# ---------------------------------------------------------------------------

_QUERY_PATTERNS = {
    "callers_of": "Find all functions that call a given function",
    "callees_of": "Find all functions called by a given function",
    "imports_of": "Find all imports of a given file or module",
    "importers_of": "Find all files that import a given file or module",
    "children_of": "Find all nodes contained in a file or class",
    "tests_for": "Find all tests for a given function or class",
    "inheritors_of": "Find all classes that inherit from a given class",
    "file_summary": "Get a summary of all nodes in a file",
}


def get_impact_radius(
    changed_files: list[str] | None = None,
    max_depth: int = 2,
    max_results: int = 500,
    repo_root: str | None = None,
    base: str = "HEAD~1",
) -> dict[str, Any]:
    """Analyze the blast radius of changed files.

    Args:
        changed_files: Explicit list of changed file paths (relative to repo root).
                       If omitted, auto-detects from git diff.
        max_depth: How many hops to traverse in the graph (default: 2).
        max_results: Maximum impacted nodes to return (default: 500).
        repo_root: Repository root path. Auto-detected if omitted.
        base: Git ref for auto-detecting changes (default: HEAD~1).

    Returns:
        Changed nodes, impacted nodes, impacted files, connecting edges,
        plus ``truncated`` flag and ``total_impacted`` count.
    """
    store, root = _get_store(repo_root)
    try:
        if changed_files is None:
            changed_files = get_changed_files(root, base)
            if not changed_files:
                changed_files = get_staged_and_unstaged(root)

        if not changed_files:
            return {
                "status": "ok",
                "summary": "No changed files detected.",
                "changed_nodes": [],
                "impacted_nodes": [],
                "impacted_files": [],
                "truncated": False,
                "total_impacted": 0,
            }

        # Convert to absolute paths for graph lookup
        abs_files = [str(root / f) for f in changed_files]
        result = store.get_impact_radius(
            abs_files, max_depth=max_depth, max_nodes=max_results
        )

        changed_dicts = [node_to_dict(n) for n in result["changed_nodes"]]
        impacted_dicts = [node_to_dict(n) for n in result["impacted_nodes"]]
        edge_dicts = [edge_to_dict(e) for e in result["edges"]]
        truncated = result["truncated"]
        total_impacted = result["total_impacted"]

        summary_parts = [
            f"Blast radius for {len(changed_files)} changed file(s):",
            f"  - {len(changed_dicts)} nodes directly changed",
            f"  - {len(impacted_dicts)} nodes impacted (within {max_depth} hops)",
            f"  - {len(result['impacted_files'])} additional files affected",
        ]
        if truncated:
            summary_parts.append(
                f"  - Results truncated: showing {len(impacted_dicts)}"
                f" of {total_impacted} impacted nodes"
            )

        return {
            "status": "ok",
            "summary": "\n".join(summary_parts),
            "changed_files": changed_files,
            "changed_nodes": changed_dicts,
            "impacted_nodes": impacted_dicts,
            "impacted_files": result["impacted_files"],
            "edges": edge_dicts,
            "truncated": truncated,
            "total_impacted": total_impacted,
        }
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Tool 3: query_graph
# ---------------------------------------------------------------------------


def query_graph(
    pattern: str,
    target: str,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Run a predefined graph query.

    Args:
        pattern: Query pattern. One of: callers_of, callees_of, imports_of,
                 importers_of, children_of, tests_for, inheritors_of, file_summary.
        target: The node name, qualified name, or file path to query about.
        repo_root: Repository root path. Auto-detected if omitted.

    Returns:
        Matching nodes and edges for the query.
    """
    store, root = _get_store(repo_root)
    try:
        if pattern not in _QUERY_PATTERNS:
            return {
                "status": "error",
                "error": (
                    f"Unknown pattern '{pattern}'. "
                    f"Available: {list(_QUERY_PATTERNS.keys())}"
                ),
            }

        results: list[dict] = []
        edges_out: list[dict] = []

        # For callers_of, skip common builtins early (bare names only)
        # "Who calls .map()?" returns hundreds of useless hits.
        # Qualified names (e.g. "utils.py::map") bypass this filter.
        if (
            pattern == "callers_of"
            and target in _BUILTIN_CALL_NAMES
            and "::" not in target
        ):
            return {
                "status": "ok", "pattern": pattern, "target": target,
                "description": _QUERY_PATTERNS[pattern],
                "summary": (
                    f"'{target}' is a common builtin "
                    "— callers_of skipped to avoid noise."
                ),
                "results": [], "edges": [],
            }

        # Resolve target - try as-is, then as absolute path, then search
        node = store.get_node(target)
        if not node:
            abs_target = str(root / target)
            node = store.get_node(abs_target)
        if not node:
            # Search by name
            candidates = store.search_nodes(target, limit=5)
            if len(candidates) == 1:
                node = candidates[0]
                target = node.qualified_name
            elif len(candidates) > 1:
                return {
                    "status": "ambiguous",
                    "summary": (
                        f"Multiple matches for '{target}'. "
                        "Please use a qualified name."
                    ),
                    "candidates": [node_to_dict(c) for c in candidates],
                }

        if not node and pattern != "file_summary":
            return {
                "status": "not_found",
                "summary": f"No node found matching '{target}'.",
            }

        qn = node.qualified_name if node else target

        if pattern == "callers_of":
            for e in store.get_edges_by_target(qn):
                if e.kind == "CALLS":
                    caller = store.get_node(e.source_qualified)
                    if caller:
                        results.append(node_to_dict(caller))
                    edges_out.append(edge_to_dict(e))
            # Fallback: CALLS edges store unqualified target names
            # (e.g. "generateTestCode") while qn is fully qualified
            # (e.g. "file.ts::generateTestCode"). Search by plain name too.
            if not results and node:
                for e in store.search_edges_by_target_name(node.name):
                    caller = store.get_node(e.source_qualified)
                    if caller:
                        results.append(node_to_dict(caller))
                    edges_out.append(edge_to_dict(e))

        elif pattern == "callees_of":
            for e in store.get_edges_by_source(qn):
                if e.kind == "CALLS":
                    callee = store.get_node(e.target_qualified)
                    if callee:
                        results.append(node_to_dict(callee))
                    edges_out.append(edge_to_dict(e))

        elif pattern == "imports_of":
            for e in store.get_edges_by_source(qn):
                if e.kind == "IMPORTS_FROM":
                    results.append({"import_target": e.target_qualified})
                    edges_out.append(edge_to_dict(e))

        elif pattern == "importers_of":
            # Find edges where target matches this file.
            # Use resolve() to canonicalize the path, matching how
            # _resolve_module_to_file stores edge targets.
            abs_target = (
                str((root / target).resolve()) if node is None
                else node.file_path
            )
            for e in store.get_edges_by_target(abs_target):
                if e.kind == "IMPORTS_FROM":
                    results.append({
                        "importer": e.source_qualified,
                        "file": e.file_path,
                    })
                    edges_out.append(edge_to_dict(e))

        elif pattern == "children_of":
            for e in store.get_edges_by_source(qn):
                if e.kind == "CONTAINS":
                    child = store.get_node(e.target_qualified)
                    if child:
                        results.append(node_to_dict(child))

        elif pattern == "tests_for":
            for e in store.get_edges_by_target(qn):
                if e.kind == "TESTED_BY":
                    test = store.get_node(e.source_qualified)
                    if test:
                        results.append(node_to_dict(test))
            # Also search by naming convention
            name = node.name if node else target
            test_nodes = store.search_nodes(f"test_{name}", limit=10)
            test_nodes += store.search_nodes(f"Test{name}", limit=10)
            seen = {r.get("qualified_name") for r in results}
            for t in test_nodes:
                if t.qualified_name not in seen and t.is_test:
                    results.append(node_to_dict(t))

        elif pattern == "inheritors_of":
            for e in store.get_edges_by_target(qn):
                if e.kind in ("INHERITS", "IMPLEMENTS"):
                    child = store.get_node(e.source_qualified)
                    if child:
                        results.append(node_to_dict(child))
                    edges_out.append(edge_to_dict(e))

        elif pattern == "file_summary":
            abs_path = str(root / target)
            file_nodes = store.get_nodes_by_file(abs_path)
            for n in file_nodes:
                results.append(node_to_dict(n))

        return {
            "status": "ok",
            "pattern": pattern,
            "target": target,
            "description": _QUERY_PATTERNS[pattern],
            "summary": (
                f"Found {len(results)} result(s) "
                f"for {pattern}('{target}')"
            ),
            "results": results,
            "edges": edges_out,
        }
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Tool 5: semantic_search_nodes
# ---------------------------------------------------------------------------


def semantic_search_nodes(
    query: str,
    kind: str | None = None,
    limit: int = 20,
    repo_root: str | None = None,
    context_files: list[str] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Search for nodes by name, keyword, or semantic similarity.

    Uses hybrid search (FTS5 BM25 + vector embeddings merged via Reciprocal
    Rank Fusion) as the primary search path, with graceful fallback to
    keyword matching.

    Args:
        query: Search string to match against node names and qualified names.
        kind: Optional filter by node kind (File, Class, Function, Type, Test).
        limit: Maximum results to return (default: 20).
        repo_root: Repository root path. Auto-detected if omitted.
        context_files: Optional list of file paths. Nodes in these files
            receive a relevance boost.

    Returns:
        Ranked list of matching nodes.
    """
    store, root = _get_store(repo_root)
    try:
        results = hybrid_search(
            store, query, kind=kind, limit=limit, context_files=context_files,
            model=model,
        )

        search_mode = "hybrid"
        if not results:
            search_mode = "keyword"

        result: dict[str, object] = {
            "status": "ok",
            "query": query,
            "search_mode": search_mode,
            "summary": f"Found {len(results)} node(s) matching '{query}'" + (
                f" (kind={kind})" if kind else ""
            ),
            "results": results,
        }
        result["_hints"] = generate_hints(
            "semantic_search_nodes", result, get_session()
        )
        return result
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Tool 6: list_graph_stats
# ---------------------------------------------------------------------------


def list_graph_stats(repo_root: str | None = None) -> dict[str, Any]:
    """Get aggregate statistics about the knowledge graph.

    Args:
        repo_root: Repository root path. Auto-detected if omitted.

    Returns:
        Total nodes, edges, breakdown by kind, languages, and last update time.
    """
    store, root = _get_store(repo_root)
    try:
        stats = store.get_stats()

        summary_parts = [
            f"Graph statistics for {root.name}:",
            f"  Files: {stats.files_count}",
            f"  Total nodes: {stats.total_nodes}",
            f"  Total edges: {stats.total_edges}",
            f"  Languages: {', '.join(stats.languages) if stats.languages else 'none'}",
            f"  Last updated: {stats.last_updated or 'never'}",
            "",
            "Nodes by kind:",
        ]
        for kind, count in sorted(stats.nodes_by_kind.items()):
            summary_parts.append(f"  {kind}: {count}")
        summary_parts.append("")
        summary_parts.append("Edges by kind:")
        for kind, count in sorted(stats.edges_by_kind.items()):
            summary_parts.append(f"  {kind}: {count}")

        # Add embedding info if available
        emb_store = EmbeddingStore(get_db_path(root))
        try:
            emb_count = emb_store.count()
            summary_parts.append("")
            summary_parts.append(f"Embeddings: {emb_count} nodes embedded")
            if not emb_store.available:
                summary_parts.append(
                    "  (install sentence-transformers for semantic search)"
                )
        finally:
            emb_store.close()

        return {
            "status": "ok",
            "summary": "\n".join(summary_parts),
            "total_nodes": stats.total_nodes,
            "total_edges": stats.total_edges,
            "nodes_by_kind": stats.nodes_by_kind,
            "edges_by_kind": stats.edges_by_kind,
            "languages": stats.languages,
            "files_count": stats.files_count,
            "last_updated": stats.last_updated,
            "embeddings_count": emb_count,
        }
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Tool 9: find_large_functions
# ---------------------------------------------------------------------------


def find_large_functions(
    min_lines: int = 50,
    kind: str | None = None,
    file_path_pattern: str | None = None,
    limit: int = 50,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Find functions, classes, or files exceeding a line-count threshold.

    Useful for identifying decomposition targets, code-quality audits,
    and enforcing size limits during code review.

    Args:
        min_lines: Minimum line count to flag (default: 50).
        kind: Filter by node kind: Function, Class, File, or Test.
        file_path_pattern: Filter by file path substring (e.g. "components/").
        limit: Maximum results (default: 50).
        repo_root: Repository root path. Auto-detected if omitted.

    Returns:
        Oversized nodes with line counts, ordered largest first.
    """
    store, root = _get_store(repo_root)
    try:
        nodes = store.get_nodes_by_size(
            min_lines=min_lines,
            kind=kind,
            file_path_pattern=file_path_pattern,
            limit=limit,
        )

        results = []
        for n in nodes:
            d = node_to_dict(n)
            d["line_count"] = (
                (n.line_end - n.line_start + 1)
                if n.line_start and n.line_end
                else 0
            )
            # Make file_path relative for readability
            try:
                d["relative_path"] = str(Path(n.file_path).relative_to(root))
            except ValueError:
                d["relative_path"] = n.file_path
            results.append(d)

        summary_parts = [
            f"Found {len(results)} node(s) with >= {min_lines} lines"
            + (f" (kind={kind})" if kind else "")
            + (f" matching '{file_path_pattern}'" if file_path_pattern else "")
            + ":",
        ]
        for r in results[:10]:
            summary_parts.append(
                f"  {r['line_count']:>4} lines | {r['kind']:>8} | "
                f"{r['name']} ({r['relative_path']}:{r['line_start']})"
            )
        if len(results) > 10:
            summary_parts.append(f"  ... and {len(results) - 10} more")

        return {
            "status": "ok",
            "summary": "\n".join(summary_parts),
            "total_found": len(results),
            "min_lines": min_lines,
            "results": results,
        }
    finally:
        store.close()

# ---------------------------------------------------------------------------
# Tool 23: get_code_quality_warnings
# ---------------------------------------------------------------------------

_VALID_SMELL_TYPES = frozenset(
    [
        "god_object", "long_param_list", "deep_nesting",
        "magic_numbers", "silent_catch", "unused_imports",
    ]
)
_VALID_SEVERITIES = frozenset(["critical", "high", "medium", "low"])

_SMELL_EXPLANATIONS: dict[str, str] = {
    "god_object": "Class >= 300 lines; likely handles too many responsibilities.",
    "long_param_list": "Function has 5+ parameters; consider a config object.",
    "deep_nesting": "Control flow nests >= 4 levels deep; use early returns.",
    "magic_numbers": "High cyclomatic complexity likely contains unexplained constants.",
    "silent_catch": "Detected via annotation; exception swallowed without logging.",
    "unused_imports": "Detected via annotation; import not referenced in file.",
}


def _derive_smells(
    kind: str,
    complexity_score: float | None,
    cognitive_complexity: float | None,
    param_count: int | None,
    nesting_depth: int | None,
    line_count: int,
) -> list[str]:
    """Derive smell tags from metric thresholds."""
    smells: list[str] = []
    if kind == "Class" and line_count >= 300:
        smells.append("god_object")
    if param_count is not None and param_count >= 5:
        smells.append("long_param_list")
    if nesting_depth is not None and nesting_depth >= 4:
        smells.append("deep_nesting")
    if complexity_score is not None and complexity_score >= 10:
        smells.append("magic_numbers")  # proxy: high cyclomatic often has magic constants
    return smells


def _smell_severity(smell_tags: list[str], complexity_score: float | None) -> str:
    """Map smell list + complexity to a severity bucket."""
    score = complexity_score or 0
    count = len(smell_tags)
    if count >= 3 or score >= 25:
        return "critical"
    if count == 2 or score >= 15:
        return "high"
    if count == 1 or score >= 10:
        return "medium"
    return "low"


def get_code_quality_warnings(
    min_complexity: int = 10,
    file_path: str | None = None,
    limit: int = 20,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Query nodes exceeding a cyclomatic complexity threshold.

    Args:
        min_complexity: Minimum complexity_score to flag (default: 10).
        file_path: Filter by file path substring (e.g. "src/").
        limit: Maximum results (default: 20).
        repo_root: Repository root path. Auto-detected if omitted.

    Returns:
        {status, data, summary} with nodes ordered by complexity_score DESC.
        Each entry contains name, type, file, complexity_score,
        cognitive_complexity, param_count, nesting_depth, smell_tags.
    """
    store, root = _get_store(repo_root)
    try:
        params: list[Any] = [float(min_complexity)]
        sql = """
            SELECT
                name, kind, file_path,
                line_start, line_end,
                complexity_score,
                cognitive_complexity,
                param_count,
                nesting_depth
            FROM nodes
            WHERE complexity_score >= ?
        """
        if file_path:
            sql += " AND file_path LIKE ?"
            params.append(f"%{file_path}%")
        sql += " ORDER BY complexity_score DESC LIMIT ?"
        params.append(limit)

        rows = store._conn.execute(sql, params).fetchall()

        data: list[dict[str, Any]] = []
        for row in rows:
            line_count = (
                (row["line_end"] - row["line_start"] + 1)
                if row["line_start"] is not None and row["line_end"] is not None
                else 0
            )
            smells = _derive_smells(
                row["kind"],
                row["complexity_score"],
                row["cognitive_complexity"],
                row["param_count"],
                row["nesting_depth"],
                line_count,
            )
            try:
                rel_file = str(Path(row["file_path"]).relative_to(root))
            except ValueError:
                rel_file = row["file_path"]
            data.append({
                "name": row["name"],
                "type": row["kind"],
                "file": rel_file,
                "complexity_score": row["complexity_score"],
                "cognitive_complexity": row["cognitive_complexity"],
                "param_count": row["param_count"],
                "nesting_depth": row["nesting_depth"],
                "smell_tags": smells,
            })

        summary = (
            f"Found {len(data)} node(s) with complexity >= {min_complexity}"
            + (f" in '{file_path}'" if file_path else "")
        )
        return {"status": "ok", "summary": summary, "data": data}
    except Exception as exc:
        logger.warning("get_code_quality_warnings error: %s", exc)
        return {"status": "error", "summary": str(exc), "data": []}
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Tool 24: get_code_smells
# ---------------------------------------------------------------------------


def get_code_smells(
    smell_type: str | None = None,
    severity: str | None = None,
    file_path: str | None = None,
    limit: int = 20,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Query nodes by code smell type and/or severity.

    smell_type values: god_object, long_param_list, deep_nesting,
                       magic_numbers, silent_catch, unused_imports.
    severity values: critical, high, medium, low.

    Args:
        smell_type: Filter by specific smell. Returns all smells if omitted.
        severity: Filter by severity bucket. Returns all severities if omitted.
        file_path: Filter by file path substring.
        limit: Maximum results (default: 20).
        repo_root: Repository root path. Auto-detected if omitted.

    Returns:
        {status, data, summary} with nodes that exhibit the requested smell.
        Each entry contains name, type, file, smell_tags, complexity_score,
        explanation.
    """
    if smell_type and smell_type not in _VALID_SMELL_TYPES:
        return {
            "status": "error",
            "summary": (
                f"Unknown smell_type '{smell_type}'. "
                f"Valid values: {sorted(_VALID_SMELL_TYPES)}"
            ),
            "data": [],
        }
    if severity and severity not in _VALID_SEVERITIES:
        return {
            "status": "error",
            "summary": (
                f"Unknown severity '{severity}'. "
                f"Valid values: {sorted(_VALID_SEVERITIES)}"
            ),
            "data": [],
        }

    store, root = _get_store(repo_root)
    try:
        # Pull all nodes that have at least one non-null metric to derive smells from.
        params: list[Any] = []
        sql = """
            SELECT
                name, kind, file_path,
                line_start, line_end,
                complexity_score,
                cognitive_complexity,
                param_count,
                nesting_depth
            FROM nodes
            WHERE (
                complexity_score IS NOT NULL
                OR cognitive_complexity IS NOT NULL
                OR param_count IS NOT NULL
                OR nesting_depth IS NOT NULL
            )
        """
        if file_path:
            sql += " AND file_path LIKE ?"
            params.append(f"%{file_path}%")
        # Fetch more than limit so we can filter by smell/severity before truncating.
        sql += " ORDER BY complexity_score DESC LIMIT ?"
        params.append(limit * 10)

        rows = store._conn.execute(sql, params).fetchall()

        data: list[dict[str, Any]] = []
        for row in rows:
            line_count = (
                (row["line_end"] - row["line_start"] + 1)
                if row["line_start"] is not None and row["line_end"] is not None
                else 0
            )
            smells = _derive_smells(
                row["kind"],
                row["complexity_score"],
                row["cognitive_complexity"],
                row["param_count"],
                row["nesting_depth"],
                line_count,
            )
            if not smells:
                continue
            row_severity = _smell_severity(smells, row["complexity_score"])
            if smell_type and smell_type not in smells:
                continue
            if severity and row_severity != severity:
                continue
            try:
                rel_file = str(Path(row["file_path"]).relative_to(root))
            except ValueError:
                rel_file = row["file_path"]
            active_smells = [smell_type] if smell_type else smells
            data.append({
                "name": row["name"],
                "type": row["kind"],
                "file": rel_file,
                "smell_tags": active_smells,
                "severity": row_severity,
                "complexity_score": row["complexity_score"],
                "explanation": " | ".join(
                    _SMELL_EXPLANATIONS[s] for s in active_smells if s in _SMELL_EXPLANATIONS
                ),
            })
            if len(data) >= limit:
                break

        filter_desc = " | ".join(
            p for p in [
                f"smell={smell_type}" if smell_type else None,
                f"severity={severity}" if severity else None,
                f"file='{file_path}'" if file_path else None,
            ]
            if p
        )
        summary = f"Found {len(data)} smell(s)" + (f" [{filter_desc}]" if filter_desc else "")
        return {"status": "ok", "summary": summary, "data": data}
    except Exception as exc:
        logger.warning("get_code_smells error: %s", exc)
        return {"status": "error", "summary": str(exc), "data": []}
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Tool 25: list_undocumented_functions
# ---------------------------------------------------------------------------


def list_undocumented_functions(
    file_path: str | None = None,
    limit: int = 20,
    repo_root: str | None = None,
) -> dict[str, Any]:
    """Query functions and methods missing documentation (documentation_gap=1).

    Results are sorted by complexity_score DESC so the most complex
    undocumented functions surface first.

    Args:
        file_path: Filter by file path substring.
        limit: Maximum results (default: 20).
        repo_root: Repository root path. Auto-detected if omitted.

    Returns:
        {status, data, summary} with undocumented nodes.
        Each entry contains name, file, lines, complexity_score,
        cognitive_complexity.
    """
    store, root = _get_store(repo_root)
    try:
        params: list[Any] = []
        sql = """
            SELECT
                name, kind, file_path,
                line_start, line_end,
                complexity_score,
                cognitive_complexity
            FROM nodes
            WHERE documentation_gap = 1
              AND kind IN ('Function', 'Test')
        """
        if file_path:
            sql += " AND file_path LIKE ?"
            params.append(f"%{file_path}%")
        sql += " ORDER BY complexity_score DESC NULLS LAST LIMIT ?"
        params.append(limit)

        rows = store._conn.execute(sql, params).fetchall()

        data: list[dict[str, Any]] = []
        for row in rows:
            line_count = (
                (row["line_end"] - row["line_start"] + 1)
                if row["line_start"] is not None and row["line_end"] is not None
                else 0
            )
            try:
                rel_file = str(Path(row["file_path"]).relative_to(root))
            except ValueError:
                rel_file = row["file_path"]
            data.append({
                "name": row["name"],
                "type": row["kind"],
                "file": rel_file,
                "lines": line_count,
                "complexity_score": row["complexity_score"],
                "cognitive_complexity": row["cognitive_complexity"],
            })

        summary = (
            f"Found {len(data)} undocumented function(s)"
            + (f" in '{file_path}'" if file_path else "")
            + " (sorted by complexity, highest first)"
        )
        return {"status": "ok", "summary": summary, "data": data}
    except Exception as exc:
        logger.warning("list_undocumented_functions error: %s", exc)
        return {"status": "error", "summary": str(exc), "data": []}
    finally:
        store.close()
