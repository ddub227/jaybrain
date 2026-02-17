"""Paths, constants, and data directory setup."""

import os
from pathlib import Path

# Base directories
PROJECT_ROOT = Path(__file__).parent.parent.parent
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
    os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS",
        os.path.expanduser("~/.config/gcloud/jaybrain-service-account.json"),
    )
)
OAUTH_CLIENT_PATH = Path(
    os.path.expanduser("~/.config/gcloud/jaybrain-oauth-client.json")
)
OAUTH_TOKEN_PATH = Path(
    os.path.expanduser("~/.config/gcloud/jaybrain-oauth-token.json")
)
GDOC_SHARE_EMAIL = os.environ.get("GDOC_SHARE_EMAIL", "joshuajbudd@gmail.com")
GDOC_FOLDER_ID = os.environ.get("GDOC_FOLDER_ID", "1_Vk6Vkhf0uihe2vN_-O853p1BYW8rI0v")
HOMELAB_TOOLS_SHEET_ID = "1VHNuKH4EHXBBECyvwMowD_uRGVWOlsggh35KDjHEIRw"
SHEETS_INDEX_ID = os.environ.get(
    "SHEETS_INDEX_ID", "1OCne8ngh2u272n-nwiXWya4VCI6mP3M4iLKIGqzQej8"
)

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
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
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
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_AUTHORIZED_USER = int(os.environ.get("TELEGRAM_AUTHORIZED_USER", "6017902047"))
TELEGRAM_POLL_TIMEOUT = 30
TELEGRAM_API_BASE = "https://api.telegram.org/bot"
TELEGRAM_MAX_MESSAGE_LEN = 4096
TELEGRAM_RATE_LIMIT_WINDOW = 60
TELEGRAM_RATE_LIMIT_MAX = 20
TELEGRAM_HISTORY_LIMIT = 30
TELEGRAM_MAX_RESPONSE_TOKENS = 2048
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GRAMCRACKER_CLAUDE_MODEL = os.environ.get("GRAMCRACKER_CLAUDE_MODEL", "claude-sonnet-4-20250514")

# Homelab project paths (file-based, not in SQLite)
HOMELAB_ROOT = Path(os.path.expanduser("~")) / "projects" / "homelab"
HOMELAB_NOTES_DIR = HOMELAB_ROOT / "notes"
HOMELAB_JOURNAL_DIR = HOMELAB_NOTES_DIR / "Journal"
HOMELAB_JOURNAL_INDEX = HOMELAB_JOURNAL_DIR / "JOURNAL_INDEX.md"
HOMELAB_CODEX_PATH = HOMELAB_NOTES_DIR / "LABSCRIBE_CODEX.md"
HOMELAB_NEXUS_PATH = HOMELAB_NOTES_DIR / "LAB_NEXUS.md"
HOMELAB_TOOLS_CSV = HOMELAB_ROOT / "HOMELAB_TOOLS_INVENTORY.csv"
HOMELAB_ATTACHMENTS_DIR = HOMELAB_JOURNAL_DIR / "attachments"
HOMELAB_JOURNAL_FILENAME = "JJ Budd's Learn Out Loud Lab_{date}.md"


def ensure_data_dirs() -> None:
    """Create all required data directories if they don't exist."""
    DATA_DIR.mkdir(exist_ok=True)
    MEMORIES_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)
    MODELS_DIR.mkdir(exist_ok=True)
    FORGE_DIR.mkdir(exist_ok=True)
    for category in MEMORY_CATEGORIES:
        (MEMORIES_DIR / category).mkdir(exist_ok=True)
