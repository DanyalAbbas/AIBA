import sys
import uuid
from pathlib import Path

import logfire
from fastmcp import FastMCP
from fastmcp.utilities.logging import configure_logging
from playwright.async_api import BrowserContext, Page, async_playwright
from playwright.async_api import Error as PlaywrightError

# Silence FastMCP's own logs completely
configure_logging(level="ERROR")

mcp = FastMCP("Multi-Agent Optimized Browser")

# Persistent structural storage
_playwright = None
_browser = None
_contexts: dict[str, BrowserContext] = {}
_pages: dict[str, Page] = {}
_set_of_mark_mapping: dict[str, dict[int, str]] = {}

# Parse headless configuration from main orchestration arguments
args = sys.argv[1:]
is_headless = "--headless" in args

storage_state_path = None

# FIXED PARSING LOGIC:
for arg in args:
    if arg.startswith("--storage-state="):
        storage_state_path = arg.split("=", 1)[1]
        break

# Alternatively, if you ever pass it as two arguments, support both:
if not storage_state_path and "--storage-state" in args:
    idx = args.index("--storage-state") + 1
    if idx < len(args):
        storage_state_path = args[idx]


async def get_session_runtime(session_id: str) -> Page:
    """
    Locates or initializes a completely isolated incognito sandbox environment
    for an individual agent, sharing a single master browser instance.
    """
    global _playwright, _browser, _contexts, _pages

    # 1. Spin up the shared master browser binary exactly once
    if _browser is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=is_headless)

    # 2. If this specific agent doesn't have an environment yet, provision it
    if session_id not in _pages:
        # Load stored session state (cookies, localStorage, IndexedDB) if available
        ctx_kwargs = {}
        if storage_state_path:
            state_file = Path(storage_state_path)
            if state_file.exists():
                ctx_kwargs["storage_state"] = str(state_file)
            else:
                # Add this so it doesn't fail silently!
                logfire.warn(f"WARNING: Storage state file not found at {state_file.absolute()}\n")

        # Create a sandboxed incognito context (isolates cookies, storage, and tabs)
        context = await _browser.new_context(**ctx_kwargs)
        page = await context.new_page()

        _contexts[session_id] = context
        _pages[session_id] = page

    return _pages[session_id]


@mcp.tool()
async def browser_navigate(session_id: str, url: str) -> str:
    """Navigate to a URL and wait for the page to fully load.

    ALWAYS follow with browser_screenshot + read_image to visually orient yourself.
    To confirm you landed on the right page, call browser_get_page_info.
    Use https:// prefix — bare domains like "example.com" will fail.

    Example workflow: browser_navigate(url) → browser_get_page_info → browser_screenshot → read_image on grid
    """
    page = await get_session_runtime(session_id)
    await page.goto(url, wait_until="load")
    return f"[{session_id}] Successfully navigated to {url}"


