# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MySQL MCP Server — a Python MCP (Model Context Protocol) server that converts natural language queries into SQL or query results. Single MySQL instance, read-only, powered by OpenAI for SQL generation and validation.

## Specs

All design artifacts live in `specs/`:
- `0001-mysql-mcp-prd.md` — Product requirements (all open questions resolved)
- `0002-mysql-mcp-design.md` — Technical design with code sketches, data models, and SQL queries
- `institutions.md` — Task backlog and decisions log

Read the design doc before implementing. It contains the full Pydantic models, INFORMATION_SCHEMA queries, sqlglot validation logic, two-stage prompt construction, and error handling strategy.

## Architecture

```
mysql_mcp/
├── server.py          # FastMCP instance, lifespan, tool registration
├── config.py          # Pydantic Settings (env vars: MYSQL_*, OPENAI_*)
├── db/
│   ├── pool.py        # aiomysql connection pool (create/close/execute_query)
│   └── schema.py      # SchemaManager — discovery, cache, incremental refresh, candidate-table filtering
├── models/
│   ├── schema.py      # Schema Pydantic models (Column → Table → Database → SchemaCache)
│   └── response.py    # Tool response models (SQLResult / SQLResponse / BothResponse)
├── llm/
│   ├── client.py      # AsyncOpenAI wrapper (generate_sql, verify_result)
│   ├── prompt.py      # PromptBuilder — two-stage table filtering + layered prompt assembly
│   └── validator.py   # AI-assisted SQL/result relevance verification
├── security/
│   └── validator.py   # SQLValidator — sqlglot AST: SELECT-only, forbidden nodes/functions, LIMIT enforcement
└── tools/
    ├── query.py       # Full 7-step pipeline: DB identify → filter → prompt → generate → validate → execute → respond
    ├── list_databases.py
    ├── describe_schema.py
    └── execute_sql.py
```

**Data flow**: FastMCP lifespan yields a shared context dict (`pool`, `schema_manager`, `llm_client`, `config`). Tools access these via `ctx.lifespan_context`.

**Global table index**: `SchemaCache.table_index` maps `table_name → [database_names]` for quick DB resolution from user input.

## Tech Stack

| Library | Role |
|---------|------|
| FastMCP 3.x | MCP server framework (lifespan, `@mcp.tool`, `Context`) |
| aiomysql | Async MySQL driver with connection pooling |
| sqlglot (with `[rs]` extra) | SQL AST parsing for security validation |
| Pydantic 2.x + pydantic-settings | Models and config |
| OpenAI 1.x (AsyncOpenAI) | SQL generation and result verification |

Python 3.11+. MySQL 5.7+. All I/O is async.

## Coding Standards

**Design principles**: SOLID, DRY, YAGNI. Favor composition over inheritance. Don't abstract until the pattern repeats three times.

**Python style**:
- Use Python 3.11+ syntax: `X | None` over `Optional[X]`, `list[str]` over `List[str]`, `type` aliases where appropriate
- Use `async with` for all resource management (connections, pool acquire)
- Prefer `@dataclass(kw_only=True)` or Pydantic models over raw dicts for structured data
- Use `logging` module, never `print()`
- Return typed objects from functions; avoid `Any`
- Use `from __future__ import annotations` only when needed for forward references

**Naming**:
- Modules: `snake_case`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private: `_leading_underscore`

**Error handling**:
- Define custom exceptions per domain (e.g., `SQLValidationError`, `SchemaError`)
- Raise specific exceptions, never bare `Exception`
- Let exceptions propagate to the tool layer, where they're caught and returned as user-facing error messages

**Performance**:
- All DB operations go through the connection pool — never open ad-hoc connections
- Use `SET SESSION max_execution_time` for query timeout enforcement at the MySQL level
- Schema cache lives in memory; incremental refresh only touches changed tables (comparing `information_schema.TABLES.UPDATE_TIME`)
- Prompt construction respects a token budget (default 4000) via the two-stage filter — don't dump full schema into every LLM call

## SQL Security Rules (non-negotiable)

Every SQL statement — whether LLM-generated or user-provided — must pass `SQLValidator.validate()` before execution:
1. sqlglot `parse(sql, read="mysql")` must yield exactly one statement
2. Root node must be `exp.Select`
3. No forbidden AST nodes: `Insert`, `Update`, `Delete`, `Replace`, `Create`, `Alter`, `Drop`, `Truncate`, `Grant`, `Revoke`
4. No forbidden functions: `LOAD_FILE`, `INTO OUTFILE`, `INTO DUMPFILE`
5. Must have `LIMIT` ≤ `max_limit` (default 1000); auto-append if missing
6. Never bypass these checks with `--no-verify` or similar flags

## Configuration

All config via environment variables (Pydantic Settings). Key vars:

| Variable | Required | Default |
|----------|----------|---------|
| `MYSQL_HOST` | Yes | `localhost` |
| `MYSQL_PORT` | Yes | `3306` |
| `MYSQL_USER` | Yes | — |
| `MYSQL_PASSWORD` | Yes | — |
| `OPENAI_API_KEY` | Yes | — |
| `OPENAI_MODEL` | No | `gpt-4o` |
| `OPENAI_BASE_URL` | No | `None` |
| `ALLOWED_DATABASES` | No | `[]` (all) |
| `DEFAULT_DATABASE` | No | `None` |
| `SCHEMA_REFRESH_INTERVAL` | No | `0` (disabled) |
| `QUERY_TIMEOUT` | No | `30` |
| `MAX_LIMIT` | No | `1000` |
| `LOG_LEVEL` | No | `INFO` |

## Commands

```bash
# Run the MCP server (stdio transport)
python -m mysql_mcp

# Install dependencies (once pyproject.toml exists)
pip install -e ".[dev]"

# Run tests
pytest
pytest tests/test_security.py -k "test_rejects_insert"  # single test
```
