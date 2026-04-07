"""CLI entry point for code-review-graph.

Usage:
    code-review-graph install
    code-review-graph init
    code-review-graph build [--base BASE]
    code-review-graph update [--base BASE]
    code-review-graph watch
    code-review-graph status
    code-review-graph serve
    code-review-graph visualize
    code-review-graph wiki
    code-review-graph detect-changes [--base BASE] [--brief]
    code-review-graph register <path> [--alias name]
    code-review-graph unregister <path_or_alias>
    code-review-graph repos
    code-review-graph health [--json]
"""

from __future__ import annotations

import sys

# Python version check — must come before any other imports
if sys.version_info < (3, 10):
    print("code-review-graph requires Python 3.10 or higher.")
    print(f"  You are running Python {sys.version}")
    print()
    print("Install Python 3.10+: https://www.python.org/downloads/")
    sys.exit(1)

import argparse
import json
import logging
import os
from importlib.metadata import version as pkg_version
from pathlib import Path


def _get_version() -> str:
    """Get the installed package version."""
    try:
        return pkg_version("code-review-graph")
    except Exception:
        return "dev"


def _supports_color() -> bool:
    """Check if the terminal likely supports ANSI colors."""
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


def _print_banner() -> None:
    """Print the startup banner with graph art and available commands."""
    color = _supports_color()
    version = _get_version()

    # ANSI escape codes
    c = "\033[36m" if color else ""   # cyan — graph art
    y = "\033[33m" if color else ""   # yellow — center node
    b = "\033[1m" if color else ""    # bold
    d = "\033[2m" if color else ""    # dim
    g = "\033[32m" if color else ""   # green — commands
    r = "\033[0m" if color else ""    # reset

    print(f"""
{c}  ●──●──●{r}
{c}  │╲ │ ╱│{r}       {b}code-review-graph{r}  {d}v{version}{r}
{c}  ●──{y}◆{c}──●{r}
{c}  │╱ │ ╲│{r}       {d}Structural knowledge graph for{r}
{c}  ●──●──●{r}       {d}smarter code reviews{r}

  {b}Commands:{r}
    {g}install{r}     Set up MCP server for AI coding platforms
    {g}init{r}        Alias for install
    {g}build{r}       Full graph build {d}(parse all files){r}
    {g}update{r}      Incremental update {d}(changed files only){r}
    {g}watch{r}       Auto-update on file changes
    {g}status{r}      Show graph statistics
    {g}visualize{r}   Generate interactive HTML graph
    {g}wiki{r}        Generate markdown wiki from communities
    {g}detect-changes{r} Analyze change impact {d}(risk-scored review){r}
    {g}register{r}    Register a repository in the multi-repo registry
    {g}unregister{r}  Remove a repository from the registry
    {g}repos{r}       List registered repositories
    {g}eval{r}        Run evaluation benchmarks
    {g}health{r}      Code quality health report
    {g}serve{r}       Start MCP server

  {d}Run{r} {b}code-review-graph <command> --help{r} {d}for details{r}
""")


def _handle_init(args: argparse.Namespace) -> None:
    """Set up MCP config for detected AI coding platforms."""
    from .incremental import find_repo_root
    from .skills import install_platform_configs

    repo_root = Path(args.repo) if args.repo else find_repo_root()
    if not repo_root:
        repo_root = Path.cwd()

    dry_run = getattr(args, "dry_run", False)
    target = getattr(args, "platform", "all") or "all"
    if target == "claude-code":
        target = "claude"

    print("Installing MCP server config...")
    configured = install_platform_configs(repo_root, target=target, dry_run=dry_run)

    if not configured:
        print("No platforms detected.")
    else:
        print(f"\nConfigured {len(configured)} platform(s): {', '.join(configured)}")

    if dry_run:
        print("\n[dry-run] No files were modified.")
        return

    # Skills and hooks are installed by default so Claude actually uses the
    # graph tools proactively.  Use --no-skills / --no-hooks to opt out.
    skip_skills = getattr(args, "no_skills", False)
    skip_hooks = getattr(args, "no_hooks", False)
    # Legacy: --skills/--hooks/--all still accepted (no-op, everything is default)

    from .skills import (
        generate_skills,
        inject_claude_md,
        inject_platform_instructions,
        install_hooks,
    )

    if not skip_skills:
        skills_dir = generate_skills(repo_root)
        print(f"Generated skills in {skills_dir}")
        inject_claude_md(repo_root)
        updated = inject_platform_instructions(repo_root)
        if updated:
            print(f"Injected graph instructions into: {', '.join(updated)}")

    if not skip_hooks:
        install_hooks(repo_root)
        print(f"Installed hooks in {repo_root / '.claude' / 'settings.json'}")

    print()
    print("Next steps:")
    print("  1. code-review-graph build    # build the knowledge graph")
    print("  2. Restart your AI coding tool to pick up the new config")



