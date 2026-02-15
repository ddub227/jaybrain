"""Browser automation module for JayBrain.

Provides Playwright-based browser control via MCP tools.
Uses accessibility tree snapshots with element refs for interaction.

Requires: pip install jaybrain[render] && playwright install chromium
"""

from __future__ import annotations

import json as _json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from .config import DATA_DIR

logger = logging.getLogger("jaybrain.browser")

# Browser state singleton - persists across tool calls within a session
_state: dict = {
    "playwright": None,
    "browser": None,
    "context": None,
    "page": None,
    "_element_refs": [],  # [{ref, role, name}] from last snapshot
    "_headless": True,
    "_stealth": False,
    "_cdp_endpoint": None,  # CDP WebSocket URL when using connect_over_cdp
}

# Default CDP port for cross-process browser reconnection
CDP_DEFAULT_PORT = 9222
CDP_ENDPOINT_FILE = DATA_DIR / ".cdp_endpoint"

# Directory for saved screenshots
SCREENSHOTS_DIR = DATA_DIR / "browser_screenshots"

# Directory for saved browser sessions (cookies + storage)
SESSIONS_DIR = DATA_DIR / "browser_sessions"

# Roles that get clickable/typable refs in snapshots
INTERACTIVE_ROLES = frozenset({
    "link", "button", "textbox", "checkbox", "radio", "combobox",
    "menuitem", "tab", "option", "searchbox", "slider", "spinbutton",
    "switch", "menuitemcheckbox", "menuitemradio", "treeitem",
})

# Roles worth showing in the tree even when non-interactive
STRUCTURAL_ROLES = frozenset({
    "heading", "paragraph", "list", "listitem", "navigation", "banner",
    "main", "contentinfo", "complementary", "form", "region", "article",
    "table", "row", "cell", "columnheader", "rowheader", "img",
    "figure", "separator", "alert", "status", "dialog", "progressbar",
})

# Max snapshot lines to prevent token explosion on huge pages
SNAPSHOT_MAX_LINES = 500


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_playwright(stealth: bool | None = None):
    """Import and start Playwright (or Patchright in stealth mode)."""
    use_stealth = stealth if stealth is not None else _state["_stealth"]

    if use_stealth:
        try:
            from patchright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Patchright not installed (needed for stealth mode). Run:\n"
                "  pip install patchright\n"
                "  patchright install chromium"
            )
    else:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Run:\n"
                "  pip install jaybrain[render]\n"
                "  playwright install chromium"
            )

    if _state["playwright"] is None:
        _state["playwright"] = sync_playwright().start()
        _state["_stealth"] = use_stealth
    return _state["playwright"]


def _ensure_page() -> object:
    """Return the active page, raising if browser not launched."""
    page = _state["page"]
    if page is None or page.is_closed():
        raise RuntimeError(
            "No browser running. Call browser_launch() first."
        )
    return page


def _build_snapshot(tree: dict | None) -> tuple[str, list[dict]]:
    """Walk accessibility tree, assign refs to interactive elements.

    Returns (text_representation, element_refs_list).
    """
    if not tree:
        return "(empty page)", []

    elements: list[dict] = []
    ref_counter = [0]
    line_counter = [0]

    def walk(node: dict, depth: int = 0) -> list[str]:
        if line_counter[0] >= SNAPSHOT_MAX_LINES:
            return []

        role = node.get("role", "")
        name = (node.get("name", "") or "").strip()
        value = node.get("value", "")

        is_interactive = role in INTERACTIVE_ROLES
        ref = None

        if is_interactive:
            ref_counter[0] += 1
            ref = ref_counter[0]
            elements.append({"ref": ref, "role": role, "name": name})

        indent = "  " * min(depth, 10)
        line = ""

        if ref:
            display_name = name if name else "(unnamed)"
            line = f"{indent}[{ref}] {role} \"{display_name}\""
        elif role in STRUCTURAL_ROLES:
            if name:
                line = f"{indent}{role} \"{name}\""
            else:
                line = f"{indent}{role}"
        elif name and role not in ("generic", "none", "presentation", "Group"):
            line = f"{indent}{role} \"{name}\""

        if value and line:
            line += f" value=\"{value}\""

        lines = []
        if line.strip():
            lines.append(line)
            line_counter[0] += 1

        for child in node.get("children", []):
            lines.extend(walk(child, depth + (1 if line.strip() else 0)))

        return lines

    text_lines = walk(tree)

    if line_counter[0] >= SNAPSHOT_MAX_LINES:
        text_lines.append(f"  ... (truncated at {SNAPSHOT_MAX_LINES} lines)")

    return "\n".join(text_lines), elements


