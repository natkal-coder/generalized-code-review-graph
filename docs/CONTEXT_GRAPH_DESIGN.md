# Context-Graph Design: Live Context Engineering for v3.0.0

## Overview

The **Context-Graph** is an in-memory hot cache layer that maintains a persistent record of file access patterns during a session. It acts as a query-optimized subset of the main SQLite knowledge graph, reducing token costs and improving query latency by ~90% for frequently accessed code regions.

## Problem Statement

- **Cold-start latency**: Every graph query hits SQLite, even for frequently accessed files
- **Token waste**: AI agents repeatedly receive context about the same hot files (imports, utils, configs)
- **Context window inefficiency**: Context window fills with repetitive information instead of fresh code
- **No session memory**: When context window compacts, the system loses track of what was just accessed

**Solution**: A sliding-window in-memory graph that learns access patterns and intelligently discards stale entries.

---

## Architecture

### 1. Context-Graph Storage

```
ContextGraph (in-memory):
├── nodes: HashMap<qualified_name: str, ContextNode>
├── edges: HashMap<(source_qualified, target_qualified): str, EdgeInfo>
├── access_log: LRU-K cache (K=2 for recency + frequency)
├── metadata: {
│     "last_persist": float,      # unix timestamp of last disk save
│     "agent_type": str,          # "claude-code", "cursor", "gemini-cli", etc.
│     "max_size_bytes": int,      # agent's context window / 2 (safety margin)
│     "current_size_bytes": int,
│   }
└── lock: threading.RWLock        # thread-safe reads, exclusive writes
```

### 2. Node Structure

Each node tracks **temporal and frequency** information:

```python
@dataclass
class ContextNode:
    qualified_name: str
    kind: str                       # File, Class, Function, Type, Test
    file_path: str
    last_accessed: float            # unix timestamp
    access_count: int               # cumulative accesses in this session
    frequency_score: float          # exponential moving average: 0.7*old + 0.3*new
    time_since_access: float        # age in seconds (computed on demand)
    node_hash: str                  # hash from main graph for validation
    # Minimal data: store only file_path, kind, qualified_name
    # Full node data fetched from SQLite on demand
```

### 3. Query Flow

```
┌─────────────────────────────────────────┐
│ User/Tool requests node or edge         │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ Hash-map lookup in ContextGraph         │
│ O(1) time, in-memory                    │
└─────────────────────────────────────────┘
              │
      ┌───────┴───────┐
      │ HIT           │ MISS
      ▼               ▼
   Return        Query SQLite
   (cached)      (main graph)
                      │
                      ▼
                 Add to ContextGraph
                 (with LRU eviction)
                      │
                      ▼
                   Return
```

---

## Implementation Details

### 1. Initialization (Agent-Aware)

At startup, detect the calling agent and set `max_size_bytes`:

```python
def detect_agent_context_window() -> tuple[str, int]:
    """Detect agent type and return (agent_type, max_context_tokens)."""
    # Check environment variables set by each agent
    if os.getenv("CURSOR_WORKSPACE"):
        return ("cursor", 200000)  # Cursor: ~200k tokens
    elif os.getenv("CLAUDE_CODE_SESSION"):
        return ("claude-code", 200000)  # Claude Code: ~200k tokens
    elif os.getenv("GEMINI_CLI"):
        return ("gemini-cli", 1000000)  # Gemini 2.0: ~1M tokens
    elif os.getenv("WINDSURF_WORKSPACE"):
        return ("windsurf", 200000)  # Windsurf: ~200k tokens
    elif os.getenv("ZED_WORKSPACE"):
        return ("zed", 100000)  # Zed: ~100k tokens
    else:
        return ("generic", 200000)  # Default fallback

# max_size_bytes = (max_context_tokens * 4 * 0.5) / 2
# Example: 200k tokens × 4 bytes/token × 0.5 (UTF-8 overhead) / 2 (safety margin)
#        = 200k * 2 / 2 = 200k bytes ≈ 200KB
```

