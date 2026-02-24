"""Tests for the trash (soft-delete recycle bin) module."""

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from jaybrain.config import TRASH_DIR, ensure_data_dirs
from jaybrain.db import get_connection, init_db
from jaybrain.trash import (
    _categorize_file,
    _sha256,
    list_trash,
    restore_file,
    run_auto_cleanup,
    scan_files,
    sweep_expired,
    trash_batch,
    trash_file,
)


def _setup(temp_data_dir):
    ensure_data_dirs()
    init_db()


class TestHelpers:
    def test_sha256_file(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "test.txt"
        f.write_text("hello world")
        h = _sha256(f)
        assert len(h) == 64
        assert h == _sha256(f)  # deterministic

    def test_sha256_dir_returns_empty(self, temp_data_dir):
        _setup(temp_data_dir)
        d = temp_data_dir / "subdir"
        d.mkdir()
        assert _sha256(d) == ""

    def test_categorize_bytecode(self):
        assert _categorize_file(Path("__pycache__")) == "bytecode"
        assert _categorize_file(Path("foo.pyc")) == "bytecode"

    def test_categorize_cache(self):
        assert _categorize_file(Path(".pytest_cache")) == "cache"
        assert _categorize_file(Path(".mypy_cache")) == "cache"
        assert _categorize_file(Path(".coverage")) == "cache"

    def test_categorize_build(self):
        assert _categorize_file(Path("dist")) == "build_artifact"
        assert _categorize_file(Path("build")) == "build_artifact"
        assert _categorize_file(Path("foo.egg-info")) == "build_artifact"

    def test_categorize_log(self):
        assert _categorize_file(Path("app.log")) == "log"

    def test_categorize_temp(self):
        assert _categorize_file(Path("null")) == "temp"
        assert _categorize_file(Path("foo.tmp")) == "temp"
        assert _categorize_file(Path("Thumbs.db")) == "temp"

    def test_categorize_source(self):
        assert _categorize_file(Path("module.py")) == "source"

    def test_categorize_general(self):
        assert _categorize_file(Path("readme.txt")) == "general"


class TestTrashFile:
    def test_trash_basic_file(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "junk.txt"
        f.write_text("garbage")

        result = trash_file(str(f), reason="test cleanup")

        assert "error" not in result
        assert result["category"] == "general"
        assert result["size_bytes"] == 7
        assert not f.exists()  # moved away
        assert Path(result["trash_path"]).exists()

    def test_trash_directory(self, temp_data_dir):
        _setup(temp_data_dir)
        d = temp_data_dir / "__pycache__"
        d.mkdir()
        (d / "foo.pyc").write_bytes(b"\x00" * 100)

        result = trash_file(str(d), reason="bytecode cleanup")

        assert "error" not in result
        assert result["is_dir"] is True
        assert result["category"] == "bytecode"
        assert not d.exists()

    def test_trash_nonexistent(self, temp_data_dir):
        _setup(temp_data_dir)
        result = trash_file("/nonexistent/file.txt")
        assert "error" in result

    def test_trash_records_manifest(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "test.txt"
        f.write_text("data")

        result = trash_file(str(f))
        entry_id = result["id"]

        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM trash_manifest WHERE id = ?", (entry_id,)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["original_path"] == str(f.resolve())
        assert row["category"] == "general"
        assert row["sha256"] != ""

    def test_trash_computes_expiry(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "app.log"
        f.write_text("log data")

        result = trash_file(str(f))
        assert result["category"] == "log"
        assert result["retention_days"] == 14  # log retention


class TestRestore:
    def test_restore_file(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "important.py"
        f.write_text("def main(): pass")
        original_hash = _sha256(f)

        # Trash it
        result = trash_file(str(f))
        entry_id = result["id"]
        assert not f.exists()

        # Restore it
        restore_result = restore_file(entry_id)
        assert restore_result.get("restored") is True
        assert f.exists()
        assert f.read_text() == "def main(): pass"
        assert _sha256(f) == original_hash

    def test_restore_nonexistent_entry(self, temp_data_dir):
        _setup(temp_data_dir)
        result = restore_file("nonexistent_id")
        assert "error" in result

    def test_restore_collision(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "file.txt"
        f.write_text("original")

        result = trash_file(str(f))
        entry_id = result["id"]

        # Create a new file at the same path
        f.write_text("new version")

        restore_result = restore_file(entry_id)
        assert "error" in restore_result
        assert "already occupied" in restore_result["error"]

    def test_restore_removes_manifest_entry(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "test.txt"
        f.write_text("data")

        result = trash_file(str(f))
        entry_id = result["id"]

        restore_file(entry_id)

        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM trash_manifest WHERE id = ?", (entry_id,)
        ).fetchone()
        conn.close()
        assert row is None


class TestListTrash:
    def test_empty_trash(self, temp_data_dir):
        _setup(temp_data_dir)
        result = list_trash()
        assert result["count"] == 0

    def test_list_after_trash(self, temp_data_dir):
        _setup(temp_data_dir)
        f1 = temp_data_dir / "a.txt"
        f1.write_text("aaa")
        f2 = temp_data_dir / "b.log"
        f2.write_text("bbb")

        trash_file(str(f1))
        trash_file(str(f2))

        result = list_trash()
        assert result["count"] == 2

    def test_list_by_category(self, temp_data_dir):
        _setup(temp_data_dir)
        f1 = temp_data_dir / "a.txt"
        f1.write_text("aaa")
        f2 = temp_data_dir / "b.log"
        f2.write_text("bbb")

        trash_file(str(f1))
        trash_file(str(f2))

        result = list_trash(category="log")
        assert result["count"] == 1
        assert result["items"][0]["category"] == "log"


class TestSweep:
    def test_sweep_no_expired(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "test.txt"
        f.write_text("data")
        trash_file(str(f))

        result = sweep_expired()
        assert result["swept"] == 0

    def test_sweep_expired_entries(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "test.txt"
        f.write_text("data")
        trash_result = trash_file(str(f))
        entry_id = trash_result["id"]

        # Manually set expiry to the past
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        conn = get_connection()
        conn.execute(
            "UPDATE trash_manifest SET expires_at = ? WHERE id = ?",
            (past, entry_id),
        )
        conn.commit()
        conn.close()

        result = sweep_expired()
        assert result["swept"] == 1

        # File should be permanently gone
        assert not Path(trash_result["trash_path"]).exists()

        # Manifest entry should be removed
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM trash_manifest WHERE id = ?", (entry_id,)
        ).fetchone()
        conn.close()
        assert row is None


class TestTrashBatch:
    def test_batch_multiple_files(self, temp_data_dir):
        _setup(temp_data_dir)
        files = []
        for i in range(3):
            f = temp_data_dir / f"file{i}.txt"
            f.write_text(f"content {i}")
            files.append({"path": str(f), "reason": "batch test"})

        result = trash_batch(files)
        assert result["trashed"] == 3
        assert result["errors"] == 0

    def test_batch_with_errors(self, temp_data_dir):
        _setup(temp_data_dir)
        f = temp_data_dir / "real.txt"
        f.write_text("real file")

        items = [
            {"path": str(f), "reason": "exists"},
            {"path": "/nonexistent/fake.txt", "reason": "missing"},
        ]

        result = trash_batch(items)
        assert result["trashed"] == 1
        assert result["errors"] == 1


class TestScanFiles:
    def test_scan_empty_dir(self, temp_data_dir):
        _setup(temp_data_dir)
        empty_dir = temp_data_dir / "empty_project"
        empty_dir.mkdir()

        result = scan_files(scan_dirs=[empty_dir])
        assert result["auto_count"] == 0
        assert result["review_count"] == 0

    def test_scan_finds_suspect_files(self, temp_data_dir):
        _setup(temp_data_dir)
        project = temp_data_dir / "myproject"
        project.mkdir()

        # Create a suspect file
        null_file = project / "null"
        null_file.write_text("junk")

        # Mock git commands to say file is not tracked and not ignored
        with patch("jaybrain.trash._find_git_root", return_value=None):
            result = scan_files(scan_dirs=[project])

        assert result["review_count"] >= 1
        paths = [i["path"] for i in result["review"]]
        assert str(null_file) in paths

    def test_scan_finds_pycache(self, temp_data_dir):
        _setup(temp_data_dir)
        project = temp_data_dir / "myproject"
        project.mkdir()
        cache = project / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-313.pyc").write_bytes(b"\x00" * 50)

        # Mock: not tracked, is ignored
        with patch("jaybrain.trash._find_git_root", return_value=project):
            with patch("jaybrain.trash._is_git_tracked", return_value=False):
                with patch("jaybrain.trash._is_git_ignored", return_value=True):
                    result = scan_files(scan_dirs=[project])

        assert result["auto_count"] >= 1
        categories = [i["category"] for i in result["auto"]]
        assert "bytecode" in categories


class TestRunAutoCleanup:
    def test_auto_cleanup_scan_finds_pycache(self, temp_data_dir):
        """Verify scan detects __pycache__ dirs as auto-trashable."""
        _setup(temp_data_dir)
        project = temp_data_dir / "myproject"
        project.mkdir()
        cache = project / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-313.pyc").write_bytes(b"\x00" * 50)

        with patch("jaybrain.trash._find_git_root", return_value=project):
            with patch("jaybrain.trash._is_git_tracked", return_value=False):
                with patch("jaybrain.trash._is_git_ignored", return_value=True):
                    scan = scan_files(scan_dirs=[project])

        assert scan["auto_count"] >= 1
        categories = [i["category"] for i in scan["auto"]]
        assert "bytecode" in categories

    def test_auto_cleanup_can_trash_directory(self, temp_data_dir):
        """Verify trash_file moves a __pycache__ directory to trash."""
        _setup(temp_data_dir)
        cache = temp_data_dir / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-313.pyc").write_bytes(b"\x00" * 50)

        result = trash_file(str(cache), reason="bytecode cleanup", category="bytecode", auto=True)

        assert "error" not in result, f"trash_file error: {result}"
        assert result["is_dir"] is True
        assert result["category"] == "bytecode"
        assert result["retention_days"] == 7
        # Original location should be gone
        assert not cache.exists()

    def test_auto_cleanup_skips_tracked(self, temp_data_dir):
        _setup(temp_data_dir)
        project = temp_data_dir / "myproject"
        project.mkdir()
        f = project / "important.pyc"
        f.write_bytes(b"\x00" * 50)

        with patch("jaybrain.trash._find_git_root", return_value=project):
            with patch("jaybrain.trash._is_git_tracked", return_value=True):
                scan = scan_files(scan_dirs=[project])

        # Tracked files should not appear in auto list
        assert scan["auto_count"] == 0
        assert f.exists()
