"""Tests for hybrid search engine."""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from jaybrain.search import hybrid_search, _verify_model_hash, _ONNX_MODEL_SHA256


class TestHybridSearch:
    def test_vector_only(self):
        vec_results = [("a", 0.1), ("b", 0.5), ("c", 0.9)]
        merged = hybrid_search(vec_results, [])
        assert merged[0][0] == "a"  # Closest distance = highest similarity
        assert len(merged) == 3

    def test_keyword_only(self):
        fts_results = [("x", -5.0), ("y", -2.0), ("z", -1.0)]
        merged = hybrid_search([], fts_results)
        assert merged[0][0] == "x"  # Most negative = best BM25 match
        assert len(merged) == 3

    def test_combined_results(self):
        vec_results = [("a", 0.1), ("b", 0.5)]
        fts_results = [("b", -5.0), ("c", -2.0)]
        merged = hybrid_search(vec_results, fts_results)
        ids = [m[0] for m in merged]
        # "b" appears in both and should score well
        assert "b" in ids
        assert "a" in ids
        assert "c" in ids

    def test_empty_inputs(self):
        merged = hybrid_search([], [])
        assert merged == []

    def test_scores_bounded(self):
        vec_results = [("a", 0.0), ("b", 1.0)]
        fts_results = [("a", -10.0), ("c", -1.0)]
        merged = hybrid_search(vec_results, fts_results)
        for _, score in merged:
            assert 0.0 <= score <= 1.0

    def test_single_result(self):
        vec_results = [("only", 0.5)]
        merged = hybrid_search(vec_results, [])
        assert len(merged) == 1
        assert merged[0][0] == "only"

    def test_custom_weights(self):
        # Use multiple results so normalization produces non-zero scores
        vec_results = [("a", 0.1), ("c", 0.9)]
        fts_results = [("b", -5.0), ("d", -1.0)]
        # All vector weight: "a" has best vector score (lowest distance)
        merged_vec = hybrid_search(vec_results, fts_results, vector_weight=1.0, keyword_weight=0.0)
        # All keyword weight: "b" has best keyword score (most negative BM25)
        merged_kw = hybrid_search(vec_results, fts_results, vector_weight=0.0, keyword_weight=1.0)
        # With full vector weight, "a" should be first (it has best vector score)
        assert merged_vec[0][0] == "a"
        # With full keyword weight, "b" should be first (it has best keyword score)
        assert merged_kw[0][0] == "b"


class TestModelHashVerification:
    """Tests for ONNX model integrity check (SEC-7)."""

    def test_valid_hash_passes(self, tmp_path):
        model_file = tmp_path / "model.onnx"
        content = b"fake model content for testing"
        model_file.write_bytes(content)
        expected_hash = hashlib.sha256(content).hexdigest()
        with patch("jaybrain.search._ONNX_MODEL_SHA256", expected_hash):
            _verify_model_hash(model_file)

    def test_tampered_file_raises(self, tmp_path):
        model_file = tmp_path / "model.onnx"
        model_file.write_bytes(b"tampered content")
        with pytest.raises(RuntimeError, match="integrity check failed"):
            _verify_model_hash(model_file)

    def test_empty_file_raises(self, tmp_path):
        model_file = tmp_path / "model.onnx"
        model_file.write_bytes(b"")
        with pytest.raises(RuntimeError, match="integrity check failed"):
            _verify_model_hash(model_file)

    def test_expected_hash_is_sha256_format(self):
        assert len(_ONNX_MODEL_SHA256) == 64
        assert all(c in "0123456789abcdef" for c in _ONNX_MODEL_SHA256)