### 2. Access Tracking & LRU-K Eviction

**LRU-K** = Track the last **K** accesses (K=2: recency + frequency):

```python
class AccessLog:
    """Track last K accesses for each node."""
    
    def record_access(self, qualified_name: str) -> float:
        """Record access, return frequency_score."""
        now = time.time()
        
        if qualified_name not in self.access_history:
            self.access_history[qualified_name] = []
        
        # Keep only last 2 accesses (recency + 1 prior for frequency)
        self.access_history[qualified_name].append(now)
        if len(self.access_history[qualified_name]) > 2:
            self.access_history[qualified_name].pop(0)
        
        # Compute frequency_score: EMA of access patterns
        accesses = self.access_history[qualified_name]
        if len(accesses) == 1:
            freq = 1.0
        else:
            # Time between last 2 accesses (lower = more frequent)
            time_delta = accesses[-1] - accesses[-2]
            freq = 1.0 / (1.0 + time_delta)  # normalize to [0, 1)
        
        return freq

def eviction_score(node: ContextNode) -> float:
    """Lower score = evict first. Higher score = keep."""
    now = time.time()
    time_since = now - node.last_accessed
    
    # Score = frequency × recency_decay
    # frequency_score ∈ [0, 1]: higher = accessed more recently/frequently
    # recency_decay ∈ [0, 1]: exp(-t/τ) where τ = 60 seconds (time constant)
    
    recency = math.exp(-time_since / 60.0)
    return node.frequency_score * recency
```

### 3. Size Management & Persistence

```python
def estimate_size_bytes(node: ContextNode) -> int:
    """Estimate serialized size of a node."""
    # Minimal fields only:
    # qualified_name (avg 60 chars) + kind (10) + file_path (200) + metadata (50)
    return len(node.qualified_name) + len(node.kind) + len(node.file_path) + 100

def check_capacity_and_evict(graph: ContextGraph) -> None:
    """Maintain max_size_bytes invariant via LRU-K eviction."""
    while graph.current_size_bytes > graph.metadata["max_size_bytes"]:
        # Find node with lowest eviction_score
        lowest_node = min(
            graph.nodes.values(),
            key=eviction_score
        )
        graph.nodes.pop(lowest_node.qualified_name)
        graph.current_size_bytes -= estimate_size_bytes(lowest_node)

def persist_to_disk(graph: ContextGraph, db_path: str) -> None:
    """Save context-graph to SQLite at .code-review-graph/context.db."""
    # Use a separate DB from the main graph.db
    # Schema: nodes (qualified_name, kind, file_path, last_accessed, frequency_score, access_count)
    # No edges stored (edges are derived from main graph on demand)
    
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS context_nodes (...)")
    for node in graph.nodes.values():
        conn.execute(
            "INSERT OR REPLACE INTO context_nodes (...) VALUES (...)",
            (node.qualified_name, node.kind, ...)
        )
    conn.commit()
    graph.metadata["last_persist"] = time.time()
```

### 4. Periodic Persistence Hook

```python
# In MCP server initialization:
def start_context_graph_persist_loop(graph: ContextGraph, interval_sec: float = 5.0):
    """Background thread to persist context-graph every N seconds."""
    def persist_loop():
        while True:
            time.sleep(interval_sec)
            try:
                persist_to_disk(graph, ".code-review-graph/context.db")
                logger.debug(f"Context-graph persisted: {graph.current_size_bytes} bytes")
            except Exception as e:
                logger.error(f"Context-graph persist failed: {e}")
    
    thread = threading.Thread(target=persist_loop, daemon=True)
    thread.start()
    return thread
```

---

## Query Integration

### Before

```python
def get_node(qualified_name: str) -> Optional[GraphNode]:
    # Always hit SQLite
    return self.main_graph.get_node(qualified_name)
```

### After

