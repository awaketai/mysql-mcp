"""describe_schema MCP tool."""

from __future__ import annotations

from fastmcp import Context

from src.models.response import DescribeSchemaResponse, ErrorResponse


async def describe_schema(
    database: str,
    table: str | None = None,
    ctx: Context = None,
) -> dict:
    """Describe the schema of a database or a specific table.

    Args:
        database: Database name.
        table: Optional table name. If omitted, returns an overview of all tables.
    """
    schema_manager = ctx.lifespan_context["schema_manager"]
    db = schema_manager.cache.databases.get(database)

    if db is None:
        return ErrorResponse(
            error="not_found",
            message=f"Database '{database}' not found",
            detail=f"Available databases: {list(schema_manager.cache.databases.keys())}",
        ).model_dump()

    if table is not None:
        tbl = db.tables.get(table)
        if tbl is None:
            view = db.views.get(table)
            if view is None:
                return ErrorResponse(
                    error="not_found",
                    message=f"Table or view '{table}' not found in database '{database}'",
                ).model_dump()
            return DescribeSchemaResponse(
                database=database,
                tables={},
                views={view.name: view.model_dump(exclude={"name"})},
                enums=[],
            ).model_dump()

        return DescribeSchemaResponse(
            database=database,
            tables={tbl.name: tbl.model_dump(exclude={"name"})},
            views={},
            enums=[],
        ).model_dump()

    # No specific table — return overview of all tables and views
    tables_overview: dict[str, dict] = {}
    for name, tbl in db.tables.items():
        tables_overview[name] = {
            "columns": [c.name for c in tbl.columns],
            "comment": tbl.comment,
        }

    views_overview: dict[str, dict] = {}
    for name, view in db.views.items():
        views_overview[name] = {
            "columns": [c.name for c in view.columns],
        }

    return DescribeSchemaResponse(
        database=database,
        tables=tables_overview,
        views=views_overview,
        enums=[e.model_dump() for e in db.enums],
    ).model_dump()
