"""Tests for the network_decay module."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from jaybrain.network_decay import (
    add_contact,
    log_interaction,
    get_stale_contacts,
    get_network_health,
    check_network_decay,
)


# ---------------------------------------------------------------------------
# add_contact
# ---------------------------------------------------------------------------


class TestAddContact:
    def test_creates_person_entity(self):
        """add_contact calls graph.add_entity with correct args."""
        with patch("jaybrain.graph.add_entity") as mock_add:
            mock_add.return_value = {"status": "created", "entity": {"name": "Alice"}}
            result = add_contact(
                name="Alice",
                contact_type="professional",
                company="Acme Corp",
                role="Engineer",
                how_met="Tech meetup",
                decay_threshold_days=14,
            )

        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args
        assert call_kwargs[1]["name"] == "Alice"
        assert call_kwargs[1]["entity_type"] == "person"
        props = call_kwargs[1]["properties"]
        assert props["company"] == "Acme Corp"
        assert props["role"] == "Engineer"
        assert props["how_met"] == "Tech meetup"
        assert props["decay_threshold_days"] == 14
        assert props["contact_count"] == 0
        assert "last_contact" in props
        assert result["status"] == "created"

    def test_default_threshold(self):
        """Default decay threshold is 30 days."""
        with patch("jaybrain.graph.add_entity") as mock_add:
            mock_add.return_value = {"status": "created", "entity": {"name": "Bob"}}
            add_contact(name="Bob")

        props = mock_add.call_args[1]["properties"]
        assert props["decay_threshold_days"] == 30

    def test_description_from_role_and_company(self):
        """Description is built from role + company."""
        with patch("jaybrain.graph.add_entity") as mock_add:
            mock_add.return_value = {"status": "created", "entity": {"name": "Carol"}}
            add_contact(name="Carol", role="CTO", company="TechCo")

        assert mock_add.call_args[1]["description"] == "CTO at TechCo"

    def test_description_company_only(self):
        """Description with company only."""
        with patch("jaybrain.graph.add_entity") as mock_add:
            mock_add.return_value = {"status": "created", "entity": {"name": "Dave"}}
            add_contact(name="Dave", company="BigCo")

        assert mock_add.call_args[1]["description"] == "BigCo"

    def test_description_empty(self):
        """No role or company = empty description."""
        with patch("jaybrain.graph.add_entity") as mock_add:
            mock_add.return_value = {"status": "created", "entity": {"name": "Eve"}}
            add_contact(name="Eve")

        assert mock_add.call_args[1]["description"] == ""


# ---------------------------------------------------------------------------
# log_interaction
# ---------------------------------------------------------------------------


class TestLogInteraction:
    def test_updates_last_contact(self):
        """log_interaction updates last_contact and increments count."""
        mock_contact = {
            "name": "Alice",
            "entity_type": "person",
            "properties": {"contact_count": 3, "last_contact": "2026-01-01T00:00:00+00:00"},
        }
        with patch("jaybrain.graph.search_entities", return_value=[mock_contact]):
            with patch("jaybrain.graph.add_entity") as mock_add:
                mock_add.return_value = {"status": "updated", "entity": {"name": "Alice"}}
                result = log_interaction("Alice", note="Discussed project")

        props = mock_add.call_args[1]["properties"]
        assert props["contact_count"] == 4
        assert props["last_note"] == "Discussed project"
        assert "last_contact" in props

    def test_no_match_returns_error(self):
        """No matching contact returns error."""
        with patch("jaybrain.graph.search_entities", return_value=[]):
            result = log_interaction("Nobody")

        assert "error" in result

    def test_prefers_exact_match(self):
        """Prefers exact name match over partial."""
        contacts = [
            {"name": "Alice Smith", "entity_type": "person", "properties": {"contact_count": 1}},
            {"name": "Alice", "entity_type": "person", "properties": {"contact_count": 5}},
        ]
        with patch("jaybrain.graph.search_entities", return_value=contacts):
            with patch("jaybrain.graph.add_entity") as mock_add:
                mock_add.return_value = {"status": "updated", "entity": {"name": "Alice"}}
                log_interaction("Alice")

        assert mock_add.call_args[1]["name"] == "Alice"

    def test_falls_back_to_first_match(self):
        """Falls back to first match when no exact match."""
        contacts = [
            {"name": "Alice Smith", "entity_type": "person", "properties": {"contact_count": 1}},
            {"name": "Alice Jones", "entity_type": "person", "properties": {"contact_count": 2}},
        ]
        with patch("jaybrain.graph.search_entities", return_value=contacts):
            with patch("jaybrain.graph.add_entity") as mock_add:
                mock_add.return_value = {"status": "updated", "entity": {"name": "Alice Smith"}}
                log_interaction("Alice")

        assert mock_add.call_args[1]["name"] == "Alice Smith"

    def test_no_note_no_last_note_key(self):
        """Without a note, last_note is not set in properties."""
        mock_contact = {
            "name": "Bob",
            "entity_type": "person",
            "properties": {"contact_count": 0},
        }
        with patch("jaybrain.graph.search_entities", return_value=[mock_contact]):
            with patch("jaybrain.graph.add_entity") as mock_add:
                mock_add.return_value = {"status": "updated", "entity": {"name": "Bob"}}
                log_interaction("Bob")

        props = mock_add.call_args[1]["properties"]
        assert "last_note" not in props


# ---------------------------------------------------------------------------
# get_stale_contacts
# ---------------------------------------------------------------------------


def _make_person_row(name, props_dict):
    """Build a mock DB row for a person entity."""
    return {
        "id": f"id-{name.lower().replace(' ', '-')}",
        "name": name,
        "entity_type": "person",
        "description": "",
        "aliases": "[]",
        "memory_ids": "[]",
        "properties": json.dumps(props_dict),
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


class TestGetStaleContacts:
    def test_empty_no_contacts(self):
        """No person entities = empty list."""
        with patch("jaybrain.network_decay.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = []
            result = get_stale_contacts()

        assert result == []

    def test_skips_contacts_without_last_contact(self):
        """Contacts without last_contact property are skipped."""
        rows = [_make_person_row("NoContact", {"company": "Test"})]
        with patch("jaybrain.network_decay.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = rows
            result = get_stale_contacts()

        assert result == []

    def test_calculates_overdue(self):
        """Correctly calculates days since contact and overdue_by."""
        forty_days_ago = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        rows = [_make_person_row("Alice", {
            "last_contact": forty_days_ago,
            "decay_threshold_days": 30,
            "company": "Acme",
        })]

        with patch("jaybrain.network_decay.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = rows
            result = get_stale_contacts()

        assert len(result) == 1
        assert result[0]["name"] == "Alice"
        assert result[0]["days_since_contact"] == 40
        assert result[0]["overdue_by"] == 10

    def test_healthy_contact_negative_overdue(self):
        """Recently contacted person has negative overdue_by."""
        two_days_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        rows = [_make_person_row("Bob", {
            "last_contact": two_days_ago,
            "decay_threshold_days": 30,
        })]

        with patch("jaybrain.network_decay.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = rows
            result = get_stale_contacts()

        assert len(result) == 1
        assert result[0]["overdue_by"] == -28

    def test_sorted_most_overdue_first(self):
        """Contacts are sorted by overdue_by descending."""
        now = datetime.now(timezone.utc)
        rows = [
            _make_person_row("Recent", {
                "last_contact": (now - timedelta(days=5)).isoformat(),
                "decay_threshold_days": 30,
            }),
            _make_person_row("Stale", {
                "last_contact": (now - timedelta(days=60)).isoformat(),
                "decay_threshold_days": 30,
            }),
            _make_person_row("Medium", {
                "last_contact": (now - timedelta(days=35)).isoformat(),
                "decay_threshold_days": 30,
            }),
        ]

        with patch("jaybrain.network_decay.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = rows
            result = get_stale_contacts()

        assert result[0]["name"] == "Stale"
        assert result[1]["name"] == "Medium"
        assert result[2]["name"] == "Recent"

    def test_threshold_override(self):
        """threshold_override overrides per-contact threshold."""
        twenty_days_ago = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        rows = [_make_person_row("Alice", {
            "last_contact": twenty_days_ago,
            "decay_threshold_days": 30,  # normally not overdue
        })]

        with patch("jaybrain.network_decay.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = rows
            result = get_stale_contacts(threshold_override=15)

        assert result[0]["overdue_by"] == 5  # 20 - 15 = 5 days overdue

    def test_uses_default_threshold_when_missing(self):
        """Uses NETWORK_DECAY_DEFAULT_DAYS when entity has no threshold."""
        thirty_five_days_ago = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
        rows = [_make_person_row("NoThreshold", {
            "last_contact": thirty_five_days_ago,
            # no decay_threshold_days in properties
        })]

        with patch("jaybrain.network_decay.get_connection") as mock_conn:
            conn = MagicMock()
            mock_conn.return_value = conn
            conn.execute.return_value.fetchall.return_value = rows
            result = get_stale_contacts()

        # Default is 30, 35 - 30 = 5 days overdue
        assert result[0]["overdue_by"] == 5


# ---------------------------------------------------------------------------
# get_network_health
# ---------------------------------------------------------------------------


class TestGetNetworkHealth:
    def test_empty_network(self):
        """No contacts = all zeros."""
        with patch("jaybrain.network_decay.get_stale_contacts", return_value=[]):
            result = get_network_health()

        assert result["total_contacts"] == 0
        assert result["healthy_count"] == 0
        assert result["stale_count"] == 0
        assert "most_neglected" not in result

    def test_mixed_health(self):
        """Mix of healthy and stale contacts."""
        contacts = [
            {"name": "Stale", "overdue_by": 10, "company": "A"},
            {"name": "Healthy", "overdue_by": -5, "company": "B"},
            {"name": "Also Stale", "overdue_by": 3, "company": "C"},
        ]
        with patch("jaybrain.network_decay.get_stale_contacts", return_value=contacts):
            result = get_network_health()

        assert result["total_contacts"] == 3
        assert result["healthy_count"] == 1
        assert result["stale_count"] == 2
        assert result["most_neglected"]["name"] == "Stale"

    def test_all_healthy(self):
        """All contacts healthy = no most_neglected."""
        contacts = [
            {"name": "A", "overdue_by": -10, "company": "X"},
            {"name": "B", "overdue_by": -20, "company": "Y"},
        ]
        with patch("jaybrain.network_decay.get_stale_contacts", return_value=contacts):
            result = get_network_health()

        assert result["stale_count"] == 0
        assert "most_neglected" not in result


# ---------------------------------------------------------------------------
# check_network_decay (heartbeat)
# ---------------------------------------------------------------------------


class TestCheckNetworkDecay:
    def test_no_stale_contacts(self):
        """No overdue contacts = not triggered."""
        contacts = [
            {"name": "A", "overdue_by": -10, "company": "X"},
        ]
        with patch("jaybrain.network_decay.get_stale_contacts", return_value=contacts):
            with patch("jaybrain.heartbeat._log_check") as mock_log:
                result = check_network_decay()

        assert result["triggered"] is False
        assert result["stale_count"] == 0
        mock_log.assert_called_once()

    def test_stale_triggers_notification(self):
        """Overdue contacts trigger dispatch_notification."""
        contacts = [
            {"name": "Alice", "overdue_by": 15, "company": "Acme"},
            {"name": "Bob", "overdue_by": 5, "company": ""},
            {"name": "Healthy", "overdue_by": -10, "company": "Good"},
        ]
        with patch("jaybrain.network_decay.get_stale_contacts", return_value=contacts):
            with patch("jaybrain.heartbeat.dispatch_notification") as mock_dispatch:
                result = check_network_decay()

        assert result["triggered"] is True
        assert result["stale_count"] == 2
        assert "Alice" in result["message"]
        assert "Bob" in result["message"]
        mock_dispatch.assert_called_once()

    def test_message_format(self):
        """Message includes contact names and overdue days."""
        contacts = [
            {"name": "John", "overdue_by": 20, "company": "BigCo"},
        ]
        with patch("jaybrain.network_decay.get_stale_contacts", return_value=contacts):
            with patch("jaybrain.heartbeat.dispatch_notification"):
                result = check_network_decay()

        assert "1 contact(s) need attention:" in result["message"]
        assert "John (BigCo) -- 20 days overdue" in result["message"]

    def test_caps_at_five_in_message(self):
        """Message shows at most 5 contacts plus a '...and N more' line."""
        contacts = [
            {"name": f"Person{i}", "overdue_by": 30 - i, "company": ""}
            for i in range(8)
        ]
        with patch("jaybrain.network_decay.get_stale_contacts", return_value=contacts):
            with patch("jaybrain.heartbeat.dispatch_notification"):
                result = check_network_decay()

        assert result["stale_count"] == 8
        assert "...and 3 more" in result["message"]

    def test_handles_error_gracefully(self):
        """Errors are caught and returned."""
        with patch("jaybrain.network_decay.get_stale_contacts", side_effect=Exception("DB error")):
            result = check_network_decay()

        assert "error" in result