@mcp.tool()
async def get_optimized_action_tree(session_id: str) -> str:
    """Scan the page for ALL visible interactive elements and return a numbered
    catalog with mcp_id identifiers. Each element gets a data-mcp-id attribute
    injected into the live DOM, enabling browser_click(mcp_id), browser_hover(mcp_id),
    browser_type(text, mcp_id), and browser_select_option(mcp_id, value).

    Use this when:
    - You need a full audit of every button, link, and input on the page
    - Visual clicking with browser_click_coords keeps missing the target
    - You need an mcp_id for browser_hover to reveal hidden menus/dropdowns
    - The page is too complex to parse visually from the screenshot alone

    IDs are EPHEMERAL — the DOM changes after any navigation or interaction.
    Always re-run this tool immediately before using any mcp_id-based action.
    On pages with 3000+ words of elements, the output truncates and saves the
    full tree to .playwright-mcp/ — use read_and_filter_file with the saved
    filename to find IDs that were cut off.

    Not needed for the basic visual loop (browser_screenshot → read_image →
    browser_click_coords). Reach for it when you switch from visual to DOM mode."""
    page = await get_session_runtime(session_id)

    extraction_script = """
    () => {
        // 1. Recursive crawler to pierce through Shadow DOMs and accessible Iframes
        function getAllInteractives(root = document) {
            let elements = [];
            if (!root) return elements;

            const nodes = root.querySelectorAll('*');
            nodes.forEach(node => {
                // Target semantic and interactive targets
                if (node.matches('button, a, input, textarea, select, [role="button"], [role="link"], [role="tab"], [role="textbox"], [role="menuitem"], [contenteditable="true"]')) {
                    elements.push(node);
                }
                // Pierce Shadow DOM boundaries
                if (node.shadowRoot) {
                    elements = elements.concat(getAllInteractives(node.shadowRoot));
                }
                // Pierce Same-Origin Iframes
                if (node.tagName === 'IFRAME') {
                    try {
                        if (node.contentDocument) {
                            elements = elements.concat(getAllInteractives(node.contentDocument));
                        }
                    } catch (e) {
                        // Cross-origin frame, cannot access via standard DOM scripting
                    }
                }
            });
            return elements;
        }

        const interactives = getAllInteractives();
        let items = [];
        let counter = 1;

        interactives.forEach(el => {
            // 2. Strict Layout Visibility Engine
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            if (rect.width === 0 || rect.height === 0 || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
            if (el.closest('[inert]')) return;

            // Inject the data-mcp-id attribute so browser_click/browser_type can target this element.
            // This is the ONLY place data-mcp-id is set — actions depend on it.
            const currentId = counter;
            el.setAttribute('data-mcp-id', currentId.toString());

            // 3. Ultra-Robust Label & Context Extraction Matrix
            let text = el.innerText || el.textContent || '';

            if (!text.trim()) {
                text = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || el.getAttribute('aria-placeholder') || '';
            }
            if (!text.trim() && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.getAttribute('contenteditable') === 'true')) {
                text = el.value || el.getAttribute('placeholder') || el.name || '';
            }
            // If the interactive tag is empty but visually houses a visual asset
            if (!text.trim() && el.querySelector('svg, img')) {
                const innerImg = el.querySelector('img');
                text = (innerImg ? innerImg.getAttribute('alt') : '') || el.className || '[Icon Only]';
                if (typeof text === 'string' && text.includes('mcp-som')) text = '[Icon Only]';
            }

            // Clean up block breaks, heavy whitespace, and tab spacing
            text = text.trim().replace(/\\s+/g, ' ');

            // Limit massive strings to save context tokens
            if (text.length > 60) {
                text = text.substring(0, 57) + '...';
            }

            // Fallback for unidentified elements to give the agent structural context
            if (!text) {
                text = el.className || '[Unnamed Element]';
            }

            let type = el.tagName.toLowerCase();
            if (el.tagName === 'INPUT') type += ` (${el.type})`;
            if (el.getAttribute('role')) type += ` [${el.getAttribute('role')}]`;
            if (el.getAttribute('contenteditable') === 'true') type += ' [editable]';

            items.push(`- [ID: ${currentId}] ${type}: "${text}"`);
            counter++;
        });

        return items.join('\\n');
    }
    """

    tree_text = await page.evaluate(extraction_script)
    if not tree_text:
        return "No interactive elements found on the screen."

    # Check if word count exceeds the 3000-word safety threshold
    total_words = len(tree_text.split())

    if total_words > 3000:
        storage_dir = Path(".playwright-mcp")
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Build unique target file for full DOM storage
        tree_id = f"tree_{str(uuid.uuid4())[:8]}"
        filename = f"action_tree_{session_id}_{tree_id}.txt"
        filepath = storage_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(tree_text)

        # Cleanly truncate line-by-line so we don't break mid-sentence
        lines = tree_text.split("\n")
        truncated_lines = []
        current_word_count = 0

        for line in lines:  # pragma: no branch - loop always exits via break
            line_words = len(line.split())
            if current_word_count + line_words > 3000:
                break
            truncated_lines.append(line)
            current_word_count += line_words

        truncated_text = "\n".join(truncated_lines)

        # Append a structural warning instruction directly into tool result context
        overflow_warning = (
            f"\n\n*** [CONTEXT TRUNCATION WARNING] ***\n"
            f"The action tree for this page contains an overwhelming number of interactive items ({total_words} words).\n"
            f"To preserve your token budget, this preview has been safely truncated.\n\n"
            f"Full Action Tree File: {filename}\n"
            f"How to locate hidden IDs: Call 'read_and_filter_file' using the file name '{filename}' "
            f"and pass specific search filters (like keywords or inputs) to find element IDs not shown below.\n"
            f"************************************"
        )
        return truncated_text + overflow_warning

    return tree_text

