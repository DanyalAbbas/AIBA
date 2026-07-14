"""Tests for src.cli.commands.beat — beat subcommand."""

from __future__ import annotations

from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


def test_beat_help():
    """beat --help should show subcommands."""
    result = runner.invoke(app, ["beat", "--help"])
    assert result.exit_code == 0
    assert "list" in result.stdout
    assert "run" in result.stdout
    assert "schedule" in result.stdout


def test_beat_list_no_beats(monkeypatch):
    """beat list with no beats configured should show info."""
    monkeypatch.setattr("src.services.beats.load_beats", lambda: {})
    result = runner.invoke(app, ["beat", "list"])
    assert result.exit_code == 0
    assert "No beats" in result.stdout


def test_beat_list_with_beats(monkeypatch):
    """beat list should display configured beats."""
    from src.services.beats import BeatConfig

    mock_beats = {
        "morning_scan": BeatConfig(
            name="morning_scan",
            schedule="0 9 * * *",
            template="default",
            effort="balanced",
            mode="agent",
            sub_agents=3,
        ),
    }
    monkeypatch.setattr("src.services.beats.load_beats", lambda: mock_beats)
    result = runner.invoke(app, ["beat", "list"])
    assert result.exit_code == 0
    assert "morning_scan" in result.stdout


def test_beat_list_with_full_details(monkeypatch):
    """beat list should display optional fields when present."""
    from src.services.beats import BeatConfig

    mock_beats = {
        "full_beat": BeatConfig(
            name="full_beat",
            schedule="*/5 * * * *",
            template="default",
            effort="max",
            mode="swarm",
            sub_agents=10,
            prompt_extra="extra context for the beat",
            allowed_csvs=["data.csv"],
            notify_email="admin@example.com",
        ),
    }
    monkeypatch.setattr("src.services.beats.load_beats", lambda: mock_beats)
    result = runner.invoke(app, ["beat", "list"])
    assert result.exit_code == 0
    assert "full_beat" in result.stdout
    assert "extra context" in result.stdout
    assert "data.csv" in result.stdout
    assert "admin@example.com" in result.stdout


def test_beat_run_without_name():
    """beat run without name and without --all should show usage."""
    result = runner.invoke(app, ["beat", "run"])
    assert "Usage" in result.stdout


def test_beat_run_single(monkeypatch):
    """beat run with name should execute that beat."""
    monkeypatch.setattr("src.services.beats.run_beat", lambda name: {
        "status": "success", "output": "test result", "errors": [],
    })
    result = runner.invoke(app, ["beat", "run", "test_beat"])
    assert result.exit_code == 0
    assert "test result" in result.stdout


def test_beat_run_with_errors(monkeypatch):
    """beat run should display errors."""
    monkeypatch.setattr("src.services.beats.run_beat", lambda name: {
        "status": "error", "output": "", "errors": ["Something broke"],
    })
    result = runner.invoke(app, ["beat", "run", "failing_beat"])
    assert result.exit_code == 0
    assert "Something broke" in result.stdout


def test_beat_run_all(monkeypatch):
    """beat run --all should run all due beats."""
    monkeypatch.setattr("src.services.beats.run_all_due", lambda: [
        {"beat": "a", "status": "success", "output": "ok"},
        {"beat": "b", "status": "error", "output": "fail"},
    ])
    result = runner.invoke(app, ["beat", "run", "--all"])
    assert result.exit_code == 0


def test_beat_schedule(capsys):
    """beat schedule should show OS instructions."""
    result = runner.invoke(app, ["beat", "schedule"])
    assert result.exit_code == 0
    assert len(result.stdout) > 0
