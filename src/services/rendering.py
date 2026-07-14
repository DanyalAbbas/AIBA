"""Rich-based rendering primitives for AIBA CLI output."""

from __future__ import annotations

import shutil
from typing import Any

from rich.console import Console as RichConsole
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# Shared Rich console (single instance)
console = RichConsole(highlight=False)

# ── Legacy ANSI color map (DEPRECATED — use Rich markup instead) ─────
C: dict[str, str] = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "purple": "\033[38;5;99m",
    "teal": "\033[38;5;44m",
    "green": "\033[38;5;42m",
    "yellow": "\033[38;5;221m",
    "red": "\033[38;5;203m",
}


# ── Terminal helpers ─────────────────────────────────────────────────

def _width() -> int:
    return shutil.get_terminal_size().columns


# ── Markdown rendering ───────────────────────────────────────────────

def render_markdown(text: str) -> None:
    """Render markdown text to the console."""
    md = Markdown(text, code_theme="monokai")
    console.print(md)


# ── Dividers ─────────────────────────────────────────────────────────

def divider(char: str = "─", style: str = "dim") -> None:
    """Print a horizontal rule spanning the terminal width."""
    console.print(Rule(style=style, characters=char))


hr = divider  # backward compatibility alias


# ── Panels ───────────────────────────────────────────────────────────

def panel_error(title: str, message: str, **kwargs: Any) -> Panel:
    """Create a red-bordered error panel."""
    return Panel(
        Text(str(message), style="red"),
        title=Text(f" {title} ", style="bold red"),
        border_style="red",
        **kwargs,
    )


def panel_success(message: str, **kwargs: Any) -> Panel:
    """Create a green-bordered success panel."""
    return Panel(
        Text(str(message), style="green"),
        border_style="green",
        **kwargs,
    )


def panel_info(title: str, message: str, **kwargs: Any) -> Panel:
    """Create a blue-bordered info panel."""
    return Panel(
        Text(str(message), style="blue"),
        title=Text(f" {title} ", style="bold blue"),
        border_style="blue",
        **kwargs,
    )


def panel_warning(message: str, **kwargs: Any) -> Panel:
    """Create a yellow-bordered warning panel."""
    return Panel(
        Text(str(message), style="yellow"),
        border_style="yellow",
        **kwargs,
    )


# ── Tables ───────────────────────────────────────────────────────────

def table(
    headers: tuple[str, ...],
    rows: list[tuple[Any, ...]],
    *,
    title: str | None = None,
) -> Table:
    """Create a styled Rich Table.

    Args:
        headers: Column header strings.
        rows: List of row tuples. Each element is either a string or a Rich renderable.
        title: Optional table title.

    """
    tbl = Table(
        title=title,
        title_style="bold",
        border_style="dim",
        header_style="bold cyan",
        show_edge=False,
    )
    for header in headers:
        tbl.add_column(header)
    for row in rows:
        tbl.add_row(*row)
    return tbl


# ── Badge ────────────────────────────────────────────────────────────

def badge(label: str, value: str, label_style: str = "dim", value_style: str = "bold cyan") -> str:
    """Return a formatted label: value string.

    Legacy helper — prefer Rich console.print() with markup.
    """
    return f"  [dim]{label}:[/dim]  [bold cyan]{value}[/bold cyan]"