@mcp.tool()
async def browser_click(session_id: str, mcp_id: int) -> str:
    """Click an element by its numeric ID from get_optimized_action_tree.

    Uses force=True — clicks the element directly even if it's covered by overlays,
    sticky headers, or cookie banners. The element just needs to exist in the DOM.

    CRITICAL: You MUST call get_optimized_action_tree right before this to get
    fresh IDs. IDs go stale after any navigation, click, or DOM change.
    Using a stale ID returns [FAIL] — re-run get_optimized_action_tree and retry.

    Prefer browser_click_coords + read_image for most interactions. Use this
    when visual clicking repeatedly hits the wrong target or you need precise
    element-level targeting."""
    page = await get_session_runtime(session_id)
    selector = f'[data-mcp-id="{mcp_id}"]'
    try:
        await page.click(selector, timeout=5000, force=True)
    except PlaywrightError:
        return (
            f"[FAIL] No element found with mcp_id={mcp_id}. "
            f"The page DOM may have changed since your last get_optimized_action_tree call. "
            f"Re-run get_optimized_action_tree to get fresh IDs, then retry."
        )
    return f"[{session_id}] Clicked element ID {mcp_id}"


_KEY_NAMES: set[str] = {
    "Enter", "Escape", "Tab", "Backspace", "Delete", "Insert",
    "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight",
    "PageDown", "PageUp", "Home", "End",
    "Shift", "Control", "Alt", "Meta",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    " ",  # Space
}


@mcp.tool()
async def browser_type(session_id: str, text: str, mcp_id: int | None = None) -> str:
    """Type text into a field, or press a named keyboard key.

    TWO MODES based on the `text` value:

    1. KEY PRESS — if `text` is a recognized key name (Enter, Escape, Tab,
       ArrowDown/Up/Left/Right, Backspace, Delete, PageDown/Up, Home, End,
       Space, F1-F12, Shift, Control, Alt, Meta, or chords like Control+a),
       it presses that key globally. No mcp_id needed.

    2. TEXT TYPING — for anything else, types `text` character-by-character
       into the currently focused element.

    STANDARD VISUAL WORKFLOW (recommended):
       browser_click_coords(x, y) into the input → browser_type(text="hello")
       without mcp_id. The click focuses the field; type goes into it.

    DOM WORKFLOW (when you have fresh action tree):
       browser_type(text="hello", mcp_id=5) — focuses element ID 5 first,
       then types. Fails fast if the ID is stale.

    To submit a form after typing: browser_type(text="Enter")."""
    page = await get_session_runtime(session_id)

    # ── key-press branch ──
    # Chords (e.g. "Control+a"): press if text contains "+"
    # Single keys: press only if in _KEY_NAMES (Enter, Escape, etc.)
    if "+" in text:
        await page.keyboard.press(text)
        return f"[{session_id}] Pressed key chord: {text}"
    if text in _KEY_NAMES:
        await page.keyboard.press(text)
        return f"[{session_id}] Pressed key: {text}"

    # ── optional focus ──
    if mcp_id is not None:
        selector = f'[data-mcp-id="{mcp_id}"]'
        try:
            await page.focus(selector)
        except PlaywrightError:
            return (
                f"[FAIL] No element found with mcp_id={mcp_id}. "
                f"Re-run get_optimized_action_tree for fresh IDs, or use "
                f"browser_click_coords + browser_type(text=...) without mcp_id."
            )

    # ── type char-by-char into whatever is focused ──
    await page.keyboard.type(text)
    target = f"element ID {mcp_id}" if mcp_id is not None else "focused element"
    return f"[{session_id}] Typed text into {target}"


