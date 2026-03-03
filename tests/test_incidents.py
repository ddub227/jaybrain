"""Tests for the incident tracking system."""

import json
import pytest

from jaybrain.db import init_db
from jaybrain.incidents import (
    log_incident,
    search_incidents,
    get_incident_detail,
    modify_incident,
    track_action_item,
    get_open_action_items,
    get_action_items_by_incident,
    compute_metrics,
)


@pytest.fixture(autouse=True)
def setup_db(temp_data_dir):
    init_db()


class TestLogIncident:
    def test_basic_log(self):
        result = log_incident(title="Test incident", summary="Something broke")
        assert result["incident"]["title"] == "Test incident"
        assert result["incident"]["summary"] == "Something broke"
        assert result["incident"]["severity"] == "medium"
        assert result["incident"]["status"] == "open"
        assert result["incident"]["incident_type"] == "hit"
        assert result["action_item_ids"] == []
        assert result["lesson_ids"] == []

    def test_log_with_action_items(self):
        result = log_incident(
            title="Bug found",
            summary="Critical bug in auth",
            severity="high",
            action_items=[
                {"description": "Add input validation", "item_type": "prevent"},
                {"description": "Add monitoring alert", "item_type": "detect"},
            ],
        )
        assert len(result["action_item_ids"]) == 2

    def test_log_with_lessons(self):
        result = log_incident(
            title="Near miss",
            summary="Almost deployed bad config",
            incident_type="near_miss",
            lessons=[
                {"description": "Config review saved us", "lesson_type": "went_well"},
                {"description": "No automated check", "lesson_type": "went_wrong"},
            ],
        )
        assert len(result["lesson_ids"]) == 2

    def test_log_with_all_fields(self):
        result = log_incident(
            title="Full incident",
            summary="Everything broke",
            date="2026-03-01",
            severity="critical",
            incident_type="hit",
            error_type="architecture_gap",
            root_cause="Missing retry logic",
            impact="Service down for 30 min",
            detection_method="automated",
            time_to_detect=5,
            time_to_resolve=30,
            tags=["outage", "retry"],
            recurrence_of="abc123",
            fix_applied="Added exponential backoff",
            action_items=[
                {"description": "Add circuit breaker", "item_type": "mitigate"},
            ],
            lessons=[
                {"description": "Monitoring caught it fast", "lesson_type": "went_well"},
            ],
        )
        inc = result["incident"]
        assert inc["date"] == "2026-03-01"
        assert inc["severity"] == "critical"
        assert inc["error_type"] == "architecture_gap"
        assert inc["root_cause"] == "Missing retry logic"
        assert inc["impact"] == "Service down for 30 min"
        assert inc["detection_method"] == "automated"
        assert inc["time_to_detect"] == 5
        assert inc["time_to_resolve"] == 30
        assert inc["tags"] == ["outage", "retry"]
        assert inc["recurrence_of"] == "abc123"
        assert inc["fix_applied"] == "Added exponential backoff"
        assert len(result["action_item_ids"]) == 1
        assert len(result["lesson_ids"]) == 1

    def test_invalid_severity_raises(self):
        with pytest.raises(ValueError):
            log_incident(title="Bad", summary="Bad", severity="extreme")

    def test_invalid_error_type_raises(self):
        with pytest.raises(ValueError):
            log_incident(title="Bad", summary="Bad", error_type="typo")


class TestSearchIncidents:
    def test_search_by_query(self):
        log_incident(title="Auth token expired", summary="Token rotation failed")
        log_incident(title="DB migration error", summary="Column mismatch")
        results = search_incidents(query="token")
        assert len(results) == 1
        assert results[0]["title"] == "Auth token expired"

    def test_search_by_severity(self):
        log_incident(title="Minor issue", summary="Small", severity="low")
        log_incident(title="Major issue", summary="Big", severity="critical")
        results = search_incidents(severity="critical")
        assert len(results) == 1
        assert results[0]["title"] == "Major issue"

    def test_search_by_tag(self):
        log_incident(title="Tagged", summary="Has tag", tags=["auth", "security"])
        log_incident(title="Untagged", summary="No relevant tag", tags=["db"])
        results = search_incidents(tag="auth")
        assert len(results) == 1
        assert results[0]["title"] == "Tagged"

    def test_search_empty_results(self):
        results = search_incidents(query="nonexistent_term_xyz")
        assert results == []

    def test_search_no_filters_returns_all(self):
        log_incident(title="One", summary="First")
        log_incident(title="Two", summary="Second")
        results = search_incidents()
        assert len(results) == 2

    def test_search_by_date_range(self):
        log_incident(title="Old", summary="Old one", date="2025-01-01")
        log_incident(title="New", summary="New one", date="2026-03-01")
        results = search_incidents(date_from="2026-01-01")
        assert len(results) == 1
        assert results[0]["title"] == "New"

    def test_search_by_error_type(self):
        log_incident(title="Bug", summary="Code bug", error_type="code_bug")
        log_incident(title="Gap", summary="Arch gap", error_type="architecture_gap")
        results = search_incidents(error_type="code_bug")
        assert len(results) == 1
        assert results[0]["title"] == "Bug"


