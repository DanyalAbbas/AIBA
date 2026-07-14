"""Tests for src.services.rendering — Rich-based rendering primitives."""

from __future__ import annotations

import pytest

from src.services.rendering import C, badge, divider, hr, render_markdown

# ── C palette (kept for backward compat) ─────────────────────────────

_REQUIRED_TOKENS = ("reset", "bold", "dim", "purple", "teal", "green", "yellow", "red")


def test_c_palette_has_all_tokens():
    for token in _REQUIRED_TOKENS:
        assert token in C, f"Missing ANSI token: {token}"


def test_c_values_are_non_empty():
    for token in _REQUIRED_TOKENS:
        assert len(C[token]) > 0, f"ANSI token '{token}' is empty"


# ── badge ────────────────────────────────────────────────────────────


def test_badge_contains_both_strings():
    result = badge("Mode", "swarm")
    assert "Mode" in result
    assert "swarm" in result


# ── divider / hr (both print via Rich Rule, return None) ─────────────


def test_divider_is_callable():
    """divider should not crash when called."""
    try:
        divider()
    except Exception as exc:
        pytest.fail(f"divider raised: {exc}")


def test_hr_is_alias_for_divider():
    """hr should be the same function as divider."""
    assert hr is divider


def test_divider_respects_custom_char():
    """divider with custom char should not crash."""
    try:
        divider(char="=")
    except Exception as exc:
        pytest.fail(f"divider(char='=') raised: {exc}")


# ── render_markdown (smoke) ──────────────────────────────────────────


def test_render_markdown_does_not_raise():
    """Smoke test: render_markdown must not crash on basic Markdown."""
    try:
        render_markdown(text="**hello**")
    except Exception as exc:
        pytest.fail(f"render_markdown raised: {exc}")
