"""Backward-compatible entry point for AIBA.

⚠ DEPRECATED: Use `python -m src` or the `aiba` CLI command instead.

This file is kept for backward compatibility with existing scripts and cron jobs.
"""

import sys


def _deprecation_warning() -> None:
    """Print a deprecation notice and delegate to the Typer-based CLI."""
    import warnings

    warnings.warn(
        "main.py is deprecated. Use 'python -m src' or the 'aiba' command instead.",
        DeprecationWarning,
        stacklevel=2,
    )


if __name__ == "__main__":
    _deprecation_warning()

    # Delegate to the new CLI app
    from src.cli import app

    sys.exit(app())
