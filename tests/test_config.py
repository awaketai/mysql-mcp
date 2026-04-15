"""Tests for mysql_mcp.config."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from mysql_mcp.config import AppConfig, MySQLConfig, OpenAIConfig


class TestMySQLConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYSQL_USER", "root")
        monkeypatch.setenv("MYSQL_PASSWORD", "secret")
        cfg = MySQLConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 3306
        assert cfg.user == "root"
        assert cfg.password == "secret"
        assert cfg.pool_min_size == 2
        assert cfg.pool_max_size == 10

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYSQL_HOST", "10.0.0.1")
        monkeypatch.setenv("MYSQL_PORT", "3307")
        monkeypatch.setenv("MYSQL_USER", "admin")
        monkeypatch.setenv("MYSQL_PASSWORD", "pw")
        monkeypatch.setenv("MYSQL_POOL_MAX_SIZE", "20")
        cfg = MySQLConfig()
        assert cfg.host == "10.0.0.1"
        assert cfg.port == 3307
        assert cfg.pool_max_size == 20

    def test_missing_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValidationError, match="MYSQL_USER"):
                MySQLConfig()


class TestOpenAIConfig:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        cfg = OpenAIConfig()
        assert cfg.api_key == "sk-test"
        assert cfg.model == "gpt-4o"
        assert cfg.base_url is None

    def test_custom_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://custom.api/v1")
        cfg = OpenAIConfig()
        assert cfg.base_url == "https://custom.api/v1"

    def test_missing_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
                OpenAIConfig()


class TestAppConfig:
    def test_full_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYSQL_USER", "root")
        monkeypatch.setenv("MYSQL_PASSWORD", "pw")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("ALLOWED_DATABASES", '["shop","analytics"]')
        monkeypatch.setenv("MAX_LIMIT", "500")
        monkeypatch.setenv("QUERY_TIMEOUT", "60")

        cfg = AppConfig()
        assert cfg.mysql.user == "root"
        assert cfg.openai.api_key == "sk-test"
        assert cfg.allowed_databases == ["shop", "analytics"]
        assert cfg.max_limit == 500
        assert cfg.query_timeout == 60

    def test_allowed_databases_single(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYSQL_USER", "root")
        monkeypatch.setenv("MYSQL_PASSWORD", "pw")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("ALLOWED_DATABASES", '["shop"]')

        cfg = AppConfig()
        assert cfg.allowed_databases == ["shop"]

    def test_allowed_databases_default_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYSQL_USER", "root")
        monkeypatch.setenv("MYSQL_PASSWORD", "pw")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        cfg = AppConfig()
        assert cfg.allowed_databases == []

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYSQL_USER", "root")
        monkeypatch.setenv("MYSQL_PASSWORD", "pw")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        cfg = AppConfig()
        assert cfg.default_database is None
        assert cfg.schema_refresh_interval == 0
        assert cfg.max_limit == 1000
        assert cfg.schema_token_budget == 4000
        assert cfg.log_level == "INFO"
