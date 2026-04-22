"""execute_sql MCP tool."""

from __future__ import annotations

import logging

from fastmcp import Context

from src.config import AppConfig
from src.db.pool import execute_query
from src.db.schema import SchemaManager
from src.models.response import ErrorResponse, SQLResult
from src.security.validator import SQLValidationError, SQLValidator

logger = logging.getLogger(__name__)


async def execute_sql(
    sql: str,
    database: str | None = None,
    ctx: Context = None,
) -> dict:
    """Execute a user-provided SQL statement after security validation.

    Args:
        sql: SQL statement to execute (SELECT only).
        database: Optional target database name.
    """
    config: AppConfig = ctx.lifespan_context["config"]
    pool = ctx.lifespan_context["pool"]
    schema_manager: SchemaManager = ctx.lifespan_context["schema_manager"]

    logger.info("execute_sql: db=%s, sql=%s", database, sql[:100])

    # Resolve database
    db_name = _resolve_database(database, config)

    # Enforce allowed_databases whitelist
    if db_name and not _is_database_allowed(db_name, schema_manager, config):
        return ErrorResponse(
            error="access_denied",
            message=f"Database '{db_name}' is not in the allowed list",
            detail=f"Allowed databases: {list(schema_manager.cache.databases.keys())}",
        ).model_dump()

    # Validate SQL
    validator = SQLValidator()
    try:
        validated_sql = validator.validate(sql, config.max_limit)
    except SQLValidationError as exc:
        logger.warning("SQL validation rejected: %s", exc.reason)
        return ErrorResponse(
            error="validation_error",
            message=exc.reason,
            detail=sql,
        ).model_dump()

    # Execute
    try:
        columns, rows = await execute_query(pool, validated_sql, db_name, config.query_timeout)
    except Exception as exc:
        logger.exception("SQL execution failed: %s", validated_sql[:100])
        return ErrorResponse(
            error="execution_error",
            message=str(exc),
            detail=validated_sql,
        ).model_dump()

    # Check for truncation
    truncated = len(rows) >= config.max_limit
    result = SQLResult(
        sql=validated_sql,
        database=db_name or "",
        columns=columns,
        rows=[list(r) for r in rows],
        row_count=len(rows),
        truncated=truncated,
    )
    return result.model_dump()


def _resolve_database(
    database: str | None,
    config: AppConfig,
) -> str | None:
    """Resolve the target database name."""
    if database:
        return database
    return config.default_database


def _is_database_allowed(
    db_name: str,
    schema_manager: SchemaManager,
    config: AppConfig,
) -> bool:
    """Check whether *db_name* is in the allowed databases."""
    if config.allowed_databases:
        return db_name in config.allowed_databases
    return db_name in schema_manager.cache.databases
