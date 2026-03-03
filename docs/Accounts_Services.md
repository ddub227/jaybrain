<!-- TEMPLATE RULES — Claude: follow these exactly when editing this file.
1. All entries go in the table below, sorted ALPHABETICALLY by Service name.
2. When adding a new entry, fill ALL columns. Use "—" if unknown.
3. Categories: api | platform | subscription | tool | internal
4. Auth methods: oauth | api-key | bot-token | cli | none | app-password
5. NEVER include actual credentials, tokens, or secrets in this file.
6. Never remove entries without explicit user approval.
7. Date format: YYYY-MM-DD
-->

# Accounts & Services

Every API, platform, subscription, and external service JJ uses across all projects.

| Service | Category | Purpose | Auth Method | Env Var / Config | Used By | Added |
|---------|----------|---------|-------------|------------------|---------|-------|
| Anthropic Claude API | api | LLM calls for GramCracker responses and SignalForge synthesis | api-key | ANTHROPIC_API_KEY | telegram.py, signalforge.py | 2026-03-02 |
| Bitwarden CLI | tool | Runtime credential retrieval — never hardcode secrets | cli | bw_unlock.ps1 | browser.py (browser_fill_from_bw) | 2026-03-02 |
| Claude Code (Max 20x) | subscription | Primary AI coding assistant — $200/month plan | subscription | — | All development | 2026-03-02 |
| Eventbrite API | api | Local cybersecurity/networking event discovery in Charlotte, NC | api-key | EVENTBRITE_API_KEY | event_discovery.py | 2026-03-02 |
| Feedly API | api | AI feed monitoring — polls every 15 min for curated articles | api-key | FEEDLY_ACCESS_TOKEN, FEEDLY_STREAM_ID | feedly.py | 2026-03-02 |
| GitHub | platform | Source control, blog hosting (Pages), pre-commit hooks | cli | git credential manager | All repos | 2026-03-02 |
| Google Calendar API | api | Calendar data access (read-only) | oauth | jaybrain-oauth-token.json | gdocs.py | 2026-03-02 |
| Google Docs API | api | Creates formatted resumes, cover letters, course tracker, synthesis docs | oauth | jaybrain-oauth-token.json | gdocs.py | 2026-03-02 |
| Google Drive API | api | Organizes files into folders, moves documents | oauth | jaybrain-oauth-token.json | gdocs.py | 2026-03-02 |
| Google Gmail API | api | Sends daily briefing emails and general email | oauth | jaybrain-oauth-token.json | daily_briefing.py, server.py | 2026-03-02 |
| Google Sheets API | api | Job tracker spreadsheet, networking spreadsheet, homelab tools | oauth | NETWORKING_SPREADSHEET_ID, JOB_SHEET_SPREADSHEET_ID | gdocs.py | 2026-03-02 |
| HuggingFace Hub | platform | One-time download of all-MiniLM-L6-v2 ONNX embedding model | none | — | search.py | 2026-03-02 |
| Meetup.com | platform | Web-scraped for local cybersecurity events (no API) | none | — | event_discovery.py | 2026-03-02 |
| NewsAPI | api | General news article ingestion | api-key | NEWSAPI_KEY | news_feeds.py | 2026-03-02 |
| SignalForge Feed Server | internal | Localhost HTTP server (port 8247) serving clustered news as HTML | none | SIGNALFORGE_FEED_PORT | signalforge_feed.py | 2026-03-02 |
| Telegram Bot API | api | GramCracker bot — receives and responds to JJ's mobile messages | bot-token | TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_USER | telegram.py | 2026-03-02 |
