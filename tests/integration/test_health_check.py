"""Integration tests for health_check tool."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from mysql_mcp.config import AppConfig
from mysql_mcp.tools.health_check import health_check


class _MockCursor:
    description = [("1",)]

    async def execute(self, sql: str, params=None) -> None:
        pass

    async def fetchone(self) -> tuple:
        return (1,)


class _MockConn:
    def __init__(self, should_fail: bool = False) -> None:
        self._should_fail = should_fail

    async def select_db(self, db: str) -> None:
        pass

    def cursor(self):
        should_fail = self._should_fail

        @asynccontextmanager
        async def _cm():
            if should_fail:
                raise Exception("connection lost")
            yield _MockCursor()

        return _cm()


class _HealthyPool:
    def acquire(self):
        @asynccontextmanager
        async def _cm():
            yield _MockConn(should_fail=False)

        return _cm()


class _UnhealthyPool:
    def acquire(self):
        @asynccontextmanager
        async def _cm():
            yield _MockConn(should_fail=True)

        return _cm()


def _make_ctx(config: AppConfig, pool: object) -> MagicMock:
    schema_manager = MagicMock()
    ctx = MagicMock()
    ctx.lifespan_context = {
        "config": config,
        "pool": pool,
        "schema_manager": schema_manager,
        "llm_client": AsyncMock(),
    }
    return ctx


@pytest.fixture()
def app_config(monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    monkeypatch.setenv("MYSQL_USER", "test")
    monkeypatch.setenv("MYSQL_PASSWORD", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return AppConfig()


class TestHealthCheck:
    @pytest.mark.asyncio()
    async def test_healthy(self, app_config: AppConfig) -> None:
        ctx = _make_ctx(app_config, _HealthyPool())
        result = await health_check(ctx)

        assert result["status"] == "healthy"
        assert result["mysql"]["ok"] is True
        assert result["openai_config"]["ok"] is True

    @pytest.mark.asyncio()
    async def test_mysql_down(self, app_config: AppConfig) -> None:
        ctx = _make_ctx(app_config, _UnhealthyPool())
        result = await health_check(ctx)

        assert result["status"] == "unhealthy"
        assert result["mysql"]["ok"] is False
        assert "error" in result["mysql"]

    @pytest.mark.asyncio()
    async def test_openai_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Config with empty api_key — can't create AppConfig without it,
        # so we test by checking the logic directly
        monkeypatch.setenv("MYSQL_USER", "test")
        monkeypatch.setenv("MYSQL_PASSWORD", "test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        config = AppConfig()

        # Manually clear the key to simulate missing config
        config.openai.api_key = ""

        ctx = _make_ctx(config, _HealthyPool())
        result = await health_check(ctx)

        assert result["openai_config"]["ok"] is False
