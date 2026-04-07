<h1 align="center">code-review-graph</h1>

<p align="center">
  <strong>AI-powered code review tool that cuts token costs by 8.2x</strong><br>
  Build semantic knowledge graphs of your codebase for smarter AI code reviews
</p>

<p align="center">
  <a href="https://code-review-graph.com"><img src="https://img.shields.io/badge/website-code--review--graph.com-blue?style=flat-square" alt="Website"></a>
  <a href="https://discord.gg/3p58KXqGFN"><img src="https://img.shields.io/badge/discord-join-5865F2?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/tirth8205/code-review-graph/stargazers"><img src="https://img.shields.io/github/stars/tirth8205/code-review-graph?style=flat-square" alt="Stars"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square" alt="MIT Licence"></a>
  <a href="https://github.com/tirth8205/code-review-graph/actions/workflows/ci.yml"><img src="https://github.com/tirth8205/code-review-graph/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg?style=flat-square" alt="Python 3.10+"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-compatible-green.svg?style=flat-square" alt="MCP"></a>
  <a href="#"><img src="https://img.shields.io/badge/version-2.1.0-purple.svg?style=flat-square" alt="v2.1.0"></a>
</p>

<br>

## The Problem

AI coding assistants (Claude Code, Cursor, Gemini CLI) re-read your **entire codebase** on every review, refactor, or debug task. A 10,000-file monorepo = 10,000 files × N tasks = **millions of wasted tokens**.

**code-review-graph solves this** by building a persistent knowledge graph of your code structure, then giving AI assistants only the minimal context they need via MCP (Model Context Protocol).

<p align="center">
  <img src="diagrams/diagram1_before_vs_after.png" alt="Token reduction: 8.2x average savings by reading only affected files instead of entire codebase" width="85%" />
</p>

---

## How It Works (30 seconds)

