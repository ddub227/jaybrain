"""Paths, constants, and data directory setup."""

import ipaddress
import logging
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

# Base directories
PROJECT_ROOT = Path(__file__).parent.parent.parent


def _load_env() -> None:
    """Load .env file from project root if present. Existing env vars take priority."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if not os.environ.get(key):
                os.environ[key] = value


_env_initialized = False


def init() -> None:
    """Load .env and set env-dependent constants. Safe to call multiple times."""
    global _env_initialized
    if _env_initialized:
        return
    _load_env()
    _init_env_vars()
    _env_initialized = True


def _init_env_vars() -> None:
    """Read environment variables into module-level constants."""
    global SERVICE_ACCOUNT_PATH, GDOC_SHARE_EMAIL, GDOC_FOLDER_ID
    global HOMELAB_TOOLS_SHEET_ID, SHEETS_INDEX_ID, NEWSAPI_KEY
    global TELEGRAM_BOT_TOKEN, TELEGRAM_AUTHORIZED_USER
    global ANTHROPIC_API_KEY, GRAMCRACKER_CLAUDE_MODEL
    global HOMELAB_JOURNAL_FILENAME, LIFE_DOMAINS_DOC_ID, EVENTBRITE_API_KEY

    SERVICE_ACCOUNT_PATH = Path(
        os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS",
            os.path.expanduser("~/.config/gcloud/jaybrain-service-account.json"),
        )
    )
    GDOC_SHARE_EMAIL = os.environ.get("GDOC_SHARE_EMAIL", "")
    GDOC_FOLDER_ID = os.environ.get("GDOC_FOLDER_ID", "")
    HOMELAB_TOOLS_SHEET_ID = os.environ.get("HOMELAB_TOOLS_SHEET_ID", "")
    SHEETS_INDEX_ID = os.environ.get("SHEETS_INDEX_ID", "")
    NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")

    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    try:
        TELEGRAM_AUTHORIZED_USER = int(
            os.environ.get("TELEGRAM_AUTHORIZED_USER", "0")
        )
    except (ValueError, TypeError):
        TELEGRAM_AUTHORIZED_USER = 0
        logging.getLogger(__name__).warning(
            "Invalid TELEGRAM_AUTHORIZED_USER env var, defaulting to 0 (disabled)"
        )

    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    GRAMCRACKER_CLAUDE_MODEL = os.environ.get(
        "GRAMCRACKER_CLAUDE_MODEL", "claude-sonnet-4-20250514"
    )
    HOMELAB_JOURNAL_FILENAME = os.environ.get(
        "HOMELAB_JOURNAL_FILENAME", "Learn Out Loud Lab_{date}.md"
    )
    LIFE_DOMAINS_DOC_ID = os.environ.get("LIFE_DOMAINS_DOC_ID", "")
    EVENTBRITE_API_KEY = os.environ.get("EVENTBRITE_API_KEY", "")

    global FEEDLY_ACCESS_TOKEN, FEEDLY_STREAM_ID, FEEDLY_POLL_INTERVAL_MINUTES
    FEEDLY_ACCESS_TOKEN = os.environ.get("FEEDLY_ACCESS_TOKEN", "")
    FEEDLY_STREAM_ID = os.environ.get("FEEDLY_STREAM_ID", "")
    try:
        FEEDLY_POLL_INTERVAL_MINUTES = int(
            os.environ.get("FEEDLY_POLL_INTERVAL_MINUTES", "15")
        )
    except (ValueError, TypeError):
        FEEDLY_POLL_INTERVAL_MINUTES = 15


DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "jaybrain.db"
MEMORIES_DIR = DATA_DIR / "memories"
SESSIONS_DIR = DATA_DIR / "sessions"
ACTIVE_SESSION_FILE = DATA_DIR / ".active_session"
PROFILE_PATH = DATA_DIR / "profile.yaml"
MODELS_DIR = PROJECT_ROOT / "models"

# Job search directories
JOB_SEARCH_DIR = Path(os.path.expanduser("~")) / "Documents" / "job_search"
RESUME_TEMPLATE_PATH = JOB_SEARCH_DIR / "resume_template.md"

# Google Docs integration (OAuth for user account, service account for Sheets MCP)
SERVICE_ACCOUNT_PATH = Path(
    os.path.expanduser("~/.config/gcloud/jaybrain-service-account.json")
)
OAUTH_CLIENT_PATH = Path(
    os.path.expanduser("~/.config/gcloud/jaybrain-oauth-client.json")
)
OAUTH_TOKEN_PATH = Path(
    os.path.expanduser("~/.config/gcloud/jaybrain-oauth-token.json")
)
GDOC_SHARE_EMAIL = ""
GDOC_FOLDER_ID = ""
HOMELAB_TOOLS_SHEET_ID = ""
SHEETS_INDEX_ID = ""

# Centralized OAuth scopes -- all Google API access uses this single list.
# Adding a scope here requires a one-time re-auth (delete the token file).
OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# NewsAPI configuration
NEWSAPI_KEY = ""
NEWSAPI_BASE_URL = "https://newsapi.org/v2"

# Scraping constants
SCRAPE_TIMEOUT = 30  # seconds
SCRAPE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
SCRAPE_MAX_PAGES = 3  # default pagination pages to follow

# Embedding model
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
ONNX_MODEL_URL = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx"
TOKENIZER_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Memory decay constants (SM-2 inspired exponential model)
DECAY_HALF_LIFE_DAYS = 90          # base half-life before 50% decay
DECAY_ACCESS_HALF_LIFE_BONUS = 30  # extra half-life days per access
DECAY_MAX_HALF_LIFE = 730          # cap at ~2 years
MIN_DECAY = 0.05                   # absolute floor

# Search defaults
DEFAULT_SEARCH_LIMIT = 10
VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3
SEARCH_CANDIDATES = 20

# Memory categories
MEMORY_CATEGORIES = [
    "episodic",    # Events, conversations, experiences
    "semantic",    # Facts, concepts, knowledge
    "procedural",  # How-to, processes, workflows
    "decision",    # Decisions made and rationale
    "preference",  # User preferences and opinions
]

# SynapseForge constants
FORGE_DIR = DATA_DIR / "forge"

FORGE_CATEGORIES = [
    "python", "networking", "mcp", "databases", "security",
    "linux", "git", "ai_ml", "web", "devops", "general",
]

# Spaced repetition intervals (mastery_range -> days until next review)
FORGE_INTERVALS = {
    0.0: 1,    # 0-20%: review in 1 day
    0.2: 3,    # 20-40%: review in 3 days
    0.4: 7,    # 40-60%: review in 7 days
    0.6: 14,   # 60-80%: review in 14 days
    0.8: 30,   # 80-100%: review in 30 days
}

# Mastery adjustment per review outcome
FORGE_MASTERY_DELTAS = {
    "understood_high": 0.15,   # understood + confidence >= 4
    "understood_low": 0.10,    # understood + confidence < 4
    "reviewed": 0.05,          # reviewed (neutral)
    "struggled": -0.10,        # struggled (lose ground)
    "skipped": 0.0,            # skipped (no change)
}

# Mastery level thresholds (name, min_mastery)
FORGE_MASTERY_LEVELS = [
    ("Spark", 0.0),
    ("Ember", 0.20),
    ("Flame", 0.40),
    ("Blaze", 0.60),
    ("Inferno", 0.80),
    ("Forged", 0.95),
]

# v2: Confidence-weighted mastery deltas (4 quadrants)
FORGE_MASTERY_DELTAS_V2 = {
    "correct_confident": 0.20,
    "correct_unsure": 0.10,
    "incorrect_confident": -0.15,
    "incorrect_unsure": -0.05,
    "skipped": 0.0,
}

# Bloom's revised taxonomy levels (ascending cognitive complexity)
FORGE_BLOOM_LEVELS = ["remember", "understand", "apply", "analyze"]

# Error classification types
FORGE_ERROR_TYPES = ["slip", "lapse", "mistake", "misconception"]

# Prerequisite mastery threshold before dependent concept unlocks
FORGE_PREREQ_THRESHOLD = 0.40

# Readiness scoring weights
FORGE_READINESS_WEIGHTS = {
    "mastery": 0.50,
    "coverage": 0.25,
    "calibration": 0.15,
    "recency": 0.10,
}

# Memory consolidation constants
CONSOLIDATION_DEFAULT_SIMILARITY = 0.80   # min cosine similarity for clustering
CONSOLIDATION_DUPLICATE_THRESHOLD = 0.92  # near-exact duplicate detection
CONSOLIDATION_MAX_CLUSTER_SIZE = 10       # max memories per cluster

# Knowledge graph constants
GRAPH_ENTITY_TYPES = [
    "person", "project", "tool", "skill", "company",
    "concept", "location", "organization",
]
GRAPH_RELATIONSHIP_TYPES = [
    "uses", "knows", "related_to", "part_of", "depends_on",
    "works_at", "created_by", "collaborates_with", "learned_from",
]
GRAPH_DEFAULT_DEPTH = 1
GRAPH_MAX_DEPTH = 3

# --- GramCracker (Telegram bot) ---
TELEGRAM_BOT_TOKEN = ""  # nosec B105 -- empty default, real value set by init()
TELEGRAM_AUTHORIZED_USER = 0
TELEGRAM_POLL_TIMEOUT = 30
TELEGRAM_API_BASE = "https://api.telegram.org/bot"
TELEGRAM_MAX_MESSAGE_LEN = 4096
TELEGRAM_RATE_LIMIT_WINDOW = 60
TELEGRAM_RATE_LIMIT_MAX = 20
TELEGRAM_HISTORY_LIMIT = 30
TELEGRAM_MAX_RESPONSE_TOKENS = 4096
ANTHROPIC_API_KEY = ""
GRAMCRACKER_CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Homelab project paths (file-based, not in SQLite)
HOMELAB_ROOT = Path(os.path.expanduser("~")) / "projects" / "homelab"
HOMELAB_NOTES_DIR = HOMELAB_ROOT / "notes"
HOMELAB_JOURNAL_DIR = HOMELAB_NOTES_DIR / "Journal"
HOMELAB_JOURNAL_INDEX = HOMELAB_JOURNAL_DIR / "JOURNAL_INDEX.md"
HOMELAB_CODEX_PATH = HOMELAB_NOTES_DIR / "LABSCRIBE_CODEX.md"
HOMELAB_NEXUS_PATH = HOMELAB_NOTES_DIR / "LAB_NEXUS.md"
HOMELAB_TOOLS_CSV = HOMELAB_ROOT / "HOMELAB_TOOLS_INVENTORY.csv"
HOMELAB_ATTACHMENTS_DIR = HOMELAB_JOURNAL_DIR / "attachments"
HOMELAB_JOURNAL_FILENAME = "Learn Out Loud Lab_{date}.md"


# --- Obsidian Vault Sync ---
VAULT_PATH = Path(os.path.expanduser("~")) / "JayBrain-Vault"
VAULT_SYNC_ENABLED = True
VAULT_SYNC_INTERVAL_SECONDS = 60  # daemon checks for changes every 60s

# --- File Watcher (Watchdog) ---
FILE_WATCHER_ENABLED = True
FILE_WATCHER_PATHS = [str(PROJECT_ROOT)]
FILE_WATCHER_IGNORE_PATTERNS: list[str] = []  # additional patterns beyond defaults

# --- GitShadow (Working Tree Snapshots) ---
GIT_SHADOW_ENABLED = True
GIT_SHADOW_INTERVAL_SECONDS = 600  # 10 minutes
GIT_SHADOW_REPO_PATHS = [str(PROJECT_ROOT)]

# Category -> subfolder mapping for memories
VAULT_MEMORY_FOLDERS = {
    "decision": "Decisions",
    "preference": "Preferences",
    "procedural": "Procedures",
    "episodic": "Experiences",
    "semantic": "Knowledge",
}

# --- Daemon ---
DAEMON_PID_FILE = DATA_DIR / "daemon.pid"
DAEMON_LOG_FILE = DATA_DIR / "daemon.log"
DAEMON_HEARTBEAT_INTERVAL = 60  # seconds between heartbeat writes

# --- Daily Briefing ---
DAILY_BRIEFING_HOUR = 7
DAILY_BRIEFING_MINUTE = 0

# --- Conversation Archive ---
CLAUDE_PROJECTS_DIR = Path(os.path.expanduser("~")) / ".claude" / "projects"
CONVERSATION_ARCHIVE_HOUR = 2  # 2 AM daily
CONVERSATION_ARCHIVE_MAX_AGE_DAYS = 7  # only archive conversations from last N days

# --- Life Domains ---
LIFE_DOMAINS_DOC_ID = ""
LIFE_DOMAINS_AVAILABLE_HOURS_WEEK = 40  # hours available outside work/sleep

# --- Time Allocation ---
TIME_ALLOCATION_CWD_MAP = {
    "jaybrain": "JayBrain Development",
    "homelab": "Learning",
    "sigma-detection-rules": "Learning",
    "ddub227.github.io": "Career",
    "job_search": "Career",
}
TIME_ALLOCATION_IDLE_THRESHOLD_MIN = 30  # gaps > this between tool calls = idle
TIME_ALLOCATION_LOOKBACK_DAYS = 7

# --- Network Decay ---
NETWORK_DECAY_DEFAULT_DAYS = 30      # default threshold for new contacts
NETWORK_DECAY_NUDGE_DAY = "wed"      # day of week for heartbeat check
NETWORK_DECAY_NUDGE_HOUR = 9

# --- Heartbeat ---
HEARTBEAT_FORGE_DUE_THRESHOLD = 5  # notify when this many concepts are due
HEARTBEAT_APP_STALE_DAYS = 7  # flag apps sitting in "applied" this long
HEARTBEAT_SESSION_CRASH_ENABLED = False  # stalled session Telegram alerts
SECURITY_PLUS_EXAM_DATE = "2026-03-01"

# --- Feedly AI Feed ---
FEEDLY_ACCESS_TOKEN = ""  # nosec B105 -- empty default, real value from env
FEEDLY_STREAM_ID = ""
FEEDLY_POLL_INTERVAL_MINUTES = 15
FEEDLY_API_BASE = "https://cloud.feedly.com/v3"
FEEDLY_FETCH_COUNT = 20
FEEDLY_NOTIFY_THRESHOLD = 1

# --- News Feed Ingestion ---
NEWS_FEED_POLL_INTERVAL_MINUTES = 30
NEWS_FEED_HTTP_TIMEOUT = 20
NEWS_FEED_MAX_ITEMS_PER_SOURCE = 100

# --- SignalForge (Article Intelligence Engine) ---
SIGNALFORGE_ARTICLES_DIR = DATA_DIR / "articles"
SIGNALFORGE_FETCH_INTERVAL_MINUTES = 60
SIGNALFORGE_CLEANUP_HOUR = 4
SIGNALFORGE_ARTICLE_TTL_DAYS = 30
SIGNALFORGE_MAX_ARTICLE_CHARS = 15_000
SIGNALFORGE_FETCH_DELAY_BASE = 2.0
SIGNALFORGE_FETCH_DELAY_JITTER = 1.5
SIGNALFORGE_FETCH_BATCH_SIZE = 50
SIGNALFORGE_BACKOFF_MAX = 60.0

# --- Event Discovery ---
EVENT_DISCOVERY_LOCATION = "Charlotte, NC"
EVENTBRITE_API_KEY = ""

# --- Trash / Soft-Delete ---
TRASH_DIR = DATA_DIR / "trash"
TRASH_DEFAULT_RETENTION_DAYS = 30
TRASH_RETENTION_BY_CATEGORY = {
    "bytecode": 7,
    "build_artifact": 7,
    "cache": 7,
    "log": 14,
    "temp": 14,
    "source": 90,
    "config": 90,
    "general": 30,
}

# --- SSRF Protection ---
# Hosts that are allowed to bypass private-IP checks (e.g., local services you trust).
# Add entries like "192.168.1.50" or "my-homelab.local" if needed.
SSRF_ALLOWED_HOSTS: set[str] = set()

_logger = logging.getLogger(__name__)


def validate_url(url: str) -> str:
    """Validate a URL is safe to fetch (not targeting private/internal networks).

    Returns the URL unchanged if valid. Raises ValueError with a clear
    message if the URL is blocked.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Blocked request: only http/https URLs are allowed, got '{parsed.scheme}'. "
            f"URL: {url}"
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Blocked request: no hostname found in URL: {url}")

    if hostname in SSRF_ALLOWED_HOSTS:
        return url

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise ValueError(
            f"Blocked request: could not resolve hostname '{hostname}'. URL: {url}"
        )

    for family, _, _, _, sockaddr in addr_info:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(
                f"Blocked request to private/internal IP address ({ip}) "
                f"resolved from '{hostname}'. "
                f"If this is intentional, add '{hostname}' to "
                f"SSRF_ALLOWED_HOSTS in config.py."
            )

    return url