def _build_snapshot_from_aria(raw: str) -> tuple[str, list[dict]]:
    """Parse Patchright's aria_snapshot() YAML-like output into our ref format.

    Input lines look like:
      - heading "Example Domain" [level=1]
      - link "Learn more":
      - textbox "Search"
    """
    elements: list[dict] = []
    ref_counter = [0]
    output_lines: list[str] = []

    for line in raw.split("\n"):
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            # Text content or continuation - include as-is
            if stripped and not stripped.startswith("/"):
                indent = len(line) - len(stripped)
                output_lines.append("  " * (indent // 2) + stripped)
            continue

        # Parse "- role "name" [attrs]:" or "- role:"
        content = stripped[2:].rstrip(":")
        indent = len(line) - len(stripped)
        depth = indent // 2

        # Extract role and name
        parts = content.split(" ", 1)
        role = parts[0].strip()
        name = ""
        if len(parts) > 1:
            rest = parts[1].strip()
            # Extract quoted name
            if rest.startswith('"'):
                end_quote = rest.find('"', 1)
                if end_quote != -1:
                    name = rest[1:end_quote]

        is_interactive = role in INTERACTIVE_ROLES
        prefix = "  " * min(depth, 10)

        if is_interactive:
            ref_counter[0] += 1
            ref = ref_counter[0]
            elements.append({"ref": ref, "role": role, "name": name})
            display = name if name else "(unnamed)"
            output_lines.append(f'{prefix}[{ref}] {role} "{display}"')
        elif role in STRUCTURAL_ROLES or name:
            if name:
                output_lines.append(f'{prefix}{role} "{name}"')
            else:
                output_lines.append(f"{prefix}{role}")

        if len(output_lines) >= SNAPSHOT_MAX_LINES:
            output_lines.append(f"  ... (truncated at {SNAPSHOT_MAX_LINES} lines)")
            break

    return "\n".join(output_lines), elements


def _resolve_ref(ref: int) -> dict:
    """Look up an element ref from the last snapshot."""
    for el in _state["_element_refs"]:
        if el["ref"] == ref:
            return el
    raise ValueError(
        f"Element ref [{ref}] not found. "
        f"Available refs: 1-{len(_state['_element_refs'])}. "
        "Run browser_snapshot() to refresh."
    )


def _locate(page, ref: int | None = None, selector: str | None = None):
    """Build a Playwright locator from a ref or CSS selector."""
    if ref is not None:
        el = _resolve_ref(ref)
        locator = page.get_by_role(el["role"], name=el["name"])
        if locator.count() > 1:
            locator = locator.first
        return locator
    elif selector:
        return page.locator(selector)
    else:
        raise ValueError("Provide either ref (from snapshot) or selector (CSS).")


def _safe_wait(page, state: str = "domcontentloaded", timeout: int = 5000):
    """Wait for load state, swallowing timeout if page didn't navigate."""
    try:
        page.wait_for_load_state(state, timeout=timeout)
    except Exception:
        pass  # click may not have triggered navigation


# ---------------------------------------------------------------------------
# Public API - called by server.py tool wrappers
# ---------------------------------------------------------------------------

def launch_browser(
    headless: bool = True,
    url: str = "",
    stealth: bool = False,
) -> dict:
    """Launch a Chromium browser instance.

    stealth: Use Patchright instead of Playwright to bypass bot detection.
    Requires: pip install patchright && patchright install chromium
    """
    # Close existing browser if any
    if _state["browser"]:
        close_browser()

    pw = _ensure_playwright(stealth=stealth)
    _state["_headless"] = headless
    _state["browser"] = pw.chromium.launch(headless=headless)
    _state["context"] = _state["browser"].new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    _state["page"] = _state["context"].new_page()
    _state["_element_refs"] = []

    result = {"status": "launched", "headless": headless, "stealth": stealth}

    if url:
        _state["page"].goto(url, wait_until="domcontentloaded", timeout=30000)
        result["url"] = _state["page"].url
        result["title"] = _state["page"].title()

    return result


def navigate(url: str) -> dict:
    """Navigate to a URL."""
    page = _ensure_page()
    _state["_element_refs"] = []
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    return {
        "status": "navigated",
        "url": page.url,
        "title": page.title(),
    }


def snapshot() -> dict:
    """Get accessibility tree snapshot with numbered element refs."""
    page = _ensure_page()

    if hasattr(page, "accessibility"):
        # Standard Playwright path
        tree = page.accessibility.snapshot()
        text, elements = _build_snapshot(tree)
    else:
        # Patchright path - use aria_snapshot() and parse
        raw = page.locator(":root").aria_snapshot()
        text, elements = _build_snapshot_from_aria(raw)

    _state["_element_refs"] = elements
    return {
        "status": "ok",
        "url": page.url,
        "title": page.title(),
        "snapshot": text,
        "interactive_elements": len(elements),
    }


def take_screenshot(full_page: bool = False) -> dict:
    """Take a screenshot, save to file, return path for viewing."""
    page = _ensure_page()
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"screenshot_{int(time.time())}.png"
    filepath = SCREENSHOTS_DIR / filename

    page.screenshot(path=str(filepath), full_page=full_page)
    return {
        "status": "ok",
        "path": str(filepath),
        "url": page.url,
        "title": page.title(),
    }


def click(ref: int | None = None, selector: str | None = None) -> dict:
    """Click an element by ref number or CSS selector."""
    page = _ensure_page()
    locator = _locate(page, ref=ref, selector=selector)
    locator.click(timeout=10000)
    _safe_wait(page)
    return {
        "status": "clicked",
        "url": page.url,
        "title": page.title(),
    }


def type_text(
    text: str,
    ref: int | None = None,
    selector: str | None = None,
    clear: bool = True,
) -> dict:
    """Type text into an input element."""
    page = _ensure_page()
    locator = _locate(page, ref=ref, selector=selector)
    if clear:
        locator.fill(text, timeout=10000)
    else:
        locator.type(text, timeout=10000)
    return {
        "status": "typed",
        "text": text,
        "url": page.url,
    }


def press_key(key: str) -> dict:
    """Press a keyboard key (e.g. Enter, Tab, Escape, ArrowDown)."""
    page = _ensure_page()
    page.keyboard.press(key)
    _safe_wait(page, timeout=3000)
    return {
        "status": "pressed",
        "key": key,
    }


def evaluate_js(expression: str) -> dict:
    """Evaluate a JavaScript expression in the page context."""
    page = _ensure_page()
    result = page.evaluate(expression)
    return {
        "status": "ok",
        "result": str(result) if result is not None else None,
    }


def close_browser() -> dict:
    """Close browser and release all resources."""
    try:
        if _state["page"] and not _state["page"].is_closed():
            _state["page"].close()
    except Exception:
        pass
    try:
        if _state["context"]:
            _state["context"].close()
    except Exception:
        pass
    try:
        if _state["browser"]:
            _state["browser"].close()
    except Exception:
        pass
    try:
        if _state["playwright"]:
            _state["playwright"].stop()
    except Exception:
        pass

    _state["playwright"] = None
    _state["browser"] = None
    _state["context"] = None
    _state["page"] = None
    _state["_element_refs"] = []
    _state["_stealth"] = False

    return {"status": "closed"}


# ---------------------------------------------------------------------------
# CDP: Cross-process browser reconnection
# ---------------------------------------------------------------------------
# Enables launching a browser in one process and reconnecting from another.
# This is critical for Claude Code where each Bash call is a new process:
#   Call 1: launch_with_cdp() -> user does MFA in visible browser
#   Call 2: connect_to_cdp()  -> continue automating same browser


def _find_chrome_executable() -> str:
    """Find Chrome/Chromium executable on Windows."""
    candidates = [
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    # Fall back to Playwright's bundled Chromium
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        path = pw.chromium.executable_path
        pw.stop()
        return path
    except Exception:
        pass

    raise RuntimeError(
        "No Chrome/Chromium found. Install Google Chrome or run "
        "'playwright install chromium'."
    )


def launch_with_cdp(
    port: int = CDP_DEFAULT_PORT,
    url: str = "",
    headless: bool = False,
    stealth: bool = False,
) -> dict:
    """Launch Chrome with CDP remote debugging enabled.

    The browser runs as a detached process that survives the calling script.
    Saves the CDP endpoint to a file so connect_to_cdp() can find it.

    Args:
        port: Remote debugging port (default 9222).
        url: Optional URL to open immediately.
        headless: Run in headless mode (default False for user interaction).
        stealth: Not yet supported with CDP launch (use regular launch_browser).

    Returns:
        Dict with cdp_endpoint, pid, port.
    """
    import socket

    # Check if port is already in use (another CDP browser might be running)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        sock.connect(("127.0.0.1", port))
        sock.close()
        # Port is in use -- try connecting to existing browser
        return connect_to_cdp(f"http://127.0.0.1:{port}")
    except (ConnectionRefusedError, socket.timeout, OSError):
        sock.close()

    # Close any existing managed browser
    if _state["browser"]:
        close_browser()

    chrome_path = _find_chrome_executable()

    # Build Chrome args
    user_data_dir = str(DATA_DIR / "cdp_profile")
    os.makedirs(user_data_dir, exist_ok=True)

    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        args.append("--headless=new")
    if url:
        args.append(url)

    # Launch as detached process (survives this script)
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )

    # Wait for CDP to become available
    endpoint = None
    for _ in range(30):
        time.sleep(0.5)
        try:
            import urllib.request
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2,
            )
            data = _json.loads(resp.read())
            endpoint = data.get("webSocketDebuggerUrl", "")
            if endpoint:
                break
        except Exception:
            continue

    if not endpoint:
        proc.kill()
        return {"error": f"Chrome did not start CDP on port {port} within 15s"}

    # Save endpoint for reconnection from other processes
    CDP_ENDPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CDP_ENDPOINT_FILE.write_text(_json.dumps({
        "endpoint": endpoint,
        "port": port,
        "pid": proc.pid,
    }))

    # Now connect Playwright to it
    return connect_to_cdp(f"http://127.0.0.1:{port}")


def connect_to_cdp(endpoint: str = "") -> dict:
    """Connect Playwright to an already-running Chrome via CDP.

    If no endpoint is provided, reads it from the saved endpoint file
    (written by launch_with_cdp).

    Args:
        endpoint: CDP HTTP endpoint (e.g. 'http://127.0.0.1:9222').
                  If empty, reads from the saved endpoint file.

    Returns:
        Dict with status, url, title of the active page.
    """
    if not endpoint:
        if CDP_ENDPOINT_FILE.exists():
            saved = _json.loads(CDP_ENDPOINT_FILE.read_text())
            port = saved.get("port", CDP_DEFAULT_PORT)
            endpoint = f"http://127.0.0.1:{port}"
        else:
            return {"error": "No CDP endpoint saved. Call launch_with_cdp() first."}

    # Close existing Playwright connection if any (but don't close the browser)
    if _state["playwright"]:
        try:
            _state["playwright"].stop()
        except Exception:
            pass
        _state["playwright"] = None
        _state["browser"] = None
        _state["context"] = None
        _state["page"] = None

    pw = _ensure_playwright()

    try:
        browser = pw.chromium.connect_over_cdp(endpoint)
    except Exception as e:
        return {"error": f"Failed to connect to CDP at {endpoint}: {e}"}

    _state["browser"] = browser
    _state["_cdp_endpoint"] = endpoint

    # Get the first context and page (or create them)
    contexts = browser.contexts
    if contexts:
        _state["context"] = contexts[0]
        pages = contexts[0].pages
        if pages:
            _state["page"] = pages[0]
        else:
            _state["page"] = contexts[0].new_page()
    else:
        _state["context"] = browser.new_context(
            viewport={"width": 1280, "height": 720},
        )
        _state["page"] = _state["context"].new_page()

    _state["_element_refs"] = []

    page = _state["page"]
    return {
        "status": "connected",
        "endpoint": endpoint,
        "url": page.url,
        "title": page.title(),
        "pages": len(contexts[0].pages) if contexts else 1,
    }


def disconnect_cdp() -> dict:
    """Disconnect Playwright from the CDP browser WITHOUT closing it.

    The browser keeps running so the user can interact manually,
    and a future call to connect_to_cdp() can reconnect.
    """
    try:
        if _state["playwright"]:
            _state["playwright"].stop()
    except Exception:
        pass

    _state["playwright"] = None
    _state["browser"] = None
    _state["context"] = None
    _state["page"] = None
    _state["_element_refs"] = []

    return {"status": "disconnected", "browser_still_running": True}


# ---------------------------------------------------------------------------
# Phase 2: Session persistence, Bitwarden, advanced interactions
# ---------------------------------------------------------------------------

def session_save(name: str) -> dict:
    """Save browser session (cookies + localStorage) to a named file."""
    page = _ensure_page()
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    # Sanitize name for filename
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filepath = SESSIONS_DIR / f"{safe_name}.json"

    state = _state["context"].storage_state()
    with open(filepath, "w", encoding="utf-8") as f:
        _json.dump(state, f, indent=2)

    cookie_count = len(state.get("cookies", []))
    origin_count = len(state.get("origins", []))

    return {
        "status": "saved",
        "name": name,
        "path": str(filepath),
        "cookies": cookie_count,
        "origins": origin_count,
    }


def session_load(
    name: str,
    headless: bool | None = None,
    url: str = "",
    stealth: bool | None = None,
) -> dict:
    """Launch browser with a previously saved session state."""
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    filepath = SESSIONS_DIR / f"{safe_name}.json"

    if not filepath.exists():
        available = [f.stem for f in SESSIONS_DIR.glob("*.json")] if SESSIONS_DIR.exists() else []
        raise FileNotFoundError(
            f"Session '{name}' not found at {filepath}. "
            f"Available sessions: {available or '(none)'}"
        )

    with open(filepath, "r", encoding="utf-8") as f:
        storage_state = _json.load(f)

    # Close existing browser if any
    if _state["browser"]:
        close_browser()

    use_headless = headless if headless is not None else _state["_headless"]

    pw = _ensure_playwright(stealth=stealth)
    _state["_headless"] = use_headless
    _state["browser"] = pw.chromium.launch(headless=use_headless)
    _state["context"] = _state["browser"].new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        storage_state=storage_state,
    )
    _state["page"] = _state["context"].new_page()
    _state["_element_refs"] = []

    cookie_count = len(storage_state.get("cookies", []))
    result = {
        "status": "loaded",
        "name": name,
        "headless": use_headless,
        "cookies_restored": cookie_count,
    }

    if url:
        _state["page"].goto(url, wait_until="domcontentloaded", timeout=30000)
        result["url"] = _state["page"].url
        result["title"] = _state["page"].title()

    return result


