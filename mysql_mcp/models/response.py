"""Pydantic models for MCP tool responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SQLResult(BaseModel):
    """Query execution result (return_type='result')."""

    sql: str
    database: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)  # type: ignore[type-arg]
    row_count: int = 0
    truncated: bool = False


class SQLResponse(BaseModel):
    """SQL-only response (return_type='sql')."""

    sql: str
    database: str
    explanation: str


class BothResponse(BaseModel):
    """SQL + result response (return_type='both')."""

    sql: str
    database: str
    explanation: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)  # type: ignore[type-arg]
    row_count: int = 0
    truncated: bool = False


class ListDatabasesResponse(BaseModel):
    databases: list[str]


class DescribeSchemaResponse(BaseModel):
    database: str
    tables: dict[str, dict] = Field(default_factory=dict)  # type: ignore[type-arg]
    views: dict[str, dict] = Field(default_factory=dict)  # type: ignore[type-arg]
    enums: list[dict] = Field(default_factory=list)  # type: ignore[type-arg]


class ErrorResponse(BaseModel):
    """Unified error response."""

    error: str
    message: str
    detail: str | None = None
