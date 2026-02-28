"""Tests for GitShadow working tree snapshots (Feature 3)."""

import json
import os
import sqlite3
import subprocess

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import init_db
from jaybrain.git_shadow import (
    _git_cmd,
    _snapshot_repo,
    query_shadow_history,
    restore_file,
    run_git_shadow,
)


def _setup(temp_data_dir):
    ensure_data_dirs()
    init_db()


def _create_git_repo(path):
    """Create a minimal git repo with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), capture_output=True,
    )
    # Create initial file and commit
    (path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(path), capture_output=True,
    )


class TestGitCmd:
    def test_basic_command(self, tmp_path):
        _create_git_repo(tmp_path / "repo")
        rc, output = _git_cmd(["status"], str(tmp_path / "repo"))
        assert rc == 0
        assert "On branch" in output

    def test_invalid_command(self, tmp_path):
        rc, output = _git_cmd(["invalid-command-xyz"], str(tmp_path))
        assert rc != 0

    def test_nonexistent_dir(self):
        rc, output = _git_cmd(["status"], "/nonexistent/path")
        assert rc != 0


class TestSnapshotRepo:
    def test_clean_repo_skipped(self, temp_data_dir, tmp_path):
        _setup(temp_data_dir)
        repo = tmp_path / "clean_repo"
        _create_git_repo(repo)

        result = _snapshot_repo(str(repo))
        assert result["status"] == "clean"
        assert result["skipped"] is True

    def test_dirty_repo_creates_stash(self, temp_data_dir, tmp_path):
        _setup(temp_data_dir)
        repo = tmp_path / "dirty_repo"
        _create_git_repo(repo)

        # Modify a tracked file (git stash create needs tracked changes)
        (repo / "README.md").write_text("# Modified content")

        result = _snapshot_repo(str(repo))
        assert result["status"] == "snapshot"
        assert "stash_hash" in result
        assert result["changed_files"] > 0

        # Verify DB entry
        history = query_shadow_history()
        assert len(history) == 1
        assert history[0]["repo_path"] == str(repo)

    def test_untracked_only_skips_stash(self, temp_data_dir, tmp_path):
        """Repos with only untracked files skip stash creation."""
        _setup(temp_data_dir)
        repo = tmp_path / "untracked_repo"
        _create_git_repo(repo)

        # Only add an untracked file (no tracked modifications)
        (repo / "new_file.py").write_text("print('hello')")

        result = _snapshot_repo(str(repo))
        assert result["status"] == "untracked_only"
        assert result["skipped"] is True

    def test_modified_tracked_file(self, temp_data_dir, tmp_path):
        _setup(temp_data_dir)
        repo = tmp_path / "modified_repo"
        _create_git_repo(repo)

        # Modify existing tracked file
        (repo / "README.md").write_text("# Modified")

        result = _snapshot_repo(str(repo))
        assert result["status"] == "snapshot"

    def test_working_tree_not_modified(self, temp_data_dir, tmp_path):
        """git stash create should NOT modify the working tree."""
        _setup(temp_data_dir)
        repo = tmp_path / "preserve_repo"
        _create_git_repo(repo)

        # Make tracked changes
        (repo / "README.md").write_text("# Modified")

        _snapshot_repo(str(repo))

        # Verify working tree is unchanged
        assert (repo / "README.md").read_text() == "# Modified"


class TestRunGitShadow:
    def test_disabled_returns_immediately(self, temp_data_dir, monkeypatch):
        import jaybrain.git_shadow as gs_mod
        monkeypatch.setattr(gs_mod, "GIT_SHADOW_ENABLED", False)

        result = run_git_shadow()
        assert result["status"] == "disabled"

    def test_not_a_repo_skipped(self, temp_data_dir, monkeypatch):
        _setup(temp_data_dir)
        not_a_repo = temp_data_dir / "not_a_repo"
        not_a_repo.mkdir()

        import jaybrain.git_shadow as gs_mod
        monkeypatch.setattr(gs_mod, "GIT_SHADOW_REPO_PATHS", [str(not_a_repo)])

        result = run_git_shadow()
        assert result["repos_checked"] == 1
        assert result["snapshots_created"] == 0
        assert result["details"][0]["status"] == "not_a_repo"

    def test_multiple_repos(self, temp_data_dir, tmp_path, monkeypatch):
        _setup(temp_data_dir)

        repo1 = tmp_path / "repo1"
        repo2 = tmp_path / "repo2"
        _create_git_repo(repo1)
        _create_git_repo(repo2)

        # Make tracked changes in repo1 only
        (repo1 / "README.md").write_text("changed")

        import jaybrain.git_shadow as gs_mod
        monkeypatch.setattr(
            gs_mod, "GIT_SHADOW_REPO_PATHS", [str(repo1), str(repo2)]
        )

        result = run_git_shadow()
        assert result["repos_checked"] == 2
        assert result["snapshots_created"] == 1


class TestQueryHistory:
    def test_query_all(self, temp_data_dir, tmp_path):
        _setup(temp_data_dir)
        repo = tmp_path / "query_repo"
        _create_git_repo(repo)

        # Create two snapshots via tracked modifications
        (repo / "README.md").write_text("change 1")
        _snapshot_repo(str(repo))

        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "commit 1"],
            cwd=str(repo), capture_output=True,
        )
        (repo / "README.md").write_text("change 2")
        _snapshot_repo(str(repo))

        results = query_shadow_history()
        assert len(results) == 2

    def test_filter_by_repo(self, temp_data_dir, tmp_path):
        _setup(temp_data_dir)
        repo = tmp_path / "filter_repo"
        _create_git_repo(repo)
        (repo / "README.md").write_text("modified")
        _snapshot_repo(str(repo))

        results = query_shadow_history(repo="filter_repo")
        assert len(results) == 1

        results = query_shadow_history(repo="nonexistent")
        assert len(results) == 0

    def test_filter_by_file(self, temp_data_dir, tmp_path):
        _setup(temp_data_dir)
        repo = tmp_path / "file_filter_repo"
        _create_git_repo(repo)
        (repo / "README.md").write_text("modified for filter test")
        _snapshot_repo(str(repo))

        results = query_shadow_history(file="README.md")
        assert len(results) == 1

    def test_limit(self, temp_data_dir, tmp_path):
        _setup(temp_data_dir)
        repo = tmp_path / "limit_repo"
        _create_git_repo(repo)

        for i in range(5):
            (repo / "README.md").write_text(f"content version {i}")
            _snapshot_repo(str(repo))
            subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", f"commit {i}"],
                cwd=str(repo), capture_output=True,
            )

        results = query_shadow_history(limit=2)
        assert len(results) == 2


class TestRestoreFile:
    def test_restore_existing_file(self, temp_data_dir, tmp_path):
        _setup(temp_data_dir)
        repo = tmp_path / "restore_repo"
        _create_git_repo(repo)

        # Modify tracked file with known content
        (repo / "README.md").write_text("original_content = True")
        _snapshot_repo(str(repo))

        # Get the shadow ID
        history = query_shadow_history()
        assert len(history) == 1
        shadow_id = history[0]["id"]

        result = restore_file(shadow_id, "README.md")
        assert "error" not in result
        assert "original_content = True" in result["content"]

    def test_restore_invalid_shadow_id(self, temp_data_dir):
        _setup(temp_data_dir)

        result = restore_file("nonexistent", "foo.py")
        assert "error" in result
        assert "not found" in result["error"]

    def test_restore_invalid_file_path(self, temp_data_dir, tmp_path):
        _setup(temp_data_dir)
        repo = tmp_path / "restore_bad_file"
        _create_git_repo(repo)
        (repo / "README.md").write_text("modified")
        _snapshot_repo(str(repo))

        history = query_shadow_history()
        shadow_id = history[0]["id"]

        result = restore_file(shadow_id, "does_not_exist.txt")
        assert "error" in result
