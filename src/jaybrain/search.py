"""Hybrid search engine combining vector similarity and FTS5 keyword search."""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path
from typing import Optional

import numpy as np

from .config import (
    EMBEDDING_DIM,
    MODELS_DIR,
    ONNX_MODEL_URL,
    TOKENIZER_NAME,
    VECTOR_WEIGHT,
    KEYWORD_WEIGHT,
    SEARCH_CANDIDATES,
)

logger = logging.getLogger(__name__)

# Lazy-loaded globals for embedding model
_tokenizer = None
_ort_session = None

# Expected SHA-256 of the ONNX model binary (all-MiniLM-L6-v2).
# Update this hash if upgrading to a new model version.
_ONNX_MODEL_SHA256 = "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"


def _verify_model_hash(model_path: Path) -> None:
    """Verify the ONNX model file matches the expected SHA-256 hash."""
    sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if sha256 != _ONNX_MODEL_SHA256:
        raise RuntimeError(
            f"ONNX model integrity check failed.\n"
            f"Expected SHA-256: {_ONNX_MODEL_SHA256}\n"
            f"Got:              {sha256}\n"
            f"The model file at {model_path} may be corrupted or tampered with. "
            f"Delete it and restart to re-download, or update _ONNX_MODEL_SHA256 "
            f"in search.py if you intentionally upgraded the model."
        )


def _ensure_model_downloaded() -> Path:
    """Download the ONNX model if not already present, with integrity check."""
    model_path = MODELS_DIR / "model.onnx"
    if model_path.exists():
        _verify_model_hash(model_path)
        return model_path

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading embedding model (one-time, ~80MB)...", file=sys.stderr)

    import requests

    response = requests.get(ONNX_MODEL_URL, stream=True, timeout=120)
    response.raise_for_status()

    with open(model_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    _verify_model_hash(model_path)
    print("Embedding model downloaded and verified.", file=sys.stderr)
    return model_path


def _load_tokenizer():
    """Load the tokenizer (fast, Rust-based)."""
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer

    from tokenizers import Tokenizer

    _tokenizer = Tokenizer.from_pretrained(TOKENIZER_NAME)
    return _tokenizer


def _load_ort_session():
    """Load the ONNX Runtime session (lazy, ~2-3s first time)."""
    global _ort_session
    if _ort_session is not None:
        return _ort_session

    import onnxruntime as ort

    model_path = _ensure_model_downloaded()
    _ort_session = ort.InferenceSession(
        str(model_path),
        providers=["CPUExecutionProvider"],
    )
    return _ort_session


def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for the given text.

    Uses ONNX Runtime + tokenizers for fast inference.
    Returns a list of 384 floats (all-MiniLM-L6-v2 dimensions).
    """
    tokenizer = _load_tokenizer()
    session = _load_ort_session()

    # Tokenize
    encoded = tokenizer.encode(text)
    input_ids = encoded.ids
    attention_mask = encoded.attention_mask

    # Pad/truncate to max length 128 (model's trained max is 256, but 128 is enough for memories)
    max_len = 128
    input_ids = input_ids[:max_len]
    attention_mask = attention_mask[:max_len]

    # Pad if shorter
    pad_len = max_len - len(input_ids)
    input_ids = input_ids + [0] * pad_len
    attention_mask = attention_mask + [0] * pad_len

    # Create token_type_ids (all zeros for single sentence)
    token_type_ids = [0] * max_len

    # Run inference
    inputs = {
        "input_ids": np.array([input_ids], dtype=np.int64),
        "attention_mask": np.array([attention_mask], dtype=np.int64),
        "token_type_ids": np.array([token_type_ids], dtype=np.int64),
    }
    outputs = session.run(None, inputs)

    # Mean pooling over token embeddings (output[0] is last_hidden_state)
    token_embeddings = outputs[0]  # shape: (1, seq_len, 384)
    mask = np.array([attention_mask], dtype=np.float32).reshape(1, max_len, 1)
    masked = token_embeddings * mask
    summed = masked.sum(axis=1)
    counts = mask.sum(axis=1)
    mean_pooled = summed / np.maximum(counts, 1e-9)

    # Normalize to unit vector
    embedding = mean_pooled[0]
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding.tolist()


def hybrid_search(
    vec_results: list[tuple[str, float]],
    fts_results: list[tuple[str, float]],
    vector_weight: float = VECTOR_WEIGHT,
    keyword_weight: float = KEYWORD_WEIGHT,
) -> list[tuple[str, float]]:
    """Merge vector and keyword search results with weighted scoring.

    Args:
        vec_results: List of (id, distance) from vector search. Lower distance = more similar.
        fts_results: List of (id, bm25_score) from FTS5. More negative = better match.
        vector_weight: Weight for vector similarity (default 0.7).
        keyword_weight: Weight for keyword match (default 0.3).

    Returns:
        Merged list of (id, combined_score) sorted by score descending (higher = better).
    """
    scores: dict[str, dict[str, float]] = {}

    # Normalize vector scores: convert distance to similarity (0-1 range)
    if vec_results:
        max_dist = max(d for _, d in vec_results) if vec_results else 1.0
        max_dist = max(max_dist, 1e-9)
        for mem_id, distance in vec_results:
            sim = 1.0 - (distance / (max_dist + 1e-9))
            sim = max(0.0, min(1.0, sim))
            scores.setdefault(mem_id, {"vec": 0.0, "fts": 0.0})
            scores[mem_id]["vec"] = sim

    # Normalize FTS scores: BM25 returns negative scores (more negative = better)
    if fts_results:
        min_score = min(s for _, s in fts_results)
        max_score = max(s for _, s in fts_results)
        score_range = max_score - min_score if max_score != min_score else 1.0
        for mem_id, bm25_score in fts_results:
            # Invert: most negative becomes 1.0
            normalized = (max_score - bm25_score) / score_range
            normalized = max(0.0, min(1.0, normalized))
            scores.setdefault(mem_id, {"vec": 0.0, "fts": 0.0})
            scores[mem_id]["fts"] = normalized

    # Combine with weights
    combined = []
    for mem_id, parts in scores.items():
        final = vector_weight * parts["vec"] + keyword_weight * parts["fts"]
        combined.append((mem_id, final))

    # Sort descending by score
    combined.sort(key=lambda x: x[1], reverse=True)
    return combined
