# JayBrain

Personal AI memory system for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). JayBrain is an MCP server that gives Claude persistent memory, user profiling, task tracking, spaced-repetition learning, job search automation, and cross-session continuity.

## Features

- **Persistent Memory** -- Store and recall memories with hybrid vector + keyword search (SQLite + sqlite-vec, ONNX embeddings)
- **User Profile** -- YAML-based profile with preferences, projects, and tools
- **Task Tracking** -- Create, update, and list tasks with priority and status
- **Session Continuity** -- Checkpoints, handoffs, and crash recovery across Claude Code sessions
- **Knowledge Base** -- Store and search reference material
- **Knowledge Graph** -- Entity and relationship tracking (people, projects, tools, skills)
- **Memory Consolidation** -- Clustering, deduplication, and archival of old memories
- **SynapseForge** -- Subject-agnostic learning engine with spaced repetition, confidence-weighted scoring, Bloom's taxonomy levels, exam readiness analytics, and error pattern tracking
- **Job Hunter** -- Job board monitoring, resume tailoring, cover letter generation, application pipeline tracking, and interview prep
- **Google Docs Integration** -- Auto-create Google Docs for resumes and cover letters via OAuth
- **Daily Briefing** -- Morning email digest with tasks, study stats, and job pipeline
- **GramCracker** -- Telegram bot for mobile access to JayBrain via Claude API
- **Pulse** -- Cross-session awareness (see what other Claude Code sessions are doing)
- **Browser Automation** -- Playwright-based browser control with stealth mode and Bitwarden integration
- **Homelab Journal** -- File-based lab documentation system (Obsidian-compatible markdown)

## Requirements

- Python 3.11+
- Claude Code CLI

## Installation

```bash
git clone https://github.com/ddub227/jaybrain.git
cd jaybrain
pip install -e ".[dev]"
```

For browser automation:

```bash
pip install -e ".[render]"
playwright install chromium
```

For stealth mode (bot-detection bypass):

```bash
pip install -e ".[stealth]"
patchright install chromium
```

## Configuration

1. Copy `.env.example` to `.env` and fill in your values
2. Set up Google OAuth credentials at `~/.config/gcloud/`
3. Configure Claude Code to use JayBrain as an MCP server

### Claude Code MCP Setup

Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "jaybrain": {
      "command": "python",
      "args": ["-m", "jaybrain.server"],
      "cwd": "/path/to/jaybrain"
    }
  }
}
```

## MCP Tools

### Memory
- `remember` -- Store a memory with category, importance, and tags
- `recall` -- Search memories with hybrid vector + keyword search
- `context_pack` -- Restore full context at session start
- `memory_find_clusters` / `memory_find_duplicates` -- Find similar or duplicate memories
- `memory_merge` / `memory_archive` -- Consolidate or archive memories
- `memory_consolidation_stats` -- View archive stats

### Profile
- `profile_get` / `profile_update` -- Read and update user profile

### Tasks
- `task_create` / `task_update` / `task_list` -- Task CRUD and listing

### Sessions
- `session_start` / `session_end` / `session_checkpoint` / `session_handoff` -- Session lifecycle management

### Knowledge
- `knowledge_store` / `knowledge_search` / `knowledge_update` -- Reference material storage

### Knowledge Graph
- `graph_add_entity` / `graph_add_relationship` -- Build the knowledge graph
- `graph_query` / `graph_search` / `graph_list` -- Query entities and relationships

### SynapseForge (Learning)
- `forge_add` / `forge_review` / `forge_study` / `forge_explain` -- Concept CRUD and study sessions
- `forge_subject_create` / `forge_subject_list` / `forge_objective_add` -- Subject and objective management
- `forge_readiness` / `forge_calibration` / `forge_knowledge_map` / `forge_errors` -- Analytics
- `forge_search` / `forge_update` / `forge_stats` -- Search, update, and stats

### Job Hunter
- `job_add` / `job_board_add` / `job_board_fetch` -- Job posting and board management
- `resume_get_template` / `resume_analyze_fit` / `resume_save_tailored` -- Resume tailoring
- `cover_letter_save` -- Cover letter generation
- `app_create` / `app_update` / `app_list` -- Application pipeline
- `interview_prep_add` / `interview_prep_get` -- Interview preparation

### Integrations
- `gdoc_create` -- Create Google Docs from markdown
- `telegram_send` / `telegram_status` -- Telegram messaging
- `pulse_active` / `pulse_activity` / `pulse_session` -- Cross-session awareness

### Browser
- `browser_launch` / `browser_close` / `browser_navigate` -- Browser lifecycle
- `browser_snapshot` / `browser_screenshot` -- Page inspection
- `browser_click` / `browser_type` / `browser_hover` / `browser_press_key` -- Interaction
- `browser_select_option` / `browser_wait` / `browser_evaluate` -- Advanced interaction
- `browser_session_save` / `browser_session_load` / `browser_session_list` -- Session persistence
- `browser_fill_from_bw` -- Bitwarden credential injection
- `browser_tab_new` / `browser_tab_list` / `browser_tab_switch` / `browser_tab_close` -- Tab management

### Homelab
- `homelab_codex_read` / `homelab_status` / `homelab_nexus_read` -- Lab documentation
- `homelab_journal_create` / `homelab_journal_list` -- Journal entries
- `homelab_tools_list` / `homelab_tools_add` -- Tools inventory

## Architecture

- **Server**: FastMCP framework
- **Database**: SQLite + sqlite-vec for hybrid vector search
- **Embeddings**: ONNX Runtime with all-MiniLM-L6-v2 (384-dim, downloaded on first run)
- **Profile**: YAML file in `data/`
- **Sessions**: SQLite tables + markdown handoff files

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

## License

MIT -- see [LICENSE](LICENSE).
