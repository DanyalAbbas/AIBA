"""Tests for get_session_runtime — must NOT use _patch_get_session autouse.

This file tests the real get_session_runtime function by mocking only
async_playwright, not the function itself.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


def _reset_globals():
    """Reset module-level globals so sessions don't leak between tests."""
    import src.tools.playwright_mcp as m

    m._playwright = None
    m._browser = None
    m._contexts.clear()
    m._pages.clear()


@pytest.fixture(autouse=True)
def _clean_globals():
    """Reset globals before and after each test."""
    _reset_globals()
    yield
    _reset_globals()


class TestGetSessionRuntime:
    """Test the real get_session_runtime with mocked Playwright internals."""

    async def test_first_call_creates_browser_and_context(self):
        """When _browser is None, it launches Chromium and creates a new context."""
        from src.tools.playwright_mcp import get_session_runtime

        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw = AsyncMock()
        mock_pw.start = AsyncMock(return_value=mock_playwright)

        with patch("src.tools.playwright_mcp.async_playwright", return_value=mock_pw):
            page = await get_session_runtime("s1")

        assert page is mock_page
        mock_playwright.chromium.launch.assert_called_once()
        mock_browser.new_context.assert_called_once()
        mock_context.new_page.assert_called_once()

    async def test_second_session_shares_browser(self):
        """A second session reuses the existing browser but creates new context."""
        from src.tools.playwright_mcp import get_session_runtime

        mock_page1 = AsyncMock()
        mock_page2 = AsyncMock()
        mock_context1 = AsyncMock()
        mock_context1.new_page = AsyncMock(return_value=mock_page1)
        mock_context2 = AsyncMock()
        mock_context2.new_page = AsyncMock(return_value=mock_page2)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(side_effect=[mock_context1, mock_context2])
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw = AsyncMock()
        mock_pw.start = AsyncMock(return_value=mock_playwright)

        with patch("src.tools.playwright_mcp.async_playwright", return_value=mock_pw):
            page1 = await get_session_runtime("s1")
            page2 = await get_session_runtime("s2")

        assert page1 is mock_page1
        assert page2 is mock_page2
        # Browser launched only once
        assert mock_playwright.chromium.launch.call_count == 1
        # But two contexts created
        assert mock_browser.new_context.call_count == 2

    async def test_existing_session_returns_cached_page(self):
        """Calling with the same session_id returns the cached page."""
        from src.tools.playwright_mcp import get_session_runtime

        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw = AsyncMock()
        mock_pw.start = AsyncMock(return_value=mock_playwright)

        with patch("src.tools.playwright_mcp.async_playwright", return_value=mock_pw):
            page1 = await get_session_runtime("s1")
            page2 = await get_session_runtime("s1")

        assert page1 is page2
        # Context created only once
        assert mock_browser.new_context.call_count == 1

    async def test_storage_state_path_not_found(self):
        """When storage_state_path is set but file missing, it warns and continues."""
        import src.tools.playwright_mcp as m
        from src.tools.playwright_mcp import get_session_runtime

        old_path = m.storage_state_path
        try:
            m.storage_state_path = "/nonexistent/path/cookies.json"
            mock_page = AsyncMock()
            mock_context = AsyncMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_browser = AsyncMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_playwright = AsyncMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_pw = AsyncMock()
            mock_pw.start = AsyncMock(return_value=mock_playwright)

            with patch("src.tools.playwright_mcp.async_playwright", return_value=mock_pw):
                page = await get_session_runtime("s1")

            assert page is mock_page
            # new_context called without storage_state
            mock_browser.new_context.assert_called_once_with()
        finally:
            m.storage_state_path = old_path

    async def test_storage_state_file_exists(self, tmp_path):
        """When storage_state_path points to an existing file, it's passed to new_context."""
        import src.tools.playwright_mcp as m
        from src.tools.playwright_mcp import get_session_runtime

        # Create a real temp file
        state_file = tmp_path / "cookies.json"
        state_file.write_text('{"cookies": []}')

        old_path = m.storage_state_path
        try:
            m.storage_state_path = str(state_file)
            mock_page = AsyncMock()
            mock_context = AsyncMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)
            mock_browser = AsyncMock()
            mock_browser.new_context = AsyncMock(return_value=mock_context)
            mock_playwright = AsyncMock()
            mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
            mock_pw = AsyncMock()
            mock_pw.start = AsyncMock(return_value=mock_playwright)

            with patch("src.tools.playwright_mcp.async_playwright", return_value=mock_pw):
                page = await get_session_runtime("s1")

            assert page is mock_page
            # new_context called WITH storage_state
            mock_browser.new_context.assert_called_once_with(storage_state=str(state_file))
        finally:
            m.storage_state_path = old_path