def _handle_health(args: argparse.Namespace) -> None:
    """Query the graph DB and print a code quality health report."""
    import sqlite3

    from .incremental import find_project_root, get_db_path

    repo_root_arg = getattr(args, "repo", None)
    from pathlib import Path as _Path
    repo_root = _Path(repo_root_arg) if repo_root_arg else find_project_root()
    db_path = get_db_path(repo_root)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # ---- documentation coverage ----
    total_fns_row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM nodes WHERE kind = 'Function'"
    ).fetchone()
    total_fns: int = total_fns_row["cnt"] if total_fns_row else 0

    documented_row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM nodes WHERE kind = 'Function' AND has_docstring = 1"
    ).fetchone()
    documented: int = documented_row["cnt"] if documented_row else 0

    undoc_complex_rows = conn.execute(
        """SELECT file_path, name, complexity_score
           FROM nodes
           WHERE kind = 'Function'
             AND (has_docstring = 0 OR has_docstring IS NULL)
             AND complexity_score IS NOT NULL
           ORDER BY complexity_score DESC
           LIMIT 10"""
    ).fetchall()
    undoc_complex = [dict(r) for r in undoc_complex_rows]

    # ---- complexity ----
    high_cc_rows = conn.execute(
        """SELECT file_path, name, complexity_score, param_count
           FROM nodes
           WHERE kind = 'Function' AND complexity_score > 10
           ORDER BY complexity_score DESC
           LIMIT 50"""
    ).fetchall()
    high_cc = [dict(r) for r in high_cc_rows]

    avg_cc_row = conn.execute(
        "SELECT AVG(complexity_score) AS avg_cc FROM nodes "
        "WHERE kind = 'Function' AND complexity_score IS NOT NULL"
    ).fetchone()
    avg_cc: float = round(avg_cc_row["avg_cc"] or 0.0, 1)

    top10_cc_rows = conn.execute(
        """SELECT file_path, name, complexity_score
           FROM nodes
           WHERE kind = 'Function' AND complexity_score IS NOT NULL
           ORDER BY complexity_score DESC
           LIMIT 10"""
    ).fetchall()
    top10_cc = [dict(r) for r in top10_cc_rows]

    # ---- code smells ----
    # God objects: classes with many direct function children
    god_objects_rows = conn.execute(
        """SELECT parent_name, file_path, COUNT(*) AS method_count
           FROM nodes
           WHERE kind = 'Function' AND parent_name IS NOT NULL AND parent_name != ''
           GROUP BY parent_name, file_path
           HAVING COUNT(*) >= 20
           ORDER BY method_count DESC"""
    ).fetchall()
    god_objects = [dict(r) for r in god_objects_rows]

    # Long parameter lists: param_count > 5
    long_params_rows = conn.execute(
        """SELECT file_path, name, param_count, complexity_score
           FROM nodes
           WHERE kind = 'Function' AND param_count > 5
           ORDER BY param_count DESC
           LIMIT 20"""
    ).fetchall()
    long_params = [dict(r) for r in long_params_rows]

    # Deep nesting: nesting_depth > 4
    deep_nesting_rows = conn.execute(
        """SELECT file_path, name, nesting_depth
           FROM nodes
           WHERE kind = 'Function' AND nesting_depth > 4
           ORDER BY nesting_depth DESC
           LIMIT 20"""
    ).fetchall()
    deep_nesting = [dict(r) for r in deep_nesting_rows]

    # Silent catches approximated via node annotations
    silent_catch_rows = conn.execute(
        """SELECT n.file_path, n.name
           FROM node_annotations na
           JOIN nodes n ON n.id = na.node_id
           WHERE na.category = 'smell' AND na.tag = 'silent_catch'"""
    ).fetchall() if _table_exists_h(conn, "node_annotations") else []
    silent_catches = [dict(r) for r in silent_catch_rows]

    # Unused imports via annotations
    unused_import_rows = conn.execute(
        """SELECT n.file_path, n.name
           FROM node_annotations na
           JOIN nodes n ON n.id = na.node_id
           WHERE na.category = 'smell' AND na.tag = 'unused_import'"""
    ).fetchall() if _table_exists_h(conn, "node_annotations") else []
    unused_imports = [dict(r) for r in unused_import_rows]

    conn.close()

    # ---- top issues ----
    top_issues: list[dict] = []
    for row in high_cc[:10]:
        fp = row["file_path"] or ""
        fn = row["name"] or ""
        cc = row["complexity_score"]
        pc = row.get("param_count")
        label = f"{fp}:{fn} - CC:{int(cc)}"
        if pc and pc > 5:
            label += f", {pc} params"
        if any(r["parent_name"] == fn for r in god_objects):
            label += ", god_object"
        top_issues.append({"location": f"{fp}:{fn}", "cc": cc, "param_count": pc, "label": label})

    total_smells = (
        len(god_objects) + len(long_params) + len(deep_nesting)
        + len(silent_catches) + len(unused_imports)
    )
    doc_gap_pct = round((1 - documented / total_fns) * 100, 1) if total_fns else 0.0
    doc_pct = round(documented / total_fns * 100, 1) if total_fns else 0.0

    payload: dict = {
        "documentation": {
            "total_functions": total_fns,
            "documented": documented,
            "documented_pct": doc_pct,
            "documentation_gap_pct": doc_gap_pct,
            "undocumented_high_complexity": undoc_complex,
        },
        "complexity": {
            "functions_cc_above_10": len(high_cc),
            "avg_cyclomatic_complexity": avg_cc,
            "top10_most_complex": top10_cc,
        },
        "smells": {
            "god_objects": god_objects,
            "long_parameter_lists": long_params,
            "deep_nesting": deep_nesting,
            "silent_catches": silent_catches,
            "unused_imports": unused_imports,
            "total": total_smells,
        },
        "top_issues": top_issues,
    }

    use_json = getattr(args, "json", False)
    if use_json:
        import json as _json
        print(_json.dumps(payload, indent=2, default=str))
        return

    color = _supports_color()
    b = "\033[1m" if color else ""
    r = "\033[0m" if color else ""
    y = "\033[33m" if color else ""
    g = "\033[32m" if color else ""
    red = "\033[31m" if color else ""

    def hdr(title: str) -> str:
        return f"\n{b}{title}{r}"

    def sep() -> str:
        return "=" * 40

    print(f"\n{b}CODE QUALITY HEALTH REPORT{r}")
    print(sep())

    # Documentation
    print(hdr("Documentation Coverage"))
    doc_color = g if doc_pct >= 80 else y if doc_pct >= 50 else red
    doc_line = (
        f"  Documented: {doc_color}{documented} / {total_fns}{r}"
        f" functions ({doc_color}{doc_pct}%{r})"
    )
    print(doc_line)
    print(f"  Undocumented high-complexity: {len(undoc_complex)} functions")
    print(f"  Documentation gap: {doc_gap_pct}%")

    # Complexity
    print(hdr("Code Complexity"))
    cc_color = g if len(high_cc) == 0 else y if len(high_cc) < 10 else red
    print(f"  Functions with complexity > 10: {cc_color}{len(high_cc)}{r}")
    print(f"  Avg cyclomatic complexity: {avg_cc}")
    if top10_cc:
        highest = top10_cc[0]
        fp = highest["file_path"] or ""
        fn = highest["name"] or ""
        cc_val = int(highest["complexity_score"] or 0)
        print(f"  Highest complexity: {fp}:{fn}() (CC={cc_val})")

    # Smells
    print(hdr("Code Smells Detected"))
    print(f"  God objects (>=20 methods): {len(god_objects)}")
    print(f"  Long parameter lists (>5 params): {len(long_params)}")
    print(f"  Deep nesting (>4): {len(deep_nesting)}")
    print(f"  Silent catch blocks: {len(silent_catches)}")
    print(f"  Unused imports: {len(unused_imports)}")
    smell_color = g if total_smells == 0 else y if total_smells < 10 else red
    print(f"  Total smells: {smell_color}{total_smells}{r}")

    # Top 10 most complex
    if top10_cc:
        print(hdr("Top 10 Most Complex Functions"))
        for i, row in enumerate(top10_cc, 1):
            fp = row["file_path"] or ""
            fn = row["name"] or ""
            cc_val = int(row["complexity_score"] or 0)
            print(f"  {i:2}. {fp}:{fn}() - CC:{cc_val}")

    # Top issues
    if top_issues:
        print(hdr("Top Issues to Fix"))
        for i, issue in enumerate(top_issues[:10], 1):
            print(f"  {i:2}. {issue['label']}")

    print()


