"""AIBA CLI entry point.

Usage:
    aiba run [prompt] [--mode] [--template] [--effort] [--interactive]
    aiba beat {list,run,schedule}
    aiba config {show,set,list,init}
    aiba session {list,load,delete}
    aiba --version --help
"""


import typer

from src.cli.commands import beat, config, session
from src.cli.commands.run import run_command

app = typer.Typer(
    name="aiba",
    help="AIBA — Autonomous Internet Browsing Agent",
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
)

app.add_typer(config.app, name="config", help="Manage configuration")
app.add_typer(session.app, name="session", help="Manage saved sessions")
app.add_typer(beat.app, name="beat", help="Manage and run scheduled beats")


@app.command()
def run(
    prompt: str | None = typer.Argument(
        None,
        help="Task description for the agent. If omitted, launches the interactive wizard.",
    ),
    mode: str = typer.Option("agent", "--mode", "-m", help="Execution mode: agent | swarm"),
    template: str = typer.Option("default", "--template", "-t", help="Prompt template"),
    effort: str = typer.Option("balanced", "--effort", "-e", help="Effort level: quick | balanced | max"),
    sub_agents: int = typer.Option(5, "--sub-agents", "-s", help="Max concurrent sub-agents (swarm only)"),
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Force interactive wizard even with a prompt",
    ),
) -> None:
    """Execute the agent with a prompt.

    If PROMPT is provided, runs non-interactively using the given options.
    If PROMPT is omitted, launches the interactive setup wizard.
    """
    run_command(
        prompt=prompt,
        mode=mode,
        template=template,
        effort=effort,
        sub_agents=sub_agents,
        interactive=interactive,
    )


def _version_callback(version_flag: bool = False) -> None:
    if version_flag:
        from importlib.metadata import version

        try:
            ver = version("aiba")
        except Exception:
            ver = "0.2.0"  # fallback for dev installs
        typer.echo(f"aiba v{ver}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", help="Show version and exit", callback=_version_callback,
    ),
) -> None:
    """AIBA — Autonomous Internet Browsing Agent."""
    pass


def entry_point() -> None:
    """Console-scripts entry point."""
    app()


if __name__ == "__main__":
    app()
