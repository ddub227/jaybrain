"""Tests for the browser automation module."""

import json
import pytest
from pathlib import Path


def test_browser_launch_and_close():
    """Test launching and closing the browser."""
    from jaybrain.browser import launch_browser, close_browser

    result = launch_browser(headless=True)
    assert result["status"] == "launched"
    assert result["headless"] is True

    result = close_browser()
    assert result["status"] == "closed"


def test_browser_launch_with_url():
    """Test launching browser with an initial URL."""
    from jaybrain.browser import launch_browser, close_browser

    try:
        result = launch_browser(headless=True, url="https://example.com")
        assert result["status"] == "launched"
        assert "example.com" in result["url"]
        assert result["title"]  # should have a title
    finally:
        close_browser()


def test_browser_navigate():
    """Test navigating to a URL."""
    from jaybrain.browser import launch_browser, navigate, close_browser

    try:
        launch_browser(headless=True)
        result = navigate("https://example.com")
        assert result["status"] == "navigated"
        assert "example.com" in result["url"]
    finally:
        close_browser()


def test_browser_snapshot():
    """Test getting accessibility snapshot."""
    from jaybrain.browser import launch_browser, navigate, snapshot, close_browser

    try:
        launch_browser(headless=True, url="https://example.com")
        result = snapshot()
        assert result["status"] == "ok"
        assert result["snapshot"]  # should have content
        assert result["interactive_elements"] >= 0
        # example.com has at least one link ("More information...")
        assert "[1]" in result["snapshot"]
    finally:
        close_browser()


def test_browser_screenshot():
    """Test taking a screenshot."""
    from jaybrain.browser import launch_browser, take_screenshot, close_browser

    try:
        launch_browser(headless=True, url="https://example.com")
        result = take_screenshot()
        assert result["status"] == "ok"
        assert result["path"]
        assert Path(result["path"]).exists()
        assert Path(result["path"]).suffix == ".png"
    finally:
        close_browser()