1. **Parse once** — code-review-graph parses your repo using [Tree-sitter](https://tree-sitter.github.io/tree-sitter/) (19 languages supported)
2. **Build graph** — Stores code structure (functions, classes, imports, calls) in local SQLite
3. **AI gets context** — When you ask for a code review, AI queries the graph instead of reading entire files
4. **Pay less** — AI reads only affected files, parameters, dependencies. Result: **8.2x fewer tokens**

<p align="center">
  <img src="diagrams/diagram2_architecture_pipeline.png" alt="Architecture: Repository → Tree-sitter Parser → SQLite Graph → Blast Radius → Minimal Review Set" width="100%" />
</p>

---

## Quick Start (3 minutes)

### Installation

```bash
pip install code-review-graph
code-review-graph install          # Auto-detects Claude Code, Cursor, Gemini CLI, Windsurf, Zed, etc.
code-review-graph build            # Parse your codebase (takes ~10s for 500 files)
```

### First Review

Open your IDE and ask your AI assistant:

```
Build the code review graph for this project
```

Then:

```
Review my changes and show impact radius
```

The graph will show:
- ✅ Which functions/classes are affected
- ✅ Which tests will break
- ✅ Code complexity of changed code
- ✅ Documentation gaps
- ✅ Code smells introduced

---

## Key Features

### 🎯 **Token Efficiency**
- **8.2x average cost reduction** (benchmarked on 6 real repos)
- Reads only affected files, not entire codebase
- Works with Claude Code, Cursor, Gemini CLI, Windsurf, Zed, Continue, OpenCode, Antigravity

### 🔍 **Intelligent Code Analysis**
| Feature | What It Does |
|---------|-------------|
| **Blast-radius analysis** | Shows exactly which functions/tests are affected by changes |
| **Code complexity metrics** | Cyclomatic complexity, cognitive complexity, nesting depth per function |
| **AI readability layer** | Extracts docstrings, intent tags (TODO/FIXME), documentation gaps |
| **Code smell detection** | Automatically flags God objects, long parameter lists, deep nesting, magic numbers |
| **Execution flow tracing** | Trace call chains from entry points, sorted by criticality |
| **Architecture overview** | Auto-generated codebase maps with coupling analysis |

### 🚀 **Developer Experience**
- **Incremental updates** — Changes sync in <2 seconds via git hooks
- **19 languages** — Python, TypeScript, JavaScript, Go, Rust, Java, C++, C#, Ruby, Kotlin, Swift, PHP, Solidity, Dart, R, Perl, Lua, Vue, Jupyter notebooks
- **Interactive visualization** — D3.js force-directed graph with search
- **Local storage** — SQLite in `.code-review-graph/`. No cloud, no API keys, no SaaS lock-in
- **Multi-repo support** — Register multiple repos, search across all of them

### 🤖 **AI Integration**
- **22 MCP tools** — Direct integration with Claude Code, Cursor, Gemini CLI
- **5 workflow prompts** — Review changes, architecture map, debug issue, onboard developer, pre-merge check
- **Semantic search** — Optional vector embeddings (sentence-transformers, Google Gemini, MiniMax)
- **Risk-scored reviews** — `detect_changes` maps diffs to affected functions, flows, test gaps

---

## Real-World Impact: AI_operating_system Project

Scan of 22 Python files, 147 functions/classes:

| Metric | Value | What It Means |
|--------|-------|---------------|
| **Functions documented** | 89/105 (84.8%) | High quality → fewer surprises |
| **Documentation gaps** | 5 functions | AI knows exactly which functions need docs |
| **Avg complexity** | 3.41 | Low complexity → easy to understand |
| **Hotspot function** | CC=23 | 1 function needs careful review |
| **Deep nesting** | 2 functions | Very few complex control structures |
| **Long param lists** | 3 functions | Minimal design issues |
| **Intent coverage** | 105/105 (100%) | All functions have TODO/FIXME context |

**Result:** AI assistant reviews this 3,000-line project by reading:
- 5 undocumented functions
- 1 high-complexity function
- 3 parameter design issues
- Intent metadata for all 105 functions

**Token savings:** 60-80% context window reduction + better accuracy

---

## Platform Support

### Works With (Auto-configures)

- **Claude Code** — Native integration via MCP
- **Cursor IDE** — Full support with .cursorrules injection
- **Gemini CLI** — First-class integration with auto-detection
- **Windsurf** — MCP server auto-configuration
- **Zed Editor** — LSP-style MCP integration
- **Continue.dev** — Plug-and-play MCP setup
- **OpenCode** — Native support
- **Antigravity** — Standalone MCP server

**One command configures all installed tools:**

```bash
code-review-graph install
```

---

## Installation & Setup

### Requirements
- Python 3.10+
- Git (for change detection)
- Optional: [uv](https://docs.astral.sh/uv/) for faster installation

### Install

```bash
# Via pip (recommended)
pip install code-review-graph

# Via pipx (isolated environment)
pipx install code-review-graph

# Via uv (fastest)
uv pip install code-review-graph
```

### Configure Your AI Tool

```bash
# Auto-detect and configure all installed tools
code-review-graph install

# Or target specific platform
code-review-graph install --platform cursor
code-review-graph install --platform claude-code
code-review-graph install --platform gemini-cli
```

### Build Your First Graph

```bash
code-review-graph build              # Full build (one-time, ~10s per 500 files)
code-review-graph update             # Incremental update on file changes
code-review-graph status             # View graph stats
code-review-graph health             # Code quality report
```

---

## Benchmarks (Real Repositories)

### Token Efficiency

| Repository | Files | Avg Naive Tokens | Graph Tokens | Savings |
|------------|-------|------------------|-------------|---------|
| express.js | 141 | 693 | 983 | 0.7x |
| fastapi | 1,122 | 4,944 | 614 | **8.1x** |
| flask | 83 | 44,751 | 4,252 | **9.1x** |
| gin (Go) | 99 | 21,972 | 1,153 | **16.4x** |
| httpx | 60 | 12,044 | 1,728 | **6.9x** |
| next.js | 2,900+ | 9,882 | 1,249 | **8.0x** |
| **Average** | **2,300+** | — | — | **8.2x** |

> Naive = reading all files. Graph = reading only affected files. Source: `evaluate/reports/summary.md`

### Impact Analysis Accuracy

| Repo | Recall | Precision | F1 Score |
|------|--------|-----------|----------|
| express | 1.0 | 0.50 | 0.667 |
| fastapi | 1.0 | 0.42 | 0.584 |
| flask | 1.0 | 0.34 | 0.475 |
| gin | 1.0 | 0.29 | 0.429 |
| httpx | 1.0 | 0.63 | 0.762 |
| next.js | 1.0 | 0.20 | 0.331 |
| **Average** | **1.0** | **0.38** | **0.54** |

> 100% recall = never misses affected files. Conservative precision = flagging extra files is safer.

---

## Use Cases

### 1. **Cost Reduction for AI Coding**
```
Problem: Claude Code/Cursor/Gemini CLI reading 100 files = $0.50-2.00 per review
Solution: code-review-graph reads 15 files = $0.06-0.25 per review
Result: 8.2x cheaper code reviews
```

### 2. **Monorepo Navigation**
```
Problem: 27,000+ files in Next.js monorepo → AI can't focus on relevant code
Solution: Graph identifies ~15 affected files per change
Result: AI understands impact in seconds, not minutes
```

### 3. **Onboarding New Developers**
```
Problem: New dev doesn't understand architecture → reads entire codebase (weeks)
Solution: Graph shows community structure, execution flows, entry points
Result: Onboarding in hours, not weeks
```

### 4. **Code Quality Automation**
```
Problem: No way to detect code smells automatically
Solution: code-review-graph detects God objects, deep nesting, long parameter lists
Result: CI/CD flags design issues before review
```

### 5. **Documentation Enforcement**
```
Problem: 30% of functions undocumented → no context for AI
Solution: code-review-graph flags documentation_gap for every function
Result: AI says "this function needs docs" during reviews
```

---

## CLI Commands

```bash
# Build & Manage
code-review-graph install          # Auto-detect and configure all platforms
code-review-graph build            # Full rebuild (parse entire repo)
code-review-graph update           # Incremental update (changed files only)
code-review-graph watch            # Auto-update on file changes

# Query & Analyze
code-review-graph status           # Graph statistics
code-review-graph health           # Code quality report (complexity, smells, docs)
code-review-graph detect-changes   # Risk-scored change analysis
code-review-graph visualize        # Generate interactive D3.js graph

# Documentation
code-review-graph wiki             # Generate markdown wiki from code structure

# Multi-Repo
code-review-graph register <path>  # Register repo in multi-repo registry
code-review-graph repos            # List registered repos
code-review-graph unregister <id>  # Remove repo from registry

# Evaluation
code-review-graph eval             # Run benchmarks on sample repos
code-review-graph serve            # Start MCP server (for custom integrations)
```

---

## MCP Tools (22 Available)

All MCP tools work automatically in Claude Code, Cursor, Gemini CLI, etc.

| Tool | Purpose |
|------|---------|
| `detect_changes` | Risk-scored analysis of code changes |
| `get_impact_radius` | Show blast radius of changed files |
| `get_review_context` | Token-optimized review context |
| `semantic_search_nodes` | Find code by meaning (vector + keyword) |
| `query_graph` | Trace callers, callees, tests, imports |
| `get_architecture_overview` | Codebase structure & coupling analysis |
| `list_communities` | Code communities (clusters) |
| `get_community` | Details of a code community |
| `list_flows` | Execution flows (entry points) |
| `get_flow` | Details of a single flow |
| `get_affected_flows` | Which flows are impacted by changes |
| `get_code_quality_warnings` | Functions above complexity threshold |
| `get_code_smells` | Flag God objects, long params, deep nesting |
| `list_undocumented_functions` | Find functions missing documentation |
| `find_large_functions` | Functions exceeding line count threshold |
| `refactor_tool` | Rename preview, dead code, suggestions |
| `apply_refactor_tool` | Apply refactoring changes |
| `generate_wiki` | Create markdown wiki from structure |
| `get_wiki_page` | Retrieve wiki for a code community |
| `list_repos` | List registered repositories |
| `cross_repo_search` | Search across multiple repos |
| `build_or_update_graph` | Build/update graph programmatically |

---

## Configuration

### Exclude Files/Paths

Create `.code-review-graphignore` in repo root:

```
generated/**
*.generated.ts
node_modules/**
vendor/**
.git/**
**/__pycache__/**
```

### Optional Dependencies

```bash
pip install code-review-graph[embeddings]          # Vector search (sentence-transformers)
pip install code-review-graph[google-embeddings]   # Google Gemini embeddings
pip install code-review-graph[communities]         # Community detection (igraph)
pip install code-review-graph[wiki]                # Wiki generation with LLM summaries
pip install code-review-graph[eval]                # Benchmarking tools
pip install code-review-graph[all]                 # Everything
```

---

## FAQ

### Q: How much does it cost?
**A:** code-review-graph is free and open source (MIT license). Reduces cost of Claude Code/Cursor by 8.2x by cutting tokens.

### Q: Does it send code to the cloud?
**A:** No. Everything runs locally. SQLite database is in `.code-review-graph/` directory. Zero external dependencies.

### Q: Which IDEs does it support?
**A:** Claude Code, Cursor, Gemini CLI, Windsurf, Zed, Continue, OpenCode, Antigravity. One command configures all.

### Q: How long does the initial build take?
**A:** ~10 seconds for 500 files. 2-3 minutes for 10,000 files. Depends on file count and language complexity.

### Q: Do I need to rebuild every time?
**A:** No. Incremental updates (via git hooks) take <2 seconds. Full rebuild only needed after major refactors.

### Q: How many languages does it support?
**A:** 19: Python, TypeScript/TSX, JavaScript, Vue, Go, Rust, Java, Scala, C#, Ruby, Kotlin, Swift, PHP, Solidity, C/C++, Dart, R, Perl, Lua, plus Jupyter/Databricks notebooks.

### Q: Can I search across multiple repos?
**A:** Yes. Use `code-review-graph register <path>` to add repos to a multi-repo registry. Then use `cross_repo_search` MCP tool.

### Q: What about private repos?
**A:** Works the same. Database is local, no cloud upload. Configure normally with SSH/HTTPS credentials you already use.

---

## Benchmarks

### Build Performance

| Repo | Files | Nodes | Edges | Build Time |
|------|-------|-------|-------|-----------|
| express | 141 | 1,910 | 17,553 | ~0.2s |
| fastapi | 1,122 | 6,285 | 27,117 | ~0.8s |
| flask | 83 | 1,446 | 7,974 | ~0.1s |
| gin | 99 | 1,286 | 16,762 | ~0.1s |
| httpx | 60 | 1,253 | 7,896 | ~0.05s |

### Search Latency

All searches complete in <2ms via SQLite FTS5 + optional vector embeddings.

---

## Contributing

```bash
git clone https://github.com/natkal-coder/code-review-graph.git
cd code-review-graph
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

### Adding a New Language

Edit `code_review_graph/parser.py`:
1. Add file extension to `EXTENSION_TO_LANGUAGE`
2. Add node type mappings for classes, functions, imports, calls
3. Add test fixture in `tests/fixtures/`
4. Submit PR

---

## Roadmap

- [ ] Phase 2: Refactoring suggestions (extract methods, consolidate duplicate code)
- [ ] Phase 3: Training data export for code generation models
- [ ] Phase 4: IDE plugins (VS Code, JetBrains, Neovim)
- [ ] Phase 5: LLM fine-tuning on code graphs (better code understanding)

---

## License

MIT. See [LICENSE](LICENSE).

---

## Community

- **Discord**: [Join us](https://discord.gg/3p58KXqGFN)
- **GitHub Issues**: Report bugs or request features
- **GitHub Discussions**: Share use cases, ask questions
- **Twitter**: [@natkal_coder](https://twitter.com/natkal_coder)

---

<p align="center">
  <strong>Stop burning tokens. Start reviewing smarter.</strong><br>
  <code>pip install code-review-graph && code-review-graph install</code><br>
  <sub>Works with Claude Code, Cursor, Gemini CLI, Windsurf, Zed, Continue, OpenCode, and Antigravity</sub>
</p>
