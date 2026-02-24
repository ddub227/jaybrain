"""Tests for the time_allocation module."""

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from jaybrain.time_allocation import (
    _map_cwd_to_domain,
    calculate_active_time,
    query_time_by_domain,
    get_weekly_report,
    get_daily_breakdown,
    check_time_allocation,
)


# ---------------------------------------------------------------------------
# CWD-to-domain mapping
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_domain_cache():
    """Clear the domain name resolution cache between tests."""
    from jaybrain import time_allocation
    time_allocation._domain_name_cache.clear()
    yield
    time_allocation._domain_name_cache.clear()


class TestCwdMapping:
    """CWD mapping tests. Mock DB so _resolve_domain_name falls back to short labels."""

    def _mock_no_db(self):
        """Patch get_connection so _resolve_domain_name returns short labels as-is."""
        return patch("jaybrain.time_allocation.get_connection", side_effect=Exception("no db"))

    def test_jaybrain(self):
        with self._mock_no_db():
            assert _map_cwd_to_domain("C:\\Users\\Joshua\\jaybrain") == "JayBrain Development"

    def test_homelab(self):
        with self._mock_no_db():
            assert _map_cwd_to_domain("/home/user/projects/homelab/notes") == "Learning"

    def test_sigma_rules(self):
        with self._mock_no_db():
            assert _map_cwd_to_domain("C:\\Users\\Joshua\\projects\\sigma-detection-rules") == "Learning"

    def test_blog(self):
        with self._mock_no_db():
            assert _map_cwd_to_domain("/home/user/ddub227.github.io/_posts") == "Career"

    def test_job_search(self):
        with self._mock_no_db():
            assert _map_cwd_to_domain("C:\\Users\\Joshua\\Documents\\job_search") == "Career"

    def test_case_insensitive(self):
        with self._mock_no_db():
            assert _map_cwd_to_domain("C:\\Users\\Joshua\\JAYBRAIN") == "JayBrain Development"

    def test_uncategorized(self):
        with self._mock_no_db():
            assert _map_cwd_to_domain("/tmp/random/project") == "Uncategorized"

    def test_empty(self):
        with self._mock_no_db():
            assert _map_cwd_to_domain("") == "Uncategorized"


# ---------------------------------------------------------------------------
# Active time calculation
# ---------------------------------------------------------------------------


def _make_activity_rows(timestamps: list[str]) -> list[dict]:
    """Build mock fetchall() results from ISO timestamp strings."""
    return [{"timestamp": ts} for ts in timestamps]


class TestCalculateActiveTime:
    def test_no_events(self):
        """Zero events = zero hours."""
        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = []
            assert calculate_active_time("sess-1") == 0.0

    def test_one_event(self):
        """Single event = zero hours (need at least 2 for a gap)."""
        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = _make_activity_rows([
                "2026-02-22T10:00:00+00:00",
            ])
            assert calculate_active_time("sess-1") == 0.0

    def test_two_events_within_threshold(self):
        """10-minute gap counts as active time."""
        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = _make_activity_rows([
                "2026-02-22T10:00:00+00:00",
                "2026-02-22T10:10:00+00:00",
            ])
            hours = calculate_active_time("sess-1")
            assert abs(hours - 10 / 60) < 0.001

    def test_gap_over_threshold_excluded(self):
        """45-minute gap (> 30 min threshold) is treated as idle."""
        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = _make_activity_rows([
                "2026-02-22T10:00:00+00:00",
                "2026-02-22T10:10:00+00:00",  # +10 min (active)
                "2026-02-22T10:55:00+00:00",  # +45 min (idle, skipped)
                "2026-02-22T11:05:00+00:00",  # +10 min (active)
            ])
            hours = calculate_active_time("sess-1")
            # 10 min + 10 min = 20 min = 0.333... hours
            assert abs(hours - 20 / 60) < 0.001

    def test_exact_threshold_included(self):
        """Gap exactly at threshold (30 min) should be included."""
        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = _make_activity_rows([
                "2026-02-22T10:00:00+00:00",
                "2026-02-22T10:30:00+00:00",  # exactly 30 min
            ])
            hours = calculate_active_time("sess-1")
            assert abs(hours - 0.5) < 0.001

    def test_custom_threshold(self):
        """Custom idle threshold is respected."""
        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = _make_activity_rows([
                "2026-02-22T10:00:00+00:00",
                "2026-02-22T10:20:00+00:00",  # +20 min
            ])
            # With 15-min threshold, 20 min gap is idle
            hours = calculate_active_time("sess-1", idle_threshold_min=15)
            assert hours == 0.0

            # With 25-min threshold, 20 min gap counts
            hours = calculate_active_time("sess-1", idle_threshold_min=25)
            assert abs(hours - 20 / 60) < 0.001

    def test_multi_event_realistic(self):
        """Realistic session: several tool calls over 2 hours with a lunch break."""
        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = _make_activity_rows([
                "2026-02-22T09:00:00+00:00",
                "2026-02-22T09:05:00+00:00",  # +5 min
                "2026-02-22T09:12:00+00:00",  # +7 min
                "2026-02-22T09:30:00+00:00",  # +18 min
                "2026-02-22T09:45:00+00:00",  # +15 min
                # 1h lunch break (idle)
                "2026-02-22T10:45:00+00:00",  # +60 min (idle)
                "2026-02-22T10:50:00+00:00",  # +5 min
                "2026-02-22T11:00:00+00:00",  # +10 min
            ])
            hours = calculate_active_time("sess-1")
            # Active: 5+7+18+15+5+10 = 60 min = 1.0 hour
            assert abs(hours - 1.0) < 0.001


