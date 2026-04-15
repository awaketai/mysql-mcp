"""FastMCP server — lifespan management and tool registration."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from mysql_mcp.config import AppConfig
from mysql_mcp.db.pool import close_pool, create_pool
from mysql_mcp.db.schema import SchemaManager
from mysql_mcp.llm.client import LLMClient
from mysql_mcp.tools.describe_schema import describe_schema
from mysql_mcp.tools.execute_sql import execute_sql
from mysql_mcp.tools.health_check import health_check
from mysql_mcp.tools.list_databases import list_databases
from mysql_mcp.tools.query import query

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manage service lifecycle: init resources on startup, cleanup on shutdown."""
    config = AppConfig()

    # 1. MySQL connection pool
    pool = await create_pool(config.mysql)

    # 2. Schema cache
    schema_manager = SchemaManager(pool, config)
    await schema_manager.load_all()

    # 3. LLM client
    llm_client = LLMClient(config.openai)

    # 4. Background schema refresh (if configured)
    refresh_task = await schema_manager.start_refresh_if_configured()

    try:
        yield {
            "config": config,
            "pool": pool,
            "schema_manager": schema_manager,
            "llm_client": llm_client,
        }
    finally:
        logger.info("Shutting down MySQL MCP Server...")
        if refresh_task:
            refresh_task.cancel()
        await llm_client.close()
        await close_pool(pool)
        logger.info("Shutdown complete")


mcp = FastMCP("MySQL MCP Server", lifespan=app_lifespan)

# Register tools
mcp.tool(query)
mcp.tool(list_databases)
mcp.tool(describe_schema)
mcp.tool(execute_sql)
mcp.tool(health_check)
