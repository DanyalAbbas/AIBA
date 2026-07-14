"""Tests for src.cli.commands.config — config subcommand."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


def test_config_show():
    """config show should display settings."""
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "gemini_api_key" in result.stdout or "AIBA Configuration" in result.stdout


def test_config_list():
    """config list should show available keys with descriptions."""
    result = runner.invoke(app, ["config", "list"])
    assert result.exit_code == 0
    assert "GEMINI_API_KEY" in result.stdout


def test_config_set_no_equals():
    """config set without = should show error."""
    result = runner.invoke(app, ["config", "set", "badformat"])
    assert "Invalid format" in result.stdout or "KEY=VALUE" in result.stdout


def test_set_impl_validates_key():
    """_set_impl with unknown key should raise."""
    import typer

    from src.cli.commands.config import _set_impl
    with pytest.raises(typer.Exit):
        _set_impl("NONEXISTENT_KEY=value")


def test_set_impl_writes_to_env(tmp_path, monkeypatch):
    """_set_impl should write KEY=VALUE to .env."""
    from src.cli.commands.config import _set_impl

    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=old_value\n", encoding="utf-8")

    _set_impl("GEMINI_API_KEY=new_value")

    content = env_file.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=new_value" in content


def test_set_impl_creates_env_if_missing(tmp_path, monkeypatch):
    """_set_impl should create .env if it doesn't exist."""
    from src.cli.commands.config import _set_impl

    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".env").is_file()

    _set_impl("GEMINI_API_KEY=hello")

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=hello" in content


def test_set_impl_appends_new_key(tmp_path, monkeypatch):
    """_set_impl should append if key not in existing .env."""
    from src.cli.commands.config import _set_impl

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=stay\n", encoding="utf-8")

    _set_impl("GUARDRAILS_ENABLED=True")

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=stay" in content
    assert "GUARDRAILS_ENABLED=True" in content


def test_set_impl_respects_validation_alias(tmp_path, monkeypatch):
    """_set_impl should match using validation alias."""
    from src.cli.commands.config import _set_impl

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("PLAYWRIGHT_HEADLESS=True\n", encoding="utf-8")
    _set_impl("PLAYWRIGHT_HEADLESS=False")
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "PLAYWRIGHT_HEADLESS=False" in content


def test_config_show_masks_secrets(tmp_path, monkeypatch):
    """config show should mask secret values like API keys."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=abcdef123456\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    # Should show masked key
    assert "abcdef123456" not in result.stdout.replace("...", "")
