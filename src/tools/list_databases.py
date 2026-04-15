"""list_databases MCP tool."""

from __future__ import annotations

from fastmcp import Context

from src.models.response import ListDatabasesResponse


async def list_databases(ctx: Context) -> dict:
    """List all accessible databases."""
    schema_manager = ctx.lifespan_context["schema_manager"]
    result = ListDatabasesResponse(databases=list(schema_manager.cache.databases.keys()))
    return result.model_dump()