def session_list() -> dict:
    """List all saved browser sessions."""
    if not SESSIONS_DIR.exists():
        return {"sessions": [], "count": 0}

    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json")):
        stat = f.stat()
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = _json.load(fh)
            cookie_count = len(data.get("cookies", []))
            origin_count = len(data.get("origins", []))
        except Exception:
            cookie_count = -1
            origin_count = -1

        sessions.append({
            "name": f.stem,
            "cookies": cookie_count,
            "origins": origin_count,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
        })

    return {"sessions": sessions, "count": len(sessions)}


def fill_from_bw(
    item_name: str,
    field: str,
    ref: int | None = None,
    selector: str | None = None,
) -> dict:
    """Fetch a credential from Bitwarden CLI and type it into a field.

    The credential value never appears in the return value or logs.
    """
    page = _ensure_page()

    # Fetch from Bitwarden CLI
    session = os.environ.get("BW_SESSION", "")
    cmd = ["bw", "get", field, item_name]
    if session:
        cmd.extend(["--session", session])

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Bitwarden CLI (bw) not found. Install it from: "
            "https://bitwarden.com/help/cli/"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Bitwarden CLI timed out. Is the vault unlocked?")

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        if "locked" in stderr.lower() or "not logged in" in stderr.lower():
            raise RuntimeError(
                "Bitwarden vault is locked. Run:\n"
                "  bw unlock\n"
                "Then set BW_SESSION in your environment."
            )
        raise RuntimeError(f"Bitwarden CLI error: {stderr}")

    value = proc.stdout.strip()
    if not value:
        raise ValueError(
            f"No value returned for field '{field}' of item '{item_name}'."
        )

    # Type into the target field
    locator = _locate(page, ref=ref, selector=selector)
    locator.fill(value, timeout=10000)

    # Log without revealing the value
    logger.info(
        "Filled field '%s' from BW item '%s' into element (ref=%s, selector=%s)",
        field, item_name, ref, selector,
    )

    return {
        "status": "filled",
        "item": item_name,
        "field": field,
        "chars": len(value),
    }


