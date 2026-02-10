"""Paths, constants, and data directory setup."""

import os
from pathlib import Path

# Base directories
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "jaybrain.db"
MEMORIES_DIR = DATA_DIR / "memories"
SESSIONS_DIR = DATA_DIR / "sessions"
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
GDOC_FOLDER_ID = os.environ.get("GDOC_FOLDER_ID", "1WUi1Ty1ghheHQPdQhbieLp5NN2Jt1CJt")

# Scraping constants
SCRAPE_TIMEOUT = 30  # seconds
SCRAPE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
SCRAPE_MAX_PAGES = 3  # default pagination pages to follow

# Embedding model
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
ONNX_MODEL_URL = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx"
TOKENIZER_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Memory decay constants
DECAY_PERIOD_DAYS = 365
MIN_DECAY = 0.1
ACCESS_REINFORCEMENT = 0.05
MAX_REINFORCEMENT = 0.4
RECENCY_BOOST_DAYS = 90

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


def ensure_data_dirs() -> None:
    """Create all required data directories if they don't exist."""
    DATA_DIR.mkdir(exist_ok=True)
    MEMORIES_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)
    MODELS_DIR.mkdir(exist_ok=True)
    FORGE_DIR.mkdir(exist_ok=True)
    for category in MEMORY_CATEGORIES:
        (MEMORIES_DIR / category).mkdir(exist_ok=True)