# ---------------------------------------------------------------------------
# query_time_by_domain
# ---------------------------------------------------------------------------


class TestQueryTimeByDomain:
    def test_empty_no_sessions(self):
        """No sessions returns empty domains."""
        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = []
            with patch("jaybrain.time_allocation.ensure_data_dirs"):
                result = query_time_by_domain()
            assert result["total_hours"] == 0.0
            assert result["sessions_analyzed"] == 0

    def test_groups_by_domain(self):
        """Sessions are grouped by CWD domain."""
        sessions = [
            {"session_id": "s1", "cwd": "C:\\Users\\Joshua\\jaybrain"},
            {"session_id": "s2", "cwd": "C:\\Users\\Joshua\\projects\\homelab"},
        ]

        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = sessions

            # Mock calculate_active_time to return known values
            with patch("jaybrain.time_allocation.calculate_active_time") as mock_calc:
                mock_calc.side_effect = [2.5, 1.0]  # jaybrain=2.5h, homelab=1.0h
                with patch("jaybrain.time_allocation.ensure_data_dirs"):
                    result = query_time_by_domain()

        assert result["domains"]["JayBrain Development"] == 2.5
        assert result["domains"]["Learning"] == 1.0
        assert result["total_hours"] == 3.5
        assert result["sessions_analyzed"] == 2


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------