def _table_exists_h(conn: object, table: str) -> bool:
    """Check whether a table exists (used inside _handle_health)."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None

def main() -> None:
    """Main CLI entry point."""
    ap = argparse.ArgumentParser(
        prog="code-review-graph",
        description="Persistent incremental knowledge graph for code reviews",
    )
    ap.add_argument(
        "-v", "--version", action="store_true", help="Show version and exit"
    )
    sub = ap.add_subparsers(dest="command")

    # install (primary) + init (alias)
    install_cmd = sub.add_parser(
        "install", help="Register MCP server with AI coding platforms"
    )
    install_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")
    install_cmd.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without writing files",
    )
    install_cmd.add_argument(
        "--no-skills", action="store_true",
        help="Skip generating Claude Code skill files",
    )
    install_cmd.add_argument(
        "--no-hooks", action="store_true",
        help="Skip installing Claude Code hooks",
    )
    # Legacy flags (kept for backwards compat, now no-ops since all is default)
    install_cmd.add_argument("--skills", action="store_true", help=argparse.SUPPRESS)
    install_cmd.add_argument("--hooks", action="store_true", help=argparse.SUPPRESS)
    install_cmd.add_argument("--all", action="store_true", dest="install_all",
                             help=argparse.SUPPRESS)
    install_cmd.add_argument(
        "--platform",
        choices=[
            "claude", "claude-code", "cursor", "windsurf", "zed",
            "continue", "opencode", "gemini-cli", "antigravity", "all",
        ],
        default="all",
        help="Target platform for MCP config (default: all detected)",
    )

    init_cmd = sub.add_parser(
        "init", help="Alias for install"
    )
    init_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")
    init_cmd.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without writing files",
    )
    init_cmd.add_argument(
        "--no-skills", action="store_true",
        help="Skip generating Claude Code skill files",
    )
    init_cmd.add_argument(
        "--no-hooks", action="store_true",
        help="Skip installing Claude Code hooks",
    )
    init_cmd.add_argument("--skills", action="store_true", help=argparse.SUPPRESS)
    init_cmd.add_argument("--hooks", action="store_true", help=argparse.SUPPRESS)
    init_cmd.add_argument("--all", action="store_true", dest="install_all",
                             help=argparse.SUPPRESS)
    init_cmd.add_argument(
        "--platform",
        choices=[
            "claude", "claude-code", "cursor", "windsurf", "zed",
            "continue", "opencode", "antigravity", "all",
        ],
        default="all",
        help="Target platform for MCP config (default: all detected)",
    )

    # build
    build_cmd = sub.add_parser("build", help="Full graph build (re-parse all files)")
    build_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")

    # update
    update_cmd = sub.add_parser("update", help="Incremental update (only changed files)")
    update_cmd.add_argument("--base", default="HEAD~1", help="Git diff base (default: HEAD~1)")
    update_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")
    update_cmd.add_argument("--quiet", action="store_true", help="Suppress output")

    # watch
    watch_cmd = sub.add_parser("watch", help="Watch for changes and auto-update")
    watch_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")

    # status
    status_cmd = sub.add_parser("status", help="Show graph statistics")
    status_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")

    # visualize
    vis_cmd = sub.add_parser("visualize", help="Generate interactive HTML graph visualization")
    vis_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")
    vis_cmd.add_argument(
        "--serve", action="store_true",
        help="Start a local HTTP server to view the visualization (localhost:8765)",
    )

    # wiki
    wiki_cmd = sub.add_parser("wiki", help="Generate markdown wiki from community structure")
    wiki_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")
    wiki_cmd.add_argument(
        "--force", action="store_true",
        help="Regenerate all pages even if content unchanged",
    )

    # register
    register_cmd = sub.add_parser(
        "register", help="Register a repository in the multi-repo registry"
    )
    register_cmd.add_argument("path", help="Path to the repository root")
    register_cmd.add_argument("--alias", default=None, help="Short alias for the repository")

    # unregister
    unregister_cmd = sub.add_parser(
        "unregister", help="Remove a repository from the multi-repo registry"
    )
    unregister_cmd.add_argument("path_or_alias", help="Repository path or alias to remove")

    # repos
    sub.add_parser("repos", help="List registered repositories")

    # eval
    eval_cmd = sub.add_parser("eval", help="Run evaluation benchmarks")
    eval_cmd.add_argument(
        "--benchmark", default=None,
        help="Comma-separated benchmarks to run (token_efficiency, impact_accuracy, "
             "flow_completeness, search_quality, build_performance)",
    )
    eval_cmd.add_argument("--repo", default=None, help="Comma-separated repo config names")
    eval_cmd.add_argument("--all", action="store_true", dest="run_all", help="Run all benchmarks")
    eval_cmd.add_argument("--report", action="store_true", help="Generate report from results")
    eval_cmd.add_argument("--output-dir", default=None, help="Output directory for results")

    # detect-changes
    detect_cmd = sub.add_parser("detect-changes", help="Analyze change impact")
    detect_cmd.add_argument(
        "--base", default="HEAD~1", help="Git diff base (default: HEAD~1)"
    )
    detect_cmd.add_argument(
        "--brief", action="store_true", help="Show brief summary only"
    )
    detect_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")

    # serve
    serve_cmd = sub.add_parser("serve", help="Start MCP server (stdio transport)")
    serve_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")

    # health
    health_cmd = sub.add_parser("health", help="Code quality health report")
    health_cmd.add_argument("--repo", default=None, help="Repository root (auto-detected)")
    health_cmd.add_argument(
        "--json", action="store_true", dest="json",
        help="Output as machine-readable JSON",
    )

    args = ap.parse_args()

    if args.version:
        print(f"code-review-graph {_get_version()}")
        return

    if not args.command:
        _print_banner()
        return

    if args.command == "serve":
        from .main import main as serve_main
        serve_main(repo_root=args.repo)
        return

    if args.command == "health":
        _handle_health(args)
        return

    if args.command == "eval":
        from .eval.reporter import generate_full_report, generate_readme_tables
        from .eval.runner import run_eval

        if getattr(args, "report", False):
            output_dir = Path(
                getattr(args, "output_dir", None) or "evaluate/results"
            )
            report = generate_full_report(output_dir)
            report_path = Path("evaluate/reports/summary.md")
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8")
            print(f"Report written to {report_path}")

            tables = generate_readme_tables(output_dir)
            print("\n--- README Tables (copy-paste) ---\n")
            print(tables)
        else:
            repos = (
                [r.strip() for r in args.repo.split(",")]
                if getattr(args, "repo", None)
                else None
            )
            benchmarks = (
                [b.strip() for b in args.benchmark.split(",")]
                if getattr(args, "benchmark", None)
                else None
            )

            if not repos and not benchmarks and not getattr(args, "run_all", False):
                print("Specify --all, --repo, or --benchmark. See --help.")
                return

            results = run_eval(
                repos=repos,
                benchmarks=benchmarks,
                output_dir=getattr(args, "output_dir", None),
            )
            print(f"\nCompleted {len(results)} benchmark(s).")
            print("Run 'code-review-graph eval --report' to generate tables.")
        return

    if args.command in ("init", "install"):
        _handle_init(args)
        return

    if args.command in ("register", "unregister", "repos"):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
        from .registry import Registry

        registry = Registry()
        if args.command == "register":
            try:
                entry = registry.register(args.path, alias=args.alias)
                alias_info = f" (alias: {entry['alias']})" if entry.get("alias") else ""
                print(f"Registered: {entry['path']}{alias_info}")
            except ValueError as exc:
                logging.error(str(exc))
                sys.exit(1)
        elif args.command == "unregister":
            if registry.unregister(args.path_or_alias):
                print(f"Unregistered: {args.path_or_alias}")
            else:
                print(f"Not found: {args.path_or_alias}")
                sys.exit(1)
        elif args.command == "repos":
            repos = registry.list_repos()
            if not repos:
                print("No repositories registered.")
                print("Use: code-review-graph register <path> [--alias name]")
            else:
                for entry in repos:
                    alias = entry.get("alias", "")
                    alias_str = f"  ({alias})" if alias else ""
                    print(f"  {entry['path']}{alias_str}")
        return

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from .graph import GraphStore
    from .incremental import (
        find_project_root,
        find_repo_root,
        full_build,
        get_db_path,
        incremental_update,
        watch,
    )

    if args.command in ("update", "detect-changes"):
        # update and detect-changes require git for diffing
        repo_root = Path(args.repo) if args.repo else find_repo_root()
        if not repo_root:
            logging.error(
                "Not in a git repository. '%s' requires git for diffing.",
                args.command,
            )
            logging.error("Use 'build' for a full parse, or run 'git init' first.")
            sys.exit(1)
    else:
        repo_root = Path(args.repo) if args.repo else find_project_root()

    db_path = get_db_path(repo_root)
    store = GraphStore(db_path)

    try:
        if args.command == "build":
            result = full_build(repo_root, store)
            print(
                f"Full build: {result['files_parsed']} files, "
                f"{result['total_nodes']} nodes, {result['total_edges']} edges"
            )
            if result["errors"]:
                print(f"Errors: {len(result['errors'])}")

        elif args.command == "update":
            result = incremental_update(repo_root, store, base=args.base)
            if not getattr(args, "quiet", False):
                print(
                    f"Incremental: {result['files_updated']} files updated, "
                    f"{result['total_nodes']} nodes, {result['total_edges']} edges"
                )

        elif args.command == "status":
            stats = store.get_stats()
            print(f"Nodes: {stats.total_nodes}")
            print(f"Edges: {stats.total_edges}")
            print(f"Files: {stats.files_count}")
            print(f"Languages: {', '.join(stats.languages)}")
            print(f"Last updated: {stats.last_updated or 'never'}")
            # Show branch info and warn if stale
            stored_branch = store.get_metadata("git_branch")
            stored_sha = store.get_metadata("git_head_sha")
            if stored_branch:
                print(f"Built on branch: {stored_branch}")
            if stored_sha:
                print(f"Built at commit: {stored_sha[:12]}")
            from .incremental import _git_branch_info
            current_branch, current_sha = _git_branch_info(repo_root)
            if stored_branch and current_branch and stored_branch != current_branch:
                print(
                    f"WARNING: Graph was built on '{stored_branch}' "
                    f"but you are now on '{current_branch}'. "
                    f"Run 'code-review-graph build' to rebuild."
                )

        elif args.command == "watch":
            watch(repo_root, store)

        elif args.command == "visualize":
            from .visualization import generate_html
            html_path = repo_root / ".code-review-graph" / "graph.html"
            generate_html(store, html_path)
            print(f"Visualization: {html_path}")
            if getattr(args, "serve", False):
                import functools
                import http.server

                serve_dir = html_path.parent
                port = 8765
                handler = functools.partial(
                    http.server.SimpleHTTPRequestHandler,
                    directory=str(serve_dir),
                )
                print(f"Serving at http://localhost:{port}/graph.html")
                print("Press Ctrl+C to stop.")
                with http.server.HTTPServer(("localhost", port), handler) as httpd:
                    try:
                        httpd.serve_forever()
                    except KeyboardInterrupt:
                        print("\nServer stopped.")
            else:
                print("Open in browser to explore your codebase graph.")

        elif args.command == "wiki":
            from .wiki import generate_wiki
            wiki_dir = repo_root / ".code-review-graph" / "wiki"
            result = generate_wiki(store, wiki_dir, force=args.force)
            total = result["pages_generated"] + result["pages_updated"] + result["pages_unchanged"]
            print(
                f"Wiki: {result['pages_generated']} new, "
                f"{result['pages_updated']} updated, "
                f"{result['pages_unchanged']} unchanged "
                f"({total} total pages)"
            )
            print(f"Output: {wiki_dir}")

        elif args.command == "detect-changes":
            from .changes import analyze_changes
            from .incremental import get_changed_files, get_staged_and_unstaged

            base = args.base
            changed = get_changed_files(repo_root, base)
            if not changed:
                changed = get_staged_and_unstaged(repo_root)

            if not changed:
                print("No changes detected.")
            else:
                result = analyze_changes(
                    store,
                    changed,
                    repo_root=str(repo_root),
                    base=base,
                )
                if args.brief:
                    print(result.get("summary", "No summary available."))
                else:
                    print(json.dumps(result, indent=2, default=str))

    finally:
        store.close()
