"""Tests for mysql_mcp.db.pool."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mysql_mcp.config import MySQLConfig
from mysql_mcp.db.pool import close_pool, create_pool, execute_query


@pytest.fixture()
def mysql_config(monkeypatch: pytest.MonkeyPatch) -> MySQLConfig:
    monkeypatch.setenv("MYSQL_USER", "test")
    monkeypatch.setenv("MYSQL_PASSWORD", "test")
    return MySQLConfig()


class TestCreatePool:
    @pytest.mark.asyncio()
    async def test_creates_pool_with_config(self, mysql_config: MySQLConfig) -> None:
        mock_pool = MagicMock()
        with patch(
            "mysql_mcp.db.pool.aiomysql.create_pool",
            return_value=mock_pool,
            new_callable=AsyncMock,
        ) as mock_create:
            pool = await create_pool(mysql_config)

        assert pool is mock_pool
        mock_create.assert_awaited_once_with(
            host="localhost",
            port=3306,
            user="test",
            password="test",
            charset="utf8mb4",
            minsize=2,
            maxsize=10,
            pool_recycle=3600,
            autocommit=True,
        )


class TestClosePool:
    @pytest.mark.asyncio()
    async def test_closes_pool(self) -> None:
        mock_pool = MagicMock()
        mock_pool.wait_closed = AsyncMock()

        await close_pool(mock_pool)

        mock_pool.close.assert_called_once()
        mock_pool.wait_closed.assert_awaited_once()


def _make_pool_mock(conn: AsyncMock) -> MagicMock:
    """Build a mock pool whose acquire() yields *conn*."""

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_acquire())
    return pool


class TestExecuteQuery:
    @pytest.mark.asyncio()
    async def test_basic_query(self) -> None:
        mock_cursor = AsyncMock()
        mock_cursor.description = [("id",), ("name",)]
        mock_cursor.fetchall = AsyncMock(return_value=[(1, "alice"), (2, "bob")])

        mock_conn = AsyncMock()

        @asynccontextmanager
        async def _cursor():
            yield mock_cursor

        mock_conn.cursor = MagicMock(return_value=_cursor())
        pool = _make_pool_mock(mock_conn)

        columns, rows = await execute_query(pool, "SELECT id, name FROM users")

        assert columns == ["id", "name"]
        assert rows == [(1, "alice"), (2, "bob")]

    @pytest.mark.asyncio()
    async def test_selects_database(self) -> None:
        mock_cursor = AsyncMock()
        mock_cursor.description = [("x",)]
        mock_cursor.fetchall = AsyncMock(return_value=[])

        mock_conn = AsyncMock()
        mock_conn.select_db = AsyncMock()

        @asynccontextmanager
        async def _cursor():
            yield mock_cursor

        mock_conn.cursor = MagicMock(return_value=_cursor())
        pool = _make_pool_mock(mock_conn)

        await execute_query(pool, "SELECT x FROM t", database="shop")

        mock_conn.select_db.assert_awaited_once_with("shop")

    @pytest.mark.asyncio()
    async def test_sets_timeout(self) -> None:
        executed_sqls: list[str] = []

        mock_cursor = AsyncMock()
        mock_cursor.description = [("x",)]
        mock_cursor.fetchall = AsyncMock(return_value=[])
        mock_cursor.execute = AsyncMock(
            side_effect=lambda sql: executed_sqls.append(sql),
        )

        mock_conn = AsyncMock()

        @asynccontextmanager
        async def _cursor():
            yield mock_cursor

        mock_conn.cursor = MagicMock(return_value=_cursor())
        pool = _make_pool_mock(mock_conn)

        await execute_query(pool, "SELECT 1", timeout=60)

        assert "SET SESSION max_execution_time = 60000" in executed_sqls
