"""Tests for mysql_mcp.db.schema."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from mysql_mcp.config import AppConfig
from mysql_mcp.db.schema import SchemaManager, _parse_enum_values, _tokenize
from mysql_mcp.models.schema import (
    ColumnInfo,
    DatabaseSchema,
    ForeignKeyInfo,
    SchemaCache,
    TableSchema,
)


# ---------------------------------------------------------------------------
# Mock helpers — simulate aiomysql pool with canned query results
# ---------------------------------------------------------------------------


class _MockCursor:
    """Cursor that returns canned rows based on SQL substring matching."""

    description = [("col",)]

    def __init__(self, results: dict[str, list[tuple]]) -> None:
        self._results = results
        self._rows: list[tuple] = []

    async def execute(self, sql: str, params=None) -> None:
        self._rows = []
        for key, rows in self._results.items():
            if key in sql:
                self._rows = rows
                return
        # If params are used (e.g. %s), try matching after parameter substitution isn't
        # possible in mock — just use the key match above.

    async def fetchall(self) -> list[tuple]:
        return self._rows


class _MockConn:
    """Mock connection that yields _MockCursor instances."""

    def __init__(self, results: dict[str, list[tuple]]) -> None:
        self._results = results

    async def select_db(self, db: str) -> None:
        pass

    def cursor(self):
        results = self._results

        @asynccontextmanager
        async def _cm():
            yield _MockCursor(results)

        return _cm()


class _MockPool:
    """Mock pool whose acquire() yields _MockConn instances."""

    def __init__(self, results: dict[str, list[tuple]]) -> None:
        self._results = results

    def acquire(self):
        results = self._results

        @asynccontextmanager
        async def _cm():
            yield _MockConn(results)

        return _cm()

    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


# ---- Test data ----

_SAMPLE_COLUMNS = [
    ("id", "int", None, "NO", "auto_increment", ""),
    ("name", "varchar(100)", None, "YES", "", "user name"),
    ("status", "enum('active','inactive')", "active", "YES", "", ""),
]

_SAMPLE_TABLES = [
    ("users", "user table", 1713000000.0),
    ("orders", "order table", 1713000100.0),
]

_SAMPLE_DATABASES = [("shop",), ("analytics",)]

_SAMPLE_ENUMS = [
    ("status", "users", "enum('active','inactive')"),
]


@pytest.fixture()
def mock_results() -> dict[str, list[tuple]]:
    return {
        "SCHEMATA": _SAMPLE_DATABASES,
        "TABLE_TYPE = 'BASE TABLE'": _SAMPLE_TABLES,
        "COLUMN_COMMENT": _SAMPLE_COLUMNS,  # unique to _GET_COLUMNS
        "STATISTICS": [],
        "REFERENTIAL_CONSTRAINTS": [],  # matches _GET_FOREIGN_KEYS (uses JOIN with rc)
        "TRIGGERS": [],
        "VIEWS": [],
        "DATA_TYPE = 'enum'": _SAMPLE_ENUMS,
    }


@pytest.fixture()
def app_config(monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    monkeypatch.setenv("MYSQL_USER", "test")
    monkeypatch.setenv("MYSQL_PASSWORD", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return AppConfig()


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestParseEnumValues:
    def test_basic(self) -> None:
        assert _parse_enum_values("enum('active','inactive')") == ["active", "inactive"]

    def test_single(self) -> None:
        assert _parse_enum_values("enum('yes')") == ["yes"]

    def test_empty(self) -> None:
        assert _parse_enum_values("varchar(100)") == []

    def test_quoted(self) -> None:
        assert _parse_enum_values("enum('a','b','c')") == ["a", "b", "c"]


class TestTokenize:
    def test_basic(self) -> None:
        assert _tokenize("show me all users") == ["show", "me", "all", "users"]

    def test_with_punctuation(self) -> None:
        assert _tokenize("users, orders and products") == ["users", "orders", "and", "products"]

    def test_empty(self) -> None:
        assert _tokenize("") == []

    def test_chinese(self) -> None:
        tokens = _tokenize("查询 users 表的数据")
        assert "users" in tokens


class TestSchemaManagerLoadAll:
    @pytest.mark.asyncio()
    async def test_load_all(self, mock_results: dict, app_config: AppConfig) -> None:
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        await manager.load_all()

        assert "shop" in manager.cache.databases
        assert "analytics" in manager.cache.databases

        shop = manager.cache.databases["shop"]
        assert "users" in shop.tables
        assert "orders" in shop.tables
        assert len(shop.tables["users"].columns) == 3
        assert shop.tables["users"].columns[0].name == "id"
        assert shop.tables["users"].columns[0].auto_increment is True

    @pytest.mark.asyncio()
    async def test_table_index_rebuilt(self, mock_results: dict, app_config: AppConfig) -> None:
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        await manager.load_all()

        assert "users" in manager.cache.table_index

    @pytest.mark.asyncio()
    async def test_enum_loaded(self, mock_results: dict, app_config: AppConfig) -> None:
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        await manager.load_all()

        shop = manager.cache.databases["shop"]
        assert len(shop.enums) == 1
        assert shop.enums[0].values == ["active", "inactive"]

    @pytest.mark.asyncio()
    async def test_allowed_databases_filter(self, mock_results: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYSQL_USER", "test")
        monkeypatch.setenv("MYSQL_PASSWORD", "test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("ALLOWED_DATABASES", '["shop"]')

        config = AppConfig()
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, config)  # type: ignore[arg-type]
        await manager.load_all()

        assert list(manager.cache.databases.keys()) == ["shop"]


class TestSchemaManagerIncrementalRefresh:
    @pytest.mark.asyncio()
    async def test_detects_new_table(self, mock_results: dict, app_config: AppConfig) -> None:
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        await manager.load_all()

        # Simulate a new table appearing
        mock_results["TABLE_TYPE = 'BASE TABLE'"].append(("products", "products table", 1713000200.0))
        mock_results["COLUMNS"] = [("id", "int", None, "NO", "auto_increment", "")]
        mock_results["STATISTICS"] = []
        mock_results["KEY_COLUMN_USAGE"] = []
        mock_results["TRIGGERS"] = []

        await manager.refresh_incremental()
        shop = manager.cache.databases["shop"]
        assert "products" in shop.tables

    @pytest.mark.asyncio()
    async def test_detects_removed_table(self, mock_results: dict, app_config: AppConfig) -> None:
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        await manager.load_all()

        # Remove orders from mock results
        mock_results["TABLE_TYPE = 'BASE TABLE'"] = [
            ("users", "user table", 1713000000.0),
        ]

        await manager.refresh_incremental()
        shop = manager.cache.databases["shop"]
        assert "orders" not in shop.tables


class TestFindCandidateTables:
    @pytest.mark.asyncio()
    async def test_direct_table_name_match(self, mock_results: dict, app_config: AppConfig) -> None:
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        await manager.load_all()

        candidates = manager.find_candidate_tables("show all users", "shop")
        assert "users" in candidates

    @pytest.mark.asyncio()
    async def test_column_name_match(self, mock_results: dict, app_config: AppConfig) -> None:
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        await manager.load_all()

        candidates = manager.find_candidate_tables("show me the name", "shop")
        assert "users" in candidates

    @pytest.mark.asyncio()
    async def test_comment_match(self, mock_results: dict, app_config: AppConfig) -> None:
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        await manager.load_all()

        candidates = manager.find_candidate_tables("show user data", "shop")
        assert "users" in candidates

    @pytest.mark.asyncio()
    async def test_fk_expansion(self, app_config: AppConfig) -> None:
        """Tables linked via foreign keys should be included."""
        cache = SchemaCache(
            databases={
                "shop": DatabaseSchema(
                    name="shop",
                    tables={
                        "orders": TableSchema(
                            name="orders",
                            columns=[ColumnInfo(name="id", type="int"), ColumnInfo(name="user_id", type="int")],
                            foreign_keys=[
                                ForeignKeyInfo(
                                    name="fk_user",
                                    columns=["user_id"],
                                    ref_table="users",
                                    ref_columns=["id"],
                                )
                            ],
                        ),
                        "users": TableSchema(
                            name="users",
                            columns=[ColumnInfo(name="id", type="int")],
                        ),
                    },
                ),
            },
        )
        pool = MagicMock()
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        manager._cache = cache

        candidates = manager.find_candidate_tables("show all orders", "shop")
        assert "orders" in candidates
        assert "users" in candidates

    @pytest.mark.asyncio()
    async def test_fallback_all_tables(self, mock_results: dict, app_config: AppConfig) -> None:
        pool = _MockPool(mock_results)
        manager = SchemaManager(pool, app_config)  # type: ignore[arg-type]
        await manager.load_all()

        candidates = manager.find_candidate_tables("xyzzy nothing matches", "shop")
        # Fallback returns all tables in the database
        assert "users" in candidates
        assert "orders" in candidates

    def test_nonexistent_database(self) -> None:
        pool = MagicMock()
        manager = SchemaManager(pool, AppConfig.__new__(AppConfig))  # type: ignore[arg-type]
        manager._cache = SchemaCache()
        assert manager.find_candidate_tables("users", "nonexistent") == []