# Directories to scan for garbage files
TRASH_SCAN_DIRS = [
    PROJECT_ROOT,                                          # jaybrain itself
    Path(os.path.expanduser("~")) / "projects",            # all project repos
]

# Patterns that are always safe to auto-trash (must also be git-ignored)
TRASH_AUTO_PATTERNS = [
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
    "**/.pytest_cache",
    "**/.mypy_cache",
    "**/.ruff_cache",
    "**/htmlcov",
    "**/.coverage",
    "**/.coverage.*",
    "**/*.egg-info",
    "**/.tox",
]

# Patterns that are NEVER deleted regardless of anything else
TRASH_PROTECTED_PATTERNS = [
    "**/.git",
    "**/.git/**",
    "**/.env",
    "**/pyproject.toml",
    "**/setup.py",
    "**/setup.cfg",
    "**/LICENSE*",
    "**/Makefile",
    "**/.pre-commit-config.yaml",
    "**/CLAUDE.md",
    "**/node_modules/**",
]

# Suspicious file patterns that get flagged for review (not auto-trashed)
TRASH_SUSPECT_PATTERNS = [
    "null",             # stray null files from shell redirection
    "**/*.tmp",
    "**/*.bak",
    "**/*.orig",
    "**/*.swp",
    "**/Thumbs.db",
    "**/.DS_Store",
]


def ensure_data_dirs() -> None:
    """Create all required data directories if they don't exist."""
    init()
    DATA_DIR.mkdir(exist_ok=True)
    MEMORIES_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)
    MODELS_DIR.mkdir(exist_ok=True)
    FORGE_DIR.mkdir(exist_ok=True)
    TRASH_DIR.mkdir(exist_ok=True)
    SIGNALFORGE_ARTICLES_DIR.mkdir(exist_ok=True)
    for category in MEMORY_CATEGORIES:
        (MEMORIES_DIR / category).mkdir(exist_ok=True)
