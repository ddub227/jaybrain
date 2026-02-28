"""Tests for the config module (paths, constants, data dirs)."""

import socket
from unittest.mock import patch

import pytest
from pathlib import Path

from jaybrain.config import (
    ensure_data_dirs,
    validate_url,
    SSRF_ALLOWED_HOSTS,
    MEMORY_CATEGORIES,
    FORGE_CATEGORIES,
    FORGE_INTERVALS,
    FORGE_MASTERY_LEVELS,
    FORGE_MASTERY_DELTAS_V2,
    FORGE_BLOOM_LEVELS,
    FORGE_ERROR_TYPES,
    GRAPH_ENTITY_TYPES,
    GRAPH_RELATIONSHIP_TYPES,
    EMBEDDING_DIM,
)
import jaybrain.config as config


class TestEnsureDataDirs:
    def test_creates_directories(self, temp_data_dir):
        ensure_data_dirs()
        assert config.DATA_DIR.exists()
        assert config.MEMORIES_DIR.exists()
        assert config.SESSIONS_DIR.exists()
        assert config.MODELS_DIR.exists()
        assert config.FORGE_DIR.exists()

    def test_creates_category_subdirs(self, temp_data_dir):
        ensure_data_dirs()
        for cat in MEMORY_CATEGORIES:
            assert (config.MEMORIES_DIR / cat).exists()

    def test_idempotent(self, temp_data_dir):
        ensure_data_dirs()
        ensure_data_dirs()
        assert config.DATA_DIR.exists()


class TestConstants:
    def test_memory_categories(self):
        assert "semantic" in MEMORY_CATEGORIES
        assert "episodic" in MEMORY_CATEGORIES
        assert "procedural" in MEMORY_CATEGORIES
        assert "decision" in MEMORY_CATEGORIES
        assert "preference" in MEMORY_CATEGORIES

    def test_forge_categories(self):
        assert "python" in FORGE_CATEGORIES
        assert "security" in FORGE_CATEGORIES
        assert "general" in FORGE_CATEGORIES

    def test_forge_intervals_ascending(self):
        keys = sorted(FORGE_INTERVALS.keys())
        values = [FORGE_INTERVALS[k] for k in keys]
        for i in range(len(values) - 1):
            assert values[i] < values[i + 1]

    def test_forge_mastery_levels_ascending(self):
        thresholds = [t for _, t in FORGE_MASTERY_LEVELS]
        for i in range(len(thresholds) - 1):
            assert thresholds[i] < thresholds[i + 1]

    def test_mastery_deltas_v2_quadrants(self):
        assert FORGE_MASTERY_DELTAS_V2["correct_confident"] > 0
        assert FORGE_MASTERY_DELTAS_V2["correct_unsure"] > 0
        assert FORGE_MASTERY_DELTAS_V2["incorrect_confident"] < 0
        assert FORGE_MASTERY_DELTAS_V2["incorrect_unsure"] < 0
        assert FORGE_MASTERY_DELTAS_V2["skipped"] == 0

    def test_bloom_levels_order(self):
        assert FORGE_BLOOM_LEVELS == ["remember", "understand", "apply", "analyze"]

    def test_error_types(self):
        assert set(FORGE_ERROR_TYPES) == {"slip", "lapse", "mistake", "misconception"}

    def test_graph_entity_types(self):
        assert "person" in GRAPH_ENTITY_TYPES
        assert "project" in GRAPH_ENTITY_TYPES
        assert "tool" in GRAPH_ENTITY_TYPES

    def test_graph_relationship_types(self):
        assert "uses" in GRAPH_RELATIONSHIP_TYPES
        assert "depends_on" in GRAPH_RELATIONSHIP_TYPES

    def test_embedding_dim(self):
        assert EMBEDDING_DIM == 384


class TestValidateUrl:
    """Tests for SSRF protection (SEC-3)."""

    def test_allows_http(self):
        url = "http://example.com/page"
        assert validate_url(url) == url

    def test_allows_https(self):
        url = "https://example.com/page"
        assert validate_url(url) == url

    def test_blocks_ftp_scheme(self):
        with pytest.raises(ValueError, match="only http/https"):
            validate_url("ftp://evil.com/file")

    def test_blocks_file_scheme(self):
        with pytest.raises(ValueError, match="only http/https"):
            validate_url("file:///etc/passwd")

    def test_blocks_javascript_scheme(self):
        with pytest.raises(ValueError, match="only http/https"):
            validate_url("javascript:alert(1)")

    def test_blocks_empty_scheme(self):
        with pytest.raises(ValueError, match="only http/https"):
            validate_url("://example.com")

    def test_blocks_no_hostname(self):
        with pytest.raises(ValueError, match="no hostname"):
            validate_url("http://")

    def test_blocks_loopback_ipv4(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, 0, 0, "", ("127.0.0.1", 0)),
            ]
            with pytest.raises(ValueError, match="private/internal"):
                validate_url("http://localhost/admin")

    def test_blocks_private_10_range(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, 0, 0, "", ("10.0.0.1", 0)),
            ]
            with pytest.raises(ValueError, match="private/internal"):
                validate_url("http://internal.corp/api")

    def test_blocks_private_192_168_range(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, 0, 0, "", ("192.168.1.100", 0)),
            ]
            with pytest.raises(ValueError, match="private/internal"):
                validate_url("http://myrouter.local/config")

    def test_blocks_private_172_range(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, 0, 0, "", ("172.16.0.5", 0)),
            ]
            with pytest.raises(ValueError, match="private/internal"):
                validate_url("http://k8s-internal.local/")

    def test_blocks_link_local(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, 0, 0, "", ("169.254.169.254", 0)),
            ]
            with pytest.raises(ValueError, match="private/internal"):
                validate_url("http://metadata.google.internal/")

    def test_blocks_unresolvable_hostname(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("not found")):
            with pytest.raises(ValueError, match="could not resolve"):
                validate_url("http://doesnotexist.invalid/page")

    def test_allows_public_ip(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (socket.AF_INET, 0, 0, "", ("93.184.216.34", 0)),
            ]
            result = validate_url("http://example.com/page")
            assert result == "http://example.com/page"

    def test_ssrf_allowed_hosts_bypass(self, monkeypatch):
        monkeypatch.setattr(config, "SSRF_ALLOWED_HOSTS", {"trusted.local"})
        result = validate_url("http://trusted.local/api")
        assert result == "http://trusted.local/api"

    def test_ssrf_allowed_hosts_no_dns_check(self, monkeypatch):
        monkeypatch.setattr(config, "SSRF_ALLOWED_HOSTS", {"trusted.local"})
        with patch("socket.getaddrinfo") as mock_dns:
            validate_url("http://trusted.local/api")
            mock_dns.assert_not_called()
