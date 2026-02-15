"""Automate Gmail App Password creation and store as user env var.

Launches a visible browser to Google App Passwords.
JJ handles sign-in and MFA, then the script takes over:
creates the app password, captures it, and sets it as a
persistent user-level environment variable.

Run:  python scripts/setup_gmail_app_password.py
"""

import subprocess
import sys
import time

# Ensure jaybrain is importable
sys.path.insert(0, "src")

from jaybrain.browser import (
    launch_browser,
    navigate,
    snapshot,
    click,
    type_text,
    close_browser,
)

APP_PASSWORDS_URL = "https://myaccount.google.com/apppasswords"
ENV_VAR_NAME = "JAYBRAIN_GMAIL_APP_PASSWORD"


def wait_for_user(msg: str):
    """Pause until the user presses Enter."""
    print(f"\n>>> {msg}")
    input(">>> Press Enter when ready...")
    print()


def find_ref_by_text(snap: dict, text: str) -> int | None:
    """Search snapshot items for a ref matching partial text (case-insensitive)."""
    for item in snap.get("items", []):
        if item.get("ref") is not None:
            name = (item.get("name") or "").lower()
            if text.lower() in name:
                return item["ref"]
    return None


def find_ref_by_role(snap: dict, role: str, text: str = "") -> int | None:
    """Search snapshot for ref by role and optional text."""
    for item in snap.get("items", []):
        if item.get("ref") is not None and item.get("role") == role:
            name = (item.get("name") or "").lower()
            if not text or text.lower() in name:
                return item["ref"]
    return None


def set_user_env_var(name: str, value: str):
    """Set a persistent user-level environment variable via PowerShell."""
    cmd = (
        f'[System.Environment]::SetEnvironmentVariable('
        f'"{name}", "{value}", "User")'
    )
    result = subprocess.run(
        ["powershell", "-Command", cmd],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        print(f"ERROR setting env var: {result.stderr}")
        return False
    return True


def main():
    print("=" * 60)
    print("  Gmail App Password Setup for JayBrain Daily Briefing")
    print("=" * 60)
    print()

    # Step 1: Launch visible browser
    print("[1/5] Launching browser...")
    result = launch_browser(headless=False, url=APP_PASSWORDS_URL)
    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1
    print("  Browser opened.")

    # Step 2: Wait for user to sign in
    wait_for_user(
        "Sign in to your Google account and complete MFA if prompted.\n"
        "    You should land on the 'App passwords' page."
    )

    # Step 3: Take snapshot and find the app name input
    print("[2/5] Reading page...")
    snap = snapshot()

    # Debug: show what we see
    items = snap.get("items", [])
    print(f"  Found {len(items)} elements on page.")

    # Look for the app name input field
    app_name_ref = find_ref_by_role(snap, "textbox")
    if app_name_ref is None:
        # Try after a short wait
        time.sleep(2)
        snap = snapshot()
        app_name_ref = find_ref_by_role(snap, "textbox")

    if app_name_ref is not None:
        print(f"  Found app name input (ref={app_name_ref})")
        print("[3/5] Typing app name 'JayBrain'...")
        type_text("JayBrain", ref=app_name_ref)
        time.sleep(1)
    else:
        print("  Could not auto-find the app name input.")
        print("  Please type 'JayBrain' in the App name field manually.")
        wait_for_user("Type 'JayBrain' in the app name field, then come back here.")

    # Step 4: Click Create
    print("[4/5] Looking for Create button...")
    snap = snapshot()
    create_ref = find_ref_by_text(snap, "create")
    if create_ref is None:
        create_ref = find_ref_by_role(snap, "button", "create")

    if create_ref is not None:
        print(f"  Clicking Create (ref={create_ref})...")
        click(ref=create_ref)
        time.sleep(3)
    else:
        print("  Could not find Create button.")
        wait_for_user("Click the 'Create' button manually.")

    # Step 5: Capture the generated password
    print("[5/5] Capturing generated password...")
    snap = snapshot()

    # The generated password typically appears in a textbox, code element,
    # or a specially formatted span. Search the snapshot text.
    password = None
    raw_text = snap.get("raw_text", "")

    # Look for the 16-char app password pattern in snapshot items
    for item in snap.get("items", []):
        name = item.get("name", "")
        # App passwords are 16 chars, sometimes with spaces (xxxx xxxx xxxx xxxx)
        cleaned = name.replace(" ", "")
        if len(cleaned) == 16 and cleaned.isalpha() and cleaned.islower():
            password = cleaned
            break

    if not password:
        # Check all text content for the pattern
        for item in snap.get("items", []):
            text = item.get("name", "")
            for word in text.split():
                cleaned = word.replace(" ", "")
                if len(cleaned) == 16 and cleaned.isalpha() and cleaned.islower():
                    password = cleaned
                    break
            if password:
                break

    if not password:
        print("  Could not auto-capture the password from the page.")
        print("  Copy it from the browser, then paste it here.")
        password = input("  Paste your app password: ").strip().replace(" ", "")

    if not password:
        print("ERROR: No password provided. Aborting.")
        close_browser()
        return 1

    print(f"  Captured password ({len(password)} chars)")

    # Step 6: Set environment variable
    print()
    print(f"Setting {ENV_VAR_NAME} as persistent user environment variable...")
    if set_user_env_var(ENV_VAR_NAME, password):
        print("  SUCCESS! Environment variable set.")
        print()
        print("  The daily briefing scheduled task will pick this up")
        print("  on its next run (tomorrow 7:00 AM).")
        print()
        print("  To test now, open a NEW terminal and run:")
        print("    python -m jaybrain.daily_briefing")
    else:
        print("  FAILED to set environment variable.")
        print(f"  Run this manually in PowerShell:")
        print(f'    [Environment]::SetEnvironmentVariable("{ENV_VAR_NAME}", "<your-password>", "User")')

    close_browser()
    return 0


if __name__ == "__main__":
    sys.exit(main())
