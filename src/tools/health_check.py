"""health_check MCP tool."""

from __future__ import annotations

from fastmcp import Context

from src.models.response import ErrorResponse


async def health_check(ctx: Context) -> dict:
    """Check server health: MySQL connectivity and config completeness."""
    pool = ctx.lifespan_context["pool"]
    config = ctx.lifespan_context["config"]

    # Check MySQL
    mysql_ok = True
    mysql_error: str | None = None
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
    except Exception as exc:
        mysql_ok = False
        mysql_error = str(exc)

    # Check OpenAI config (no actual API call)
    openai_ok = bool(config.openai.api_key)

    healthy = mysql_ok and openai_ok

    result: dict = {
        "status": "healthy" if healthy else "unhealthy",
        "mysql": {"ok": mysql_ok, **({"error": mysql_error} if mysql_error else {})},
        "openai_config": {"ok": openai_ok},
    }

    if not healthy:
        result["error"] = ErrorResponse(
            error="health_check_failed",
            message="One or more health checks failed",
        ).model_dump()

    return result
