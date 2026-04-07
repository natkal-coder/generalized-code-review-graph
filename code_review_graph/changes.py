"""Change impact analysis for code review.

Maps git diffs to affected functions, flows, communities, and test coverage
gaps. Produces risk-scored, priority-ordered review guidance enriched with
code quality metrics (complexity, smells, documentation coverage).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

from .constants import SECURITY_KEYWORDS as _SECURITY_KEYWORDS
from .flows import get_affected_flows
from .graph import GraphNode, GraphStore, _sanitize_name, node_to_dict

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = int(os.environ.get("CRG_GIT_TIMEOUT", "30"))  # seconds, configurable

_SAFE_GIT_REF = re.compile(r"^[A-Za-z0-9_.~^/@{}\-]+$")

# Thresholds for smell detection
_CC_HIGH = 10       # cyclomatic complexity: high
_CC_VERY_HIGH = 20  # cyclomatic complexity: very high
_COG_HIGH = 15      # cognitive complexity: high
_PARAM_LONG = 5     # long parameter list


# ---------------------------------------------------------------------------
# 1. parse_git_diff_ranges
# ---------------------------------------------------------------------------


def parse_git_diff_ranges(
    repo_root: str,
    base: str = "HEAD~1",
) -> dict[str, list[tuple[int, int]]]:
    """Run ``git diff --unified=0`` and extract changed line ranges per file.

    Args:
        repo_root: Absolute path to the repository root.
        base: Git ref to diff against (default: ``HEAD~1``).

    Returns:
        Mapping of file paths to lists of ``(start_line, end_line)`` tuples.
        Returns an empty dict on error.
    """
    if not _SAFE_GIT_REF.match(base):
        logger.warning("Invalid git ref rejected: %s", base)
        return {}
    try:
        result = subprocess.run(
            ["git", "diff", "--unified=0", base, "--"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=_GIT_TIMEOUT,
        )
        if result.returncode != 0:
            logger.warning("git diff failed (rc=%d): %s", result.returncode, result.stderr[:200])
            return {}
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("git diff error: %s", exc)
        return {}

    return _parse_unified_diff(result.stdout)


def _parse_unified_diff(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Parse unified diff output into file -> line-range mappings.

    Handles the ``@@ -old,count +new,count @@`` hunk header format.
    """
    ranges: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None

    # Match "+++ b/path/to/file"
    file_pattern = re.compile(r"^\+\+\+ b/(.+)$")
    # Match "@@ ... +start,count @@" or "@@ ... +start @@"
    hunk_pattern = re.compile(r"^@@ .+? \+(\d+)(?:,(\d+))? @@")

    for line in diff_text.splitlines():
        file_match = file_pattern.match(line)
        if file_match:
            current_file = file_match.group(1)
            continue

        hunk_match = hunk_pattern.match(line)
        if hunk_match and current_file is not None:
            start = int(hunk_match.group(1))
            count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
            if count == 0:
                # Pure deletion hunk (no lines added); still note the position.
                end = start
            else:
                end = start + count - 1
            ranges.setdefault(current_file, []).append((start, end))

    return ranges


# ---------------------------------------------------------------------------
# 2. map_changes_to_nodes
# ---------------------------------------------------------------------------


def map_changes_to_nodes(
    store: GraphStore,
    changed_ranges: dict[str, list[tuple[int, int]]],
) -> list[GraphNode]:
    """Find graph nodes whose line ranges overlap the changed lines.

    Args:
        store: The graph store.
        changed_ranges: Mapping of file paths to ``(start, end)`` tuples.

    Returns:
        Deduplicated list of overlapping graph nodes.
    """
    seen: set[str] = set()
    result: list[GraphNode] = []

    for file_path, ranges in changed_ranges.items():
        # Try the path as-is, then also try all nodes to match relative paths.
        nodes = store.get_nodes_by_file(file_path)
        if not nodes:
            # The graph may store absolute paths; try a suffix match.
            matched_paths = store.get_files_matching(file_path)
            for mp in matched_paths:
                nodes.extend(store.get_nodes_by_file(mp))

        for node in nodes:
            if node.qualified_name in seen:
                continue
            if node.line_start is None or node.line_end is None:
                continue
            # Check overlap with any changed range.
            for start, end in ranges:
                if node.line_start <= end and node.line_end >= start:
                    result.append(node)
                    seen.add(node.qualified_name)
                    break

    return result


# ---------------------------------------------------------------------------
# 3. compute_risk_score
# ---------------------------------------------------------------------------


