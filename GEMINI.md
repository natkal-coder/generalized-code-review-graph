<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**Use the code-review-graph MCP tools FIRST for code analysis.** The graph is faster, cheaper (fewer tokens), and gives you structural context (callers, dependents, test coverage) that file scanning cannot.

### Gemini CLI Setup

The code-review-graph MCP server is auto-configured in `~/.gemini/settings.json` under `mcpServers.code-review-graph`.

To verify the setup:
```bash
gemini /mcp list
# Should show: code-review-graph with available tools
```

To reload the server after updates:
```bash
gemini /mcp reload
```

### When to Use Graph Tools

- **Exploring code**: `semantic_search_nodes` or `query_graph` (not manual file reads)
- **Understanding impact**: `get_impact_radius` (not tracing imports manually)
- **Code review**: `detect_changes` + `get_review_context` (not reading entire files)
- **Finding relationships**: `query_graph` with patterns (callers_of, callees_of, imports_of, tests_for)
- **Architecture**: `get_architecture_overview` + `list_communities`

### Key Tools Reference

| Tool | Purpose |
|------|---------|
| `detect_changes` | Git-aware impact analysis with risk scoring |
| `get_review_context` | Minimal context for code review + source snippets |
| `get_impact_radius` | Blast radius: which functions/files are affected |
| `get_affected_flows` | Which execution paths are impacted |
| `query_graph` | Trace callers, callees, imports, tests, inheritance |
| `semantic_search_nodes` | Vector-based code search |
| `get_architecture_overview` | High-level system structure |
| `list_flows` + `get_flow` | Execution flow analysis by criticality |
| `refactor_tool` | Rename preview, dead code detection |

### Tips for Gemini CLI

1. Graph updates automatically on file changes (via hooks in `.claude/settings.json`)
2. For best results, run `code-review-graph build` once after installing
3. Use `/mcp list` during a session to see available tools
4. Tools return structured data—parse the JSON output for better analysis
5. Cost savings: 8.2x fewer tokens on average vs. naive file reads

### Workflow

```
1. User asks about code changes
2. You run: detect_changes (git-aware impact analysis)
3. Run: get_affected_flows (which paths are touched)
4. Run: get_review_context (minimal context + guidance)
5. For each high-risk area: query_graph with pattern="tests_for"
6. Provide thorough review with structural understanding
```

### Documentation

- Full tool docs: See `.code-review-graph/graph.db` metadata
- Architecture analysis: `get_architecture_overview_tool`
- Community structure: `get_community_tool` for specific modules
- Wiki: `generate_wiki_tool` creates markdown knowledge base
