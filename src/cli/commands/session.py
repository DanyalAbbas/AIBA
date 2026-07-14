"""`aiba session` subcommand — manage saved sessions."""

from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from rich.prompt import Confirm

from src.services import rendering as R

_SESSIONS_DIR = Path("sessions")


class _SessionResult:
    """Minimal AgentRunResult shim wrapping saved session history.

    Cast to AgentRunResult when passing to the REPL.
    """
    def __init__(self, messages: list[Any]) -> None:
        self._messages = messages

    def all_messages(self) -> list[Any]:
        return self._messages

    new_messages = all_messages

app = typer.Typer(
    name="session",
    help="Manage saved sessions",
    rich_markup_mode="rich",
)


@app.command()
def list() -> None:
    """List saved sessions."""
    from src.services.session import list_sessions

    available = list_sessions()
    if not available:
        R.console.print(R.panel_info("No sessions", f"No saved sessions found in {_SESSIONS_DIR}/"))
        return

    rows = []
    for name in available:
        path = _SESSIONS_DIR / f"{name}.json"
        if path.is_file():
            mtime_dt = datetime.fromtimestamp(path.stat().st_mtime)
            mtime_str = mtime_dt.strftime("%Y-%m-%d %H:%M")
            size = path.stat().st_size
            rows.append((name, mtime_str, f"{size}B"))

    table = R.table(
        ("Name", "Last Modified", "Size"),
        rows,
        title="Saved Sessions",
    )
    R.console.print(table)


@app.command()
def load(
    name: str = typer.Argument(..., help="Session name to load"),
) -> None:
    """Load and resume a saved session."""
    from src.prompts import EffortMode, get_effort_config
    from src.services.session import load_session, print_history

    try:
        history, saved_settings = load_session(name)
    except FileNotFoundError:
        R.console.print(R.panel_error("Not found", f"Session '{name}' not found in {_SESSIONS_DIR}/"))
        raise typer.Exit(code=1) from None
    except Exception as exc:
        R.console.print(R.panel_error("Load failed", f"{type(exc).__name__}: {exc}"))
        raise typer.Exit(code=1) from exc

    from typing import cast

    from pydantic_ai.run import AgentRunResult

    fake = cast(AgentRunResult, _SessionResult(history))

    if not saved_settings:
        from src.agents.sub_agent import run as run_agent
        from src.services.repl import run as run_repl

        config = get_effort_config(EffortMode.BALANCED)
        R.console.print()
        R.divider()
        print_history(history)
        run_repl(run_agent, fake, config, "Agent", {"mode": "agent", "effort": "balanced"})
        return

    from src.agents.main_agent import run as run_orch
    from src.agents.sub_agent import run as run_agent

    mode_val = saved_settings.get("mode", "agent")
    effort_str = saved_settings.get("effort", "balanced")

    try:
        effort_val = EffortMode(effort_str)
    except ValueError:
        effort_val = EffortMode.BALANCED

    agent_fn = run_orch if mode_val == "swarm" else run_agent
    agent_name = "Orchestrator" if mode_val == "swarm" else "Agent"
    config = get_effort_config(effort_val)

    R.console.print()
    R.divider()
    R.console.print(f"  [green]✓[/green] Resuming session [bold]{name}[/bold] ({len(history)} messages)")
    R.divider()

    print_history(history)

    from src.services.repl import run as run_repl
    run_repl(agent_fn, fake, config, agent_name, dict(saved_settings))


@app.command()
def delete(
    name: str = typer.Argument(..., help="Session name to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a saved session."""
    if not yes:
        confirmed = Confirm.ask(f"Delete session [bold]{name}[/bold]?")
        if not confirmed:
            R.console.print("[dim]Cancelled.[/dim]")
            return

    path = _SESSIONS_DIR / f"{name}.json"
    if not path.is_file():
        R.console.print(R.panel_error("Not found", f"Session '{name}' not found"))
        raise typer.Exit(code=1)

    path.unlink()
    R.console.print(R.panel_success(f"Deleted session '{name}'"))