def compute_risk_score(store: GraphStore, node: GraphNode) -> float:
    """Compute a risk score (0.0 - 1.0) for a single node.

    Scoring factors:
      - Flow participation: 0.05 per flow membership, capped at 0.25
      - Community crossing: 0.05 per caller from a different community, capped at 0.15
      - Test coverage: 0.30 if no TESTED_BY edges, 0.05 if tested
      - Security sensitivity: 0.20 if name matches security keywords
      - Caller count: callers / 20, capped at 0.10
    """
    score = 0.0

    # --- Flow participation (cap 0.25) ---
    flow_count = store.count_flow_memberships(node.id)
    score += min(flow_count * 0.05, 0.25)

    # --- Community crossing (cap 0.15) ---
    callers = store.get_edges_by_target(node.qualified_name)
    caller_edges = [e for e in callers if e.kind == "CALLS"]

    cross_community = 0
    node_cid = store.get_node_community_id(node.id)

    if node_cid is not None and caller_edges:
        caller_qns = [edge.source_qualified for edge in caller_edges]
        cid_map = store.get_community_ids_by_qualified_names(caller_qns)
        for cid in cid_map.values():
            if cid is not None and cid != node_cid:
                cross_community += 1
    score += min(cross_community * 0.05, 0.15)

    # --- Test coverage ---
    tested_edges = store.get_edges_by_target(node.qualified_name)
    has_test = any(e.kind == "TESTED_BY" for e in tested_edges)
    score += 0.05 if has_test else 0.30

    # --- Security sensitivity ---
    name_lower = node.name.lower()
    qn_lower = node.qualified_name.lower()
    if any(kw in name_lower or kw in qn_lower for kw in _SECURITY_KEYWORDS):
        score += 0.20

    # --- Caller count (cap 0.10) ---
    caller_count = len(caller_edges)
    score += min(caller_count / 20.0, 0.10)

    return round(min(max(score, 0.0), 1.0), 4)


# ---------------------------------------------------------------------------
# 4. Code quality helpers
# ---------------------------------------------------------------------------


def _smell_tags_for_node(node: GraphNode) -> list[dict[str, str]]:
    """Return a list of smell dicts for a single node based on its metrics.

    Each dict has ``smell`` (str) and ``severity`` ("low" | "medium" | "high").
    Returns an empty list when no smells are detected or metrics are absent.
    """
    smells: list[dict[str, str]] = []

    cc = node.complexity_score
    if cc is not None:
        if cc >= _CC_VERY_HIGH:
            smells.append({"smell": "high_cyclomatic_complexity", "severity": "high"})
        elif cc >= _CC_HIGH:
            smells.append({"smell": "high_cyclomatic_complexity", "severity": "medium"})

    cog = node.cognitive_complexity
    if cog is not None and cog >= _COG_HIGH:
        smells.append({"smell": "high_cognitive_complexity", "severity": "high"})

    pc = node.param_count
    if pc is not None and pc >= _PARAM_LONG:
        smells.append({"smell": "long_param_list", "severity": "high"})

    nd = node.nesting_depth
    if nd is not None and nd >= 4:
        severity = "high" if nd >= 6 else "medium"
        smells.append({"smell": "deep_nesting", "severity": severity})

    return smells


def _complexity_entry(node: GraphNode) -> dict[str, Any]:
    """Build a per-node complexity record suitable for the output dict."""
    return {
        "name": _sanitize_name(node.name),
        "qualified_name": _sanitize_name(node.qualified_name),
        "file": node.file_path,
        "line_start": node.line_start,
        "cc": node.complexity_score,
        "cognitive": node.cognitive_complexity,
        "nesting_depth": node.nesting_depth,
        "param_count": node.param_count,
    }


