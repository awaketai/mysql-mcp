"""MySQL connection pool management via aiomysql."""

from __future__ import annotations

import logging

import aiomysql

from src.config import MySQLConfig

logger = logging.getLogger(__name__)


async def create_pool(config: MySQLConfig) -> aiomysql.Pool:
    """Create an aiomysql connection pool from config."""
    kwargs: dict = {
        "host": config.host,
        "port": config.port,
        "user": config.user,
        "password": config.password,
        "charset": config.charset,
        "minsize": config.pool_min_size,
        "maxsize": config.pool_max_size,
        "pool_recycle": config.pool_recycle,
        "autocommit": True,
    }
    if config.ssl:
        kwargs["ssl"] = {"ssl": True}
    pool = await aiomysql.create_pool(**kwargs)
    logger.info(
        "Connection pool created: %s:%d (min=%d, max=%d, ssl=%s)",
        config.host,
        config.port,
        config.pool_min_size,
        config.pool_max_size,
        config.ssl,
    )
    return pool


async def close_pool(pool: aiomysql.Pool) -> None:
    """Gracefully close all connections in the pool."""
    pool.close()
    await pool.wait_closed()
    logger.info("Connection pool closed")


async def execute_query(
    pool: aiomysql.Pool,
    sql: str,
    database: str | None = None,
    timeout: int = 30,
) -> tuple[list[str], list[tuple]]:
    """Execute a SQL query and return (column_names, rows).

    Sets SESSION max_execution_time for query-level timeout protection.
    Always explicitly selects the target database to avoid context bleed
    from pooled connections.
    """
    async with pool.acquire() as conn:
        if database:
            await conn.select_db(database)
        async with conn.cursor() as cur:
            await cur.execute(
                "SET SESSION max_execution_time = %s", (timeout * 1000,)
            )
            await cur.execute(sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = await cur.fetchall()
            return columns, list(rows)