@mcp.tool()
async def browser_screenshot(session_id: str) -> str:
    """Take TWO screenshots of the current page viewport and save to .playwright-mcp/:

    1. Set-of-Mark (SOM) — `snap_XXXX_som.png`
       Numbered red badges overlay every interactive element. Each badge number
       maps to a DOM element ID. Use browser_click_mark with the SOM filename
       and badge number to click directly by visual number. Now CAN handle even covered
       elements invisibly.

    2. Coordinate Grid — `snap_XXXX_grid.png`
       Pixel ruler with X/Y axis markers every 50px. Use browser_click_coords(x, y)
       by reading coordinates directly off the grid image with read_image.

    ALWAYS call this after: navigation, scroll, click, type, or any page change.
    Then call read_image on the returned filenames to visually inspect the page.
    This is your primary way to see what the browser sees."""
    page = await get_session_runtime(session_id)

    # Generate a baseline unique ID for this visual step
    snapshot_base = f"snap_{str(uuid.uuid4())[:8]}"

    filename_som = f"{snapshot_base}_som.png"
    filename_grid = f"{snapshot_base}_grid.png"

    path_som = f".playwright-mcp/{filename_som}"
    path_grid = f".playwright-mcp/{filename_grid}"

    # --- PASS 1: SET OF MARK INJECTION ---
    som_injection_script = """
    () => {
        // 1. Recursive DOM crawler
        function getAllInteractives(root = document) {
            let elements = [];
            if (!root) return elements;

            const nodes = root.querySelectorAll('*');
            nodes.forEach(node => {
                if (node.matches('button, a, input, textarea, select, [role="button"], [role="link"], [role="textbox"], [role="menuitem"], [role="tab"], [contenteditable="true"]')) {
                    elements.push(node);
                }
                if (node.shadowRoot) {
                    elements = elements.concat(getAllInteractives(node.shadowRoot));
                }
                if (node.tagName === 'IFRAME') {
                    try {
                        if (node.contentDocument) elements = elements.concat(getAllInteractives(node.contentDocument));
                    } catch (e) {}
                }
            });
            return elements;
        }

        // 2. Absolute bounding box calculation for nested iframes
        function getAbsoluteRect(el) {
            let rect = el.getBoundingClientRect();
            let currentWindow = el.ownerDocument.defaultView;
            let x = rect.left;
            let y = rect.top;
            while (currentWindow !== window && currentWindow !== null) {
                let frameElement = currentWindow.frameElement;
                if (!frameElement) break;
                let frameRect = frameElement.getBoundingClientRect();
                x += frameRect.left;
                y += frameRect.top;
                currentWindow = currentWindow.parent;
            }
            return { left: x, top: y, width: rect.width, height: rect.height };
        }

        // 3. Deep occlusion check piercing Shadow DOMs
        function getDeepElement(x, y, doc = document) {
            let el = doc.elementFromPoint(x, y);
            while (el && el.shadowRoot) {
                let innerEl = el.shadowRoot.elementFromPoint(x, y);
                if (!innerEl || innerEl === el) break;
                el = innerEl;
            }
            return el;
        }

        const interactives = getAllInteractives();
        let counter = 1;
        let elementMap = {};

        interactives.forEach((el) => {
            const rect = getAbsoluteRect(el);
            const style = window.getComputedStyle(el);
            if (rect.width === 0 || rect.height === 0 || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
            if (el.closest('[inert]')) return;

            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;

            // Bounds check
            if (centerX >= 0 && centerX <= window.innerWidth && centerY >= 0 && centerY <= window.innerHeight) {
                // Local coordinate check for the specific document layer
                const localRect = el.getBoundingClientRect();
                const localCenterX = localRect.left + localRect.width / 2;
                const localCenterY = localRect.top + localRect.height / 2;

                const topEl = getDeepElement(localCenterX, localCenterY, el.ownerDocument);

                if (topEl && !el.contains(topEl) && !topEl.contains(el)) {
                    const topStyle = window.getComputedStyle(topEl);
                    if (topStyle.backgroundColor !== 'rgba(0, 0, 0, 0)' && topStyle.opacity !== '0') {
                        return; // Covered by modal scrim/backdrop
                    }
                }
            } else {
                return; // Out of bounds
            }

            const markNumber = counter++;
            let mcpId = el.getAttribute('data-mcp-id');
            if (!mcpId) {
                mcpId = `mcp_gen_${Math.random().toString(36).substring(2, 9)}`;
                el.setAttribute('data-mcp-id', mcpId);
            }

            elementMap[markNumber] = mcpId;

            // Draw bounding boxes (Position Fixed maps properly to the viewport)
            const overlay = document.createElement('div');
            overlay.className = 'mcp-som-visual-box';
            overlay.style.position = 'fixed';
            overlay.style.left = `${rect.left}px`;
            overlay.style.top = `${rect.top}px`;
            overlay.style.width = `${rect.width}px`;
            overlay.style.height = `${rect.height}px`;
            overlay.style.border = '2px solid #ff0055';
            overlay.style.backgroundColor = 'rgba(255, 0, 85, 0.08)';
            overlay.style.pointerEvents = 'none';
            overlay.style.zIndex = '2147483647';
            overlay.style.boxSizing = 'border-box';

            const badge = document.createElement('span');
            badge.innerText = markNumber;
            badge.style.position = 'absolute';
            badge.style.top = '-14px';
            badge.style.left = '0px';
            badge.style.backgroundColor = '#ff0055';
            badge.style.color = '#ffffff';
            badge.style.fontSize = '11px';
            badge.style.fontFamily = 'monospace';
            badge.style.fontWeight = 'bold';
            badge.style.padding = '1px 4px';
            badge.style.borderRadius = '3px';
            badge.style.lineHeight = '1';

            overlay.appendChild(badge);
            document.documentElement.appendChild(overlay);
        });

        return elementMap;
    }
    """

    # Render Marks -> Capture SoM -> Clear Marks
    mark_to_mcp_id_map = await page.evaluate(som_injection_script)
    _set_of_mark_mapping[filename_som] = {int(k): v for k, v in mark_to_mcp_id_map.items()}
    await page.screenshot(path=path_som)
    await page.evaluate("() => document.querySelectorAll('.mcp-som-visual-box').forEach(b => b.remove())")

    # --- PASS 2: COORDINATE GRID INJECTION ---
    grid_injection_script = """
        () => {
            const container = document.createElement('div');
            container.className = 'mcp-grid-visual-overlay';
            container.style.position = 'fixed';
            container.style.top = '0';
            container.style.left = '0';
            container.style.width = '100vw';
            container.style.height = '100vh';
            container.style.pointerEvents = 'none';
            container.style.zIndex = '2147483647';

            const majorStep = 100;
            const minorStep = 50;

            // 1. Draw Grid Lines
            for (let x = minorStep; x < window.innerWidth; x += minorStep) {
                const isMajor = (x % majorStep === 0);
                const line = document.createElement('div');
                line.style.position = 'absolute';
                line.style.left = `${x}px`;
                line.style.top = '0';
                line.style.width = '1px';
                line.style.height = '100%';
                line.style.backgroundColor = isMajor ? 'rgba(0, 150, 255, 0.5)' : 'rgba(0, 150, 255, 0.15)';
                container.appendChild(line);
            }

            for (let y = minorStep; y < window.innerHeight; y += minorStep) {
                const isMajor = (y % majorStep === 0);
                const line = document.createElement('div');
                line.style.position = 'absolute';
                line.style.top = `${y}px`;
                line.style.left = '0';
                line.style.height = '1px';
                line.style.width = '100%';
                line.style.backgroundColor = isMajor ? 'rgba(0, 150, 255, 0.5)' : 'rgba(0, 150, 255, 0.15)';
                container.appendChild(line);
            }

            // 2. Draw Dense Intersection Badges (The VLM Trick)
            for (let x = majorStep; x < window.innerWidth; x += majorStep) {
                for (let y = majorStep; y < window.innerHeight; y += majorStep) {
                    const label = document.createElement('div');
                    // Format: X,Y (e.g., 200,400)
                    label.innerText = `${x},${y}`;
                    label.style.position = 'absolute';
                    // Offset slightly so it doesn't block the exact pixel intersection point
                    label.style.left = `${x + 3}px`;
                    label.style.top = `${y + 3}px`;
                    label.style.color = '#fff';
                    // High contrast background so it pops over any website design
                    label.style.backgroundColor = 'rgba(60, 20, 220, 0.9)';
                    label.style.fontSize = '15px';
                    label.style.fontFamily = 'monospace';
                    label.style.fontWeight = '900';
                    label.style.padding = '1px 3px';
                    label.style.borderRadius = '3px';
                    label.style.boxShadow = '0 0 2px rgba(0,0,0,0.8)';

                    container.appendChild(label);
                }
            }

            document.documentElement.appendChild(container);
        }
        """

    # Render Grid -> Capture Grid -> Clear Grid
    await page.evaluate(grid_injection_script)
    await page.screenshot(path=path_grid)
    await page.evaluate("() => document.querySelectorAll('.mcp-grid-visual-overlay').forEach(g => g.remove())")

    # Return structured multi-file payload to the agent context
    return (
        f"[{session_id}] Viewport captured. Two visual reference maps generated successfully:\n\n"
        f"1. SET-OF-MARK VIEW: File '{filename_som}'\n"
        f"   -> Purpose: Shows interactive element ID badges. Use this map with standard selector tools.\n\n"
        f"2. COORDINATE GRID VIEW: File '{filename_grid}'\n"
        f"   -> Purpose: Shows absolute X/Y viewport coordinates with increments every 50px.\n"
        f"   -> Use this map explicitly to target clicks using pixel positions on custom components."
    )


