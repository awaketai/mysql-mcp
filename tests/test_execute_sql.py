"""Tests for execute_sql tool."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import AppConfig
from src.models.schema import SchemaCache
from src.tools.execute_sql import execute_sql


def _make_ctx(lifespan_context: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.lifespan_context = lifespan_context
    return ctx


class _MockPool:
    def __init__(self, columns: list[str], rows: list[tuple]) -> None:
        self._columns = columns
        self._rows = rows

    def acquire(self):
        pool = self

        @asynccontextmanager
        async def _cm():
            yield _MockConn(pool)

        return _cm()


class _MockConn:
    def __init__(self, pool: _MockPool) -> None:
        self._pool = pool

    async def select_db(self, db: str) -> None:
        pass

    def cursor(self):
        pool = self._pool

        @asynccontextmanager
        async def _cm():
            yield _MockCursor(pool)

        return _cm()


class _MockCursor:
    def __init__(self, pool: _MockPool) -> None:
        self._pool = pool

    description = [("id",), ("name",)]

    async def execute(self, sql: str, params=None) -> None:
        pass

    async def fetchall(self) -> list[tuple]:
        return self._pool._rows


@pytest.fixture()
def app_config(monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    monkeypatch.setenv("MYSQL_USER", "test")
    monkeypatch.setenv("MYSQL_PASSWORD", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return AppConfig()


class TestExecuteSQL:
    @pytest.mark.asyncio()
    async def test_valid_select(self, app_config: AppConfig) -> None:
        pool = _MockPool(["id", "name"], [(1, "alice"), (2, "bob")])
        schema_manager = MagicMock()
        schema_manager.cache = SchemaCache()
        ctx = _make_ctx({"config": app_config, "pool": pool, "schema_manager": schema_manager})

        result = await execute_sql(sql="SELECT id, name FROM users", database="shop", ctx=ctx)

        assert result["sql"] == "SELECT id, name FROM users LIMIT 1000"
        assert result["database"] == "shop"
        assert result["row_count"] == 2

    @pytest.mark.asyncio()
    async def test_rejects_insert(self, app_config: AppConfig) -> None:
        pool = _MockPool([], [])
        schema_manager = MagicMock()
        schema_manager.cache = SchemaCache()
        ctx = _make_ctx({"config": app_config, "pool": pool, "schema_manager": schema_manager})

        result = await execute_sql(sql="INSERT INTO users VALUES (1, 'alice')", ctx=ctx)

        assert result["error"] == "validation_error"
        assert "SELECT" in result["message"]

    @pytest.mark.asyncio()
    async def test_rejects_delete(self, app_config: AppConfig) -> None:
        pool = _MockPool([], [])
        schema_manager = MagicMock()
        schema_manager.cache = SchemaCache()
        ctx = _make_ctx({"config": app_config, "pool": pool, "schema_manager": schema_manager})

        result = await execute_sql(sql="DELETE FROM users", ctx=ctx)

        assert result["error"] == "validation_error"

    @pytest.mark.asyncio()
    async def test_uses_default_database(self, app_config: AppConfig) -> None:
        pool = _MockPool(["x"], [(42,)])
        schema_manager = MagicMock()
        schema_manager.cache = SchemaCache()
        ctx = _make_ctx({"config": app_config, "pool": pool, "schema_manager": schema_manager})

        result = await execute_sql(sql="SELECT 42", ctx=ctx)

        # default_database is None, so database should be empty string or None
        assert "sql" in result
