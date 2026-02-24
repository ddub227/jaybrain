# JayBrain Long-Term Build Queue

Last updated: 2026-02-24

## Hardware Profile

| Spec | Value |
|------|-------|
| CPU | Intel N100 (4 cores, no HT, 800 MHz base / 3.4 GHz burst) |
| RAM | 15.8 GB (typical ~5 GB free with Edge + Claude Code running) |
| Disk | 475 GB SSD, ~167 GB free |
| OS | Windows 11 Pro (no WSL installed) |
| Python | 3.13 (Windows Store) |

## Current System Footprint

### What's Running

| Component | Type | RAM Estimate | CPU Impact |
|-----------|------|-------------|------------|
| JayBrain MCP Server | On-demand (per Claude Code session) | ~80 MB (ONNX model + SQLite) | Burst on embedding calls |
| JayBrain Daemon | Persistent background process | ~40 MB | Negligible (wakes on schedule) |
| GramCracker Telegram Bot | Persistent background process | ~50 MB | Negligible (30s poll loop) |
| Claude Code session | Active during use | ~100 MB (node.exe) | API-bound |
| Pulse session hooks | Fires on every tool use | ~5 MB (short-lived Python) | <1s per event |
| Pre-commit hooks | Fires on every commit | ~10 MB (short-lived) | <3s per commit |

**Total JayBrain overhead: ~280 MB when everything is running.**
That's comfortable on 16 GB with ~5 GB headroom.

### Database

- **Size:** 6.6 MB (will grow slowly -- ~3.5 KB per memory, ~2 KB per forge concept)
- **Tables:** 35 logical tables (73 including FTS/vec virtual tables)
- **Largest tables:** session_activity_log (1,814 rows), forge_concepts (274), forge_reviews (166)
- **Projected size at 10K memories:** ~50-70 MB (still trivial)

### Codebase

- **Modules:** 15+ in `src/jaybrain/`
- **MCP Tools:** 137 registered
- **Daemon Jobs:** 14 scheduled modules + 1 heartbeat
- **Dependencies:** 14 required + 4 optional
- **Tests:** 737 passing
- **Lines of code:** ~16,500 (src/jaybrain/)

## Completed Features

