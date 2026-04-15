"""Tests for mysql_mcp.llm.client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mysql_mcp.config import OpenAIConfig
from mysql_mcp.llm.client import LLMClient, _extract_sql


@pytest.fixture()
def openai_config(monkeypatch: pytest.MonkeyPatch) -> OpenAIConfig:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    return OpenAIConfig()


class TestExtractSQL:
    def test_plain_sql(self) -> None:
        assert _extract_sql("SELECT * FROM users LIMIT 10") == "SELECT * FROM users LIMIT 10"

    def test_markdown_sql_block(self) -> None:
        text = "```sql\nSELECT * FROM users LIMIT 10;\n```"
        assert _extract_sql(text) == "SELECT * FROM users LIMIT 10;"

    def test_markdown_plain_block(self) -> None:
        text = "```\nSELECT 1;\n```"
        assert _extract_sql(text) == "SELECT 1;"

    def test_explanation_before_sql(self) -> None:
        text = "Here is the query:\nSELECT id FROM users LIMIT 5"
        assert _extract_sql(text) == "SELECT id FROM users LIMIT 5"

    def test_multiline_with_explanation(self) -> None:
        text = "Sure, here you go:\nSELECT id, name\nFROM users\nWHERE active = 1\nLIMIT 100"
        result = _extract_sql(text)
        assert result.startswith("SELECT")
        assert "FROM users" in result

    def test_with_cte(self) -> None:
        text = "```sql\nWITH cte AS (SELECT 1) SELECT * FROM cte;\n```"
        assert "WITH" in _extract_sql(text)

    def test_empty(self) -> None:
        assert _extract_sql("") == ""


class TestLLMClientGenerateSQL:
    @pytest.mark.asyncio()
    async def test_calls_openai_and_extracts_sql(self, openai_config: OpenAIConfig) -> None:
        mock_message = MagicMock()
        mock_message.content = "```sql\nSELECT id FROM users LIMIT 10;\n```"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("mysql_mcp.llm.client.AsyncOpenAI") as mock_openai_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client.close = AsyncMock()
            mock_openai_cls.return_value = mock_client

            client = LLMClient(openai_config)
            result = await client.generate_sql("system prompt", "show me users")

        assert result == "SELECT id FROM users LIMIT 10;"

    @pytest.mark.asyncio()
    async def test_temperature_is_zero(self, openai_config: OpenAIConfig) -> None:
        mock_message = MagicMock()
        mock_message.content = "SELECT 1"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message)]

        with patch("mysql_mcp.llm.client.AsyncOpenAI") as mock_openai_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client.close = AsyncMock()
            mock_openai_cls.return_value = mock_client

            client = LLMClient(openai_config)
            await client.generate_sql("sys", "user")

            call_kwargs = mock_client.chat.completions.create.call_args
            assert call_kwargs.kwargs.get("temperature") == 0 or call_kwargs[1].get("temperature") == 0


class TestLLMClientVerifyResult:
    @pytest.mark.asyncio()
    async def test_verify_returns_true_on_yes(self, openai_config: OpenAIConfig) -> None:
        mock_message = MagicMock()
        mock_message.content = "yes"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message)]

        with patch("mysql_mcp.llm.client.AsyncOpenAI") as mock_openai_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client.close = AsyncMock()
            mock_openai_cls.return_value = mock_client

            client = LLMClient(openai_config)
            assert await client.verify_result("show users", "SELECT * FROM users") is True

    @pytest.mark.asyncio()
    async def test_verify_returns_false_on_no(self, openai_config: OpenAIConfig) -> None:
        mock_message = MagicMock()
        mock_message.content = "no"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_message)]

        with patch("mysql_mcp.llm.client.AsyncOpenAI") as mock_openai_cls:
            mock_client = AsyncMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client.close = AsyncMock()
            mock_openai_cls.return_value = mock_client

            client = LLMClient(openai_config)
            assert await client.verify_result("show users", "DELETE FROM users") is False