@mcp.tool()
async def browser_snapshot(session_id: str) -> str:
    """Capture the page's accessibility tree (DOM structure) as a YAML file.

    This tool produces a structured text representation of every element on the page — headings,
    links, buttons, inputs, landmarks, and their hierarchy. Saved as YAML to
    .playwright-mcp/.

    Use this when:
    - You need to audit page structure without visual noise
    - Looking for elements hidden off-screen or behind other layers
    - The action tree is truncated and you need the full DOM catalog
    - You want a text-searchable record of page content

    Returns the YAML content. Use read_and_filter_file to search within it."""
    page = await get_session_runtime(session_id)
    filename = f"snapshot_{str(uuid.uuid4())[4:]}.yaml"
    path = ".playwright-mcp/" + filename

    snapshot_text = await page.aria_snapshot()
    Path(path).write_text(snapshot_text, encoding="utf-8")

    lines = snapshot_text.splitlines()
    truncated_lines: list[str] = []
    current_word_count = 0

    for line in lines:
        line_words = len(line.split())
        if current_word_count + line_words > 3000:
            break
        truncated_lines.append(line)
        current_word_count += line_words

    truncated_text = "\n".join(truncated_lines)

    # Append a structural warning instruction directly into tool result context
    overflow_warning = (
        f"\n\n*** [CONTEXT TRUNCATION WARNING] ***\n"
        f"The Snapshot for this page contains an overwhelming number of characters.\n"
        f"To preserve your token budget, this preview has been safely truncated.\n\n"
        f"Full Snapshot File: {filename}\n"
        f"How to locate hidden Snapshot: Call 'read_and_filter_file' using the file name '{filename}' "
        f"and pass specific search filters (like keywords or inputs) to dig deeper in the Snapshot.\n"
        f"************************************"
    )
    return truncated_text + overflow_warning


