"""Evaluation framework for code-review-graph.

Provides scoring metrics (token efficiency, MRR, precision/recall) and
a markdown report generator for benchmarking graph-based code reviews.
"""

from __future__ import annotations

from .reporter import generate_markdown_report
from .scorer import compute_mrr, compute_precision_recall, compute_token_efficiency

__all__ = [
    "compute_mrr",
    "compute_precision_recall",
    "compute_token_efficiency",
    "generate_markdown_report",
]