class TestWeeklyReport:
    def test_on_track(self):
        """Domain at 80% of target is on_track."""
        time_data = {
            "domains": {"Career": 16.0},
            "total_hours": 16.0,
            "sessions_analyzed": 5,
            "period_start": "2026-02-15",
            "period_end": "2026-02-22",
        }
        targets = {"Career": 20.0}

        with patch("jaybrain.time_allocation.query_time_by_domain", return_value=time_data):
            with patch("jaybrain.time_allocation._get_domain_targets", return_value=targets):
                report = get_weekly_report(days_back=7)

        career = next(d for d in report["domains"] if d["name"] == "Career")
        assert career["status"] == "on_track"
        assert career["pct"] == 80.0

    def test_under_target(self):
        """Domain at 30% of target is under."""
        time_data = {
            "domains": {"Learning": 4.5},
            "total_hours": 4.5,
            "sessions_analyzed": 2,
            "period_start": "2026-02-15",
            "period_end": "2026-02-22",
        }
        targets = {"Learning": 15.0}

        with patch("jaybrain.time_allocation.query_time_by_domain", return_value=time_data):
            with patch("jaybrain.time_allocation._get_domain_targets", return_value=targets):
                report = get_weekly_report(days_back=7)

        learning = next(d for d in report["domains"] if d["name"] == "Learning")
        assert learning["status"] == "under"

    def test_over_target(self):
        """Domain at 200% of target is over."""
        time_data = {
            "domains": {"JayBrain Development": 15.0},
            "total_hours": 15.0,
            "sessions_analyzed": 8,
            "period_start": "2026-02-15",
            "period_end": "2026-02-22",
        }
        targets = {"JayBrain Development": 7.5}

        with patch("jaybrain.time_allocation.query_time_by_domain", return_value=time_data):
            with patch("jaybrain.time_allocation._get_domain_targets", return_value=targets):
                report = get_weekly_report(days_back=7)

        jb = next(d for d in report["domains"] if d["name"] == "JayBrain Development")
        assert jb["status"] == "over"
        assert jb["pct"] == 200.0

    def test_no_target_domain(self):
        """Domain with no target shows no_target status."""
        time_data = {
            "domains": {"Uncategorized": 1.0},
            "total_hours": 1.0,
            "sessions_analyzed": 1,
            "period_start": "2026-02-15",
            "period_end": "2026-02-22",
        }
        targets = {}

        with patch("jaybrain.time_allocation.query_time_by_domain", return_value=time_data):
            with patch("jaybrain.time_allocation._get_domain_targets", return_value=targets):
                report = get_weekly_report(days_back=7)

        uncat = next(d for d in report["domains"] if d["name"] == "Uncategorized")
        assert uncat["status"] == "no_target"

    def test_scales_targets_for_non_weekly(self):
        """14-day lookback doubles the target hours."""
        time_data = {
            "domains": {"Career": 40.0},
            "total_hours": 40.0,
            "sessions_analyzed": 10,
            "period_start": "2026-02-08",
            "period_end": "2026-02-22",
        }
        targets = {"Career": 20.0}

        with patch("jaybrain.time_allocation.query_time_by_domain", return_value=time_data):
            with patch("jaybrain.time_allocation._get_domain_targets", return_value=targets):
                report = get_weekly_report(days_back=14)

        career = next(d for d in report["domains"] if d["name"] == "Career")
        assert career["target_hours"] == 40.0  # 20 * 14/7 = 40
        assert career["status"] == "on_track"

    def test_includes_untracked_target_domains(self):
        """Domains with targets but zero actual hours still appear."""
        time_data = {
            "domains": {},
            "total_hours": 0.0,
            "sessions_analyzed": 0,
            "period_start": "2026-02-15",
            "period_end": "2026-02-22",
        }
        targets = {"Career": 20.0, "Learning": 15.0}

        with patch("jaybrain.time_allocation.query_time_by_domain", return_value=time_data):
            with patch("jaybrain.time_allocation._get_domain_targets", return_value=targets):
                report = get_weekly_report(days_back=7)

        names = {d["name"] for d in report["domains"]}
        assert "Career" in names
        assert "Learning" in names


# ---------------------------------------------------------------------------
# Daily breakdown
# ---------------------------------------------------------------------------


class TestDailyBreakdown:
    def test_groups_by_day(self):
        """Sessions on different days appear in separate entries."""
        sessions = [
            {"session_id": "s1", "cwd": "C:\\Users\\Joshua\\jaybrain", "started_at": "2026-02-20T10:00:00+00:00"},
            {"session_id": "s2", "cwd": "C:\\Users\\Joshua\\jaybrain", "started_at": "2026-02-21T14:00:00+00:00"},
        ]

        with patch("jaybrain.time_allocation.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = sessions

            with patch("jaybrain.time_allocation.calculate_active_time") as mock_calc:
                mock_calc.side_effect = [3.0, 2.0]
                with patch("jaybrain.time_allocation.ensure_data_dirs"):
                    result = get_daily_breakdown(days_back=7)

        assert len(result) == 2
        assert result[0]["date"] == "2026-02-20"
        assert result[1]["date"] == "2026-02-21"


# ---------------------------------------------------------------------------
# Heartbeat check
# ---------------------------------------------------------------------------


class TestCheckTimeAllocation:
    def test_no_alerts(self):
        """All on_track = no notification."""
        report = {
            "domains": [
                {"name": "Career", "actual_hours": 18.0, "target_hours": 20.0, "pct": 90.0, "status": "on_track"},
            ],
            "total_actual": 18.0,
            "total_target": 20.0,
            "period_days": 7,
            "sessions_analyzed": 5,
        }

        with patch("jaybrain.time_allocation.get_weekly_report", return_value=report):
            result = check_time_allocation()

        assert result["triggered"] is False

    def test_under_triggers_notification(self):
        """Under-target domain triggers Telegram notification."""
        report = {
            "domains": [
                {"name": "Learning", "actual_hours": 3.0, "target_hours": 15.0, "pct": 20.0, "status": "under"},
            ],
            "total_actual": 3.0,
            "total_target": 15.0,
            "period_days": 7,
            "sessions_analyzed": 1,
        }

        with patch("jaybrain.time_allocation.get_weekly_report", return_value=report):
            with patch("jaybrain.heartbeat.dispatch_notification") as mock_dispatch:
                result = check_time_allocation()

        assert result["triggered"] is True
        assert "Learning" in result["message"]
        mock_dispatch.assert_called_once()
