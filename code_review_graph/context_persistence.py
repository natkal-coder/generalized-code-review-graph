"""Persistence for context-graph: save/load to SQLite context.db.

Enables session continuity: context learned in one session can be restored.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

from .agent_detect import AgentInfo
from .context_config import ContextConfig
from .context_graph import ContextGraph
from .context_node import AccessLog, ContextNode

logger = logging.getLogger(__name__)

# SQLite schema for context database
CONTEXT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS context_nodes (
    qualified_name TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    token_estimate INTEGER NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    frequency_score REAL NOT NULL DEFAULT 0.0,
    last_accessed REAL NOT NULL,
    first_accessed REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS access_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qualified_name TEXT NOT NULL,
    timestamp REAL NOT NULL,
    tool_name TEXT NOT NULL,
    query_context TEXT,
    FOREIGN KEY (qualified_name) REFERENCES context_nodes(qualified_name)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_access_logs_qualified
    ON access_logs(qualified_name);
CREATE INDEX IF NOT EXISTS idx_access_logs_timestamp
    ON access_logs(timestamp DESC);
"""


def save_context(graph: ContextGraph, db_path: str | Path) -> None:
    """Save context-graph to SQLite database.

    Args:
        graph: ContextGraph instance to persist
        db_path: Path to context.db file

    Raises:
        IOError: If database write fails
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(CONTEXT_SCHEMA_SQL)

        # Get all nodes under lock
        nodes = list(graph._store.values())

        # Persist nodes
        for node in nodes:
            conn.execute(
                """
                INSERT OR REPLACE INTO context_nodes
                (qualified_name, kind, token_estimate, access_count,
                 frequency_score, last_accessed, first_accessed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.qualified_name,
                    node.kind,
                    node.token_estimate,
                    node.access_count,
                    node.frequency_score,
                    node.last_accessed,
                    node.first_accessed,
                ),
            )

            # Persist access logs (keep only last 100 per node)
            if node.access_log:
                # Delete old access logs for this node
                conn.execute(
                    "DELETE FROM access_logs WHERE qualified_name = ?",
                    (node.qualified_name,),
                )

                # Insert recent logs (last 100)
                for log in node.access_log[-100:]:
                    conn.execute(
                        """
                        INSERT INTO access_logs
                        (qualified_name, timestamp, tool_name, query_context)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            node.qualified_name,
                            log.timestamp,
                            log.tool_name,
                            log.query_context,
                        ),
                    )

        conn.commit()
        conn.close()
        logger.info("ContextGraph persisted to %s (%d nodes)", db_path, len(nodes))
    except sqlite3.Error as e:
        logger.error("Failed to persist context-graph: %s", e)
        raise IOError(f"Context persistence failed: {e}") from e


def load_context(
    db_path: str | Path, config: ContextConfig, agent: AgentInfo
) -> ContextGraph:
    """Load context-graph from SQLite database or create fresh if not found.

    Args:
        db_path: Path to context.db file
        config: ContextConfig for new graph
        agent: AgentInfo for new graph

    Returns:
        ContextGraph loaded from disk or newly initialized
    """
    db_path = Path(db_path)
    graph = ContextGraph(config, agent)

    if not db_path.exists():
        logger.info("No context.db found; starting with fresh context-graph")
        return graph

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row

        # Load nodes
        rows = conn.execute(
            "SELECT * FROM context_nodes ORDER BY last_accessed DESC"
        ).fetchall()

        for row in rows:
            qualified_name = row["qualified_name"]
            ctx_node = ContextNode(
                qualified_name=qualified_name,
                kind=row["kind"],
                token_estimate=row["token_estimate"],
                access_count=row["access_count"],
                frequency_score=row["frequency_score"],
                last_accessed=row["last_accessed"],
                first_accessed=row["first_accessed"],
            )

            # Load access logs for this node
            log_rows = conn.execute(
                "SELECT timestamp, tool_name, query_context FROM access_logs "
                "WHERE qualified_name = ? ORDER BY timestamp DESC LIMIT 2",
                (qualified_name,),
            ).fetchall()

            for log_row in log_rows:
                log = AccessLog(
                    timestamp=log_row["timestamp"],
                    tool_name=log_row["tool_name"],
                    query_context=log_row["query_context"],
                )
                ctx_node.access_log.append(log)

            # Add to graph
            graph._store[qualified_name] = ctx_node
            graph._current_token_usage += ctx_node.token_estimate

        conn.close()
        logger.info(
            "ContextGraph loaded from %s (%d nodes, %d tokens)",
            db_path,
            len(graph._store),
            graph._current_token_usage,
        )
    except sqlite3.Error as e:
        logger.warning("Failed to load context-graph: %s; starting fresh", e)
        # Return fresh graph on load failure

    return graph


def clear_context(db_path: str | Path) -> None:
    """Clear context database.

    Args:
        db_path: Path to context.db file
    """
    db_path = Path(db_path)
    if db_path.exists():
        try:
            db_path.unlink()
            logger.info("Context database cleared: %s", db_path)
        except OSError as e:
            logger.error("Failed to clear context database: %s", e)
            raise