- [x] Persistent memory (episodic, semantic, procedural, decision, preference)
- [x] Hybrid search (vector + FTS keyword)
- [x] Memory consolidation (clustering, dedup, merge, archive)
- [x] Knowledge graph (entities, relationships, BFS traversal)
- [x] User profiling
- [x] Task management + priority queue
- [x] Session continuity (checkpoint, handoff, crash recovery)
- [x] SynapseForge learning engine (spaced repetition, confidence-weighted scoring, Bloom's taxonomy, exam readiness)
- [x] Job hunter pipeline (boards, postings, applications, resume tailoring, interview prep)
- [x] Google Docs/Drive/Sheets/Gmail/Calendar integration
- [x] Browser automation (Playwright + Patchright stealth)
- [x] Homelab journal system (file-based, Obsidian-compatible)
- [x] GramCracker Telegram bot
- [x] Pulse cross-session awareness
- [x] Daemon with APScheduler (13 modules)
- [x] Daily Telegram briefing (10 data sections)
- [x] Time allocation tracking (activity-based from Pulse)
- [x] Network relationship decay (contact tracking + staleness nudges)
- [x] Life domains + goals + sub-goals + dependencies
- [x] Conversation archive to Google Docs
- [x] Event discovery
- [x] Heartbeat notifications (7 check types)
- [x] Pre-commit security (gitleaks + bandit + pip-audit)
- [x] Job board auto-fetch with change detection
- [x] Adversarial security auditor (AUDITOR_CLAUDE.md + launch script)
- [x] SynapseForge study scheduling (enhanced heartbeat with queue depth, streak, exam proximity)

## Build Queue

### Near-Term (ready to build)

#### ~~1. pip-audit Pre-Commit Addition~~ SHIPPED (2026-02-23)
Added to pre-commit hook. Scans dependencies for known CVEs on every commit.

#### ~~2. Job Board Monitoring Automation~~ SHIPPED (2026-02-24)
Daemon module `job_board_autofetch` runs Wednesday 10 AM. Fetches all active boards, computes SHA-256 content hash, detects changes, sends Telegram notification. Content hash stored in `job_boards.content_hash` column (migration 12).

#### ~~3. Adversarial Security Auditor Session~~ SHIPPED (2026-02-24)
`AUDITOR_CLAUDE.md` provides adversarial system prompt with zero project context. `scripts/run_auditor.py` launches a read-only Claude Code session that audits every file in `src/jaybrain/` and produces a structured report (SECURITY / ARCHITECTURE / COMPLEXITY / TECHNICAL DEBT).

#### ~~4. SynapseForge Study Scheduling~~ SHIPPED (2026-02-24)
Enhanced `heartbeat.py` forge study checks with: queue depth (due + new + struggling counts), streak length calculation, exam proximity awareness, adaptive threshold (lowers to 1 when exam <=7 days). Morning/evening notifications include rich context.

### Medium-Term (needs design work)

#### 5. GitHub Actions CI Pipeline
**Resource cost:** Zero local (runs in cloud)
**What:** CI pipeline for tests + bandit + semgrep (semgrep runs on Linux in GitHub Actions).
**Why:** Semgrep can't run on Windows natively. CI gives us semgrep for free in the cloud.
**Verdict: BUILD IT when ready.** Solves the semgrep gap without WSL.

#### 6. Conversation Intelligence
**Resource cost:** Moderate (Claude API calls for summarization)
**What:** Auto-extract decisions, action items, and patterns from Claude Code conversations.
**Why:** context_pack already captures session state. This adds cross-session pattern mining.
**Verdict: DESIGN FIRST.** API cost needs budgeting. Could be expensive at scale.

#### 7. Automated Blog Draft Pipeline
**Resource cost:** Low-Moderate (Claude API for draft generation)
**What:** After homelab sessions, auto-generate blog drafts from journal + session notes.
**Why:** Blog publishing workflow exists but draft creation is manual.
**Verdict: BUILD when homelab sessions resume regularly.**

### Deferred (not worth building now)

#### 8. WSL Installation
**Resource cost: HIGH (2+ GB RAM permanently consumed)**
**What:** Windows Subsystem for Linux for access to Linux-only tools.
**Why considered:** Semgrep, Docker, better shell tooling.
**Why deferred:**
- N100 with 16 GB RAM is already at ~11 GB used with Edge + Claude Code
- WSL 2 takes 2-8 GB RAM (Hyper-V VM), putting you in swap territory
- The primary motivation (semgrep) is solved by GitHub Actions CI (#5)
- Docker on WSL would add another 1-2 GB minimum
- File system cross-access (/mnt/c/) is noticeably slow
**Verdict: DON'T INSTALL.** The resource cost isn't justified. Use GitHub Actions for Linux tooling.

#### 9. Local LLM / Ollama Integration
**Resource cost: PROHIBITIVE**
**What:** Run local language models for offline intelligence.
**Why not:** N100 is an efficiency chip, not a compute chip. Even small models (7B) need 4-8 GB RAM and would saturate all 4 cores. This machine can't do it.
**Verdict: NOT FEASIBLE on current hardware.**

#### 10. Docker Containers
**Resource cost: HIGH (requires WSL 2 on Windows)**
**What:** Containerized services for JayBrain components.
**Why not:** Docker Desktop on Windows requires WSL 2 (see #8). Adds 2-4 GB RAM overhead minimum. JayBrain's architecture (SQLite + Python processes) doesn't benefit from containerization at this scale.
**Verdict: NOT NEEDED.** JayBrain runs fine as native Python processes.

## Resource Budget

**Available RAM budget for JayBrain:** ~3-4 GB (from the ~5 GB typically free)

| Component | Current | Projected (all queue items built) |
|-----------|---------|-----------------------------------|
| MCP Server | ~80 MB | ~80 MB (no change) |
| Daemon | ~40 MB | ~45 MB (1-2 more lightweight jobs) |
| GramCracker | ~50 MB | ~50 MB (no change) |
| Pulse hooks | ~5 MB | ~5 MB (no change) |
| Pre-commit | ~10 MB | ~15 MB (+pip-audit) |
| Browser automation | ~200 MB (when active) | ~200 MB (when active) |
| **Total** | **~385 MB peak** | **~395 MB peak** |

**Verdict: All near-term and medium-term build items are safe for this hardware.**
The items in "Deferred" are deferred specifically because they'd blow the resource budget.

## Architecture Health Notes

- **137 MCP tools** is high but not problematic -- FastMCP handles tool resolution efficiently. Consider grouping related tools under fewer entry points if latency increases.
- **35 database tables** is reasonable. SQLite handles hundreds of tables fine. Monitor DB size when memories exceed ~1,000.
- **13 daemon modules** are mostly cron-triggered (daily/weekly). The only interval-based jobs are heartbeat (60s) and session crash check (30m). Both are lightweight DB queries.
- **No circular dependencies** detected in the import graph.
- **All external API calls** (Google, Telegram, NewsAPI, Anthropic) are in try/except with graceful fallbacks.