@mcp.tool()
async def browser_evaluate(session_id: str, js_code: str) -> str:
    """Run arbitrary JavaScript in the page and return the result.

    READ-ONLY ONLY. Use for extracting data, reading DOM properties, checking
    page state, or scraping values that aren't visible in screenshots. Never
    use this to click, type, scroll, or modify the page — use the dedicated
    tools for those actions.

    Examples: get the current page title, extract all links, check if an
    element's text matches expected content, read input values."""
    page = await get_session_runtime(session_id)

    try:
        result = await page.evaluate(js_code)
        return f"[{session_id}] JS code evaluated. Result: {result}"
    except PlaywrightError as e:
        # Extract just the main error message without the massive stack trace
        error_msg = str(e).split('\n')[0]
        return f"[{session_id}] JavaScript Execution Failed: {error_msg}. Please check your selectors and try again."
    except Exception as e:
        return f"[{session_id}] Unexpected Python error: {e!s}"

@mcp.tool()
async def browser_locator(session_id: str, selector: str) -> str:
    """Find an element by CSS selector and return its text content.

    This is a DOM query tool — use it to verify page content or read text
    from specific elements. Returns the element's visible text, or a
    not-found message if the selector doesn't match.

    For full page scanning, prefer get_optimized_action_tree which catalogs
    ALL interactive elements with mcp_ids you can click/hover/type on.
    For raw JavaScript queries, use browser_evaluate."""
    page = await get_session_runtime(session_id)
    element_handle = await page.query_selector(selector)
    if element_handle:
        text_content = await element_handle.text_content()
        return f"[{session_id}] Element found. Text content: {text_content.strip() if text_content else '(empty)'}"
    else:
        return f"[{session_id}] No element found for selector: {selector}"


