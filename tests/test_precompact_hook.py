"""Tests for the PreCompact hook script."""

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db, get_connection

HOOK_SCRIPT = Path(__file__).parent.parent / "scripts" / "precompact_hook.py"


def _import_hook_module(db_path: Path):
    """Import precompact_hook.py as a module with a custom DB_PATH."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("precompact_hook", str(HOOK_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Override AFTER exec_module (exec_module sets the module-level DB_PATH)
    mod.DB_PATH = db_path
    return mod


class TestPreCompactHook:
    def _setup_db(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        conn = get_connection()
        try:
            from jaybrain.db import now_iso
            conn.execute(
                "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
                ("test-session-123", now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

    def test_precompact_creates_checkpoint(self, temp_data_dir):
        self._setup_db(temp_data_dir)
        db_path = temp_data_dir / "jaybrain.db"

        mod = _import_hook_module(db_path)
        data = {
            "session_id": "test-session-123",
            "cwd": "/c/Users/Joshua/jaybrain",
            "hook_event_name": "PreCompact",
        }
        mod.handle_precompact(data)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT checkpoint_summary, checkpoint_at FROM sessions WHERE id = ?",
            ("test-session-123",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["checkpoint_at"] is not None
        assert "PreCompact" in row["checkpoint_summary"]

    def test_precompact_creates_session_if_missing(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        db_path = temp_data_dir / "jaybrain.db"

        mod = _import_hook_module(db_path)
        data = {
            "session_id": "brand-new-session",
            "cwd": "/test",
            "hook_event_name": "PreCompact",
        }
        mod.handle_precompact(data)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            ("brand-new-session",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["checkpoint_at"] is not None

    def test_precompact_ignores_empty_session_id(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        db_path = temp_data_dir / "jaybrain.db"

        mod = _import_hook_module(db_path)
        # No session_id should be a no-op
        mod.handle_precompact({"hook_event_name": "PreCompact"})

        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        assert count == 0

    def test_main_ignores_non_precompact_events(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        db_path = temp_data_dir / "jaybrain.db"

        wrapper = temp_data_dir / "hook_wrapper.py"
        wrapper.write_text(
            "import sys, importlib.util, pathlib\n"
            f"spec = importlib.util.spec_from_file_location('precompact_hook', r'{HOOK_SCRIPT}')\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            f"mod.DB_PATH = pathlib.Path(r'{db_path}')\n"
            "spec.loader.exec_module(mod)\n"
            "mod.main()\n"
        )

        data = {"session_id": "some-session", "hook_event_name": "PostToolUse"}
        subprocess.run(
            [sys.executable, str(wrapper)],
            input=json.dumps(data),
            capture_output=True, text=True, timeout=10,
        )

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT * FROM sessions WHERE id = 'some-session'").fetchone()
        conn.close()
        assert row is None

    def test_precompact_handles_empty_stdin(self, temp_data_dir):
        ensure_data_dirs()
        init_db()
        db_path = temp_data_dir / "jaybrain.db"

        wrapper = temp_data_dir / "hook_wrapper.py"
        wrapper.write_text(
            "import sys, importlib.util, pathlib\n"
            f"spec = importlib.util.spec_from_file_location('precompact_hook', r'{HOOK_SCRIPT}')\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            f"mod.DB_PATH = pathlib.Path(r'{db_path}')\n"
            "spec.loader.exec_module(mod)\n"
            "mod.main()\n"
        )

        result = subprocess.run(
            [sys.executable, str(wrapper)],
            input="",
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_precompact_performance(self, temp_data_dir):
        """Verify the hook function completes in under 5 seconds."""
        self._setup_db(temp_data_dir)
        db_path = temp_data_dir / "jaybrain.db"

        mod = _import_hook_module(db_path)
        data = {
            "session_id": "test-session-123",
            "cwd": "/test",
            "hook_event_name": "PreCompact",
        }

        start = time.monotonic()
        mod.handle_precompact(data)
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, f"Hook took {elapsed:.1f}s (must be <5s)"