def select_option(
    ref: int | None = None,
    selector: str | None = None,
    value: str | None = None,
    label: str | None = None,
    index: int | None = None,
) -> dict:
    """Select an option from a <select> dropdown."""
    page = _ensure_page()
    locator = _locate(page, ref=ref, selector=selector)

    if value is not None:
        locator.select_option(value=value, timeout=10000)
        chosen = value
    elif label is not None:
        locator.select_option(label=label, timeout=10000)
        chosen = label
    elif index is not None:
        locator.select_option(index=index, timeout=10000)
        chosen = f"index:{index}"
    else:
        raise ValueError("Provide one of: value, label, or index.")

    return {
        "status": "selected",
        "chosen": chosen,
        "url": page.url,
    }


def wait_for(
    selector: str | None = None,
    text: str | None = None,
    state: str = "visible",
    timeout: int = 10000,
) -> dict:
    """Wait for an element or text to appear on the page.

    state: 'visible', 'hidden', 'attached', 'detached'.
    """
    page = _ensure_page()

    if text is not None:
        locator = page.get_by_text(text)
        locator.wait_for(state=state, timeout=timeout)
        return {
            "status": "found",
            "text": text,
            "state": state,
        }
    elif selector is not None:
        page.wait_for_selector(selector, state=state, timeout=timeout)
        return {
            "status": "found",
            "selector": selector,
            "state": state,
        }
    else:
        raise ValueError("Provide either selector or text to wait for.")


