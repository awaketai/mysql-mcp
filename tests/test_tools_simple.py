"""Tests for list_databases and describe_schema tools."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mysql_mcp.models.schema import (
    ColumnInfo,
    DatabaseSchema,
    SchemaCache,
    TableSchema,
    ViewSchema,
)
from mysql_mcp.tools.describe_schema import describe_schema
from mysql_mcp.tools.list_databases import list_databases


def _make_ctx(lifespan_context: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.lifespan_context = lifespan_context
    return ctx


def _sample_cache() -> SchemaCache:
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
                views={
                    "active_users": ViewSchema(
                        name="active_users",
                        columns=[ColumnInfo(name="id", type="int")],
                        definition="SELECT id FROM users WHERE status='active'",
                    ),
                },
            ),
            "analytics": DatabaseSchema(name="analytics"),
        },
    )


class TestListDatabases:
    @pytest.mark.asyncio()
    async def test_returns_all_databases(self) -> None:
        cache = _sample_cache()
        schema_manager = MagicMock()
        schema_manager.cache = cache
        ctx = _make_ctx({"schema_manager": schema_manager})

        result = await list_databases(ctx)

        assert sorted(result["databases"]) == ["analytics", "shop"]


class TestDescribeSchema:
    @pytest.mark.asyncio()
    async def test_database_overview(self) -> None:
        cache = _sample_cache()
        schema_manager = MagicMock()
        schema_manager.cache = cache
        ctx = _make_ctx({"schema_manager": schema_manager})

        result = await describe_schema(database="shop", ctx=ctx)

        assert result["database"] == "shop"
        assert "users" in result["tables"]
        assert "active_users" in result["views"]
        assert result["tables"]["users"]["columns"] == ["id", "name"]

    @pytest.mark.asyncio()
    async def test_specific_table(self) -> None:
        cache = _sample_cache()
        schema_manager = MagicMock()
        schema_manager.cache = cache
        ctx = _make_ctx({"schema_manager": schema_manager})

        result = await describe_schema(database="shop", table="users", ctx=ctx)

        assert result["database"] == "shop"
        assert "users" in result["tables"]
        assert "columns" in result["tables"]["users"]

    @pytest.mark.asyncio()
    async def test_specific_view(self) -> None:
        cache = _sample_cache()
        schema_manager = MagicMock()
        schema_manager.cache = cache
        ctx = _make_ctx({"schema_manager": schema_manager})

        result = await describe_schema(database="shop", table="active_users", ctx=ctx)

        assert "active_users" in result["views"]

    @pytest.mark.asyncio()
    async def test_nonexistent_database(self) -> None:
        cache = _sample_cache()
        schema_manager = MagicMock()
        schema_manager.cache = cache
        ctx = _make_ctx({"schema_manager": schema_manager})

        result = await describe_schema(database="nonexistent", ctx=ctx)

        assert result["error"] == "not_found"

    @pytest.mark.asyncio()
    async def test_nonexistent_table(self) -> None:
        cache = _sample_cache()
        schema_manager = MagicMock()
        schema_manager.cache = cache
        ctx = _make_ctx({"schema_manager": schema_manager})

        result = await describe_schema(database="shop", table="nonexistent", ctx=ctx)

        assert result["error"] == "not_found"
