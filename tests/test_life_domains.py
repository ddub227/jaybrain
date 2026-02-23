"""Tests for the life domains goal tracking module."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import get_connection, init_db, now_iso


def _setup_db():
    ensure_data_dirs()
    init_db()


def _create_domain(conn, name="Career", priority=5, hours=10.0):
    """Helper to create a test domain."""
    from jaybrain.life_domains import _generate_id
    did = _generate_id()
    now = now_iso()
    conn.execute(
        """INSERT INTO life_domains
        (id, name, description, priority, hours_per_week, created_at, updated_at)
        VALUES (?, ?, '', ?, ?, ?, ?)""",
        (did, name, priority, hours, now, now),
    )
    conn.commit()
    return did


def _create_goal(conn, domain_id, title="Pass Security+", progress=0.0,
                 target_date=None, auto_metric_source="", status="active"):
    """Helper to create a test goal."""
    from jaybrain.life_domains import _generate_id
    gid = _generate_id()
    now = now_iso()
    conn.execute(
        """INSERT INTO life_goals
        (id, domain_id, title, status, progress, target_date,
         auto_metric_source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (gid, domain_id, title, status, progress, target_date,
         auto_metric_source, now, now),
    )
    conn.commit()
    return gid


class TestDomainOverview:
    def test_empty_domains(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import get_domain_overview

        result = get_domain_overview()
        assert result["total_domains"] == 0
        assert result["domains"] == []

    def test_domain_with_goals(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import get_domain_overview

        conn = get_connection()
        try:
            did = _create_domain(conn, "Career", priority=5)
            _create_goal(conn, did, "Get certified", progress=0.5)
            _create_goal(conn, did, "Find job", progress=0.2)
        finally:
            conn.close()

        result = get_domain_overview()
        assert result["total_domains"] == 1
        domain = result["domains"][0]
        assert domain["name"] == "Career"
        assert domain["goal_count"] == 2
        assert domain["progress"] == 0.35  # avg of 0.5 and 0.2

    def test_multiple_domains_sorted_by_priority(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import get_domain_overview

        conn = get_connection()
        try:
            _create_domain(conn, "Health", priority=3)
            _create_domain(conn, "Career", priority=8)
            _create_domain(conn, "Learning", priority=5)
        finally:
            conn.close()

        result = get_domain_overview()
        names = [d["name"] for d in result["domains"]]
        assert names[0] == "Career"  # Highest priority first


class TestGoalDetail:
    def test_goal_not_found(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import get_goal_detail

        result = get_goal_detail("nonexistent")
        assert "error" in result

    def test_goal_with_subgoals(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import get_goal_detail, _generate_id

        conn = get_connection()
        try:
            did = _create_domain(conn, "Career")
            gid = _create_goal(conn, did, "Pass Security+", progress=0.6)

            # Add sub-goals
            now = now_iso()
            for title in ["Study domain 1", "Study domain 2"]:
                conn.execute(
                    """INSERT INTO life_sub_goals
                    (id, goal_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (_generate_id(), gid, title, now, now),
                )
            conn.commit()
        finally:
            conn.close()

        result = get_goal_detail(gid)
        assert result["title"] == "Pass Security+"
        assert result["progress"] == 0.6
        assert len(result["sub_goals"]) == 2


class TestUpdateProgress:
    def test_update_basic(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import update_goal_progress

        conn = get_connection()
        try:
            did = _create_domain(conn, "Career")
            gid = _create_goal(conn, did, "Pass cert", progress=0.3)
        finally:
            conn.close()

        result = update_goal_progress(gid, 0.7, "Good study session")
        assert result["status"] == "updated"
        assert result["progress"] == 0.7

        # Verify metric was recorded
        conn = get_connection()
        try:
            metrics = conn.execute(
                "SELECT * FROM life_goal_metrics WHERE goal_id = ?", (gid,)
            ).fetchall()
            assert len(metrics) == 1
            assert metrics[0]["metric_value"] == 0.7
        finally:
            conn.close()

    def test_update_clamps_progress(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import update_goal_progress

        conn = get_connection()
        try:
            did = _create_domain(conn, "Test")
            gid = _create_goal(conn, did, "Test goal")
        finally:
            conn.close()

        result = update_goal_progress(gid, 1.5)  # Over 1.0
        assert result["progress"] == 1.0

        result = update_goal_progress(gid, -0.5)  # Under 0.0
        assert result["progress"] == 0.0

    def test_update_nonexistent_goal(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import update_goal_progress

        result = update_goal_progress("fake_id", 0.5)
        assert "error" in result


class TestParseDomainsDoc:
    def test_parse_basic_doc(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import _parse_domains_doc

        text = """# Career
Focus on cybersecurity career

- Pass Security+ (by March 2026)
  - Study domain 1
  - Study domain 2
- Get SOC Analyst role

# Health
Stay active

- Exercise 3x/week
- Sleep 7+ hours
"""
        result = _parse_domains_doc(text)
        assert len(result) == 2
        assert result[0]["name"] == "Career"
        assert len(result[0]["goals"]) == 2
        assert result[0]["goals"][0]["title"] == "Pass Security+"
        assert result[0]["goals"][0]["target_date"] == "March 2026"
        assert len(result[0]["goals"][0]["sub_goals"]) == 2
        assert result[1]["name"] == "Health"

    def test_parse_empty_doc(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import _parse_domains_doc

        result = _parse_domains_doc("")
        assert result == []

    def test_parse_skips_meta_headers(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import _parse_domains_doc

        text = """# Life Domains
## Overview
## Career
- Get job
"""
        result = _parse_domains_doc(text)
        assert len(result) == 1
        assert result[0]["name"] == "Career"


class TestConflictDetection:
    def test_no_conflicts(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import detect_conflicts

        conn = get_connection()
        try:
            _create_domain(conn, "Career", hours=10)
            _create_domain(conn, "Health", hours=5)
        finally:
            conn.close()

        result = detect_conflicts()
        # 15h < 40h default, no overcommit
        time_conflicts = [c for c in result["conflicts"] if c["type"] == "time_overcommit"]
        assert len(time_conflicts) == 0

    def test_time_overcommit(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import detect_conflicts

        conn = get_connection()
        try:
            _create_domain(conn, "Career", hours=25)
            _create_domain(conn, "Health", hours=20)
        finally:
            conn.close()

        result = detect_conflicts()
        time_conflicts = [c for c in result["conflicts"] if c["type"] == "time_overcommit"]
        assert len(time_conflicts) == 1

    def test_overdue_goal(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import detect_conflicts

        conn = get_connection()
        try:
            did = _create_domain(conn, "Career")
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            _create_goal(conn, did, "Past deadline goal", target_date=yesterday)
        finally:
            conn.close()

        result = detect_conflicts()
        overdue = [c for c in result["conflicts"] if c["type"] == "overdue_goal"]
        assert len(overdue) == 1


class TestPriorityStack:
    def test_empty_stack(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import get_priority_stack

        result = get_priority_stack()
        assert result["total_active_goals"] == 0

    def test_priority_ordering(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import get_priority_stack

        conn = get_connection()
        try:
            high_did = _create_domain(conn, "High Priority", priority=10)
            low_did = _create_domain(conn, "Low Priority", priority=1)
            _create_goal(conn, high_did, "Important goal")
            _create_goal(conn, low_did, "Less important goal")
        finally:
            conn.close()

        result = get_priority_stack()
        assert result["priority_stack"][0]["domain"] == "High Priority"

    def test_deadline_boost(self, temp_data_dir):
        _setup_db()
        from jaybrain.life_domains import get_priority_stack

        conn = get_connection()
        try:
            did = _create_domain(conn, "Career", priority=1)
            tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+00:00")
            far_future = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%dT00:00:00+00:00")
            _create_goal(conn, did, "Urgent goal", target_date=tomorrow)
            _create_goal(conn, did, "Distant goal", target_date=far_future)
        finally:
            conn.close()

        result = get_priority_stack()
        assert result["priority_stack"][0]["title"] == "Urgent goal"


class TestMigration9:
    def test_life_domains_tables_exist(self, temp_data_dir):
        _setup_db()

        conn = get_connection()
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "life_domains" in tables
            assert "life_goals" in tables
            assert "life_sub_goals" in tables
            assert "life_goal_dependencies" in tables
            assert "life_goal_metrics" in tables
        finally:
            conn.close()
