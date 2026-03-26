"""Tests for skills and hooks auto-install."""

import json

from code_review_graph.skills import (
    _CLAUDE_MD_SECTION_MARKER,
    generate_hooks_config,
    generate_skills,
    inject_claude_md,
    install_hooks,
)


class TestGenerateSkills:
    def test_creates_skills_directory(self, tmp_path):
        result = generate_skills(tmp_path)
        assert result.is_dir()
        assert result == tmp_path / ".claude" / "skills"

    def test_creates_four_skill_files(self, tmp_path):
        skills_dir = generate_skills(tmp_path)
        files = sorted(f.name for f in skills_dir.iterdir())
        assert files == [
            "debug-issue.md",
            "explore-codebase.md",
            "refactor-safely.md",
            "review-changes.md",
        ]

    def test_skill_files_have_frontmatter(self, tmp_path):
        skills_dir = generate_skills(tmp_path)
        for path in skills_dir.iterdir():
            content = path.read_text()
            assert content.startswith("---\n")
            assert "name:" in content
            assert "description:" in content
            # Frontmatter closes
            lines = content.split("\n")
            assert lines[0] == "---"
            closing_idx = content.index("---", 4)
            assert closing_idx > 0

    def test_custom_skills_dir(self, tmp_path):
        custom = tmp_path / "my-skills"
        result = generate_skills(tmp_path, skills_dir=custom)
        assert result == custom
        assert result.is_dir()
        assert len(list(result.iterdir())) == 4

    def test_idempotent(self, tmp_path):
        """Running twice should not fail and files should still be valid."""
        generate_skills(tmp_path)
        generate_skills(tmp_path)
        skills_dir = tmp_path / ".claude" / "skills"
        assert len(list(skills_dir.iterdir())) == 4


class TestGenerateHooksConfig:
    def test_returns_dict_with_hooks(self):
        config = generate_hooks_config()
        assert "hooks" in config

    def test_has_post_tool_use(self):
        config = generate_hooks_config()
        assert "PostToolUse" in config["hooks"]
        hooks = config["hooks"]["PostToolUse"]
        assert len(hooks) >= 1
        assert hooks[0]["matcher"] == "Edit|Write|Bash"
        assert "update" in hooks[0]["command"]
        assert hooks[0]["timeout"] == 5000

    def test_has_session_start(self):
        config = generate_hooks_config()
        assert "SessionStart" in config["hooks"]
        hooks = config["hooks"]["SessionStart"]
        assert len(hooks) >= 1
        assert "status" in hooks[0]["command"]
        assert hooks[0]["timeout"] == 3000

    def test_has_pre_commit(self):
        config = generate_hooks_config()
        assert "PreCommit" in config["hooks"]
        hooks = config["hooks"]["PreCommit"]
        assert len(hooks) >= 1
        assert "detect-changes" in hooks[0]["command"]
        assert hooks[0]["timeout"] == 10000

    def test_has_all_three_hook_types(self):
        config = generate_hooks_config()
        hook_types = set(config["hooks"].keys())
        assert hook_types == {"PostToolUse", "SessionStart", "PreCommit"}


class TestInstallHooks:
    def test_creates_settings_file(self, tmp_path):
        install_hooks(tmp_path)
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "hooks" in data

    def test_merges_with_existing(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir(parents=True)
        existing = {"customSetting": True, "hooks": {"OtherHook": []}}
        (settings_dir / "settings.json").write_text(json.dumps(existing))

        install_hooks(tmp_path)

        data = json.loads((settings_dir / "settings.json").read_text())
        assert data["customSetting"] is True
        assert "PostToolUse" in data["hooks"]
        assert "SessionStart" in data["hooks"]
        assert "PreCommit" in data["hooks"]

    def test_creates_claude_directory(self, tmp_path):
        install_hooks(tmp_path)
        assert (tmp_path / ".claude").is_dir()


class TestInjectClaudeMd:
    def test_creates_section_in_new_file(self, tmp_path):
        inject_claude_md(tmp_path)
        content = (tmp_path / "CLAUDE.md").read_text()
        assert _CLAUDE_MD_SECTION_MARKER in content
        assert "MCP Tools" in content

    def test_appends_to_existing_file(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# My Project\n\nExisting content.\n")

        inject_claude_md(tmp_path)

        content = claude_md.read_text()
        assert "# My Project" in content
        assert "Existing content." in content
        assert _CLAUDE_MD_SECTION_MARKER in content

    def test_idempotent(self, tmp_path):
        """Running twice should not duplicate the section."""
        inject_claude_md(tmp_path)
        first_content = (tmp_path / "CLAUDE.md").read_text()

        inject_claude_md(tmp_path)
        second_content = (tmp_path / "CLAUDE.md").read_text()

        assert first_content == second_content
        assert second_content.count(_CLAUDE_MD_SECTION_MARKER) == 1

    def test_idempotent_with_existing_content(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Existing\n")

        inject_claude_md(tmp_path)
        first_content = claude_md.read_text()

        inject_claude_md(tmp_path)
        second_content = claude_md.read_text()

        assert first_content == second_content
        assert second_content.count(_CLAUDE_MD_SECTION_MARKER) == 1
