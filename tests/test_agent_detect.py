"""Tests for agent_detect module: agent detection and context window profiles."""

from __future__ import annotations

import os

import pytest

from code_review_graph.agent_detect import (
    AGENT_PROFILES,
    AgentInfo,
    detect_agent,
    get_agent_by_name,
)


class TestAgentInfo:
    """Test AgentInfo dataclass."""

    def test_create_agent_info(self) -> None:
        """Test creating an AgentInfo."""
        agent = AgentInfo(
            name="Test Agent",
            context_window=100000,
            estimated_overhead=10000,
        )
        assert agent.name == "Test Agent"
        assert agent.context_window == 100000
        assert agent.estimated_overhead == 10000

    def test_effective_capacity(self) -> None:
        """Test effective_capacity() calculation."""
        agent = AgentInfo(
            name="Test",
            context_window=100000,
            estimated_overhead=10000,
        )
        assert agent.effective_capacity() == 90000

    def test_agent_info_frozen(self) -> None:
        """Test that AgentInfo is frozen (immutable)."""
        agent = AGENT_PROFILES["claude-code"]
        with pytest.raises(AttributeError):
            agent.name = "Modified"  # type: ignore


class TestAgentProfiles:
    """Test predefined AGENT_PROFILES."""

    def test_claude_code_profile(self) -> None:
        """Test Claude Code profile."""
        agent = AGENT_PROFILES["claude-code"]
        assert agent.name == "Claude Code"
        assert agent.context_window == 200000
        assert agent.estimated_overhead == 20000
        assert agent.effective_capacity() == 180000

    def test_cursor_profile(self) -> None:
        """Test Cursor profile."""
        agent = AGENT_PROFILES["cursor"]
        assert agent.name == "Cursor"
        assert agent.context_window == 128000
        assert agent.estimated_overhead == 15000
        assert agent.effective_capacity() == 113000

    def test_gemini_cli_profile(self) -> None:
        """Test Gemini CLI profile."""
        agent = AGENT_PROFILES["gemini-cli"]
        assert agent.name == "Gemini CLI"
        assert agent.context_window == 1000000
        assert agent.estimated_overhead == 50000
        assert agent.effective_capacity() == 950000

    def test_generic_profile(self) -> None:
        """Test generic fallback profile."""
        agent = AGENT_PROFILES["generic"]
        assert agent.name == "Generic/Unknown"
        assert agent.context_window == 100000

    def test_all_profiles_have_capacity(self) -> None:
        """Test that all profiles have reasonable capacity."""
        for name, agent in AGENT_PROFILES.items():
            assert agent.context_window > 0
            assert agent.estimated_overhead >= 0
            assert agent.effective_capacity() > 0
            assert agent.effective_capacity() <= agent.context_window


class TestDetectAgent:
    """Test detect_agent() function."""

    def test_detect_claude_code(self) -> None:
        """Test detecting Claude Code from env var."""
        os.environ["CLAUDE_CODE"] = "1"
        try:
            agent = detect_agent()
            assert agent.name == "Claude Code"
        finally:
            os.environ.pop("CLAUDE_CODE", None)

    def test_detect_cursor(self) -> None:
        """Test detecting Cursor from env var."""
        os.environ["CURSOR"] = "1"
        try:
            agent = detect_agent()
            assert agent.name == "Cursor"
        finally:
            os.environ.pop("CURSOR", None)

    def test_detect_cursor_session(self) -> None:
        """Test detecting Cursor from CURSOR_SESSION env var."""
        os.environ["CURSOR_SESSION"] = "active"
        try:
            agent = detect_agent()
            assert agent.name == "Cursor"
        finally:
            os.environ.pop("CURSOR_SESSION", None)

    def test_detect_gemini_cli(self) -> None:
        """Test detecting Gemini CLI from env var."""
        os.environ["GEMINI_CLI"] = "1"
        try:
            agent = detect_agent()
            assert agent.name == "Gemini CLI"
        finally:
            os.environ.pop("GEMINI_CLI", None)

    def test_detect_windsurf(self) -> None:
        """Test detecting Windsurf from env var."""
        os.environ["WINDSURF_WORKSPACE"] = "/path/to/workspace"
        try:
            agent = detect_agent()
            assert agent.name == "Windsurf"
        finally:
            os.environ.pop("WINDSURF_WORKSPACE", None)

    def test_detect_zed(self) -> None:
        """Test detecting Zed from env var."""
        os.environ["ZED_WORKSPACE"] = "/path/to/workspace"
        try:
            agent = detect_agent()
            assert agent.name == "Zed"
        finally:
            os.environ.pop("ZED_WORKSPACE", None)

    def test_detect_continue(self) -> None:
        """Test detecting Continue from env var."""
        os.environ["CONTINUE"] = "1"
        try:
            agent = detect_agent()
            assert agent.name == "Continue"
        finally:
            os.environ.pop("CONTINUE", None)

    def test_detect_explicit_override(self) -> None:
        """Test explicit CRG_AGENT_TYPE override."""
        os.environ["CRG_AGENT_TYPE"] = "gemini-cli"
        try:
            agent = detect_agent()
            assert agent.name == "Gemini CLI"
        finally:
            os.environ.pop("CRG_AGENT_TYPE", None)

    def test_detect_fallback_generic(self) -> None:
        """Test fallback to generic when no agent detected."""
        # Clear all agent-specific env vars
        for key in ["CLAUDE_CODE", "CURSOR", "CURSOR_SESSION", "GEMINI_CLI",
                    "WINDSURF_WORKSPACE", "ZED_WORKSPACE", "CONTINUE",
                    "CONTINUE_SESSION", "CRG_AGENT_TYPE"]:
            os.environ.pop(key, None)

        agent = detect_agent()
        assert agent.name == "Generic/Unknown"

    def test_detect_priority_order(self) -> None:
        """Test detection priority: CRG_AGENT_TYPE > env-specific vars."""
        # Set both explicit and env-specific
        os.environ["CRG_AGENT_TYPE"] = "cursor"
        os.environ["CLAUDE_CODE"] = "1"

        try:
            agent = detect_agent()
            # Should prefer explicit override
            assert agent.name == "Cursor"
        finally:
            os.environ.pop("CRG_AGENT_TYPE", None)
            os.environ.pop("CLAUDE_CODE", None)


class TestGetAgentByName:
    """Test get_agent_by_name() function."""

    def test_get_by_lowercase_key(self) -> None:
        """Test getting agent by lowercase key."""
        agent = get_agent_by_name("claude-code")
        assert agent is not None
        assert agent.name == "Claude Code"

    def test_get_by_display_name(self) -> None:
        """Test getting agent by display name."""
        agent = get_agent_by_name("Cursor")
        assert agent is not None
        assert agent.context_window == 128000

    def test_get_by_display_name_lowercase(self) -> None:
        """Test getting agent by lowercase display name."""
        agent = get_agent_by_name("gemini cli")
        assert agent is not None
        assert agent.context_window == 1000000

    def test_get_nonexistent_agent(self) -> None:
        """Test getting agent that doesn't exist."""
        agent = get_agent_by_name("nonexistent")
        assert agent is None

    def test_get_case_insensitive(self) -> None:
        """Test case-insensitive lookup."""
        agent1 = get_agent_by_name("CLAUDE-CODE")
        agent2 = get_agent_by_name("claude-code")
        assert agent1 == agent2
        assert agent1 is not None
