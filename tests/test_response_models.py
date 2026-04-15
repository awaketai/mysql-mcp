"""Tests for src.models.response."""

from __future__ import annotations

from src.models.response import (
    BothResponse,
    DescribeSchemaResponse,
    ErrorResponse,
    ListDatabasesResponse,
    SQLResponse,
    SQLResult,
)


class TestSQLResult:
    def test_basic(self) -> None:
        r = SQLResult(
            sql="SELECT 1",
            database="test",
            columns=["1"],
            rows=[[1]],
            row_count=1,
        )
        assert r.sql == "SELECT 1"
        assert r.row_count == 1
        assert r.truncated is False

    def test_empty_result(self) -> None:
        r = SQLResult(sql="SELECT 1", database="test")
        assert r.columns == []
        assert r.rows == []
        assert r.row_count == 0

    def test_truncated(self) -> None:
        r = SQLResult(
            sql="SELECT * FROM t",
            database="test",
            columns=["id"],
            rows=[[1]],
            row_count=1001,
            truncated=True,
        )
        assert r.truncated is True

    def test_model_dump(self) -> None:
        r = SQLResult(sql="SELECT 1", database="test")
        d = r.model_dump()
        assert d["sql"] == "SELECT 1"
        assert d["truncated"] is False


class TestSQLResponse:
    def test_basic(self) -> None:
        r = SQLResponse(
            sql="SELECT id FROM users LIMIT 10",
            database="shop",
            explanation="Query user IDs",
        )
        assert r.explanation == "Query user IDs"


class TestBothResponse:
    def test_basic(self) -> None:
        r = BothResponse(
            sql="SELECT 1",
            database="test",
            explanation="test query",
            columns=["1"],
            rows=[[1]],
            row_count=1,
        )
        assert r.explanation == "test query"
        assert r.rows == [[1]]


class TestListDatabasesResponse:
    def test_basic(self) -> None:
        r = ListDatabasesResponse(databases=["shop", "analytics"])
        assert len(r.databases) == 2

    def test_empty(self) -> None:
        r = ListDatabasesResponse(databases=[])
        assert r.databases == []


class TestDescribeSchemaResponse:
    def test_basic(self) -> None:
        r = DescribeSchemaResponse(
            database="shop",
            tables={"users": {"columns": ["id", "name"]}},
            views={"active_users": {"columns": ["id"]}},
            enums=[{"name": "status", "values": ["active", "inactive"]}],
        )
        assert "users" in r.tables
        assert len(r.enums) == 1


class TestErrorResponse:
    def test_basic(self) -> None:
        r = ErrorResponse(
            error="validation_error",
            message="Only SELECT statements are allowed",
            detail="Got: INSERT INTO users VALUES (1)",
        )
        assert r.error == "validation_error"
        assert r.detail is not None

    def test_without_detail(self) -> None:
        r = ErrorResponse(error="timeout", message="Query timed out after 30s")
        assert r.detail is None
