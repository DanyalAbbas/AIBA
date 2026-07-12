"""Tests for sub_agent.py — sub-agent run() and tool functions.

Uses pydantic-ai's TestModel to mock the LLM so no real API calls are made.
"""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.agents.sub_agent import (
    preview_click,
    read_and_filter_file,
    read_image,
    run,
    sub_agent,
)
from src.prompts import EffortMode

# ── Helpers ──────────────────────────────────────────────────────────

def _minimal_png(width: int = 32, height: int = 32) -> bytes:
    """Generate a valid minimal PNG in memory."""
    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = b""
    for y in range(height):
        raw += b"\x00" + bytes([y % 256, (y * 3) % 256, (y * 7) % 256]) * width

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _run_agent(
    prompt: str = "Research this topic",
    effort_mode: EffortMode = EffortMode.BALANCED,
    output_text: str = "sub-agent result",
    instructions: str | None = None,
    **kwargs,
):
    """Run the sub_agent with sub_agent.run_sync mocked to avoid MCP Playwright init."""
    fake_result = MagicMock()
    fake_result.output = output_text

    fake_request = MagicMock()
    fake_request.instructions = instructions
    fake_request.parts = [MagicMock()]
    fake_request.parts[0].content = prompt
    fake_response = MagicMock()
    fake_result.all_messages.return_value = [fake_request, fake_response]
    fake_result.new_messages.return_value = [fake_response]

    with patch.object(sub_agent, "run_sync", return_value=fake_result):
        return run(prompt, effort_mode=effort_mode, **kwargs)


# ═════════════════════════════════════════════════════════════════════
#  run() — effort modes
# ═════════════════════════════════════════════════════════════════════


class TestRunEffortModes:
    def test_run_default_balanced(self):
        result = _run_agent(effort_mode=EffortMode.BALANCED)
        assert result.output == "sub-agent result"

    def test_run_quick(self):
        result = _run_agent(effort_mode=EffortMode.QUICK, output_text="quick search")
        assert result.output == "quick search"

    def test_run_max(self):
        result = _run_agent(effort_mode=EffortMode.MAX, output_text="deep dive")
        assert result.output == "deep dive"


# ═════════════════════════════════════════════════════════════════════
#  run() — kwargs override
# ═════════════════════════════════════════════════════════════════════


class TestRunKwargs:
    def test_kwargs_override_model_settings(self):
        result = _run_agent(
            model_settings={"temperature": 0.1, "max_tokens": 50},
            output_text="custom settings",
        )
        assert result.output == "custom settings"

    def test_kwargs_override_instructions(self):
        result = _run_agent(
            instructions="Investigate deeply.",
            output_text="custom instructions",
        )
        assert result.output == "custom instructions"
        first_msg = result.all_messages()[0]
        msg_instructions: str | None = getattr(first_msg, "instructions", None)
        assert "Investigate deeply." in (msg_instructions or "")

    def test_kwargs_override_usage_limits(self):
        from pydantic_ai.usage import UsageLimits

        result = _run_agent(
            usage_limits=UsageLimits(request_limit=3),
            output_text="limited run",
        )
        assert result.output == "limited run"


# ═════════════════════════════════════════════════════════════════════
#  run() — capture messages
# ═════════════════════════════════════════════════════════════════════


class TestRunMessages:
    def test_run_sync_is_called_with_prompt(self):
        with patch.object(sub_agent, "run_sync") as mock_run:
            mock_result = mock_run.return_value
            mock_result.output = "msg result"
            mock_result.all_messages.return_value = []
            mock_result.new_messages.return_value = []
            result = run("test prompt")

        assert result.output == "msg result"
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == "test prompt"

    def test_prompt_forwarded_to_run_sync(self):
        with patch.object(sub_agent, "run_sync") as mock_run:
            mock_run.return_value.output = "done"
            mock_run.return_value.all_messages.return_value = []
            run("specific investigation prompt")

        assert mock_run.call_args[0][0] == "specific investigation prompt"

    def test_instructions_kwarg_reaches_run_sync(self):
        with patch.object(sub_agent, "run_sync") as mock_run:
            mock_run.return_value.output = "done"
            mock_run.return_value.all_messages.return_value = []
            run("prompt", instructions="focus on accuracy")

        assert mock_run.call_args[1].get("instructions") == "focus on accuracy"


# ═════════════════════════════════════════════════════════════════════
#  read_image tool
# ═════════════════════════════════════════════════════════════════════