```python
def get_node(qualified_name: str) -> Optional[GraphNode]:
    # Try context-graph first
    if qualified_name in self.context_graph.nodes:
        self.context_graph.record_access(qualified_name)
        # Full node data already in ContextNode
        return self.context_graph.nodes[qualified_name].to_graph_node()
    
    # Miss: query main graph
    node = self.main_graph.get_node(qualified_name)
    if node:
        # Add to context-graph
        context_node = ContextNode.from_graph_node(node)
        self.context_graph.nodes[qualified_name] = context_node
        self.context_graph.current_size_bytes += estimate_size_bytes(context_node)
        check_capacity_and_evict(self.context_graph)
    
    return node
```

---

## Lifecycle Events

| Event | Action |
|-------|--------|
| **Session Start** | Detect agent, load context.db from disk, set max_size_bytes |
| **Query Hit (context-graph)** | Update last_accessed, access_count, frequency_score |
| **Query Miss (SQLite)** | Add node to context-graph, check capacity, evict if needed |
| **Every 5 seconds** | Persist context-graph to .code-review-graph/context.db |
| **Context Window Compaction** | Older/less-accessed nodes already discarded by LRU-K |
| **Session End** | Final persist to disk (automatic on shutdown) |

---

## Performance Impact

### Query Latency
- **Hit path**: O(1) hash-map lookup (~1-5μs)
- **Miss path**: O(log n) SQLite B-tree + O(1) insertion (~10-50ms)
- **Average**: ~90% of reads should hit (higher for "hot" code regions)

### Memory Usage
- **Per-node**: ~200-300 bytes (minimal fields only)
- **Max nodes**: max_size_bytes / 300 ≈ 667 nodes for 200KB context graph
- **Typical session**: 100-300 hot nodes (utilities, imports, configs, tests)

### Disk I/O
- **Persistence**: 5-second interval, ~5-10ms per persist
- **Size on disk**: Same as max_size_bytes (200KB typical)
- **Startup**: Load from disk (~1-2ms)

### Token Savings
- **Query cost**: Reduced ~90% for hot paths
- **Context window**: Eliminates redundant info, reserves space for fresh code
- **Overall**: Indirect savings; main benefit is **query latency** and **session memory**

---

## Configuration

### Environment Variables

```bash
# Override agent type detection
export CRG_AGENT_TYPE="cursor"

# Override max context window (bytes)
export CRG_CONTEXT_MAX_BYTES=204800  # 200KB

# Override persistence interval (seconds)
export CRG_CONTEXT_PERSIST_INTERVAL=5.0

# Disable context-graph entirely (fallback to main graph only)
export CRG_CONTEXT_GRAPH_ENABLED=false
```

### Settings in `.claude/settings.json`

```json
{
  "codeReviewGraph": {
    "contextGraphEnabled": true,
    "contextMaxBytes": 204800,
    "persistIntervalSec": 5.0,
    "lrkAccessLimit": 2
  }
}
```

---

## Testing

```
tests/test_context_graph.py:
├── test_detect_agent_context_window()
├── test_hash_map_o1_lookup()
├── test_lru_k_eviction()
├── test_capacity_check()
├── test_persist_to_disk()
├── test_access_tracking()
├── test_frequency_score()
├── test_context_miss_fallback()
└── test_session_lifecycle()
```

---

## Migration Path (v2.1.0 → v3.0.0)

1. No breaking changes to main graph or MCP tools
2. Context-graph is additive layer; queries work with or without it
3. Old `context.db` files ignored (fresh context per session)
4. Graceful degradation: if context-graph fails, main graph queries continue

---

## Future Extensions

1. **Cross-session persistence**: Save context-graph per project, restore on reopen
2. **Shared context**: Upload context-graph to git for team sync
3. **Predictive prefetch**: Load frequently-accessed neighbors before they're queried
4. **Adaptive τ**: Learn time constant (τ=60s) per project/team