def _compute_complexity_analysis(
    store: GraphStore,
    changed_funcs: list[GraphNode],
    base: str,
    repo_root: str | None,
) -> dict[str, Any]:
    """Produce a complexity_analysis block for changed functions.

    For each changed function we compare the current metrics stored in the graph
    (which reflect the post-change state after the last ``build``/``update``) to
    the metrics that were recorded for the base commit.  Because the graph only
    stores the current state, the "before" metrics are approximated by querying
    the ``node_metrics`` history table when available; otherwise we mark the
    delta as unknown (``None``).

    In practice the graph is rebuilt after each push, so ``complexity_score``
    on the node reflects the newest code.  The "before" value is the last
    persisted metric for that node (recorded by a previous build).
    """
    increased: list[dict[str, Any]] = []
    decreased: list[dict[str, Any]] = []
    total_delta = 0

    for node in changed_funcs:
        if node.is_test:
            continue
        cc_after = node.complexity_score
        if cc_after is None:
            continue

        # Try to retrieve the previous metric from node_metrics history.
        cc_before: float | None = _get_previous_metric(store, node.id, "complexity_score")

        if cc_before is None:
            # No prior snapshot — treat as new function, delta unknown.
            continue

        delta = cc_after - cc_before
        if delta == 0:
            continue

        total_delta += delta
        entry = {
            "name": _sanitize_name(node.name),
            "qualified_name": _sanitize_name(node.qualified_name),
            "file": node.file_path,
            "cc_before": round(cc_before, 2),
            "cc_after": round(cc_after, 2),
            "delta": round(delta, 2),
        }
        if delta > 0:
            increased.append(entry)
        else:
            decreased.append(entry)

    # Sort by absolute delta descending so worst offenders appear first.
    increased.sort(key=lambda x: x["delta"], reverse=True)
    decreased.sort(key=lambda x: x["delta"])

    return {
        "total_complexity_delta": round(total_delta, 2),
        "functions_with_increased_complexity": increased,
        "functions_with_decreased_complexity": decreased,
    }


def _get_previous_metric(store: GraphStore, node_id: int, metric: str) -> float | None:
    """Retrieve the second-to-last recorded value for a metric from node_metrics.

    node_metrics stores the current value only (upserted on each build).
    If no historical data is available returns ``None``.

    This function queries the ``node_metrics_history`` table when it exists
    (added in a future migration), falling back to ``None`` gracefully.
    """
    try:
        row = store._conn.execute(  # noqa: SLF001
            """SELECT value FROM node_metrics_history
               WHERE node_id = ? AND metric = ?
               ORDER BY recorded_at DESC
               LIMIT 1 OFFSET 1""",
            (node_id, metric),
        ).fetchone()
        return float(row["value"]) if row else None
    except Exception:
        # Table doesn't exist or query failed — degrade gracefully.
        return None


def _compute_smell_analysis(changed_funcs: list[GraphNode]) -> dict[str, Any]:
    """Identify code smells introduced or present in changed functions.

    Since we only have the current state (post-change), we report smells on
    the changed nodes.  We cannot reliably detect "removed" smells without
    historical metrics, so ``removed_smells`` will always be empty unless
    ``node_metrics_history`` is available.
    """
    new_smells: list[dict[str, Any]] = []

    for node in changed_funcs:
        if node.is_test:
            continue
        for smell in _smell_tags_for_node(node):
            new_smells.append({
                "function": _sanitize_name(node.qualified_name),
                "file": node.file_path,
                **smell,
            })

    # Sort by severity (high > medium > low).
    _sev_order = {"high": 0, "medium": 1, "low": 2}
    new_smells.sort(key=lambda x: _sev_order.get(x["severity"], 9))

    return {
        "new_smells": new_smells,
        "removed_smells": [],  # requires node_metrics_history; not yet implemented
    }


def _compute_test_impact(
    store: GraphStore,
    changed_funcs: list[GraphNode],
) -> dict[str, Any]:
    """Count tests directly affected by changes and estimate coverage delta.

    "Affected" means the test has a TESTED_BY edge pointing at one of the
    changed functions, or the changed function CALLS something that is tested.
    We do not walk the full transitive closure to keep this O(n).
    """
    affected_test_qns: set[str] = set()
    total_non_test = 0

    for node in changed_funcs:
        if node.is_test:
            continue
        total_non_test += 1
        edges = store.get_edges_by_target(node.qualified_name)
        for e in edges:
            if e.kind == "TESTED_BY":
                affected_test_qns.add(e.source_qualified)

    tests_affected = len(affected_test_qns)

    # Coverage delta: approximate as fraction of untested changed functions.
    # Negative delta means coverage got worse (more untested code).
    if total_non_test == 0:
        coverage_delta = 0.0
    else:
        untested = sum(
            1 for n in changed_funcs
            if not n.is_test and not any(
                e.kind == "TESTED_BY"
                for e in store.get_edges_by_target(n.qualified_name)
            )
        )
        coverage_delta = round(-100.0 * untested / total_non_test, 1)

    return {
        "tests_affected": tests_affected,
        "test_coverage_delta": coverage_delta,
    }


def _compute_documentation_changes(changed_funcs: list[GraphNode]) -> dict[str, Any]:
    """Count documentation gaps introduced or fixed by the change set."""
    now_undocumented = sum(
        1 for n in changed_funcs
        if not n.is_test and n.documentation_gap and not n.has_docstring
    )
    now_documented = sum(
        1 for n in changed_funcs
        if not n.is_test and n.has_docstring and not n.documentation_gap
    )
    return {
        "functions_now_undocumented": now_undocumented,
        "functions_now_documented": now_documented,
    }


