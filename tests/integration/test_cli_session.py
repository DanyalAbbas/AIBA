"""Integration tests for session load/delete commands."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


def test_session_load_missing():
    """session load with non-existent name should error."""
    result = runner.invoke(app, ["session", "load", "nonexistent_session"])
    assert "not found" in result.stdout.lower()


def test_session_load_with_settings(tmp_path, monkeypatch):
    """session load with valid settings should preview the session."""
    monkeypatch.setattr("src.services.session.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    session_data = {"version": 1, "settings": {"mode": "agent", "effort": "balanced"}, "messages": []}
    (tmp_path / "test_session.json").write_text(json.dumps(session_data), encoding="utf-8")

    with patch("src.services.repl.run"):
        result = runner.invoke(app, ["session", "load", "test_session"])
        assert result.exit_code == 0


def test_session_load_invalid_effort(tmp_path, monkeypatch):
    """session load with invalid effort should fallback to balanced."""
    monkeypatch.setattr("src.services.session.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    session_data = {"version": 1, "settings": {"mode": "agent", "effort": "INVALID_EFFORT"}, "messages": []}
    (tmp_path / "bad_effort.json").write_text(json.dumps(session_data), encoding="utf-8")

    with patch("src.services.repl.run"):
        result = runner.invoke(app, ["session", "load", "bad_effort"])
        assert result.exit_code == 0


def test_session_load_no_settings_key(tmp_path, monkeypatch):
    """session load with missing settings key triggers legacy fallback."""
    monkeypatch.setattr("src.services.session.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    # Wrapper dict but no settings key → returns None for settings → legacy path
    legacy_data = {"version": 1, "messages": []}
    (tmp_path / "legacy.json").write_text(json.dumps(legacy_data), encoding="utf-8")

    with patch("src.services.repl.run"):
        result = runner.invoke(app, ["session", "load", "legacy"])
        assert result.exit_code == 0


def test_session_load_corrupt_file(tmp_path, monkeypatch):
    """session load with corrupted file should error gracefully."""
    monkeypatch.setattr("src.services.session.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    (tmp_path / "corrupt.json").write_text("not valid json{{{", encoding="utf-8")

    result = runner.invoke(app, ["session", "load", "corrupt"])
    assert result.exit_code == 1
    assert "Failed to load" in result.stdout or "Error" in result.stdout


def test_session_delete_with_yes(tmp_path, monkeypatch):
    """session delete --yes should remove the file."""
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    session_file = tmp_path / "test_delete.json"
    session_file.write_text("{}", encoding="utf-8")

    result = runner.invoke(app, ["session", "delete", "test_delete", "--yes"])
    assert result.exit_code == 0
    assert not session_file.is_file()


def test_session_delete_missing():
    """session delete non-existent with --yes should error."""
    result = runner.invoke(app, ["session", "delete", "does_not_exist", "--yes"])
    assert "not found" in result.stdout.lower()


def test_session_delete_without_yes_confirm(tmp_path, monkeypatch):
    """session delete without --yes should confirm then delete."""
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    session_file = tmp_path / "confirm_delete.json"
    session_file.write_text("{}", encoding="utf-8")

    with patch("rich.prompt.Confirm.ask", return_value=True):
        result = runner.invoke(app, ["session", "delete", "confirm_delete"])
        assert result.exit_code == 0
        assert not session_file.is_file()


def test_session_delete_without_yes_cancel(tmp_path, monkeypatch):
    """session delete without --yes and answering no should cancel."""
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    session_file = tmp_path / "cancel_delete.json"
    session_file.write_text("{}", encoding="utf-8")

    with patch("rich.prompt.Confirm.ask", return_value=False):
        result = runner.invoke(app, ["session", "delete", "cancel_delete"])
        assert result.exit_code == 0
        assert session_file.is_file()
