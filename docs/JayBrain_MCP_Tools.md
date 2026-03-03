<!-- TEMPLATE RULES — Claude: follow these exactly when editing this file.
1. Tools are grouped by CATEGORY. Within each category, sorted ALPHABETICALLY by Tool name.
2. When adding a new tool, place it in the correct category table. If no category fits, create a new one.
3. When adding a new tool, fill ALL columns. Use "—" if unknown.
4. Never remove entries without explicit user approval.
5. Date format: YYYY-MM-DD
-->

# JayBrain MCP Tools

Complete registry of all 170 MCP tools exposed by JayBrain. Grouped by category.

## Memory (4 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| deep_recall | query, limit=10 | Single-call search across memories, knowledge, AND graph | 2026-03-02 |
| forget | memory_id | Delete a specific memory by ID | 2026-03-02 |
| recall | query, category, tags, limit=10 | Hybrid vector + keyword search across memories | 2026-03-02 |
| remember | content, category="semantic", tags, importance=0.5 | Store a memory with embedding | 2026-03-02 |

## Profile (2 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| profile_get | — | Read the full user profile | 2026-03-02 |
| profile_update | section, key, value | Update a specific field in the user profile | 2026-03-02 |

## Task (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| task_create | title, description, priority="medium", project, tags, due_date | Create a new task | 2026-03-02 |
| task_list | status, project, priority, limit=50 | List tasks with optional filters | 2026-03-02 |
| task_update | task_id, status/title/description/priority/project/tags/due_date | Update a task's fields | 2026-03-02 |

## Task Queue (7 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| queue_bump | task_id | Move a task to position 1 (urgent) | 2026-03-02 |
| queue_defer | task_id | Move a task to the end of the queue | 2026-03-02 |
| queue_next | — | Returns the next task in the queue | 2026-03-02 |
| queue_pop | — | Mark top task as in_progress and pop it | 2026-03-02 |
| queue_push | task_id, position | Add a task to the queue at optional position | 2026-03-02 |
| queue_reorder | task_ids | Reorder the queue by providing task IDs in order | 2026-03-02 |
| queue_view | — | Show the full task queue | 2026-03-02 |

## Session (4 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| session_checkpoint | summary, decisions_made, next_steps | Save a mid-session checkpoint without closing | 2026-03-02 |
| session_end | summary, decisions_made, next_steps | End current session and create handoff | 2026-03-02 |
| session_handoff | — | Get last session's context for continuity | 2026-03-02 |
| session_start | title="" | Start a new session and return previous handoff | 2026-03-02 |

## Knowledge (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| knowledge_search | query, category, limit=10 | Search knowledge base via hybrid vector + keyword | 2026-03-02 |
| knowledge_store | title, content, category="general", tags, source | Store structured reference knowledge | 2026-03-02 |
| knowledge_update | knowledge_id, title/content/category/tags | Update a knowledge entry | 2026-03-02 |

## SynapseForge v1 (7 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| forge_add | term, definition, category, difficulty, tags, related_jaybrain_component, source, notes, subject_id, bloom_level | Quick-capture a concept for spaced repetition | 2026-03-02 |
| forge_explain | concept_id | Full concept details with review history | 2026-03-02 |
| forge_review | concept_id, outcome, confidence=3, time_spent_seconds, notes, was_correct, error_type, bloom_level | Record a review outcome for a concept | 2026-03-02 |
| forge_search | query, category, difficulty, limit=10 | Search concepts via hybrid vector + keyword | 2026-03-02 |
| forge_stats | — | Get SynapseForge learning statistics | 2026-03-02 |
| forge_study | category, limit=10, subject_id | Get a prioritized study queue | 2026-03-02 |
| forge_update | concept_id, term/definition/category/difficulty/tags/component/source/notes | Update a concept's fields | 2026-03-02 |

## SynapseForge v2 — Subjects & Objectives (7 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| forge_calibration | subject_id="" | Calibration analytics — confidence vs actual performance | 2026-03-02 |
| forge_errors | subject_id="", concept_id="" | Error pattern analysis by type | 2026-03-02 |
| forge_knowledge_map | subject_id | Generate markdown knowledge map for a subject | 2026-03-02 |
| forge_objective_add | subject_id, code, title, domain, exam_weight | Add an exam objective to a subject | 2026-03-02 |
| forge_readiness | subject_id | Exam readiness score with domain breakdown | 2026-03-02 |
| forge_subject_create | name, short_name, description, pass_score, total_questions, time_limit_minutes | Create a new learning subject | 2026-03-02 |
| forge_subject_list | — | List all subjects with concept/objective counts | 2026-03-02 |

