"""Tests for src.cli.commands.session — session subcommand."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()
_SESSIONS_DIR = Path("sessions")


def test_session_help():
    """session --help should show subcommands."""
    result = runner.invoke(app, ["session", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "load" in result.stdout
    assert "delete" in result.stdout


def test_session_list_no_sessions(tmp_path, monkeypatch):
    """session list with no saved sessions should show appropriate message."""
    monkeypatch.setattr("src.services.session.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    result = runner.invoke(app, ["session", "list"])
    assert result.exit_code == 0
    assert "No saved" in result.stdout or "No sessions" in result.stdout


def test_session_list_with_sessions(tmp_path, monkeypatch):
    """session list should display session names."""
    monkeypatch.setattr("src.services.session.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    (tmp_path / "mysession.json").write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["session", "list"])
    assert result.exit_code == 0
    assert "mysession" in result.stdout


def test_session_load_not_found():
    """session load with non-existent name should show error."""
    result = runner.invoke(app, ["session", "load", "nonexistent"])
    assert "not found" in result.stdout.lower() or "Not found" in result.stdout


def test_session_delete_not_found_with_yes():
    """session delete with --yes and non-existent name should error."""
    result = runner.invoke(app, ["session", "delete", "nonexistent", "--yes"])
    assert "not found" in result.stdout.lower()


def test_session_delete_success(tmp_path, monkeypatch):
    """session delete should remove the session file."""
    monkeypatch.setattr("src.cli.commands.session._SESSIONS_DIR", tmp_path)
    session_file = tmp_path / "test_session.json"
    session_file.write_text("{}", encoding="utf-8")
    assert session_file.is_file()

    result = runner.invoke(app, ["session", "delete", "test_session", "--yes"])
    assert result.exit_code == 0
    assert not session_file.is_file()


def test_sessions_dir_is_path():
    """_SESSIONS_DIR should be a Path."""
    from src.cli.commands.session import _SESSIONS_DIR
    assert isinstance(_SESSIONS_DIR, Path)


def test_session_result_shim():
    """_SessionResult should wrap messages list."""
    from src.cli.commands.session import _SessionResult
    shim = _SessionResult(["msg1"])
    assert shim.all_messages() == ["msg1"]
    assert shim.new_messages() == ["msg1"]
