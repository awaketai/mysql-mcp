"""Tests for query tool — the core NL-to-SQL pipeline."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import AppConfig
from src.models.schema import (
    ColumnInfo,
    DatabaseSchema,
    SchemaCache,
    TableSchema,
)
from src.tools.query import query


def _make_ctx(lifespan_context: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.lifespan_context = lifespan_context
    return ctx


# ---------------------------------------------------------------------------
# Mock pool (reusable)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_config(monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    monkeypatch.setenv("MYSQL_USER", "test")
    monkeypatch.setenv("MYSQL_PASSWORD", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DEFAULT_DATABASE", "shop")
    return AppConfig()


@pytest.fixture()
def schema_cache() -> SchemaCache:
    return SchemaCache(
        databases={
            "shop": DatabaseSchema(
                name="shop",
                tables={
                    "users": TableSchema(
                        name="users",
                        columns=[
                            ColumnInfo(name="id", type="int"),
                            ColumnInfo(name="name", type="varchar(100)"),
                        ],
                        comment="user table",
                    ),
                },
            ),
        },
        table_index={"users": ["shop"]},
    )


def _make_full_ctx(
    app_config: AppConfig,
    schema_cache: SchemaCache,
    pool: _MockPool,
    generated_sql: str = "SELECT id, name FROM users LIMIT 100",
) -> MagicMock:
    schema_manager = MagicMock()
    schema_manager.cache = schema_cache

    llm_client = AsyncMock()
    llm_client.generate_sql = AsyncMock(return_value=generated_sql)
    llm_client.verify_result = AsyncMock(return_value=True)

    return _make_ctx({
        "config": app_config,
        "pool": pool,
        "schema_manager": schema_manager,
        "llm_client": llm_client,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestQueryReturnType:
    @pytest.mark.asyncio()
    async def test_result_mode(
        self, app_config: AppConfig, schema_cache: SchemaCache,
    ) -> None:
        pool = _MockPool(["id", "name"], [(1, "alice"), (2, "bob")])
        ctx = _make_full_ctx(app_config, schema_cache, pool)

        result = await query(
            natural_language="show me all users",
            return_type="result",
            ctx=ctx,
        )

        assert "sql" in result
        assert result["database"] == "shop"
        assert result["row_count"] == 2
        assert "columns" in result

    @pytest.mark.asyncio()
    async def test_sql_mode(
        self, app_config: AppConfig, schema_cache: SchemaCache,
    ) -> None:
        pool = _MockPool(["id"], [(1,)])
        ctx = _make_full_ctx(app_config, schema_cache, pool)

        result = await query(
            natural_language="show me all users",
            return_type="sql",
            ctx=ctx,
        )

        assert "sql" in result
        assert "explanation" in result
        assert "columns" not in result

    @pytest.mark.asyncio()
    async def test_both_mode(
        self, app_config: AppConfig, schema_cache: SchemaCache,
    ) -> None:
        pool = _MockPool(["id", "name"], [(1, "alice")])
        ctx = _make_full_ctx(app_config, schema_cache, pool)

        result = await query(
            natural_language="show me all users",
            return_type="both",
            ctx=ctx,
        )

        assert "sql" in result
        assert "explanation" in result
        assert "columns" in result
        assert "rows" in result


class TestQueryDatabaseResolution:
    @pytest.mark.asyncio()
    async def test_explicit_database(
        self, app_config: AppConfig, schema_cache: SchemaCache,
    ) -> None:
        pool = _MockPool(["id"], [(1,)])
        ctx = _make_full_ctx(app_config, schema_cache, pool)

        result = await query(
            natural_language="show all users",
            database="shop",
            ctx=ctx,
        )

        assert result["database"] == "shop"

    @pytest.mark.asyncio()
    async def test_inferred_from_table_name(
        self, app_config: AppConfig, schema_cache: SchemaCache,
    ) -> None:
        pool = _MockPool(["id"], [(1,)])
        ctx = _make_full_ctx(app_config, schema_cache, pool)

        result = await query(
            natural_language="show all from users",
            ctx=ctx,
        )

        # "users" is in table_index → ["shop"]
        assert result["database"] == "shop"

    @pytest.mark.asyncio()
    async def test_no_database_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYSQL_USER", "test")
        monkeypatch.setenv("MYSQL_PASSWORD", "test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # No DEFAULT_DATABASE
        config = AppConfig()

        cache = SchemaCache(databases={"shop": DatabaseSchema(name="shop")})
        pool = _MockPool(["id"], [(1,)])
        schema_manager = MagicMock()
        schema_manager.cache = cache

        ctx = _make_ctx({
            "config": config,
            "pool": pool,
            "schema_manager": schema_manager,
            "llm_client": AsyncMock(),
        })

        result = await query(
            natural_language="show something that matches nothing",
            ctx=ctx,
        )

        assert result["error"] == "database_required"


class TestQueryRetry:
    @pytest.mark.asyncio()
    async def test_retries_on_bad_sql_then_succeeds(
        self, app_config: AppConfig, schema_cache: SchemaCache,
    ) -> None:
        pool = _MockPool(["id"], [(1,)])
        ctx = _make_full_ctx(app_config, schema_cache, pool)

        llm_client = ctx.lifespan_context["llm_client"]
        # First: return INSERT (will be rejected), second: return valid SELECT
        llm_client.generate_sql = AsyncMock(
            side_effect=[
                "INSERT INTO users VALUES (1)",
                "SELECT id FROM users LIMIT 10",
            ]
        )

        result = await query(
            natural_language="show users",
            ctx=ctx,
        )

        assert "sql" in result
        assert result["sql"].startswith("SELECT")
        assert llm_client.generate_sql.call_count == 2

    @pytest.mark.asyncio()
    async def test_max_retries_exhausted(
        self, app_config: AppConfig, schema_cache: SchemaCache,
    ) -> None:
        pool = _MockPool(["id"], [(1,)])
        ctx = _make_full_ctx(app_config, schema_cache, pool)

        llm_client = ctx.lifespan_context["llm_client"]
        llm_client.generate_sql = AsyncMock(return_value="DROP TABLE users")

        result = await query(
            natural_language="show users",
            ctx=ctx,
        )

        assert result["error"] == "max_retries_exceeded"
        assert llm_client.generate_sql.call_count == 3
