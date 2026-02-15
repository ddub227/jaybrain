"""Tests for the homelab domain (file-based journal, tools, reference docs)."""

import csv
from pathlib import Path

import pytest

from jaybrain import config
from jaybrain.homelab import (
    add_tool,
    create_journal_entry,
    get_status,
    list_journal_entries,
    list_tools,
    read_codex,
    read_nexus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_INDEX = """\
# JJ Budd's Learn Out Loud Lab - Journal Index

## Quick Stats

| Metric | Value |
|--------|-------|
| **Total Lab Sessions** | 6 |
| **Latest Entry** | 2025-12-20 |
| **Active VMs** | 3 |

---

## Skills Progression

### Mastered
- [x] VirtualBox networking (Host-Only, NAT)
- [x] Active Directory basic setup

### In Progress
- [ ] Splunk SPL queries
- [ ] Windows Event Log analysis

### Planned
- [ ] Wireshark packet analysis
- [ ] Sysmon deployment

---

## SOC Analyst Readiness Checklist

- [x] Set up SIEM (Splunk)
- [ ] Create detection rules
- [x] Practice log analysis
- [ ] Build incident response playbook

---

## Journal Entries

### 2025-12
| Date | Title | Focus |
|------|-------|-------|
| [[JJ Budd's Learn Out Loud Lab_2025-12-20|2025-12-20]] | AD Forest Setup | Active Directory |
| [[JJ Budd's Learn Out Loud Lab_2025-12-15|2025-12-15]] | Splunk Onboarding | SIEM |

### 2025-11
| Date | Title | Focus |
|------|-------|-------|
| [[JJ Budd's Learn Out Loud Lab_2025-11-30|2025-11-30]] | Network Config | Networking |

---

*Last Updated: 2025-12-20*
"""

SAMPLE_CSV = """\
Tool,Creator,Purpose,Status
Splunk,Splunk Inc.,SIEM platform,Deployed
CrackMapExec,byt3bl33d3r,AD enumeration,Deployed
Nmap,Gordon Lyon,Network scanning,Planned
"""

SAMPLE_JOURNAL_CONTENT = """\
# JJ Budd's Learn Out Loud Lab - 2026-01-10

| Field | Value |
|-------|-------|
| **Date** | 2026-01-10 |
| **Focus** | Sysmon Deployment |
| **Duration** | 2 hours |

## Objective
Deploy Sysmon across all lab endpoints.

## Key Findings
- Sysmon captures process creation events
- SwiftOnSecurity config is the gold standard
"""


@pytest.fixture
def homelab_dirs():
    """Create the homelab directory structure under the monkeypatched paths."""
    config.HOMELAB_ROOT.mkdir(parents=True, exist_ok=True)
    config.HOMELAB_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    config.HOMELAB_JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    return config.HOMELAB_ROOT


@pytest.fixture
def journal_index(homelab_dirs):
    """Write a sample JOURNAL_INDEX.md."""
    config.HOMELAB_JOURNAL_INDEX.write_text(SAMPLE_INDEX, encoding="utf-8")
    return config.HOMELAB_JOURNAL_INDEX


@pytest.fixture
def tools_csv(homelab_dirs):
    """Write a sample HOMELAB_TOOLS_INVENTORY.csv."""
    config.HOMELAB_TOOLS_CSV.write_text(SAMPLE_CSV, encoding="utf-8")
    return config.HOMELAB_TOOLS_CSV


# ---------------------------------------------------------------------------
# TestHomelabStatus
# ---------------------------------------------------------------------------

class TestHomelabStatus:
    def test_parses_quick_stats(self, journal_index):
        result = get_status()
        assert result["quick_stats"]["Total Lab Sessions"] == "6"
        assert result["quick_stats"]["Latest Entry"] == "2025-12-20"
        assert result["quick_stats"]["Active VMs"] == "3"

    def test_parses_skills(self, journal_index):
        result = get_status()
        assert "VirtualBox networking (Host-Only, NAT)" in result["skills"]["mastered"]
        assert "Splunk SPL queries" in result["skills"]["in_progress"]
        assert "Wireshark packet analysis" in result["skills"]["planned"]

    def test_parses_soc_readiness(self, journal_index):
        result = get_status()
        assert result["soc_readiness"]["completed"] == 2
        assert result["soc_readiness"]["total"] == 4

    def test_parses_recent_entries(self, journal_index):
        result = get_status()
        assert result["total_entries"] == 3
        assert result["recent_entries"][0]["date"] == "2025-12-20"

    def test_missing_file(self, homelab_dirs):
        result = get_status()
        assert "error" in result


# ---------------------------------------------------------------------------
# TestJournalCreate
# ---------------------------------------------------------------------------

class TestJournalCreate:
    def test_creates_file(self, journal_index):
        result = create_journal_entry("2026-01-10", SAMPLE_JOURNAL_CONTENT)
        assert result["status"] == "created"
        assert result["date"] == "2026-01-10"
        filepath = Path(result["path"])
        assert filepath.exists()
        assert "Sysmon Deployment" in filepath.read_text(encoding="utf-8")

    def test_creates_month_directory(self, journal_index):
        create_journal_entry("2026-02-05", SAMPLE_JOURNAL_CONTENT)
        month_dir = config.HOMELAB_JOURNAL_DIR / "2026-02"
        assert month_dir.is_dir()

    def test_updates_index(self, journal_index):
        create_journal_entry("2026-01-10", SAMPLE_JOURNAL_CONTENT)
        content = config.HOMELAB_JOURNAL_INDEX.read_text(encoding="utf-8")
        assert "2026-01-10" in content
        # Session count should be incremented from 6 to 7
        assert "7" in content

    def test_rejects_duplicate_date(self, journal_index):
        create_journal_entry("2026-01-10", SAMPLE_JOURNAL_CONTENT)
        result = create_journal_entry("2026-01-10", SAMPLE_JOURNAL_CONTENT)
        assert result["status"] == "exists"

    def test_rejects_bad_date(self, journal_index):
        result = create_journal_entry("not-a-date", SAMPLE_JOURNAL_CONTENT)
        assert "error" in result


# ---------------------------------------------------------------------------
# TestJournalList
# ---------------------------------------------------------------------------

class TestJournalList:
    def test_lists_entries(self, journal_index):
        result = list_journal_entries()
        assert result["total"] == 3
        assert len(result["entries"]) == 3

    def test_respects_limit(self, journal_index):
        result = list_journal_entries(limit=2)
        assert result["count"] == 2
        assert result["total"] == 3

    def test_missing_file(self, homelab_dirs):
        result = list_journal_entries()
        assert "error" in result


# ---------------------------------------------------------------------------
# TestToolsList
# ---------------------------------------------------------------------------

class TestToolsList:
    def test_lists_all(self, tools_csv):
        result = list_tools()
        assert result["count"] == 3

    def test_filters_by_status(self, tools_csv):
        result = list_tools(status="Deployed")
        assert result["count"] == 2
        for t in result["tools"]:
            assert t["status"] == "Deployed"

    def test_missing_csv(self, homelab_dirs):
        result = list_tools()
        assert "error" in result


# ---------------------------------------------------------------------------
# TestToolsAdd
# ---------------------------------------------------------------------------

class TestToolsAdd:
    def test_adds_tool(self, tools_csv):
        result = add_tool("Wireshark", "Wireshark Foundation", "Packet analysis", "Planned")
        assert result["status"] == "added"
        assert result["tool"] == "Wireshark"
        # Verify it's in the CSV
        updated = list_tools()
        assert updated["count"] == 4

    def test_rejects_duplicate(self, tools_csv):
        result = add_tool("Splunk", "Splunk Inc.", "SIEM", "Deployed")
        assert result["status"] == "duplicate"

    def test_preserves_existing(self, tools_csv):
        add_tool("Zeek", "Zeek Project", "Network monitoring", "Deployed")
        result = list_tools()
        names = [t["tool"] for t in result["tools"]]
        assert "Splunk" in names
        assert "Zeek" in names


# ---------------------------------------------------------------------------
# TestNexusRead
# ---------------------------------------------------------------------------

class TestNexusRead:
    def test_reads_file(self, homelab_dirs):
        config.HOMELAB_NEXUS_PATH.write_text("# LAB_NEXUS\nNetwork topology here.", encoding="utf-8")
        result = read_nexus()
        assert result["status"] == "ok"
        assert "Network topology" in result["content"]

    def test_missing_file(self, homelab_dirs):
        result = read_nexus()
        assert "error" in result


# ---------------------------------------------------------------------------
# TestCodexRead
# ---------------------------------------------------------------------------

class TestCodexRead:
    def test_reads_file(self, homelab_dirs):
        config.HOMELAB_CODEX_PATH.write_text("# LABSCRIBE CODEX\nFormatting rules.", encoding="utf-8")
        result = read_codex()
        assert result["status"] == "ok"
        assert "Formatting rules" in result["content"]

    def test_missing_file(self, homelab_dirs):
        result = read_codex()
        assert "error" in result
