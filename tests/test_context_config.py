"""Tests for context_config module: configuration loading and validation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from code_review_graph.context_config import ContextConfig, load_context_config


class TestContextConfig:
    """Test ContextConfig dataclass."""

    def test_create_valid_config(self) -> None:
        """Test creating a valid ContextConfig."""
        config = ContextConfig(
            max_tokens=200000,
            eviction_threshold=0.85,
            lru_k=2,
            persistence_path="/tmp/context.db",
        )
        assert config.max_tokens == 200000
        assert config.eviction_threshold == 0.85
        assert config.lru_k == 2
        assert config.persistence_path == "/tmp/context.db"

    def test_config_frozen(self) -> None:
        """Test that ContextConfig is frozen (immutable)."""
        config = ContextConfig(200000, 0.85, 2, "/tmp/context.db")
        with pytest.raises(AttributeError):
            config.max_tokens = 300000  # type: ignore

    def test_invalid_eviction_threshold_too_high(self) -> None:
        """Test validation of eviction_threshold > 1.0."""
        with pytest.raises(ValueError, match="eviction_threshold"):
            ContextConfig(200000, 1.5, 2, "/tmp/context.db")

    def test_invalid_eviction_threshold_zero(self) -> None:
        """Test validation of eviction_threshold = 0."""
        with pytest.raises(ValueError, match="eviction_threshold"):
            ContextConfig(200000, 0.0, 2, "/tmp/context.db")

    def test_invalid_lru_k_zero(self) -> None:
        """Test validation of lru_k < 1."""
        with pytest.raises(ValueError, match="lru_k"):
            ContextConfig(200000, 0.85, 0, "/tmp/context.db")

    def test_invalid_max_tokens_too_small(self) -> None:
        """Test validation of max_tokens < 1000."""
        with pytest.raises(ValueError, match="max_tokens"):
            ContextConfig(500, 0.85, 2, "/tmp/context.db")

    def test_valid_edge_cases(self) -> None:
        """Test valid edge cases."""
        # Max threshold
        config1 = ContextConfig(1000, 1.0, 1, "/tmp/context.db")
        assert config1.eviction_threshold == 1.0

        # Min threshold (just above 0)
        config2 = ContextConfig(1000, 0.01, 1, "/tmp/context.db")
        assert config2.eviction_threshold == 0.01


class TestLoadContextConfig:
    """Test load_context_config() function."""

    def test_load_defaults(self, tmp_path: Path) -> None:
        """Test loading with default values (no env vars, no settings file)."""
        # Ensure no env vars set
        old_env = {}
        for key in ["CRG_CONTEXT_MAX_TOKENS", "CRG_EVICTION_THRESHOLD", "CRG_CONTEXT_LRU_K"]:
            old_env[key] = os.environ.pop(key, None)

        try:
            config = load_context_config(tmp_path)
            assert config.max_tokens == 200000  # Default
            assert config.eviction_threshold == 0.85  # Default
            assert config.lru_k == 2  # Default
            assert config.agent_type is None  # Default
        finally:
            # Restore env
            for key, val in old_env.items():
                if val is not None:
                    os.environ[key] = val

    def test_load_from_env_vars(self, tmp_path: Path) -> None:
        """Test loading from environment variables."""
        os.environ["CRG_CONTEXT_MAX_TOKENS"] = "300000"
        os.environ["CRG_EVICTION_THRESHOLD"] = "0.80"
        os.environ["CRG_CONTEXT_LRU_K"] = "3"
        os.environ["CRG_AGENT_TYPE"] = "cursor"

        try:
            config = load_context_config(tmp_path)
            assert config.max_tokens == 300000
            assert config.eviction_threshold == 0.80
            assert config.lru_k == 3
            assert config.agent_type == "cursor"
        finally:
            for key in ["CRG_CONTEXT_MAX_TOKENS", "CRG_EVICTION_THRESHOLD",
                        "CRG_CONTEXT_LRU_K", "CRG_AGENT_TYPE"]:
                os.environ.pop(key, None)

    def test_load_from_settings_file(self, tmp_path: Path) -> None:
        """Test loading from .code-review-graph/settings.json."""
        settings_dir = tmp_path / ".code-review-graph"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = settings_dir / "settings.json"

        settings_data = {
            "contextGraph": {
                "maxTokens": 150000,
                "evictionThreshold": 0.75,
                "lruK": 1,
                "agentType": "gemini-cli",
            }
        }
        settings_file.write_text(json.dumps(settings_data))

        config = load_context_config(tmp_path)
        assert config.max_tokens == 150000
        assert config.eviction_threshold == 0.75
        assert config.lru_k == 1
        assert config.agent_type == "gemini-cli"

    def test_env_overrides_settings_file(self, tmp_path: Path) -> None:
        """Test that env vars override settings file."""
        settings_dir = tmp_path / ".code-review-graph"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = settings_dir / "settings.json"

        settings_data = {
            "contextGraph": {
                "maxTokens": 150000,
                "evictionThreshold": 0.75,
            }
        }
        settings_file.write_text(json.dumps(settings_data))

        os.environ["CRG_CONTEXT_MAX_TOKENS"] = "250000"

        try:
            config = load_context_config(tmp_path)
            # Env var should override settings file
            assert config.max_tokens == 250000
            # Settings file value should still be used for eviction_threshold
            assert config.eviction_threshold == 0.75
        finally:
            os.environ.pop("CRG_CONTEXT_MAX_TOKENS", None)

    def test_malformed_settings_file_ignored(self, tmp_path: Path) -> None:
        """Test that malformed settings.json is gracefully ignored."""
        settings_dir = tmp_path / ".code-review-graph"
        settings_dir.mkdir(parents=True, exist_ok=True)
        settings_file = settings_dir / "settings.json"

        # Write invalid JSON
        settings_file.write_text("{ invalid json }")

        # Should fall back to defaults
        config = load_context_config(tmp_path)
        assert config.max_tokens == 200000

    def test_persistence_path_env_override(self, tmp_path: Path) -> None:
        """Test overriding persistence_path via env var."""
        custom_path = "/custom/path/context.db"
        os.environ["CRG_CONTEXT_PERSISTENCE_PATH"] = custom_path

        try:
            config = load_context_config(tmp_path)
            assert config.persistence_path == custom_path
        finally:
            os.environ.pop("CRG_CONTEXT_PERSISTENCE_PATH", None)

    def test_default_persistence_path(self, tmp_path: Path) -> None:
        """Test default persistence path."""
        config = load_context_config(tmp_path)
        assert ".code-review-graph" in config.persistence_path
        assert "context.db" in config.persistence_path

    def test_scoring_weights_default(self, tmp_path: Path) -> None:
        """Test that scoring weights are configured."""
        config = load_context_config(tmp_path)
        assert config.scoring_weights is not None
        assert "recency" in config.scoring_weights
        assert "frequency" in config.scoring_weights
        assert "access_count" in config.scoring_weights
        assert config.scoring_weights["recency"] == 0.5
        assert config.scoring_weights["frequency"] == 0.3
        assert config.scoring_weights["access_count"] == 0.2