## SynapseForge v2 — Extended (4 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| forge_backup | local_only=False | Export forge tables to JSON and optionally Google Docs | 2026-03-02 |
| forge_maintenance | vacuum=True, analyze=True | Run DB maintenance — integrity check, VACUUM, ANALYZE | 2026-03-02 |
| forge_reembed | subject_id="", dry_run=False | Regenerate missing embeddings for forge concepts | 2026-03-02 |
| forge_weak_areas | subject_id="", limit=10 | Identify weak areas with remediation recommendations | 2026-03-02 |

## System (4 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| context_pack | — | Full startup context — profile, handoff, tasks, decisions, forge data | 2026-03-02 |
| daily_briefing_send | — | Send daily briefing HTML email via Gmail on demand | 2026-03-02 |
| memory_reinforce | memory_id | Boost a memory's importance by incrementing access count | 2026-03-02 |
| stats | — | JayBrain system statistics — counts and storage | 2026-03-02 |

## Job Board (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| job_board_add | name, url, board_type="general", tags | Register a job board URL to monitor | 2026-03-02 |
| job_board_fetch | board_id, max_pages=0, render="auto" | Fetch a job board URL with SPA detection | 2026-03-02 |
| job_board_list | active_only=True | List all registered job boards | 2026-03-02 |

## Job Posting (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| job_add | title, company, url, description, required_skills, preferred_skills, salary, job_type, work_mode, location, board_id, tags | Add a job posting | 2026-03-02 |
| job_get | job_id | Get full job posting details | 2026-03-02 |
| job_search | query, company, work_mode, limit=20 | Search saved job postings | 2026-03-02 |

## Application Tracking (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| app_create | job_id, status="discovered", notes, tags | Start tracking an application | 2026-03-02 |
| app_list | status, limit=50 | List applications with pipeline summary | 2026-03-02 |
| app_update | application_id, status/resume_path/cover_letter_path/applied_date/notes/tags | Update an application | 2026-03-02 |

## Resume & Skills (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| resume_analyze_fit | job_id | Compare JJ's skills against a job posting — match score | 2026-03-02 |
| resume_get_template | — | Read the resume template with HTML comment markers | 2026-03-02 |
| resume_save_tailored | company, role, content | Save tailored resume as markdown + Google Doc | 2026-03-02 |

## Google Docs & Drive (5 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| gdoc_create | title, content, folder_id, share_with | Create a formatted Google Doc from markdown | 2026-03-02 |
| gdoc_edit | doc_id, operation, find/replace/heading/content | Edit an existing Google Doc | 2026-03-02 |
| gdoc_read_structure | doc_id | Read a Google Doc's structure — headings, levels, indexes | 2026-03-02 |
| gdrive_find_or_create_folder | name, parent_id | Find or create a Google Drive folder | 2026-03-02 |
| gdrive_move_to_folder | file_id, folder_id | Move a file into a Drive folder | 2026-03-02 |

## Email (1 tool)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| send_email | to, subject, body | Send email via Gmail API with markdown-to-HTML | 2026-03-02 |

## Cover Letter & Interview (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| cover_letter_save | company, role, content | Save cover letter as markdown + Google Doc | 2026-03-02 |
| interview_prep_add | application_id, prep_type="general", content, tags | Save interview prep content | 2026-03-02 |
| interview_prep_get | application_id | Get full interview context — job, app, prep, resume | 2026-03-02 |

## Memory Consolidation (5 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| memory_archive | memory_ids, reason="manual_archive" | Soft-delete memories without merging | 2026-03-02 |
| memory_consolidation_stats | — | Consolidation history — archive counts, merge logs | 2026-03-02 |
| memory_find_clusters | min_similarity=0.80, max_age_days, category, limit=10 | Find clusters of semantically similar memories | 2026-03-02 |
| memory_find_duplicates | threshold=0.92, category, limit=20 | Find near-duplicate memory pairs | 2026-03-02 |
| memory_merge | memory_ids, merged_content, merged_tags, merged_importance, reason | Merge multiple memories into one | 2026-03-02 |

## Knowledge Graph (5 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| graph_add_entity | name, entity_type, description, aliases, source_memory_ids, properties | Add or update a graph entity | 2026-03-02 |
| graph_add_relationship | source_entity, target_entity, rel_type, weight, evidence_ids, properties, valid_from/until | Add or update a relationship | 2026-03-02 |
| graph_list | entity_type, limit=100 | List all entities in the graph | 2026-03-02 |
| graph_query | entity_name, depth=1, entity_type | Get an entity and its N-depth neighborhood | 2026-03-02 |
| graph_search | query, entity_type, limit=20 | Search entities by name substring | 2026-03-02 |

## Contact / Network Decay (4 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| contact_add | name, contact_type="professional", company, role, how_met, decay_threshold_days=30 | Add a professional contact | 2026-03-02 |
| contact_list | stale_only=False | List contacts with decay status | 2026-03-02 |
| contact_log | name, note | Log an interaction — resets decay timer | 2026-03-02 |
| network_health | — | Summary of professional network health | 2026-03-02 |

