import mimetypes
import os
import re
from pathlib import Path
from typing import Any

import nanoid
from fastmcp.client.transports.stdio import StdioTransport
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from pydantic_ai import Agent, AgentRetries, BinaryContent, RunContext, ToolReturn
from pydantic_ai.capabilities import MCP as MCPCapability
from pydantic_ai.capabilities import (
    IncludeToolReturnSchemas,
    ReinjectSystemPrompt,
    Thinking,
    WebFetch,
    WebSearch,
)
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.run import AgentRunResult
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai_shields import InputGuard, SecretRedaction

from src.prompts import EffortMode, get_effort_config
from src.tools.common_tools import append_csv as _append_csv
from src.tools.common_tools import read_csv as _read_csv
from src.tools.common_tools import todo as _todo
from src.utils.settings import AibaSettings

STORAGE_STATE_PATH = str(Path(".playwright-mcp/cookies.json").resolve())

_settings = AibaSettings()

# @playwright/mcp respects the HEADLESS env var (0=headed/visible, 1=headless).
# Merge with os.environ so the subprocess inherits PATH, DISPLAY, HOME, etc.
mcp_env = {**os.environ, "HEADLESS": "1" if _settings.playwright_headless else "0"}

# ----- System prompt for the sub-agent -----
SYSTEM_PROMPT = """
You are an AIBA internet browsing agent. Go deep — exhaust every lead, cross-verify findings, never settle for surface-level results.

## Few-Shot Examples — match your task to the closest example.

### Example 1: Research / "tell me about"
User: "Tell me about aibacli.tech"
You:  web_search("aibacli.tech") → web_fetch(top_result_url) → compile answer → DONE.
     ✓ 2-3 tool calls. No browser.

### Example 2: Find specific info on a known site
User: "What's the price of iPhone 15 on Apple's site?"
You:  web_search("iPhone 15 price Apple official site") → web_fetch(apple.com/iphone-15) → extract price → DONE.
     ✓ web_fetch pulls the page text. No browser needed.

### Example 3: Compare / synthesize
User: "Compare React vs Vue for a startup"
You:  web_search("React vs Vue 2025 comparison") → web_fetch(2-3 articles) → synthesize → DONE.
     ✓ Multiple fetches, still no browser.

### Example 4: Log in / authenticate
User: "Log into github.com with username X and password Y"
You:  browser_navigate("https://github.com/login") → get_optimized_action_tree → browser_click(username_field) → browser_type("X") → browser_click(password_field) → browser_type("Y") → browser_click(submit_button) → browser_screenshot → DONE.
     ✓ Browser required — the task is interaction, not reading.

### Example 5: Fill and submit a form
User: "Fill out the contact form on example.com/contact"
You:  browser_navigate("https://example.com/contact") → get_optimized_action_tree → click each field → type → click submit → browser_screenshot → DONE.
     ✓ Browser from step 1 because form interaction is required.

### Example 6: Extract from a JS-heavy page
User: "Scrape the live leaderboard from example.com/scores"
You:  browser_navigate("https://example.com/scores") → browser_evaluate("document.querySelector('.leaderboard').innerText") → return data.
     ✓ Browser needed, but use evaluate/snapshot, NOT visual tools.

## Decision Rule
- Can the task be answered by READING text from the open web? → Examples 1-3 (web_search + web_fetch)
- Does the task require CLICKING, TYPING, or LOGGING IN? → Examples 4-6 (browser)

**HARD RULE**: Never browser_navigate as your first action. If web_fetch gives you the answer, STOP. Do not open the browser "just to look."

## Visual Click Loop (browser visual tools — LAST RESORT)
- browser_screenshot → read_image on the grid to read coordinates
- preview_click(grid_file, x, y) FIRST — confirm where the click lands
- Only then: browser_click_coords(x, y)
- If visual fails 2+ times → switch to DOM: get_optimized_action_tree → browser_click(mcp_id)
- Rotate visual ⇄ DOM. Never retry the same approach more than twice.

## Meta-Tool Warning
`search_tools` and `load_capability` are Pydantic AI framework admin tools — they do NOT search the web. Use `web_search` to search the internet.

**BROWSER USAGE RULE**: Always first try fast automation tools e.g. optimized_action_tree and browser_snapshot + read_and_filter_file to do the task as quickly as possible. But if the task requires visual confirmation, interaction, or JS evaluation, use the browser visual tools e.g. screenshot and coordinate click. Always prefer breadth over depth — do not exhaustively click every element unless explicitly asked.

IMPORTANT NOTE: Always make sure that you provide the correct and accurate information. If unsure then double check the information before providing it. If you are unable to find the information, then clearly state that you are unable to find the information instead of providing inaccurate or false information.
"""

