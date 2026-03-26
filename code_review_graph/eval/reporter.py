"""Markdown report generator for evaluation benchmark results.

Takes a list of benchmark result dicts and produces a formatted markdown table
suitable for inclusion in documentation or CI output.
"""

from __future__ import annotations

from typing import Any


def generate_markdown_report(results: list[dict[str, Any]]) -> str:
    """Generate a markdown report from benchmark results.

    Each result dict should contain at minimum a ``benchmark`` key identifying
    the benchmark name, plus any metric keys (e.g. ``ratio``,
    ``reduction_percent``, ``mrr``, ``precision``, ``recall``, ``f1``).

    Args:
        results: List of result dicts from benchmark runs.

    Returns:
        A markdown string containing a summary table and per-benchmark details.
    """
    if not results:
        return "# Evaluation Report\n\nNo benchmark results to report.\n"

    lines: list[str] = []
    lines.append("# Evaluation Report")
    lines.append("")

    # Collect all metric keys across results (excluding 'benchmark')
    all_keys: list[str] = []
    seen: set[str] = set()
    for r in results:
        for k in r:
            if k != "benchmark" and k not in seen:
                all_keys.append(k)
                seen.add(k)

    # Summary table
    lines.append("## Summary")
    lines.append("")

    header = "| Benchmark | " + " | ".join(all_keys) + " |"
    separator = "| --- | " + " | ".join("---" for _ in all_keys) + " |"
    lines.append(header)
    lines.append(separator)

    for r in results:
        name = r.get("benchmark", "unknown")
        values = [str(r.get(k, "-")) for k in all_keys]
        lines.append(f"| {name} | " + " | ".join(values) + " |")

    lines.append("")

    # Per-benchmark detail sections
    lines.append("## Details")
    lines.append("")
    for r in results:
        name = r.get("benchmark", "unknown")
        lines.append(f"### {name}")
        lines.append("")
        for k in all_keys:
            v = r.get(k, "-")
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    return "\n".join(lines)
