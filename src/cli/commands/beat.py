"""`aiba beat` subcommand — manage and run scheduled beats."""


import typer

app = typer.Typer(
    name="beat",
    help="Manage and run scheduled beats",
    rich_markup_mode="rich",
)


@app.command()
def list() -> None:
    """List all configured beats."""
    from src.services import beats as svc
    from src.services import rendering as R

    configured = svc.load_beats()
    if not configured:
        R.console.print(R.panel_info("No beats", "No beats configured. Edit beats.yaml to add one."))
        return

    rows = []
    for name, beat in configured.items():
        rows.append((name, beat.schedule, beat.mode, beat.template, beat.effort))

    table = R.table(
        ("Name", "Schedule", "Mode", "Template", "Effort"),
        rows,
        title="Beats",
    )
    R.console.print(table)

    for name, beat in configured.items():
        R.console.print()
        R.console.print(f"  [bold green]{name}[/bold green]")
        R.console.print(f"  [dim]Schedule:[/dim]   {beat.schedule}")
        R.console.print(f"  [dim]Mode:[/dim]       {beat.mode}")
        R.console.print(f"  [dim]Template:[/dim]   {beat.template}")
        R.console.print(f"  [dim]Effort:[/dim]     {beat.effort}")
        R.console.print(f"  [dim]Sub-agents:[/dim] {beat.sub_agents}")
        if beat.prompt_extra:
            R.console.print(f"  [dim]Extra:[/dim]      {beat.prompt_extra[:80]}")
        if beat.allowed_csvs:
            R.console.print(f"  [dim]CSVs:[/dim]       {', '.join(beat.allowed_csvs)}")
        if beat.notify_email:
            R.console.print(f"  [dim]Notify:[/dim]     {beat.notify_email}")
    R.console.print()


@app.command()
def run(
    name: str | None = typer.Argument(None, help="Beat name to run"),
    all: bool = typer.Option(False, "--all", help="Run all due beats"),
) -> None:
    """Run a specific beat or all due beats."""
    from src.services import beats as svc
    from src.services import rendering as R

    if all:
        results = svc.run_all_due()
        for r in results:
            status = r.get("status", "?")
            icon = {
                "success": "[green]✓[/green]",
                "error": "[red]✗[/red]",
                "skipped": "[dim]○[/dim]",
            }.get(status, "[dim]?[/dim]")
            out = (r.get("output") or "")[:100]
            R.console.print(f"  {icon} {r.get('beat', '?')}: {out}")
        return

    if not name:
        typer.echo("Usage: aiba beat run [NAME]")
        typer.echo("       aiba beat run --all")
        raise typer.Exit(code=1)

    result = svc.run_beat(name)
    status = result.get("status", "?")
    icon = {
        "success": "[green]✓[/green]",
        "error": "[red]✗[/red]",
        "skipped": "[dim]○[/dim]",
    }.get(status, "[dim]?[/dim]")
    R.console.print(f"  {icon} {name}: {status}")
    if result.get("output"):
        R.render_markdown(result["output"])
    if result.get("errors"):
        for err in result["errors"]:
            R.console.print(f"  [red]✗[/red] {err}")


@app.command()
def schedule() -> None:
    """Show OS scheduler setup instructions."""
    from src.services import beats as svc
    from src.services import rendering as R

    R.console.print()
    R.console.print(svc.os_schedule_instructions())
    R.console.print()
