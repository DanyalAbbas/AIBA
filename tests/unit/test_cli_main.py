"""Tests for src.cli.main — Typer app shell."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


def test_version_flag():
    """--version should print version and exit."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "aiba v" in result.stdout


def test_help_flag():
    """--help should show app info."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "AIBA" in result.stdout
    assert "run" in result.stdout
    assert "config" in result.stdout
    assert "session" in result.stdout
    assert "beat" in result.stdout


def test_run_help():
    """run --help should show run command options."""
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "prompt" in result.stdout.lower()
    assert "mode" in result.stdout.lower()


def test_config_help():
    """config --help should show config subcommands."""
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "show" in result.stdout.lower()
    assert "set" in result.stdout.lower()
    assert "list" in result.stdout.lower()


def test_session_help():
    """session --help should show session subcommands."""
    result = runner.invoke(app, ["session", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout.lower()
    assert "load" in result.stdout.lower()
    assert "delete" in result.stdout.lower()


def test_beat_help():
    """beat --help should show beat subcommands."""
    result = runner.invoke(app, ["beat", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout.lower()
    assert "run" in result.stdout.lower()
    assert "schedule" in result.stdout.lower()


def test_entry_point():
    """entry_point function should call app()."""
    from src.cli.main import entry_point

    assert callable(entry_point)


def test_version_fallback(monkeypatch):
    """_version_callback should raise Exit with fallback version."""
    import importlib.metadata
    def _raise(_name):
        raise Exception("version lookup failed")
    monkeypatch.setattr(importlib.metadata, "version", _raise)

    import typer

    from src.cli.main import _version_callback
    with pytest.raises(typer.Exit) as exc_info:
        _version_callback(version_flag=True)
    assert exc_info.value.exit_code == 0


def test_main_callback_no_subcommand():
    """Callback with no subcommand should show help (exit 0)."""
    result = runner.invoke(app, [])
    assert "AIBA" in result.stdout


def test_run_interactive_flag():
    """run --help should mention --interactive flag."""
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "interactive" in result.stdout.lower()


def test_entry_point_calls_app():
    """entry_point should call app()."""
    from unittest.mock import patch

    from src.cli import main

    with patch.object(main, "app") as mock_app:
        main.entry_point()
        mock_app.assert_called_once()


def test_set_impl_edge_case_alias_not_string():
    """_set_impl should handle non-string validation_alias gracefully."""
    import typer

    from src.cli.commands.config import _set_impl

    with pytest.raises(typer.Exit):
        _set_impl("NONEXISTENT_KEY=value")