@mcp.tool()
async def browser_wait_for_timeout(session_id: str, milliseconds: int) -> str:
    """Pause execution for a specified number of milliseconds.

    Use when a page is loading dynamically (infinite scroll, lazy images,
    JavaScript rendering) and you need to give it time to settle before
    taking a screenshot or clicking. 1000-3000ms is typical for page loads.

    Also useful for respecting rate limits between rapid navigation actions."""
    page = await get_session_runtime(session_id)
    await page.wait_for_timeout(milliseconds)
    return f"[{session_id}] Waited for {milliseconds} milliseconds."


@mcp.tool()
async def browser_scroll(session_id: str, direction: str, amount: str = "page") -> str:
    """Scroll the page up or down.

    Args:
        direction: 'up' or 'down'
        amount: 'page' (viewport height, default) or a pixel value like '300'.
                Use smaller pixel values for fine-grained scrolling.

    ALWAYS call browser_screenshot after scrolling to see the new viewport.
    Combine with browser_get_page_info to track scroll position as percentage."""
    page = await get_session_runtime(session_id)
    px = "window.innerHeight" if amount == "page" else amount
    sign = "-" if direction == "up" else ""
    await page.evaluate(f"window.scrollBy(0, {sign}{px})")
    return f"[{session_id}] Scrolled {direction} by {amount}"


@mcp.tool()
async def browser_click_coords(session_id: str, x: int, y: int) -> str:
    """Click at exact viewport pixel coordinates (x, y from top-left).

    This is your PRIMARY click tool for the visual workflow. Uses raw
    mouse.click(x, y) with zero actionability checks — it fires directly
    at the coordinates, bypassing overlays, sticky headers, and z-index
    issues that cause DOM-based clicks to time out.

    STANDARD VISUAL LOOP:
      browser_screenshot → read_image on the grid → browser_click_coords(x, y)
      where x, y are read directly from the coordinate grid overlay.

    Use this when: clicking any visible element by coordinates, dealing with
    Canvas/SVG/custom UI, clicking underneath cookie banners or sticky navs,
    or any time browser_click(mcp_id) fails to register.

    FALLBACK: browser_click_mark(screenshot, badge_number) for SoM-based clicking.
    DOM ALTERNATIVE: get_optimized_action_tree → browser_click(mcp_id) when
    coordinates consistently miss."""
    page = await get_session_runtime(session_id)
    await page.mouse.click(x, y)
    return f"[{session_id}] Clicked at viewport coordinates ({x}, {y})"


@mcp.tool()
async def browser_hover(session_id: str, mcp_id: int) -> str:
    """Hover the mouse over an element identified by its mcp_id from get_optimized_action_tree.

    Many sites (LinkedIn, GitHub, Notion, Twitter, Google Docs) reveal action
    buttons, tooltips, and dropdown menus only on hover. If a page looks empty
    or expected buttons are missing:
      1. get_optimized_action_tree → find the container element's mcp_id
      2. browser_hover(mcp_id) → reveals hidden controls
      3. get_optimized_action_tree → get fresh IDs for the newly revealed elements
      4. browser_click(mcp_id) on the revealed element

    Always re-run get_optimized_action_tree after hovering — revealed elements
    are invisible to the action tree until they become visible."""
    page = await get_session_runtime(session_id)
    selector = f'[data-mcp-id="{mcp_id}"]'
    try:
        await page.hover(selector, timeout=5000)
    except PlaywrightError:
        return (
            f"[FAIL] No element found with mcp_id={mcp_id}. "
            f"Re-run get_optimized_action_tree to get fresh IDs."
        )
    return f"[{session_id}] Hovered over element ID {mcp_id}"


@mcp.tool()
async def browser_go_back(session_id: str) -> str:
    """Navigate back in browser history. Equivalent to clicking the back button."""
    page = await get_session_runtime(session_id)
    await page.go_back(wait_until="load")
    return f"[{session_id}] Navigated back. Current URL: {page.url}"