def test_browser_click_by_ref():
    """Test clicking an element by ref number."""
    from jaybrain.browser import (
        launch_browser, snapshot, click, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")
        snap = snapshot()
        # example.com has a "More information..." link
        assert snap["interactive_elements"] >= 1
        result = click(ref=1)
        assert result["status"] == "clicked"
    finally:
        close_browser()


def test_browser_click_by_selector():
    """Test clicking an element by CSS selector."""
    from jaybrain.browser import launch_browser, click, close_browser

    try:
        launch_browser(headless=True, url="https://example.com")
        result = click(selector="a")
        assert result["status"] == "clicked"
    finally:
        close_browser()


def test_browser_type_text():
    """Test typing text into a search box on a real page."""
    from jaybrain.browser import (
        launch_browser, navigate, snapshot, type_text, close_browser,
    )

    try:
        launch_browser(headless=True)
        # Use a page with a text input - DuckDuckGo has a search box
        navigate("https://duckduckgo.com")
        snap = snapshot()
        # Find a textbox ref
        textbox_ref = None
        for line in snap["snapshot"].split("\n"):
            if "textbox" in line and "[" in line:
                ref_str = line.split("[")[1].split("]")[0]
                textbox_ref = int(ref_str)
                break
        if textbox_ref:
            result = type_text("playwright test", ref=textbox_ref)
            assert result["status"] == "typed"
    finally:
        close_browser()


def test_browser_press_key():
    """Test pressing a key."""
    from jaybrain.browser import launch_browser, press_key, close_browser

    try:
        launch_browser(headless=True, url="https://example.com")
        result = press_key("Tab")
        assert result["status"] == "pressed"
        assert result["key"] == "Tab"
    finally:
        close_browser()


def test_browser_evaluate_js():
    """Test evaluating JavaScript."""
    from jaybrain.browser import launch_browser, evaluate_js, close_browser

    try:
        launch_browser(headless=True, url="https://example.com")
        result = evaluate_js("document.title")
        assert result["status"] == "ok"
        assert result["result"]  # should return the page title
    finally:
        close_browser()


def test_no_browser_raises():
    """Test that tools raise when no browser is running."""
    from jaybrain.browser import navigate, close_browser, _state

    # Ensure clean state
    close_browser()

    with pytest.raises(RuntimeError, match="No browser running"):
        navigate("https://example.com")


def test_invalid_ref_raises():
    """Test that invalid ref raises ValueError."""
    from jaybrain.browser import launch_browser, click, close_browser

    try:
        launch_browser(headless=True, url="https://example.com")
        with pytest.raises(ValueError, match="Element ref"):
            click(ref=9999)
    finally:
        close_browser()


def test_server_tools_registered():
    """Test that browser tools are registered in the MCP server."""
    from jaybrain.server import mcp

    tool_names = [t.name for t in mcp._tool_manager._tools.values()]
    expected = [
        "browser_launch", "browser_navigate", "browser_snapshot",
        "browser_screenshot", "browser_click", "browser_type",
        "browser_press_key", "browser_close",
        "browser_session_save", "browser_session_load", "browser_session_list",
        "browser_fill_from_bw", "browser_select_option", "browser_wait",
        "browser_hover", "browser_evaluate", "browser_go_back",
        "browser_go_forward", "browser_tab_list", "browser_tab_new",
        "browser_tab_switch", "browser_tab_close",
    ]
    for name in expected:
        assert name in tool_names, f"Tool {name} not registered in MCP server"


# =========================================================================
# Phase 2 Tests
# =========================================================================

def test_session_save_and_load():
    """Test saving and loading a browser session."""
    from jaybrain.browser import (
        launch_browser, navigate, session_save, session_load,
        session_list, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")

        # Save session
        result = session_save("test_session")
        assert result["status"] == "saved"
        assert result["name"] == "test_session"
        assert Path(result["path"]).exists()

        # List sessions
        listed = session_list()
        assert listed["count"] >= 1
        names = [s["name"] for s in listed["sessions"]]
        assert "test_session" in names

        # Load session into a fresh browser
        result = session_load("test_session", url="https://example.com")
        assert result["status"] == "loaded"
        assert result["name"] == "test_session"
        assert "example.com" in result["url"]
    finally:
        close_browser()
        # Cleanup session file
        session_file = Path(result["path"]) if "path" in locals().get("result", {}) else None
        from jaybrain.browser import SESSIONS_DIR
        cleanup = SESSIONS_DIR / "test_session.json"
        if cleanup.exists():
            cleanup.unlink()


def test_session_load_not_found():
    """Test loading a nonexistent session raises FileNotFoundError."""
    from jaybrain.browser import session_load, close_browser

    close_browser()
    with pytest.raises(FileNotFoundError, match="not found"):
        session_load("nonexistent_session_xyz")


def test_session_list_empty():
    """Test listing sessions when directory doesn't exist yet."""
    from jaybrain.browser import session_list

    result = session_list()
    assert "sessions" in result
    assert "count" in result


def test_select_option_by_value():
    """Test selecting a dropdown option on a page with a <select> element."""
    from jaybrain.browser import (
        launch_browser, evaluate_js, select_option, close_browser,
    )

    try:
        launch_browser(headless=True)
        # Create a test page with a dropdown
        evaluate_js("""
            document.body.innerHTML = `
                <select id="color">
                    <option value="r">Red</option>
                    <option value="g">Green</option>
                    <option value="b">Blue</option>
                </select>
            `;
        """)
        result = select_option(selector="#color", value="g")
        assert result["status"] == "selected"
        assert result["chosen"] == "g"

        # Verify the selection took effect
        val = evaluate_js('document.querySelector("#color").value')
        assert val["result"] == "g"
    finally:
        close_browser()


def test_select_option_by_label():
    """Test selecting a dropdown by visible label text."""
    from jaybrain.browser import (
        launch_browser, evaluate_js, select_option, close_browser,
    )

    try:
        launch_browser(headless=True)
        evaluate_js("""
            document.body.innerHTML = `
                <select id="fruit">
                    <option value="a">Apple</option>
                    <option value="b">Banana</option>
                </select>
            `;
        """)
        result = select_option(selector="#fruit", label="Banana")
        assert result["status"] == "selected"
    finally:
        close_browser()


def test_wait_for_selector():
    """Test waiting for an element to appear."""
    from jaybrain.browser import (
        launch_browser, evaluate_js, wait_for, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")
        # Element already exists
        result = wait_for(selector="h1", state="visible", timeout=5000)
        assert result["status"] == "found"
    finally:
        close_browser()


def test_wait_for_text():
    """Test waiting for text to appear on the page."""
    from jaybrain.browser import (
        launch_browser, wait_for, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")
        result = wait_for(text="Example Domain", state="visible", timeout=5000)
        assert result["status"] == "found"
    finally:
        close_browser()


def test_hover():
    """Test hovering over an element."""
    from jaybrain.browser import (
        launch_browser, snapshot, hover, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")
        snapshot()  # populate refs
        result = hover(ref=1)
        assert result["status"] == "hovered"
    finally:
        close_browser()


def test_hover_by_selector():
    """Test hovering by CSS selector."""
    from jaybrain.browser import (
        launch_browser, hover, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")
        result = hover(selector="a")
        assert result["status"] == "hovered"
    finally:
        close_browser()


# =========================================================================
# Phase 3 Tests - Stealth (Patchright)
# =========================================================================

def test_stealth_launch_and_navigate():
    """Test launching in stealth mode with Patchright."""
    from jaybrain.browser import launch_browser, navigate, snapshot, close_browser

    try:
        result = launch_browser(headless=True, stealth=True)
        assert result["status"] == "launched"
        assert result["stealth"] is True

        result = navigate("https://example.com")
        assert result["status"] == "navigated"
        assert "example.com" in result["url"]

        snap = snapshot()
        assert snap["interactive_elements"] >= 1
    finally:
        close_browser()


def test_stealth_evaluate_js():
    """Test that stealth mode supports JS evaluation."""
    from jaybrain.browser import launch_browser, evaluate_js, close_browser

    try:
        launch_browser(headless=True, stealth=True, url="https://example.com")
        result = evaluate_js("document.title")
        assert result["status"] == "ok"
        assert "Example" in result["result"]
    finally:
        close_browser()


def test_stealth_close_resets_flag():
    """Test that closing stealth browser resets the stealth flag."""
    from jaybrain.browser import launch_browser, close_browser, _state

    launch_browser(headless=True, stealth=True)
    assert _state["_stealth"] is True
    close_browser()
    assert _state["_stealth"] is False


def test_normal_after_stealth():
    """Test switching from stealth back to normal mode."""
    from jaybrain.browser import launch_browser, evaluate_js, close_browser

    try:
        # Launch stealth
        launch_browser(headless=True, stealth=True, url="https://example.com")
        close_browser()

        # Launch normal
        launch_browser(headless=True, stealth=False, url="https://example.com")
        result = evaluate_js("document.title")
        assert result["status"] == "ok"
    finally:
        close_browser()


# =========================================================================
# Phase 4 Tests - Tabs, Navigation History, JS Evaluate
# =========================================================================

def test_go_back_and_forward():
    """Test browser history navigation."""
    from jaybrain.browser import (
        launch_browser, navigate, go_back, go_forward, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")
        navigate("https://www.iana.org/domains/reserved")

        result = go_back()
        assert result["status"] == "navigated_back"
        assert "example.com" in result["url"]

        result = go_forward()
        assert result["status"] == "navigated_forward"
        assert "iana.org" in result["url"]
    finally:
        close_browser()


def test_tab_new_and_list():
    """Test opening tabs and listing them."""
    from jaybrain.browser import (
        launch_browser, tab_new, tab_list, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")

        # Open a second tab
        result = tab_new("https://www.iana.org")
        assert result["status"] == "opened"
        assert result["tab_count"] == 2

        # List tabs
        tabs = tab_list()
        assert tabs["count"] == 2
        urls = [t["url"] for t in tabs["tabs"]]
        assert any("example.com" in u for u in urls)
        assert any("iana.org" in u for u in urls)
    finally:
        close_browser()


def test_tab_switch():
    """Test switching between tabs."""
    from jaybrain.browser import (
        launch_browser, tab_new, tab_switch, tab_list, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")
        tab_new("https://www.iana.org")

        # Switch back to first tab
        result = tab_switch(0)
        assert result["status"] == "switched"
        assert "example.com" in result["url"]

        # Switch to second tab
        result = tab_switch(1)
        assert "iana.org" in result["url"]
    finally:
        close_browser()


def test_tab_close():
    """Test closing a tab."""
    from jaybrain.browser import (
        launch_browser, tab_new, tab_close, tab_list, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")
        tab_new("https://www.iana.org")

        # Close current tab (tab 1)
        result = tab_close()
        assert result["status"] == "closed_tab"
        assert result["remaining_tabs"] == 1

        # Verify we're back on the first tab
        tabs = tab_list()
        assert tabs["count"] == 1
        assert "example.com" in tabs["tabs"][0]["url"]
    finally:
        close_browser()


def test_tab_close_by_index():
    """Test closing a specific tab by index."""
    from jaybrain.browser import (
        launch_browser, tab_new, tab_close, tab_list, close_browser,
    )

    try:
        launch_browser(headless=True, url="https://example.com")
        tab_new("https://www.iana.org")

        # Close tab 0 (example.com) while on tab 1
        result = tab_close(index=0)
        assert result["status"] == "closed_tab"
        assert "example.com" in result["closed_url"]

        tabs = tab_list()
        assert tabs["count"] == 1
        assert "iana.org" in tabs["tabs"][0]["url"]
    finally:
        close_browser()


def test_tab_switch_invalid_index():
    """Test switching to an invalid tab index."""
    from jaybrain.browser import launch_browser, tab_switch, close_browser

    try:
        launch_browser(headless=True, url="https://example.com")
        with pytest.raises(ValueError, match="out of range"):
            tab_switch(99)
    finally:
        close_browser()