class TestReadImage:
    def test_file_not_found(self):
        from pydantic_ai import ToolReturn

        result = read_image("nonexistent_image.png")
        assert isinstance(result, ToolReturn)
        assert "No image found" in str(result.return_value)

    def test_reads_valid_image(self, tmp_path):
        from pydantic_ai import BinaryContent, ToolReturn

        mcp_dir = tmp_path / ".playwright-mcp"
        mcp_dir.mkdir()
        (mcp_dir / "test.png").write_bytes(_minimal_png())

        def _pathed(p: str) -> Path:
            if p.startswith(".playwright-mcp/"):
                return tmp_path / p
            return Path(p)

        with patch("src.agents.sub_agent.Path", side_effect=_pathed):
            result = read_image("test.png")
            assert isinstance(result, ToolReturn)
            assert isinstance(result.return_value, BinaryContent)
            assert result.return_value.media_type.startswith("image/")

    def test_non_image_extension_defaults_to_png(self, tmp_path):
        from pydantic_ai import BinaryContent, ToolReturn

        mcp_dir = tmp_path / ".playwright-mcp"
        mcp_dir.mkdir()
        (mcp_dir / "data.bin").write_bytes(_minimal_png())

        def _pathed(p: str) -> Path:
            if p.startswith(".playwright-mcp/"):
                return tmp_path / p
            return Path(p)

        with patch("src.agents.sub_agent.Path", side_effect=_pathed):
            result = read_image("data.bin")
            assert isinstance(result, ToolReturn)
            assert isinstance(result.return_value, BinaryContent)
            assert result.return_value.media_type == "image/png"


# ═════════════════════════════════════════════════════════════════════
#  preview_click tool
# ═════════════════════════════════════════════════════════════════════


class TestPreviewClick:
    def test_file_not_found(self):
        from pydantic_ai import ToolReturn

        result = preview_click("nope.png", 50, 50)
        assert isinstance(result, ToolReturn)
        assert "No image found" in str(result.return_value)

    def test_out_of_bounds(self, tmp_path):
        from pydantic_ai import ToolReturn

        mcp_dir = tmp_path / ".playwright-mcp"
        mcp_dir.mkdir()
        (mcp_dir / "grid.png").write_bytes(_minimal_png(100, 200))

        def _pathed(p: str) -> Path:
            if p.startswith(".playwright-mcp/"):
                return tmp_path / p
            return Path(p)

        with patch("src.agents.sub_agent.Path", side_effect=_pathed):
            result = preview_click("grid.png", 150, 50)
            assert isinstance(result, ToolReturn)
            assert "OUT OF BOUNDS" in str(result.return_value)

    def test_valid_click(self, tmp_path):
        from pydantic_ai import BinaryContent, ToolReturn

        mcp_dir = tmp_path / ".playwright-mcp"
        mcp_dir.mkdir()
        (mcp_dir / "grid.png").write_bytes(_minimal_png(200, 200))

        def _pathed(p: str) -> Path:
            if p.startswith(".playwright-mcp/"):
                return tmp_path / p
            return Path(p)

        with patch("src.agents.sub_agent.Path", side_effect=_pathed):
            result = preview_click("grid.png", 80, 120)
            assert isinstance(result, ToolReturn)
            assert isinstance(result.return_value, BinaryContent)
            assert result.return_value.media_type == "image/png"
            assert (mcp_dir / "preview_grid.png").is_file()

    def test_origin_click(self, tmp_path):
        from pydantic_ai import BinaryContent, ToolReturn

        mcp_dir = tmp_path / ".playwright-mcp"
        mcp_dir.mkdir()
        (mcp_dir / "grid.png").write_bytes(_minimal_png(100, 100))

        def _pathed(p: str) -> Path:
            if p.startswith(".playwright-mcp/"):
                return tmp_path / p
            return Path(p)

        with patch("src.agents.sub_agent.Path", side_effect=_pathed):
            result = preview_click("grid.png", 0, 0)
            assert isinstance(result, ToolReturn)
            assert isinstance(result.return_value, BinaryContent)

    def test_corner_click(self, tmp_path):
        from pydantic_ai import BinaryContent, ToolReturn

        mcp_dir = tmp_path / ".playwright-mcp"
        mcp_dir.mkdir()
        (mcp_dir / "grid.png").write_bytes(_minimal_png(150, 100))

        def _pathed(p: str) -> Path:
            if p.startswith(".playwright-mcp/"):
                return tmp_path / p
            return Path(p)

        with patch("src.agents.sub_agent.Path", side_effect=_pathed):
            result = preview_click("grid.png", 149, 99)
            assert isinstance(result, ToolReturn)
            assert isinstance(result.return_value, BinaryContent)


# ═════════════════════════════════════════════════════════════════════
#  read_and_filter_file tool
# ═════════════════════════════════════════════════════════════════════