def hover(ref: int | None = None, selector: str | None = None) -> dict:
    """Hover over an element (useful for dropdown menus)."""
    page = _ensure_page()
    locator = _locate(page, ref=ref, selector=selector)
    locator.hover(timeout=10000)
    return {
        "status": "hovered",
        "url": page.url,
    }


# ---------------------------------------------------------------------------
# Phase 4: Multi-tab, navigation history
# ---------------------------------------------------------------------------

def go_back() -> dict:
    """Navigate back in browser history."""
    page = _ensure_page()
    page.go_back(wait_until="domcontentloaded", timeout=10000)
    _state["_element_refs"] = []
    return {
        "status": "navigated_back",
        "url": page.url,
        "title": page.title(),
    }


def go_forward() -> dict:
    """Navigate forward in browser history."""
    page = _ensure_page()
    page.go_forward(wait_until="domcontentloaded", timeout=10000)
    _state["_element_refs"] = []
    return {
        "status": "navigated_forward",
        "url": page.url,
        "title": page.title(),
    }


def tab_list() -> dict:
    """List all open tabs with their URLs and titles."""
    if not _state["context"]:
        raise RuntimeError("No browser running. Call browser_launch() first.")

    pages = _state["context"].pages
    tabs = []
    active_url = _state["page"].url if _state["page"] and not _state["page"].is_closed() else None

    for i, p in enumerate(pages):
        if p.is_closed():
            continue
        tabs.append({
            "index": i,
            "url": p.url,
            "title": p.title(),
            "active": p.url == active_url,
        })

    return {"tabs": tabs, "count": len(tabs)}


