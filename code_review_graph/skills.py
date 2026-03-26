"""Claude Code skills and hooks auto-install.

Generates Claude Code agent skill files, hooks configuration, and
CLAUDE.md integration for seamless code-review-graph usage.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# --- Skill file contents ---

_SKILLS: dict[str, dict[str, str]] = {
    "explore-codebase.md": {
        "name": "Explore Codebase",
        "description": "Navigate and understand codebase structure using the knowledge graph",
        "body": (
            "## Explore Codebase\n\n"
            "Use the code-review-graph MCP tools to explore and understand the codebase.\n\n"
            "### Steps\n\n"
            "1. Run `list_graph_stats` to see overall codebase metrics.\n"
            "2. Run `get_architecture_overview` for high-level community structure.\n"
            "3. Use `list_communities` to find major modules, then `get_community` "
            "for details.\n"
            "4. Use `semantic_search_nodes` to find specific functions or classes.\n"
            "5. Use `query_graph` with patterns like `callers_of`, `callees_of`, "
            "`imports_of` to trace relationships.\n"
            "6. Use `list_flows` and `get_flow` to understand execution paths.\n\n"
            "### Tips\n\n"
            "- Start broad (stats, architecture) then narrow down to specific areas.\n"
            "- Use `children_of` on a file to see all its functions and classes.\n"
            "- Use `find_large_functions` to identify complex code."
        ),
    },
    "review-changes.md": {
        "name": "Review Changes",
        "description": "Perform a structured code review using change detection and impact",
        "body": (
            "## Review Changes\n\n"
            "Perform a thorough, risk-aware code review using the knowledge graph.\n\n"
            "### Steps\n\n"
            "1. Run `detect_changes` to get risk-scored change analysis.\n"
            "2. Run `get_affected_flows` to find impacted execution paths.\n"
            "3. For each high-risk function, run `query_graph` with "
            "pattern=\"tests_for\" to check test coverage.\n"
            "4. Run `get_impact_radius` to understand the blast radius.\n"
            "5. For any untested changes, suggest specific test cases.\n\n"
            "### Output Format\n\n"
            "Provide findings grouped by risk level (high/medium/low) with:\n"
            "- What changed and why it matters\n"
            "- Test coverage status\n"
            "- Suggested improvements\n"
            "- Overall merge recommendation"
        ),
    },
    "debug-issue.md": {
        "name": "Debug Issue",
        "description": "Systematically debug issues using graph-powered code navigation",
        "body": (
            "## Debug Issue\n\n"
            "Use the knowledge graph to systematically trace and debug issues.\n\n"
            "### Steps\n\n"
            "1. Use `semantic_search_nodes` to find code related to the issue.\n"
            "2. Use `query_graph` with `callers_of` and `callees_of` to trace "
            "call chains.\n"
            "3. Use `get_flow` to see full execution paths through suspected areas.\n"
            "4. Run `detect_changes` to check if recent changes caused the issue.\n"
            "5. Use `get_impact_radius` on suspected files to see what else is affected.\n\n"
            "### Tips\n\n"
            "- Check both callers and callees to understand the full context.\n"
            "- Look at affected flows to find the entry point that triggers the bug.\n"
            "- Recent changes are the most common source of new issues."
        ),
    },
    "refactor-safely.md": {
        "name": "Refactor Safely",
        "description": "Plan and execute safe refactoring using dependency analysis",
        "body": (
            "## Refactor Safely\n\n"
            "Use the knowledge graph to plan and execute refactoring with confidence.\n\n"
            "### Steps\n\n"
            "1. Use `refactor_tool` with mode=\"suggest\" for community-driven "
            "refactoring suggestions.\n"
            "2. Use `refactor_tool` with mode=\"dead_code\" to find unreferenced code.\n"
            "3. For renames, use `refactor_tool` with mode=\"rename\" to preview all "
            "affected locations.\n"
            "4. Use `apply_refactor_tool` with the refactor_id to apply renames.\n"
            "5. After changes, run `detect_changes` to verify the refactoring impact.\n\n"
            "### Safety Checks\n\n"
            "- Always preview before applying (rename mode gives you an edit list).\n"
            "- Check `get_impact_radius` before major refactors.\n"
            "- Use `get_affected_flows` to ensure no critical paths are broken.\n"
            "- Run `find_large_functions` to identify decomposition targets."
        ),
    },
}


def generate_skills(repo_root: Path, skills_dir: Path | None = None) -> Path:
    """Generate Claude Code skill files.

    Creates `.claude/skills/` directory with 4 skill markdown files,
    each containing frontmatter and instructions.

    Args:
        repo_root: Repository root directory.
        skills_dir: Custom skills directory. Defaults to repo_root/.claude/skills.

    Returns:
        Path to the skills directory.
    """
    if skills_dir is None:
        skills_dir = repo_root / ".claude" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    for filename, skill in _SKILLS.items():
        path = skills_dir / filename
        content = (
            "---\n"
            f"name: {skill['name']}\n"
            f"description: {skill['description']}\n"
            "---\n\n"
            f"{skill['body']}\n"
        )
        path.write_text(content)
        logger.info("Wrote skill: %s", path)

    return skills_dir


def generate_hooks_config() -> dict[str, Any]:
    """Generate Claude Code hooks configuration.

    Returns a hooks config dict with PostToolUse, SessionStart, and
    PreCommit hooks for automatic graph updates.

    Returns:
        Dict with hooks configuration suitable for .claude/settings.json.
    """
    return {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Edit|Write|Bash",
                    "command": "code-review-graph update --quiet",
                    "timeout": 5000,
                },
            ],
            "SessionStart": [
                {
                    "command": "code-review-graph status --json",
                    "timeout": 3000,
                },
            ],
            "PreCommit": [
                {
                    "command": "code-review-graph detect-changes --brief",
                    "timeout": 10000,
                },
            ],
        }
    }


def install_hooks(repo_root: Path) -> None:
    """Write hooks config to .claude/settings.json.

    Merges with existing settings if present, preserving non-hook
    configuration.

    Args:
        repo_root: Repository root directory.
    """
    settings_dir = repo_root / ".claude"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings_path = settings_dir / "settings.json"

    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read existing %s: %s", settings_path, exc)

    hooks_config = generate_hooks_config()
    existing.update(hooks_config)

    settings_path.write_text(json.dumps(existing, indent=2) + "\n")
    logger.info("Wrote hooks config: %s", settings_path)


_CLAUDE_MD_SECTION_MARKER = "<!-- code-review-graph MCP tools -->"

_CLAUDE_MD_SECTION = f"""{_CLAUDE_MD_SECTION_MARKER}
## MCP Tools: code-review-graph