# We use an alphabet that excludes easily confused characters like l, 1, O, 0
SAFE_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"

class SubAgentContext(BaseModel):
    """Contextual information for the sub-agent's execution environment."""

    # Generates a random 4-character ID by default
    session_id: str = Field(
        default_factory=lambda: nanoid.generate(SAFE_ALPHABET, size=4),
        description="Short, unique session ID for this sub-agent run."
    )
# ----- Sub-Agent Definition -----
sub_agent_model = GoogleModel(
    model_name=AibaSettings().gemini_sub_model,
    provider=GoogleProvider(api_key=AibaSettings().gemini_api_key),
)

playwright_mcp_args = [
    "run",
    "python",
    "-m",
    "src.tools.playwright_mcp",
    f"--storage-state={STORAGE_STATE_PATH}",
]

if _settings.playwright_headless:
    playwright_mcp_args.append("--headless")

# ---- Custom Playwright MCP via StdioTransport ----
playwright_transport = StdioTransport(
    command="uv",
    args=playwright_mcp_args,
    env=mcp_env,
)

playwright_cap = MCPCapability(
    local=playwright_transport,
    id="playwright",
    description="Browser automation: navigate pages, take snapshots, click elements, fill forms.",
    defer_loading=False,
)

# ----- Configurable web search -----
if _settings.web_search_engine == "duckduckgo":
    _web_search_cap = WebSearch(native=False, local="duckduckgo")
else:
    _web_search_cap = WebSearch(local="duckduckgo")

# ----- Initialize the sub-agent with the specified model -----
sub_agent = Agent(
    model=sub_agent_model,
    system_prompt=SYSTEM_PROMPT,
    deps_type=SubAgentContext,
    capabilities=[
        _web_search_cap,
        WebFetch(local=True),
        playwright_cap,
        ReinjectSystemPrompt(),
        IncludeToolReturnSchemas(
            tools=lambda ctx, td: bool(td.return_schema),
        ),
        *([SecretRedaction(), InputGuard()] if _settings.guardrails_enabled else []),
    ],
    tool_timeout=60.0,
    end_strategy="early",
    retries=AgentRetries(tools=3, output=3),
    max_concurrency=3,
)

# ---- Define dynamic system prompt for the sub agent ----
@sub_agent.system_prompt
def add_dynamic_system_prompt(ctx: RunContext[SubAgentContext]) -> str:
  return f"Note: your unique session ID is {ctx.deps.session_id}. Use this ID in all tool calls and outputs."

# ----- Define tools for the sub-agent -----
@sub_agent.tool_plain
def read_image(file_name: str) -> ToolReturn:
    """Reads an image from a local file path and returns it to the agent.

    Args:
        file_name: The name of the image file.

    """
    path = Path(f".playwright-mcp/{file_name}")

    # 1. Error handling: check if the file exists
    if not path.is_file():
        return ToolReturn(return_value=f"No image found at the path: {file_name}")

    # 2. Read the image bytes
    image_bytes = path.read_bytes()

    # 3. Dynamically guess the correct media type (default to image/png if unsure)
    mime_type, _ = mimetypes.guess_type(path)
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"

    # 4. Package into BinaryContent and return via ToolReturn
    return ToolReturn(
        return_value=BinaryContent(data=image_bytes, media_type=mime_type),
    )


