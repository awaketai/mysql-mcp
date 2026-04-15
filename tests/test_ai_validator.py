"""Tests for mysql_mcp.llm.validator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mysql_mcp.llm.validator import AIResultValidator


@pytest.fixture()
def mock_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def validator(mock_client: AsyncMock) -> AIResultValidator:
    return AIResultValidator(mock_client)


class TestVerifySQLRelevance:
    @pytest.mark.asyncio()
    async def test_delegates_to_client(self, validator: AIResultValidator, mock_client: AsyncMock) -> None:
        mock_client.verify_result = AsyncMock(return_value=True)
        result = await validator.verify_sql_relevance("show users", "SELECT * FROM users LIMIT 10")
        assert result is True
        mock_client.verify_result.assert_awaited_once_with("show users", "SELECT * FROM users LIMIT 10")

    @pytest.mark.asyncio()
    async def test_returns_false(self, validator: AIResultValidator, mock_client: AsyncMock) -> None:
        mock_client.verify_result = AsyncMock(return_value=False)
        result = await validator.verify_sql_relevance("show users", "DELETE FROM users")
        assert result is False


class TestVerifyResultQuality:
    @pytest.mark.asyncio()
    async def test_passes_sample_rows(self, validator: AIResultValidator, mock_client: AsyncMock) -> None:
        mock_client.verify_result = AsyncMock(return_value=True)
        rows = [[1, "alice"], [2, "bob"]]
        result = await validator.verify_result_quality("show users", "SELECT * FROM users", rows)
        assert result is True
        mock_client.verify_result.assert_awaited_once_with(
            "show users", "SELECT * FROM users", sample_rows=rows,
        )
