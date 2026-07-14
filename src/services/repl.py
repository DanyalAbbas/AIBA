"""Interactive REPL loop with persistent chat history and Rich styling."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.run import AgentRunResult

from src.prompts import EffortConfig
from src.services import rendering as R
from src.services.session import (
    SESSIONS_DIR,
    save_session,
    trim_history,
)


def _setup_readline() -> None:
    """Configure readline with history persistence.

    Wrapped in a function so tests can exercise each code path.
    """
    try:
        import atexit
        import readline
    except ImportError:
        return  # readline not available (edge case)

    _HISTORY_FILE = Path.home() / ".aiba_history"
    try:
        readline.read_history_file(str(_HISTORY_FILE))
    except (FileNotFoundError, OSError):
        pass  # First run, no history yet
    readline.set_history_length(1000)
    atexit.register(
        lambda: readline.write_history_file(str(_HISTORY_FILE))
        if hasattr(readline, "write_history_file") and _HISTORY_FILE.parent.is_dir()
        else None,
    )


_setup_readline()

_HELP = (
    "  [bold]Commands:[/bold]\n"
    "  [bold cyan]/exit, /quit[/bold cyan]   End the session\n"
    "  [bold cyan]/clear[/bold cyan]         Reset history (keeps system prompt)\n"
    "  [bold cyan]/history[/bold cyan]       Show message count\n"
    "  [bold cyan]/save <name>[/bold cyan]  Save conversation to sessions/<name>.json\n"
    "  [bold cyan]/help[/bold cyan]          Show this message\n"
    "  [bold cyan]/stats[/bold cyan]         Show session statistics\n"
)


def run(
    agent_fn: Callable[..., AgentRunResult],
    initial_result: AgentRunResult,
    config: EffortConfig,
    agent_name: str = "Agent",
    session_settings: dict[str, Any] | None = None,
) -> None:
    """Interactive REPL loop with persistent chat history."""
    history = initial_result.all_messages()
    if session_settings is None:
        session_settings = {}

    R.console.print(
        R.panel_info(
            "Session started",
            "Type [bold]/exit[/bold] to quit, [bold]/clear[/bold] to reset, [bold]/help[/bold] for commands.",
        )
    )

    while True:
        try:
            user_input = R.console.input("  [bold cyan]▸[/bold cyan]  ").strip()
        except (EOFError, KeyboardInterrupt):
            R.console.print("\n[dim]Session ended.[/dim]")
            break

        if not user_input:
            continue

        lower = user_input.lower()

        if lower in ("/exit", "/quit"):
            R.console.print("[dim]Session ended.[/dim]")
            break

        if lower == "/clear":
            history = initial_result.all_messages()[:1]
            R.console.print("[dim]History cleared. System prompt preserved.[/dim]")
            continue

        if lower == "/history":
            R.console.print(f"  [dim]Messages in history: {len(history)}[/dim]")
            continue

        if lower == "/stats":
            R.console.print(f"  [dim]Messages: {len(history)}[/dim]")
            R.console.print(f"  [dim]Agent: {agent_name}[/dim]")
            if session_settings:
                for k, v in session_settings.items():
                    R.console.print(f"  [dim]{k}: {v}[/dim]")
            continue

        if lower.startswith("/save "):
            raw = user_input[6:].strip()
            name = Path(raw).stem
            if not name:
                R.console.print("[red]✗[/red]  Usage: /save <name>")
                continue
            try:
                save_session(name, history, session_settings)
                R.console.print(
                    f"[green]✓[/green] Session saved to {SESSIONS_DIR / name.split('.')[0]}.json"
                    f" ({len(history)} messages)",
                )
            except Exception as exc:
                R.console.print(f"[red]✗[/red] Failed to save: {exc}")
            continue

        if lower == "/help":
            R.console.print(_HELP)
            continue

        if lower.startswith("/"):
            R.console.print(f"[red]✗[/red]  Unknown command: '{user_input}'")
            R.console.print(_HELP)
            continue

        # Normal user message — run the agent
        R.console.print("[dim]Thinking...[/dim]", end="\r")
        try:
            instructions_key = (
                "main_instructions" if agent_name == "Orchestrator" else "instructions"
            )
            result = agent_fn(
                user_input,
                message_history=history,
                instructions=config.get(instructions_key),
                model_settings=config["model_settings"],
                usage_limits=config["usage_limits"],
            )
            R.console.print("           ", end="\r")

            R.console.print()
            R.divider()
            R.render_markdown(result.output)
            R.divider()
            R.console.print()

            history = trim_history(result.all_messages())

        except UsageLimitExceeded as exc:
            R.console.print(f"\n[yellow]⚠[/yellow]  Resource limit hit: {exc}")
            R.console.print(
                "[dim]Try a shorter prompt or use /clear to reset.[/dim]",
            )
        except Exception as exc:
            R.console.print(f"\n[red]✗[/red]  Error: {type(exc).__name__}: {exc}")
