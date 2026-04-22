"""End-to-end integration tests for the query pipeline."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import AppConfig
from src.models.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    IndexInfo,
    SchemaCache,
    TableSchema,
    ViewSchema,
)
from src.tools.query import query


# ---------------------------------------------------------------------------
# Mock infrastructure
# ---------------------------------------------------------------------------


class _MockCursor:
    description = [("id",), ("name",), ("total",)]

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    async def execute(self, sql: str, params=None) -> None:
        pass

    async def fetchall(self) -> list[tuple]:
        return self._rows


class _MockConn:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    async def select_db(self, db: str) -> None:
        pass

    def cursor(self):
        rows = self._rows

        @asynccontextmanager
        async def _cm():
            yield _MockCursor(rows)

        return _cm()


class _MockPool:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def acquire(self):
        rows = self._rows

        @asynccontextmanager
        async def _cm():
            yield _MockConn(rows)

        return _cm()


def _make_ctx(
    config: AppConfig,
    cache: SchemaCache,
    pool: _MockPool,
    llm_sql: str,
) -> MagicMock:
    schema_manager = MagicMock()
    schema_manager.cache = cache

    llm_client = AsyncMock()
    llm_client.generate_sql = AsyncMock(return_value=llm_sql)
    llm_client.verify_result = AsyncMock(return_value=True)

    ctx = MagicMock()
    ctx.lifespan_context = {
        "config": config,
        "pool": pool,
        "schema_manager": schema_manager,
        "llm_client": llm_client,
    }
    return ctx


def _shop_cache() -> SchemaCache:
    return SchemaCache(
        databases={
            "shop": DatabaseSchema(
                name="shop",
                tables={
                    "users": TableSchema(
                        name="users",
                        columns=[
                            ColumnInfo(name="id", type="int", auto_increment=True),
                            ColumnInfo(name="name", type="varchar(100)", comment="user name"),
                            ColumnInfo(name="status", type="enum('active','inactive')"),
                        ],
                        indexes=[IndexInfo(name="PRIMARY", columns=["id"], unique=True)],
                        comment="user table",
                    ),
                    "orders": TableSchema(
                        name="orders",
                        columns=[
                            ColumnInfo(name="id", type="int", auto_increment=True),
                            ColumnInfo(name="user_id", type="int"),
                            ColumnInfo(name="total", type="decimal(10,2)"),
                            ColumnInfo(name="created_at", type="datetime"),
                        ],
                        foreign_keys=[
                            ForeignKeyInfo(
                                name="fk_user",
                                columns=["user_id"],
                                ref_table="users",
                                ref_columns=["id"],
                            )
                        ],
                        comment="order table",
                    ),
                    "products": TableSchema(
                        name="products",
                        columns=[
                            ColumnInfo(name="id", type="int"),
                            ColumnInfo(name="name", type="varchar(200)"),
                            ColumnInfo(name="price", type="decimal(10,2)"),
                        ],
                        comment="product catalog",
                    ),
                },
                views={
                    "active_users": ViewSchema(
                        name="active_users",
                        columns=[ColumnInfo(name="id", type="int"), ColumnInfo(name="name", type="varchar(100)")],
                        definition="SELECT id, name FROM users WHERE status='active'",
                    ),
                },
            ),
        },
        table_index={
            "users": ["shop"],
            "orders": ["shop"],
            "products": ["shop"],
            "active_users": ["shop"],
        },
    )


@pytest.fixture()
def app_config(monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    monkeypatch.setenv("MYSQL_USER", "test")
    monkeypatch.setenv("MYSQL_PASSWORD", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DEFAULT_DATABASE", "shop")
    return AppConfig()


# ---------------------------------------------------------------------------
# E2E tests
# ---------------------------------------------------------------------------


class TestSimpleQuery:
    @pytest.mark.asyncio()
    async def test_basic_select(self, app_config: AppConfig) -> None:
        cache = _shop_cache()
        pool = _MockPool([(1, "Alice", "active"), (2, "Bob", "active")])
        ctx = _make_ctx(app_config, cache, pool, "SELECT id, name FROM users LIMIT 100")

        result = await query(natural_language="show all users", ctx=ctx)

        assert result["database"] == "shop"
        assert result["row_count"] == 2
        assert "SELECT" in result["sql"]

    @pytest.mark.asyncio()
    async def test_explicit_database(self, app_config: AppConfig) -> None:
        cache = _shop_cache()
        pool = _MockPool([(1, "Widget", 9.99)])
        ctx = _make_ctx(app_config, cache, pool, "SELECT * FROM products LIMIT 10")

        result = await query(
            natural_language="show products",
            database="shop",
            return_type="sql",
            ctx=ctx,
        )

        assert result["database"] == "shop"
        assert "explanation" in result
        assert "columns" not in result  # sql mode


class TestJoinQuery:
    @pytest.mark.asyncio()
    async def test_join_query(self, app_config: AppConfig) -> None:
        cache = _shop_cache()
        pool = _MockPool([(1, "Alice", 99.50)])
        join_sql = (
            "SELECT u.name, o.total FROM users u "
            "JOIN orders o ON u.id = o.user_id LIMIT 100"
        )
        ctx = _make_ctx(app_config, cache, pool, join_sql)

        result = await query(
            natural_language="show user names with their order totals",
            ctx=ctx,
        )

        assert result["row_count"] == 1
        assert "JOIN" in result["sql"]


class TestAggregationQuery:
    @pytest.mark.asyncio()
    async def test_count_query(self, app_config: AppConfig) -> None:
        cache = _shop_cache()
        pool = _MockPool([(42,)])
        ctx = _make_ctx(
            app_config, cache, pool,
            "SELECT COUNT(*) AS total FROM users LIMIT 1",
        )

        result = await query(
            natural_language="how many users are there",
            return_type="both",
            ctx=ctx,
        )

        assert "COUNT" in result["sql"]
        assert result["row_count"] == 1
        assert "explanation" in result
        assert "columns" in result


class TestRetryFlow:
    @pytest.mark.asyncio()
    async def test_retry_on_bad_sql_then_succeed(self, app_config: AppConfig) -> None:
        cache = _shop_cache()
        pool = _MockPool([(1, "Alice")])
        ctx = _make_ctx(app_config, cache, pool, "SELECT id FROM users LIMIT 10")

        llm = ctx.lifespan_context["llm_client"]
        llm.generate_sql = AsyncMock(side_effect=[
            "INSERT INTO users VALUES (1)",  # rejected
            "DELETE FROM users",  # rejected
            "SELECT id, name FROM users LIMIT 10",  # success
        ])

        result = await query(natural_language="show users", ctx=ctx)

        assert result["row_count"] == 1
        assert llm.generate_sql.call_count == 3

    @pytest.mark.asyncio()
    async def test_all_retries_fail(self, app_config: AppConfig) -> None:
        cache = _shop_cache()
        pool = _MockPool([])
        ctx = _make_ctx(app_config, cache, pool, "DROP TABLE users")

        llm = ctx.lifespan_context["llm_client"]
        llm.generate_sql = AsyncMock(return_value="DROP TABLE users")

        result = await query(natural_language="delete everything", ctx=ctx)

        assert result["error"] == "max_retries_exceeded"
        assert llm.generate_sql.call_count == 3


class TestDatabaseResolution:
    @pytest.mark.asyncio()
    async def test_infer_from_table_in_input(self, app_config: AppConfig) -> None:
        cache = _shop_cache()
        pool = _MockPool([(1,)])
        ctx = _make_ctx(app_config, cache, pool, "SELECT COUNT(*) FROM orders LIMIT 1")

        result = await query(natural_language="count all orders", ctx=ctx)

        assert result["database"] == "shop"

    @pytest.mark.asyncio()
    async def test_no_database_no_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYSQL_USER", "test")
        monkeypatch.setenv("MYSQL_PASSWORD", "test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        config = AppConfig()  # no DEFAULT_DATABASE

        cache = SchemaCache(databases={"shop": DatabaseSchema(name="shop")})
        pool = _MockPool([])
        ctx = _make_ctx(config, cache, pool, "SELECT 1")

        result = await query(natural_language="show something", ctx=ctx)

        assert result["error"] == "database_required"