This project uses **code-review-graph** for structural code analysis via MCP.

### Available Tools

| Tool | Description |
|------|-------------|
| `build_or_update_graph` | Build or incrementally update the knowledge graph |
| `detect_changes` | Risk-scored change impact analysis for code review |
| `get_impact_radius` | Blast radius from changed files |
| `get_review_context` | Focused review context with source snippets |
| `get_affected_flows` | Find execution flows affected by changes |
| `query_graph` | Predefined graph queries (callers, callees, imports, tests) |
| `semantic_search_nodes` | Search by name or semantic similarity |
| `list_flows` / `get_flow` | Explore execution flows |
| `list_communities` / `get_community` | Explore code communities |
| `get_architecture_overview` | High-level architecture from communities |
| `find_large_functions` | Find oversized functions/classes |
| `refactor_tool` / `apply_refactor_tool` | Graph-powered refactoring |
| `list_graph_stats` | Codebase metrics |
| `embed_graph` | Compute vector embeddings for semantic search |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern=\"tests_for\" to check coverage.
"""


def inject_claude_md(repo_root: Path) -> None:
    """Append MCP tools section to CLAUDE.md.

    Idempotent: checks if the section marker is already present
    before appending.

    Args:
        repo_root: Repository root directory.
    """
    claude_md_path = repo_root / "CLAUDE.md"

    existing = ""
    if claude_md_path.exists():
        existing = claude_md_path.read_text()

    if _CLAUDE_MD_SECTION_MARKER in existing:
        logger.info("CLAUDE.md already contains MCP tools section, skipping.")
        return

    separator = "\n" if existing and not existing.endswith("\n") else ""
    extra_newline = "\n" if existing else ""
    claude_md_path.write_text(existing + separator + extra_newline + _CLAUDE_MD_SECTION)
    logger.info("Appended MCP tools section to %s", claude_md_path)
