"""MCP tools for context-graph management and visibility.

Exposes context status, active nodes, and cache control.
"""

from __future__ import annotations

from typing import Any

from ..context_graph import ContextGraph


def get_context_summary(context_graph: ContextGraph | None) -> dict[str, Any]:
    """Get context-graph summary stats.

    Available as MCP tool: `get_context_summary`

    Args:
        context_graph: ContextGraph instance or None if disabled

    Returns:
        Dict with context-graph statistics
    """
    if context_graph is None:
        return {
            "enabled": False,
            "message": "Context-graph not initialized or disabled",
        }

    return {
        "enabled": True,
        **context_graph.summary(),
    }


def get_active_context(context_graph: ContextGraph | None) -> dict[str, Any]:
    """Get top N active context nodes sorted by relevance.

    Available as MCP tool: `get_active_context`

    Args:
        context_graph: ContextGraph instance or None if disabled

    Returns:
        Dict with active nodes list
    """
    if context_graph is None:
        return {
            "enabled": False,
            "message": "Context-graph not initialized or disabled",
        }

    active = context_graph.active_context()
    return {
        "enabled": True,
        "count": len(active),
        "nodes": [
            {
                "qualified_name": node.qualified_name,
                "kind": node.kind,
                "access_count": node.access_count,
                "frequency_score": round(node.frequency_score, 3),
                "time_since_access_seconds": node.time_since_access(),
                "token_estimate": node.token_estimate,
            }
            for node in active
        ],
    }


def clear_context(context_graph: ContextGraph | None) -> dict[str, Any]:
    """Clear all nodes from context-graph.

    Available as MCP tool: `clear_context`

    Args:
        context_graph: ContextGraph instance or None if disabled

    Returns:
        Dict with result
    """
    if context_graph is None:
        return {
            "enabled": False,
            "message": "Context-graph not initialized or disabled",
        }

    summary_before = context_graph.summary()
    context_graph.clear()
    return {
        "enabled": True,
        "cleared": True,
        "nodes_removed": summary_before["nodes_count"],
        "tokens_freed": summary_before["total_tokens"],
        "message": f"Cleared {summary_before['nodes_count']} nodes "
        f"({summary_before['total_tokens']} tokens)",
    }