## Homelab (7 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| homelab_codex_read | — | Read LABSCRIBE_CODEX journal formatting rules | 2026-03-02 |
| homelab_journal_create | date, content | Create a journal entry and update JOURNAL_INDEX | 2026-03-02 |
| homelab_journal_list | limit=10 | List recent journal entries | 2026-03-02 |
| homelab_nexus_read | — | Read LAB_NEXUS infrastructure overview | 2026-03-02 |
| homelab_status | — | Quick stats, skills, SOC readiness, recent entries | 2026-03-02 |
| homelab_tools_add | tool, creator, purpose, status="Deployed" | Add a tool to HOMELAB_TOOLS_INVENTORY | 2026-03-02 |
| homelab_tools_list | status | List homelab tools filtered by status | 2026-03-02 |

## Pulse — Cross-Session Awareness (4 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| pulse_active | stale_minutes=60 | List all active Claude Code sessions | 2026-03-02 |
| pulse_activity | session_id, limit=20 | Recent activity stream across sessions | 2026-03-02 |
| pulse_context | session_id, snippet, last_n=30, context_window=10 | Read another session's conversation transcript | 2026-03-02 |
| pulse_session | session_id | Full details on a specific session | 2026-03-02 |

## Time Allocation (2 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| time_allocation_daily | days_back=7 | Daily breakdown of hours by domain | 2026-03-02 |
| time_allocation_report | days_back=7 | Weekly time allocation report vs targets | 2026-03-02 |

## Telegram (2 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| telegram_send | message | Send a message to JJ via Telegram | 2026-03-02 |
| telegram_status | — | Check GramCracker bot health | 2026-03-02 |

## Browser — Core (8 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| browser_click | ref, selector | Click an element by ref number or CSS selector | 2026-03-02 |
| browser_close | — | Close the browser and release resources | 2026-03-02 |
| browser_launch | headless=True, url, stealth=False | Launch a Chromium browser instance | 2026-03-02 |
| browser_navigate | url | Navigate to a URL | 2026-03-02 |
| browser_press_key | key | Press a keyboard key (Enter, Tab, Escape, etc.) | 2026-03-02 |
| browser_screenshot | full_page=False | Take a screenshot — returns file path | 2026-03-02 |
| browser_snapshot | — | Get page accessibility tree with numbered refs | 2026-03-02 |
| browser_type | text, ref, selector, clear=True | Type text into an input field | 2026-03-02 |

## Browser — Session & Advanced (7 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| browser_fill_from_bw | item_name, field="password", ref, selector | Fill a form field with a Bitwarden credential | 2026-03-02 |
| browser_hover | ref, selector | Hover over an element | 2026-03-02 |
| browser_select_option | ref, selector, value, label, index | Select from a dropdown | 2026-03-02 |
| browser_session_list | — | List saved browser sessions | 2026-03-02 |
| browser_session_load | name, headless, url, stealth | Launch browser with a saved session | 2026-03-02 |
| browser_session_save | name | Save current session (cookies + localStorage) | 2026-03-02 |
| browser_wait | selector, text, state="visible", timeout=10000 | Wait for element or text to appear/disappear | 2026-03-02 |

## Browser — Navigation & Tabs (7 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| browser_evaluate | name | Evaluate a named JS expression from safe allowlist | 2026-03-02 |
| browser_go_back | — | Navigate back in history | 2026-03-02 |
| browser_go_forward | — | Navigate forward in history | 2026-03-02 |
| browser_tab_close | index | Close a tab by index or current tab | 2026-03-02 |
| browser_tab_list | — | List all open tabs with URLs and titles | 2026-03-02 |
| browser_tab_new | url="" | Open a new tab | 2026-03-02 |
| browser_tab_switch | index | Switch to a tab by index | 2026-03-02 |

## Browser — CDP Reconnection (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| browser_connect_cdp | endpoint | Reconnect to running Chrome via CDP | 2026-03-02 |
| browser_disconnect_cdp | — | Disconnect from CDP browser without closing | 2026-03-02 |
| browser_launch_cdp | port=9222, url, headless=False | Launch Chrome with CDP remote debugging | 2026-03-02 |

## Daemon (2 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| daemon_control | action | Control daemon — start or stop | 2026-03-02 |
| daemon_status | — | Check daemon status — state, PID, heartbeat, modules | 2026-03-02 |

## File Watcher (1 tool)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| file_deletions | path, since, limit=20 | Query the file deletion log | 2026-03-02 |

## Git Shadow (2 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| git_shadow_history | repo, file, since, limit=20 | Query working tree snapshot history | 2026-03-02 |
| git_shadow_restore | shadow_id, file_path | Extract a file version from a shadow snapshot | 2026-03-02 |