@sub_agent.tool_plain
def preview_click(file_name: str, x: int, y: int) -> ToolReturn:
    """Preview where a click will land on a grid screenshot before committing.

    Draws a red circle and crosshair at (x, y) on a COPY of the grid image
    so you can visually confirm the target. Returns the annotated image.

    Args:
        file_name: The grid screenshot filename from browser_screenshot
                   (e.g. 'snap_abc123_grid.png').
        x: Horizontal pixel coordinate (from left edge of viewport).
        y: Vertical pixel coordinate (from top edge of viewport).

    Use this BEFORE browser_click_coords when:
    - You are unsure if coordinates are centered on the target
    - You've been misclicking and need to calibrate
    - The element is small or tightly packed
    """
    path = Path(f".playwright-mcp/{file_name}")
    if not path.is_file():
        return ToolReturn(return_value=f"No image found at: {file_name}")

    img = Image.open(path)
    w, h = img.size

    if not (0 <= x < w and 0 <= y < h):
        return ToolReturn(
            return_value=(
                f"COORDINATES OUT OF BOUNDS: ({x}, {y}) is outside the image "
                f"({w}x{h}). Valid range: x=0..{w - 1}, y=0..{h - 1}. "
                f"Adjust and retry."
            )
        )

    # Draw on a copy, never mutate the original
    annotated = img.copy()
    draw = ImageDraw.Draw(annotated)

    # Crosshair — two perpendicular lines through the click point
    draw.line([(x - 15, y), (x + 15, y)], fill="red", width=2)
    draw.line([(x, y - 15), (x, y + 15)], fill="red", width=2)

    # Outer ring
    draw.ellipse([(x - 10, y - 10), (x + 10, y + 10)], outline="red", width=2)
    # Solid center dot
    draw.ellipse([(x - 2, y - 2), (x + 2, y + 2)], fill="red")

    # Save and return
    preview_name = f"preview_{file_name}"
    preview_path = Path(f".playwright-mcp/{preview_name}")
    annotated.save(preview_path, format="PNG")

    preview_bytes = preview_path.read_bytes()
    return ToolReturn(
        return_value=BinaryContent(data=preview_bytes, media_type="image/png"),
    )



@sub_agent.tool_plain
def read_and_filter_file(
    file_name: str,
    start_line: int = 0,
    search_string: str | None = None,
    search_regex: str | None = None,
) -> str:
    """Reads a file and extracts relevant lines. Searches the ENTIRE file regardless
    of size — only the OUTPUT is capped at ~3000 words. Use this when the action
    tree is truncated and an element you need might be deep in the file.

    Args:
        file_name: The name of the text file in .playwright-mcp/.
        start_line: 1-indexed line number to start searching from (skip earlier lines).
        search_string: Optional substring. Only lines containing this are returned.
        search_regex: Optional Python regex. Only lines matching it are returned.

    """
    path = Path(".playwright-mcp/" + file_name)
    if not path.is_file():
        return f"Error: File not found at {file_name}"

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        return f"Error reading file: {e!s}"

    output_lines = []

    compiled_regex = None
    if search_regex:
        try:
            compiled_regex = re.compile(search_regex)
        except re.error as e:
            return f"Error: Invalid regular expression pattern: {e!s}"

    for idx, line in enumerate(lines, start=1):
        if idx < start_line:
            continue
        if search_string and search_string not in line:
            continue
        if compiled_regex and not compiled_regex.search(line):
            continue
        output_lines.append(f"{idx}: {line}")

    if not output_lines:
        return "No matching lines found based on the provided filters."

    # Truncate OUTPUT at ~3000 words (searches the entire file, only caps display)
    word_count = 0
    truncated = []
    for entry in output_lines:
        entry_words = len(entry.split())
        if word_count + entry_words > 3000:
            truncated.append("... (truncated at 3000 words. Re-run with a narrower "
                             "search_string or higher start_line to see more.)")
            break
        truncated.append(entry)
        word_count += entry_words

    return "\n".join(truncated)


# ----- Main function to run the sub-agent -----
def run(
    prompt: str,
    effort_mode: EffortMode = EffortMode.BALANCED,
    **kwargs: Any,
) -> AgentRunResult:
    """Run the sub-agent. Returns the full result object.

    Args:
        prompt: The natural-language task for the sub-agent.
        effort_mode: Controls temperature, token budget, and instruction depth.
        **kwargs: Forwarded to sub_agent.run_sync (e.g. message_history,
            model_settings, usage_limits). Override config-derived defaults.

    Returns:
        AgentRunResult with .output, .all_messages(), .new_messages(), etc.

    """
    config = get_effort_config(effort_mode)
    run_kwargs: dict[str, Any] = {
        "instructions": config["instructions"],
        "model_settings": config["model_settings"],
        "usage_limits": config["usage_limits"],
    }
    if effort_mode == EffortMode.MAX:
        run_kwargs["capabilities"] = [Thinking(effort="high")]

    # REPL-provided kwargs take precedence over config defaults
    run_kwargs.update(kwargs)

    # CSV/todo tools are injected per-run so they are ONLY available when
    # run() is called directly (agent mode).  spawn_sub_agents() calls
    # sub_agent.run() — the pydantic-ai method — which skips injection.
    csv_toolset = FunctionToolset(tools=[_read_csv, _append_csv, _todo])

    return sub_agent.run_sync(
        prompt,
        deps=SubAgentContext(),
        toolsets=[csv_toolset],
        **run_kwargs,
    )
