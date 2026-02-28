"""Tests for file deletion log (Feature 2)."""

import os
import sqlite3
import time

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db
from jaybrain.file_watcher import (
    DeletionHandler,
    FileWatcherThread,
    _should_ignore,
    query_deletions,
)


def _setup(temp_data_dir):
    ensure_data_dirs()
    init_db()


class TestIgnorePatterns:
    def test_pyc_ignored(self):
        assert _should_ignore("/project/__pycache__/foo.pyc") is True

    def test_pycache_dir_ignored(self):
        assert _should_ignore("/project/__pycache__") is True

    def test_git_objects_ignored(self):
        assert _should_ignore("/project/.git/objects/ab/cd1234") is True

    def test_git_index_lock_ignored(self):
        assert _should_ignore("/project/.git/index.lock") is True

    def test_node_modules_ignored(self):
        assert _should_ignore("/project/node_modules/foo/bar.js") is True

    def test_tmp_files_ignored(self):
        assert _should_ignore("/project/data/something.tmp") is True

    def test_swap_files_ignored(self):
        assert _should_ignore("/project/.daemon.py.swp") is True

    def test_source_file_not_ignored(self):
        assert _should_ignore("/project/src/main.py") is False

    def test_config_file_not_ignored(self):
        assert _should_ignore("/project/.mcp.json") is False

    def test_markdown_not_ignored(self):
        assert _should_ignore("/project/docs/README.md") is False

    def test_custom_pattern_respected(self):
        assert _should_ignore("/project/build/output.js", ["*/build/*"]) is True

    def test_custom_pattern_does_not_affect_default(self):
        # Custom pattern doesn't break default behavior
        assert _should_ignore("/project/src/main.py", ["*/build/*"]) is False

    def test_windows_paths_normalized(self):
        assert _should_ignore("C:\\project\\__pycache__\\foo.pyc") is True


class TestDeletionHandler:
    def test_deletion_logged_to_db(self, temp_data_dir):
        _setup(temp_data_dir)

        handler = DeletionHandler()
        handler._log_deletion(
            file_path="/project/.mcp.json",
            filename=".mcp.json",
            event_type="file_deleted",
        )

        results = query_deletions()
        assert len(results) == 1
        assert results[0]["filename"] == ".mcp.json"
        assert results[0]["event_type"] == "file_deleted"
        assert results[0]["pid"] == os.getpid()

    def test_multiple_deletions_logged(self, temp_data_dir):
        _setup(temp_data_dir)

        handler = DeletionHandler()
        for name in ["a.py", "b.py", "c.py"]:
            handler._log_deletion(
                file_path=f"/project/{name}",
                filename=name,
                event_type="file_deleted",
            )

        results = query_deletions()
        assert len(results) == 3

    def test_dir_deletion_logged(self, temp_data_dir):
        _setup(temp_data_dir)

        handler = DeletionHandler()
        handler._log_deletion(
            file_path="/project/src/old_module",
            filename="old_module",
            event_type="dir_deleted",
        )

        results = query_deletions()
        assert len(results) == 1
        assert results[0]["event_type"] == "dir_deleted"


class TestQueryDeletions:
    def test_query_all(self, temp_data_dir):
        _setup(temp_data_dir)

        handler = DeletionHandler()
        handler._log_deletion("/project/a.py", "a.py", "file_deleted")
        handler._log_deletion("/project/b.py", "b.py", "file_deleted")

        results = query_deletions()
        assert len(results) == 2

    def test_query_with_path_filter(self, temp_data_dir):
        _setup(temp_data_dir)

        handler = DeletionHandler()
        handler._log_deletion("/project/src/foo.py", "foo.py", "file_deleted")
        handler._log_deletion("/project/docs/bar.md", "bar.md", "file_deleted")

        results = query_deletions(path="src")
        assert len(results) == 1
        assert results[0]["filename"] == "foo.py"

    def test_query_with_since_filter(self, temp_data_dir):
        _setup(temp_data_dir)

        handler = DeletionHandler()
        handler._log_deletion("/project/a.py", "a.py", "file_deleted")

        # Query with a past date should find it
        results = query_deletions(since="2020-01-01")
        assert len(results) == 1

        # Query with a future date should not find it
        results = query_deletions(since="2099-01-01")
        assert len(results) == 0

    def test_query_limit(self, temp_data_dir):
        _setup(temp_data_dir)

        handler = DeletionHandler()
        for i in range(10):
            handler._log_deletion(f"/project/file{i}.py", f"file{i}.py", "file_deleted")

        results = query_deletions(limit=3)
        assert len(results) == 3

    def test_query_empty_db(self, temp_data_dir):
        _setup(temp_data_dir)
        results = query_deletions()
        assert len(results) == 0


class TestFileWatcherThread:
    def test_start_and_stop(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir)

        # Point watcher at the temp dir
        import jaybrain.file_watcher as fw_mod
        monkeypatch.setattr(fw_mod, "FILE_WATCHER_ENABLED", True)
        monkeypatch.setattr(fw_mod, "FILE_WATCHER_PATHS", [str(temp_data_dir)])

        watcher = FileWatcherThread()
        watcher.start()
        assert watcher.is_running

        watcher.stop()
        assert not watcher.is_running

    def test_disabled_does_not_start(self, temp_data_dir, monkeypatch):
        import jaybrain.file_watcher as fw_mod
        monkeypatch.setattr(fw_mod, "FILE_WATCHER_ENABLED", False)

        watcher = FileWatcherThread()
        watcher.start()
        assert not watcher.is_running

    def test_nonexistent_path_handled(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir)

        import jaybrain.file_watcher as fw_mod
        monkeypatch.setattr(fw_mod, "FILE_WATCHER_ENABLED", True)
        monkeypatch.setattr(fw_mod, "FILE_WATCHER_PATHS", ["/nonexistent/path"])

        watcher = FileWatcherThread()
        watcher.start()
        # Should not crash, just warn
        watcher.stop()