## Conversation Archive (2 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| conversation_archive_run | — | Manually trigger conversation archive to Google Docs | 2026-03-02 |
| conversation_archive_status | — | Check archive status — recent runs and stats | 2026-03-02 |

## Life Domains (6 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| domains_conflicts | — | Check for conflicts in goal scheduling | 2026-03-02 |
| domains_goal_detail | goal_id | Detailed information about a specific goal | 2026-03-02 |
| domains_overview | — | Overview of all life domains with goals and progress | 2026-03-02 |
| domains_priority_stack | — | Current priority stack by deadlines, weights, exams | 2026-03-02 |
| domains_sync | — | Manually sync Life Domains from Google Doc | 2026-03-02 |
| domains_update_progress | goal_id, progress, note | Update progress on a goal (0.0–1.0) | 2026-03-02 |

## Heartbeat (2 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| heartbeat_status | — | Check heartbeat notification status | 2026-03-02 |
| heartbeat_test | check_name | Manually trigger a specific heartbeat check | 2026-03-02 |

## Onboarding (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| onboarding_answer | step, response | Submit an answer for an onboarding step | 2026-03-02 |
| onboarding_progress | — | Check onboarding completion status | 2026-03-02 |
| onboarding_start | — | Start the onboarding intake questionnaire | 2026-03-02 |

## Event Discovery (2 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| event_discover | — | Trigger event discovery for local cyber events | 2026-03-02 |
| event_list | status="new", limit=20 | List discovered events by status | 2026-03-02 |

## Feedly (3 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| feedly_fetch | — | Manually trigger a Feedly AI Feed poll | 2026-03-02 |
| feedly_search | query, limit=10 | Search Feedly articles in knowledge base | 2026-03-02 |
| feedly_status | — | Check feed monitoring status and recent articles | 2026-03-02 |

## News Feed (5 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| news_feed_add_source | name, url, source_type="rss", tags | Register a new RSS/Atom/JSON feed source | 2026-03-02 |
| news_feed_list_sources | active_only=True | List all feed sources with poll status | 2026-03-02 |
| news_feed_poll | source_id="" | Poll one or all active feeds | 2026-03-02 |
| news_feed_remove_source | source_id | Remove a feed source | 2026-03-02 |
| news_feed_status | — | Dashboard for news feed ingestion | 2026-03-02 |

## SignalForge (9 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| signalforge_cluster_detail | cluster_id | Full details for a story cluster with articles | 2026-03-02 |
| signalforge_clusters | limit=20, min_significance=0.0 | List story clusters ranked by significance | 2026-03-02 |
| signalforge_feed_start | — | Start HTTP feed server on localhost:8247 | 2026-03-02 |
| signalforge_feed_stop | — | Stop the HTTP feed server | 2026-03-02 |
| signalforge_fetch | knowledge_id | Fetch full article text for a specific article | 2026-03-02 |
| signalforge_read | knowledge_id | Read full article text from file store | 2026-03-02 |
| signalforge_status | — | Dashboard — fetch progress, storage stats, expiring articles | 2026-03-02 |
| signalforge_clusters | limit=20, min_significance=0.0 | List story clusters ranked by significance | 2026-03-02 |
| signalforge_synthesize | force=False | Trigger daily SignalForge synthesis to Google Docs | 2026-03-02 |
| signalforge_synthesis_status | — | Synthesis dashboard — last 7 runs and token usage | 2026-03-02 |

## Personality (1 tool)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| personality_config | style, energy_level, humor_level | View or update personality settings | 2026-03-02 |

## Trash / Recycle Bin (6 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| trash_auto_cleanup | — | Run full auto-cleanup pipeline | 2026-03-02 |
| trash_delete | filepath, reason | Move a file to trash (soft-delete) | 2026-03-02 |
| trash_list | category, limit=50 | List files in trash | 2026-03-02 |
| trash_restore | entry_id | Restore a trashed file to original location | 2026-03-02 |
| trash_scan | auto_only=False | Scan for trashable files | 2026-03-02 |
| trash_sweep | — | Permanently delete expired trash entries | 2026-03-02 |

## Cram (6 tools)

| Tool | Parameters | Purpose | Added |
|------|-----------|---------|-------|
| cram_add | topic, description, source_question, source_answer | Add a cram topic — auto-links to SynapseForge | 2026-03-02 |
| cram_list | sort_by="understanding" | List all cram topics with understanding levels | 2026-03-02 |
| cram_remove | topic_id | Remove a cram topic | 2026-03-02 |
| cram_review | topic_id, was_correct, confidence=3, notes | Record a cram quiz answer | 2026-03-02 |
| cram_stats | — | Cram dashboard — counts, accuracy, distribution | 2026-03-02 |
| cram_study | limit=10 | Get prioritized cram study queue | 2026-03-02 |