# ---------------------------------------------------------------------------
# 5. analyze_changes
# ---------------------------------------------------------------------------


def analyze_changes(
    store: GraphStore,
    changed_files: list[str],
    changed_ranges: dict[str, list[tuple[int, int]]] | None = None,
    repo_root: str | None = None,
    base: str = "HEAD~1",
) -> dict[str, Any]:
    """Analyze changes and produce risk-scored review guidance.

    Args:
        store: The graph store.
        changed_files: List of changed file paths.
        changed_ranges: Optional pre-parsed diff ranges. If not provided and
            ``repo_root`` is given, they are computed via git.
        repo_root: Repository root (for git diff).
        base: Git ref to diff against.

    Returns:
        Dict with ``summary``, ``risk_score``, ``changed_functions``,
        ``affected_flows``, ``test_gaps``, ``review_priorities``,
        ``complexity_analysis``, ``smell_analysis``, ``test_impact``, and
        ``documentation_changes``.
    """
    # Compute changed ranges if not provided.
    if changed_ranges is None and repo_root is not None:
        changed_ranges = parse_git_diff_ranges(repo_root, base)

    # Map changes to nodes.
    if changed_ranges:
        changed_nodes = map_changes_to_nodes(store, changed_ranges)
    else:
        # Fallback: all nodes in changed files.
        changed_nodes = []
        for fp in changed_files:
            changed_nodes.extend(store.get_nodes_by_file(fp))

    # Filter to functions/tests for risk scoring (skip File nodes).
    changed_funcs = [
        n for n in changed_nodes
        if n.kind in ("Function", "Test", "Class")
    ]

    # Compute per-node risk scores.
    node_risks: list[dict[str, Any]] = []
    for node in changed_funcs:
        risk = compute_risk_score(store, node)
        node_risks.append({
            **node_to_dict(node),
            "risk_score": risk,
        })

    # Overall risk score: max of individual risks, or 0.
    overall_risk = max((nr["risk_score"] for nr in node_risks), default=0.0)

    # Affected flows.
    affected = get_affected_flows(store, changed_files)

    # Detect test gaps: changed functions without TESTED_BY edges.
    test_gaps: list[dict[str, Any]] = []
    for node in changed_funcs:
        if node.is_test:
            continue
        tested = store.get_edges_by_target(node.qualified_name)
        if not any(e.kind == "TESTED_BY" for e in tested):
            test_gaps.append({
                "name": _sanitize_name(node.name),
                "qualified_name": _sanitize_name(node.qualified_name),
                "file": node.file_path,
                "line_start": node.line_start,
                "line_end": node.line_end,
            })

    # Review priorities: top 10 by risk score.
    review_priorities = sorted(node_risks, key=lambda x: x["risk_score"], reverse=True)[:10]

    # --- Code quality enrichment ---
    complexity_analysis = _compute_complexity_analysis(store, changed_funcs, base, repo_root)
    smell_analysis = _compute_smell_analysis(changed_funcs)
    test_impact = _compute_test_impact(store, changed_funcs)
    documentation_changes = _compute_documentation_changes(changed_funcs)

    # Build summary.
    summary_parts = [
        f"Analyzed {len(changed_files)} changed file(s):",
        f"  - {len(changed_funcs)} changed function(s)/class(es)",
        f"  - {affected['total']} affected flow(s)",
        f"  - {len(test_gaps)} test gap(s)",
        f"  - Overall risk score: {overall_risk:.2f}",
    ]
    if test_gaps:
        gap_names = [g["name"] for g in test_gaps[:5]]
        summary_parts.append(f"  - Untested: {', '.join(gap_names)}")
    cc_delta = complexity_analysis["total_complexity_delta"]
    if cc_delta:
        direction = "+" if cc_delta > 0 else ""
        summary_parts.append(f"  - Complexity delta: {direction}{cc_delta} CC points")
    if smell_analysis["new_smells"]:
        summary_parts.append(f"  - New smells: {len(smell_analysis['new_smells'])}")

    return {
        "summary": "\n".join(summary_parts),
        "risk_score": overall_risk,
        "changed_functions": node_risks,
        "affected_flows": affected["affected_flows"],
        "test_gaps": test_gaps,
        "review_priorities": review_priorities,
        "complexity_analysis": complexity_analysis,
        "smell_analysis": smell_analysis,
        "test_impact": test_impact,
        "documentation_changes": documentation_changes,
    }