def tab_new(url: str = "") -> dict:
    """Open a new tab, optionally navigating to a URL."""
    if not _state["context"]:
        raise RuntimeError("No browser running. Call browser_launch() first.")

    new_page = _state["context"].new_page()
    _state["page"] = new_page
    _state["_element_refs"] = []

    result = {"status": "opened", "tab_count": len(_state["context"].pages)}

    if url:
        new_page.goto(url, wait_until="domcontentloaded", timeout=30000)
        result["url"] = new_page.url
        result["title"] = new_page.title()

    return result


def tab_switch(index: int) -> dict:
    """Switch to a tab by index (from browser_tab_list)."""
    if not _state["context"]:
        raise RuntimeError("No browser running. Call browser_launch() first.")

    pages = [p for p in _state["context"].pages if not p.is_closed()]

    if index < 0 or index >= len(pages):
        raise ValueError(
            f"Tab index {index} out of range. "
            f"Open tabs: 0-{len(pages) - 1}"
        )

    _state["page"] = pages[index]
    _state["_element_refs"] = []

    return {
        "status": "switched",
        "index": index,
        "url": pages[index].url,
        "title": pages[index].title(),
    }


def tab_close(index: int | None = None) -> dict:
    """Close a tab by index, or close the current tab if no index given."""
    if not _state["context"]:
        raise RuntimeError("No browser running. Call browser_launch() first.")

    pages = [p for p in _state["context"].pages if not p.is_closed()]

    if index is not None:
        if index < 0 or index >= len(pages):
            raise ValueError(f"Tab index {index} out of range.")
        target = pages[index]
    else:
        target = _state["page"]

    closed_url = target.url
    target.close()

    # Switch to another open tab if we closed the active one
    remaining = [p for p in _state["context"].pages if not p.is_closed()]
    if remaining:
        _state["page"] = remaining[-1]
        _state["_element_refs"] = []
    else:
        _state["page"] = None
        _state["_element_refs"] = []

    return {
        "status": "closed_tab",
        "closed_url": closed_url,
        "remaining_tabs": len(remaining),
    }
