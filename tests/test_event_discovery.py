"""Tests for the event discovery module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from jaybrain.config import ensure_data_dirs
from jaybrain.db import get_connection, init_db, now_iso


def _setup_db():
    ensure_data_dirs()
    init_db()


class TestScoreRelevance:
    def test_highly_relevant_event(self, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import _score_relevance

        score = _score_relevance(
            "BSides Charlotte Cybersecurity Conference",
            "SOC analyst workshop, threat detection, SIEM tools, incident response training"
        )
        assert score > 0.5

    def test_irrelevant_event(self, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import _score_relevance

        score = _score_relevance(
            "Cooking Class for Beginners",
            "Learn to make pasta from scratch in this fun weekend workshop"
        )
        assert score < 0.1

    def test_moderately_relevant(self, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import _score_relevance

        score = _score_relevance(
            "Charlotte Tech Networking Mixer",
            "Meet local tech professionals, career networking event"
        )
        assert 0.0 < score < 0.8


class TestFilterRelevantEvents:
    def test_filters_and_sorts(self, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import filter_relevant_events

        events = [
            {"title": "BSides Charlotte", "description": "Cybersecurity conference"},
            {"title": "Cooking Class", "description": "Learn to cook pasta"},
            {"title": "SOC Workshop", "description": "SIEM and incident response training"},
        ]

        result = filter_relevant_events(events, min_relevance=0.1)
        # Only cyber-relevant events should remain
        assert all("Cooking" not in e["title"] for e in result)
        # Should be sorted by relevance
        if len(result) >= 2:
            assert result[0]["relevance_score"] >= result[1]["relevance_score"]

    def test_deduplicates(self, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import filter_relevant_events

        events = [
            {"title": "Security Conference", "description": "cybersecurity"},
            {"title": "Security Conference", "description": "cybersecurity"},
        ]

        result = filter_relevant_events(events)
        assert len(result) <= 1


class TestSaveEvents:
    def test_save_new_events(self, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import _save_events

        events = [
            {
                "title": "BSides Charlotte 2026",
                "description": "Annual cybersecurity conference",
                "url": "https://bsidesclt.com",
                "event_date": "2026-06-15T09:00:00Z",
                "location": "Charlotte, NC",
                "source": "eventbrite",
                "relevance_score": 0.85,
            },
        ]

        saved = _save_events(events)
        assert saved == 1

        # Verify in DB
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM discovered_events WHERE title = ?",
                ("BSides Charlotte 2026",),
            ).fetchone()
            assert row is not None
            assert row["relevance_score"] == 0.85
        finally:
            conn.close()

    def test_dedup_on_save(self, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import _save_events

        events = [
            {"title": "Test Event", "description": "", "url": "", "event_date": "",
             "location": "", "source": "test", "relevance_score": 0.5},
        ]

        _save_events(events)
        saved = _save_events(events)  # Second save
        assert saved == 0  # No new events


class TestListEvents:
    def test_list_empty(self, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import list_events

        result = list_events()
        assert result["count"] == 0
        assert result["events"] == []

    def test_list_with_events(self, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import _save_events, list_events

        _save_events([
            {"title": "Event A", "description": "desc", "url": "", "event_date": "",
             "location": "", "source": "test", "relevance_score": 0.5},
            {"title": "Event B", "description": "desc", "url": "", "event_date": "",
             "location": "", "source": "test", "relevance_score": 0.8},
        ])

        result = list_events(status="new")
        assert result["count"] == 2


class TestRunEventDiscovery:
    @patch("jaybrain.event_discovery.discover_eventbrite", return_value=[])
    @patch("jaybrain.event_discovery.discover_web_events", return_value=[])
    def test_run_with_no_results(self, mock_web, mock_eb, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import run_event_discovery

        result = run_event_discovery()
        assert result["total_discovered"] == 0
        assert result["relevant"] == 0
        assert result["new_saved"] == 0

    @patch("jaybrain.event_discovery.discover_web_events", return_value=[])
    @patch("jaybrain.event_discovery.discover_eventbrite")
    def test_run_with_results(self, mock_eb, mock_web, temp_data_dir):
        _setup_db()
        from jaybrain.event_discovery import run_event_discovery

        mock_eb.return_value = [
            {"title": "Cyber Conference", "description": "cybersecurity event",
             "url": "https://example.com", "event_date": "2026-06-01",
             "location": "Charlotte, NC", "source": "eventbrite"},
        ]

        with patch("jaybrain.telegram.send_telegram_message", return_value={"status": "sent"}):
            result = run_event_discovery()

        assert result["total_discovered"] == 1