@mcp.tool()
async def browser_go_forward(session_id: str) -> str:
    """Navigate forward in browser history. Equivalent to clicking the forward button."""
    page = await get_session_runtime(session_id)
    await page.go_forward(wait_until="load")
    return f"[{session_id}] Navigated forward. Current URL: {page.url}"


@mcp.tool()
async def browser_select_option(session_id: str, mcp_id: int, value: str) -> str:
    """Select an option from a <select> dropdown by its visible label text.

    Args:
        mcp_id: The ID from get_optimized_action_tree for the <select> element.
        value: The visible label text to select (e.g., 'United States', 'Option 3').
               Must match exactly what the user sees.

    Always re-run get_optimized_action_tree before using mcp_id — stale IDs fail.
    If selection fails, verify the value text matches exactly and retry."""
    page = await get_session_runtime(session_id)
    selector = f'[data-mcp-id="{mcp_id}"]'
    try:
        await page.select_option(selector, label=value, timeout=5000)
    except PlaywrightError:
        return (
            f"[FAIL] Could not select '{value}' on mcp_id={mcp_id}. "
            f"Re-run get_optimized_action_tree to get fresh IDs."
        )
    return f"[{session_id}] Selected '{value}' in element ID {mcp_id}"


@mcp.tool()
async def browser_get_page_info(session_id: str) -> str:
    """Return current page metadata: URL, title, scroll position, and viewport size.

    Use this as a lightweight orientation check after navigation or during long
    interaction chains — it's fast and costs no image tokens. Tells you:
    - Where you are (URL, title)
    - How far down the page you've scrolled (as a percentage)
    - Whether there's more content below the fold

    Does NOT capture visual state — still take browser_screenshot for that."""
    page = await get_session_runtime(session_id)
    info = await page.evaluate("""
        () => ({
            url: window.location.href,
            title: document.title,
            scrollY: window.scrollY,
            viewportHeight: window.innerHeight,
            documentHeight: document.documentElement.scrollHeight
        })
    """)
    pct = round(info["scrollY"] / max(info["documentHeight"] - info["viewportHeight"], 1) * 100)
    return (
        f"[{session_id}] URL: {info['url']}\n"
        f"Title: {info['title']}\n"
        f"Scroll: {info['scrollY']}px / {info['documentHeight']}px ({pct}% down the page)"
    )


@mcp.tool()
async def browser_click_mark(session_id: str, screenshot_file_name: str, mark_number: int) -> str:
    """Click an element by reading its visual badge number from a Set-of-Mark screenshot.

    Pass the exact SOM filename returned by browser_screenshot (e.g. 'snap_abc123_som.png')
    and the red badge number visible on top of the element. This resolves the badge
    to the element's DOM ID internally. Uses force=True — works through overlays.

    This is the BRIDGE between visual and DOM modes: you see the badge visually
    via read_image, you click it with this tool.

    ALTERNATIVES:
    - browser_click_coords(x, y): purely visual, no DOM involved
    - browser_click(mcp_id): purely DOM, no visual needed (must refresh action tree first)"""
    if screenshot_file_name not in _set_of_mark_mapping:
        return f"Error: Screenshot ID '{screenshot_file_name}' not found in active session memory."

    session_marks = _set_of_mark_mapping[screenshot_file_name]
    if mark_number not in session_marks:
        return f"Error: Mark number [{mark_number}] was not present in screenshot '{screenshot_file_name}'."

    mcp_id = session_marks[mark_number]
    page = await get_session_runtime(session_id)

    selector = f'[data-mcp-id="{mcp_id}"]'
    try:
        await page.click(selector, timeout=5000, force=True)
        return f"[{session_id}] Clicked element with mark_number={mark_number}."
    except PlaywrightError:
        return f""""
            [FAIL] Mark #{mark_number} resolved to mcp_id={mcp_id} but the
            element no longer exists in the DOM. The page may have changed
            since the screenshot. Re-run browser_screenshot or fall back
            to browser_click_coords with the grid.
        """
# ── Entry Point ───────────────────────────────────────────────────

def main():
    """Entry point for `fastmcp run` or direct execution via stdio."""
    mcp.run(show_banner=False)

if __name__ == "__main__":  # pragma: no cover
    main()
