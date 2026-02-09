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


def ensure_data_dirs() -> None:
    """Create all required data directories if they don't exist."""
    DATA_DIR.mkdir(exist_ok=True)
    MEMORIES_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)
    MODELS_DIR.mkdir(exist_ok=True)
    for category in MEMORY_CATEGORIES:
        (MEMORIES_DIR / category).mkdir(exist_ok=True)