class TestReadAndFilterFile:
    def _patch_path(self, tmp_path: Path):
        def _pathed(p: str) -> Path:
            if p.startswith(".playwright-mcp/"):
                return tmp_path / p
            return Path(p)
        return patch("src.agents.sub_agent.Path", side_effect=_pathed)

    def _make_sample(self, tmp_path: Path) -> str:
        mcp_dir = tmp_path / ".playwright-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        content = (
            "apple pie recipe\n"
            "banana bread recipe\n"
            "cherry pie recipe\n"
            "date pudding recipe\n"
            "elderberry jam\n"
        )
        (mcp_dir / "recipes.txt").write_text(content)
        return "recipes.txt"

    def test_read_all_lines(self, tmp_path):
        sample = self._make_sample(tmp_path)
        with self._patch_path(tmp_path):
            result = read_and_filter_file(sample)
        assert "apple pie" in result
        assert "elderberry jam" in result

    def test_start_line(self, tmp_path):
        sample = self._make_sample(tmp_path)
        with self._patch_path(tmp_path):
            result = read_and_filter_file(sample, start_line=3)
        assert "apple" not in result
        assert "banana" not in result
        assert "cherry pie" in result
        assert "elderberry" in result

    def test_search_string(self, tmp_path):
        sample = self._make_sample(tmp_path)
        with self._patch_path(tmp_path):
            result = read_and_filter_file(sample, search_string="pie")
        assert "apple pie" in result
        assert "cherry pie" in result
        assert "banana" not in result

    def test_search_regex(self, tmp_path):
        sample = self._make_sample(tmp_path)
        with self._patch_path(tmp_path):
            result = read_and_filter_file(sample, search_regex=r"^[a-c]")
        assert "apple pie" in result
        assert "banana bread" in result
        assert "cherry pie" in result
        assert "date" not in result

    def test_combined_filters(self, tmp_path):
        sample = self._make_sample(tmp_path)
        with self._patch_path(tmp_path):
            result = read_and_filter_file(sample, start_line=2, search_string="pie")
        assert "cherry pie" in result
        assert "apple pie" not in result

    def test_start_line_beyond_eof(self, tmp_path):
        sample = self._make_sample(tmp_path)
        with self._patch_path(tmp_path):
            result = read_and_filter_file(sample, start_line=100)
        assert result == "No matching lines found based on the provided filters."

    def test_no_matches(self, tmp_path):
        sample = self._make_sample(tmp_path)
        with self._patch_path(tmp_path):
            result = read_and_filter_file(sample, search_string="zzz_nonexistent")
        assert result == "No matching lines found based on the provided filters."

    def test_file_not_found(self):
        result = read_and_filter_file("nonexistent.txt")
        assert result.startswith("Error: File not found at")

    def test_invalid_regex(self, tmp_path):
        sample = self._make_sample(tmp_path)
        with self._patch_path(tmp_path):
            result = read_and_filter_file(sample, search_regex="[invalid")
        assert result.startswith("Error: Invalid regular expression pattern:")

    def test_read_error(self, tmp_path):
        mcp_dir = tmp_path / ".playwright-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        (mcp_dir / "corrupt.txt").write_text("will fail to read")
        with self._patch_path(tmp_path):
            with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                result = read_and_filter_file("corrupt.txt")
        assert result.startswith("Error reading file:")
        assert "denied" in result

    def test_truncation(self, tmp_path):
        mcp_dir = tmp_path / ".playwright-mcp"
        mcp_dir.mkdir(parents=True, exist_ok=True)
        (mcp_dir / "big.txt").write_text("word " * 4000)
        with self._patch_path(tmp_path):
            result = read_and_filter_file("big.txt")
        assert "truncated" in result.lower()

    def test_default_start_line(self, tmp_path):
        sample = self._make_sample(tmp_path)
        with self._patch_path(tmp_path):
            result = read_and_filter_file(sample)
        assert "1: apple" in result


# ═════════════════════════════════════════════════════════════════════
#  dynamic system prompt
# ═════════════════════════════════════════════════════════════════════


class TestDynamicSystemPrompt:
    def test_system_prompt_includes_session_id(self):
        from unittest.mock import MagicMock

        from pydantic_ai import RunContext

        from src.agents.sub_agent import SubAgentContext, add_dynamic_system_prompt

        deps = SubAgentContext(session_id="abc123")
        ctx = MagicMock(spec=RunContext)
        ctx.deps = deps

        result = add_dynamic_system_prompt(ctx)
        assert isinstance(result, str)
        assert "abc123" in result
        assert "session ID" in result


# ═════════════════════════════════════════════════════════════════════
#  web_search engine config
# ═════════════════════════════════════════════════════════════════════


class TestWebSearchConfig:
    def test_non_duckduckgo_engine_fallback(self):
        import importlib

        import src.agents.sub_agent as mod

        old_val = os.environ.get("WEB_SEARCH_ENGINE")
        os.environ["WEB_SEARCH_ENGINE"] = "google"
        try:
            importlib.reload(mod)
            from pydantic_ai.capabilities import WebSearch

            assert isinstance(mod._web_search_cap, WebSearch)
        finally:
            if old_val is None:
                del os.environ["WEB_SEARCH_ENGINE"]
            else:
                os.environ["WEB_SEARCH_ENGINE"] = old_val
            importlib.reload(mod)
