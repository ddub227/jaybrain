<!-- TEMPLATE RULES — Claude: follow these exactly when editing this file.
1. All entries go in the table below, sorted ALPHABETICALLY by Tool name (case-insensitive).
2. When adding a new entry, fill ALL columns. Never leave a column blank — use "—" if unknown.
3. When adding a new column, backfill ALL existing rows before finishing.
4. Never remove entries without explicit user approval.
5. Categories: library | framework | service | extension | dev | stdlib
6. "Used By" = the JayBrain source file(s) that import/use the tool (e.g., server.py, db.py).
7. Date format: YYYY-MM-DD
-->

# JayBrain Tools & Dependencies

Complete inventory of every tool, library, framework, and service that JayBrain uses.

| Tool | Category | Purpose | Used By | Added |
|------|----------|---------|---------|-------|
| anthropic | library | Anthropic Python SDK — calls Claude for GramCracker responses and SignalForge synthesis | telegram.py, signalforge.py | 2026-03-02 |
| apscheduler | library | Scheduled task backbone for the daemon — cron and interval triggers for all recurring jobs | daemon.py | 2026-03-02 |
| asyncio | stdlib | Async event loop for the MCP server — runs FastMCP and offloads sync work via run_in_executor | server.py | 2026-03-02 |
| bandit | dev | Python security linter — runs via pre-commit hook to catch hardcoded secrets and subprocess risks | pyproject.toml | 2026-03-02 |
| beautifulsoup4 | library | HTML parsing — fallback article text extraction in SignalForge, job board page scraping with SPA detection | scraping.py | 2026-03-02 |
| concurrent.futures | stdlib | ThreadPoolExecutor — dedicated single-worker thread pool for all Playwright browser calls | server.py | 2026-03-02 |
| defusedxml | library | Secure XML/RSS parsing — prevents XXE attacks when parsing feeds from external sources | news_feeds.py | 2026-03-02 |
| email.mime | stdlib | Constructs HTML email for the daily morning briefing before sending via Gmail API | daily_briefing.py | 2026-03-02 |
| Eventbrite API | service | Searches for local cybersecurity and networking events in Charlotte, NC | event_discovery.py | 2026-03-02 |
| FastMCP | framework | The MCP server framework — exposes all JayBrain tools to Claude Code via Model Context Protocol | server.py | 2026-03-02 |
| Feedly API | service | Polls JJ's Feedly AI Feed stream for new articles, deduplicates, stores with embeddings | feedly.py | 2026-03-02 |
| fnmatch | stdlib | Pattern matching for file watcher ignore rules — keeps deletion log clean of WAL noise events | file_watcher.py | 2026-03-02 |
| git | service | GitShadow calls git stash create via subprocess; conversation archive calls claude -p for summaries | git_shadow.py, conversation_archive.py | 2026-03-02 |
| google-api-python-client | library | Google Docs/Drive/Sheets/Gmail API client — creates docs, organizes Drive folders, sends briefing email | gdocs.py, daily_briefing.py | 2026-03-02 |
| google-auth | library | OAuth 2.0 credential loading and token refresh for Google APIs with scope validation | gdocs.py, daily_briefing.py | 2026-03-02 |
| google-auth-oauthlib | library | Runs OAuth 2.0 interactive browser flow to get initial token when no cached token exists | gdocs.py | 2026-03-02 |
| googlenewsdecoder | library | Decodes Google News protobuf-encoded redirect URLs to get actual article URLs | signalforge.py | 2026-03-02 |
| hashlib | stdlib | SHA-256 verification of downloaded ONNX model and content-change detection hashing for job boards | search.py, job_boards.py | 2026-03-02 |
| http.server | stdlib | Zero-dependency localhost HTTP server — serves SignalForge clustered news articles as HTML | signalforge_feed.py | 2026-03-02 |
| HuggingFace Hub | service | One-time download source for the all-MiniLM-L6-v2 ONNX embedding model (SHA-256 verified) | search.py | 2026-03-02 |
| ipaddress + socket | stdlib | SSRF protection — resolves hostnames and blocks requests to private/loopback/link-local ranges | config.py | 2026-03-02 |
| numpy | library | Numerical ops on embedding vectors — mean pooling, L2 normalization, cosine similarity matrices | search.py, consolidation.py, signalforge.py | 2026-03-02 |
| onnxruntime | library | Runs all-MiniLM-L6-v2 ONNX model locally for 384-dim text embeddings — no API calls needed | search.py | 2026-03-02 |
| pathlib | stdlib | Filesystem path handling used universally — handles Windows/cross-platform slash issues automatically | all modules | 2026-03-02 |
| patchright | library | Drop-in stealth Playwright replacement — patches Chromium CDP signatures to evade bot detection | browser.py | 2026-03-02 |
| pip-audit | dev | Scans installed packages for known CVEs | pyproject.toml | 2026-03-02 |
| playwright | framework | Browser automation via Chromium — all browser_* MCP tools for navigation, clicking, screenshots | browser.py | 2026-03-02 |
| pydantic | library | Data validation and serialization — all JayBrain data models are Pydantic BaseModels with Field validators | models.py | 2026-03-02 |
| pytest | dev | Test runner for the entire test suite (80+ test files) | tests/ | 2026-03-02 |
| pytest-asyncio | dev | Enables asyncio_mode=auto in pytest so async test functions work without boilerplate | pyproject.toml | 2026-03-02 |
| pyyaml | library | Reads and writes the user profile file (profile.yaml) — stores JJ's name, preferences, and notes | profile.py | 2026-03-02 |
| requests | library | HTTP client — downloads ONNX model, calls Feedly/Eventbrite/Telegram APIs, fetches RSS feeds and articles | search.py, feedly.py, event_discovery.py, telegram.py, news_feeds.py, signalforge.py | 2026-03-02 |
| SQLite | service | Primary data store for ALL JayBrain data — WAL mode enabled, single-file database, zero-config | db.py, daemon.py, file_watcher.py, git_shadow.py, daily_briefing.py, signalforge_feed.py | 2026-03-02 |
| sqlite-vec | extension | SQLite extension adding vector similarity search (ANN) — powers hybrid search with cosine distance on 384-dim embeddings | db.py | 2026-03-02 |
| struct | stdlib | Packs/unpacks 32-bit floats for serializing embedding vectors to/from SQLite binary blobs | db.py | 2026-03-02 |
| subprocess | stdlib | Spawns child processes — launches Chromium via CDP, runs git commands, calls claude CLI | browser.py, git_shadow.py, conversation_archive.py, daemon.py | 2026-03-02 |
| Telegram Bot API | service | GramCracker bot — polls Telegram HTTP API directly via requests to receive and respond to JJ's messages | telegram.py | 2026-03-02 |
| threading | stdlib | Background daemon threads — file watcher Observer and SignalForge HTTP feed server | browser.py, telegram.py, signalforge_feed.py | 2026-03-02 |
| tokenizers | library | Rust-based HuggingFace tokenizer — pre-processes text into token IDs before feeding to ONNX model | search.py | 2026-03-02 |
| trafilatura | library | Best-in-class article text extraction from HTML (F1: 0.958) — primary extractor in SignalForge | signalforge.py | 2026-03-02 |
| uuid | stdlib | Generates 12-char hex IDs for all database rows via uuid4().hex[:12] | all modules with DB writes | 2026-03-02 |
| watchdog | library | Filesystem event monitoring — watches project directory for file deletions, logs forensic trail | file_watcher.py | 2026-03-02 |
