"""Configuration for context-graph session management.

Loads settings from environment variables and .code-review-graph/settings.json.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ContextConfig:
    """Configuration for context-graph behavior."""

    max_tokens: int  # Max tokens in context-graph before eviction
    eviction_threshold: float  # Trigger eviction at this ratio (0-1)
    lru_k: int  # LRU-K: keep last N accesses per node
    persistence_path: str  # Path to save context.db
    agent_type: Optional[str] = None  # Auto-detected agent type
    scoring_weights: dict[str, float] = None  # Weights for relevance scoring

    def __post_init__(self) -> None:
        # Validate ranges
        if not (0 < self.eviction_threshold <= 1.0):
            raise ValueError("eviction_threshold must be in (0, 1]")
        if self.lru_k < 1:
            raise ValueError("lru_k must be >= 1")
        if self.max_tokens < 1000:
            raise ValueError("max_tokens must be >= 1000")


def load_context_config(repo_root: str | Path = ".") -> ContextConfig:
    """Load context-graph configuration from environment and settings file.

    Priority:
    1. Environment variables (CRG_* prefix)
    2. .code-review-graph/settings.json
    3. Defaults
    """
    repo_root = Path(repo_root)

    # Track which env vars were explicitly set
    env_max_tokens = "CRG_CONTEXT_MAX_TOKENS" in os.environ
    env_eviction = "CRG_EVICTION_THRESHOLD" in os.environ
    env_lru_k = "CRG_CONTEXT_LRU_K" in os.environ
    env_agent = "CRG_AGENT_TYPE" in os.environ
    env_persistence = "CRG_CONTEXT_PERSISTENCE_PATH" in os.environ

    # Defaults
    max_tokens = 200000
    eviction_threshold = 0.85
    lru_k = 2
    agent_type = None
    persistence_path = str(repo_root / ".code-review-graph" / "context.db")

    # Try to load from .code-review-graph/settings.json first
    settings_file = repo_root / ".code-review-graph" / "settings.json"
    if settings_file.exists():
        try:
            with settings_file.open() as f:
                settings = json.load(f)
            ctx_settings = settings.get("contextGraph", {})
            max_tokens = ctx_settings.get("maxTokens", max_tokens)
            eviction_threshold = ctx_settings.get("evictionThreshold", eviction_threshold)
            lru_k = ctx_settings.get("lruK", lru_k)
            agent_type = ctx_settings.get("agentType", agent_type)
            if "persistencePath" in ctx_settings:
                persistence_path = ctx_settings["persistencePath"]
        except (json.JSONDecodeError, IOError) as e:
            # Silently ignore parse errors; use defaults
            pass

    # Override with environment variables (takes precedence)
    if env_max_tokens:
        max_tokens = int(os.getenv("CRG_CONTEXT_MAX_TOKENS"))
    if env_eviction:
        eviction_threshold = float(os.getenv("CRG_EVICTION_THRESHOLD"))
    if env_lru_k:
        lru_k = int(os.getenv("CRG_CONTEXT_LRU_K"))
    if env_agent:
        agent_type = os.getenv("CRG_AGENT_TYPE")
    if env_persistence:
        persistence_path = os.getenv("CRG_CONTEXT_PERSISTENCE_PATH")

    scoring_weights = {
        "recency": 0.5,
        "frequency": 0.3,
        "access_count": 0.2,
    }

    return ContextConfig(
        max_tokens=max_tokens,
        eviction_threshold=eviction_threshold,
        lru_k=lru_k,
        persistence_path=persistence_path,
        agent_type=agent_type,
        scoring_weights=scoring_weights,
    )
