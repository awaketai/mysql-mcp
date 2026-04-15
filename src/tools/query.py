"""query MCP tool — the core natural-language-to-SQL pipeline."""

from __future__ import annotations

import logging

from fastmcp import Context

from src.db.pool import execute_query
from src.db.schema import SchemaManager
from src.llm.client import LLMClient
from src.llm.prompt import PromptBuilder
from src.llm.validator import AIResultValidator
from src.models.response import (
    BothResponse,
    ErrorResponse,
    SQLResponse,
    SQLResult,
)
from src.security.validator import SQLValidationError, SQLValidator

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


async def query(
    natural_language: str,
    database: str | None = None,
    return_type: str = "result",
    ctx: Context = None,
) -> dict:
    """Convert a natural-language query into SQL and optionally execute it.

    Args:
        natural_language: The user's query in natural language.
        database: Optional target database name.
        return_type: What to return — 'sql', 'result', or 'both'. Defaults to 'result'.
    """
    config = ctx.lifespan_context["config"]
    pool = ctx.lifespan_context["pool"]
    schema_manager: SchemaManager = ctx.lifespan_context["schema_manager"]
    llm_client: LLMClient = ctx.lifespan_context["llm_client"]

    logger.info("Query request: %s (db=%s, type=%s)", natural_language[:100], database, return_type)

    # Step 1: resolve target database
    db_name = _resolve_database(database, natural_language, schema_manager, config)
    if db_name is None:
        logger.warning("Could not resolve database for query: %s", natural_language[:100])
        return ErrorResponse(
            error="database_required",
            message="Could not determine the target database. Please specify one.",
        ).model_dump()

    # Step 2: candidate-table filtering
    prompt_builder = PromptBuilder(schema_manager.cache, config.max_limit)
    candidates = prompt_builder.find_candidate_tables(natural_language, db_name)
    logger.debug("Candidate tables for '%s': %s", db_name, candidates)

    # Step 3–6: generate → validate → execute loop (with retries)
    system_prompt = prompt_builder.build_system_prompt(db_name, candidates)
    validator = SQLValidator()
    last_error: str | None = None

    for attempt in range(_MAX_RETRIES):
        # Step 3: build prompt + call LLM
        try:
            user_prompt = natural_language
            if last_error:
                user_prompt = (
                    f"{natural_language}\n\n"
                    f"Previous attempt failed with: {last_error}\n"
                    "Please fix the SQL."
                )
            raw_sql = await llm_client.generate_sql(system_prompt, user_prompt)
        except Exception as exc:
            logger.exception("LLM generation failed on attempt %d", attempt + 1)
            return ErrorResponse(
                error="llm_error",
                message=f"Failed to generate SQL: {exc}",
            ).model_dump()

        # Step 4: security validation
        try:
            sql = validator.validate(raw_sql, config.max_limit)
        except SQLValidationError as exc:
            last_error = f"SQL validation: {exc.reason}"
            logger.warning("Attempt %d: %s", attempt + 1, last_error)
            continue

        # Step 5: test execution
        try:
            columns, rows = await execute_query(pool, sql, db_name, config.query_timeout)
        except Exception as exc:
            last_error = f"Execution error: {exc}"
            logger.warning("Attempt %d: %s", attempt + 1, last_error)
            continue

        # Step 6: optional AI verification
        # (skipped for now — enabled via config in future phases)

        # Step 7: build response
        truncated = len(rows) >= config.max_limit
        logger.info(
            "Query succeeded: %d rows, truncated=%s, attempt=%d",
            len(rows), truncated, attempt + 1,
        )
        return _build_response(
            return_type=return_type,
            sql=sql,
            database=db_name,
            columns=columns,
            rows=rows,
            truncated=truncated,
            user_input=natural_language,
        )

    # All retries exhausted
    logger.error("All %d retries exhausted for query: %s", _MAX_RETRIES, natural_language[:100])
    return ErrorResponse(
        error="max_retries_exceeded",
        message=f"Failed to generate valid SQL after {_MAX_RETRIES} attempts. Last error: {last_error}",
    ).model_dump()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_database(
    database: str | None,
    user_input: str,
    schema_manager: SchemaManager,
    config: object,
) -> str | None:
    """Resolve the target database from explicit arg, table-index inference, or config default."""
    if database:
        return database

    # Try to infer from table names mentioned in user input
    table_index = schema_manager.cache.table_index
    tokens = user_input.lower().split()
    matched_dbs: set[str] = set()
    for token in tokens:
        # Clean up token
        clean = token.strip(",'\"()[]{};:")
        if clean in table_index:
            matched_dbs.update(table_index[clean])

    if len(matched_dbs) == 1:
        return matched_dbs.pop()

    # Fallback to config default
    return getattr(config, "default_database", None)


def _build_response(
    return_type: str,
    sql: str,
    database: str,
    columns: list[str],
    rows: list[tuple],
    truncated: bool,
    user_input: str,
) -> dict:
    """Construct the appropriate response based on return_type."""
    serialised_rows = [list(r) for r in rows]

    if return_type == "sql":
        return SQLResponse(
            sql=sql,
            database=database,
            explanation=f"Generated SQL for: {user_input}",
        ).model_dump()

    if return_type == "both":
        return BothResponse(
            sql=sql,
            database=database,
            explanation=f"Generated SQL for: {user_input}",
            columns=columns,
            rows=serialised_rows,
            row_count=len(rows),
            truncated=truncated,
        ).model_dump()

    # Default: "result"
    return SQLResult(
        sql=sql,
        database=database,
        columns=columns,
        rows=serialised_rows,
        row_count=len(rows),
        truncated=truncated,
    ).model_dump()