class TestIncidentDetail:
    def test_full_detail(self):
        result = log_incident(
            title="Detail test",
            summary="Full detail",
            action_items=[{"description": "Fix it", "item_type": "prevent"}],
            lessons=[{"description": "Should have tested", "lesson_type": "went_wrong"}],
        )
        detail = get_incident_detail(result["incident"]["id"])
        assert detail is not None
        assert detail["incident"]["title"] == "Detail test"
        assert len(detail["action_items"]) == 1
        assert detail["action_items"][0]["description"] == "Fix it"
        assert len(detail["lessons"]) == 1
        assert detail["lessons"][0]["description"] == "Should have tested"

    def test_not_found(self):
        assert get_incident_detail("nonexistent") is None


class TestActionItemTrack:
    def test_mark_done(self):
        result = log_incident(
            title="AI test",
            summary="Test action items",
            action_items=[{"description": "Do the thing", "item_type": "prevent"}],
        )
        ai_id = result["action_item_ids"][0]
        updated = track_action_item(ai_id, "done")
        assert updated is not None
        assert updated["status"] == "done"
        assert updated["completed_at"] is not None

    def test_mark_in_progress(self):
        result = log_incident(
            title="Progress test",
            summary="Test",
            action_items=[{"description": "Working on it", "item_type": "detect"}],
        )
        ai_id = result["action_item_ids"][0]
        updated = track_action_item(ai_id, "in_progress")
        assert updated["status"] == "in_progress"
        assert updated["completed_at"] is None

    def test_list_open(self):
        log_incident(
            title="Open items test",
            summary="Has open items",
            action_items=[
                {"description": "Open one", "item_type": "prevent"},
                {"description": "Open two", "item_type": "detect"},
            ],
        )
        open_items = get_open_action_items()
        assert len(open_items) == 2
        assert all(item["status"] == "todo" for item in open_items)

    def test_done_items_not_in_open(self):
        result = log_incident(
            title="Done test",
            summary="Test",
            action_items=[{"description": "Will be done", "item_type": "prevent"}],
        )
        ai_id = result["action_item_ids"][0]
        track_action_item(ai_id, "done")
        open_items = get_open_action_items()
        assert len(open_items) == 0

    def test_not_found(self):
        result = track_action_item("nonexistent", "done")
        assert result is None

    def test_list_by_incident(self):
        result = log_incident(
            title="By incident",
            summary="Test",
            action_items=[
                {"description": "Item A", "item_type": "prevent"},
                {"description": "Item B", "item_type": "detect"},
            ],
        )
        items = get_action_items_by_incident(result["incident"]["id"])
        assert len(items) == 2


class TestMetrics:
    def test_empty_db(self):
        metrics = compute_metrics()
        assert metrics["total"] == 0
        assert metrics["by_severity"] == {}
        assert metrics["action_item_completion_rate"] == 0.0
        assert metrics["recent"] == []

    def test_populated(self):
        log_incident(
            title="Sev high",
            summary="High severity",
            severity="high",
            error_type="code_bug",
            time_to_detect=10,
            time_to_resolve=60,
            tags=["auth", "bug"],
            action_items=[{"description": "Fix", "item_type": "prevent"}],
        )
        log_incident(
            title="Sev low",
            summary="Low severity",
            severity="low",
            error_type="process_gap",
            tags=["process", "auth"],
        )
        # Recurrence
        log_incident(
            title="Again",
            summary="Happened again",
            severity="high",
            recurrence_of="original123",
            tags=["bug"],
        )

        metrics = compute_metrics()
        assert metrics["total"] == 3
        assert metrics["by_severity"]["high"] == 2
        assert metrics["by_severity"]["low"] == 1
        assert metrics["by_error_type"]["code_bug"] == 1
        assert metrics["by_error_type"]["process_gap"] == 1
        assert metrics["recurrence_count"] == 1
        assert metrics["recurrence_rate"] == round(1 / 3, 3)
        assert metrics["avg_time_to_detect"] == 10.0
        assert metrics["avg_time_to_resolve"] == 60.0
        assert metrics["action_item_total"] == 1
        assert metrics["action_item_done"] == 0
        assert metrics["action_item_completion_rate"] == 0.0
        assert len(metrics["top_tags"]) > 0
        # "auth" appears in 2 incidents
        auth_tag = next(t for t in metrics["top_tags"] if t["tag"] == "auth")
        assert auth_tag["count"] == 2
        assert len(metrics["recent"]) == 3


class TestModifyIncident:
    def test_resolve(self):
        result = log_incident(title="To resolve", summary="Will be resolved")
        inc_id = result["incident"]["id"]
        updated = modify_incident(inc_id, status="resolved", fix_applied="Patched it")
        assert updated["status"] == "resolved"
        assert updated["fix_applied"] == "Patched it"

    def test_modify_nonexistent(self):
        result = modify_incident("nonexistent", status="closed")
        assert result is None

    def test_update_root_cause(self):
        result = log_incident(title="No RCA yet", summary="Needs RCA")
        inc_id = result["incident"]["id"]
        updated = modify_incident(inc_id, root_cause="Race condition in auth flow")
        assert updated["root_cause"] == "Race condition in auth flow"

    def test_update_tags(self):
        result = log_incident(title="Tag update", summary="Test", tags=["old"])
        inc_id = result["incident"]["id"]
        updated = modify_incident(inc_id, tags=["new", "updated"])
        assert updated["tags"] == ["new", "updated"]
